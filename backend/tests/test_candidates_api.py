"""阶段2 D2:候选端点(GET /candidates + POST /candidates/refresh)单测。

不联网:_pipeline_fn 注入假流水线返回固定 rows;DB 临时;token 临时。
验证固定返回 Top rules.CANDIDATE_LIMIT=20(v1.3.0 C 起不再随 free_slots 截断/满仓闭门)、
无缓存 degraded、refresh 落表。
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
    """造 n 条 Candidate dict(rank 1..n;阶段3.1 带 score)。"""
    out = []
    for i in range(1, n + 1):
        out.append({
            "rank": i, "name": f"票{i}", "code": f"60000{i}", "sector": "半导体",
            "tag": "放量突破", "price": 10.0 + i, "chg": "+3.00%",
            "volMultiple": "2.8x", "volPct": 90, "flow": "+1.20亿",
            "turnover": "4.6%", "warn": None,
            "score": max(10, 100 - (i - 1) * 5),   # rank1→100 递减,末位不低于 SCORE_FLOOR
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


# —— refresh 落表 + GET 读缓存固定返回 Top 20(v1.3.0 C2/C4,不再随 free_slots)——
def test_refresh_then_get_returns_fixed_20(client):
    c, _ = client
    rr = c.post("/api/v1/candidates/refresh", headers=AUTH)
    assert rr.status_code == 200
    rb = rr.json()
    assert rb["ok"] is True and rb["count"] == 20 and rb["trade_date"] == "2026-05-06"
    assert rb["degraded"] is False

    g = c.get("/api/v1/candidates", headers=AUTH).json()
    assert g["degraded"] is False and g["trade_date"] == "2026-05-06"
    assert g["free_slots"] == 3
    assert len(g["candidates"]) == 20        # 固定 20(rules.CANDIDATE_LIMIT),不再截断
    # 形状对齐 Candidate(camelCase);阶段3.1 键集合 = 阶段2 键集合 + score(精确断言)。
    c0 = g["candidates"][0]
    for k in ("rank", "name", "code", "sector", "tag", "price", "chg",
              "volMultiple", "volPct", "flow", "turnover", "score"):
        assert k in c0
    # 键集合精确:阶段2 的 11 键 + score(warn=None 省略,不在集合内)
    expected_keys = {"rank", "name", "code", "sector", "tag", "price", "chg",
                     "volMultiple", "volPct", "flow", "turnover", "score"}
    assert set(c0.keys()) == expected_keys
    assert c0["score"] == 100                # rank=1 → score=100(_fake_rows)


# —— 候选条数不随持仓变化:开 2 仓仍返 20 ——
def test_candidate_count_unaffected_by_holdings(client):
    c, _ = client
    c.post("/api/v1/candidates/refresh", headers=AUTH)
    for i in range(2):
        c.post("/api/v1/positions/open", json={
            "code": f"60010{i}", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
        }, headers=AUTH)
    g = c.get("/api/v1/candidates", headers=AUTH).json()
    assert g["free_slots"] == 1              # free_slots 字段仍返回(供其他用途)
    assert len(g["candidates"]) == 20        # 但候选条数不再随之截断


# —— 满仓仍返 20、无闭门(v1.3.0 C 验收①,已删满仓闭门)——
def test_full_holdings_still_returns_20_no_closed_door(client):
    c, _ = client
    c.post("/api/v1/candidates/refresh", headers=AUTH)
    for i in range(3):
        c.post("/api/v1/positions/open", json={
            "code": f"60020{i}", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
        }, headers=AUTH)
    g = c.get("/api/v1/candidates", headers=AUTH).json()
    assert g["free_slots"] == 0
    assert len(g["candidates"]) == 20         # 满仓不再闭门,仍返 Top 20
    assert len(store.list_candidates("2026-05-06")) == 20


# —— 候选池不足 20 条时,原样返回不足数(不报错、不补空)——
def test_fewer_than_20_candidates_returns_all(client, monkeypatch):
    c, app_mod = client
    monkeypatch.setattr(
        app_mod, "_pipeline_fn",
        lambda basis: (_fake_rows(7), False, "ok", "2026-05-06"),
        raising=False,
    )
    c.post("/api/v1/candidates/refresh", headers=AUTH)
    g = c.get("/api/v1/candidates", headers=AUTH).json()
    assert len(g["candidates"]) == 7


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

    def _fake(code, name, sector, mode, pnl_pct, trade_day, question, history_digest=None):
        if capture is not None:
            capture.update(dict(code=code, name=name, sector=sector, mode=mode,
                                pnl_pct=pnl_pct, trade_day=trade_day, question=question,
                                history_digest=history_digest))
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


# —— F3:analyze 落 analysis_verdicts(响应契约不变,仅副作用)——————————————

def test_analyze_persists_verdict_using_candidate_entry_date(client, monkeypatch):
    """trade_date 取该 code 所属候选的 entry_date,即使 latest_candidate_date 已滚动。"""
    c, app_mod = client
    from app.db import store as store_mod

    # 先在 2026-06-23 刷一批候选(含 600003),再手动 upsert 一批新的 2026-06-24(滚动 latest)
    monkeypatch.setattr(
        app_mod, "_pipeline_fn",
        lambda basis: (_fake_rows(5), False, "ok", "2026-06-23"), raising=False,
    )
    c.post("/api/v1/candidates/refresh", headers=AUTH)
    store_mod.upsert_candidates("2026-06-24", _fake_rows(3))   # latest 滚到 06-24,不含 600003? 含
    assert store_mod.latest_candidate_date() == "2026-06-24"

    _inject_analyze(app_mod, monkeypatch, analysis=_legal_analysis("可进"))
    r = c.post("/api/v1/candidates/600003/analyze", headers=AUTH)
    assert r.status_code == 200
    # 600003 在两个快照里都存在(_fake_rows 从 1 起编号),candidate_entry_date_of
    # 取【最近一次】所属日 = 06-24(而非 06-23);验证落库确实用了该口径且非空。
    verdict = store_mod.get_verdict("2026-06-24", "600003")
    assert verdict == "可进"


def test_analyze_no_persist_when_code_not_in_any_candidate(client, monkeypatch):
    """查不到所属候选日(该 code 从未出现在任何候选快照)→ 不落,不报错。"""
    c, app_mod = client
    from app.db import store as store_mod

    _inject_analyze(app_mod, monkeypatch, analysis=_legal_analysis("可进"))
    r = c.post("/api/v1/candidates/999999/analyze", headers=AUTH)
    assert r.status_code == 200   # 响应不受影响
    # 从未刷新过候选缓存(该 client 的其他测试各自独立 DB)→ 查不到,不落不崩
    assert store_mod.candidate_entry_date_of("999999") is None


def test_coach_does_not_persist_verdict(client, monkeypatch):
    """coach(在持仓中间地带)一律不落 analysis_verdicts,避免污染候选回测。"""
    c, app_mod = client
    from app.db import store as store_mod

    monkeypatch.setattr(
        app_mod, "_pipeline_fn",
        lambda basis: (_fake_rows(5), False, "ok", "2026-06-23"), raising=False,
    )
    c.post("/api/v1/candidates/refresh", headers=AUTH)   # 600001 出现在候选里

    _inject_analyze(app_mod, monkeypatch, analysis=_legal_analysis("不进"))
    op = c.post("/api/v1/positions/open", json={
        "code": "600001", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    pid = op.json()["position_id"]
    r = c.post(f"/api/v1/positions/{pid}/coach", json={}, headers=AUTH)
    assert r.status_code == 200
    # coach 走了深判但不应落 analysis_verdicts(即使 600001 有 entry_date 可查到)
    assert store_mod.get_verdict("2026-06-23", "600001") is None


def test_analyze_persist_overwrites_with_latest_verdict(client, monkeypatch):
    """ON CONFLICT DO UPDATE:同一 (trade_date, code) 重复深判覆盖为最新一次。"""
    c, app_mod = client
    from app.db import store as store_mod

    monkeypatch.setattr(
        app_mod, "_pipeline_fn",
        lambda basis: (_fake_rows(3), False, "ok", "2026-06-23"), raising=False,
    )
    c.post("/api/v1/candidates/refresh", headers=AUTH)

    _inject_analyze(app_mod, monkeypatch, analysis=_legal_analysis("可进"))
    c.post("/api/v1/candidates/600001/analyze", headers=AUTH)
    assert store_mod.get_verdict("2026-06-23", "600001") == "可进"

    _inject_analyze(app_mod, monkeypatch, analysis=_legal_analysis("不进"))
    c.post("/api/v1/candidates/600001/analyze", headers=AUTH)
    assert store_mod.get_verdict("2026-06-23", "600001") == "不进"   # 覆盖为最新


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


# —— F4:GET /candidates/outcomes(只读统计,鉴权,本版本不接客户端)——————————

def test_outcomes_requires_auth(client):
    c, _ = client
    assert c.get("/api/v1/candidates/outcomes").status_code == 401


def test_outcomes_empty_table_returns_zero_not_500(client):
    c, _ = client
    r = c.get("/api/v1/candidates/outcomes", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["sample_total"] == 0
    assert b["by_rank_tier"] == [] and b["by_tag"] == [] and b["by_verdict"] == []
    assert "暂无回测样本" in b["note"]


def test_outcomes_aggregates_by_rank_tier_tag_verdict(client):
    c, _ = client
    from app.db import store as store_mod

    rows = [
        {"entry_date": "2026-06-20", "code": "600001", "name": "A", "rank": 1,
         "tag": "放量突破", "verdict": "可进", "entry_close": 10.0,
         "exit_date": "2026-06-25", "exit_close": 12.0, "ret_3d": 20.0},
        {"entry_date": "2026-06-20", "code": "600002", "name": "B", "rank": 3,
         "tag": "放量突破", "verdict": "不进", "entry_close": 10.0,
         "exit_date": "2026-06-25", "exit_close": 9.0, "ret_3d": -10.0},
        {"entry_date": "2026-06-20", "code": "600003", "name": "C", "rank": 8,
         "tag": "站上均线", "verdict": None, "entry_close": 5.0,
         "exit_date": "2026-06-25", "exit_close": 5.5, "ret_3d": 10.0},
        {"entry_date": "2026-06-20", "code": "600004", "name": "D", "rank": 12,
         "tag": "站上均线", "verdict": None, "entry_close": 8.0,
         "exit_date": "2026-06-25", "exit_close": 7.0, "ret_3d": -12.5},
    ]
    for r in rows:
        store_mod.upsert_candidate_outcome(r)

    r = c.get("/api/v1/candidates/outcomes", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["sample_total"] == 4

    tiers = {t["tier"]: t for t in b["by_rank_tier"]}
    assert tiers["1-5"]["n"] == 2   # rank 1,3
    assert tiers["1-5"]["avg_ret_3d"] == pytest.approx((20.0 - 10.0) / 2)
    assert tiers["1-5"]["win_rate"] == pytest.approx(0.5)
    assert tiers["6-10"]["n"] == 1   # rank 8
    assert tiers["11+"]["n"] == 1    # rank 12

    tags = {t["tag"]: t for t in b["by_tag"]}
    assert tags["放量突破"]["n"] == 2
    assert tags["站上均线"]["n"] == 2

    verdicts = {v["verdict"]: v for v in b["by_verdict"]}
    assert verdicts["可进"]["n"] == 1 and verdicts["可进"]["avg_ret_3d"] == pytest.approx(20.0)
    assert verdicts["不进"]["n"] == 1 and verdicts["不进"]["avg_ret_3d"] == pytest.approx(-10.0)
    # 两个 verdict=None 的行不进入 by_verdict


def test_outcomes_since_filters(client):
    c, _ = client
    from app.db import store as store_mod

    store_mod.upsert_candidate_outcome({
        "entry_date": "2026-06-10", "code": "600001", "name": "A", "rank": 1,
        "tag": "放量突破", "verdict": None, "entry_close": 10.0,
        "exit_date": "2026-06-13", "exit_close": 11.0, "ret_3d": 10.0,
    })
    store_mod.upsert_candidate_outcome({
        "entry_date": "2026-06-25", "code": "600002", "name": "B", "rank": 1,
        "tag": "放量突破", "verdict": None, "entry_close": 10.0,
        "exit_date": "2026-06-28", "exit_close": 11.0, "ret_3d": 10.0,
    })
    r = c.get("/api/v1/candidates/outcomes?since=2026-06-20", headers=AUTH)
    b = r.json()
    assert b["sample_total"] == 1
    assert b["since"] == "2026-06-20"
