"""复盘闭环层(阶段3 Phase G)。

子模块:
  · score  —— 纪律打分聚合(纯确定性、零 LLM):ISO 周原语(iso_week/week_bounds/prev_week)
              + aggregate_week(读某周 trades 聚合 discipline_rate/score/redFlags/每笔
              ReviewTrade/近6周 trend/openHoldings)+ 机械短评单一事实源 _mechanical_comment。
  · brain  —— 教练大脑注入(两条独立产物,严格分流):build_review_ref(带情绪第二人称,
              仅回客户端展示,绝不进 LLM prompt)+ build_history_digest(中性统计摘要,进 prompt)。

铁律:打分只聚合 trades 表 store._compute_kept_flags 已落库的 kept_*/broke_rule,
     不重算守线判定、不动 store.py 常量;-5.0/+15.0/D4/容差带 仍只在 app.db.store 顶部。
     短评模板 _mechanical_comment 只在 score.py 定义一处,G1 aggregate 与 G3 close_position 共用。
"""
