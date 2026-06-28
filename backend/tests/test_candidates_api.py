"""阶段2 D2:候选端点(GET /candidates + POST /candidates/refresh)单测。

不联网:_pipeline_fn 注入假流水线返回固定 rows;DB 临时;token 临时。
验证截断随 free_slots(满仓闭门)、无缓存 degraded、refresh 落表。
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.config import settings as settings_singleton
from app.db import store

TEST_TOKEN = "t" * 64
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _freeze_today(monkeypatch, iso: str) -> None:
    """冻结 date.today() 到指定日期(沿 test_api.py D5 三态测试的写法)。

    `_current_trade_date`(开仓 buy_date)与 coach 端点的 D 计数都用 `date.today()`;
    不冻结则在周末/节假日跑会因 buy_date 取下一交易日(未来)致 trade_day 计数为 0,
    测试脆弱。冻结到交易日即让 [buy_date, today] 成为确定的 D1。
    """
    from datetime import date as _date

    y, m, d = (int(x) for x in iso.split("-"))
    frozen = _date(y, m, d)

    class _FixedDate(_date):
        @classmethod
        def today(cls):
            return frozen

    monkeypatch.setattr("datetime.date", _FixedDate)


def _fake_rows(n):
    """造 n 条 Candidate dict(rank 1..n)。"""
    out = []
    for i in range(1, n + 1):
        out.append({
            "rank": i, "name": f"票{i}", "code": f"60000{i}", "sector": "半导体",
            "tag": "放量突破", "price": 10.0 + i, "chg": "+3.00%",
            "volMultiple": "2.8x", "volPct": 90, "flow": "+1.20亿",
            "turnover": "4.6%", "warn": None,
        })
    return out


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_singleton, "DB_PATH", str(tmp_path / "cand_api.db"), raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    # 有 token 假象,避免 no_tushare_token 分支干扰(真实 pipeline 已被替身覆盖)
    monkeypatch.setattr(settings_singleton, "TUSHARE_TOKEN", "x" * 32, raising=False)
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: {}, raising=False)
    # 默认 pipeline 替身:返回 20 条假候选,trade_date 固定
    monkeypatch.setattr(
        app_mod, "_pipeline_fn",
        lambda basis: (_fake_rows(20), False, "ok", "2026-05-06"),
        raising=False,
    )
    with TestClient(app_mod.app) as c:
        yield c, app_mod


# —— 鉴权 ——
def test_candidates_requires_auth(client):
    c, _ = client
    assert c.get("/api/v1/candidates").status_code == 401
    assert c.post("/api/v1/candidates/refresh").status_code == 401


# —— 无缓存 → degraded 空列表 ——
def test_candidates_empty_no_cache(client):
    c, _ = client
    r = c.get("/api/v1/candidates", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["candidates"] == [] and b["degraded"] is True
    assert b["free_slots"] == 3 and b["reason"] == "no_cache"


# —— 无 token → degraded reason=no_tushare_token ——
def test_candidates_no_tushare_token(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(settings_singleton, "TUSHARE_TOKEN", None, raising=False)
    b = c.get("/api/v1/candidates", headers=AUTH).json()
    assert b["degraded"] is True and b["reason"] == "no_tushare_token"


# —— refresh 落表 + GET 读缓存按 5×free_slots 截断(空仓 3 → 15)——
def test_refresh_then_get_truncates_15(client):
    c, _ = client
    rr = c.post("/api/v1/candidates/refresh", headers=AUTH)
    assert rr.status_code == 200
    rb = rr.json()
    assert rb["ok"] is True and rb["count"] == 20 and rb["trade_date"] == "2026-05-06"
    assert rb["degraded"] is False

    g = c.get("/api/v1/candidates", headers=AUTH).json()
    assert g["degraded"] is False and g["trade_date"] == "2026-05-06"
    assert g["free_slots"] == 3
    assert len(g["candidates"]) == 15        # 5×3 截断
    # 形状对齐 Candidate(camelCase)
    c0 = g["candidates"][0]
    for k in ("rank", "name", "code", "sector", "tag", "price", "chg",
              "volMultiple", "volPct", "flow", "turnover"):
        assert k in c0


# —— 截断随 free_slots:开 2 仓 → free=1 → 取 5 ——
def test_truncation_follows_free_slots(client):
    c, _ = client
    c.post("/api/v1/candidates/refresh", headers=AUTH)
    for i in range(2):
        c.post("/api/v1/positions/open", json={
            "code": f"60010{i}", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
        }, headers=AUTH)
    g = c.get("/api/v1/candidates", headers=AUTH).json()
    assert g["free_slots"] == 1
    assert len(g["candidates"]) == 5         # 5×1


# —— 满仓闭门:开 3 仓 → free=0 → 空列表 ——
def test_full_holdings_closes_door(client):
    c, _ = client
    c.post("/api/v1/candidates/refresh", headers=AUTH)
    for i in range(3):
        c.post("/api/v1/positions/open", json={
            "code": f"60020{i}", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
        }, headers=AUTH)
    g = c.get("/api/v1/candidates", headers=AUTH).json()
    assert g["free_slots"] == 0
    assert g["candidates"] == []             # 闭门(缓存仍在,运行时截断为 0)
    # 但缓存表仍有 20 条(端点只是运行时截断)
    assert len(store.list_candidates("2026-05-06")) == 20


# —— refresh degraded(pipeline 失败)→ degraded:true count=0 ——
def test_refresh_degraded(client, monkeypatch):
    c, app_mod = client
    monkeypatch.setattr(
        app_mod, "_pipeline_fn",
        lambda basis: ([], True, "token 缺失", "2026-05-06"),
        raising=False,
    )
    rb = c.post("/api/v1/candidates/refresh", headers=AUTH).json()
    assert rb["ok"] is True and rb["count"] == 0 and rb["degraded"] is True


# —— refresh pipeline 抛异常也不崩 ——
def test_refresh_pipeline_exception_safe(client, monkeypatch):
    c, app_mod = client

    def _boom(basis):
        raise RuntimeError("network down")

    monkeypatch.setattr(app_mod, "_pipeline_fn", _boom, raising=False)
    r = c.post("/api/v1/candidates/refresh", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["degraded"] is True and r.json()["count"] == 0


# —— D4:on-demand 深判 /candidates/{code}/analyze ————————————————————

def _legal_analysis(verdict="可进"):
    axis = {"value": "突破", "tone": "good", "text": "放量"}
    return {
        "form": dict(axis), "fund": dict(axis),
        "news": {"value": "无雷", "tone": "neutral", "text": "温和"},
        "verdict": verdict, "plan": "止损 -5%,止盈 +15%,D4 清仓。",
    }


def _inject_analyze(app_mod, monkeypatch, analysis=None, fund_asof="2026-05-06", capture=None):
    analysis = analysis or _legal_analysis()

    def _fake(code, name, sector, mode, pnl_pct, trade_day, question):
        if capture is not None:
            capture.update(dict(code=code, name=name, sector=sector, mode=mode,
                                pnl_pct=pnl_pct, trade_day=trade_day, question=question))
        return {"analysis": analysis, "fund_asof": fund_asof}

    monkeypatch.setattr(app_mod, "_analyze_fn", _fake, raising=False)


def test_analyze_requires_auth(client):
    c, _ = client
    assert c.post("/api/v1/candidates/603986/analyze").status_code == 401


def test_analyze_returns_structured_card(client, monkeypatch):
    c, app_mod = client
    cap = {}
    _inject_analyze(app_mod, monkeypatch, capture=cap)
    r = c.post("/api/v1/candidates/603986/analyze", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["code"] == "603986"
    assert b["fund_asof"] == "2026-05-06"
    a = b["analysis"]
    for k in ("form", "fund", "news", "verdict", "plan"):
        assert k in a
    assert a["verdict"] == "可进" and a["form"]["tone"] == "good"
    assert cap["mode"] == "candidate"


def test_analyze_meta_from_candidate_cache(client, monkeypatch):
    c, app_mod = client
    cap = {}
    _inject_analyze(app_mod, monkeypatch, capture=cap)
    # 先刷候选(默认 _pipeline_fn 产 20 条,code 600001..600020,name 票i,sector 半导体)
    c.post("/api/v1/candidates/refresh", headers=AUTH)
    c.post("/api/v1/candidates/600003/analyze", headers=AUTH)
    assert cap["name"] == "票3" and cap["sector"] == "半导体"


def test_analyze_degraded_card_still_200(client, monkeypatch):
    c, app_mod = client
    # 注入降级占位卡(verdict=观望,三轴 neutral)
    deg = {
        "form": {"value": "暂无", "tone": "neutral", "text": "降级"},
        "fund": {"value": "暂无", "tone": "neutral", "text": "降级"},
        "news": {"value": "暂无", "tone": "neutral", "text": "降级"},
        "verdict": "观望", "plan": "维持纪律。",
    }
    _inject_analyze(app_mod, monkeypatch, analysis=deg)
    r = c.post("/api/v1/candidates/603986/analyze", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["analysis"]["verdict"] == "观望"


# —— D4:中间地带 /positions/{id}/coach ————————————————————————————————

def test_coach_requires_auth(client):
    c, _ = client
    assert c.post("/api/v1/positions/1/coach", json={}).status_code == 401


def test_coach_not_holding_404(client):
    c, _ = client
    r = c.post("/api/v1/positions/999/coach", json={}, headers=AUTH)
    assert r.status_code == 404
    assert r.json()["detail"]["reason"] == "not_holding"


def test_coach_returns_binary_advice(client, monkeypatch):
    c, app_mod = client
    cap = {}
    _inject_analyze(app_mod, monkeypatch, analysis=_legal_analysis("不进"), capture=cap)
    # 注入实时价替身,给 pnl_pct
    monkeypatch.setattr(app_mod, "_quotes_fn",
                        lambda codes: {"600000": type("Q", (), {"price": 103.0})()},
                        raising=False)
    # 冻结日期到交易日(2026-06-23 周二),否则周末跑时 _current_trade_date 取下周一
    # (未来 buy_date)→ count[buy_date, today]=0,trade_day 断言脆弱(同 test_api D5 写法)。
    _freeze_today(monkeypatch, "2026-06-23")
    op = c.post("/api/v1/positions/open", json={
        "code": "600000", "buy_price": 100.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    pid = op.json()["position_id"]
    r = c.post(f"/api/v1/positions/{pid}/coach", json={"question": "还能拿吗"}, headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["advice"] == "清"     # verdict 不进 → 清
    assert "analysis" in b and "fund_asof" in b and b["reason"]
    assert cap["mode"] == "coach" and cap["question"] == "还能拿吗"
    assert cap["pnl_pct"] == pytest.approx(3.0)        # (103-100)/100
    # 买入日=今日(交易日)→ count[2026-06-23, 2026-06-23]=1(D1),确定值非 >=1。
    assert cap["trade_day"] == 1


def test_coach_advice_hold_when_watch(client, monkeypatch):
    c, app_mod = client
    _inject_analyze(app_mod, monkeypatch, analysis=_legal_analysis("观望"))
    op = c.post("/api/v1/positions/open", json={
        "code": "600001", "buy_price": 50.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    pid = op.json()["position_id"]
    b = c.post(f"/api/v1/positions/{pid}/coach", json={}, headers=AUTH).json()
    assert b["advice"] == "拿"    # 观望 → 拿
