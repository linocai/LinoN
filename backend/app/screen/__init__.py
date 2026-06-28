"""选股数据层(阶段2 Phase D1)。

子模块:
  · rules    —— 钉死的选股规则单一事实源(黑名单 / 高位线 / 截断 / 排序权重)。
                技术面交 LLM 判,这里只硬编真二元项 + 宽筛"宁松勿紧"经验默认值。
  · fetch    —— 全市场 EOD 拉取(daily_basic/moneyflow_dc/daily 按 trade_date 单次批量
                + stock_basic 行业映射缓存),pandas 归一,内存算放量/新高/60日涨幅。
  · pipeline —— 粗筛 → 排序 → 截断,产对齐 Candidate 形状的 dict 列表。

规则常量 -5.0/+15.0/D4/容差带 仍只在 app.db.store 顶部,本包 import 复用,禁止再写一份。
"""
