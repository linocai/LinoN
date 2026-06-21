"""交易日历原语(plan §4 Phase 0.5,含锁定约束 1+2)。

接口契约:
    is_trading_day(date) -> bool
    next_trading_day(date) -> date
    prev_trading_day(date) -> date
    trading_window(date) -> [(am_open,am_close),(pm_open,pm_close)] | None
    count_holding_trade_days(buy_date, today) -> int   # 闭区间[buy,today]交易日数,买入日=1
    should_force_close(buy_date, today) -> bool         # == (count == 4)

锁定语义(钉死,builder 不得改):
  · count_holding_trade_days 数闭区间 [buy_date, today] 的交易日个数,买入日计为 1。
  · count == 4(买入日之后第 3 个交易日)即 should_force_close 为真。可卖日 = D2/D3,D4 强平。

数据源:trade_cal 驱动 + 静态 2025–2026 兜底。
  · 缺 token → 用静态表,不崩(覆盖年份外保守按"工作日=交易日"近似,并不在本期路径)。
  · 有 token → 可调 verify_against_trade_cal 拉 SSE trade_cal 与静态表比对,不一致告警。

注意:本模块在名为 `calendar` 的包内,务必【绝对导入】,不用 `import calendar`
     (会拿到本包而非标准库)。本模块只依赖标准库 datetime,不碰标准库 calendar。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple, Union

from app.calendar.static_holidays import STATIC_CLOSED, STATIC_YEARS

logger = logging.getLogger(__name__)

# A 股两段交易时段(有午休)。集合竞价(9:15–9:25 / 14:57–15:00)价格行为不同,
# 阶段0 不实现竞价逻辑,仅此注释留痕。
_AM = (time(9, 30), time(11, 30))
_PM = (time(13, 0), time(15, 0))

DateLike = Union[date, datetime, str]


def _to_date(d: DateLike) -> date:
    """归一为 date。支持 date / datetime / 'YYYY-MM-DD' / 'YYYYMMDD'。"""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    s = str(d).strip()
    if "-" in s:
        return datetime.strptime(s, "%Y-%m-%d").date()
    return datetime.strptime(s, "%Y%m%d").date()


def _iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# —— 基础判定 ————————————————————————————————————————————————————

def is_trading_day(d: DateLike) -> bool:
    """是否交易日。规则:周末非交易;静态休市表内非交易;其余工作日交易。

    静态表覆盖 2025–2026。超出覆盖年份时退化为"工作日即交易日"近似
    (本期不走到;trade_cal 到位后由其覆盖),并打 warning。
    """
    dt = _to_date(d)
    if dt.weekday() >= 5:           # 5=周六 6=周日
        return False
    if _iso(dt) in STATIC_CLOSED:
        return False
    if dt.year not in STATIC_YEARS:
        logger.warning(
            "is_trading_day(%s): 超出静态表覆盖年份 %s,退化为工作日近似(待 trade_cal 覆盖)",
            _iso(dt), STATIC_YEARS,
        )
    return True


def next_trading_day(d: DateLike) -> date:
    """严格在 d 之后的下一个交易日(不含 d 自身)。"""
    dt = _to_date(d) + timedelta(days=1)
    # 上限保护:静态表内最坏连休不超过 ~12 天,给 40 天足够冗余
    for _ in range(40):
        if is_trading_day(dt):
            return dt
        dt += timedelta(days=1)
    raise RuntimeError(f"next_trading_day: 40 天内未找到交易日,起点 {_iso(_to_date(d))}")


def prev_trading_day(d: DateLike) -> date:
    """严格在 d 之前的上一个交易日(不含 d 自身)。"""
    dt = _to_date(d) - timedelta(days=1)
    for _ in range(40):
        if is_trading_day(dt):
            return dt
        dt -= timedelta(days=1)
    raise RuntimeError(f"prev_trading_day: 40 天内未找到交易日,起点 {_iso(_to_date(d))}")


def trading_window(d: DateLike) -> Optional[List[Tuple[time, time]]]:
    """两段交易时段;非交易日返回 None。

    [(09:30,11:30),(13:00,15:00)]。集合竞价不在内(见模块注释)。
    """
    if not is_trading_day(d):
        return None
    return [_AM, _PM]


# —— 持仓交易日计数(锁定语义)——————————————————————————————————————

def count_holding_trade_days(buy_date: DateLike, today: DateLike) -> int:
    """闭区间 [buy_date, today] 内交易日个数,买入日计为 1。

    锁定语义:买入日 = D1。今天早于买入日 → 0(异常输入保护)。
    跨周末/节假日时只数交易日(非自然日)。
    """
    bd = _to_date(buy_date)
    td = _to_date(today)
    if td < bd:
        return 0
    count = 0
    cur = bd
    while cur <= td:
        if is_trading_day(cur):
            count += 1
        cur += timedelta(days=1)
    return count


def should_force_close(buy_date: DateLike, today: DateLike) -> bool:
    """D4 强平:当且仅当 count_holding_trade_days == 4。"""
    return count_holding_trade_days(buy_date, today) == 4


# —— trade_cal 校验对齐(有 token 时;无 token 不调用)————————————————

def verify_against_trade_cal(start: str, end: str) -> dict:
    """拉 SSE trade_cal 与静态表比对(有 token 时)。返回比对报告 dict。

    无 token / 接口失败 → {'ok': False, 'reason': ...},不崩。
    不一致 → 在 'mismatches' 列出,并打 warning(告警,不自动改静态表)。
    """
    from app.data.tushare_client import ts_trade_cal  # 延迟导入,避免循环

    res = ts_trade_cal(start, end)
    if not res.ok or res.data is None:
        return {"ok": False, "reason": res.reason, "mismatches": []}

    mismatches = []
    try:
        df = res.data
        for _, row in df.iterrows():
            cal_date = str(row["cal_date"])           # 'YYYYMMDD'
            is_open_ts = int(row["is_open"]) == 1     # trade_cal 口径
            d = _to_date(cal_date)
            is_open_static = is_trading_day(d)
            if is_open_ts != is_open_static:
                mismatches.append({
                    "date": _iso(d),
                    "trade_cal_is_open": is_open_ts,
                    "static_is_open": is_open_static,
                })
    except Exception as e:
        return {"ok": False, "reason": f"trade_cal 解析异常: {e}", "mismatches": []}

    if mismatches:
        logger.warning(
            "静态日历与 trade_cal 不一致 %d 处(以 trade_cal 为准,需更新静态表): %s",
            len(mismatches), mismatches[:10],
        )
    return {"ok": True, "reason": "ok", "mismatches": mismatches}
