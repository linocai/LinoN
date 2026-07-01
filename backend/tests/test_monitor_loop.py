"""阶段1 A.3+A.4+A.5 端到端(单 unit 一轮):拉价→判硬线→升级→推送(注入,不联网/不真推)。

driver 用 run_one_tick / run_eod_tick;注入 quotes_fn/two_source_fn/push_fn,
DB 指 tmp。验证:硬线触发推送计数、两源存疑不触发、非交易时段判定、EOD 摘要推送。
"""

from datetime import date, datetime

import pytest

from app.db import store
from app.monitor.escalation import EscalationManager
from app.monitor import loop as loop_mod


class _Q:
    def __init__(self, price, pre_close=99.0, limit_up=109.0, limit_down=89.0):
        self.price = price
        self.pre_close = pre_close
        self.limit_up = limit_up
        self.limit_down = limit_down


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from app.config import settings as st
    p = str(tmp_path / "mon.db")
    monkeypatch.setattr(st, "DB_PATH", p, raising=False)
    store.init_db(p)
    return p


def _seed(db, code="600000", buy_price=100.0, buy_date="2026-06-22"):
    store.open_position(code, "示例", buy_price, 100, "x", buy_date, db_path=db)
    store.upsert_device_token("dev-1", "ios", db_path=db)


def test_tick_triggers_stop_push(db):
    _seed(db)
    esc = EscalationManager(interval_min=15)
    pushes = []

    res = loop_mod.run_one_tick(
        esc=esc, now=datetime(2026, 6, 23, 10, 0, 0),   # D2 交易时段
        quotes_fn=lambda codes: {c: _Q(94.0) for c in codes},   # -6% 触损
        two_source_fn=lambda codes: {c: {"sina": None, "tencent": None} for c in codes},
        push_fn=lambda *a, **k: pushes.append((a, k)),
        db_path=db,
    )
    assert res["holdings"] == 1
    assert len(res["events"]) == 1 and res["events"][0].kind == "stop"
    assert res["pushes"] == 1           # 一票一设备 → 一推
    assert len(pushes) == 1
    # 推送参数带 thread_id/escalation
    args, kw = pushes[0]
    assert kw["thread_id"] == "600000" and kw["badge_escalation"] == 1


def test_two_source_divergence_suspect_no_push(db):
    _seed(db)
    esc = EscalationManager(interval_min=15)
    pushes = []

    # 两源 pre_close 差异巨大(90 vs 99)→ suspect → 不触发硬线
    def two_src(codes):
        return {c: {"sina": _Q(94.0, pre_close=90.0), "tencent": _Q(94.0, pre_close=99.0)} for c in codes}

    res = loop_mod.run_one_tick(
        esc=esc, now=datetime(2026, 6, 23, 10, 0, 0),
        quotes_fn=lambda codes: {c: _Q(94.0, pre_close=90.0) for c in codes},
        two_source_fn=two_src,
        push_fn=lambda *a, **k: pushes.append((a, k)),
        db_path=db,
    )
    # 只产出 suspect 事件,无硬线推送
    assert all(e.kind == "suspect" for e in res["events"])
    assert res["pushes"] == 0 and pushes == []


def test_eod_tick_pushes_summary(db):
    _seed(db)
    pushes = []
    res = loop_mod.run_eod_tick(
        now=datetime(2026, 6, 23, 15, 10, 0),
        quotes_fn=lambda codes: {c: _Q(108.0) for c in codes},
        push_fn=lambda *a, **k: pushes.append((a, k)),
        db_path=db,
    )
    assert len(res["summaries"]) == 1 and res["pushes"] == 1
    # EOD category 普通
    _, kw = pushes[0]
    from app.push.apns import CATEGORY_EOD
    assert kw["category"] == CATEGORY_EOD


def test_no_holdings_no_push(db):
    store.upsert_device_token("dev-1", "ios", db_path=db)   # 有设备无持仓
    esc = EscalationManager(interval_min=15)
    res = loop_mod.run_one_tick(
        esc=esc, now=datetime(2026, 6, 23, 10, 0, 0),
        quotes_fn=lambda codes: {}, two_source_fn=lambda codes: {},
        push_fn=lambda *a, **k: None, db_path=db,
    )
    assert res["holdings"] == 0 and res["pushes"] == 0


# ————————————————————————————————————————————————————————————————————
# 审后修复 #1:一 tick 内每源只拉一次(price 与一致性校验复用同一对结果)
# ————————————————————————————————————————————————————————————————————

def test_tick_pulls_each_source_once(db):
    """不注入 quotes_fn → price 从 two_source_fn 派生,两源各只拉一次。

    断言:two_source_fn 整 tick 只被调一次;price/suspect 行为与原先一致
    (优先 sina;两源都齐才比一致性)。
    """
    _seed(db)
    esc = EscalationManager(interval_min=15)
    pushes = []
    calls = {"two_src": 0}

    def two_src(codes):
        calls["two_src"] += 1
        # sina 现价 94(-6% 触损),tencent 一致 → 不 suspect
        return {c: {"sina": _Q(94.0, pre_close=99.0),
                    "tencent": _Q(94.1, pre_close=99.0)} for c in codes}

    res = loop_mod.run_one_tick(
        esc=esc, now=datetime(2026, 6, 23, 10, 0, 0),   # D2
        two_source_fn=two_src,
        push_fn=lambda *a, **k: pushes.append((a, k)),
        db_path=db,
    )
    # two_source_fn 整 tick 只调一次(每源各拉一次的唯一拉价口)
    assert calls["two_src"] == 1
    # price 从两源派生(优先 sina 的 94 → -6% 触损);行为与原先一致
    assert len(res["events"]) == 1 and res["events"][0].kind == "stop"
    assert res["pushes"] == 1 and len(pushes) == 1


def test_tick_suspect_reuses_same_pull(db):
    """两源派生时,一致性校验复用同一对结果:pre_close 分歧 → suspect 不触发硬线。"""
    _seed(db)
    esc = EscalationManager(interval_min=15)
    pushes = []
    calls = {"two_src": 0}

    def two_src(codes):
        calls["two_src"] += 1
        return {c: {"sina": _Q(94.0, pre_close=90.0),
                    "tencent": _Q(94.0, pre_close=99.0)} for c in codes}

    res = loop_mod.run_one_tick(
        esc=esc, now=datetime(2026, 6, 23, 10, 0, 0),
        two_source_fn=two_src,
        push_fn=lambda *a, **k: pushes.append((a, k)),
        db_path=db,
    )
    assert calls["two_src"] == 1
    assert all(e.kind == "suspect" for e in res["events"])
    assert res["pushes"] == 0 and pushes == []


# ————————————————————————————————————————————————————————————————————
# 审后修复 #2:D4 后重启不丢 time 升级(启动重建 + 每 tick ensure + 幂等)
# ————————————————————————————————————————————————————————————————————

def test_rebuild_time_escalation_on_restart(db):
    """模拟重启:空 escalation + 一只 count≥4(D5)未平持仓 → 启动重建 → 有 active time 升级且会 due_push。"""
    # buy 2026-06-15 → 到 2026-06-22 count==5(过 D4,classify 不再产 time 事件)
    _seed(db, code="600000", buy_price=100.0, buy_date="2026-06-15")
    esc = EscalationManager(interval_min=15)   # 全新空状态 = 重启后
    assert esc.has_track("600000", "time") is False

    n = loop_mod.rebuild_time_escalations(esc, now=datetime(2026, 6, 22, 9, 30), db_path=db)
    assert n == 1
    assert esc.has_track("600000", "time") is True
    # 该 time 升级 active 且会 due_push(badge 从 1 起)
    due = esc.due_pushes(now=datetime(2026, 6, 22, 9, 30))
    assert len(due) == 1 and due[0][1] == 1
    assert due[0][0].event.kind == "time"


def test_tick_ensures_time_escalation_for_overdue(db):
    """count≥4 在持仓即便价格线未触发,每 tick 也 ensure 一条 time 升级并推送。"""
    _seed(db, code="600000", buy_price=100.0, buy_date="2026-06-15")   # D5
    esc = EscalationManager(interval_min=15)
    pushes = []

    res = loop_mod.run_one_tick(
        esc=esc, now=datetime(2026, 6, 22, 10, 0, 0),
        # 现价 100(0% 不触价格线)→ 仅靠 ensure 产 time 升级
        two_source_fn=lambda codes: {c: {"sina": _Q(100.0, pre_close=99.0), "tencent": None} for c in codes},
        push_fn=lambda *a, **k: pushes.append((a, k)),
        db_path=db,
    )
    # 无价格线事件,但 ensure 出 time 升级 → 推 1 条
    assert res["pushes"] == 1 and len(pushes) == 1
    _, kw = pushes[0]
    assert kw["custom"]["kind"] == "time" and kw["badge_escalation"] == 1
    assert esc.has_track("600000", "time") is True


def test_ensure_time_escalation_idempotent_no_badge_reset(db):
    """已有 time 升级时重跑(重建/再 tick)不重置 badge/计数(幂等)。"""
    _seed(db, code="600000", buy_price=100.0, buy_date="2026-06-15")   # D5
    esc = EscalationManager(interval_min=15)
    now0 = datetime(2026, 6, 22, 9, 30)

    # 首次重建 → 新建 + 推一次(badge=1)
    assert loop_mod.rebuild_time_escalations(esc, now=now0, db_path=db) == 1
    due = esc.due_pushes(now=now0)
    esc.mark_pushed(due[0][0], now=now0)   # push_count → 1

    # 15min 后再推一次 → badge=2
    now1 = now0.replace(minute=45)
    due = esc.due_pushes(now=now1)
    assert len(due) == 1 and due[0][1] == 2
    esc.mark_pushed(due[0][0], now=now1)   # push_count → 2

    # 再次重建/ensure(模拟又一次重启或下一 tick)→ 已存在,不重置
    assert loop_mod.rebuild_time_escalations(esc, now=now1, db_path=db) == 0
    # badge 没被打回 1:此刻未到下一 interval → 无 due;下一 interval 应是 3 不是 1
    now2 = now1.replace(hour=10, minute=5)   # 距上次 push 已 >15min
    due = esc.due_pushes(now=now2)
    assert len(due) == 1 and due[0][1] == 3   # 计数延续(2→3),证明未被重置


def test_ensure_time_escalation_stops_after_ack(db):
    """ack 后该 code 的 time 升级停;重跑 ensure 不复活(has_track 含已 ack)。"""
    _seed(db, code="600000", buy_price=100.0, buy_date="2026-06-15")   # D5
    esc = EscalationManager(interval_min=15)
    now0 = datetime(2026, 6, 22, 9, 30)

    loop_mod.rebuild_time_escalations(esc, now=now0, db_path=db)
    assert esc.ack("600000", "marked_close") == 1   # 用户处理
    # ack 后无 due
    assert esc.due_pushes(now=now0.replace(hour=11)) == []
    # 再 ensure(下一 tick)不复活
    assert loop_mod.rebuild_time_escalations(esc, now=now0.replace(hour=11), db_path=db) == 0
    assert esc.due_pushes(now=now0.replace(hour=11)) == []


def test_no_time_escalation_before_d4(db):
    """count<4(D3)不 ensure time 升级(不误产)。"""
    _seed(db, code="600000", buy_price=100.0, buy_date="2026-06-17")   # 到 06-22 count==3
    esc = EscalationManager(interval_min=15)
    assert loop_mod.rebuild_time_escalations(esc, now=datetime(2026, 6, 22, 9, 30), db_path=db) == 0
    assert esc.has_track("600000", "time") is False


def test_trading_time_helpers():
    # 2026-06-23 周二交易日 10:00 在交易段;20:00 不在
    assert loop_mod._is_trading_now(datetime(2026, 6, 23, 10, 0)) is True
    assert loop_mod._is_trading_now(datetime(2026, 6, 23, 20, 0)) is False
    # 周六 06-27 非交易日
    assert loop_mod._is_trading_now(datetime(2026, 6, 27, 10, 0)) is False
    # 收盘后判定
    assert loop_mod._is_after_close(datetime(2026, 6, 23, 15, 10)) is True
    assert loop_mod._is_after_close(datetime(2026, 6, 23, 14, 0)) is False


# —— D2:候选刷新 tick(EOD 后落表,注入假 pipeline 免联网)————————————

def test_candidate_window_helper():
    # 15:35 后才刷新候选(早于 EOD 推送 15:05)
    assert loop_mod._is_after_candidate_window(datetime(2026, 6, 23, 15, 40)) is True
    assert loop_mod._is_after_candidate_window(datetime(2026, 6, 23, 15, 10)) is False
    assert loop_mod._is_after_candidate_window(datetime(2026, 6, 27, 16, 0)) is False  # 周六


def test_run_candidate_refresh_upserts(db):
    """注入假 pipeline → run_candidate_refresh 落表一次。"""
    rows = [{
        "rank": 1, "name": "兆易创新", "code": "603986", "sector": "半导体",
        "tag": "放量突破", "price": 100.0, "chg": "+5.00%", "volMultiple": "2.8x",
        "volPct": 90, "flow": "+1.20亿", "turnover": "4.6%", "warn": None,
    }]
    res = loop_mod.run_candidate_refresh(
        now=datetime(2026, 6, 23, 15, 40),
        pipeline_fn=lambda basis: (rows, False, "ok", "2026-06-23"),
        db_path=db,
    )
    assert res["count"] == 1 and res["degraded"] is False
    cached = store.list_candidates("2026-06-23", db_path=db)
    assert len(cached) == 1 and cached[0]["code"] == "603986"


def test_run_candidate_refresh_degraded_safe(db):
    """pipeline degraded → 落空表,不崩。"""
    res = loop_mod.run_candidate_refresh(
        now=datetime(2026, 6, 23, 15, 40),
        pipeline_fn=lambda basis: ([], True, "token 缺失", "2026-06-23"),
        db_path=db,
    )
    assert res["count"] == 0 and res["degraded"] is True


def test_run_candidate_refresh_exception_safe(db):
    """pipeline 抛异常被吞,不掀翻。"""
    def _boom(basis):
        raise RuntimeError("network down")
    res = loop_mod.run_candidate_refresh(now=datetime(2026, 6, 23, 15, 40),
                                         pipeline_fn=_boom, db_path=db)
    assert res["count"] == 0 and res["degraded"] is True


# —— F3:候选回测回填(EOD 候选刷新之后,注入假 backfill_fn 免联网)——————————

def test_run_candidate_backfill_calls_injected_fn(db):
    captured = {}

    def _fake_backfill(*, now, db_path=None):
        captured["now"] = now
        captured["db_path"] = db_path
        return {"filled": 2, "skipped": 0, "entries_scanned": 2}

    res = loop_mod.run_candidate_backfill(
        now=datetime(2026, 6, 26, 15, 40), backfill_fn=_fake_backfill, db_path=db,
    )
    assert res["filled"] == 2
    assert captured["now"] == datetime(2026, 6, 26, 15, 40)
    assert captured["db_path"] == db


def test_run_candidate_backfill_exception_safe(db):
    """回填异常被吞,不掀翻轮询。"""
    def _boom(*, now, db_path=None):
        raise RuntimeError("db locked")
    res = loop_mod.run_candidate_backfill(
        now=datetime(2026, 6, 26, 15, 40), backfill_fn=_boom, db_path=db,
    )
    assert res == {"filled": 0, "skipped": 0, "entries_scanned": 0}


def test_run_candidate_backfill_default_fn_wires_to_backtest_module(db, monkeypatch):
    """默认 backfill_fn 应指向 app.screen.backtest.run_backfill(未注入时)。"""
    from app.screen import backtest as backtest_mod

    called = {}

    def _fake_run_backfill(now=None, *, daily_all_fn=None, db_path=None):
        called["now"] = now
        called["db_path"] = db_path
        return {"filled": 0, "skipped": 0, "entries_scanned": 0}

    monkeypatch.setattr(backtest_mod, "run_backfill", _fake_run_backfill)
    res = loop_mod.run_candidate_backfill(now=datetime(2026, 6, 26, 15, 40), db_path=db)
    assert res["entries_scanned"] == 0
    assert called["now"] == datetime(2026, 6, 26, 15, 40)
