"""规则常量单一事实源(与客户端 Models.swift / plan §4b 对齐)。

止损/止盈/D4/容差带**只在这一处定义**;monitor(hardline/eod)、screen、review 等
一律 `from app.db.store import ...` 复用,**禁止再写一份**。经 store 包 `__init__` re-export,
`from app.db.store import STOP_TRIGGER_PCT` 与拆包前用法完全一致(单一事实源不变)。
"""

# —— 止损/止盈/容差常量 ——
STOP_RATIO = 0.95           # 止损线 = buy_price × 0.95(-5%)
TAKE_RATIO = 1.15           # 止盈线 = buy_price × 1.15(+15%)
# 触发线口径定死 -5.0(plan §4b);展示侧 -4.9 仅显示阈,触发判定引用 -5.0。
STOP_TRIGGER_PCT = -5.0
TAKE_TRIGGER_PCT = 15.0
# 止损容差带(约束5):在 -6%~-4% 离场都算"守了止损",不因正常滑点误标破纪律。
STOP_KEPT_LOW = -6.0
STOP_KEPT_HIGH = -4.0
FORCE_CLOSE_TRADE_DAY = 4   # D4 强平

MAX_HOLDINGS = 3            # 同时最多 3 票
