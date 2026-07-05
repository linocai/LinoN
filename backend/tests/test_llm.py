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


def _ok_adj_factor_flat(code, start, end):
    """复权因子恒定(无除权)→ qfq_closes 后序列与原始价一致,不改变既有断言。

    阶段2.5 F2 新增:analyze_stock 现会调 adj_factor_fn 做单票前复权;单测必须
    显式注入(不能让 tc.ts_adj_factor 默认值触发真网络调用)。恒定因子等价旧行为。
    """
    import pandas as pd
    rows = [{"trade_date": f"202605{30 - i:02d}" if (30 - i) <= 31 else "20260501",
             "adj_factor": 1.0} for i in range(30)]
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
        adj_factor_fn=_ok_adj_factor_flat,
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
        "form": {"close": 100.0, "vol_multiple": 2.8, "vwap_ok": True}, "fund": {"net_mf_3d": 1200.0},
        "news": {"titles": ["放量"]}, "fund_asof": "2026-05-06",
    })
    assert "候选股选股深判" in cand and "兆易创新" in cand and "2026-05-06" in cand
    # 阶段3.1 信号1/2:candidate 模式含 收盘站VWAP + 量价形态吸筹/出货判读要求
    assert "收盘站VWAP=" in cand
    assert "吸筹" in cand and "出货" in cand

    coach = prompt_mod.build_user_prompt({
        "mode": "coach", "code": "603986", "name": "兆易创新",
        "pnl_pct": 3.2, "trade_day": 2, "question": "还能拿吗",
        "form": {}, "fund": {}, "news": {"note": "无舆情"}, "fund_asof": "2026-05-06",
    })
    assert "二元建议" in coach and "+3.20%" in coach and "还能拿吗" in coach
    # coach 模式不加吸筹/出货提示(仍二元拿/清,plan Phase C 验收6)
    assert "量价形态判读要求" not in coach


def test_build_user_prompt_degraded_vwap_graceful():
    """深判降级链:form 缺 vwap_ok(占位 dict 标 —)→ prompt 优雅显示 收盘站VWAP=—,不崩(验收7)。"""
    cand = prompt_mod.build_user_prompt({
        "mode": "candidate", "code": "603986", "name": "x",
        "form": {"close": "—", "vwap_ok": "—", "_degraded": True},
        "fund": {}, "news": {"note": "无"}, "fund_asof": "2026-05-06",
    })
    assert "收盘站VWAP=—" in cand


def _ok_daily_with_amount(code, start, end):
    """带 amount 列的单票 daily(阶段3.1:验 vwap_ok 流入 ctx)。

    今日 close=105,amount=1000 千元,vol=100 手 → vwap=100 → close>vwap → vwap_ok True。
    """
    import pandas as pd
    rows = []
    for i in range(30):
        td = f"202605{30 - i:02d}" if (30 - i) <= 31 else "20260501"
        rows.append({
            "trade_date": td,
            "close": 105.0 if i == 0 else 100.0,
            "vol": 100.0, "pre_close": 100.0, "amount": 1000.0,
        })
    return TushareResult.success(pd.DataFrame(rows))


def test_analyze_stock_vwap_ok_flows_to_ctx(with_key):
    """带 amount 的单票 daily → _fetch_form 算出 vwap_ok 并进 ctx(信号1 喂 LLM)。"""
    captured = {}

    def _fake_deepseek(context):
        captured["ctx"] = context
        return deepseek.degraded_analysis("测试")

    analyze.analyze_stock(
        "603986", "兆易创新", "半导体",
        daily_fn=_ok_daily_with_amount, moneyflow_fn=_ok_moneyflow,
        sentiment_fn=lambda c: {"titles": [], "note": "", "degraded": False},
        deepseek_fn=_fake_deepseek,
        adj_factor_fn=_ok_adj_factor_flat,
    )
    assert captured["ctx"]["form"]["vwap_ok"] is True


def test_analyze_stock_degraded_form_has_vwap_placeholder(with_key):
    """Tushare daily 失败 → 形态占位 dict 带 vwap_ok='—'(降级链不崩,验收7)。"""
    captured = {}

    def _fake_deepseek(context):
        captured["ctx"] = context
        return deepseek.degraded_analysis("数据缺失")

    analyze.analyze_stock(
        "603986", daily_fn=_fail_fn, moneyflow_fn=_fail_fn,
        sentiment_fn=lambda c: {"titles": [], "note": "无", "degraded": True},
        deepseek_fn=_fake_deepseek,
    )
    assert captured["ctx"]["form"]["vwap_ok"] == "—"


# —— v1.4 Phase B:coach 盘中上下文注入(analyze_stock/chat_stock + prompt) ————————

def test_fetch_form_returns_prev5_avg_vol(with_key):
    """_fetch_form 顺带吐 prev5_avg_vol(手,不复权,vols[1:6] 均值),供盘中折算基准。"""
    captured = {}

    def _fake_deepseek(context):
        captured["ctx"] = context
        return deepseek.degraded_analysis("测试")

    analyze.analyze_stock(
        "603986", daily_fn=_ok_daily, moneyflow_fn=_ok_moneyflow,
        sentiment_fn=lambda c: {"titles": [], "note": "", "degraded": False},
        deepseek_fn=_fake_deepseek,
        adj_factor_fn=_ok_adj_factor_flat,
    )
    # _ok_daily: i==0 时 vol=3000,其余(含 i=1..5)vol=1000 → prev5_avg_vol=1000.0
    assert captured["ctx"]["form"]["prev5_avg_vol"] == 1000.0


def test_fetch_form_degraded_prev5_avg_vol_zero():
    """daily 拉取失败 → 占位 dict 的 prev5_avg_vol=0.0(不缺键,不崩)。"""
    out = analyze._fetch_form("603986", _fail_fn)
    assert out["prev5_avg_vol"] == 0.0
    assert out["_degraded"] is True


def _quote(**overrides):
    from app.data.realtime import Quote
    base = dict(
        code="603986", name="兆易创新", price=101.0, pre_close=100.0,
        open=100.5, high=102.0, low=99.5, limit_up=110.0, limit_down=90.0,
        volume=2000.0, amount=101.0 * 2000.0 * 100.0,  # 真实比例 amount≈price×volume×100
        ts="2026-07-06 10:30:00", source="sina",
    )
    base.update(overrides)
    return Quote(**base)


def test_analyze_stock_coach_intraday_injects_context(with_key):
    """coach + is_trading + 有 Quote → context 含 intraday 键,快照字段齐全。"""
    captured = {}

    def _fake_deepseek(context):
        captured["ctx"] = context
        return deepseek.degraded_analysis("测试")

    analyze.analyze_stock(
        "603986", "兆易创新", "半导体", mode="coach", pnl_pct=1.0, trade_day=2,
        daily_fn=_ok_daily, moneyflow_fn=_ok_moneyflow,
        sentiment_fn=lambda c: {"titles": [], "note": "", "degraded": False},
        deepseek_fn=_fake_deepseek, adj_factor_fn=_ok_adj_factor_flat,
        intraday_quote=_quote(), is_trading=True,
    )
    intr = captured["ctx"].get("intraday")
    assert intr is not None
    assert intr["is_trading"] is True
    assert intr["price"] == 101.0
    assert intr["is_above_vwap"] is not None   # 真实比例 amount 应算出合法 VWAP


def test_analyze_stock_coach_not_trading_omits_intraday(with_key):
    """coach 但 is_trading=False(未传 True)→ context 不含 intraday 键。"""
    captured = {}

    def _fake_deepseek(context):
        captured["ctx"] = context
        return deepseek.degraded_analysis("测试")

    analyze.analyze_stock(
        "603986", mode="coach", pnl_pct=1.0, trade_day=2,
        daily_fn=_ok_daily, moneyflow_fn=_ok_moneyflow,
        sentiment_fn=lambda c: {"titles": [], "note": "", "degraded": False},
        deepseek_fn=_fake_deepseek, adj_factor_fn=_ok_adj_factor_flat,
        intraday_quote=_quote(), is_trading=False,
    )
    assert "intraday" not in captured["ctx"]


def test_analyze_stock_candidate_mode_never_injects_intraday(with_key):
    """candidate 模式即便误传 intraday_quote/is_trading=True 也不组装(候选无持仓语境)。"""
    captured = {}

    def _fake_deepseek(context):
        captured["ctx"] = context
        return deepseek.degraded_analysis("测试")

    analyze.analyze_stock(
        "603986", mode="candidate",
        daily_fn=_ok_daily, moneyflow_fn=_ok_moneyflow,
        sentiment_fn=lambda c: {"titles": [], "note": "", "degraded": False},
        deepseek_fn=_fake_deepseek, adj_factor_fn=_ok_adj_factor_flat,
        intraday_quote=_quote(), is_trading=True,
    )
    assert "intraday" not in captured["ctx"]


def test_chat_stock_coach_intraday_injects_context():
    """chat_stock coach 模式同 analyze_stock:盘中 + Quote → context 含 intraday。"""
    captured = {}

    def _fake_chat(messages, context):
        captured["ctx"] = context
        return {"reply": "x", "verdict": "观望"}

    analyze.chat_stock(
        "603986", [{"role": "user", "content": "还能拿吗"}], mode="coach",
        pnl_pct=1.0, trade_day=2, chat_fn=_fake_chat,
        daily_fn=_ok_daily, moneyflow_fn=_ok_moneyflow,
        sentiment_fn=lambda c: {"titles": [], "note": "", "degraded": False},
        adj_factor_fn=_ok_adj_factor_flat,
        intraday_quote=_quote(), is_trading=True,
    )
    intr = captured["ctx"].get("intraday")
    assert intr is not None and intr["is_trading"] is True


def test_build_user_prompt_coach_intraday_block_and_fund_guardrail():
    """coach + intraday 键 → prompt 含盘中块(区分标签)+ 资金约束句(建议#8)。"""
    ctx = {
        "mode": "coach", "code": "603986", "name": "兆易创新",
        "pnl_pct": 3.2, "trade_day": 2,
        "form": {"vol_multiple": 2.8}, "fund": {}, "news": {"note": "无"},
        "fund_asof": "2026-07-03",
        "intraday": {
            "is_trading": True, "price": 101.0, "pre_close": 100.0,
            "chg_pct": 1.0, "open_chg_pct": 0.5, "vwap": 99.0,
            "is_above_vwap": True, "intraday_vol_ratio": 1.4,
            "vol_note": "ok", "asof": "2026-07-03 10:30:00",
        },
    }
    out = prompt_mod.build_user_prompt(ctx)
    assert "盘中上下文" in out
    assert "昨日 EOD 放量倍数" in out          # 与盘中量比标签必须显著区分(建议#8)
    assert "盘中折算量比" in out
    # T-1 EOD 资金约束句钉死措辞
    assert "今日盘中资金未知" in out and "不得据此推测今日盘中资金动向" in out
    # 盘中护栏句(含"早盘折算通常偏高")
    assert "早盘折算通常偏高" in out


def test_build_user_prompt_non_trading_no_intraday_block_but_has_fund_guardrail():
    """非交易时段(context 无 intraday 键)→ 不渲染盘中块,但资金约束句照旧钉死。"""
    ctx = {
        "mode": "coach", "code": "603986", "name": "兆易创新",
        "pnl_pct": 3.2, "trade_day": 2,
        "form": {}, "fund": {}, "news": {"note": "无"}, "fund_asof": "2026-07-03",
    }
    out = prompt_mod.build_user_prompt(ctx)
    assert "盘中上下文" not in out
    assert "今日盘中资金未知" in out


def test_build_user_prompt_candidate_mode_no_intraday_block():
    """candidate 模式即便 context 意外带 intraday 键(理论不会发生)也不影响——
    此处验证候选正常路径确无 intraday 键时不渲染盘中块(与 coach 对照)。"""
    cand = prompt_mod.build_user_prompt({
        "mode": "candidate", "code": "603986", "name": "兆易创新", "sector": "半导体",
        "form": {}, "fund": {}, "news": {"note": "无"}, "fund_asof": "2026-07-03",
    })
    assert "盘中上下文" not in cand


def test_build_chat_context_block_coach_intraday_block():
    """build_chat_context_block(对话)同 build_user_prompt:盘中块 + 资金约束句。"""
    ctx = {
        "mode": "coach", "code": "603986", "name": "兆易创新",
        "pnl_pct": 3.2, "trade_day": 2,
        "form": {}, "fund": {}, "news": {"note": "无"}, "fund_asof": "2026-07-03",
        "intraday": {
            "is_trading": True, "price": 101.0, "pre_close": 100.0,
            "chg_pct": 1.0, "open_chg_pct": 0.5, "vwap": 99.0,
            "is_above_vwap": True, "intraday_vol_ratio": 1.4,
            "vol_note": "ok", "asof": "2026-07-03 10:30:00",
        },
    }
    out = prompt_mod.build_chat_context_block(ctx)
    assert "盘中上下文" in out
    assert "今日盘中资金未知" in out
