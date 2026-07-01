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
    "fund": {"value": "主力净流入", "tone": "good", "text": "近 3 日主力持续净流入,当日未大幅流出(资金面=截至上一交易日 EOD)。"},
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
- **数据时序铁律**:moneyflow 是 EOD 数据,资金面一律**截至上一交易日 EOD,今日盘中资金未知**——
  在 fund.text 里诚实标注这一点,不要假装知道今日盘中资金。

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
        "【形态】"
        f"现价 {form.get('close','—')},当日 {form.get('pct_chg','—')}%,"
        f"放量倍数 {form.get('vol_multiple','—')}x,"
        f"创20日新高={form.get('new_high_20d','—')},站20日均线={form.get('above_ma20','—')},"
        f"近60交易日累计涨幅 {form.get('pct_60d','—')}%,换手 {form.get('turnover','—')}%"
    )

    fund = context.get("fund", {})
    lines.append(
        "【资金面(截至上一交易日 EOD,今日盘中资金未知)】"
        f"近3日主力净流入合计 {fund.get('net_mf_3d','—')} 万元,"
        f"当日主力净流入 {fund.get('net_mf_amount','—')} 万元;"
        f"基准日 fund_asof={context.get('fund_asof','—')}"
    )

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
