"""v1.2.1 Phase A5:POST /chat 对话端点单测。

不联网:DeepSeek 用 httpx.MockTransport / 注入替身;不真调 Tushare。
覆盖(plan §4 A5):
  ① 首条候选对话 reply+verdict+is_first=true、非降级可进 → 落 analysis_verdicts;
  ② 追问轮(messages 含 assistant)is_first=false → 不落;
  ③ 降级(degraded=true)即便 is_first 也不落;
  ④ coach 模式非持仓 → 404;
  ⑤ 缺 key → 降级 reply + verdict=观望 + degraded=true + 仍 HTTP 200;
  ⑥ history_digest 进 prompt 而 review_ref 不进(build_chat_context_block 不含 review_ref);
  ⑦ 多轮 messages 原样透传进 payload。
另补:coach 模式以 pos code 为准(忽略 body.code)、chat_stock 同日追问命中缓存不重拉、
clamp_chat/degraded_chat 夹紧行为。
"""

import importlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings as settings_singleton
from app.db import store
from app.llm import deepseek
from app.llm import prompt as prompt_mod
from app.llm import analyze
from app.data.tushare_client import TushareResult

TEST_TOKEN = "t" * 64
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


# —— deepseek.chat / clamp_chat / degraded_chat(纯函数 + MockTransport)—————————

def _mock_transport(status, content_obj):
    def handler(request):
        body = {"choices": [{"message": {"content": content_obj}}]}
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def _ctx():
    return {"mode": "candidate", "code": "603986", "name": "兆易创新", "sector": "半导体",
            "form": {}, "fund": {}, "news": {"titles": []}, "fund_asof": "2026-07-02"}


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setattr(settings_singleton, "DEEPSEEK_API_KEY", "sk-test-key-123456", raising=False)


def test_degraded_chat_shape():
    out = deepseek.degraded_chat("测试原因")
    assert out["degraded"] is True
    assert out["verdict"] == "观望"
    assert "维持纪律" in out["reply"]


def test_clamp_chat_legal_passthrough():
    raw = {"reply": "这是一段合法的分析文本。", "verdict": "可进"}
    out = deepseek.clamp_chat(raw)
    assert out == {"reply": "这是一段合法的分析文本。", "verdict": "可进", "degraded": False}


def test_clamp_chat_illegal_verdict_to_neutral():
    out = deepseek.clamp_chat({"reply": "文本", "verdict": "强烈推荐"})
    assert out["verdict"] == "观望" and out["degraded"] is False


def test_clamp_chat_empty_reply_degrades():
    out = deepseek.clamp_chat({"reply": "", "verdict": "可进"})
    assert out["degraded"] is True and out["verdict"] == "观望"


def test_clamp_chat_non_dict_degrades():
    out = deepseek.clamp_chat("not a dict")
    assert out["degraded"] is True


def test_chat_legal_json(with_key):
    legal = json.dumps({"reply": "形态资金消息综合判断,可以关注。", "verdict": "可进"}, ensure_ascii=False)
    out = deepseek.chat([{"role": "user", "content": "能不能进?"}], _ctx(), transport=_mock_transport(200, legal))
    assert out["verdict"] == "可进" and out["degraded"] is False
    assert "关注" in out["reply"]


def test_chat_illegal_json_degrades(with_key):
    out = deepseek.chat([{"role": "user", "content": "x"}], _ctx(), transport=_mock_transport(200, "不是JSON{{{"))
    assert out["degraded"] is True and out["verdict"] == "观望"


def test_chat_non_200_degrades(with_key):
    out = deepseek.chat([{"role": "user", "content": "x"}], _ctx(), transport=_mock_transport(500, "{}"))
    assert out["degraded"] is True


def test_chat_timeout_degrades(with_key):
    def handler(request):
        raise httpx.TimeoutException("timed out")
    out = deepseek.chat([{"role": "user", "content": "x"}], _ctx(), transport=httpx.MockTransport(handler))
    assert out["degraded"] is True
    assert out["verdict"] == "观望"
    assert "维持纪律" in out["reply"]


def test_chat_missing_key_degrades(monkeypatch):
    monkeypatch.setattr(settings_singleton, "DEEPSEEK_API_KEY", None, raising=False)
    out = deepseek.chat([{"role": "user", "content": "x"}], _ctx())
    assert out["degraded"] is True
    assert out["verdict"] == "观望"


def test_chat_messages_transparently_passed(with_key):
    """多轮 messages 原样透传进 payload(A5 要点⑦)。"""
    captured = {}

    def handler(request):
        captured["payload"] = json.loads(request.content)
        body = {"choices": [{"message": {"content": json.dumps({"reply": "ok", "verdict": "观望"})}}]}
        return httpx.Response(200, json=body)

    history = [
        {"role": "user", "content": "分析一下这只票"},
        {"role": "assistant", "content": "形态还行"},
        {"role": "user", "content": "那如果明天低开呢?"},
    ]
    deepseek.chat(history, _ctx(), transport=httpx.MockTransport(handler))
    payload_messages = captured["payload"]["messages"]
    # 前两条是 system(CHAT_SYSTEM_PROMPT + 事实块),之后原样跟着 history
    assert payload_messages[-3:] == history
    assert payload_messages[0]["role"] == "system"
    assert payload_messages[1]["role"] == "system"


def test_chat_uses_chat_specific_timeout_constants():
    """决定7:对话专属超时常量,不复用 /analyze 的 12s×3。"""
    assert deepseek._CHAT_READ_TIMEOUT == 25.0
    assert deepseek._CHAT_CONNECT_TIMEOUT == 6.0
    assert deepseek._CHAT_MAX_ATTEMPTS == 2
    assert deepseek._READ_TIMEOUT == 12.0
    assert deepseek._MAX_ATTEMPTS == 3


# —— prompt:CHAT_SYSTEM_PROMPT / build_chat_context_block ——————————————————

def test_chat_system_prompt_has_output_schema():
    sp = prompt_mod.CHAT_SYSTEM_PROMPT
    assert "reply" in sp and "verdict" in sp
    assert "可进" in sp and "观望" in sp and "不进" in sp
    assert "-5%" in sp and "+15%" in sp and "D4" in sp


def test_build_chat_context_block_no_review_ref():
    """A5 要点⑥:history_digest 进 prompt 而 review_ref 不进。"""
    ctx = {
        "mode": "coach", "code": "601138", "name": "工业富联", "sector": "通信",
        "form": {}, "fund": {}, "news": {"titles": []}, "fund_asof": "2026-07-02",
        "pnl_pct": 2.5, "trade_day": 2,
        "history_digest": "近 5 笔:3 守线 / 2 破止损",
    }
    block = prompt_mod.build_chat_context_block(ctx)
    assert "历史纪律" in block and "守线" in block
    # review_ref 情绪串特征不出现(该 context 本就不含 review_ref 字段,函数也不读它)
    review_ref = "你上次 沪电股份 也是没在 -5% 走,亏了 8.2%"
    assert review_ref not in block
    assert "你上次" not in block


def test_build_chat_context_block_omits_digest_when_empty():
    ctx = {"mode": "candidate", "code": "603986", "name": "兆易创新", "sector": "半导体",
           "form": {}, "fund": {}, "news": {"titles": []}, "fund_asof": "2026-07-02",
           "history_digest": ""}
    block = prompt_mod.build_chat_context_block(ctx)
    assert "历史纪律" not in block


# —— analyze.chat_stock:编排 + 缓存 ————————————————————————————————————

def _ok_daily(code, start, end):
    import pandas as pd
    rows = []
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
        {"trade_date": "20260506", "net_amount": 1200.0},
        {"trade_date": "20260505", "net_amount": 800.0},
        {"trade_date": "20260504", "net_amount": 500.0},
    ]
    return TushareResult.success(pd.DataFrame(rows))


def _ok_adj_factor_flat(code, start, end):
    import pandas as pd
    rows = [{"trade_date": f"202605{30 - i:02d}" if (30 - i) <= 31 else "20260501",
             "adj_factor": 1.0} for i in range(30)]
    return TushareResult.success(pd.DataFrame(rows))


def _fail_fn(*a, **k):
    return TushareResult.fail("token 缺失")


def test_chat_stock_full_chain():
    captured = {}

    def _fake_chat(messages, context):
        captured["ctx"] = context
        captured["messages"] = messages
        return {"reply": "分析结论", "verdict": "可进", "degraded": False}

    out = analyze.chat_stock(
        "603986", [{"role": "user", "content": "能进吗"}],
        mode="candidate", name="兆易创新", sector="半导体",
        chat_fn=_fake_chat, daily_fn=_ok_daily, moneyflow_fn=_ok_moneyflow,
        sentiment_fn=lambda c: {"titles": ["放量"], "note": "", "degraded": False},
        adj_factor_fn=_ok_adj_factor_flat,
    )
    assert out["reply"] == "分析结论" and out["verdict"] == "可进" and out["degraded"] is False
    assert "fund_asof" in out
    ctx = captured["ctx"]
    assert ctx["form"]["vol_multiple"] == 3.0
    assert ctx["fund"]["net_mf_3d"] == 2500.0
    assert "history_digest" in ctx


def test_chat_stock_degraded_data_safe():
    out = analyze.chat_stock(
        "603986", [{"role": "user", "content": "x"}],
        daily_fn=_fail_fn, moneyflow_fn=_fail_fn,
        sentiment_fn=lambda c: {"titles": [], "note": "未获取到舆情", "degraded": True},
        chat_fn=lambda messages, ctx: deepseek.degraded_chat("数据缺失"),
    )
    assert out["degraded"] is True and out["verdict"] == "观望"


def test_chat_stock_deepseek_exception_safe():
    def _boom(messages, ctx):
        raise RuntimeError("boom")
    out = analyze.chat_stock(
        "603986", [{"role": "user", "content": "x"}],
        daily_fn=_fail_fn, moneyflow_fn=_fail_fn,
        sentiment_fn=lambda c: {"titles": [], "note": "x", "degraded": True},
        chat_fn=_boom,
    )
    assert out["degraded"] is True and out["verdict"] == "观望"


def test_chat_stock_same_day_cache_hit(monkeypatch):
    """同一 thread(同 code、同日)追问命中缓存,不重拉 daily(A3 缓存要求)。"""
    analyze._chat_fact_cache.clear()
    call_count = {"daily": 0}

    def _counting_daily(code, start, end):
        call_count["daily"] += 1
        return _ok_daily(code, start, end)

    def _fake_chat(messages, context):
        return {"reply": "r", "verdict": "观望", "degraded": False}

    common = dict(
        daily_fn=_counting_daily, moneyflow_fn=_ok_moneyflow,
        sentiment_fn=lambda c: {"titles": [], "note": "", "degraded": False},
        adj_factor_fn=_ok_adj_factor_flat, chat_fn=_fake_chat,
    )
    analyze.chat_stock("603986", [{"role": "user", "content": "第一问"}], **common)
    analyze.chat_stock(
        "603986",
        [{"role": "user", "content": "第一问"}, {"role": "assistant", "content": "r"},
         {"role": "user", "content": "追问"}],
        **common,
    )
    assert call_count["daily"] == 1   # 第二轮命中缓存,未重拉
    analyze._chat_fact_cache.clear()


# —— app.chat 端点:注入 _chat_fn,不联网 ————————————————————————————————

def _freeze_today(monkeypatch, iso: str) -> None:
    from datetime import date as _date
    y, m, d = (int(x) for x in iso.split("-"))
    frozen = _date(y, m, d)

    class _FixedDate(_date):
        @classmethod
        def today(cls):
            return frozen

    monkeypatch.setattr("datetime.date", _FixedDate)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "chat_api.db")
    monkeypatch.setattr(settings_singleton, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    _freeze_today(monkeypatch, "2026-07-02")   # 交易日,免周末/节假日 buy_date 漂移
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: {}, raising=False)

    cap = {}

    def _fake_chat_fn(code, messages, *, mode, name, sector, pnl_pct, trade_day, history_digest):
        cap["last_call"] = dict(
            code=code, messages=messages, mode=mode, name=name, sector=sector,
            pnl_pct=pnl_pct, trade_day=trade_day, history_digest=history_digest,
        )
        result = cap.get("_next_result") or {
            "reply": "默认回复", "verdict": "可进", "fund_asof": "2026-07-01", "degraded": False,
        }
        return result

    monkeypatch.setattr(app_mod, "_chat_fn", _fake_chat_fn, raising=False)
    with TestClient(app_mod.app) as c:
        yield c, db_path, cap


def _seed_candidate(db_path, code="603986", name="兆易创新", trade_date="2026-07-01"):
    store.upsert_candidates(trade_date, [{
        "rank": 1, "name": name, "code": code, "sector": "半导体",
        "tag": "放量突破", "price": 55.0, "chg": "+3.00%",
        "volMultiple": "2.8x", "volPct": 90, "flow": "+1.20亿",
        "turnover": "4.6%", "score": 88,
    }], db_path=db_path)


def test_chat_candidate_first_turn_persists_verdict_when_enter(client):
    """A5①:首条候选对话返 reply+verdict、is_first=true、非降级可进 → 落 analysis_verdicts。"""
    c, db_path, cap = client
    _seed_candidate(db_path)
    cap["_next_result"] = {"reply": "综合判断可以关注。", "verdict": "可进",
                            "fund_asof": "2026-07-01", "degraded": False}
    r = c.post("/api/v1/chat", json={
        "mode": "candidate", "code": "603986",
        "messages": [{"role": "user", "content": "能不能进?"}],
    }, headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["is_first"] is True
    assert b["reply"] == "综合判断可以关注。" and b["verdict"] == "可进"
    assert b["degraded"] is False and b["fund_asof"] == "2026-07-01"
    assert store.get_verdict("2026-07-01", "603986", db_path=db_path) == "可进"


def test_chat_candidate_followup_does_not_persist(client):
    """A5②:追问轮(messages 含 assistant)is_first=false → 不落库。"""
    c, db_path, cap = client
    _seed_candidate(db_path)
    cap["_next_result"] = {"reply": "追问回答。", "verdict": "可进",
                            "fund_asof": "2026-07-01", "degraded": False}
    r = c.post("/api/v1/chat", json={
        "mode": "candidate", "code": "603986",
        "messages": [
            {"role": "user", "content": "能不能进?"},
            {"role": "assistant", "content": "可以关注。"},
            {"role": "user", "content": "那止损怎么设?"},
        ],
    }, headers=AUTH)
    b = r.json()
    assert b["is_first"] is False
    assert store.get_verdict("2026-07-01", "603986", db_path=db_path) is None


def test_chat_candidate_degraded_first_turn_does_not_persist(client):
    """A5③:降级(degraded=true)即便 is_first 也不落。"""
    c, db_path, cap = client
    _seed_candidate(db_path)
    cap["_next_result"] = {"reply": "深判暂不可用。", "verdict": "观望",
                            "fund_asof": "2026-07-01", "degraded": True}
    r = c.post("/api/v1/chat", json={
        "mode": "candidate", "code": "603986",
        "messages": [{"role": "user", "content": "能不能进?"}],
    }, headers=AUTH)
    b = r.json()
    assert b["is_first"] is True and b["degraded"] is True
    assert store.get_verdict("2026-07-01", "603986", db_path=db_path) is None


def test_chat_coach_not_holding_404(client):
    """A5④:coach 模式非持仓 → 404 not_holding。"""
    c, _, _ = client
    r = c.post("/api/v1/chat", json={
        "mode": "coach", "code": "603986", "position_id": 9999,
        "messages": [{"role": "user", "content": "怎么办?"}],
    }, headers=AUTH)
    assert r.status_code == 404
    assert r.json()["detail"]["reason"] == "not_holding"


def test_chat_coach_missing_position_id_404(client):
    c, _, _ = client
    r = c.post("/api/v1/chat", json={
        "mode": "coach", "code": "603986",
        "messages": [{"role": "user", "content": "怎么办?"}],
    }, headers=AUTH)
    assert r.status_code == 404


def test_chat_coach_uses_pos_code_ignoring_body_code(client):
    """coach 模式以 pos["code"] 为准,忽略 body.code。"""
    c, db_path, cap = client
    op = c.post("/api/v1/positions/open", json={
        "code": "601138", "name": "工业富联", "buy_price": 100.0, "qty": 100,
        "entry_reason": "x",
    }, headers=AUTH)
    pid = op.json()["position_id"]

    r = c.post("/api/v1/chat", json={
        "mode": "coach", "code": "999999", "position_id": pid,   # body.code 故意传错
        "messages": [{"role": "user", "content": "怎么办?"}],
    }, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["code"] == "601138"
    assert cap["last_call"]["code"] == "601138"


def test_chat_missing_key_degrades_via_real_chat_stock(monkeypatch, tmp_path):
    """A5⑤:缺 key → 降级 reply + verdict=观望 + degraded=true + 仍 HTTP 200(走真 chat_stock,不注入 _chat_fn)。"""
    db_path = str(tmp_path / "chat_nokey.db")
    monkeypatch.setattr(settings_singleton, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    monkeypatch.setattr(settings_singleton, "DEEPSEEK_API_KEY", None, raising=False)
    _freeze_today(monkeypatch, "2026-07-02")
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: {}, raising=False)
    # 不 monkeypatch _chat_fn:走真 _default_chat_fn → chat_stock → deepseek.chat(缺 key)
    monkeypatch.setattr(analyze, "_chat_fact_cache", {})

    with TestClient(app_mod.app) as c:
        r = c.post("/api/v1/chat", json={
            "mode": "candidate", "code": "603986",
            "messages": [{"role": "user", "content": "能不能进?"}],
        }, headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["degraded"] is True
    assert b["verdict"] == "观望"
    assert "维持纪律" in b["reply"]


def test_chat_history_digest_injected_review_ref_not(client):
    """A5⑥(端点层):history_digest 传进 _chat_fn,不含 review_ref 措辞。"""
    c, db_path, cap = client
    pid_hist = store.open_position("002463", "沪电股份", 100.0, 100, "追高", "2026-06-20", db_path=db_path)
    store.close_position(pid_hist, 90.0, close_time="2026-06-25 10:00:00", holding_trade_days=2, db_path=db_path)

    _seed_candidate(db_path)
    c.post("/api/v1/chat", json={
        "mode": "candidate", "code": "603986",
        "messages": [{"role": "user", "content": "能不能进?"}],
    }, headers=AUTH)
    digest = cap["last_call"]["history_digest"]
    assert digest and ("守线" in digest or "破" in digest)
    assert "你" not in digest   # review_ref 才用第二人称"你",history_digest 是中性统计


def test_chat_multi_turn_messages_passed_through(client):
    """A5⑦:多轮 messages 原样透传进 _chat_fn。"""
    c, db_path, cap = client
    _seed_candidate(db_path)
    history = [
        {"role": "user", "content": "分析一下"},
        {"role": "assistant", "content": "形态还行"},
        {"role": "user", "content": "资金呢?"},
    ]
    c.post("/api/v1/chat", json={
        "mode": "candidate", "code": "603986", "messages": history,
    }, headers=AUTH)
    assert cap["last_call"]["messages"] == history
