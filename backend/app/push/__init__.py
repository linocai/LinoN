"""APNs 直连推送(阶段1 A.4)。

子模块:
  · apns —— token-based JWT(ES256)构造 + payload 组装 + send_push(可注入/可 mock)。

凭证:KeyID Q963AP3VY8 / TeamID HX73DFL88G / BundleID top.linotsai.linon;
dev 网关 api.sandbox.push.apple.com(.env APNS_USE_SANDBOX)。.p8 私钥不入 git。
"""
