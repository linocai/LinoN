"""深判编排(阶段2 Phase D3 / D4):补单票形态+资金+舆情 → 拼 prompt → 调 DeepSeek → DeepAnalysis。

plan §4.3:on-demand 对候选/在持仓深判。资金面一律截至上一交易日 EOD,返回带 fund_asof 标注。

单票数据补全:
  · 形态:ts_daily(code, 近 ~65 交易日)+ ts_adj_factor(前复权,阶段2.5)→
    app.screen.form 共享函数算放量倍数/创20日新高/站20日均线/60日涨幅/当日涨跌幅/换手。
  · 资金:ts_moneyflow(code, 近 3 日)主力净流入合计 + 当日。
  · 舆情:sentiment.fetch_sentiment(best-effort,失败 neutral 占位,不阻塞)。

降级铁律:缺 Tushare token → 形态/资金段标注缺失但仍调 DeepSeek(news neutral);
缺 DEEPSEEK_API_KEY/超时/非法 JSON → deepseek.analyze 返回降级占位卡。全链路不崩。
缺 adj_factor → 该票该日退化为原始价(不复权,不崩)。

可注入(单测免联网):daily_fn / moneyflow_fn / sentiment_fn / deepseek_fn / adj_factor_fn。
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from app.calendar.trading_calendar import prev_trading_day
from app.data import tushare_client as tc
from app.llm import deepseek, sentiment
from app.screen.form import compute_form, qfq_closes

logger = logging.getLogger(__name__)


def _bare(code: str) -> str:
    return re.sub(r"\D", "", code or "")[:6]


def fund_asof_date(now: Optional[date] = None) -> str:
    """资金面基准日(上一交易日 EOD)'YYYY-MM-DD'。

    moneyflow 是 EOD 数据,深判一律截至上一交易日 EOD(盘中资金未知)——
    无论今天是否交易日,都取严格上一交易日(prev_trading_day 不含今天)。
    """
    ref = now or date.today()
    return prev_trading_day(ref).strftime("%Y-%m-%d")


# —— 单票形态/资金补全(Tushare,降级不崩)——————————————————————————————

def _fetch_form(
    code: str, daily_fn: Callable, adj_factor_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """薄封装(签名基本不变,新增可选 adj_factor_fn 免破坏既有调用点)。

    近 ~65 交易日 daily + 复权因子 → qfq_closes 复权 → compute_form 统一算
    放量/新高/均线/60日涨幅/当日涨跌幅/换手。失败 → 占位 dict(标注缺失)。
    adj_factor_fn 缺省时用 tc.ts_adj_factor(单测/老调用点可不传,自动退化为
    该票该日缺因子 → qfq_closes 内部 factor=1.0 不复权,不崩)。
    """
    adj_factor_fn = adj_factor_fn or tc.ts_adj_factor
    today = date.today()
    end = today.strftime("%Y%m%d")
    start = (today - timedelta(days=130)).strftime("%Y%m%d")  # 自然日 130 ≈ 65 交易日余量
    res = daily_fn(code, start, end)
    if not res.ok or res.data is None or len(res.data) == 0:
        return {"close": "—", "pct_chg": "—", "vol_multiple": "—",
                "new_high_20d": "—", "above_ma20": "—", "pct_60d": "—",
                "turnover": "—", "vwap_ok": "—", "_degraded": True}
    df = res.data.sort_values("trade_date", ascending=False).reset_index(drop=True)
    raw_closes = [float(x) for x in df["close"].tolist()]
    vols = [float(x) for x in df["vol"].tolist()]
    trade_dates = [str(x) for x in df["trade_date"].tolist()]
    # amount(千元,阶段3.1 VWAP 信号1);单票 daily 有 amount 列,缺列/缺值退化 0.0(vwap_ok False)。
    amounts = [float(x or 0.0) for x in df["amount"].tolist()] if "amount" in df.columns else None

    # 复权因子(新→旧,与 raw_closes 同序对齐);拉取失败 → 全 None,qfq_closes 内部退化不复权。
    adj_map: Dict[str, float] = {}
    try:
        adj_res = adj_factor_fn(code, start, end)
        if adj_res.ok and adj_res.data is not None and len(adj_res.data) > 0:
            for _, r in adj_res.data.iterrows():
                af = r.get("adj_factor")
                if af is not None:
                    adj_map[str(r.get("trade_date"))] = float(af)
    except Exception as e:
        logger.warning("单票 adj_factor 拉取异常(降级不复权): %s", e)
    adj_factors: List[Optional[float]] = [adj_map.get(d) for d in trade_dates]

    closes = qfq_closes(raw_closes, adj_factors)
    today_close = closes[0] if closes else 0.0
    form = compute_form(closes, vols, amounts)   # 阶段3.1:传 amount 序列算 vwap_ok(信号1)

    return {
        "close": round(today_close, 2), "pct_chg": form.pct_chg,
        "vol_multiple": form.vol_multiple,
        "new_high_20d": form.new_high_20d, "above_ma20": form.above_ma20,
        "pct_60d": form.pct_60d if form.pct_60d is not None else "—",
        "turnover": "—",  # 单票换手需 daily_basic;深判形态以 daily 为主,换手非关键
        "vwap_ok": form.vwap_ok,   # 收盘站 VWAP(信号1,喂 LLM 判量价形态)
        "_degraded": False,
    }


def _fetch_fund(code: str, moneyflow_fn: Callable) -> Dict[str, Any]:
    """近 ~5 交易日 moneyflow → 近 3 日主力净流入合计 + 当日。失败 → 占位(标注缺失)。"""
    today = date.today()
    end = today.strftime("%Y%m%d")
    start = (today - timedelta(days=12)).strftime("%Y%m%d")
    res = moneyflow_fn(code, start, end)
    if not res.ok or res.data is None or len(res.data) == 0:
        return {"net_mf_3d": "—", "net_mf_amount": "—", "_degraded": True}
    df = res.data.sort_values("trade_date", ascending=False).reset_index(drop=True)
    amounts = [float(x) for x in df["net_mf_amount"].tolist()]
    net_today = round(amounts[0], 2) if amounts else 0.0
    net_3d = round(sum(amounts[:3]), 2) if amounts else 0.0
    return {"net_mf_3d": net_3d, "net_mf_amount": net_today, "_degraded": False}


# —— 编排 ————————————————————————————————————————————————————————

def analyze_stock(
    code: str,
    name: str = "",
    sector: str = "",
    *,
    mode: str = "candidate",
    pnl_pct: Optional[float] = None,
    trade_day: Optional[int] = None,
    question: Optional[str] = None,
    history_digest: Optional[str] = None,
    now: Optional[date] = None,
    daily_fn: Optional[Callable] = None,
    moneyflow_fn: Optional[Callable] = None,
    sentiment_fn: Optional[Callable] = None,
    deepseek_fn: Optional[Callable] = None,
    adj_factor_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """对单票深判,返回 (analysis: DeepAnalysis dict, fund_asof: str)。

    mode='candidate' 选股深判 / mode='coach' 在持仓中间地带二元建议。
    history_digest(阶段3 G4):中性历史纪律统计串,非空时经 build_user_prompt 注入 prompt
    的【历史纪律】节(guardrail 见 SYSTEM_PROMPT:仅供引用增说服力,不改 verdict 判定口径)。
    **注入的是中性 digest,绝不是带情绪的 review_ref**(两路径分流)。
    全链路降级不崩:任一数据段失败 → 占位标注;DeepSeek 失败 → 降级占位卡。
    可注入 *_fn 免单测联网(adj_factor_fn 阶段2.5 新增,沿 daily_fn 模式)。
    """
    daily_fn = daily_fn or tc.ts_daily
    moneyflow_fn = moneyflow_fn or tc.ts_moneyflow
    sentiment_fn = sentiment_fn or sentiment.fetch_sentiment
    deepseek_fn = deepseek_fn or deepseek.analyze
    adj_factor_fn = adj_factor_fn or tc.ts_adj_factor

    bare = _bare(code)
    fund_asof = fund_asof_date(now)

    form = _fetch_form(bare, daily_fn, adj_factor_fn)
    fund = _fetch_fund(bare, moneyflow_fn)
    try:
        news = sentiment_fn(bare)
    except Exception as e:
        logger.warning("舆情编排异常(降级): %s", e)
        news = {"titles": [], "note": "未获取到舆情,仅技术+资金判定", "degraded": True}

    context: Dict[str, Any] = {
        "mode": mode, "code": bare, "name": name or bare, "sector": sector or "—",
        "form": form, "fund": fund, "news": news, "fund_asof": fund_asof,
        "pnl_pct": pnl_pct, "trade_day": trade_day, "question": question,
        # 中性历史纪律统计(G4);仅非空时 build_user_prompt 加【历史纪律】节。
        # 绝不放 review_ref(情绪串)——那只回客户端展示,不进 prompt。
        "history_digest": history_digest or "",
    }

    try:
        analysis = deepseek_fn(context)
    except Exception as e:   # deepseek 内部已兜底,这里再兜一层
        logger.warning("DeepSeek 编排异常(降级): %s", e)
        analysis = deepseek.degraded_analysis(f"编排异常 {type(e).__name__}")

    return {"analysis": analysis, "fund_asof": fund_asof}


def coach_advice_from_analysis(analysis: Dict[str, Any]) -> str:
    """从 DeepAnalysis 的 verdict 派生中间地带二元 advice('拿'|'清')。

    plan §4.3:拿→观望/可进语义,清→不进。verdict='不进' → '清';否则 '拿'。
    """
    return "清" if analysis.get("verdict") == "不进" else "拿"
