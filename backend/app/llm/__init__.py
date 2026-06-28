"""DeepSeek 深判层(阶段2 Phase D3)。

子模块:
  · deepseek  —— httpx 调 DeepSeek /chat/completions(response_format=json_object)
                 + 超时/失败/非法 JSON 降级,可注入 transport 免单测联网。
  · prompt    —— system 前置词(v2 §6 形态/资金/消息方法论 + DeepAnalysis schema 样例
                 + 枚举约束 + "泡沫=暴涨/乖离+情绪过热,不看 PE")。
  · sentiment —— 东财股吧 best-effort 抓取标题 + 降级(失败 → news 轴 neutral 占位)。
  · analyze   —— 编排:补单票形态/资金/舆情 → 拼 prompt → 调 DeepSeek → 校验夹紧 → DeepAnalysis。

降级铁律:缺 DEEPSEEK_API_KEY / 超时 / 非法 JSON → 降级占位卡
(verdict=观望、三轴 tone=neutral、诚实文案),绝不抛崩。
"""
