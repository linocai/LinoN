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
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from app.calendar.trading_calendar import prev_trading_day
from app.data import intraday
from app.data import tushare_client as tc
from app.data.realtime import Quote
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
                "turnover": "—", "vwap_ok": "—", "_degraded": True,
                "prev5_avg_vol": 0.0}
    df = res.data.sort_values("trade_date", ascending=False).reset_index(drop=True)
    raw_closes = [float(x) for x in df["close"].tolist()]
    vols = [float(x) for x in df["vol"].tolist()]
    trade_dates = [str(x) for x in df["trade_date"].tolist()]
    # 前5交易日日均量(手,不复权;v1.4 Phase B 盘中量能折算基准)。本字段只在盘中
    # coach 组装快照时被消费(analyze_stock/chat_stock 的 is_trading 分支),此时
    # Tushare daily 当日行尚未收录,vols[0] 是 T-1——按 plan §4 Phase C 字面口径
    # 「取最近 5 条」(=T-1..T-5)取 vols[:5](审后修复 🟡#2,原 vols[1:6] 会跳过 T-1
    # 取 T-2..T-6,系统性抬高折算量比)。注意:此窗口与 compute_form 内部
    # vol_multiple 用的 vols[1:6](EOD 场景 vols[0]=今日,故排除今日取前5日)口径
    # 刻意不同——两者调用时机不同(此为盘中调用、彼为 EOD 调用),分母对应的"前5日"
    # 实际是同一组交易日。
    _prev5 = vols[:5]
    prev5_avg_vol = round(sum(_prev5) / len(_prev5), 1) if _prev5 else 0.0
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
        "prev5_avg_vol": prev5_avg_vol,   # v1.4 Phase B:盘中量能折算基准(手)
    }


def _fetch_fund(code: str, moneyflow_fn: Callable) -> Dict[str, Any]:
    """近 ~5 交易日主力资金 → 近 3 日主力净额合计 + 当日 + 实际数据基准日。失败 → 占位。

    源 = 东财 moneyflow_dc(字段 net_amount);兼容老 moneyflow(net_mf_amount)供注入测试。
    asof = 实际拿到的最新交易日(盘后=今日、盘中=上一交易日)——供 fund_asof 如实标注,
    不再无视数据写死上一交易日。
    """
    today = date.today()
    end = today.strftime("%Y%m%d")
    start = (today - timedelta(days=12)).strftime("%Y%m%d")
    res = moneyflow_fn(code, start, end)
    if not res.ok or res.data is None or len(res.data) == 0:
        return {"net_mf_3d": "—", "net_mf_amount": "—", "asof": None, "_degraded": True}
    df = res.data.sort_values("trade_date", ascending=False).reset_index(drop=True)
    col = "net_amount" if "net_amount" in df.columns else "net_mf_amount"  # 东财 / 老源兼容
    amounts = [float(x) for x in df[col].tolist()]
    net_today = round(amounts[0], 2) if amounts else 0.0
    net_3d = round(sum(amounts[:3]), 2) if amounts else 0.0
    asof = str(df["trade_date"].iloc[0])   # 'YYYYMMDD' 最新交易日 = 实际数据基准
    return {"net_mf_3d": net_3d, "net_mf_amount": net_today, "asof": asof, "_degraded": False}


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
    intraday_quote: Optional[Quote] = None,
    is_trading: bool = False,
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

    intraday_quote/is_trading(v1.4 Phase B):端点层判窗口 + 拉一拍完整 Quote 后传入,
    本函数不自己拉盘中价(保持可注入/不联网)。仅 mode=='coach' 且 is_trading 且
    intraday_quote 非 None 时,用 form['prev5_avg_vol'] + intraday_quote 组装盘中快照
    存入 context['intraday'](prompt.py 据此渲染盘中块);candidate 模式一律不组装
    (候选是次日进场判断,无盘中持仓语境)。
    """
    daily_fn = daily_fn or tc.ts_daily
    # 资金源 = 东财 moneyflow_dc(6000 积分,net_amount=超大单+大单主力净额)。与选股层
    # (fetch.py)统一、与用户同花顺/东财 App 方向一致;原始 moneyflow 口径不同、能到符号相反,
    # 已弃用(2026-07-02 修:深析层此前误用原始 moneyflow,给出与候选列表相反的净流出)。
    moneyflow_fn = moneyflow_fn or tc.ts_moneyflow_dc
    sentiment_fn = sentiment_fn or sentiment.fetch_sentiment
    deepseek_fn = deepseek_fn or deepseek.analyze
    adj_factor_fn = adj_factor_fn or tc.ts_adj_factor

    bare = _bare(code)

    form = _fetch_form(bare, daily_fn, adj_factor_fn)
    fund = _fetch_fund(bare, moneyflow_fn)
    # fund_asof 取实际拿到的资金最新交易日(盘后=今日 EOD、盘中=上一交易日);拉取失败无
    # 数据 → 退回"严格上一交易日"占位。不再无视数据写死上一交易日(修 07-02 盘后误标 07-01)。
    _asof_raw = fund.get("asof")
    fund_asof = (
        f"{_asof_raw[:4]}-{_asof_raw[4:6]}-{_asof_raw[6:8]}" if _asof_raw
        else fund_asof_date(now)
    )
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

    # v1.4 Phase B:盘中上下文快照(仅 coach 模式 + 盘中 + 拿到 Quote 才组装,唯一路径——
    # 与 form/fund 同处编排层组装,端点层不重复拉 daily/组装快照)。candidate 模式/窗口
    # 外/quote=None 均不进 context,prompt.py 据 "intraday" 键是否存在决定要不要渲染盘中块。
    if mode == "coach" and is_trading and intraday_quote is not None:
        context["intraday"] = intraday.build_intraday_snapshot(
            intraday_quote, form.get("prev5_avg_vol", 0.0),
            now=datetime.now(), is_trading=True,
        )

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


# —— v1.2.1 Phase A:对话式深判编排 ————————————————————————————————————————

# 事实块 (code, 当日 YYYYMMDD) 级 TTL 缓存,仅供 chat_stock 链路使用(plan §4.2 A3 /
# plan-critic 🔵3:不得给共享 _fetch_form/_fetch_fund 全局加缓存,那会顺带改 /analyze
# 行为,违反端点隔离初衷)。模块级 dict + 日期键天然失效(跨日不再命中);失败不缓存
# (下轮重试)。不引第三方缓存库。
_chat_fact_cache: Dict[Any, Dict[str, Any]] = {}


def _chat_cache_key(bare: str, today: date) -> Any:
    return (bare, today.strftime("%Y%m%d"))


def _fetch_chat_facts(
    bare: str,
    daily_fn: Callable,
    moneyflow_fn: Callable,
    sentiment_fn: Callable,
    adj_factor_fn: Callable,
    now: Optional[date],
) -> Dict[str, Any]:
    """chat_stock 专属:同一 (code, 当日) 内追问命中缓存,不重拉 form/fund/舆情。

    与 analyze_stock/_fetch_form/_fetch_fund 完全独立,不影响 /analyze /coach 行为。
    失败(无数据/异常)不缓存,留给下一轮追问重试。
    """
    today = now or date.today()
    key = _chat_cache_key(bare, today)
    cached = _chat_fact_cache.get(key)
    if cached is not None:
        return cached

    form = _fetch_form(bare, daily_fn, adj_factor_fn)
    fund = _fetch_fund(bare, moneyflow_fn)
    _asof_raw = fund.get("asof")
    fund_asof = (
        f"{_asof_raw[:4]}-{_asof_raw[4:6]}-{_asof_raw[6:8]}" if _asof_raw
        else fund_asof_date(now)
    )
    try:
        news = sentiment_fn(bare)
    except Exception as e:
        logger.warning("对话舆情编排异常(降级): %s", e)
        news = {"titles": [], "note": "未获取到舆情,仅技术+资金判定", "degraded": True}

    facts = {"form": form, "fund": fund, "fund_asof": fund_asof, "news": news}
    # 形态/资金**任一降级**(无数据)即不缓存,留给下一轮追问重试——避免资金瞬时失败把降级
    # 资金面钉一整天(当日重开 thread 落的 verdict 都基于缺失资金)。两者都成功才缓存供同日复用。
    if not form.get("_degraded") and not fund.get("_degraded"):
        _chat_fact_cache[key] = facts
    return facts


def chat_stock(
    code: str,
    messages: List[Dict[str, str]],
    *,
    mode: str = "candidate",
    name: str = "",
    sector: str = "",
    pnl_pct: Optional[float] = None,
    trade_day: Optional[int] = None,
    history_digest: Optional[str] = None,
    now: Optional[date] = None,
    intraday_quote: Optional[Quote] = None,
    is_trading: bool = False,
    chat_fn: Optional[Callable] = None,
    daily_fn: Optional[Callable] = None,
    moneyflow_fn: Optional[Callable] = None,
    sentiment_fn: Optional[Callable] = None,
    adj_factor_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """多轮对话式深判编排:补真实形态+资金+fund_asof(+best-effort 舆情)→ 拼 context →
    deepseek.chat(messages, context) → 返回 {reply, verdict, fund_asof, degraded}。

    mode='candidate' 候选深析对话 / mode='coach' 持仓追问对话。事实块**每轮都注入**
    (不判 is_first)——追问轮用户常问资金/形态,必须拿到真实事实(plan §4.2 A3 /
    plan-critic 重要6:口径统一)。同一 (code, 当日) 内命中 TTL 缓存不重拉。
    history_digest 为中性统计,**绝不含 review_ref**(守味隔离,调用方需自行丢弃 ref)。
    全链路降级不崩:任一数据段失败 → 占位标注;DeepSeek 失败 → degraded_chat。
    可注入 *_fn 免单测联网。

    intraday_quote/is_trading(v1.4 Phase B,同 analyze_stock):仅 mode=='coach' 且
    is_trading 且 intraday_quote 非 None 时组装盘中快照存入 context['intraday']。
    """
    daily_fn = daily_fn or tc.ts_daily
    moneyflow_fn = moneyflow_fn or tc.ts_moneyflow_dc
    sentiment_fn = sentiment_fn or sentiment.fetch_sentiment
    adj_factor_fn = adj_factor_fn or tc.ts_adj_factor
    chat_fn = chat_fn or deepseek.chat

    bare = _bare(code)
    facts = _fetch_chat_facts(bare, daily_fn, moneyflow_fn, sentiment_fn, adj_factor_fn, now)

    context: Dict[str, Any] = {
        "mode": mode, "code": bare, "name": name or bare, "sector": sector or "—",
        "form": facts["form"], "fund": facts["fund"], "news": facts["news"],
        "fund_asof": facts["fund_asof"],
        "pnl_pct": pnl_pct, "trade_day": trade_day,
        # 中性历史纪律统计;绝不放 review_ref(情绪串)——那只回客户端展示,不进 prompt。
        "history_digest": history_digest or "",
    }

    # v1.4 Phase B:同 analyze_stock,仅 coach + 盘中 + 有 Quote 才组装(candidate 不组装)。
    # 审后修复 🟡#3:build_intraday_snapshot 的 now 形参要 datetime(供 elapsed_trading_
    # minutes 调 .time()),本函数的 `now` 形参是 date(供 fund_asof_date/事实缓存键)——
    # 两者类型不同,不可混用;与 analyze_stock 对齐直接用 datetime.now()。
    if mode == "coach" and is_trading and intraday_quote is not None:
        context["intraday"] = intraday.build_intraday_snapshot(
            intraday_quote, facts["form"].get("prev5_avg_vol", 0.0),
            now=datetime.now(), is_trading=True,
        )

    try:
        result = chat_fn(messages, context)
    except Exception as e:   # deepseek.chat 内部已兜底,这里再兜一层
        logger.warning("DeepSeek 对话编排异常(降级): %s", e)
        result = deepseek.degraded_chat(f"编排异常 {type(e).__name__}")

    return {
        "reply": result.get("reply", ""),
        "verdict": result.get("verdict", "观望"),
        "fund_asof": facts["fund_asof"],
        "degraded": bool(result.get("degraded", False)),
    }
