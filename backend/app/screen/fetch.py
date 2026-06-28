"""全市场 EOD 拉取 + pandas 归一(阶段2 Phase D1)。

plan §4.0:Tushare daily_basic/moneyflow_dc 按 trade_date **一次返回全市场** ~5400 行,
daily 近 N 日按 trade_date 逐日批量拉再内存拼接;stock_basic 行业映射缓存(进程内,
启动/EOD 拉一次)。**不落原始全市场数据**(内存紧),只把当日候选结果落 candidates 表。

降级铁律(沿阶段0/1):任一接口缺 token/失败 → 优雅降级,绝不抛崩。
  · stock_basic 失败 → 行业映射为空(白酒黑名单退化为仅代码段/ST,不误杀也不漏挡到崩)。
  · daily_basic 失败 → fetch 返回 None + reason(pipeline 据此返回空列表 degraded)。
  · moneyflow_dc 失败/无权限(2000 积分 token 跑会落此)→ 资金面退化为 0(不崩;
    粗筛"近 3 日净流入>0"会把全市场挡掉、资金排序因子失效,但全链路不崩)。
  · daily(近 N 日)部分日失败 → 用已拿到的日子算,缺得太多则该指标退化(不崩)。

字段口径(2026-06 真实冒烟校验,见 CLAUDE.md):
  · daily_basic:close / turnover_rate(%) / total_mv(万元) / volume_ratio(量比)。
  · moneyflow_dc(东财源,选股资金面唯一信号):net_amount(万元,主力净额=超大单
    buy_elg + 大单 buy_lg);6000 积分解锁、当日数据(比原始 moneyflow 发布延迟更优)。
    与原始 moneyflow.net_mf_amount 同单位(万元)、口径不同(东财主力 vs 同花顺式),属预期。
  · daily:vol(手) / amount(千元) / close / pre_close / pct_chg(%)。
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.calendar.trading_calendar import prev_trading_day
from app.data import tushare_client as tc
from app.screen import rules

logger = logging.getLogger(__name__)

# 近 N 日 daily 用于算放量倍数(当日量/5日均量)、创 20 日新高、站 20 日均线、60 日涨幅。
# 取 60 + 余量,保证 60 日窗口完整。
_LOOKBACK_TRADE_DAYS = 65


def _bare(ts_code: str) -> str:
    """ts_code('600000.SH') → 裸 6 位代码('600000')。"""
    return re.sub(r"\D", "", str(ts_code or ""))[:6]


# —— 行业映射缓存(进程内,启动/EOD 拉一次)————————————————————————————

_INDUSTRY_MAP: Dict[str, str] = {}
_NAME_MAP: Dict[str, str] = {}
_INDUSTRY_LOADED = False
_INDUSTRY_LOCK = threading.Lock()


def load_industry_map(force: bool = False) -> Dict[str, str]:
    """拉 stock_basic → 进程内缓存 {裸代码: industry}。

    无 token/失败 → 返回空 dict(不崩;白酒黑名单退化为仅代码段/ST)。
    force=True 强制重拉(EOD 刷新可调)。结果缓存(行业一日内不变)。
    """
    global _INDUSTRY_LOADED
    with _INDUSTRY_LOCK:
        if _INDUSTRY_LOADED and not force:
            return _INDUSTRY_MAP
        res = tc.ts_stock_basic()
        if not res.ok or res.data is None:
            logger.warning("stock_basic 拉取失败(%s);行业映射退化为空", res.reason)
            _INDUSTRY_LOADED = True   # 标记已尝试,避免每 tick 重试打满限频
            return _INDUSTRY_MAP
        try:
            _INDUSTRY_MAP.clear()
            _NAME_MAP.clear()
            for _, row in res.data.iterrows():
                code = _bare(row.get("ts_code"))
                if not code:
                    continue
                _INDUSTRY_MAP[code] = str(row.get("industry") or "")
                _NAME_MAP[code] = str(row.get("name") or "")
            _INDUSTRY_LOADED = True
            logger.info("行业映射已缓存 %d 条", len(_INDUSTRY_MAP))
        except Exception as e:  # 解析异常也不崩
            logger.warning("stock_basic 解析异常(%s);行业映射退化为空", e)
            _INDUSTRY_LOADED = True
        return _INDUSTRY_MAP


def reset_industry_cache() -> None:
    """清行业缓存(测试 / 热重载用)。"""
    global _INDUSTRY_LOADED
    with _INDUSTRY_LOCK:
        _INDUSTRY_MAP.clear()
        _NAME_MAP.clear()
        _INDUSTRY_LOADED = False


def industry_of(code: str) -> Optional[str]:
    return _INDUSTRY_MAP.get(_bare(code))


def name_of(code: str) -> Optional[str]:
    return _NAME_MAP.get(_bare(code))


# —— 单票归一行 ————————————————————————————————————————————————————

@dataclass
class StockRow:
    """单票当日 + 近期派生指标(pipeline 的输入单元)。"""
    code: str                       # 裸 6 位
    name: str
    industry: str
    close: float = 0.0
    pct_chg: float = 0.0            # 当日涨跌幅 %
    turnover: float = 0.0          # 换手率 %
    total_mv_yi: float = 0.0       # 总市值(亿元,total_mv÷1e4)
    net_mf_amount: float = 0.0     # 当日主力净额(万元,东财 moneyflow_dc.net_amount)
    net_mf_3d: float = 0.0         # 近 3 日主力净额合计(万元,东财 moneyflow_dc.net_amount)
    vol_multiple: float = 0.0      # 当日量 / 5 日均量
    pct_60d: Optional[float] = None  # 近 60 交易日累计涨幅 %
    new_high_20d: bool = False     # 创 20 日新高
    above_ma20: bool = False       # 站上 20 日均线


@dataclass
class MarketSnapshot:
    """全市场当日快照(归一后的 StockRow 列表 + 基准 trade_date)。"""
    trade_date: str                 # 'YYYY-MM-DD'(展示用)
    rows: List[StockRow] = field(default_factory=list)
    ok: bool = True
    reason: str = "ok"

    @classmethod
    def fail(cls, trade_date: str, reason: str) -> "MarketSnapshot":
        return cls(trade_date=trade_date, rows=[], ok=False, reason=reason)


def _fmt_date(yyyymmdd: str) -> str:
    s = str(yyyymmdd)
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _recent_trade_dates(latest_yyyymmdd: str, n: int) -> List[str]:
    """从 latest(含)往前取 n 个交易日('YYYYMMDD' 列表,新→旧)。"""
    from app.calendar.trading_calendar import _to_date  # 复用日历归一

    out: List[str] = [latest_yyyymmdd]
    cur = _to_date(latest_yyyymmdd)
    for _ in range(n - 1):
        cur = prev_trading_day(cur)
        out.append(cur.strftime("%Y%m%d"))
    return out


def fetch_market_snapshot(trade_date_yyyymmdd: str) -> MarketSnapshot:
    """拉全市场当日 daily_basic + moneyflow + 近 N 日 daily,归一为 MarketSnapshot。

    trade_date_yyyymmdd:EOD 基准交易日 'YYYYMMDD'。
    无 token/核心接口失败 → MarketSnapshot.fail(不崩)。
    daily 近 N 日缺日子 → 用已有日子算,缺太多则相应指标退化(pct_60d=None 等)。
    """
    import pandas as pd

    disp = _fmt_date(trade_date_yyyymmdd)
    load_industry_map()   # 确保行业映射在位(无 token 则空,不崩)

    db = tc.ts_daily_basic_all(trade_date_yyyymmdd)
    if not db.ok or db.data is None:
        return MarketSnapshot.fail(disp, f"daily_basic 拉取失败: {db.reason}")

    mf = tc.ts_moneyflow_dc_all(trade_date_yyyymmdd)
    mf_today: Dict[str, float] = {}
    if mf.ok and mf.data is not None:
        for _, r in mf.data.iterrows():
            mf_today[_bare(r.get("ts_code"))] = float(r.get("net_amount") or 0.0)
    else:
        logger.warning("moneyflow_dc 拉取失败(%s);资金面退化为 0", mf.reason)

    # 近 N 日 daily(逐交易日批量拉,内存拼接)。某日失败跳过(不崩)。
    dates = _recent_trade_dates(trade_date_yyyymmdd, _LOOKBACK_TRADE_DAYS)
    # daily_frames[date] = {code: {'close','vol','pre_close'}}
    daily_by_date: Dict[str, Dict[str, dict]] = {}
    for d in dates:
        res = tc.ts_daily_all(d)
        if not res.ok or res.data is None:
            continue
        per: Dict[str, dict] = {}
        for _, r in res.data.iterrows():
            per[_bare(r.get("ts_code"))] = {
                "close": float(r.get("close") or 0.0),
                "vol": float(r.get("vol") or 0.0),
                "pre_close": float(r.get("pre_close") or 0.0),
            }
        daily_by_date[d] = per

    # 近 3 日主力净流入合计(用东财 moneyflow_dc 近 3 个交易日)
    mf_3d_dates = dates[:rules.RECENT_FLOW_DAYS]
    mf_3d: Dict[str, float] = dict(mf_today)  # 当日已含
    for d in mf_3d_dates[1:]:                 # 再补前 2 日
        res = tc.ts_moneyflow_dc_all(d)
        if not res.ok or res.data is None:
            continue
        for _, r in res.data.iterrows():
            c = _bare(r.get("ts_code"))
            mf_3d[c] = mf_3d.get(c, 0.0) + float(r.get("net_amount") or 0.0)

    rows: List[StockRow] = []
    latest = trade_date_yyyymmdd
    for _, r in db.data.iterrows():
        code = _bare(r.get("ts_code"))
        if not code:
            continue
        industry = _INDUSTRY_MAP.get(code, "")
        name = _NAME_MAP.get(code, code)
        close = float(r.get("close") or 0.0)
        turnover = float(r.get("turnover_rate") or 0.0)
        total_mv = float(r.get("total_mv") or 0.0)   # 万元
        sr = StockRow(
            code=code, name=name, industry=industry,
            close=close,
            turnover=turnover,
            total_mv_yi=round(total_mv / 1e4, 2),
            net_mf_amount=mf_today.get(code, 0.0),
            net_mf_3d=mf_3d.get(code, 0.0),
        )
        # 近 N 日形态(从 daily_by_date 取本票历史序列,新→旧)
        _enrich_form(sr, code, dates, daily_by_date, latest)
        rows.append(sr)

    return MarketSnapshot(trade_date=disp, rows=rows, ok=True, reason="ok")


def _enrich_form(
    sr: StockRow,
    code: str,
    dates: List[str],
    daily_by_date: Dict[str, Dict[str, dict]],
    latest: str,
) -> None:
    """从近 N 日 daily 序列算放量倍数 / 创 20 日新高 / 站 20 日均线 / 60 日涨幅 / 当日涨跌幅。

    dates 新→旧;daily_by_date[date][code] = {'close','vol','pre_close'}。
    缺数据时各指标保守退化(vol_multiple=0、new_high=False、pct_60d=None),不崩。
    """
    # 本票历史序列(新→旧),只取有该 code 数据的交易日
    seq = []
    for d in dates:
        rec = daily_by_date.get(d, {}).get(code)
        if rec is not None:
            seq.append(rec)
    if not seq:
        return
    today_rec = seq[0]
    today_vol = today_rec["vol"]
    today_close = today_rec["close"] or sr.close
    pre_close = today_rec["pre_close"]
    if pre_close > 0:
        sr.pct_chg = round((today_close - pre_close) / pre_close * 100, 2)

    closes = [x["close"] for x in seq if x["close"] > 0]   # 新→旧
    vols = [x["vol"] for x in seq]

    # 放量倍数 = 当日量 / 前 5 日均量(用 today 之前的 5 个交易日)
    prev5 = vols[1:6]
    prev5 = [v for v in prev5 if v > 0]
    if prev5:
        avg5 = sum(prev5) / len(prev5)
        if avg5 > 0:
            sr.vol_multiple = round(today_vol / avg5, 2)

    # 创 20 日新高:今日收盘 >= 近 20 日(不含今日)最高收盘
    prev20 = closes[1:21]
    if prev20 and today_close > 0:
        sr.new_high_20d = today_close >= max(prev20)

    # 站上 20 日均线(用近 20 日收盘均值,含今日近似;窗口不足用现有)
    ma_window = closes[:rules.MA_DAYS]
    if ma_window:
        ma20 = sum(ma_window) / len(ma_window)
        sr.above_ma20 = today_close >= ma20

    # 近 60 交易日累计涨幅:今日收盘 vs 60 个交易日前收盘
    if len(closes) >= 2:
        # closes 新→旧;取第 min(60, len-1) 个作为基准
        base_idx = min(60, len(closes) - 1)
        base = closes[base_idx]
        if base > 0:
            sr.pct_60d = round((today_close - base) / base * 100, 2)
