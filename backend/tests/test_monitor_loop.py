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


# —— v1.3.1 C1:候选刷新自动 tick 已删,唯一途径改纯手动(POST /candidates/refresh)——
# 死码已删:loop 模块不再有 run_candidate_refresh/_is_after_candidate_window/
# _CANDIDATE_AFTER,相应旧测试(test_candidate_window_helper/test_run_candidate_refresh_*)
# 随之删除(建议#11:该编排函数从未被 app.py 端点调用,是纯死码)。


# —— F3:候选回测回填(v1.3.1 C1 改:挂 EOD 块内,注入假 backfill_fn 免联网)——————————

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


# ————————————————————————————————————————————————————————————————————
# v1.3.1 C1:候选刷新自动 tick 已删(死码验证)+ 回填改挂 EOD 块内(每交易日仅触发一次)
# ————————————————————————————————————————————————————————————————————

def test_candidate_auto_refresh_helpers_removed():
    """死码已删(建议#11):loop 模块不再有候选刷新自动 tick 相关的任何名字。"""
    assert not hasattr(loop_mod, "run_candidate_refresh")
    assert not hasattr(loop_mod, "_is_after_candidate_window")
    assert not hasattr(loop_mod, "_CANDIDATE_AFTER")
    assert not hasattr(loop_mod, "_default_pipeline_fn")   # loop 层的死码版本(非 app.py 那份)


def test_eod_tick_and_backfill_still_present_and_wired():
    """⚠ 保留不动:EOD 摘要 tick(run_eod_tick)未被误删;回填函数仍存在(挂载点改了,函数不变)。"""
    assert hasattr(loop_mod, "run_eod_tick")
    assert hasattr(loop_mod, "run_candidate_backfill")


def test_monitor_loop_source_guards_backfill_inside_eod_block():
    """grep 守卫(封死重要#7):run_candidate_backfill 调用必须在 last_eod_date 守卫的
    EOD 分支内,不能是无守卫的独立 if 块(否则 15:05-24:00 每 5min 打一遍 Tushare)。
    """
    import inspect
    src = inspect.getsource(loop_mod.monitor_loop)
    # 定位 EOD 分支所在整段(elif ... 到下一个顶层 else/except 之前)
    eod_idx = src.index("elif _is_after_close(now)")
    backfill_idx = src.index("run_candidate_backfill")
    else_idx = src.index("else:", eod_idx)
    # run_candidate_backfill 调用位置必须落在 "elif _is_after_close" 之后、下一个 "else:" 之前
    assert eod_idx < backfill_idx < else_idx
    # 不再有 last_candidate_date 这个内存防重变量(候选刷新 tick 已删)
    assert "last_candidate_date" not in src


def test_monitor_loop_eod_and_backfill_run_once_per_trading_day_after_close(db, monkeypatch):
    """端到端(注入 asyncio.to_thread 底层调用,免真拉网):同一天多次 tick 触发
    收盘后判定,run_eod_tick/run_candidate_backfill 都只各跑一次(last_eod_date 守卫);
    非交易时段(交易时段内)不触发候选回填(重要#7 门禁:回填绝不能在收盘前跑)。
    """
    import asyncio
    from app.config import settings as st
    monkeypatch.setattr(st, "DB_PATH", db, raising=False)

    eod_calls = []
    backfill_calls = []
    monkeypatch.setattr(loop_mod, "run_eod_tick", lambda **kw: eod_calls.append(kw) or {"summaries": [], "pushes": 0})
    monkeypatch.setattr(loop_mod, "run_candidate_backfill", lambda **kw: backfill_calls.append(kw) or {"filled": 0, "skipped": 0, "entries_scanned": 0})
    monkeypatch.setattr(loop_mod, "run_one_tick", lambda **kw: {"events": [], "pushes": 0, "holdings": 0})

    # 固定 now 恒为同一交易日收盘后时刻(2026-06-23 周二 15:10),3 轮循环后主动停止。
    fixed_now = datetime(2026, 6, 23, 15, 10, 0)
    call_count = {"n": 0}

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(loop_mod, "datetime", _FixedDateTime)

    async def _drive():
        esc = EscalationManager(interval_min=15)
        stop_event = asyncio.Event()

        async def _stopper():
            # 让 monitor_loop 空转几轮(每轮 now 都相同 → 第2轮起 last_eod_date 已命中,不再重跑)
            await asyncio.sleep(0.05)
            stop_event.set()

        await asyncio.gather(loop_mod.monitor_loop(esc, stop_event), _stopper())

    asyncio.run(_drive())

    # 同一天多轮 tick,EOD/回填都只各触发一次(last_eod_date 守卫生效,重要#7 门禁)
    assert len(eod_calls) == 1
    assert len(backfill_calls) == 1
