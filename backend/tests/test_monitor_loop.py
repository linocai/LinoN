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


def test_trading_time_helpers():
    # 2026-06-23 周二交易日 10:00 在交易段;20:00 不在
    assert loop_mod._is_trading_now(datetime(2026, 6, 23, 10, 0)) is True
    assert loop_mod._is_trading_now(datetime(2026, 6, 23, 20, 0)) is False
    # 周六 06-27 非交易日
    assert loop_mod._is_trading_now(datetime(2026, 6, 27, 10, 0)) is False
    # 收盘后判定
    assert loop_mod._is_after_close(datetime(2026, 6, 23, 15, 10)) is True
    assert loop_mod._is_after_close(datetime(2026, 6, 23, 14, 0)) is False
