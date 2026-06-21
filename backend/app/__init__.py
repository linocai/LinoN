"""LinoN backend application package.

阶段 0(基建)子模块:
  config    — pydantic-settings 读 .env(密钥/路径)
  data      — 实时价(新浪主/腾讯降级)+ Tushare 封装
  db        — SQLite 四表 + CRUD
  calendar  — 交易日历原语(静态兜底 + trade_cal 驱动)
  smoke     — 冒烟脚本依赖的内部 helper(脚本本体在 scripts/)
"""
