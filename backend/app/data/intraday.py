"""盘中数据层(纯函数,plan v1.4 §4 Phase A)。

本模块只吃「已拿到的数据」(Quote 对象 / prev5 均量数值),不自己拉价、不拉
daily、不联网——拉价/拉 daily 在端点层(Phase B/C)做,便于单测不联网 +
端点批量复用一拍拉价。

四个函数职责:
  · `_is_intraday_window(now)`  —— 本 feature 唯一的"是否盘中"真值源。
      **明令不得复用** `app.monitor.loop._is_trading_now`(那个按两段窗口判、
      午休/15:00 后返 False;本函数刻意把午休算作"盘中",因为午休时当日
      累计成交量/amount/VWAP/现价都是有效的上午终态)。
  · `elapsed_trading_minutes(now)` —— 已开盘时长(分钟),跨午休定格 120。
  · `intraday_vol_ratio(current_vol, prev5_avg_vol, elapsed_min)` —— 按已开盘
      时长折算全天量,除以前5日均量得比值;早盘头 60min/无基准/收盘边缘分支
      各标注 note。
  · `vwap_of(quote)` —— vwap = amount/(volume×100)(元/股)。**注意系数**:
      `Quote` 归一后 volume 单位=手、amount 单位=元(见 CLAUDE.md 数据源坑 +
      `app/data/realtime.py` 模块头注释),与 `app/screen/form.py:173` 的
      `amount×1000/(vol×100)`(千元/手)系数不同——那是 Tushare daily 原始
      字段口径(amount 千元),这里是 realtime 归一后口径(amount 已是元),
      **不要照抄 form.py 的 ×1000**。
  · `build_intraday_snapshot(...)` —— 纯编排,组装单票盘中快照 dict。
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional, Tuple

from app.calendar import is_trading_day
from app.data.realtime import Quote

# A 股两段交易时段边界(与 app.calendar.trading_calendar._AM/_PM 一致,但本模块
# 刻意不复用 trading_window/_is_trading_now——见模块头注释,午休判定不同)。
_OPEN = time(9, 30)
_CLOSE = time(15, 0)
_NOON_START = time(11, 30)
_NOON_END = time(13, 0)

# 早盘头 60min:集合竞价噪声 + A 股早盘量能前置,折算系统性高估,阈提到 60min。
_EARLY_MINUTES_THRESHOLD = 60
# 全天交易分钟数(120 + 120)。
_FULL_DAY_MINUTES = 240


def _is_intraday_window(now: datetime) -> bool:
    """本 feature 唯一"是否盘中"判定:交易日 且 09:30 ≤ now.time() < 15:00(含午休)。

    禁止复用 `loop._is_trading_now`(见模块头注释)。响应体 `is_trading` 字段
    的值即本函数的返回值。
    """
    if not is_trading_day(now.date()):
        return False
    t = now.time()
    return _OPEN <= t < _CLOSE


def elapsed_trading_minutes(now: datetime) -> int:
    """已开盘交易分钟数(跨午休 11:30–13:00 不计,午休期间定格 120)。

    `now<09:30` → 0;`now>=15:00` → 240。纯 datetime 运算,时段有效性由
    调用方先经 `_is_intraday_window` 判。
    """
    t = now.time()
    if t < _OPEN:
        return 0
    if t >= _CLOSE:
        return _FULL_DAY_MINUTES
    if t < _NOON_START:
        # 上午段内:分钟差
        delta = datetime.combine(now.date(), t) - datetime.combine(now.date(), _OPEN)
        return int(delta.total_seconds() // 60)
    if t < _NOON_END:
        # 午休:定格在上午满量 120min
        return 120
    # 下午段内:120(上午) + 下午已过分钟
    delta = datetime.combine(now.date(), t) - datetime.combine(now.date(), _NOON_END)
    return 120 + int(delta.total_seconds() // 60)


def intraday_vol_ratio(
    current_vol: float,
    prev5_avg_vol: float,
    elapsed_min: int,
) -> Tuple[Optional[float], str]:
    """按已开盘时长折算全天量 / 前5日均量。

    返回 (ratio_or_None, note),note ∈ {"ok","early","closed","no_base"}。
    优先级(plan 定死):early 阈(60min)先判,no_base 次之,>=240 走 closed,
    否则 ok。ratio 保留 1 位小数。
    """
    if elapsed_min < _EARLY_MINUTES_THRESHOLD:
        return None, "early"
    if prev5_avg_vol <= 0:
        return None, "no_base"
    projected_full_vol = current_vol / elapsed_min * _FULL_DAY_MINUTES
    ratio = round(projected_full_vol / prev5_avg_vol, 1)
    note = "closed" if elapsed_min >= _FULL_DAY_MINUTES else "ok"
    return ratio, note


def vwap_of(quote: Optional[Quote]) -> Tuple[Optional[float], Optional[bool]]:
    """vwap = amount/(volume×100)(元/股);is_above_vwap = price >= vwap。

    `Quote` 归一后 volume=手、amount=元(不是 form.py 的千元/手口径,系数
    不同,见模块头注释)。quote is None 或 volume<=0(停牌/开盘前/无成交)
    → (None, None)。
    """
    if quote is None or quote.volume <= 0:
        return None, None
    vwap = quote.amount / (quote.volume * 100.0)
    if vwap <= 0:
        return None, None
    is_above = quote.price >= vwap
    return round(vwap, 4), is_above


def build_intraday_snapshot(
    quote: Optional[Quote],
    prev5_avg_vol: float,
    *,
    now: datetime,
    is_trading: bool,
) -> dict:
    """纯编排:组装单票盘中快照 dict。不在此函数内拉价/拉 daily。

    形状:{is_trading, price, pre_close, chg_pct, open_chg_pct, vwap,
           is_above_vwap, intraday_vol_ratio, vol_note, asof}
    """
    if not is_trading:
        return {
            "is_trading": False,
            "price": None,
            "pre_close": None,
            "chg_pct": None,
            "open_chg_pct": None,
            "vwap": None,
            "is_above_vwap": None,
            "intraday_vol_ratio": None,
            "vol_note": "non_trading",
            "asof": "",
        }

    if quote is None:
        return {
            "is_trading": True,
            "price": None,
            "pre_close": None,
            "chg_pct": None,
            "open_chg_pct": None,
            "vwap": None,
            "is_above_vwap": None,
            "intraday_vol_ratio": None,
            "vol_note": "no_base",
            "asof": "",
        }

    pre_close = quote.pre_close
    chg_pct: Optional[float] = None
    open_chg_pct: Optional[float] = None
    if pre_close > 0:
        chg_pct = round((quote.price - pre_close) / pre_close * 100, 2)
        open_chg_pct = round((quote.open - pre_close) / pre_close * 100, 2)

    vwap, is_above_vwap = vwap_of(quote)

    elapsed_min = elapsed_trading_minutes(now)
    ratio, vol_note = intraday_vol_ratio(quote.volume, prev5_avg_vol, elapsed_min)

    return {
        "is_trading": True,
        "price": quote.price,
        "pre_close": pre_close,
        "chg_pct": chg_pct,
        "open_chg_pct": open_chg_pct,
        "vwap": vwap,
        "is_above_vwap": is_above_vwap,
        "intraday_vol_ratio": ratio,
        "vol_note": vol_note,
        "asof": quote.ts,
    }
