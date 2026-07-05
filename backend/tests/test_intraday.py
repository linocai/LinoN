"""Phase A 盘中数据层(纯函数)单测,plan v1.4 §4 Phase A 验收清单逐条覆盖。

全部传假 Quote/数值,不联网、不拉价、不拉 daily。
"""

from datetime import datetime
from typing import Optional

from app.data.intraday import (
    build_intraday_snapshot,
    elapsed_trading_minutes,
    intraday_vol_ratio,
    vwap_of,
    _is_intraday_window,
)
from app.data.realtime import Quote

_TRADING_DATE = "2026-07-06"   # 周一,静态表内交易日
_NON_TRADING_DATE = "2026-07-04"  # 周六


def _dt(date_str: str, hh: int, mm: int) -> datetime:
    return datetime.strptime(f"{date_str} {hh:02d}:{mm:02d}", "%Y-%m-%d %H:%M")


def _make_quote(
    price: float,
    volume: float,
    *,
    pre_close: float = 10.0,
    open_: float = 10.0,
    amount: Optional[float] = None,
) -> Quote:
    """构造真实比例的假 Quote:amount ≈ price × volume × 100(元)。

    致命#1 回归门:若 vwap_of 误写 amount/volume(少除 100),用这组真实
    比例数据算出的 vwap 会离谱大 100 倍,is_above_vwap 判定会翻转出错,
    从而被断言抓出。
    """
    if amount is None:
        amount = price * volume * 100.0
    return Quote(
        code="000001",
        name="测试股",
        price=price,
        pre_close=pre_close,
        open=open_,
        high=max(price, open_),
        low=min(price, open_),
        limit_up=round(pre_close * 1.1, 2),
        limit_down=round(pre_close * 0.9, 2),
        volume=volume,
        amount=amount,
        ts="2026-07-06 10:30:00",
        source="sina",
    )


# —— _is_intraday_window ————————————————————————————————————————————

def test_is_intraday_window_true_at_noon_break():
    """午休 12:00 仍算盘中(明定死行为,禁复用 loop._is_trading_now)。"""
    assert _is_intraday_window(_dt(_TRADING_DATE, 12, 0)) is True


def test_is_intraday_window_true_at_open_and_before_close():
    assert _is_intraday_window(_dt(_TRADING_DATE, 9, 30)) is True
    assert _is_intraday_window(_dt(_TRADING_DATE, 14, 59)) is True


def test_is_intraday_window_false_before_open():
    assert _is_intraday_window(_dt(_TRADING_DATE, 9, 20)) is False


def test_is_intraday_window_false_after_close():
    assert _is_intraday_window(_dt(_TRADING_DATE, 15, 1)) is False
    assert _is_intraday_window(_dt(_TRADING_DATE, 15, 0)) is False  # 边界:< 15:00 才算


def test_is_intraday_window_false_on_non_trading_day():
    assert _is_intraday_window(_dt(_NON_TRADING_DATE, 10, 0)) is False


# —— elapsed_trading_minutes ——————————————————————————————————————————

def test_elapsed_minutes_before_open_is_zero():
    assert elapsed_trading_minutes(_dt(_TRADING_DATE, 9, 0)) == 0


def test_elapsed_minutes_morning_partial():
    assert elapsed_trading_minutes(_dt(_TRADING_DATE, 10, 30)) == 60


def test_elapsed_minutes_across_noon_break_stays_120():
    """跨午休:12:00/12:30 均定格 120(用上午累计量折算)。"""
    assert elapsed_trading_minutes(_dt(_TRADING_DATE, 12, 0)) == 120
    assert elapsed_trading_minutes(_dt(_TRADING_DATE, 12, 30)) == 120


def test_elapsed_minutes_afternoon():
    assert elapsed_trading_minutes(_dt(_TRADING_DATE, 13, 30)) == 150  # 120+30
    assert elapsed_trading_minutes(_dt(_TRADING_DATE, 14, 59)) == 239


def test_elapsed_minutes_closing_edge_is_full_day():
    assert elapsed_trading_minutes(_dt(_TRADING_DATE, 15, 0)) == 240
    assert elapsed_trading_minutes(_dt(_TRADING_DATE, 20, 0)) == 240


# —— intraday_vol_ratio ————————————————————————————————————————————

def test_vol_ratio_early_below_60min():
    ratio, note = intraday_vol_ratio(current_vol=1000, prev5_avg_vol=2000, elapsed_min=59)
    assert ratio is None
    assert note == "early"


def test_vol_ratio_ok_normal_case():
    # elapsed=120,当日量=120000手,折算全天=120000/120*240=240000,前5日均量=200000
    # ratio = 240000/200000 = 1.2
    ratio, note = intraday_vol_ratio(current_vol=120000, prev5_avg_vol=200000, elapsed_min=120)
    assert ratio == 1.2
    assert note == "ok"


def test_vol_ratio_no_base_when_prev5_zero_or_negative():
    ratio, note = intraday_vol_ratio(current_vol=1000, prev5_avg_vol=0, elapsed_min=120)
    assert ratio is None
    assert note == "no_base"
    ratio2, note2 = intraday_vol_ratio(current_vol=1000, prev5_avg_vol=-5, elapsed_min=120)
    assert ratio2 is None
    assert note2 == "no_base"


def test_vol_ratio_closed_edge_at_240():
    ratio, note = intraday_vol_ratio(current_vol=200000, prev5_avg_vol=200000, elapsed_min=240)
    assert ratio == 1.0
    assert note == "closed"


# —— vwap_of(致命#1 回归门,真实比例假 Quote)—————————————————————————

def test_vwap_of_price_above_vwap_true():
    # amount = price(11)*volume(1000)*100 = 1,100,000;vwap = amount/(vol*100) = 11.0
    # price(11) 高于均价 vwap 时 is_above_vwap 应为 True——反之若函数误写
    # amount/volume(少除100),算出 vwap=1100(元/手误当元/股),price(11)<<1100,
    # is_above_vwap 会被误判 False,本测试即可抓出。
    q = _make_quote(price=11.0, volume=1000, pre_close=10.0, amount=11.0 * 1000 * 100 * 0.9)
    # amount 略小于均匀分布(0.9倍)使均价 < price,确保站上 vwap
    vwap, is_above = vwap_of(q)
    assert vwap is not None
    assert vwap < 11.0  # 均价应在个位数量级(元/股),不是四位数
    assert is_above is True


def test_vwap_of_price_below_vwap_false():
    q = _make_quote(price=9.0, volume=1000, pre_close=10.0, amount=9.0 * 1000 * 100 * 1.2)
    vwap, is_above = vwap_of(q)
    assert vwap is not None
    assert vwap > 9.0
    assert is_above is False


def test_vwap_of_zero_volume_degrades_to_none():
    q = _make_quote(price=10.0, volume=0, amount=0)
    vwap, is_above = vwap_of(q)
    assert vwap is None
    assert is_above is None


def test_vwap_of_none_quote_degrades_to_none():
    vwap, is_above = vwap_of(None)
    assert vwap is None
    assert is_above is None


# —— build_intraday_snapshot ——————————————————————————————————————————

def test_snapshot_non_trading_all_null():
    snap = build_intraday_snapshot(
        quote=None, prev5_avg_vol=100000,
        now=_dt(_NON_TRADING_DATE, 10, 0), is_trading=False,
    )
    assert snap["is_trading"] is False
    assert snap["price"] is None
    assert snap["chg_pct"] is None
    assert snap["open_chg_pct"] is None
    assert snap["vwap"] is None
    assert snap["is_above_vwap"] is None
    assert snap["intraday_vol_ratio"] is None
    assert snap["vol_note"] == "non_trading"
    assert snap["asof"] == ""


def test_snapshot_quote_none_when_trading_all_null_no_base():
    snap = build_intraday_snapshot(
        quote=None, prev5_avg_vol=100000,
        now=_dt(_TRADING_DATE, 10, 30), is_trading=True,
    )
    assert snap["is_trading"] is True
    assert snap["price"] is None
    assert snap["vol_note"] == "no_base"


def test_snapshot_normal_case_fields_computed():
    q = _make_quote(price=11.0, volume=120000, pre_close=10.0, open_=10.5)
    snap = build_intraday_snapshot(
        quote=q, prev5_avg_vol=200000,
        now=_dt(_TRADING_DATE, 11, 30), is_trading=True,
    )
    assert snap["is_trading"] is True
    assert snap["price"] == 11.0
    assert snap["pre_close"] == 10.0
    assert snap["chg_pct"] == 10.0   # (11-10)/10*100
    assert snap["open_chg_pct"] == 5.0  # (10.5-10)/10*100
    assert snap["vwap"] is not None
    assert snap["intraday_vol_ratio"] is not None
    assert snap["vol_note"] == "ok"
    assert snap["asof"] == q.ts


def test_snapshot_pre_close_zero_divide_guard():
    """建议#6:pre_close=0 时 chg_pct/open_chg_pct 应为 None(除零守卫),不崩不算。"""
    q = _make_quote(price=11.0, volume=120000, pre_close=0.0, open_=10.5)
    snap = build_intraday_snapshot(
        quote=q, prev5_avg_vol=200000,
        now=_dt(_TRADING_DATE, 11, 30), is_trading=True,
    )
    assert snap["chg_pct"] is None
    assert snap["open_chg_pct"] is None
    # 其余字段仍正常计算(除零守卫只影响 pct 两个字段)
    assert snap["price"] == 11.0


def test_snapshot_prev5_zero_gives_no_base_ratio():
    q = _make_quote(price=11.0, volume=120000, pre_close=10.0)
    snap = build_intraday_snapshot(
        quote=q, prev5_avg_vol=0,
        now=_dt(_TRADING_DATE, 11, 30), is_trading=True,
    )
    assert snap["intraday_vol_ratio"] is None
    assert snap["vol_note"] == "no_base"


def test_snapshot_early_window_marks_note():
    q = _make_quote(price=11.0, volume=1000, pre_close=10.0)
    snap = build_intraday_snapshot(
        quote=q, prev5_avg_vol=200000,
        now=_dt(_TRADING_DATE, 9, 45), is_trading=True,   # elapsed=15min < 60
    )
    assert snap["intraday_vol_ratio"] is None
    assert snap["vol_note"] == "early"
