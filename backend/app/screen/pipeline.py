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


def passes_coarse(sr: StockRow, cfg: Optional[Dict[str, Any]] = None) -> bool:
    """粗筛宽条件(经验默认值,plan §4.1;**非生死阈,宁松勿紧**)。

    量比(官方 daily_basic.volume_ratio)≥ vol_ratio_min(v1.3.1 A2 改口径,旧用
    自算放量倍数)且 主力近 3 日净流入 > 0 且 当日非大幅净流出 且
    (创 20 日新高 或 站 20 日均线 任一即可)。任一不满足则粗筛淘汰。
    门槛宽:把"值不值得进"留给 LLM 深判,这里只挡明显不相关的票。

    v1.3.1 Phase B:cfg 缺省(None)→ 直接回落 rules 模块级常量(VOL_RATIO_MIN/
    DAY_OUTFLOW_FLOOR),行为与改前逐字节一致,保批1测试/旧调用不回归。cfg 传入
    (resolve 后全量)时用 cfg["vol_ratio_min"/"day_outflow_floor"]。
    """
    if cfg is not None:
        vol_ratio_min = cfg.get("vol_ratio_min", rules.VOL_RATIO_MIN)
        day_outflow_floor = cfg.get("day_outflow_floor", rules.DAY_OUTFLOW_FLOOR)
    else:
        vol_ratio_min = rules.VOL_RATIO_MIN
        day_outflow_floor = rules.DAY_OUTFLOW_FLOOR
    if sr.volume_ratio < vol_ratio_min:
        return False
    if sr.net_mf_3d <= 0:
        return False
    if sr.net_mf_amount < day_outflow_floor:
        return False
    if not (sr.new_high_20d or sr.above_ma20):
        return False
    return True


def _sector_of(sr: StockRow) -> str:
    """板块展示(用行业字段占位;免费板块归类，无则空)。"""
    return sr.industry or "—"


def build_candidates(
    snapshot: MarketSnapshot, cfg: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """对快照执行 黑名单 → 粗筛 → 排序(全量),产候选 dict 列表(未截断)。

    v1.3.1 A1/A2:高位线 ≥100% 硬排除已删(不再有单独的"高位线"过滤阶段,只在
    展示层标注 warnLevel,见 _merge_warn/_warn_level)。截断在端点运行时做
    (v1.3.0 起固定 rules.CANDIDATE_LIMIT=20,不再随 free_slots 变化、不再满仓闭门);
    这里产**已排序的全部合格候选**并打 rank(1 起),端点再 prefix(rules.CANDIDATE_LIMIT)。

    v1.3.1 Phase B:cfg 缺省(None)→ 回落 rules 默认常量(passes_coarse/rank_score 内部
    各自处理,行为与改前逐字节一致,保批1测试/旧调用不回归)。cfg 传入(resolve 后全量)
    时显式穿参 passes_coarse/rank_score/_merge_warn/_warn_level(生效机制,禁 monkeypatch)。
    """
    survivors: List[StockRow] = []
    for sr in snapshot.rows:
        # 黑名单硬排除(二元)
        if rules.is_blacklisted(sr.code, sr.name, sr.industry):
            continue
        # 粗筛宽条件(经验默认值);高位线不再在此过滤,只在 warn 分级展示(v1.3.1 A1)
        if not passes_coarse(sr, cfg):
            continue
        survivors.append(sr)

    if not survivors:
        return []

    # 机械排序(v1.3.1 九因子:量比权重最大 + 位置健康/换手健康/VWAP/横盘突破/市值弹性/
    # 近期活跃/资金面 + 单日软闸罚项)
    scores = rules.rank_score(
        vol_ratios=[s.volume_ratio for s in survivors],          # 官方量比(v1.3.1 改口径)
        fund_3d=[s.net_mf_rate_3d for s in survivors],  # 相对口径(占成交额%),免大盘股偏置
        turnovers=[s.turnover for s in survivors],
        pos_healths=[s.pos_health for s in survivors],           # 位置健康(v1.3.1 新增)
        vwap_oks=[s.vwap_ok for s in survivors],                 # 信号1
        breakout_oks=[s.breakout_ok for s in survivors],         # 信号7(v1.3.1 新增)
        total_mv_yis=[s.total_mv_yi for s in survivors],         # 信号4
        actives=[s.had_limit_up for s in survivors],             # 信号5
        day_pcts=[s.pct_chg for s in survivors],                 # 信号6(今日涨幅)
        cfg=cfg,
    )
    # 展示分 score:对【全部 survivors】原始加权分绝对化 clamp(×100,[0,100])(v1.4.1
    # Phase C1,与 rank 同源同序、只展示不改排序;跨天可比,见 plan §4.2 打分展示口径)。
    display_scores = _normalize_scores(scores)

    ranked = sorted(
        zip(survivors, scores, display_scores), key=lambda t: t[1], reverse=True
    )

    out: List[Dict[str, Any]] = []
    for i, (sr, _raw, disp) in enumerate(ranked, start=1):
        warn = _merge_warn(sr, cfg)
        cand: Dict[str, Any] = {
            "rank": i,
            "name": sr.name,
            "code": sr.code,
            "sector": _sector_of(sr),
            "tag": "放量突破" if sr.new_high_20d else "站上均线",
            "price": round(sr.close, 2),
            "chg": _fmt_chg(sr.pct_chg),
            "volMultiple": _fmt_vol_multiple(sr.vol_multiple),   # 展示用自算放量倍数(解耦不变)
            "volPct": _vol_pct(sr.vol_multiple),
            "flow": _fmt_flow(sr.net_mf_3d),
            "turnover": _fmt_turnover(sr.turnover),
            "warn": warn,   # None → 客户端不降级
            "score": disp,  # 阶段3.1:当日相对分(展示,不参与排序/截断)
        }
        # v1.3.1 A2.5:warnLevel(≥100%→"high",其余 warn 场景→"amber",无→省略键)
        level = _warn_level(sr, cfg)
        if level:
            cand["warnLevel"] = level
        out.append(cand)
    return out


def _merge_warn(sr: StockRow, cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """合并 60 日高位 warn(信号无关,现有) + 单日暴涨软闸 warn(信号6);仍单一可选字符串。

    两条都命中 → 拼接展示("；"分隔);只命中一条 → 该条;都不命中 → None。
    plan §4.1:warn 仍是 Optional[str],客户端 CandidateRow 已有琥珀降级逻辑,不改契约。
    """
    high = rules.high_warn_text(sr.pct_60d)              # ≥50%(含≥100%) → 非空(v1.3.1 A1 改;
                                                          # 高位分级阈不进配置,不吃 cfg)
    surge = rules.day_surge_warn_text(sr.pct_chg, cfg)   # 今日 ≥day_surge_warn_pct → 非空
    parts = [w for w in (high, surge) if w]
    if not parts:
        return None
    return "；".join(parts)


def _warn_level(sr: StockRow, cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """warnLevel 分级(v1.3.1 A2.5):≥100% 高位 → 'high'(红级);[50,100%) → 'amber'。

    高位分级与单日暴涨 warn 并列出现时,级别取最高(有 high 则 high,否则有 amber
    才 amber,否则 None)——见 plan §4.1 第4层:high_position_warn_level 已是最高优先级
    的红/琥珀,单日暴涨软闸仅在无高位分级时才把级别抬到 amber。
    """
    high_level = rules.high_warn_level(sr.pct_60d)   # 'high' / 'amber' / None(阈不进配置)
    if high_level:
        return high_level
    if rules.day_surge_warn_text(sr.pct_chg, cfg):
        return "amber"
    return None


def _normalize_scores(raw_scores: List[float]) -> List[int]:
    """展示分绝对口径(v1.4.1 Phase C1,plan §4.2):`clamp(原始加权分 × 100, 0, 100)`。

    逐票独立,不再依赖池内 min/max——跨天可比、弱势日诚实显低分(甚至 0)。
    正权部分(8 因子权重归一和=1.0)恒落 [0,1],day_surge 罚项使总分可下探到负值;
    负分一律夹 0(展示语义:0 分=最差,不显负数),上界 100 clamp 兜死。
    旧 SCORE_FLOOR 语义(避免末位恒 0)在绝对口径下取消——弱势票诚实显低分是刻意的。
    """
    return [int(round(max(0.0, min(100.0, s * 100)))) for s in raw_scores]


def run_pipeline(
    trade_date_yyyymmdd: Optional[str] = None,
    *,
    snapshot_fn=None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], bool, str, str]:
    """端到端:拉全市场快照 → 粗筛排序 → 候选 dict 列表(未截断)。

    返回 (rows, degraded, reason, trade_date)。
      · 无 token/拉取失败 → ([], True, reason, trade_date)(degraded,空列表,不崩)。
      · 成功但当日零合格 → ([], False, "no_candidates", trade_date)(唯一的"歇")。
    snapshot_fn 可注入(测试用,免联网);默认 fetch_market_snapshot。
    trade_date_yyyymmdd 缺省时由调用方决定(D2 端点传 EOD 基准日)。

    v1.3.1 Phase B:cfg(resolve 后全量活配置)显式穿参给 build_candidates(粗筛/排序/warn
    用)+ 默认 snapshot_fn(fetch_market_snapshot,粗筛前的 pos_health/breakout_ok 派生用)。
    **注入的测试替身 snapshot_fn 只按 1 参(td)调用**(保 test_screen.py 现有 `def _fail(td)`
    等注入函数不回归)——cfg 只在使用【默认】fetch_market_snapshot 时才穿进快照拉取层;
    显式注入 snapshot_fn 时 cfg 仍会传给 build_candidates(粗筛/排序生效),只是快照拉取
    本身不吃 cfg(测试场景本就用样例 StockRow,不经真实 fetch 阈值路径)。cfg 缺省 None
    → 全链路回落 rules 默认常量,行为与改前逐字节一致,保批1测试/旧调用不回归。
    """
    injected = snapshot_fn is not None
    snapshot_fn = snapshot_fn or fetch_market_snapshot
    td = trade_date_yyyymmdd or datetime.now().strftime("%Y%m%d")
    try:
        snap = snapshot_fn(td) if injected else snapshot_fn(td, cfg=cfg)
    except Exception as e:  # 任何异常都不崩
        return [], True, f"快照拉取异常: {e}", _disp(td)

    if not snap.ok:
        return [], True, snap.reason, snap.trade_date

    rows = build_candidates(snap, cfg)
    if not rows:
        return [], False, "no_candidates", snap.trade_date
    return rows, False, "ok", snap.trade_date


def _disp(yyyymmdd: str) -> str:
    s = str(yyyymmdd)
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s
