"""阶段1 A.1/A.2/A.4 ack:FastAPI 鉴权 + 开/清仓录入 + 漏录防护 + ack 端点。

用 TestClient(触发 lifespan)。关掉后台监控轮询(ENABLE_MONITOR=False)避免干扰;
DB 指向 tmp 路径(monkeypatch settings.DB_PATH);API_TOKEN 用临时 64 字符。
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.config import settings as settings_singleton
from app.db import store

TEST_TOKEN = "t" * 64
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 临时 DB + 临时 token;关后台监控
    monkeypatch.setattr(settings_singleton, "DB_PATH", str(tmp_path / "api.db"), raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    with TestClient(app_mod.app) as c:
        yield c


# —— health 免鉴权 ——
def test_health_no_auth(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and "version" in body


# —— 鉴权 401 ——
def test_missing_token_401(client):
    assert client.get("/api/v1/positions").status_code == 401


def test_wrong_token_401(client):
    r = client.get("/api/v1/positions", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_devices_requires_auth(client):
    assert client.post("/api/v1/devices", json={"token": "abc", "platform": "ios"}).status_code == 401


# —— A.1 设备注册 upsert 不增行 ——
def test_device_upsert_idempotent(client):
    for _ in range(3):
        r = client.post("/api/v1/devices", json={"token": "dev-token-1", "platform": "ios"}, headers=AUTH)
        assert r.status_code == 200 and r.json()["ok"] is True
    assert len(store.list_device_tokens()) == 1


# —— A.2 开仓闭环 ——
def test_open_returns_position_and_stop_line(client):
    r = client.post("/api/v1/positions/open", json={
        "code": "603986", "buy_price": 100.0, "qty": 200, "entry_reason": "放量突破",
    }, headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["position_id"] >= 1
    assert b["stop_line"] == 95.0          # buy×0.95
    assert b["take_line"] == 115.0
    assert "buy_date" in b


# —— A.2 满仓 409 slots_full ——
def test_slots_full_409(client):
    for i in range(3):
        r = client.post("/api/v1/positions/open", json={
            "code": f"60000{i}", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
        }, headers=AUTH)
        assert r.status_code == 200
    r4 = client.post("/api/v1/positions/open", json={
        "code": "600009", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    assert r4.status_code == 409
    assert r4.json()["detail"]["reason"] == "slots_full"


# —— A.2 重复 code 409 duplicate_holding ——
def test_duplicate_holding_409(client):
    body = {"code": "600000", "buy_price": 10.0, "qty": 100, "entry_reason": "x"}
    assert client.post("/api/v1/positions/open", json=body, headers=AUTH).status_code == 200
    r2 = client.post("/api/v1/positions/open", json=body, headers=AUTH)
    assert r2.status_code == 409
    assert r2.json()["detail"]["reason"] == "duplicate_holding"


# —— A.2 字段校验 422 ——
@pytest.mark.parametrize("bad", [
    {"code": "600000", "buy_price": -1, "qty": 100, "entry_reason": "x"},   # 负价
    {"code": "600000", "buy_price": 10.0, "qty": 0, "entry_reason": "x"},   # 0 量
    {"code": "600000", "buy_price": 10.0, "qty": 100},                       # 缺 entry_reason
    {"buy_price": 10.0, "qty": 100, "entry_reason": "x"},                    # 缺 code
])
def test_open_field_validation_422(client, bad):
    assert client.post("/api/v1/positions/open", json=bad, headers=AUTH).status_code == 422


# —— A.2 列持仓形状对齐 Models.swift ——
def test_list_positions_shape(client):
    client.post("/api/v1/positions/open", json={
        "code": "603986", "name": "兆易创新", "buy_price": 100.0, "qty": 200, "entry_reason": "突破",
    }, headers=AUTH)
    r = client.get("/api/v1/positions", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["free_slots"] == 2
    h = b["holdings"][0]
    # 含 name,不含 stop_line(客户端派生)
    assert h["name"] == "兆易创新"
    assert "stop_line" not in h
    for k in ("id", "code", "buy_price", "qty", "entry_reason", "buy_date"):
        assert k in h


# —— A.2 清仓闭环 + 重复清仓 404 ——
def test_close_loop_and_double_close_404(client):
    r = client.post("/api/v1/positions/open", json={
        "code": "600000", "buy_price": 100.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    pid = r.json()["position_id"]

    rc = client.post(f"/api/v1/positions/{pid}/close", json={"sell_price": 116.0}, headers=AUTH)
    assert rc.status_code == 200
    cb = rc.json()
    assert cb["ok"] is True and cb["trade_id"] >= 1
    assert abs(cb["pnl"] - 16.0) < 1e-6
    assert cb["kept_take"] is True and cb["broke_rule"] is False

    # 持仓已归档
    assert client.get("/api/v1/positions", headers=AUTH).json()["holdings"] == []

    # 重复清同一 id → 404 not_holding
    rc2 = client.post(f"/api/v1/positions/{pid}/close", json={"sell_price": 116.0}, headers=AUTH)
    assert rc2.status_code == 404
    assert rc2.json()["detail"]["reason"] == "not_holding"


def test_close_nonexistent_404(client):
    r = client.post("/api/v1/positions/999/close", json={"sell_price": 10.0}, headers=AUTH)
    assert r.status_code == 404
    assert r.json()["detail"]["reason"] == "not_holding"


# —— A.4 ack 端点 ——
def test_ack_endpoint(client):
    r = client.post("/api/v1/alerts/600000/ack", json={"action": "marked_close"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_ack_invalid_action_422(client):
    r = client.post("/api/v1/alerts/600000/ack", json={"action": "nope"}, headers=AUTH)
    assert r.status_code == 422
