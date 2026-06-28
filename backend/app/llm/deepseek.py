"""DeepSeek /chat/completions 调用 + DeepAnalysis 校验夹紧 + 降级(阶段2 Phase D3)。

plan §4.0:https://api.deepseek.com/v1/chat/completions(OpenAI 兼容),model deepseek-chat,
response_format={"type":"json_object"} 强制结构化;httpx 同步调用,超时 30s。

降级铁律(plan §4.0 / 任务书):缺 DEEPSEEK_API_KEY / 超时 / 非法 JSON → 返回降级占位
DeepAnalysis(verdict=观望、三轴 tone=neutral、诚实文案),**绝不抛崩**。

可注入 transport(沿 send_push(transport=...) 模式)→ 单测不真连 DeepSeek。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.config import settings
from app.llm.prompt import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepseek.com/v1/chat/completions"
_MODEL = "deepseek-chat"
_TIMEOUT = 30.0

# 合法枚举(校验夹紧用,与 Models.swift 对齐)
_TONES = {"good", "warn", "bad", "neutral"}
_VERDICTS = {"可进", "观望", "不进"}


# —— 降级占位卡 ————————————————————————————————————————————————————

def degraded_analysis(reason: str) -> Dict[str, Any]:
    """降级占位 DeepAnalysis(verdict=观望、三轴 tone=neutral、诚实文案)。"""
    note = f"深判降级:{reason}。仅供参考,请勿据此进场。"
    axis = {"value": "暂无", "tone": "neutral", "text": note}
    return {
        "form": dict(axis),
        "fund": dict(axis),
        "news": dict(axis),
        "verdict": "观望",
        "plan": "深判暂不可用,维持纪律:止损 -5%、止盈 +15%、满 3 交易日第 4 日清仓。",
    }


# —— 校验夹紧 ————————————————————————————————————————————————————

def _clamp_axis(raw: Any) -> Dict[str, Any]:
    """夹紧单轴 {value, tone, text};tone 越界 → neutral;缺字段补占位。"""
    if not isinstance(raw, dict):
        return {"value": "暂无", "tone": "neutral", "text": ""}
    tone = raw.get("tone")
    if tone not in _TONES:
        tone = "neutral"
    return {
        "value": str(raw.get("value", "暂无"))[:12],
        "tone": tone,
        "text": str(raw.get("text", "")),
    }


def clamp_analysis(raw: Any, reason_if_invalid: str = "模型输出非法") -> Dict[str, Any]:
    """把 LLM 原始输出夹紧为合法 DeepAnalysis。完全无法解析 → 降级占位卡。

    tone/verdict 越界值夹到合法枚举(verdict 越界 → 观望);三轴缺失补占位。
    """
    if not isinstance(raw, dict):
        return degraded_analysis(reason_if_invalid)
    verdict = raw.get("verdict")
    if verdict not in _VERDICTS:
        verdict = "观望"
    plan = raw.get("plan")
    if not isinstance(plan, str) or not plan.strip():
        plan = "止损 -5%、止盈 +15%、满 3 交易日第 4 日无条件清仓。"
    return {
        "form": _clamp_axis(raw.get("form")),
        "fund": _clamp_axis(raw.get("fund")),
        "news": _clamp_axis(raw.get("news")),
        "verdict": verdict,
        "plan": plan,
    }


# —— 真调用(可注入 transport)————————————————————————————————————————

def analyze(context: Dict[str, Any], *, transport: Optional[Any] = None) -> Dict[str, Any]:
    """对单票上下文调 DeepSeek 深判,返回校验夹紧后的合法 DeepAnalysis。

    缺 key → 降级占位卡(不调用);超时/网络/非 200/非法 JSON → 降级占位卡(不崩)。
    transport 注入(httpx.MockTransport 等)→ 单测不真连。
    """
    if not settings.has_deepseek_key:
        return degraded_analysis("未配置 DEEPSEEK_API_KEY")

    try:
        import httpx
    except ImportError:
        return degraded_analysis("httpx 未安装")

    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(context)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY.strip()}",
        "Content-Type": "application/json",
    }

    try:
        client_kwargs: Dict[str, Any] = {"timeout": _TIMEOUT}
        if transport is not None:
            client_kwargs["transport"] = transport
        with httpx.Client(**client_kwargs) as client:
            resp = client.post(_API_URL, json=payload, headers=headers)
    except Exception as e:   # 超时/网络/连接异常一律降级
        logger.warning("DeepSeek 调用异常(降级): %s", e)
        return degraded_analysis(f"调用异常 {type(e).__name__}")

    if resp.status_code != 200:
        logger.warning("DeepSeek 非 200(%s,降级)", resp.status_code)
        return degraded_analysis(f"上游 {resp.status_code}")

    # 解析 OpenAI 兼容响应 → content(应是 JSON 字符串)
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("DeepSeek 响应解析异常(降级): %s", e)
        return degraded_analysis("响应结构异常")

    parsed = _loads_lenient(content)
    if parsed is None:
        logger.warning("DeepSeek content 非合法 JSON(降级)")
        return degraded_analysis("模型输出非 JSON")

    return clamp_analysis(parsed, reason_if_invalid="模型输出字段非法")


def _loads_lenient(content: str) -> Optional[Any]:
    """宽松解析 content:直接 json.loads;失败则剥 markdown 围栏再试。返回 None 表示彻底失败。"""
    if not isinstance(content, str):
        return None
    s = content.strip()
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        pass
    # 剥 ```json ... ``` 围栏
    if "```" in s:
        inner = s.split("```")
        for chunk in inner:
            c = chunk.strip()
            if c.startswith("json"):
                c = c[4:].strip()
            if c.startswith("{"):
                try:
                    return json.loads(c)
                except (json.JSONDecodeError, TypeError):
                    continue
    # 截取首个 { 到末个 } 再试
    lb, rb = s.find("{"), s.rfind("}")
    if 0 <= lb < rb:
        try:
            return json.loads(s[lb:rb + 1])
        except (json.JSONDecodeError, TypeError):
            return None
    return None
