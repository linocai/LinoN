"""FastAPI 应用(阶段1 A.1/A.2/A.4 ack)。

  · app.py    —— FastAPI 实例 + 路由(health/devices/positions/alerts)+ 后台轮询挂载。
  · deps.py   —— require_token 鉴权依赖(Bearer 比对 .env API_TOKEN,hmac.compare_digest)。
  · schemas.py—— 请求/响应模型(pydantic)。

绑 127.0.0.1:8001(nginx 反代)。health 免鉴权;其余端点过 require_token。
"""
