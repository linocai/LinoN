"""今日盈亏纯函数(v1.4.1 Phase A,plan §4)。

不联网、不落库、可注入单测。今日盈亏 = 今日已实现 + 今日浮动(同花顺式口径)。
· 今日已实现:trades 表 close_time 日期属今日的行 net_pnl_amount 求和(NULL 行跳过)。
· 今日浮动:Σ 持仓 (price − todayBase) × qty,todayBase = 今日新买用 buy_price,否则用 pre_close。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def today_realized_amount(trades: List[Dict[str, Any]], today: str) -> float:
    """今日已实现净额:close_time 日期部分 == today 且 net_pnl_amount 非空的行求和。

    无匹配行 → 0.0。日期匹配用 str(close_time)[:10] == today,兼容
    "YYYY-MM-DD HH:MM:SS" 与 ISO8601 "YYYY-MM-DDTHH:MM:SS"(两者前 10 位都是 YYYY-MM-DD)。
    """
    total = 0.0
    for t in trades:
        close_time = t.get("close_time")
        if close_time is None:
            continue
        if str(close_time)[:10] != today:
            continue
        net = t.get("net_pnl_amount")
        if net is None:
            continue
        total += float(net)
    return total


def today_float_pnl(
    holdings: List[Dict[str, Any]],
    prices: Dict[str, float],
    pre_closes: Dict[str, float],
    today: str,
) -> Tuple[float, bool]:
    """今日浮动 = Σ (price − todayBase) × qty。

    todayBase = 今日新买(buy_date[:10]==today)用 buy_price,否则用 pre_close。
    两条降级分支,均记该仓浮动 0 + partial=True(先判 price 再判 base):
    · price 缺失/<=0(停牌/拉价失败)→ 无论今日新买与否,记 0 + partial。
    · pre_close 缺失/<=0 且非今日新买 → 记 0 + partial(今日新买用 buy_price 不受影响)。
    """
    total = 0.0
    partial = False
    for h in holdings:
        code = h.get("code")
        qty = h.get("qty", 0) or 0
        buy_date = str(h.get("buy_date") or "")
        buy_price = h.get("buy_price", 0.0) or 0.0

        price = prices.get(code)
        if price is None or price <= 0:
            partial = True
            continue

        is_new_buy_today = buy_date[:10] == today
        if is_new_buy_today:
            base = buy_price
        else:
            pre_close = pre_closes.get(code)
            if pre_close is None or pre_close <= 0:
                partial = True
                continue
            base = pre_close

        total += (price - base) * qty

    return total, partial
