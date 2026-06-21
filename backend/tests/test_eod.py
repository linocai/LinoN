"""阶段1 A.5:盘后 EOD 摘要(盈亏%/D几/明日 D4 预警;无 Tushare token 降级)。"""

from datetime import date

import importlib

import pytest

from app.monitor.eod import build_eod_summary, build_eod_summaries

BUY = date(2026, 6, 22)   # 周一 D1


def test_eod_summary_basic_fields():
    s = build_eod_summary(
        code="600000", name="示例", buy_price=100.0, price=108.0,
        buy_date=BUY, today=date(2026, 6, 23),  # D2
    )
    assert s.pnl_pct == 8.0
    assert s.trade_day == 2
    assert "D2" in s.body and "+8.0%" in s.body


def test_eod_tomorrow_d4_warning():
    """D3(06-24)收盘 → 明日 06-25 是 D4 → 标'明日强平'。"""
    s = build_eod_summary(
        code="600000", name="示例", buy_price=100.0, price=100.0,
        buy_date=BUY, today=date(2026, 6, 24),  # D3
    )
    assert s.force_close_tomorrow is True
    assert "明日 D4 强平" in s.body


def test_eod_no_d4_warning_on_d2():
    s = build_eod_summary(
        code="600000", name="x", buy_price=100.0, price=100.0,
        buy_date=BUY, today=date(2026, 6, 23),  # D2 → 明日 D3,非 D4
    )
    assert s.force_close_tomorrow is False
    assert "明日未到强平日" in s.body


def test_fund_check_degrades_without_tushare_token(monkeypatch):
    """无 Tushare token → 资金段降级注明,整条照出不崩。"""
    from app.config import settings as st
    monkeypatch.setattr(st, "TUSHARE_TOKEN", None, raising=False)
    # 重新 import eod 不必要——_fund_check_note 实时读 settings
    s = build_eod_summary(
        code="600000", name="x", buy_price=100.0, price=95.0,
        buy_date=BUY, today=date(2026, 6, 23),
    )
    assert "资金校验:已跳过 token 缺失" in s.body


def test_fund_check_note_with_token(monkeypatch):
    from app.config import settings as st
    monkeypatch.setattr(st, "TUSHARE_TOKEN", "x" * 40, raising=False)
    s = build_eod_summary(
        code="600000", name="x", buy_price=100.0, price=95.0,
        buy_date=BUY, today=date(2026, 6, 23),
    )
    assert "token 在位" in s.body


def test_build_eod_summaries_batch():
    holdings = [
        {"code": "600000", "name": "甲", "buy_price": 100.0, "buy_date": BUY},
        {"code": "603986", "name": "乙", "buy_price": 50.0, "buy_date": BUY},
    ]
    quotes = {"600000": {"price": 110.0}, "603986": {"price": 50.0}}
    out = build_eod_summaries(holdings, quotes, today=date(2026, 6, 23))
    assert len(out) == 2
    assert out[0].pnl_pct == 10.0 and out[1].pnl_pct == 0.0


def test_build_eod_summaries_missing_quote_falls_back():
    holdings = [{"code": "600000", "name": "甲", "buy_price": 100.0, "buy_date": BUY}]
    out = build_eod_summaries(holdings, {}, today=date(2026, 6, 23))
    assert out[0].pnl_pct == 0.0   # 缺价 → 用 buy_price → 0%
