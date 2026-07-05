"""DeepSeek 深判 system 前置词 + DeepAnalysis schema 约束(阶段2 Phase D3)。

把 v2 §6 三维度方法论(形态主轴 / 资金确认 / 消息排雷)+ §7 决策层(中间地带 B 剂量、
泡沫判定)写成系统提示;强制 DeepAnalysis JSON schema + 枚举约束。服务端解析后再校验夹紧
(本文件只负责"教 LLM 怎么输出",夹紧在 deepseek.py / analyze.py)。

铁律对齐:止损 -5% / 止盈 +15% / D4 强平(规则常量在 store.py;此处只在文案引用,
不另立常量)。"泡沫=短期暴涨/乖离过大 + 情绪过热,不看 PE"。
"""

from __future__ import annotations

import json
from typing import Any, Dict


# DeepAnalysis JSON schema 样例(逐字段对齐 Models.swift / plan §4.3),内嵌进 system prompt。
_SCHEMA_EXAMPLE = {
    "form": {"value": "平台突破", "tone": "good", "text": "放量站上 20 日均线,平台有效突破,非左侧抄底。"},
    "fund": {"value": "主力净流入", "tone": "good", "text": "近 3 日主力持续净流入,当日未大幅流出(东财主力口径)。"},
    "news": {"value": "无雷", "tone": "neutral", "text": "未见监管警告/重大利空;舆情温和,无一日游迹象。"},
    "verdict": "可进",
    "plan": "现价附近分批,止损 -5%,止盈 +15%,满 3 交易日第 4 日无条件清仓。",
}

# 方法论 system prompt(v2 §6 + §7 蒸馏)。
SYSTEM_PROMPT = f"""你是 A 股短线交易的专业判官,服务一位有本职工作、当日买次日卖(T+1)、最多持 2–3 天、
同时最多 3 票全仓进出的短线投机者。你的职责是按下面方法论对**一只候选股或在持仓**做深度判定,
**只输出严格的 JSON**(下方 schema),不要任何多余文字、不要 markdown 代码块包裹。

# 三维度方法论(按优先级:形态主轴 → 资金确认 → 消息排雷)

## ① 形态面(主轴,最重要)
- 偏好:平台突破 / 底部放量启动;**剔除左侧抄底**(不接下跌中的刀)。
- 进场时机:盘中突破 / 尾盘放量站稳 / 昨日没进次日仍强,皆可;**回踩等待型不追**。
- 平台/突破有效性不设死阈值,你结合放量倍数、是否创 N 日新高、是否站上均线综合判断。

## ② 资金面(确认器)
- **只看主力净流入 + 换手率**,不看北向/龙虎榜。
- 重**连续几日净流入**(持续性优先),当日不能大幅净流出。
- 顺序:先看 K 线形态,再用资金确认。
- **数据时序**:资金面是**东财主力 EOD 数据**(基准日为给定的 `fund_asof`,盘后=今日 EOD、盘中=上一交易日;
  客户端会单独显著标注该日期),**非盘中实时逐笔**——fund.text 聚焦资金强弱本身,**不要写死"截至上一交易日"、
  不要在正文里重复日期、不要假装知道盘中实时资金**。

## ③ 消息面(只排雷,非买入理由)
- 资金 + 技术是主轴,消息/板块只做**最后排雷**。
- 个股消息**不作买入理由,只排雷**(被监管警告/重大利空 → 不进)。
- **"泡沫明显" = 短期暴涨/乖离过大 + 情绪过热(舆情狂欢),不看估值 PE**(不误杀高估值题材股)。
- 舆情若未获取到,news 轴用 neutral 并注明"未获取到舆情,仅技术+资金判定",**不要据此下不进结论**。

# 离场铁律(写进 plan,口径定死)
- 止损 **-5% 必走**;止盈 **+15% 必走**;**满 3 交易日,第 4 日(D4)无条件清仓**。
- 中间地带(-5%~+15%)= 二元建议(拿 or 清),最看重**量能是否萎缩 + 主力资金还在不在**。

# 历史纪律注入(guardrail,必须遵守)
- 若 user 消息含【历史纪律】一节(用户过去守/破线的中性统计),**仅供你在 text/plan 里引用以增强说服力**
  (如提醒用户"你近几笔常在止损点硬扛")。
- **不得据此改变 verdict 判定标准**:verdict 一律**只按当前这一笔的形态/资金/铁律客观判定**,
  不因用户历史破线多就系统性调保守、也不因历史守线好就放松。铁律仍是 -5%/+15%/D4,不因历史松动。

# 盘中上下文(guardrail,v1.4)
若提供盘中上下文,它是按已开盘时长折算的估算实时数据,可参考但不精确;资金面仍是 EOD、不代表盘中资金。

# 输出格式(严格 JSON,字段与枚举不可变)
{json.dumps(_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}

字段约束:
- form/fund/news 各为对象 {{value, tone, text}}:value 是 ≤6 字结论词,text 是一句中文说明。
- **tone 只能取**:"good"(利好/确认)、"warn"(需警惕)、"bad"(利空/排雷命中)、"neutral"(中性/数据缺失)。
- **verdict 只能取**:"可进"、"观望"、"不进"。
- plan 是一句话进场/止损计划(必须含 -5% 止损与 D4 时间止损口径)。
- 只输出这个 JSON 对象,不要额外解释、不要 markdown 围栏。
"""


def build_user_prompt(context: Dict[str, Any]) -> str:
    """把单票形态/资金/舆情上下文拼成 user 消息(交给 DeepSeek 判)。

    context 由 analyze.py 编排:code/name/sector、形态数值(放量/新高/均线/60日涨幅/换手)、
    资金(近 3 日主力净流入 + 当日,标注 fund_asof)、舆情(标题列表或降级说明)、
    可选模式(candidate 选股深判 / coach 在持仓二元建议 + 当前盈亏%/持仓天数)。
    """
    lines = []
    mode = context.get("mode", "candidate")
    if mode == "coach":
        lines.append("【模式】在持仓中间地带二元建议(拿 or 清),请在 verdict 用'观望/可进'表示倾向'拿',用'不进'表示倾向'清'。")
        if context.get("pnl_pct") is not None:
            lines.append(f"【当前盈亏】{context['pnl_pct']:+.2f}%(在 -5%~+15% 中间地带)")
        if context.get("trade_day") is not None:
            lines.append(f"【持仓交易日】第 {context['trade_day']} 个交易日(D{context['trade_day']};D4 无条件清仓)")
        if context.get("question"):
            lines.append(f"【我的问题】{context['question']}")
    else:
        lines.append("【模式】候选股选股深判(该不该进)。")

    lines.append(f"【标的】{context.get('name','')}({context.get('code','')})  板块:{context.get('sector','—')}")

    form = context.get("form", {})
    lines.append(
        "【形态(昨日 EOD)】"
        f"现价 {form.get('close','—')},当日 {form.get('pct_chg','—')}%,"
        f"昨日 EOD 放量倍数 {form.get('vol_multiple','—')}x,"
        f"创20日新高={form.get('new_high_20d','—')},站20日均线={form.get('above_ma20','—')},"
        f"近60交易日累计涨幅 {form.get('pct_60d','—')}%,换手 {form.get('turnover','—')}%,"
        f"收盘站VWAP={form.get('vwap_ok','—')}"
    )
    # 阶段3.1 信号2:量价形态吸筹/出货判定提示(仅 candidate 模式,不硬编阈值只加上下文)。
    if mode != "coach":
        lines.append(
            "【量价形态判读要求】请结合放量倍数 + 当日涨幅 + 是否收盘站上 VWAP 判断量价形态属"
            "吸筹(温和放量缓涨、收在均价之上,健康)还是出货(爆量暴拉 / 放巨量滞涨、收在均价"
            "之下,危险):若判为出货形态,请相应降低 form 轴 tone 或把 verdict 转为观望。"
        )

    fund = context.get("fund", {})
    lines.append(
        "【资金面(东财主力 EOD,非盘中实时;基准日见下方 fund_asof)】"
        f"以下资金数据截至 {context.get('fund_asof','—')} 收盘(东财主力 EOD),"
        "今日盘中资金未知,不得据此推测今日盘中资金动向或据此说\"主力今日在/撤\"。"
        f"近3日主力净流入合计 {fund.get('net_mf_3d','—')} 万元,"
        f"当日主力净流入 {fund.get('net_mf_amount','—')} 万元;"
        f"基准日 fund_asof={context.get('fund_asof','—')}"
    )

    # v1.4 Phase B:盘中上下文块(仅 context 含 intraday 键时渲染;candidate 模式/窗口外
    # /拉价失败均不含此键,故此处天然不渲染)。
    intr = context.get("intraday")
    if intr:
        lines.append(_intraday_block(intr))

    news = context.get("news", {})
    titles = news.get("titles") or []
    if titles:
        lines.append("【舆情(东财股吧最新标题,best-effort,仅供排雷参考)】")
        for t in titles[:8]:
            lines.append(f"  · {t}")
    else:
        lines.append(f"【舆情】{news.get('note','未获取到舆情,仅技术+资金判定')}")

    # 历史纪律注入(仅当非空;进 prompt 的是中性 history_digest,不是 review_ref 情绪串)。
    # guardrail(见 SYSTEM_PROMPT):仅供 text/plan 引用增说服力,不得据此改 verdict 判定标准。
    history_digest = context.get("history_digest")
    if history_digest:
        lines.append(f"【历史纪律(中性统计,仅供引用增说服力,不改 verdict 判定口径)】{history_digest}")

    lines.append("请据上述信息,严格按 system 指定的 JSON schema 输出深判结果。")
    return "\n".join(lines)


# —— v1.4 Phase B:盘中上下文块(coach/chat 共用文案)————————————————————————

_VOL_NOTE_TEXT = {
    "ok": "",
    "early": "(开盘初量能待观察)",
    "closed": "",
    "no_base": "(量能基准缺失)",
    "non_trading": "",
}


def _intraday_block(intr: Dict[str, Any]) -> str:
    """把盘中快照 dict(见 app.data.intraday.build_intraday_snapshot)拼成 prompt 段。

    两个量能数标签必须显著区分(建议#8):昨日 EOD 放量倍数 vs 盘中折算量比,防 LLM
    混谈。仅调用方已判定 context 含 intraday 键时才会调用本函数。
    """
    price = intr.get("price")
    chg_pct = intr.get("chg_pct")
    ratio = intr.get("intraday_vol_ratio")
    vol_note = intr.get("vol_note", "")
    is_above_vwap = intr.get("is_above_vwap")
    vwap = intr.get("vwap")

    ratio_text = f"{ratio}x{_VOL_NOTE_TEXT.get(vol_note, '')}" if ratio is not None else f"—{_VOL_NOTE_TEXT.get(vol_note, '')}"
    vwap_text = "是" if is_above_vwap is True else ("否" if is_above_vwap is False else "—")

    lines = [
        "【盘中上下文(实时,非 EOD)】"
        f"现价 {price if price is not None else '—'},今日涨幅 {chg_pct if chg_pct is not None else '—'}%,"
        f"盘中折算量比(估算,非精确) {ratio_text},"
        f"是否站VWAP(当日累计均价,元/股,vwap={vwap if vwap is not None else '—'})={vwap_text}",
        "【盘中护栏】盘中量能为按已开盘时长折算的估算值,非精确,早盘折算通常偏高"
        "(A 股早盘量能前置,勿据此怂恿追高);VWAP 为当日累计均价(元/股)。",
    ]
    return "\n".join(lines)


# —— v1.2.1 Phase A:对话式深判 system prompt + 事实注入块 ——————————————————————

# 对话输出 schema 样例:自由中文 reply + 旁路 verdict(供落库回测,不进 UI 结构化渲染)。
_CHAT_SCHEMA_EXAMPLE = {
    "reply": "形态上放量站上平台,20日新高有效突破,不是左侧抄底;资金面近3日主力持续净流入、"
             "当日未见明显流出(东财主力口径,截至 fund_asof);消息面暂未见监管警告或重大利空。"
             "综合看可以关注,进场后按纪律止损 -5%、止盈 +15%,满 3 交易日第 4 日无条件清仓。",
    "verdict": "可进",
}

# 对话式 system prompt(蒸馏 SYSTEM_PROMPT 的三维度方法论 + 离场铁律 + guardrail,
# 但输出格式改为自由中文 reply + 旁路 verdict,而非三轴结构化卡)。
CHAT_SYSTEM_PROMPT = f"""你是 A 股短线交易的专业判官,服务一位有本职工作、当日买次日卖(T+1)、最多持 2–3 天、
同时最多 3 票全仓进出的短线投机者。你正在与他做多轮对话(初始深判 + 追问),**只输出严格的 JSON**
(下方 schema),不要任何多余文字、不要 markdown 代码块包裹。

# 三维度方法论(按优先级:形态主轴 → 资金确认 → 消息排雷)

## ① 形态面(主轴,最重要)
- 偏好:平台突破 / 底部放量启动;**剔除左侧抄底**(不接下跌中的刀)。
- 进场时机:盘中突破 / 尾盘放量站稳 / 昨日没进次日仍强,皆可;**回踩等待型不追**。
- 平台/突破有效性不设死阈值,结合放量倍数、是否创 N 日新高、是否站上均线综合判断。

## ② 资金面(确认器)
- **只看主力净流入 + 换手率**,不看北向/龙虎榜。重**连续几日净流入**(持续性优先),当日不能大幅净流出。
- 顺序:先看 K 线形态,再用资金确认。
- **数据时序(必须诚实交代)**:资金面是**东财主力 EOD 数据**(基准日为给定的 `fund_asof`,盘后=今日
  EOD、盘中=上一交易日),**非盘中实时逐笔**。回答里如涉及资金,措辞要让用户明白这不是盘中实时资金,
  但不要重复写死具体日期(客户端会单独显著标注 fund_asof)。

## ③ 消息面(只排雷,非买入理由)
- 资金 + 技术是主轴,消息/板块只做**最后排雷**。个股消息**不作买入理由,只排雷**(监管警告/重大利空→不进)。
- **"泡沫明显" = 短期暴涨/乖离过大 + 情绪过热,不看估值 PE**。舆情缺失时用中性措辞,不据此下不进结论。

# 离场铁律(对话里可引用,口径定死,不新立)
- 止损 **-5% 必走**;止盈 **+15% 必走**;**满 3 交易日,第 4 日(D4)无条件清仓**。
- 中间地带(-5%~+15%)= 二元倾向(拿 or 清),最看重**量能是否萎缩 + 主力资金还在不在**。

# 护栏(必须遵守)
- **只依据下方注入的事实作答**,不要编造未提供的数据(如具体新闻内容、未给出的技术指标)。
- **诚实交代资金口径**:资金面来自东财主力 EOD 数据,不是盘中实时。
- **绝不越出离场铁律**:任何回答都不能建议突破 -5%/+15%/D4 的框架(如"可以再扛扛""可以不止损"这类话绝不能说)。
- **不替用户扣扳机**:只给判断依据和倾向,买/卖/持有的最终决定权在用户,不要用命令式语气替他决定。
- **verdict 只按当前这一笔客观判定**:即使【历史纪律】一节显示用户过去常破线,也**不得**据此系统性调保守;
  verdict 只反映这一笔当下的形态/资金/铁律判断。
- 若对方追问(非首轮),结合历史对话上下文自然接续回答,不要重复第一轮已经说过的完整分析。
- 若提供盘中上下文,它是按已开盘时长折算的估算实时数据,可参考但不精确;资金面仍是 EOD、不代表盘中资金。

# 输出格式(严格 JSON,字段不可变)
{json.dumps(_CHAT_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}

字段约束:
- reply:自由中文分析,**约 200–250 字**,可用『』或换行组织分段,**不用 markdown 标题**(不要 #/##/**加粗**这类语法)。
- **verdict 只能取**:"可进"、"观望"、"不进"。
- 只输出这个 JSON 对象,不要额外解释、不要 markdown 围栏。
"""


def build_chat_context_block(context: Dict[str, Any]) -> str:
    """把标的/形态/资金/舆情/fund_asof/history_digest 拼成对话事实注入前缀。

    复用 build_user_prompt 的形态/资金/舆情文案逻辑(措辞对齐,保证事实呈现口径一致)。
    **绝不含 review_ref**(带情绪串,对话区不用,守味隔离沿阶段3 brain.py 两路径分流)。
    以 role=system 事实块形式拼进 deepseek.chat 的 messages(见 A2)。
    """
    lines = []
    mode = context.get("mode", "candidate")
    if mode == "coach":
        # 持仓追问一律走 coach(含触损/触盈),按实际盈亏派生区间措辞,**不写死"中间地带"**——
        # 否则对 -7% 触损持仓会注入"在 -5%~+15% 中间地带"这种自相矛盾的假事实(违反"只注入真
        # 事实")。阈 -5%/+15% 此处为文案引用(判定在 hardline/store,不另立常量)。
        _pnl = context.get("pnl_pct")
        if _pnl is None:
            _zone = "在持仓"
        elif _pnl < -5.0:
            _zone = "已跌破 -5% 止损线"
        elif _pnl > 15.0:
            _zone = "已过 +15% 止盈线"
        else:
            _zone = "-5%~+15% 中间地带"
        lines.append(f"【模式】在持仓对话(用户已持有该票,{_zone})。")
        if _pnl is not None:
            lines.append(f"【当前盈亏】{_pnl:+.2f}%({_zone})")
        if context.get("trade_day") is not None:
            lines.append(f"【持仓交易日】第 {context['trade_day']} 个交易日(D{context['trade_day']};D4 无条件清仓)")
    else:
        lines.append("【模式】候选股选股深判对话(该不该进)。")

    lines.append(f"【标的】{context.get('name','')}({context.get('code','')})  板块:{context.get('sector','—')}")

    form = context.get("form", {})
    lines.append(
        "【形态(昨日 EOD)】"
        f"现价 {form.get('close','—')},当日 {form.get('pct_chg','—')}%,"
        f"昨日 EOD 放量倍数 {form.get('vol_multiple','—')}x,"
        f"创20日新高={form.get('new_high_20d','—')},站20日均线={form.get('above_ma20','—')},"
        f"近60交易日累计涨幅 {form.get('pct_60d','—')}%,换手 {form.get('turnover','—')}%,"
        f"收盘站VWAP={form.get('vwap_ok','—')}"
    )

    fund = context.get("fund", {})
    lines.append(
        "【资金面(东财主力 EOD,非盘中实时;基准日见下方 fund_asof)】"
        f"以下资金数据截至 {context.get('fund_asof','—')} 收盘(东财主力 EOD),"
        "今日盘中资金未知,不得据此推测今日盘中资金动向或据此说\"主力今日在/撤\"。"
        f"近3日主力净流入合计 {fund.get('net_mf_3d','—')} 万元,"
        f"当日主力净流入 {fund.get('net_mf_amount','—')} 万元;"
        f"基准日 fund_asof={context.get('fund_asof','—')}"
    )

    # v1.4 Phase B:盘中上下文块(仅 context 含 intraday 键时渲染)。
    intr = context.get("intraday")
    if intr:
        lines.append(_intraday_block(intr))

    news = context.get("news", {})
    titles = news.get("titles") or []
    if titles:
        lines.append("【舆情(东财股吧最新标题,best-effort,仅供排雷参考)】")
        for t in titles[:8]:
            lines.append(f"  · {t}")
    else:
        lines.append(f"【舆情】{news.get('note','未获取到舆情,仅技术+资金判定')}")

    # 中性历史纪律统计(仅当非空);绝不含 review_ref(情绪串,对话端点不取用)。
    history_digest = context.get("history_digest")
    if history_digest:
        lines.append(f"【历史纪律(中性统计,仅供引用增说服力,不改 verdict 判定口径)】{history_digest}")

    lines.append("以上是本轮对话可依据的注入事实,请据此结合对话历史回答用户,严格按 system 指定的 JSON schema 输出。")
    return "\n".join(lines)
