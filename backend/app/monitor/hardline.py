"""3 硬线判定(纯函数,可单测,不联网)—— 阶段1 A.3。

判定口径(常量引用 app.db.store 单一事实源,与客户端 Models.swift / plan §4b 同源):
  · 止损   pnl_pct ≤ STOP_TRIGGER_PCT(-5.0)
  · 止盈   pnl_pct ≥ TAKE_TRIGGER_PCT(+15.0)
  · D4 时间 should_force_close(buy_date, today) == True(count==4)

特殊感知(plan A.3,防误报 / 对齐 T+1 现实):
  · T+1 感知:买入日(D1,count==1)命中价格硬线 → 文案"记录,明日开盘处理",
              不喊"必走"(T+1 当日不可卖)。时间线 D4 永远不会在 D1 触发,无需此分支。
  · 涨跌停感知:用 Quote.limit_up/limit_down,现价一字封死跌停 → "封死,明日处理";
              触止盈线时若封涨停同理(可成交才"必走")。
  · 多源一致性校验:同票两源 pre_close / 现价口径差超阈值 → 标"行情存疑",【不据此触发硬线】
              (防除权口径差导致假报警)。校验在调用方(loop)拿到两源时做,结果以
              quote_suspect=True 传入 classify;suspect 时本函数只产出"行情存疑"事件、不触发硬线。

产出"待推送事件"(HardlineEvent)交 A.4 升级器;本模块不写库、不发推。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from app.db.store import (
    STOP_TRIGGER_PCT,
    TAKE_TRIGGER_PCT,
)
from app.calendar.trading_calendar import (
    count_holding_trade_days,
    should_force_close,
)

# 硬线类型(category 由此映射 APNs 锁屏动作按钮)
KIND_STOP = "stop"        # 止损 -5%
KIND_TAKE = "take"        # 止盈 +15%
KIND_TIME = "time"        # D4 时间强平
KIND_SUSPECT = "suspect"  # 行情存疑(非硬线,不升级;仅记录/可选普通提示)

# 涨跌停一字封死判定:现价贴住涨/跌停价(留极小容差 0.01 应对四舍五入)。
_LIMIT_EPS = 0.011


@dataclass
class HardlineEvent:
    """一条待推送的硬线事件(交升级器)。"""
    code: str
    name: str
    kind: str                 # KIND_STOP / KIND_TAKE / KIND_TIME / KIND_SUSPECT
    title: str
    body: str
    pnl_pct: float
    trade_day: int            # 当前是第几交易日(D几)
    actionable: bool          # True=今日可走"必走";False=T+1/封死"明日处理"
    suspect: bool = False     # 行情存疑(不触发硬线的 KIND_SUSPECT 用)

    @property
    def is_hardline(self) -> bool:
        return self.kind in (KIND_STOP, KIND_TAKE, KIND_TIME)


def _at_limit_down(price: float, limit_down: float) -> bool:
    return limit_down > 0 and price <= limit_down + _LIMIT_EPS


def _at_limit_up(price: float, limit_up: float) -> bool:
    return limit_up > 0 and price >= limit_up - _LIMIT_EPS


def _stop_event(name: str, code: str, pnl_pct: float, td: int,
                price: float, limit_down: float) -> HardlineEvent:
    """构造止损硬线事件(含 T+1 与一字跌停文案分叉)。"""
    pnl_txt = f"{pnl_pct:+.1f}%"
    if td <= 1:
        # D1 命中:T+1 当日不可卖
        return HardlineEvent(
            code=code, name=name, kind=KIND_STOP,
            title=f"{name} 已触 −5% 止损线",
            body=f"现价浮亏 {pnl_txt}。今日买入(T+1 不可卖),记录,明日开盘处理。",
            pnl_pct=pnl_pct, trade_day=td, actionable=False,
        )
    if _at_limit_down(price, limit_down):
        return HardlineEvent(
            code=code, name=name, kind=KIND_STOP,
            title=f"{name} 已触 −5% 止损线",
            body=f"现价浮亏 {pnl_txt},一字跌停封死无法成交,明日开盘处理。",
            pnl_pct=pnl_pct, trade_day=td, actionable=False,
        )
    return HardlineEvent(
        code=code, name=name, kind=KIND_STOP,
        title=f"{name} 已触 −5% 止损线",
        body=f"现价浮亏 {pnl_txt},触止损线,必走。",
        pnl_pct=pnl_pct, trade_day=td, actionable=True,
    )


def _take_event(name: str, code: str, pnl_pct: float, td: int,
                price: float, limit_up: float) -> HardlineEvent:
    pnl_txt = f"{pnl_pct:+.1f}%"
    if td <= 1:
        return HardlineEvent(
            code=code, name=name, kind=KIND_TAKE,
            title=f"{name} 已触 +15% 止盈线",
            body=f"现价浮盈 {pnl_txt}。今日买入(T+1 不可卖),记录,明日开盘处理。",
            pnl_pct=pnl_pct, trade_day=td, actionable=False,
        )
    if _at_limit_up(price, limit_up):
        return HardlineEvent(
            code=code, name=name, kind=KIND_TAKE,
            title=f"{name} 已触 +15% 止盈线",
            body=f"现价浮盈 {pnl_txt},一字涨停封死无法成交,明日开盘处理。",
            pnl_pct=pnl_pct, trade_day=td, actionable=False,
        )
    return HardlineEvent(
        code=code, name=name, kind=KIND_TAKE,
        title=f"{name} 已触 +15% 止盈线",
        body=f"现价浮盈 {pnl_txt},触止盈线,可走。",
        pnl_pct=pnl_pct, trade_day=td, actionable=True,
    )


def _time_event(name: str, code: str, pnl_pct: float, td: int) -> HardlineEvent:
    """D4 时间强平。无券商兜底,沿用升级机制(loop 侧)。"""
    pnl_txt = f"{pnl_pct:+.1f}%"
    return HardlineEvent(
        code=code, name=name, kind=KIND_TIME,
        title=f"{name} 持仓已到 D4",
        body=f"持仓第 4 个交易日,现价 {pnl_txt},无条件清仓(D4 时间止损)。",
        pnl_pct=pnl_pct, trade_day=td, actionable=True,
    )


def pnl_pct_of(buy_price: float, price: float) -> float:
    """浮动盈亏百分比 = (price-buy)/buy*100。buy<=0 → 0。"""
    if buy_price <= 0:
        return 0.0
    return (price - buy_price) / buy_price * 100.0


def quotes_consistent(
    pre_close_a: float, price_a: float,
    pre_close_b: float, price_b: float,
    *, rel_threshold: float = 0.02,
) -> bool:
    """两源(新浪 vs 腾讯)一致性:pre_close 与现价相对差均在阈内则一致。

    任一口径相对差 > rel_threshold(默认 2%)→ 不一致(疑似除权/口径差)。
    任一源缺值(<=0)→ 视为不一致(不冒险触发)。
    """
    for x, y in ((pre_close_a, pre_close_b), (price_a, price_b)):
        if x <= 0 or y <= 0:
            return False
        base = max(abs(x), abs(y))
        if base == 0:
            return False
        if abs(x - y) / base > rel_threshold:
            return False
    return True


def classify(
    *,
    code: str,
    name: str,
    buy_price: float,
    price: float,
    pre_close: float,
    limit_up: float,
    limit_down: float,
    buy_date,
    today: Optional[date] = None,
    quote_suspect: bool = False,
) -> List[HardlineEvent]:
    """对单票产出待推送硬线事件列表(0..N 条)。

    quote_suspect=True(两源不一致)→ 只产出 KIND_SUSPECT、不触发任何硬线(防假报警)。
    否则按 止损/止盈/时间 三线分别判定,带 T+1 与涨跌停文案分叉。
    时间线 D4 与价格线可同时触发(各一条事件)。
    """
    td = count_holding_trade_days(buy_date, today) if today else count_holding_trade_days(buy_date, buy_date)
    pnl = pnl_pct_of(buy_price, price)

    if quote_suspect:
        return [HardlineEvent(
            code=code, name=name, kind=KIND_SUSPECT,
            title=f"{name} 行情存疑",
            body="两源(新浪/腾讯)pre_close 或现价口径差超阈值,本轮不据此触发硬线。",
            pnl_pct=pnl, trade_day=td, actionable=False, suspect=True,
        )]

    events: List[HardlineEvent] = []

    # 止损 / 止盈(价格线)
    if pnl <= STOP_TRIGGER_PCT:
        events.append(_stop_event(name, code, pnl, td, price, limit_down))
    elif pnl >= TAKE_TRIGGER_PCT:
        events.append(_take_event(name, code, pnl, td, price, limit_up))

    # 时间线 D4(独立于价格线,可叠加)
    if should_force_close(buy_date, today) if today else should_force_close(buy_date, buy_date):
        events.append(_time_event(name, code, pnl, td))

    return events
