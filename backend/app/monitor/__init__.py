"""监控守护(阶段1 A.3 + A.4 升级 + A.5 EOD)。

子模块:
  · hardline   —— 纯函数:3 硬线判定 + T+1/涨跌停文案 + 多源一致性校验(可单测,不联网)。
  · escalation —— 硬线事件升级/ack 状态机(未确认按 ESCALATE_INTERVAL_MIN 重复推)。
  · eod        —— 盘后 EOD 摘要(每持仓盈亏%/D几/明日 D4 预警;无 Tushare token 降级)。
  · loop       —— app 内后台 asyncio 轮询任务(交易时段每分钟拉价 → 判硬线 → 交升级器 → 推送)。

规则常量单一事实源:复用 app.db.store 顶部的 -5.0/+15.0/D4/容差带常量,不另写一份。
"""
