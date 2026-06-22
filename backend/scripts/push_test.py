"""track C.3 本地真机推送自测:从 Mac 直发一条 sandbox APNs 到真机 device token。

用法:
  cd backend && source .venv/bin/activate
  python scripts/push_test.py <device_token_hex>

读 backend/.env 的 APNS_*(.p8 路径 / KeyID / TeamID / BundleID / APNS_USE_SANDBOX=true),
经 app.push.apns.send_push 真发到 api.sandbox.push.apple.com。
验证三件:① 推得到(status 200);② 锁屏硬线卡;③ 动作按钮(category=HARDLINE,
对齐客户端 PushManager 注册的 category 与 didReceive 读的 custom["code"])。

device_token 从真机抓:Xcode 里 Run 到 iPhone → 授权通知 → 控制台打印
"🔑 [LinoN] APNs device token (sandbox): <hex>"(见 PushManager DEBUG 分支)。
"""

from __future__ import annotations

import sys

from app.config import settings
from app.push import apns


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/push_test.py <device_token_hex>")
        return 2
    token = sys.argv[1].strip().replace(" ", "")

    gw = "sandbox" if settings.APNS_USE_SANDBOX else "PROD(生产)"
    print(f"网关: {gw}  ·  topic(bundle): {settings.APNS_BUNDLE_ID}  ·  KeyID: {settings.APNS_KEY_ID}")
    if not settings.has_apns_config:
        print("✗ APNs 配置不全:检查 backend/.env 的 APNS_KEY_PATH(.p8 是否存在)/APNS_KEY_ID/APNS_TEAM_ID/APNS_BUNDLE_ID")
        return 1

    res = apns.send_push(
        token,
        title="沪电股份 已触 −5% 止损线",
        body="现价 47.50 · 浮亏 −5.1%。铁律:次日开盘无条件清仓。",
        category=apns.CATEGORY_HARDLINE,        # "HARDLINE" —— 决定锁屏动作按钮
        thread_id="002463",
        badge_escalation=1,                     # 角标"第 1 次升级"
        custom={"code": "002463", "kind": "stop", "escalation": 1},
    )
    print(f"结果: ok={res.ok}  status={res.status}  reason={res.reason!r}  apns_id={res.apns_id}")
    if not res.ok:
        print("  常见原因: BadDeviceToken(token 抄错/非 sandbox token) · "
              "TopicDisallowed(bundle 与 .p8 的 App 不符) · ExpiredProviderToken(JWT/时钟)")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
