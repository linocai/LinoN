"""阶段3 G4:教练大脑注入(brain.py + prompt guardrail + 两路径分流)单测。

覆盖 plan §4.4 G4 验收:
  ① build_review_ref 破止损历史 → 正确第二人称;无破线历史 → None;
  ② coach 响应带/不带 review_ref 两态,advice/reason/analysis/fund_asof 契约不回归;
  ③ prompt 注入 history_digest 后仍返合法 DeepAnalysis;两路径分流断言:
     进 prompt 的 context 含 history_digest(中性串)、review_ref(情绪串)不出现在传给 deepseek_fn 的任何字段;
  ④ 解耦断言:同票"注入 vs 不注入 history_digest",deepseek_fn 收到的判定输入不因历史系统性变保守;
  ⑤ 无历史/无 DeepSeek key → 全链路降级不崩。
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.config import settings as settings_singleton
from app.db import store
from app.llm import analyze, deepseek, prompt as prompt_mod
from app.review.brain import build_history_digest, build_review_ref

TEST_TOKEN = "t" * 64
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _trade(code, name, pnl, kept_stop, kept_time, broke_rule, close_time):
    return {
        "code": code, "name": name, "pnl": pnl,
        "kept_stop": int(kept_stop), "kept_take": 0,
        "kept_time": int(kept_time), "broke_rule": int(broke_rule),
        "close_time": close_time,
    }


# —— ①:build_review_ref ————————————————————————————————————————————

def test_review_ref_broke_stop_second_person():
    trades = [
        _trade("002463", "沪电股份", -8.2, False, True, True, "2026-06-30 10:00:00"),
    ]
    ref = build_review_ref("601138", trades_fn=lambda: trades)
    assert ref is not None
    assert "沪电股份" in ref and "没在 -5% 走" in ref and "8.2%" in ref
    assert ref.startswith("你")


def test_review_ref_broke_time():
    trades = [
        _trade("600111", "某票", 1.2, True, False, True, "2026-06-30 10:00:00"),
    ]
    ref = build_review_ref("601138", trades_fn=lambda: trades)
    assert "持过 D4 没清" in ref


def test_review_ref_none_when_no_broke_history():
    trades = [
        _trade("603986", "兆易创新", 16.0, True, True, False, "2026-06-30 10:00:00"),  # 守
    ]
    assert build_review_ref("601138", trades_fn=lambda: trades) is None
    assert build_review_ref("601138", trades_fn=lambda: []) is None


def test_review_ref_takes_latest_two():
    trades = [
        _trade("600001", "A", -7.0, False, True, True, "2026-06-01 10:00:00"),
        _trade("600002", "B", -9.0, False, True, True, "2026-06-20 10:00:00"),
        _trade("600003", "C", -8.0, False, True, True, "2026-06-30 10:00:00"),
    ]
    ref = build_review_ref("601138", trades_fn=lambda: trades)
    # 取最近两笔(C, B),最早的 A 不进
    assert "C" in ref and "B" in ref and "A" not in ref


# —— build_history_digest ————————————————————————————————————————

def test_history_digest_neutral_stats():
    trades = [
        _trade("600001", "A", 5.0, True, True, False, "2026-06-25 10:00:00"),
        _trade("600002", "B", 6.0, True, True, False, "2026-06-26 10:00:00"),
        _trade("600003", "C", 7.0, True, True, False, "2026-06-27 10:00:00"),
        _trade("600004", "D", -8.0, False, True, True, "2026-06-28 10:00:00"),
        _trade("600005", "E", 1.0, True, False, True, "2026-06-29 10:00:00"),
    ]
    d = build_history_digest(trades_fn=lambda: trades)
    assert d.startswith("近 5 笔:")
    assert "3 守线" in d and "1 破止损" in d and "1 破时间" in d
    # 中性:不带第二人称、不带情绪强措辞
    assert "你" not in d and "亏了" not in d


def test_history_digest_empty_when_no_history():
    assert build_history_digest(trades_fn=lambda: []) == ""


# —— ③:两路径分流(review_ref 绝不进 prompt / history_digest 进 prompt)————

def test_history_digest_in_prompt_review_ref_not():
    """核心分流断言:history_digest(中性)进 prompt;review_ref(情绪)不进任何 deepseek_fn 字段。"""
    captured = {}

    def _fake_deepseek(context):
        captured["ctx"] = context
        return deepseek.degraded_analysis("测试")

    # 直接调 analyze_stock 注入 history_digest(不注入 review_ref——它本就不该进这里)
    out = analyze.analyze_stock(
        "601138", "工业富联", "半导体",
        mode="coach", pnl_pct=3.0, trade_day=2,
        history_digest="近 5 笔:3 守线 / 2 破止损",
        daily_fn=lambda c, s, e: _fail_result(),
        moneyflow_fn=lambda c, s, e: _fail_result(),
        sentiment_fn=lambda c: {"titles": [], "note": "x", "degraded": True},
        deepseek_fn=_fake_deepseek,
    )
    ctx = captured["ctx"]
    # history_digest 在 context 里
    assert ctx["history_digest"] == "近 5 笔:3 守线 / 2 破止损"
    # 拼进 user prompt 的【历史纪律】节
    user_prompt = prompt_mod.build_user_prompt(ctx)
    assert "【历史纪律" in user_prompt and "3 守线 / 2 破止损" in user_prompt
    # review_ref 的情绪串绝不出现在 context 任何字段 / user prompt 里
    review_ref = "你上次 沪电股份 也是没在 -5% 走,亏了 8.2%"
    for v in ctx.values():
        assert review_ref not in str(v)
    assert review_ref not in user_prompt


def test_prompt_no_history_section_when_digest_empty():
    ctx = {
        "mode": "coach", "code": "601138", "name": "工业富联",
        "form": {}, "fund": {}, "news": {"note": "x"}, "fund_asof": "2026-06-30",
        "history_digest": "",
    }
    up = prompt_mod.build_user_prompt(ctx)
    assert "【历史纪律" not in up   # 空 digest → 不加节


def test_system_prompt_has_guardrail():
    sp = prompt_mod.SYSTEM_PROMPT
    assert "历史纪律" in sp
    assert "不得据此改变 verdict 判定标准" in sp or "不得据此改" in sp
    assert "verdict" in sp


# —— ④:解耦断言(注入 vs 不注入,verdict 判定输入不系统性变保守)————————

def test_injection_decoupled_from_verdict_judgement():
    """同一票在 注入 history_digest / 不注入 两种 context 下,deepseek_fn 收到的
    形态/资金判定输入(form/fund/news)完全一致——历史只多加一节文案,不改判定素材。"""
    seen = []

    def _fake_deepseek(context):
        # 记录判定素材(不含 history_digest 的部分)
        seen.append({k: context.get(k) for k in ("form", "fund", "news", "pnl_pct", "trade_day")})
        return deepseek.degraded_analysis("测试")

    common = dict(
        code="601138", name="工业富联", sector="半导体", mode="coach",
        pnl_pct=3.0, trade_day=2,
        daily_fn=lambda c, s, e: _fail_result(),
        moneyflow_fn=lambda c, s, e: _fail_result(),
        sentiment_fn=lambda c: {"titles": [], "note": "x", "degraded": True},
        deepseek_fn=_fake_deepseek,
    )
    analyze.analyze_stock(**common, history_digest="")                       # 不注入
    analyze.analyze_stock(**common, history_digest="近 5 笔:1 守线 / 4 破止损")  # 注入(历史很差)

    # 两次判定素材完全一致(历史不改判定输入)
    assert seen[0] == seen[1]


# —— ②/⑤:coach 端点带/不带 review_ref + 降级不崩 ————————————————————————

@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "brain_api.db")
    monkeypatch.setattr(settings_singleton, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: {}, raising=False)

    cap = {}

    def _fake_analyze(code, name, sector, mode, pnl_pct, trade_day, question, history_digest=None):
        cap["history_digest"] = history_digest
        return {
            "analysis": {
                "form": {"value": "x", "tone": "good", "text": "y"},
                "fund": {"value": "x", "tone": "good", "text": "y"},
                "news": {"value": "x", "tone": "neutral", "text": "y"},
                "verdict": "观望", "plan": "维持纪律。",
            },
            "fund_asof": "2026-06-30",
        }

    monkeypatch.setattr(app_mod, "_analyze_fn", _fake_analyze, raising=False)
    with TestClient(app_mod.app) as c:
        yield c, db_path, cap


def _open_holding(client_tuple, code="601138", name="工业富联"):
    c, _, _ = client_tuple
    op = c.post("/api/v1/positions/open", json={
        "code": code, "name": name, "buy_price": 100.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    return op.json()["position_id"]


def test_coach_includes_review_ref_when_broke_history(client):
    c, db_path, cap = client
    # 种一条历史破止损 trade(经 close_position 自然落库,含 name/note)
    pid_hist = store.open_position("002463", "沪电股份", 100.0, 100, "追高", "2026-06-20", db_path=db_path)
    store.close_position(pid_hist, 90.0, close_time="2026-06-25 10:00:00", holding_trade_days=2, db_path=db_path)

    pid = _open_holding(client)
    r = c.post(f"/api/v1/positions/{pid}/coach", json={}, headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    # 契约不回归
    assert b["ok"] is True and b["advice"] in ("拿", "清")
    assert "analysis" in b and "fund_asof" in b and "reason" in b
    # review_ref 出现(带情绪第二人称)
    assert "review_ref" in b
    assert "沪电股份" in b["review_ref"] and "你" in b["review_ref"]
    # history_digest 已注入 _analyze_fn(中性统计,非 review_ref)
    assert cap["history_digest"] and "守线" in cap["history_digest"]
    assert "你" not in cap["history_digest"]


def test_coach_omits_review_ref_when_no_broke_history(client):
    c, db_path, cap = client
    # 只有守线历史 → 无 review_ref
    pid_hist = store.open_position("603986", "兆易创新", 100.0, 100, "x", "2026-06-20", db_path=db_path)
    store.close_position(pid_hist, 116.0, close_time="2026-06-25 10:00:00", holding_trade_days=2, db_path=db_path)

    pid = _open_holding(client)
    b = c.post(f"/api/v1/positions/{pid}/coach", json={}, headers=AUTH).json()
    assert b["ok"] is True
    assert "review_ref" not in b   # 无破线历史 → 省略字段(非占位)


def test_coach_no_history_no_crash(client):
    c, db_path, cap = client
    # 空库无历史 → review_ref 省略、history_digest 空,不崩
    pid = _open_holding(client)
    b = c.post(f"/api/v1/positions/{pid}/coach", json={}, headers=AUTH).json()
    assert b["ok"] is True
    assert "review_ref" not in b
    assert cap["history_digest"] == ""


# —— 辅助 ——

class _R:
    ok = False
    data = None
    reason = "fail"


def _fail_result():
    return _R()
