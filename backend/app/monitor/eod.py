"""盘后 EOD 摘要(阶段1 A.5)。

收盘后对每持仓产出一条 EOD 摘要(非升级类、category 普通):
  · 盈亏%(现价 vs 买入价)
  · 持仓第几交易日(D几)
  · 明日 D4 预警(明日 should_force_close 为真 → 标"明日强平")

当日资金二次校验占位:需 Tushare moneyflow/daily_basic,无 token 降级跳过
(摘要注明"资金校验:已跳过 token 缺失"),整条照推,不崩。

纯函数(build_eod_summary)可单测;真发推由 loop/调用方做。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from app.calendar.trading_calendar import (
    count_holding_trade_days,
    next_trading_day,
    should_force_close,
)
from app.config import settings
from app.monitor.hardline import pnl_pct_of


@dataclass
class EodSummary:
    code: str
    name: str
    title: str
    body: str
    pnl_pct: float
    trade_day: int
    force_close_tomorrow: bool


def _fund_check_note() -> str:
    """资金二次校验段:有 token 才查;无 token 降级注明。

    本期(A.5)即使有 token 也仅占位文案——真查 moneyflow/daily_basic 的口径校验
    留待联调(报告/plan 已注明);无 token 时降级注明,整条照推不崩。
    """
    if settings.has_tushare_token:
        return "资金校验:token 在位(口径校验待联调)"
    return "资金校验:已跳过 token 缺失"


def build_eod_summary(
    *,
    code: str,
    name: str,
    buy_price: float,
    price: float,
    buy_date,
    today: Optional[date] = None,
) -> EodSummary:
    """对单持仓产出一条 EOD 摘要。price 为收盘价。"""
    td = count_holding_trade_days(buy_date, today) if today else count_holding_trade_days(buy_date, buy_date)
    pnl = pnl_pct_of(buy_price, price)

    ref_today = today or date.today()
    tomorrow = next_trading_day(ref_today)
    fc_tomorrow = should_force_close(buy_date, tomorrow)

    warn = "明日 D4 强平 ⚠️" if fc_tomorrow else "明日未到强平日"
    fund = _fund_check_note()
    body = (
        f"今日盈亏 {pnl:+.1f}% · 持仓第 {td} 个交易日(D{td}) · {warn}\n{fund}"
    )
    return EodSummary(
        code=code, name=name,
        title=f"{name} 盘后摘要",
        body=body,
        pnl_pct=pnl, trade_day=td, force_close_tomorrow=fc_tomorrow,
    )


def build_eod_summaries(holdings: List[dict], quotes: dict, today: Optional[date] = None
                        ) -> List[EodSummary]:
    """对一批持仓产出 EOD 摘要列表。

    holdings:list_holdings() 输出(含 code/name/buy_price/buy_date)。
    quotes:{code: Quote-like}(有 .price 或 dict['price']);缺价用 buy_price 兜底(0%)。
    """
    out: List[EodSummary] = []
    for h in holdings:
        code = h["code"]
        q = quotes.get(code)
        if q is None:
            price = h["buy_price"]
        elif hasattr(q, "price"):
            price = q.price
        else:
            price = q.get("price", h["buy_price"])
        out.append(build_eod_summary(
            code=code, name=h["name"], buy_price=h["buy_price"],
            price=price, buy_date=h["buy_date"], today=today,
        ))
    return out
