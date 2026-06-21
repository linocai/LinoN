"""APNs token-based 推送(ES256 JWT)—— 阶段1 A.4。

token-based JWT(plan):.p8 私钥 + KeyID(kid)+ TeamID(iss);header alg=ES256;
payload {iss, iat};Authorization: bearer <jwt>;apns-topic = BundleID。
JWT 缓存 ≤ 1h(Apple 要求 token 寿命 20–60min,过期重签;这里 ~50min 刷新)。

dev 网关:api.sandbox.push.apple.com(APNS_USE_SANDBOX=true);prod:api.push.apple.com。

可注入/可 mock:
  · send_push(...) 通过 transport 回调真发 HTTP/2(默认 _http2_post);测试注入假 transport,
    不依赖真 .p8、不真连 Apple。
  · JWT 签名单测用临时生成的 EC key(P-256),验证 header/claims 与 ES256 可被公钥验签。

锁屏动作按钮:由 category 决定(客户端注册 UNNotificationCategory:
  "HARDLINE" → 「标记次日清仓」「问教练」;"EOD" → 普通)。thread-id 按 code 聚合。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import jwt  # PyJWT

from app.config import settings

logger = logging.getLogger(__name__)

# APNs 网关
GATEWAY_SANDBOX = "https://api.sandbox.push.apple.com"
GATEWAY_PROD = "https://api.push.apple.com"

# 锁屏动作分类(与客户端 UNNotificationCategory 标识对齐)
CATEGORY_HARDLINE = "HARDLINE"   # 硬线警报:含「标记次日清仓」「问教练」动作
CATEGORY_EOD = "EOD"             # 盘后摘要:普通

# JWT 刷新窗口:Apple 接受 20–60min,留余量 ~50min 重签。
_JWT_TTL_SEC = 50 * 60

# 推送结果
@dataclass
class PushResult:
    ok: bool
    status: int            # HTTP 状态码(成功 200);本地未发=0
    reason: str            # apns 错误 reason 或本地原因
    apns_id: str = ""


# —— JWT 缓存 ————————————————————————————————————————————————————

_jwt_cache: Dict[str, Any] = {"token": None, "iat": 0, "kid": None}


def _read_key(key_path: str) -> str:
    with open(key_path, "r", encoding="utf-8") as f:
        return f.read()


def build_jwt(
    *,
    key_pem: str,
    key_id: str,
    team_id: str,
    iat: Optional[int] = None,
) -> str:
    """构造 APNs token-based JWT(ES256)。

    header: {alg: ES256, kid: <KeyID>};claims: {iss: <TeamID>, iat: <now>}。
    key_pem 为 PKCS#8 EC 私钥 PEM(.p8 内容);单测可传临时 EC key 的 PEM。
    """
    now = int(iat if iat is not None else time.time())
    return jwt.encode(
        {"iss": team_id, "iat": now},
        key_pem,
        algorithm="ES256",
        headers={"kid": key_id, "alg": "ES256"},
    )


def get_jwt(now: Optional[int] = None) -> Optional[str]:
    """取缓存 JWT(≤ ~50min 复用,过期重签)。APNs 配置不全 → None。"""
    if not settings.has_apns_config:
        logger.warning("APNs 配置不全(KeyID/TeamID/BundleID/.p8 路径),跳过 JWT 构造")
        return None
    now = int(now if now is not None else time.time())
    cached = _jwt_cache.get("token")
    if (
        cached
        and _jwt_cache.get("kid") == settings.APNS_KEY_ID
        and now - int(_jwt_cache.get("iat", 0)) < _JWT_TTL_SEC
    ):
        return cached
    try:
        key_pem = _read_key(settings.APNS_KEY_PATH)  # type: ignore[arg-type]
    except OSError as e:
        logger.error("读取 .p8 失败(%s): %s", settings.APNS_KEY_PATH, e)
        return None
    token = build_jwt(
        key_pem=key_pem,
        key_id=settings.APNS_KEY_ID,    # type: ignore[arg-type]
        team_id=settings.APNS_TEAM_ID,  # type: ignore[arg-type]
        iat=now,
    )
    _jwt_cache.update({"token": token, "iat": now, "kid": settings.APNS_KEY_ID})
    return token


def reset_jwt_cache() -> None:
    """清 JWT 缓存(测试/凭证热切换用)。"""
    _jwt_cache.update({"token": None, "iat": 0, "kid": None})


# —— payload 组装 ————————————————————————————————————————————————

def build_payload(
    title: str,
    body: str,
    *,
    category: str,
    badge: Optional[int] = None,
    thread_id: Optional[str] = None,
    custom: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """组装 APNs payload(aps + 自定义字段)。

    category 决定锁屏动作按钮;thread_id 按持仓 code 聚合;badge 显示升级次数。
    custom 透传业务字段(如 code/kind/escalation,供客户端动作回报 ack)。
    """
    aps: Dict[str, Any] = {
        "alert": {"title": title, "body": body},
        "sound": "default",
        "category": category,
    }
    if badge is not None:
        aps["badge"] = badge
    if thread_id:
        aps["thread-id"] = thread_id
    payload: Dict[str, Any] = {"aps": aps}
    if custom:
        payload.update(custom)
    return payload


# —— 真发 transport(HTTP/2)—— 可注入/可 mock ——————————————————————

# Transport 签名:(url, headers, body_bytes) -> (status_code, reason, apns_id)
Transport = Callable[[str, Dict[str, str], bytes], "PushResult"]


def _http2_post(url: str, headers: Dict[str, str], body: bytes) -> PushResult:
    """默认真发:httpx HTTP/2 POST 到 APNs。仅在真连时被调(测试注入假 transport)。"""
    try:
        import httpx
    except ImportError:
        return PushResult(ok=False, status=0, reason="httpx 未安装")
    try:
        with httpx.Client(http2=True, timeout=10.0) as client:
            resp = client.post(url, headers=headers, content=body)
        apns_id = resp.headers.get("apns-id", "")
        if resp.status_code == 200:
            return PushResult(ok=True, status=200, reason="ok", apns_id=apns_id)
        reason = ""
        try:
            reason = resp.json().get("reason", "")
        except Exception:
            reason = resp.text[:200]
        return PushResult(ok=False, status=resp.status_code, reason=reason, apns_id=apns_id)
    except Exception as e:  # 网络/TLS/HTTP2 协商失败
        return PushResult(ok=False, status=0, reason=f"传输异常: {e}")


def _gateway() -> str:
    return GATEWAY_SANDBOX if settings.APNS_USE_SANDBOX else GATEWAY_PROD


def send_push(
    device_token: str,
    title: str,
    body: str,
    *,
    category: str = CATEGORY_HARDLINE,
    thread_id: Optional[str] = None,
    badge_escalation: int = 0,
    custom: Optional[Dict[str, Any]] = None,
    transport: Optional[Transport] = None,
    jwt_token: Optional[str] = None,
) -> PushResult:
    """发一条 APNs 推送到单个 device_token。

    · category 决定锁屏动作(HARDLINE/EOD);thread_id 按 code 聚合;
      badge_escalation = 第几次升级(>0 时作 badge 展示"第 N 次升级")。
    · transport 可注入(测试用假 transport,不真连 Apple);默认 _http2_post。
    · jwt_token 可注入(测试用临时 key 签的 token);默认走 get_jwt() 缓存。
    · 凭证不全 / JWT 取不到 → ok=False, reason 可读,【不抛崩】。
    """
    transport = transport or _http2_post
    token = jwt_token if jwt_token is not None else get_jwt()
    if token is None:
        return PushResult(ok=False, status=0, reason="APNs JWT 不可用(凭证缺失/读取失败)")

    badge = badge_escalation if badge_escalation > 0 else None
    payload = build_payload(
        title, body, category=category, badge=badge,
        thread_id=thread_id, custom=custom,
    )
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "authorization": f"bearer {token}",
        "apns-topic": settings.APNS_BUNDLE_ID or "",
        "apns-push-type": "alert",
        "apns-priority": "10",
        "content-type": "application/json",
    }
    url = f"{_gateway()}/3/device/{device_token}"
    return transport(url, headers, body_bytes)
