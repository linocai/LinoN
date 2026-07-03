"""v1.3.0 Phase A:三仓相关性护栏单测。

覆盖 plan §4 Phase A 验收标准①-④:
① 开仓落 positions.industry,且开仓路径不触发 load_industry_map() 同步联网
   (只调 industry_of,冷缓存开仓仍秒回不阻塞)。
② GET /positions/correlation 命中同行业返 conflict:true + 冲突明细;不同行业/空持仓/
   无行业数据返 conflict:false。
③ 纯函数 compute_correlation 覆盖 4 态:命中、不命中、待买行业空、持仓行业空串跳过;
   并覆盖同 code 排除。
④ 降级不误报(无 token → 行业映射空 → conflict 恒 false)。

铁律:不联网。行业映射用 monkeypatch 注入,不真拉 Tushare。
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.api.app import compute_correlation
from app.config import settings as settings_singleton
from app.db import store

TEST_TOKEN = "t" * 64
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


# —— ③ 纯函数 4 态(注入持仓列表 + 待买行业,不连库不连网)——————————————————

def test_compute_correlation_hit():
    holdings = [
        {"code": "600000", "name": "浦发银行", "industry": "银行"},
        {"code": "600036", "name": "招商银行", "industry": "银行"},
    ]
    r = compute_correlation("银行", holdings, exclude_code="600519")
    assert r["conflict"] is True
    assert r["industry"] == "银行"
    codes = {c["code"] for c in r["conflict_with"]}
    assert codes == {"600000", "600036"}


def test_compute_correlation_no_hit_different_industry():
    holdings = [{"code": "600519", "name": "贵州茅台", "industry": "白酒"}]
    r = compute_correlation("银行", holdings, exclude_code="")
    assert r["conflict"] is False
    assert r["conflict_with"] == []


def test_compute_correlation_target_industry_empty():
    """待买行业为空/None → 直接 conflict:false(无凭据不误报)。"""
    holdings = [{"code": "600000", "name": "浦发银行", "industry": "银行"}]
    assert compute_correlation("", holdings)["conflict"] is False
    assert compute_correlation(None, holdings)["conflict"] is False


def test_compute_correlation_skips_empty_industry_holdings():
    """持仓行业为 NULL/空串 → 跳过该行(防"空串==空串"误命中)。"""
    holdings = [
        {"code": "600000", "name": "浦发银行", "industry": ""},
        {"code": "600036", "name": "招商银行", "industry": None},
    ]
    r = compute_correlation("", holdings)   # 待买行业本就空,双重保险仍 false
    assert r["conflict"] is False
    # 待买行业非空但持仓行业空串/None,仍应跳过不误命中(target 非空模拟"银行"两字空串比较)
    r2 = compute_correlation("银行", holdings)
    assert r2["conflict"] is False
    assert r2["conflict_with"] == []


def test_compute_correlation_excludes_same_code():
    """排除与待买同 code 的持仓行(免"与自己同主线")。"""
    holdings = [{"code": "600519", "name": "贵州茅台", "industry": "白酒"}]
    r = compute_correlation("白酒", holdings, exclude_code="600519")
    assert r["conflict"] is False


def test_compute_correlation_no_holdings():
    assert compute_correlation("银行", [])["conflict"] is False


# —— ①②④ 端点 + 开仓不联网(需 TestClient,行业映射用 monkeypatch 注入)——————————

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_singleton, "DB_PATH", str(tmp_path / "corr.db"), raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: {}, raising=False)
    with TestClient(app_mod.app) as c:
        yield c, app_mod


def test_correlation_requires_auth(client):
    c, _ = client
    assert c.get("/api/v1/positions/correlation?code=600519").status_code == 401


def test_correlation_no_holdings_returns_false(client, monkeypatch):
    c, app_mod = client
    from app.screen import fetch as fetch_mod
    monkeypatch.setattr(fetch_mod, "load_industry_map", lambda force=False: {}, raising=False)
    monkeypatch.setattr(fetch_mod, "industry_of", lambda code: "白酒", raising=False)
    r = c.get("/api/v1/positions/correlation?code=600519", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["conflict"] is False and b["conflictWith"] == []


def test_correlation_hits_same_industry(client, monkeypatch):
    c, app_mod = client
    from app.screen import fetch as fetch_mod

    # 造一个白酒持仓(直接 store.open_position 带 industry,绕开开仓路径的只读限制)
    store.open_position(
        code="000858", name="五粮液", buy_price=100.0, qty=100,
        entry_reason="x", buy_date="2026-06-22", industry="白酒",
    )
    monkeypatch.setattr(fetch_mod, "load_industry_map", lambda force=False: {}, raising=False)
    monkeypatch.setattr(fetch_mod, "industry_of", lambda code: "白酒", raising=False)

    r = c.get("/api/v1/positions/correlation?code=600519", headers=AUTH)
    b = r.json()
    assert b["conflict"] is True
    assert b["industry"] == "白酒"
    assert b["conflictWith"][0]["code"] == "000858"


def test_correlation_different_industry_no_conflict(client, monkeypatch):
    c, app_mod = client
    from app.screen import fetch as fetch_mod

    store.open_position(
        code="000858", name="五粮液", buy_price=100.0, qty=100,
        entry_reason="x", buy_date="2026-06-22", industry="白酒",
    )
    monkeypatch.setattr(fetch_mod, "load_industry_map", lambda force=False: {}, raising=False)
    monkeypatch.setattr(fetch_mod, "industry_of", lambda code: "银行", raising=False)

    r = c.get("/api/v1/positions/correlation?code=600036", headers=AUTH)
    assert r.json()["conflict"] is False


def test_correlation_no_industry_data_degrades_false(client, monkeypatch):
    """④ 降级不误报:无 token → 行业映射空 → industry_of 恒 None → conflict 恒 false。"""
    c, app_mod = client
    from app.screen import fetch as fetch_mod

    store.open_position(
        code="000858", name="五粮液", buy_price=100.0, qty=100,
        entry_reason="x", buy_date="2026-06-22", industry="",   # 冷缓存开仓时未落到行业
    )
    monkeypatch.setattr(fetch_mod, "load_industry_map", lambda force=False: {}, raising=False)
    monkeypatch.setattr(fetch_mod, "industry_of", lambda code: None, raising=False)

    r = c.get("/api/v1/positions/correlation?code=600519", headers=AUTH)
    assert r.json()["conflict"] is False


def test_correlation_endpoint_exception_safe(client, monkeypatch):
    """行业映射拉取异常(如 Tushare 网络错误)→ 端点仍 200 且 conflict:false,不崩。"""
    c, app_mod = client
    from app.screen import fetch as fetch_mod

    def _boom(force=False):
        raise RuntimeError("network down")

    monkeypatch.setattr(fetch_mod, "load_industry_map", _boom, raising=False)
    r = c.get("/api/v1/positions/correlation?code=600519", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["conflict"] is False


# —— ① 开仓落 industry + 开仓路径绝不联网 ——————————————————————————————

def test_open_position_persists_industry(client, monkeypatch):
    c, app_mod = client
    from app.screen import fetch as fetch_mod
    monkeypatch.setattr(fetch_mod, "industry_of", lambda code: "半导体", raising=False)

    r = c.post("/api/v1/positions/open", json={
        "code": "603986", "buy_price": 50.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    assert r.status_code == 200
    pid = r.json()["position_id"]
    row = store.get_position(pid)
    assert row["industry"] == "半导体"


def test_open_position_industry_blank_when_cache_miss(client, monkeypatch):
    """冷缓存/查不到 → 落空串,不阻塞开仓(不抛异常、不 500)。"""
    c, app_mod = client
    from app.screen import fetch as fetch_mod
    monkeypatch.setattr(fetch_mod, "industry_of", lambda code: None, raising=False)

    r = c.post("/api/v1/positions/open", json={
        "code": "603986", "buy_price": 50.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    assert r.status_code == 200
    pid = r.json()["position_id"]
    row = store.get_position(pid)
    assert row["industry"] == ""


def test_open_position_never_calls_load_industry_map(client, monkeypatch):
    """🟡2 红线:开仓路径只调 industry_of,绝不触发 load_industry_map() 同步联网。

    把 load_industry_map 替身设为"调用即抛异常",若开仓路径不慎触发会直接暴露;
    再断言 industry_of 确实被调用过(证明用了只读缓存路径,不是整段被绕过)。
    """
    c, app_mod = client
    from app.screen import fetch as fetch_mod

    def _load_boom(force=False):
        raise AssertionError("开仓路径绝不应调用 load_industry_map()(冷缓存拉全市场会拖过客户端超时)")

    called = {"industry_of": False}

    def _industry_of(code):
        called["industry_of"] = True
        return "半导体"

    monkeypatch.setattr(fetch_mod, "load_industry_map", _load_boom, raising=False)
    monkeypatch.setattr(fetch_mod, "industry_of", _industry_of, raising=False)

    r = c.post("/api/v1/positions/open", json={
        "code": "603986", "buy_price": 50.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    assert r.status_code == 200   # 若误触发 load_industry_map,_boom 会被 _resolve_industry
    # 的 try/except 吞掉退化为空串而不是 500——所以额外用 called 断言确认真走了 industry_of。
    assert called["industry_of"] is True
    row = store.get_position(r.json()["position_id"])
    assert row["industry"] == "半导体"


def test_open_position_cold_cache_returns_fast_no_exception(client, monkeypatch):
    """冷缓存(industry_of 返回 None,即从未 load 过)开仓仍秒回、不阻塞、不抛异常。"""
    c, app_mod = client
    from app.screen import fetch as fetch_mod
    fetch_mod.reset_industry_cache()   # 确保真冷缓存态(未 load 过)
    # 不 monkeypatch industry_of/load_industry_map:验证真实 _resolve_industry 在
    # 冷缓存(_INDUSTRY_MAP 为空)下只做一次 dict.get 查不到,立即返回空串,不联网。

    import time
    t0 = time.monotonic()
    r = c.post("/api/v1/positions/open", json={
        "code": "603986", "buy_price": 50.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    elapsed = time.monotonic() - t0
    assert r.status_code == 200
    assert elapsed < 2.0   # 秒回(纯内存 dict 查找,不等网络)
    row = store.get_position(r.json()["position_id"])
    assert row["industry"] == ""
