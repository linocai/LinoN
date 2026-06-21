"""Phase 0.5 交易日历:D1–D4 计数、仅 D4 强平、跨周末/节假日按交易日计、原语。

锁定语义:count_holding_trade_days 闭区间 [buy, today] 交易日数,买入日=1;
         should_force_close ⟺ count==4。
"""

from datetime import date, time

from app.calendar import (
    count_holding_trade_days,
    is_trading_day,
    next_trading_day,
    prev_trading_day,
    should_force_close,
    trading_window,
)


# —— 连续交易日 D1–D4(2026-06-22 周一买入,Mon–Thu 连续交易)——

def test_consecutive_d1_d4_counts():
    buy = "2026-06-22"  # Mon
    assert count_holding_trade_days(buy, "2026-06-22") == 1  # D1 Mon
    assert count_holding_trade_days(buy, "2026-06-23") == 2  # D2 Tue
    assert count_holding_trade_days(buy, "2026-06-24") == 3  # D3 Wed
    assert count_holding_trade_days(buy, "2026-06-25") == 4  # D4 Thu


def test_force_close_only_at_d4_consecutive():
    buy = "2026-06-22"
    assert should_force_close(buy, "2026-06-22") is False  # D1
    assert should_force_close(buy, "2026-06-23") is False  # D2
    assert should_force_close(buy, "2026-06-24") is False  # D3
    assert should_force_close(buy, "2026-06-25") is True   # D4
    assert should_force_close(buy, "2026-06-26") is False  # D5(过了不再触发)


# —— 跨周末:2026-06-25 周四买入,周末不计 ——

def test_count_across_weekend():
    buy = "2026-06-25"  # Thu
    assert count_holding_trade_days(buy, "2026-06-26") == 2  # D2 Fri
    # 周末不增
    assert count_holding_trade_days(buy, "2026-06-27") == 2  # Sat
    assert count_holding_trade_days(buy, "2026-06-28") == 2  # Sun
    assert count_holding_trade_days(buy, "2026-06-29") == 3  # D3 Mon
    assert count_holding_trade_days(buy, "2026-06-30") == 4  # D4 Tue
    assert should_force_close(buy, "2026-06-30") is True


# —— 跨国庆:2026-09-29 周二买入,国庆 10/1–10/7 休 ——

def test_count_across_national_holiday():
    buy = "2026-09-29"  # Tue
    assert count_holding_trade_days(buy, "2026-09-30") == 2   # D2 Wed
    # 国庆休市,计数冻结
    assert count_holding_trade_days(buy, "2026-10-01") == 2
    assert count_holding_trade_days(buy, "2026-10-07") == 2
    # 节后首个交易日 10-08(Thu)= D3
    assert is_trading_day("2026-10-08") is True
    assert count_holding_trade_days(buy, "2026-10-08") == 3   # D3
    assert count_holding_trade_days(buy, "2026-10-09") == 4   # D4 Fri
    assert should_force_close(buy, "2026-10-09") is True
    assert should_force_close(buy, "2026-10-08") is False


# —— 异常输入:today 早于 buy → 0 ——

def test_today_before_buy():
    assert count_holding_trade_days("2026-06-25", "2026-06-22") == 0
    assert should_force_close("2026-06-25", "2026-06-22") is False


# —— 原语 ——

def test_is_trading_day():
    assert is_trading_day("2026-06-18") is True    # Thu 交易
    assert is_trading_day("2026-06-19") is False   # 端午
    assert is_trading_day("2026-06-20") is False   # Sat
    assert is_trading_day("2026-06-21") is False   # Sun + 端午
    assert is_trading_day("2026-06-22") is True    # Mon 交易
    # 调休补班周末:股市仍休
    assert is_trading_day("2026-09-20") is False   # 国庆补班周日,市场休
    # 春节
    assert is_trading_day("2026-02-17") is False


def test_next_prev_trading_day_skip_holiday():
    # 端午+周末后,06-18 的下一个交易日是 06-22
    assert next_trading_day("2026-06-18") == date(2026, 6, 22)
    assert prev_trading_day("2026-06-22") == date(2026, 6, 18)
    # 国庆后:09-30 下一个交易日是 10-08(节中全休)
    assert next_trading_day("2026-09-30") == date(2026, 10, 8)
    assert prev_trading_day("2026-10-08") == date(2026, 9, 30)


def test_next_prev_exclusive_of_self():
    """严格在之后/之前,不含自身。"""
    assert next_trading_day("2026-06-22") == date(2026, 6, 23)
    assert prev_trading_day("2026-06-23") == date(2026, 6, 22)


def test_trading_window_two_segments():
    win = trading_window("2026-06-22")
    assert win == [(time(9, 30), time(11, 30)), (time(13, 0), time(15, 0))]
    assert trading_window("2026-06-21") is None   # 非交易日


def test_2025_static_table_spotcheck():
    """2025 静态表抽查(春节/国庆/端午)。"""
    assert is_trading_day("2025-01-01") is False   # 元旦
    assert is_trading_day("2025-01-28") is False   # 春节首日
    assert is_trading_day("2025-02-05") is True    # 春节后首个交易日(Wed)
    assert is_trading_day("2025-10-08") is False   # 国庆末日
    assert is_trading_day("2025-10-09") is True    # 国庆后(Thu)
