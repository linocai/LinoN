"""阶段1 A.4:硬线升级/重复至确认状态机(时间注入,可控)。"""

from datetime import datetime, timedelta

from app.monitor.escalation import EscalationManager
from app.monitor.hardline import HardlineEvent, KIND_STOP, KIND_TIME

T0 = datetime(2026, 6, 23, 10, 0, 0)


def _ev(kind=KIND_STOP, code="600000"):
    return HardlineEvent(
        code=code, name="示例", kind=kind, title="t", body="b",
        pnl_pct=-6.0, trade_day=2, actionable=True,
    )


def test_first_push_immediate_badge_1():
    esc = EscalationManager(interval_min=15)
    esc.register(_ev(), now=T0)
    due = esc.due_pushes(now=T0)
    assert len(due) == 1
    tr, badge = due[0]
    assert badge == 1
    esc.mark_pushed(tr, now=T0)
    # 立刻再问 → 不到间隔,不推
    assert esc.due_pushes(now=T0) == []


def test_escalation_after_interval_badge_increments():
    esc = EscalationManager(interval_min=15)
    esc.register(_ev(), now=T0)
    tr, badge = esc.due_pushes(now=T0)[0]
    esc.mark_pushed(tr, now=T0)

    # 14 分钟:还不到
    assert esc.due_pushes(now=T0 + timedelta(minutes=14)) == []
    # 15 分钟:升级,badge=2
    due = esc.due_pushes(now=T0 + timedelta(minutes=15))
    assert len(due) == 1 and due[0][1] == 2
    esc.mark_pushed(due[0][0], now=T0 + timedelta(minutes=15))
    # 再 15 分钟:badge=3
    due3 = esc.due_pushes(now=T0 + timedelta(minutes=30))
    assert due3[0][1] == 3


def test_ack_stops_escalation():
    esc = EscalationManager(interval_min=15)
    esc.register(_ev(), now=T0)
    tr, _ = esc.due_pushes(now=T0)[0]
    esc.mark_pushed(tr, now=T0)
    n = esc.ack("600000", "marked_close")
    assert n == 1
    # 1 小时后也不再推
    assert esc.due_pushes(now=T0 + timedelta(hours=1)) == []
    assert esc.active_tracks() == []


def test_ack_dismissed_action():
    esc = EscalationManager(interval_min=15)
    esc.register(_ev(), now=T0)
    assert esc.ack("600000", "dismissed") == 1


def test_ack_by_code_stops_all_kinds():
    """一票同时止损+D4 两条 → 按 code ack 停两条。"""
    esc = EscalationManager(interval_min=15)
    esc.register(_ev(kind=KIND_STOP), now=T0)
    esc.register(_ev(kind=KIND_TIME), now=T0)
    assert len(esc.active_tracks()) == 2
    n = esc.ack("600000", "marked_close")  # 不指定 kind
    assert n == 2 and esc.active_tracks() == []


def test_register_refreshes_unacked_event_text():
    esc = EscalationManager(interval_min=15)
    esc.register(_ev(), now=T0)
    new = _ev()
    new.body = "刷新文案"
    esc.register(new, now=T0 + timedelta(minutes=1))
    tr, _ = esc.due_pushes(now=T0)[0]
    assert tr.event.body == "刷新文案"


def test_suspect_event_not_escalated():
    from app.monitor.hardline import KIND_SUSPECT
    esc = EscalationManager(interval_min=15)
    susp = HardlineEvent(
        code="600000", name="x", kind=KIND_SUSPECT, title="t", body="b",
        pnl_pct=-6.0, trade_day=2, actionable=False, suspect=True,
    )
    esc.register(susp, now=T0)
    assert esc.due_pushes(now=T0) == []
