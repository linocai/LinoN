"""选股流水线:粗筛 → 排序 → 截断(阶段2 Phase D1)。

输入 MarketSnapshot(归一后的 StockRow 列表),输出对齐 Candidate 形状的 dict 列表
(逐字段对齐 design_handoff_linon/Models.swift 的 Candidate,见 plan §4.3):

  {rank, name, code, sector, tag, price, chg, volMultiple, volPct, flow, turnover, warn?}

铁律(plan §4.1):
  · 黑名单 / 高位线 / 截断 是硬规则(二元)。
  · 粗筛宽条件是"宁松勿紧"经验默认值(rules.py 内,可迭代,不卡生死)。
  · 排序机械加权,放量权重最大。
  · candidates 列表里 analysis 省略(深判 on-demand,不批量)。

无 token / 拉取失败 → run_pipeline 返回 (rows=[], degraded=True, reason)。绝不抛崩。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.screen import rules
from app.screen.fetch import MarketSnapshot, StockRow, fetch_market_snapshot


def _fmt_chg(pct: float) -> str:
    """涨跌幅展示串,带正负号。"""
    return f"{pct:+.2f}%"


def _fmt_vol_multiple(x: float) -> str:
    return f"{x:.1f}x"


def _vol_pct(vol_multiple: float) -> int:
    """放量进度 0–100(展示用)。放量倍数 1x→0、3x 及以上→100(线性夹紧)。

    设计用 ≥80 显绿。3x 封顶给一个直观刻度:(mult-1)/2*100,夹 [0,100]。
    """
    pct = (vol_multiple - 1.0) / 2.0 * 100.0
    return int(max(0, min(100, round(pct))))


def _fmt_flow(net_mf_wan: float) -> str:
    """主力净流入展示串(万元 → 亿/万)。"""
    yi = net_mf_wan / 1e4
    if abs(yi) >= 1.0:
        return f"{yi:+.2f}亿"
    return f"{net_mf_wan:+.0f}万"


def _fmt_turnover(pct: float) -> str:
    return f"{pct:.1f}%"


def passes_coarse(sr: StockRow) -> bool:
    """粗筛宽条件(经验默认值,plan §4.1;**非生死阈,宁松勿紧**)。

    放量 ≥ VOL_MULTIPLE_MIN 且 主力近 3 日净流入 > 0 且 当日非大幅净流出 且
    (创 20 日新高 或 站 20 日均线 任一即可)。任一不满足则粗筛淘汰。
    门槛宽:把"值不值得进"留给 LLM 深判,这里只挡明显不相关的票。
    """
    if sr.vol_multiple < rules.VOL_MULTIPLE_MIN:
        return False
    if sr.net_mf_3d <= 0:
        return False
    if sr.net_mf_amount < rules.DAY_OUTFLOW_FLOOR:
        return False
    if not (sr.new_high_20d or sr.above_ma20):
        return False
    return True


def _sector_of(sr: StockRow) -> str:
    """板块展示(用行业字段占位;免费板块归类，无则空)。"""
    return sr.industry or "—"


def build_candidates(snapshot: MarketSnapshot) -> List[Dict[str, Any]]:
    """对快照执行 黑名单 → 高位线 → 粗筛 → 排序(全量),产候选 dict 列表(未截断)。

    截断在端点运行时按 free_slots 做(plan D2);这里产**已排序的全部合格候选**
    并打 rank(1 起),端点再 prefix(5×free_slots)。
    """
    survivors: List[StockRow] = []
    for sr in snapshot.rows:
        # 黑名单硬排除(二元)
        if rules.is_blacklisted(sr.code, sr.name, sr.industry):
            continue
        # 高位线(二元):≥100% 排除
        verdict = rules.high_position_verdict(sr.pct_60d)
        if verdict == "exclude":
            continue
        # 粗筛宽条件(经验默认值)
        if not passes_coarse(sr):
            continue
        survivors.append(sr)

    if not survivors:
        return []

    # 机械排序(阶段3.1 八因子:放量权重最大 + VWAP/市值弹性/近期活跃/换手健康 + 单日软闸罚项)
    scores = rules.rank_score(
        vol_multiples=[s.vol_multiple for s in survivors],
        fund_3d=[s.net_mf_rate_3d for s in survivors],  # 相对口径(占成交额%),免大盘股偏置
        turnovers=[s.turnover for s in survivors],
        pct_60ds=[(s.pct_60d if s.pct_60d is not None else 0.0) for s in survivors],
        vwap_oks=[s.vwap_ok for s in survivors],                 # 信号1
        total_mv_yis=[s.total_mv_yi for s in survivors],         # 信号4
        actives=[s.had_limit_up for s in survivors],             # 信号5
        day_pcts=[s.pct_chg for s in survivors],                 # 信号6(今日涨幅)
    )
    # 展示分 score:对【全部 survivors】原始加权分 min-max 归一到 [SCORE_FLOOR,100](截断前,
    # 与 rank 同源同序、只展示不改排序;全相等/单票 → 中性满分 100;见 plan §4.0 打分展示口径)。
    display_scores = _normalize_scores(scores)

    ranked = sorted(
        zip(survivors, scores, display_scores), key=lambda t: t[1], reverse=True
    )

    out: List[Dict[str, Any]] = []
    for i, (sr, _raw, disp) in enumerate(ranked, start=1):
        warn = _merge_warn(sr)
        out.append({
            "rank": i,
            "name": sr.name,
            "code": sr.code,
            "sector": _sector_of(sr),
            "tag": "放量突破" if sr.new_high_20d else "站上均线",
            "price": round(sr.close, 2),
            "chg": _fmt_chg(sr.pct_chg),
            "volMultiple": _fmt_vol_multiple(sr.vol_multiple),
            "volPct": _vol_pct(sr.vol_multiple),
            "flow": _fmt_flow(sr.net_mf_3d),
            "turnover": _fmt_turnover(sr.turnover),
            "warn": warn,   # None → 客户端不降级
            "score": disp,  # 阶段3.1:当日相对分(展示,不参与排序/截断)
        })
    return out


def _merge_warn(sr: StockRow) -> Optional[str]:
    """合并 60 日高位 warn(信号无关,现有) + 单日暴涨软闸 warn(信号6);仍单一可选字符串。

    两条都命中 → 拼接展示("；"分隔);只命中一条 → 该条;都不命中 → None。
    plan §4.1:warn 仍是 Optional[str],客户端 CandidateRow 已有琥珀降级逻辑,不改契约。
    """
    high = rules.high_warn_text(sr.pct_60d)          # ≥50% 且 <100% → 非空
    surge = rules.day_surge_warn_text(sr.pct_chg)    # 今日 ≥9% → 非空
    parts = [w for w in (high, surge) if w]
    if not parts:
        return None
    return "；".join(parts)


def _normalize_scores(raw_scores: List[float]) -> List[int]:
    """把原始加权分 min-max 归一到 [SCORE_FLOOR, 100] 取整(展示分,plan §4.0)。

    · 对传入的【全部原始分】(截断前)归一——与 rank 同源同序,单调递增变换,不改次序。
    · 全相等/单票(max-min≈0)→ 统一给中性满分 100(避免除零 + "唯一/并列最优")。
    · floor 抬到 SCORE_FLOOR(=10)而非 0:避免末位恒 0 分、两票必然 100/0 的观感矛盾。
    """
    if not raw_scores:
        return []
    lo, hi = min(raw_scores), max(raw_scores)
    floor = rules.SCORE_FLOOR
    if hi - lo < 1e-12:
        return [100] * len(raw_scores)   # 全相等/单票 → 中性满分
    span = hi - lo
    return [int(round(floor + (s - lo) / span * (100 - floor))) for s in raw_scores]


def run_pipeline(
    trade_date_yyyymmdd: Optional[str] = None,
    *,
    snapshot_fn=None,
) -> Tuple[List[Dict[str, Any]], bool, str, str]:
    """端到端:拉全市场快照 → 粗筛排序 → 候选 dict 列表(未截断)。

    返回 (rows, degraded, reason, trade_date)。
      · 无 token/拉取失败 → ([], True, reason, trade_date)(degraded,空列表,不崩)。
      · 成功但当日零合格 → ([], False, "no_candidates", trade_date)(唯一的"歇")。
    snapshot_fn 可注入(测试用,免联网);默认 fetch_market_snapshot。
    trade_date_yyyymmdd 缺省时由调用方决定(D2 端点传 EOD 基准日)。
    """
    snapshot_fn = snapshot_fn or fetch_market_snapshot
    td = trade_date_yyyymmdd or datetime.now().strftime("%Y%m%d")
    try:
        snap = snapshot_fn(td)
    except Exception as e:  # 任何异常都不崩
        return [], True, f"快照拉取异常: {e}", _disp(td)

    if not snap.ok:
        return [], True, snap.reason, snap.trade_date

    rows = build_candidates(snap)
    if not rows:
        return [], False, "no_candidates", snap.trade_date
    return rows, False, "ok", snap.trade_date


def _disp(yyyymmdd: str) -> str:
    s = str(yyyymmdd)
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s
