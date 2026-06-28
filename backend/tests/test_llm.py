"""阶段2 D3:DeepSeek 深判层(deepseek/sentiment/analyze/prompt)单测。

不联网:DeepSeek 用 httpx.MockTransport 注入假响应;舆情/Tushare 用注入替身。
验证:合法 JSON 解析、非法 JSON/超时/非 200/缺 key 降级、tone/verdict 夹紧、
舆情失败 neutral 占位、analyze 全链路降级不崩、fund_asof 标注。
"""

import json

import httpx
import pytest

from app.llm import deepseek, sentiment, analyze
from app.llm import prompt as prompt_mod
from app.config import settings as settings_singleton
from app.data.tushare_client import TushareResult


# —— deepseek:校验夹紧(纯函数,无网络)————————————————————————————————

def test_clamp_legal_passthrough():
    raw = {
        "form": {"value": "平台突破", "tone": "good", "text": "放量站上均线"},
        "fund": {"value": "净流入", "tone": "good", "text": "近3日流入"},
        "news": {"value": "无雷", "tone": "neutral", "text": "舆情温和"},
        "verdict": "可进", "plan": "止损 -5%",
    }
    out = deepseek.clamp_analysis(raw)
    assert out["verdict"] == "可进"
    assert out["form"]["tone"] == "good" and out["news"]["tone"] == "neutral"


def test_clamp_illegal_tone_and_verdict():
    raw = {
        "form": {"value": "x", "tone": "bullish", "text": "t"},   # tone 越界 → neutral
        "fund": {"value": "y", "tone": "good", "text": "t"},
        "news": {"value": "z", "tone": "bad", "text": "t"},
        "verdict": "强烈推荐",                                     # verdict 越界 → 观望
        "plan": "",                                               # 空 plan → 兜底文案
    }
    out = deepseek.clamp_analysis(raw)
    assert out["form"]["tone"] == "neutral"
    assert out["verdict"] == "观望"
    assert out["plan"]  # 非空兜底


def test_clamp_non_dict_degrades():
    out = deepseek.clamp_analysis("not a dict")
    assert out["verdict"] == "观望"
    assert all(out[a]["tone"] == "neutral" for a in ("form", "fund", "news"))


def test_degraded_analysis_shape():
    out = deepseek.degraded_analysis("测试原因")
    for k in ("form", "fund", "news", "verdict", "plan"):
        assert k in out
    assert out["verdict"] == "观望"
    assert "测试原因" in out["form"]["text"]


# —— deepseek:_loads_lenient 宽松解析 ————————————————————————————————

def test_loads_lenient_plain_and_fenced():
    obj = {"verdict": "可进"}
    assert deepseek._loads_lenient(json.dumps(obj)) == obj
    fenced = "```json\n" + json.dumps(obj) + "\n```"
    assert deepseek._loads_lenient(fenced) == obj
    # 前后有杂字 → 截 {..}
    noisy = "这是结果:" + json.dumps(obj) + " 完毕"
    assert deepseek._loads_lenient(noisy) == obj
    assert deepseek._loads_lenient("完全不是 json") is None


# —— deepseek.analyze:注入 MockTransport(不真连)————————————————————————

@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setattr(settings_singleton, "DEEPSEEK_API_KEY", "sk-test-key-123456", raising=False)


def _mock_transport(status, content_obj):
    """造一个返回 OpenAI 兼容响应的 MockTransport。content_obj 为 message.content(字符串)。"""
    def handler(request):
        body = {"choices": [{"message": {"content": content_obj}}]}
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def _ctx():
    return {"mode": "candidate", "code": "603986", "name": "兆易创新", "sector": "半导体",
            "form": {}, "fund": {}, "news": {"titles": []}, "fund_asof": "2026-05-06"}


def test_analyze_legal_json(with_key):
    legal = json.dumps({
        "form": {"value": "突破", "tone": "good", "text": "放量"},
        "fund": {"value": "流入", "tone": "good", "text": "近3日"},
        "news": {"value": "无雷", "tone": "neutral", "text": "温和"},
        "verdict": "可进", "plan": "止损-5%",
    }, ensure_ascii=False)
    out = deepseek.analyze(_ctx(), transport=_mock_transport(200, legal))
    assert out["verdict"] == "可进" and out["form"]["tone"] == "good"


def test_analyze_illegal_json_degrades(with_key):
    out = deepseek.analyze(_ctx(), transport=_mock_transport(200, "这不是JSON{{{"))
    assert out["verdict"] == "观望"
    assert all(out[a]["tone"] == "neutral" for a in ("form", "fund", "news"))


def test_analyze_non_200_degrades(with_key):
    out = deepseek.analyze(_ctx(), transport=_mock_transport(500, "{}"))
    assert out["verdict"] == "观望"


def test_analyze_timeout_degrades(with_key):
    def handler(request):
        raise httpx.TimeoutException("timed out")
    out = deepseek.analyze(_ctx(), transport=httpx.MockTransport(handler))
    assert out["verdict"] == "观望"
    assert "调用异常" in out["form"]["text"]


def test_analyze_missing_key_degrades(monkeypatch):
    monkeypatch.setattr(settings_singleton, "DEEPSEEK_API_KEY", None, raising=False)
    out = deepseek.analyze(_ctx())   # 不调网络,直接降级
    assert out["verdict"] == "观望"
    assert "DEEPSEEK_API_KEY" in out["form"]["text"]


def test_analyze_clamps_illegal_model_output(with_key):
    bad = json.dumps({
        "form": {"value": "x", "tone": "moon", "text": "t"},
        "fund": {"value": "y", "tone": "good", "text": "t"},
        "news": {"value": "z", "tone": "neutral", "text": "t"},
        "verdict": "一把梭", "plan": "p",
    }, ensure_ascii=False)
    out = deepseek.analyze(_ctx(), transport=_mock_transport(200, bad))
    assert out["form"]["tone"] == "neutral"   # moon → neutral
    assert out["verdict"] == "观望"            # 一把梭 → 观望


# —— sentiment:降级 ————————————————————————————————————————————————

def test_sentiment_titles_ok():
    out = sentiment.fetch_sentiment("603986", fetch_fn=lambda c: ["利好消息", "放量突破"])
    assert out["degraded"] is False and out["titles"] == ["利好消息", "放量突破"]
    assert out["note"] == ""


def test_sentiment_empty_degrades():
    out = sentiment.fetch_sentiment("603986", fetch_fn=lambda c: [])
    assert out["degraded"] is True and out["titles"] == []
    assert "未获取到舆情" in out["note"]


def test_sentiment_exception_degrades():
    def _boom(c):
        raise RuntimeError("network down")
    out = sentiment.fetch_sentiment("603986", fetch_fn=_boom)
    assert out["degraded"] is True


# —— analyze:编排(注入假数据,免联网)——————————————————————————————————

def _ok_daily(code, start, end):
    import pandas as pd
    rows = []
    # 造 30 行 daily(新→旧由 analyze 内排序)
    for i in range(30):
        rows.append({
            "trade_date": f"202605{30 - i:02d}" if (30 - i) <= 31 else "20260501",
            "close": 100.0 - i, "vol": 3000.0 if i == 0 else 1000.0,
            "pre_close": 99.0 if i == 0 else 100.0 - i - 1,
        })
    return TushareResult.success(pd.DataFrame(rows))


def _ok_moneyflow(code, start, end):
    import pandas as pd
    rows = [
        {"trade_date": "20260506", "net_mf_amount": 1200.0},
        {"trade_date": "20260505", "net_mf_amount": 800.0},
        {"trade_date": "20260504", "net_mf_amount": 500.0},
    ]
    return TushareResult.success(pd.DataFrame(rows))


def _fail_fn(*a, **k):
    return TushareResult.fail("token 缺失")


def test_analyze_stock_full_chain(with_key):
    captured = {}

    def _fake_deepseek(context):
        captured["ctx"] = context
        return deepseek.degraded_analysis("测试")  # 形状合法即可

    out = analyze.analyze_stock(
        "603986", "兆易创新", "半导体",
        daily_fn=_ok_daily, moneyflow_fn=_ok_moneyflow,
        sentiment_fn=lambda c: {"titles": ["放量"], "note": "", "degraded": False},
        deepseek_fn=_fake_deepseek,
    )
    assert "analysis" in out and "fund_asof" in out
    # fund_asof 标注上一交易日
    assert len(out["fund_asof"]) == 10 and out["fund_asof"][4] == "-"
    # 形态/资金已补进 context
    ctx = captured["ctx"]
    assert ctx["form"]["vol_multiple"] == 3.0
    assert ctx["fund"]["net_mf_3d"] == 2500.0
    assert ctx["news"]["titles"] == ["放量"]


def test_analyze_stock_degraded_data_safe(with_key):
    """Tushare 全失败 → 形态/资金占位标注,仍走 DeepSeek(此处假深判),不崩。"""
    out = analyze.analyze_stock(
        "603986", "兆易创新", "半导体",
        daily_fn=_fail_fn, moneyflow_fn=_fail_fn,
        sentiment_fn=lambda c: {"titles": [], "note": "未获取到舆情", "degraded": True},
        deepseek_fn=lambda ctx: deepseek.degraded_analysis("数据缺失"),
    )
    assert out["analysis"]["verdict"] == "观望"


def test_analyze_stock_deepseek_exception_safe(with_key):
    def _boom(ctx):
        raise RuntimeError("boom")
    out = analyze.analyze_stock(
        "603986", daily_fn=_fail_fn, moneyflow_fn=_fail_fn,
        sentiment_fn=lambda c: {"titles": [], "note": "x", "degraded": True},
        deepseek_fn=_boom,
    )
    assert out["analysis"]["verdict"] == "观望"   # 兜底降级


def test_coach_advice_mapping():
    assert analyze.coach_advice_from_analysis({"verdict": "不进"}) == "清"
    assert analyze.coach_advice_from_analysis({"verdict": "观望"}) == "拿"
    assert analyze.coach_advice_from_analysis({"verdict": "可进"}) == "拿"


# —— prompt:构建 ————————————————————————————————————————————————————

def test_system_prompt_has_schema_and_enums():
    sp = prompt_mod.SYSTEM_PROMPT
    assert "可进" in sp and "观望" in sp and "不进" in sp
    assert "good" in sp and "warn" in sp and "bad" in sp and "neutral" in sp
    assert "-5%" in sp and "+15%" in sp
    assert "泡沫" in sp and "PE" in sp   # 泡沫不看 PE


def test_build_user_prompt_candidate_and_coach():
    cand = prompt_mod.build_user_prompt({
        "mode": "candidate", "code": "603986", "name": "兆易创新", "sector": "半导体",
        "form": {"close": 100.0, "vol_multiple": 2.8}, "fund": {"net_mf_3d": 1200.0},
        "news": {"titles": ["放量"]}, "fund_asof": "2026-05-06",
    })
    assert "候选股选股深判" in cand and "兆易创新" in cand and "2026-05-06" in cand

    coach = prompt_mod.build_user_prompt({
        "mode": "coach", "code": "603986", "name": "兆易创新",
        "pnl_pct": 3.2, "trade_day": 2, "question": "还能拿吗",
        "form": {}, "fund": {}, "news": {"note": "无舆情"}, "fund_asof": "2026-05-06",
    })
    assert "二元建议" in coach and "+3.20%" in coach and "还能拿吗" in coach
