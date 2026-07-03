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
    net_amount_rate(净额占当日成交额比例 %)——排序资金因子改用这个相对口径
    (net_mf_rate_3d,近 3 日合计),避免绝对金额天然偏向大盘股;net_mf_3d(绝对
    万元)仍保留供粗筛"近 3 日净流入>0"的正负号判定(符号不受量纲影响,不用改)。
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
from app.screen.form import compute_form, qfq_closes

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
    net_mf_rate_3d: float = 0.0    # 近 3 日主力净额占成交额比例合计(%,moneyflow_dc.net_amount_rate)
                                    # ——排序资金因子用这个相对口径,免绝对金额偏向大盘股
    vol_multiple: float = 0.0      # 当日量 / 5 日均量
    pct_60d: Optional[float] = None  # 近 60 交易日累计涨幅 %
    new_high_20d: bool = False     # 创 20 日新高
    above_ma20: bool = False       # 站上 20 日均线
    vwap_ok: bool = False          # 收盘站当日 VWAP(阶段3.1 信号1)
    had_limit_up: bool = False     # 近 N 日(排除今日)有涨停(阶段3.1 信号5)


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
    load_industry_map(force=True)   # 候选刷新时强制重拉行业映射(每日一次,不打限频):
    # 让"候选刷新自然回填"对首次加载失败(_INDUSTRY_LOADED 粘死空)也成立,相关性护栏自愈(v1.3.0 reviewer 🔵1)

    db = tc.ts_daily_basic_all(trade_date_yyyymmdd)
    if not db.ok or db.data is None:
        return MarketSnapshot.fail(disp, f"daily_basic 拉取失败: {db.reason}")

    mf = tc.ts_moneyflow_dc_all(trade_date_yyyymmdd)
    mf_today: Dict[str, float] = {}
    mf_today_rate: Dict[str, float] = {}
    if mf.ok and mf.data is not None:
        for _, r in mf.data.iterrows():
            c = _bare(r.get("ts_code"))
            mf_today[c] = float(r.get("net_amount") or 0.0)
            mf_today_rate[c] = float(r.get("net_amount_rate") or 0.0)
    else:
        logger.warning("moneyflow_dc 拉取失败(%s);资金面退化为 0", mf.reason)

    # 近 N 日 daily(逐交易日批量拉,内存拼接)。某日失败跳过(不崩)。
    dates = _recent_trade_dates(trade_date_yyyymmdd, _LOOKBACK_TRADE_DAYS)
    # daily_frames[date] = {code: {'close','vol','pre_close'}}
    daily_by_date: Dict[str, Dict[str, dict]] = {}
    # adj_by_date[date] = {code: adj_factor}(阶段2.5 F2:前复权技术指标)。
    # 与 daily 同循环同步拉取(节流复用限频降级),缺该日 → 该日不进 dict(compute_form
    # 内 qfq_closes 会对缺因子的日子退化 factor=1.0,不崩)。
    adj_by_date: Dict[str, Dict[str, float]] = {}
    adj_ok_days = 0
    for d in dates:
        res = tc.ts_daily_all(d)
        if res.ok and res.data is not None:
            per: Dict[str, dict] = {}
            for _, r in res.data.iterrows():
                per[_bare(r.get("ts_code"))] = {
                    "close": float(r.get("close") or 0.0),
                    "vol": float(r.get("vol") or 0.0),
                    "pre_close": float(r.get("pre_close") or 0.0),
                    "amount": float(r.get("amount") or 0.0),  # 千元(阶段3.1 信号1 VWAP)
                }
            daily_by_date[d] = per

        adj_res = tc.ts_adj_factor_all(d)
        if adj_res.ok and adj_res.data is not None:
            adj_per: Dict[str, float] = {}
            for _, r in adj_res.data.iterrows():
                c = _bare(r.get("ts_code"))
                af = r.get("adj_factor")
                if af is not None:
                    adj_per[c] = float(af)
            adj_by_date[d] = adj_per
            adj_ok_days += 1
        else:
            logger.debug("adj_factor 拉取失败(%s): %s", d, adj_res.reason)

    # 可观测性硬要求(plan §4.0 重要3):静默大面积限频失效要能从日志看出来。
    logger.info(
        "adj_factor 拉取 %d/%d 日成功(trade_date=%s)",
        adj_ok_days, len(dates), disp,
    )

    # 近 3 日主力净流入合计(用东财 moneyflow_dc 近 3 个交易日)
    mf_3d_dates = dates[:rules.RECENT_FLOW_DAYS]
    mf_3d: Dict[str, float] = dict(mf_today)  # 当日已含
    mf_rate_3d: Dict[str, float] = dict(mf_today_rate)
    for d in mf_3d_dates[1:]:                 # 再补前 2 日
        res = tc.ts_moneyflow_dc_all(d)
        if not res.ok or res.data is None:
            continue
        for _, r in res.data.iterrows():
            c = _bare(r.get("ts_code"))
            mf_3d[c] = mf_3d.get(c, 0.0) + float(r.get("net_amount") or 0.0)
            mf_rate_3d[c] = mf_rate_3d.get(c, 0.0) + float(r.get("net_amount_rate") or 0.0)

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
            net_mf_rate_3d=round(mf_rate_3d.get(code, 0.0), 4),
        )
        # 近 N 日形态(从 daily_by_date 取本票历史序列,新→旧;复权用 adj_by_date)
        _enrich_form(sr, code, dates, daily_by_date, latest, adj_by_date)
        rows.append(sr)

    return MarketSnapshot(trade_date=disp, rows=rows, ok=True, reason="ok")


def _enrich_form(
    sr: StockRow,
    code: str,
    dates: List[str],
    daily_by_date: Dict[str, Dict[str, dict]],
    latest: str,
    adj_by_date: Optional[Dict[str, Dict[str, float]]] = None,
) -> None:
    """薄封装(签名不变,test_screen.py 有测试直接调它断言字段)。

    内部改为:取本票 close/vol/adj 历史序列(新→旧)→ qfq_closes 复权 → compute_form
    统一算放量倍数/创20日新高/站20日均线/60日涨幅/当日涨跌幅,写回 sr。
    adj_by_date 缺省(None,如旧测试直调 5 参)→ 视为无复权数据,退化为原始价
    (等价旧行为,不崩)。dates 新→旧;daily_by_date[date][code] = {'close','vol','pre_close'}。
    """
    adj_by_date = adj_by_date or {}
    # 本票历史序列(新→旧),只取有该 code 数据的交易日;同步取该日 adj_factor(缺则 None)。
    # amount(千元,阶段3.1 VWAP 信号1)从 daily record 取,缺键退化 0.0(旧测试无该键不崩)。
    raw_closes: List[float] = []
    vols: List[float] = []
    amounts: List[float] = []
    adj_factors: List[Optional[float]] = []
    for d in dates:
        rec = daily_by_date.get(d, {}).get(code)
        if rec is None:
            continue
        raw_closes.append(rec["close"])
        vols.append(rec["vol"])
        amounts.append(float(rec.get("amount") or 0.0))
        adj_factors.append(adj_by_date.get(d, {}).get(code))
    if not raw_closes:
        return

    # 只复权 close(vol/amount 不动,是当日绝对量);缺因子退化 factor=1.0(qfq_closes 内部处理)。
    closes = qfq_closes(raw_closes, adj_factors)
    result = compute_form(closes, vols, amounts)

    sr.pct_chg = result.pct_chg
    sr.vol_multiple = result.vol_multiple
    sr.new_high_20d = result.new_high_20d
    sr.above_ma20 = result.above_ma20
    sr.pct_60d = result.pct_60d
    sr.vwap_ok = result.vwap_ok
    sr.had_limit_up = result.had_limit_up
