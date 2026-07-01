"""信号回测回填(阶段2.5 F3,plan §4.0/§4.3)。

对已产生 >= 3 个交易日的候选,回填其后 3 个交易日的实际涨跌(ret_3d),供 §4.1
三维度统计(排序分位分层收益 / tag 胜率 / DeepSeek verdict 命中率)使用。

【回测收益口径,致命2修订,数学正确】:
  ret_3d = entry_date 后 3 个交易日 daily.pct_chg 累乘:
    ret_3d = (∏_{i=1..3}(1 + pct_chg_i/100) − 1) × 100
  daily.pct_chg 本身即复权调整后的真实日收益(Tushare 已在源头处理除权),除权日
  天然正确,【不需要为回测另拉 adj_factor】,也不做"entry/exit 各自 qfq 再比"
  (那样两天基准日不同、基准不约分,窗口内除权即算错)。
  entry_close/exit_close 只存原始 daily.close 供人工核对展示,不参与 ret_3d 计算。

【回填防重,不靠内存】:每次调用 store.pending_backfill_entries(today) 扫描
  candidates 有、candidate_outcomes 缺、且 entry_date 已过去 >= 3 个交易日的候选,
  批量补齐;天然靠 UNIQUE(entry_date,code) 幂等,重启/错过窗口次日自动补,不永久漏。

缺某日/某票 daily → 该票跳过不落(不崩)。
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from app.calendar.trading_calendar import next_trading_day
from app.data import tushare_client as tc
from app.db import store

logger = logging.getLogger(__name__)


def _bare(ts_code: str) -> str:
    return re.sub(r"\D", "", str(ts_code or ""))[:6]


def _default_daily_all_fn(trade_date_yyyymmdd: str):
    return tc.ts_daily_all(trade_date_yyyymmdd)


def _next_n_trading_dates(entry_date_iso: str, n: int) -> List[str]:
    """entry_date(含,'YYYY-MM-DD')之后第 1..n 个交易日,返回 'YYYYMMDD' 列表(升序)。"""
    from app.calendar.trading_calendar import _to_date

    cur = _to_date(entry_date_iso)
    out: List[str] = []
    for _ in range(n):
        cur = next_trading_day(cur)
        out.append(cur.strftime("%Y%m%d"))
    return out


def run_backfill(
    now: Optional[datetime] = None,
    *,
    daily_all_fn: Optional[Callable[[str], Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """扫描待回填候选批,拉后 3 个交易日 daily 累乘 pct_chg 算 ret_3d,落库。

    daily_all_fn 可注入(单测免联网):签名 (trade_date_yyyymmdd) -> TushareResult。
    返回 {filled, skipped, entries_scanned}(供日志/测试断言)。失败/缺数据不崩。
    """
    daily_all_fn = daily_all_fn or _default_daily_all_fn
    today = (now or datetime.now()).date() if isinstance(now, datetime) else (now or date.today())

    pending = store.pending_backfill_entries(today, min_trade_days=4, db_path=db_path)
    if not pending:
        return {"filled": 0, "skipped": 0, "entries_scanned": 0}

    # 按 entry_date 分组,同一 entry_date 的候选共用同一批"后 3 交易日" daily 拉取。
    by_entry: Dict[str, List[Dict[str, str]]] = {}
    for row in pending:
        by_entry.setdefault(row["entry_date"], []).append(row)

    filled = 0
    skipped = 0
    for entry_date, rows in by_entry.items():
        exit_dates = _next_n_trading_dates(entry_date, 3)   # ['YYYYMMDD'] x3,升序
        exit_date_iso = exit_dates[-1]
        exit_date_disp = f"{exit_date_iso[0:4]}-{exit_date_iso[4:6]}-{exit_date_iso[6:8]}"

        # 拉 3 个交易日全市场 daily(逐日),按 code 取 pct_chg/close。缺某日 → 该日对所有票跳过。
        pct_by_code: Dict[str, List[float]] = {r["code"]: [] for r in rows}
        entry_close_by_code: Dict[str, float] = {}
        exit_close_by_code: Dict[str, float] = {}

        # entry_date 当天 close(供 entry_close 人工核对)
        entry_yyyymmdd = entry_date.replace("-", "")
        entry_res = daily_all_fn(entry_yyyymmdd)
        if entry_res.ok and entry_res.data is not None:
            for _, r in entry_res.data.iterrows():
                c = _bare(r.get("ts_code"))
                if c in pct_by_code:
                    entry_close_by_code[c] = float(r.get("close") or 0.0)

        any_day_failed_for_code: Dict[str, bool] = {r["code"]: False for r in rows}
        for i, d in enumerate(exit_dates):
            res = daily_all_fn(d)
            if not res.ok or res.data is None:
                logger.warning("回测回填:daily 拉取失败(entry_date=%s, day=%s): %s",
                                entry_date, d, res.reason)
                for code in pct_by_code:
                    any_day_failed_for_code[code] = True
                continue
            day_map: Dict[str, tuple] = {}
            for _, r in res.data.iterrows():
                c = _bare(r.get("ts_code"))
                day_map[c] = (float(r.get("pct_chg") or 0.0), float(r.get("close") or 0.0))
            for code in pct_by_code:
                rec = day_map.get(code)
                if rec is None:
                    any_day_failed_for_code[code] = True
                    continue
                pct_by_code[code].append(rec[0])
                if d == exit_date_iso:
                    exit_close_by_code[code] = rec[1]

        for row in rows:
            code = row["code"]
            if any_day_failed_for_code.get(code) or len(pct_by_code[code]) != 3:
                skipped += 1
                continue
            if code not in entry_close_by_code or code not in exit_close_by_code:
                skipped += 1
                continue
            ret = 1.0
            for pct in pct_by_code[code]:
                ret *= (1.0 + pct / 100.0)
            ret_3d = round((ret - 1.0) * 100.0, 4)

            verdict = store.get_verdict(entry_date, code, db_path=db_path)
            store.upsert_candidate_outcome({
                "entry_date": entry_date, "code": code, "name": row.get("name", code),
                "rank": row.get("rank", 0), "tag": row.get("tag"), "verdict": verdict,
                "entry_close": entry_close_by_code[code], "exit_date": exit_date_disp,
                "exit_close": exit_close_by_code[code], "ret_3d": ret_3d,
            }, db_path=db_path)
            filled += 1

    return {"filled": filled, "skipped": skipped, "entries_scanned": len(pending)}


# —— 回测统计聚合(阶段2.5 F4,plan §4.1:排序分位分层 / tag 胜率 / verdict 命中率)——

_RANK_TIERS = (("1-5", 1, 5), ("6-10", 6, 10), ("11+", 11, None))
_SAMPLE_SMALL_THRESHOLD = 5   # 样本量小于此值时诚实标注"仅供参考"


def _tier_of(rank: int) -> str:
    for label, lo, hi in _RANK_TIERS:
        if hi is None:
            if rank >= lo:
                return label
        elif lo <= rank <= hi:
            return label
    return "11+"


def _agg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """一组 outcome 行 → {n, avg_ret_3d, win_rate}。空组不应被调用(调用方需过滤)。"""
    n = len(rows)
    avg = sum(r["ret_3d"] for r in rows) / n
    wins = sum(1 for r in rows if r["ret_3d"] > 0)
    return {"n": n, "avg_ret_3d": round(avg, 2), "win_rate": round(wins / n, 4)}


def compute_outcome_stats(since: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """聚合 candidate_outcomes → §4.1 三维度统计(端点聚合返回,不预计算落库)。

    · by_rank_tier:按 rank 分层(1-5/6-10/11+),各层 avg_ret_3d + win_rate。
    · by_tag:按 tag 分组(放量突破/站上均线等)。
    · by_verdict:仅统计 verdict 非空的行(深判 on-demand,样本天然稀疏)。
    空表 → 各分组空数组,sample_total=0,note 标"暂无回测样本"。样本量小于阈值
    (<5)的分组不剔除,但整体 note 会诚实标注"部分分组样本量小,仅供参考"。
    """
    rows = store.list_outcomes(since=since, db_path=db_path)
    sample_total = len(rows)
    if sample_total == 0:
        return {
            "sample_total": 0, "since": since or "",
            "by_rank_tier": [], "by_tag": [], "by_verdict": [],
            "note": "暂无回测样本",
        }

    by_tier: Dict[str, List[Dict[str, Any]]] = {}
    by_tag: Dict[str, List[Dict[str, Any]]] = {}
    by_verdict: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        tier = _tier_of(int(r["rank"]))
        by_tier.setdefault(tier, []).append(r)
        tag = r.get("tag") or "—"
        by_tag.setdefault(tag, []).append(r)
        verdict = r.get("verdict")
        if verdict:
            by_verdict.setdefault(verdict, []).append(r)

    tier_order = [label for label, _, _ in _RANK_TIERS]
    out_tier = [
        {"tier": t, **_agg(by_tier[t])} for t in tier_order if t in by_tier
    ]
    out_tag = [{"tag": t, **_agg(rs)} for t, rs in sorted(by_tag.items())]
    out_verdict = [{"verdict": v, **_agg(rs)} for v, rs in sorted(by_verdict.items())]

    small_sample = sample_total < _SAMPLE_SMALL_THRESHOLD or (
        by_verdict and all(len(rs) < _SAMPLE_SMALL_THRESHOLD for rs in by_verdict.values())
    )
    note = "样本量小于阈值,仅供参考" if small_sample else ""
    if not by_verdict:
        note = (note + ";" if note else "") + "verdict 维度样本不足(深判 on-demand,尚无深判记录)"

    return {
        "sample_total": sample_total, "since": since or "",
        "by_rank_tier": out_tier, "by_tag": out_tag, "by_verdict": out_verdict,
        "note": note,
    }
