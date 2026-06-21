"""阶段1 A.4:APNs JWT 构造(ES256)+ payload + send_push 注入 transport(不真连 Apple)。

用临时生成的 EC P-256 key 单测 JWT 签名;验证 header(alg/kid)、claims(iss/iat)、
可被对应公钥验签。send_push 注入假 transport,断言 URL/headers/payload 正确组装,
不依赖真 .p8、不真连 api.sandbox.push.apple.com。
"""

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.push import apns
from app.push.apns import (
    CATEGORY_EOD,
    CATEGORY_HARDLINE,
    PushResult,
    build_jwt,
    build_payload,
    send_push,
)


@pytest.fixture()
def ec_keypair():
    """生成临时 EC P-256 私钥/公钥 PEM(模拟 .p8,不用真凭证)。"""
    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


# —— JWT 构造 ——
def test_build_jwt_header_and_claims(ec_keypair):
    priv_pem, pub_pem = ec_keypair
    iat = int(time.time())
    token = build_jwt(key_pem=priv_pem, key_id="Q963AP3VY8", team_id="HX73DFL88G", iat=iat)

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["kid"] == "Q963AP3VY8"

    # 用公钥验签(证明 ES256 私钥确实签了)
    claims = jwt.decode(token, pub_pem, algorithms=["ES256"])
    assert claims["iss"] == "HX73DFL88G"
    assert claims["iat"] == iat


def test_build_jwt_verifiable_only_by_matching_key(ec_keypair):
    priv_pem, _ = ec_keypair
    other = ec.generate_private_key(ec.SECP256R1())
    other_pub = other.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    token = build_jwt(key_pem=priv_pem, key_id="K", team_id="T")
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, other_pub, algorithms=["ES256"])


# —— payload 组装 ——
def test_build_payload_hardline():
    p = build_payload("标题", "正文", category=CATEGORY_HARDLINE, badge=2,
                      thread_id="600000", custom={"code": "600000", "kind": "stop"})
    aps = p["aps"]
    assert aps["alert"] == {"title": "标题", "body": "正文"}
    assert aps["category"] == CATEGORY_HARDLINE
    assert aps["badge"] == 2
    assert aps["thread-id"] == "600000"
    assert p["code"] == "600000" and p["kind"] == "stop"


def test_build_payload_no_badge_no_thread():
    p = build_payload("t", "b", category=CATEGORY_EOD)
    assert "badge" not in p["aps"] and "thread-id" not in p["aps"]


# —— send_push 注入 transport(不真连)——
def test_send_push_uses_injected_transport(ec_keypair):
    priv_pem, _ = ec_keypair
    jwt_token = build_jwt(key_pem=priv_pem, key_id="Q963AP3VY8", team_id="HX73DFL88G")

    captured = {}

    def fake_transport(url, headers, body) -> PushResult:
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body.decode("utf-8"))
        return PushResult(ok=True, status=200, reason="ok", apns_id="fake-id")

    res = send_push(
        "device-abc", "硬线警报", "沪电股份 已触 −5% 止损线",
        category=CATEGORY_HARDLINE, thread_id="002463", badge_escalation=2,
        custom={"code": "002463", "kind": "stop"},
        transport=fake_transport, jwt_token=jwt_token,
    )
    assert res.ok and res.status == 200 and res.apns_id == "fake-id"
    # URL 落在 /3/device/<token>
    assert captured["url"].endswith("/3/device/device-abc")
    # sandbox 网关(默认 APNS_USE_SANDBOX=true)
    assert "sandbox" in captured["url"]
    # 鉴权头携带 bearer JWT
    assert captured["headers"]["authorization"] == f"bearer {jwt_token}"
    # payload 正确
    assert captured["body"]["aps"]["badge"] == 2
    assert captured["body"]["aps"]["thread-id"] == "002463"
    assert captured["body"]["code"] == "002463"


def test_send_push_no_jwt_returns_fail(monkeypatch):
    """JWT 取不到(凭证缺失)→ ok=False,不抛崩,不调用 transport。"""
    called = {"n": 0}

    def fake_transport(url, headers, body):
        called["n"] += 1
        return PushResult(ok=True, status=200, reason="ok")

    # jwt_token=None 且 get_jwt 返回 None(强制)
    monkeypatch.setattr(apns, "get_jwt", lambda now=None: None)
    res = send_push("dev", "t", "b", transport=fake_transport)
    assert res.ok is False and called["n"] == 0
    assert "JWT" in res.reason or "凭证" in res.reason


def test_send_push_badge_zero_omits_badge(ec_keypair):
    priv_pem, _ = ec_keypair
    jwt_token = build_jwt(key_pem=priv_pem, key_id="K", team_id="T")
    captured = {}

    def fake_transport(url, headers, body):
        captured["body"] = json.loads(body.decode("utf-8"))
        return PushResult(ok=True, status=200, reason="ok")

    send_push("dev", "t", "b", badge_escalation=0,
              transport=fake_transport, jwt_token=jwt_token)
    assert "badge" not in captured["body"]["aps"]
