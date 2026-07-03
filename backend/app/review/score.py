"""纪律打分聚合(阶段3 Phase G1,纯确定性、零 LLM)。

plan §4.1 打分口径 + §4.2 短评模板单一事实源。核心:
  · ISO 周原语:iso_week / week_bounds / prev_week(禁止对周号做算术减一)。
  · _mechanical_comment(flags):机械短评单一事实源(G1 aggregate 与 G3 close_position 共用,
    不各写一份)。收 _compute_kept_flags 返回的 dict,产"守住铁律"/"破止损:跌穿 -5% 未走"/
    "破时间:持过 D4 未清"。
  · _red_flag_line(name, flags):redFlags 数组一条(带股票名的破线明细)。
  · aggregate_week(week, *, trades_fn, holdings_fn):读该周 trades 聚合 §4.1 全字段
    (discipline_rate/score/redFlags/每笔 ReviewTrade/近6周 trend/openHoldings),纯函数可注入。

铁律:只聚合 trades 表既有 kept_*/broke_rule(store._compute_kept_flags 已落库),
     不重算守线判定、不动 store.py 常量。openHoldings[].tradeDay 复用 count_holding_trade_days。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

# 近 6 个 ISO 周趋势
TREND_WEEKS = 6


# —— ISO 周原语 ————————————————————————————————————————————————————

def iso_week(dt: Any) -> str:
    """某日期/时刻所属 ISO 周标识 'YYYY-Www'(如 '2026-W27')。

    dt 支持 date / datetime / 'YYYY-MM-DD ...' / 'YYYY-MM-DD' 串。
    用 isocalendar() 的 (iso_year, iso_week)——**ISO 年可能与自然年不同**
    (如 2026-01-01 若在 W53/W01 边界,iso_year 会落到相邻年)。
    """
    d = _to_date(dt)
    iy, iw, _ = d.isocalendar()
    return f"{iy}-W{iw:02d}"


def week_bounds(week: str) -> tuple:
    """某 ISO 周的 (周一 date, 周日 date)。

    用 date.fromisocalendar(year, week, 1) 算周一(ISO 周一 = 第 1 天),
    周日 = 周一 + 6 天。week 形如 '2026-W27'。
    """
    year, wk = _split_week(week)
    monday = date.fromisocalendar(year, wk, 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def prev_week(week: str) -> str:
    """上一 ISO 周 'YYYY-Www'。

    方法论(定死):**当前周周一 − 1 天,再取 isocalendar()**——
    禁止对周号本身做算术减一('2026-W01' 的上一周是 '2025-W52',不是 '2026-W00';
    2025 年 ISO 共 52 周)。
    """
    monday, _ = week_bounds(week)
    prev = monday - timedelta(days=1)
    iy, iw, _ = prev.isocalendar()
    return f"{iy}-W{iw:02d}"


def _split_week(week: str) -> tuple:
    """'YYYY-Www' → (year:int, week:int)。"""
    y_str, w_str = week.split("-W")
    return int(y_str), int(w_str)


def _to_date(dt: Any) -> date:
    """归一为 date。支持 date / datetime / 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD'。"""
    if isinstance(dt, datetime):
        return dt.date()
    if isinstance(dt, date):
        return dt
    s = str(dt).strip()
    # close_time 形如 'YYYY-MM-DD HH:MM:SS';open_time 可能仅 'YYYY-MM-DD'
    head = s.split(" ")[0].split("T")[0]
    return datetime.strptime(head, "%Y-%m-%d").date()


# —— 机械短评单一事实源(G1 aggregate + G3 close_position 共用)——————————————

def _mechanical_comment(flags: Dict[str, Any]) -> str:
    """机械短评(单一事实源,plan §4.2 重要6)。收 _compute_kept_flags 返回的 dict。

    守线全绿(broke_rule==0)→ "守住铁律";
    破止损(not kept_stop)→ "破止损:跌穿 -5% 未走";
    破时间(not kept_time)→ "破时间:持过 D4 未清"。
    两条都破(极端)→ 两句拼接。broke_rule 但无法归因(理论不出现)→ 兜底"破纪律"。
    """
    broke = bool(flags.get("broke_rule"))
    if not broke:
        return "守住铁律"
    parts: List[str] = []
    if not flags.get("kept_stop"):
        parts.append("破止损:跌穿 -5% 未走")
    if not flags.get("kept_time"):
        parts.append("破时间:持过 D4 未清")
    return "；".join(parts) if parts else "破纪律"


def _red_flag_line(name: str, flags: Dict[str, Any], pnl_pct: Optional[float] = None) -> str:
    """redFlags 数组一条(带股票名的破线明细,plan §4.1.6)。

    破止损 → "{name} 破止损:{pnl}% 未在 -5% 走"(有 pnl 时带具体跌幅);
    破时间 → "{name} 破时间:持过 D4 未清"。
    仅在 broke_rule==1 时调用(调用方保证);两条都破 → 拼接。
    """
    parts: List[str] = []
    if not flags.get("kept_stop"):
        if pnl_pct is not None:
            parts.append(f"{name} 破止损:{_fmt_pnl(pnl_pct)} 未在 -5% 走")
        else:
            parts.append(f"{name} 破止损:跌穿 -5% 未走")
    if not flags.get("kept_time"):
        parts.append(f"{name} 破时间:持过 D4 未清")
    return "；".join(parts) if parts else f"{name} 破纪律"


def _fmt_pnl(pnl_pct: float) -> str:
    """收益百分比展示串(如 '+6.4%' / '-8.2%',保留 1 位小数,ASCII 号)。"""
    return f"{pnl_pct:+.1f}%"


# —— 周聚合(纯函数,可注入 trades_fn / holdings_fn 免联库)————————————————

def aggregate_week(
    week: str,
    *,
    trades_fn: Callable[[], List[Dict[str, Any]]],
    holdings_fn: Callable[[], List[Dict[str, Any]]],
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """聚合某 ISO 周复盘(plan §4.1 全字段)。纯函数、零 LLM。

    trades_fn() → 全部已闭合 trades 行(dict,含 code/close_time/kept_*/broke_rule/pnl/name)。
    holdings_fn() → 当前未平 positions 行(dict,含 code/name/buy_price/buy_date)。
    today 缺省 date.today()(供 openHoldings.tradeDay 计数 + trend 判空周)。

    返回 §4.3 Review 形状 dict(camelCase),含 openHoldings/sampleNote。
    """
    from app.calendar.trading_calendar import count_holding_trade_days

    today = today or date.today()
    all_trades = list(trades_fn() or [])

    # 本周 trades:close_time 落在该 ISO 周内
    week_trades = [t for t in all_trades if _trade_week(t) == week]
    n = len(week_trades)
    kept = sum(1 for t in week_trades if not int(t.get("broke_rule", 0)))
    discipline_rate = round(kept / n * 100) if n else 0
    score = discipline_rate  # 本阶段一比一

    # 环比:本周 − 上一 ISO 周
    pw = prev_week(week)
    prev_trades = [t for t in all_trades if _trade_week(t) == pw]
    prev_rate = _rate_of(prev_trades)
    rate_trend = discipline_rate - prev_rate if prev_trades else 0

    # redFlags + 每笔 ReviewTrade
    red_flags: List[str] = []
    review_trades: List[Dict[str, Any]] = []
    net_vals: List[float] = []                 # v1.3.0:本周非空净额行(供 netPnlTotal)
    for t in week_trades:
        flags = _flags_of(t)
        name = _trade_name(t)
        pnl_val = _pnl_of(t)
        broke = bool(int(t.get("broke_rule", 0)))
        if broke:
            red_flags.append(_red_flag_line(name, flags, pnl_val))
        net_amt = _net_pnl_of(t)               # 旧 NULL 行 → None(不兜 0.0,🟡1)
        if net_amt is not None:
            net_vals.append(net_amt)
        review_trades.append({
            "name": name,
            "code": str(t.get("code", "")),
            "pnl": _fmt_pnl(pnl_val),
            "netPnlAmount": net_amt,            # 元,可空(旧行 NULL → null,不是 0.0)
            "tag": "red" if broke else "good",
            "comment": _mechanical_comment(flags),
        })
    # netPnlTotal:周内无任何非空净额行 → None(D 端显"—");否则 = 非空行之和,四舍五入到分。
    net_pnl_total: Optional[float] = round(sum(net_vals), 2) if net_vals else None

    # 近 6 ISO 周 trend(无交易的周补 0)
    trend = _build_trend(week, all_trades)

    # 未平持仓(不计入本周 discipline_rate)
    open_holdings: List[Dict[str, Any]] = []
    for h in (holdings_fn() or []):
        open_holdings.append({
            "name": h.get("name") or str(h.get("code", "")),
            "code": str(h.get("code", "")),
            "buyPrice": float(h.get("buy_price", 0.0) or 0.0),
            "tradeDay": count_holding_trade_days(h.get("buy_date"), today),
        })

    sample_note = "本周 0 笔闭合" if n == 0 else f"本周 {n} 笔闭合"

    return {
        "week": week,
        "score": score,
        "disciplineRate": discipline_rate,
        "rateTrend": rate_trend,
        "redFlags": red_flags,
        "lessons": "",                 # 本阶段留空串(LLM 生成 lessons 属 OUT)
        "nextWeekNote": "",            # 端点层从 reviews 表补(store.get_review_note)
        "netPnlTotal": net_pnl_total,  # v1.3.0:周净额合计(元,可空:无非空净额行 → None)
        "trend": trend,
        "trades": review_trades,
        "openHoldings": open_holdings,
        "sampleNote": sample_note,
    }


# —— 内部工具 ————————————————————————————————————————————————————————

def _trade_week(t: Dict[str, Any]) -> str:
    """一笔 trade 归属 ISO 周(按 close_time)。"""
    return iso_week(t.get("close_time"))


def _flags_of(t: Dict[str, Any]) -> Dict[str, Any]:
    """从 trade 行取 kept_*/broke_rule(SQLite 存 0/1 int)。"""
    return {
        "kept_stop": bool(int(t.get("kept_stop", 0))),
        "kept_take": bool(int(t.get("kept_take", 0))),
        "kept_time": bool(int(t.get("kept_time", 0))),
        "broke_rule": bool(int(t.get("broke_rule", 0))),
    }


def _trade_name(t: Dict[str, Any]) -> str:
    """trade 展示名:name 优先,NULL/空 兜底回 code(plan §4.4 G2)。"""
    return t.get("name") or str(t.get("code", ""))


def _pnl_of(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("pnl", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _net_pnl_of(t: Dict[str, Any]) -> Optional[float]:
    """净收益金额(元,可空)。v1.3.0 迁移前的旧行无此列/值为 NULL → 返 None(不兜 0.0,🟡1)。

    ⚠️ 与 _pnl_of 不同:真 0 元收益(net_pnl_amount==0.0)必须原样返 0.0,只有
    键缺失 / SQLite NULL(dict 取到 None)才返 None——区分"没数据"vs"真 0 元"。
    """
    if "net_pnl_amount" not in t:
        return None
    raw = t.get("net_pnl_amount")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _rate_of(trades: List[Dict[str, Any]]) -> int:
    """一组 trades 的 discipline_rate(供环比上周用)。空 → 0。"""
    if not trades:
        return 0
    kept = sum(1 for t in trades if not int(t.get("broke_rule", 0)))
    return round(kept / len(trades) * 100)


def _build_trend(week: str, all_trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """近 TREND_WEEKS 个 ISO 周(含 week 自身,最早在前)的 discipline_rate。

    无交易的周补 value=0。label 取 'Wnn'(如 'W25')。
    """
    # 从当前周往前回溯 TREND_WEEKS 周
    weeks: List[str] = []
    cur = week
    for _ in range(TREND_WEEKS):
        weeks.append(cur)
        cur = prev_week(cur)
    weeks.reverse()  # 最早在前

    # 各周 rate
    by_week: Dict[str, List[Dict[str, Any]]] = {}
    for t in all_trades:
        by_week.setdefault(_trade_week(t), []).append(t)

    out: List[Dict[str, Any]] = []
    for wk in weeks:
        rate = _rate_of(by_week.get(wk, []))
        out.append({"label": f"W{_split_week(wk)[1]:02d}", "value": rate})
    return out
