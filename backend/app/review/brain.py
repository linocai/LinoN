"""教练大脑注入(阶段3 Phase G4)。两条独立产物,严格分流,不混用:

  ① build_review_ref(code, *, trades_fn) → Optional[str]
     **客户端展示用**,带情绪第二人称(如"你上次 002463 也是没在 -5% 走,亏了 8.2%")。
     读 trades 里 broke_rule==1 的历史笔,按破止损/破时间取最近 1–2 笔拼一句话。
     无破线历史 → None(降级不硬造)。**此串绝不进 LLM prompt**(带情绪强措辞进 context 放大串味)。

  ② build_history_digest(*, trades_fn) → str
     **进 prompt 用**,中性统计摘要(如"近 5 笔:3 守线 / 2 破止损 / 1 破时间")。
     无历史 → 空串(prompt 不加【历史纪律】节,DeepSeek 照常判)。

铁律(plan §4.0 教练大脑注入):注入是"提供上下文"不是"改判定口径"——SYSTEM_PROMPT 的 guardrail
(见 prompt.py)明确"【历史纪律】仅供 text/plan 引用,不得据此改 verdict 判定标准"。
两串均由后端确定性拼(不让 LLM 查库)。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# review_ref 回溯的最大破线笔数(最近 1–2 笔)
_REVIEW_REF_MAX = 2
# history_digest 统计的最近笔数窗口
_DIGEST_WINDOW = 5


def _broke_reason(t: Dict[str, Any]) -> Optional[str]:
    """一笔破线的归因文案(破止损 / 破时间);未破 → None。"""
    if not int(t.get("broke_rule", 0)):
        return None
    if not int(t.get("kept_stop", 0)):
        return "没在 -5% 走"
    if not int(t.get("kept_time", 0)):
        return "持过 D4 没清"
    return "破了纪律"


def _pnl_disp(t: Dict[str, Any]) -> str:
    """收益展示串(取绝对值配'亏了'语气,如 '8.2%')。"""
    try:
        pnl = float(t.get("pnl", 0.0) or 0.0)
    except (TypeError, ValueError):
        pnl = 0.0
    return f"{abs(pnl):.1f}%"


def build_review_ref(
    code: str,
    *,
    trades_fn: Callable[[], List[Dict[str, Any]]],
) -> Optional[str]:
    """构建带情绪第二人称的历史教训引用(仅客户端展示,绝不进 LLM prompt)。

    读全部已闭合 trades 里 broke_rule==1 的历史笔,取最近 1–2 笔(按 close_time 倒序)
    拼一句话:"你上次 {name/code} 也是{破哪条},亏了 {pnl}%"。
    无破线历史 → None(coach 卡不显引用块)。
    """
    trades = list(trades_fn() or [])
    broke = [t for t in trades if int(t.get("broke_rule", 0))]
    if not broke:
        return None
    # 按 close_time 倒序取最近的
    broke.sort(key=lambda t: str(t.get("close_time", "")), reverse=True)
    picks = broke[:_REVIEW_REF_MAX]

    clauses: List[str] = []
    for t in picks:
        reason = _broke_reason(t)
        if reason is None:
            continue
        name = t.get("name") or str(t.get("code", ""))
        clauses.append(f"上次 {name} 也是{reason},亏了 {_pnl_disp(t)}")
    if not clauses:
        return None
    # "你" 开头一句,第二笔用"；还有"连接
    joined = "；还有".join(clauses)
    return f"你{joined}。别再让同样的死法重演。"


def build_history_digest(
    *,
    trades_fn: Callable[[], List[Dict[str, Any]]],
) -> str:
    """构建中性统计摘要(进 LLM prompt 的【历史纪律】节)。

    统计最近 _DIGEST_WINDOW 笔:守线 / 破止损 / 破时间 计数。
    如"近 5 笔:3 守线 / 2 破止损"。无历史 → 空串(prompt 不加【历史纪律】节)。
    **中性统计,不带情绪、不带第二人称、不含 review_ref 的强措辞。**
    """
    trades = list(trades_fn() or [])
    if not trades:
        return ""
    # 取最近 _DIGEST_WINDOW 笔(按 close_time 倒序)
    trades.sort(key=lambda t: str(t.get("close_time", "")), reverse=True)
    recent = trades[:_DIGEST_WINDOW]
    n = len(recent)
    kept = sum(1 for t in recent if not int(t.get("broke_rule", 0)))
    broke_stop = sum(
        1 for t in recent
        if int(t.get("broke_rule", 0)) and not int(t.get("kept_stop", 0))
    )
    broke_time = sum(
        1 for t in recent
        if int(t.get("broke_rule", 0)) and not int(t.get("kept_time", 0))
    )
    parts = [f"{kept} 守线"]
    if broke_stop:
        parts.append(f"{broke_stop} 破止损")
    if broke_time:
        parts.append(f"{broke_time} 破时间")
    return f"近 {n} 笔:" + " / ".join(parts)
