# LinoN 阶段2(选股 + 决策)审查报告

> reviewer:外部审计员视角从零审查,对照 `PROJECT_PLAN.md` §4(D1–E2)+ §4b 客户端契约 + `Models.swift`。
> 审查日期 2026-06-23。门禁均亲自跑通(非信 builder 自述);真 key 做了 analyze/coach 端点活体冒烟。

## 整体评估

- **实现完成度:约 97%**。D1–D5 后端 + E1/E2 前端全部落地,验收标准逐项命中,无遗漏的 Phase、无 plan 之外的多余功能(扫描全部改动文件:范围严格收敛在 plan 列举的模块内)。剩余 3% 为下文几条次要/打磨项,均不影响收口。
- **整体代码质量:高**。分层清晰(screen/llm 纯函数 + 可注入),降级路径处处兜底且有单测覆盖,契约逐字段对齐,规则常量单一事实源纪律严守。注释把"为什么"写清(铁律/口径/降级语义),可维护性好。
- **主要亮点**:
  1. **铁律执行到位**:`rules.py` 把技术面交给 LLM,只硬编真二元项(黑名单/高位线/截断/排序权重);粗筛宽条件全部标注"宁松勿紧、可迭代、不卡生死",且逻辑上是粗筛门槛而非生死阈。没有把宽筛写成硬生死阈。
  2. **全链路降级不崩**:缺 Tushare→候选 degraded 空列表;缺 DeepSeek/超时/非 200/非法 JSON→降级占位卡(verdict=观望、三轴 neutral);舆情失败→news neutral 不阻塞。每条降级分支都有对应单测,且**活体冒烟验证**(真 DeepSeek 返回被夹紧成合法 DeepAnalysis)。
  3. **契约逐字段对齐**:`Candidate`(camelCase)/`DeepAnalysis`(三轴+verdict+plan,tone/verdict 枚举)后端返回 vs `Models.swift` 客户端解码完全一致;客户端 `DeepAnalysisDecodeTests` 用真后端形状 JSON 解码验证(可进/观望/不进 + 四 tone 全覆盖)。
  4. **审后修复 #2 的契约保全**:D5 buy_date 改取下一交易日 + monitor 层 `_ensure_time_escalation` 重建,均未动 `should_force_close` 的 `count==4` 契约,而是在 monitor 层补偿。

### 门禁亲验结果(全部真实跑通)

| 门禁 | 结果 |
|---|---|
| 后端 `python -m pytest` | **183 passed**, 1 warning(urllib3 LibreSSL 无害)。分布:test_screen 34 / test_llm 20 / test_candidates_api 16 / test_monitor_loop 16 / test_api 23 / test_db 10 + 阶段1 基线。 |
| iOS build(LinoJ-iPhone16Pro) | **BUILD SUCCEEDED** |
| macOS build | **BUILD SUCCEEDED** |
| client `xcodebuild test` | **32 passed**, 0 failures(TEST SUCCEEDED) |
| 活体冒烟(真 Tushare+DeepSeek key) | health 200 / candidates 无缓存→degraded:true reason=no_cache HTTP200 / **analyze 603986 真 DeepSeek→合法 DeepAnalysis(verdict=可进、tones∈枚举、axis keys 正确、fund.text 标注 EOD 时序)、fund_asof=2026-06-22** / coach 非持仓→404 / 缺 auth→401。uvicorn 日志无 traceback、无 key 泄漏。 |

新增测试**有意义**(真断言行为:黑名单参数化 13 例、夹紧越界枚举、截断随 free_slots、D5 三态周末/节假日/交易日 frozen-date、coach advice 映射),非占位/恒真。SnapshotRenderTests 是离屏可视核对(>1KB 防空白回归),已如实标注非像素断言。

---

## 🔴 致命问题(必须修复)

**无。** 无契约漂移、无解码失败风险、无鉴权缺口、无崩溃路径、无密钥泄漏。

---

## 🟡 重要问题(应该修复)

**无达到"重要"级别的问题。** 逐项核查结论:

- **规则常量单一事实源**:✅ grep 全仓确认 `-5.0/+15.0/0.95/1.15/-6.0/-4.0/D4` **仅在 `store.py` 顶部**定义;`screen`/`llm`/监控仅在注释/LLM 文案中提及,无第二处定义。`hardline.py` 从 `store` import 复用。`rules.py` 的高位线 100/50 与 prompt 的 -5%/+15% 文案是选股/LLM 专属,非离场规则常量,不冲突。
- **粗筛非生死阈**:✅ `passes_coarse` 的放量 1.5/净流入/新高/均线均为可调经验值,注释标注;高位 ≥100% 排除是 plan §4.1 明列的合法二元硬规则,非被偷偷写成宽筛硬阈。
- **Tushare 单位口径**:✅ `total_mv`(万元)÷1e4→亿、`net_mf_amount`(万元)用于 `DAY_OUTFLOW_FLOOR=-5000`(万元)、`_fmt_flow` 万元÷1e4→亿,内部一致;`daily.amount`(千元)仅文档提及、实际未使用(只用 close/vol/pre_close),无换算 bug 空间。放量倍数自算(不用 Tushare volume_ratio,与注释一致)。白酒黑名单 industry 集合覆盖白酒/酿酒/黄酒/啤酒/葡萄酒/其他酒,茅台冒烟命中。
- **满仓闭门双保险**:✅ 服务端 `GET /candidates` `limit=5×free_slots`、满仓返空;客户端 `shownCandidates` 再夹一层。截断公式 3→15/2→5/0→0 单测验证。清仓后 `refresh()` 末尾 `loadCandidates()` 重开。
- **buy_date 修复**:✅ `_current_trade_date` 周末/节假日取 `next_trading_day`;test_api 三态 frozen-date 覆盖(06-23→06-23 / 06-27 周六→06-29 / 10-01 国庆→10-08)。`should_force_close` 的 `count==4` 未动。
- **路由顺序**:✅ `/candidates/refresh`(单段)与 `/candidates/{code}/analyze`(两段)无匹配冲突;无 `/candidates/{code}` 裸路由会 shadow refresh。4 新端点全部 `Depends(require_token)`,活体 401 验证。
- **EOD tick 防重**:✅ `last_candidate_date` 防每交易日重算;pipeline 异常被 `run_candidate_refresh` 内 try 吞、`monitor_loop` 外层再吞双保险;15:35 窗口独立于 15:05 EOD 推送。重启重算靠 upsert 整体替换同日,不致数据损坏(仅冗余 Tushare 拉取,见下 🔵)。

---

## 🔵 建议改进(可以考虑)

1. **[`app/monitor/loop.py:327` + `app/api/app.py:280`]** 候选刷新基准日(`_candidate_basis_date`/`run_candidate_refresh` 内 basis 计算)对"交易日"仅判 `is_trading_day(today)`、**不判是否已过 15:35**。手动 `POST /candidates/refresh` 若在交易日盘中(如 10:00)调用,basis=今天,而 Tushare 今日 EOD 未出 → fetch 失败 → degraded(不崩,符合契约)。行为正确但非最优;可在 refresh 编排里对"交易日但未过收盘窗口"回退到上一交易日,让盘中手动 refresh 也能拿到昨日候选。**非 bug,体验优化**。

2. **[`app/monitor/loop.py:327`]** `last_candidate_date` 同阶段1 EOD `last_eod_date` 一样是内存态,重启/错过窗口可能重算或漏算当日候选(upsert 幂等故无数据损坏,仅冗余一次全市场拉取)。与 plan §5 已登记的 EOD 推送防重打磨项同源,可一并落库防重启漏/重算,**推后到打磨阶段**。

3. **[`app/screen/fetch.py:110,218`]** `StockRow.total_mv_yi`(总市值亿元)已算但 pipeline 粗筛/排序均未使用(死字段)。若无意纳入市值过滤,可删以减噪;若计划后续用市值剔小盘,保留无妨(标注 TODO 更清晰)。

4. **[`app/llm/analyze.py:85`]** 深判单票 `_fetch_form` 的 `turnover` 恒为 `"—"`(注释说单票换手需 daily_basic,深判以 daily 为主故略)。LLM prompt 里换手位显示 `—`,不影响判定但信息略缺;若想补,可加单票 `ts_daily_basic(code, fund_asof)` 取 turnover_rate。**plan 未要求,可选**。

5. **[`client/LinoN/App/AppModel.swift:343,360`]** `openCoach`/`runCoach` 的 `coachPosition(id:)` 调用未透传用户 `question`(用的是自动 opener,question 参数恒 nil)。当前交互是"问教练"按钮触发固定 opener,符合阶段2 范围(真问答接 LLM 留阶段3);但 `coachPosition(id:question:)` 已支持 question 形参却未接通,属预留未用。阶段3 接 composer↔coach 真问答时补。

6. **[`client/LinoN/App/AppModel.swift:310`]** 候选 `chgIsUp = !c.chg.contains("-")`,当 chg 为 `0.00%` 或 `+0.00%` 时判为 up(绿)。零涨幅染绿是极小视觉边角(中性本应灰),不影响功能。**可忽略**。

---

## 收口判断

**阶段2 达到可收口标准。** 实现与 plan §4 高度一致(完成度 ~97%),零致命、零重要问题;三档门禁(后端 183 / 双端 build / client 32)亲验全绿,且真 key 活体冒烟验证了 DeepSeek 深判全链路与降级契约。上列 6 条建议均为体验优化/打磨/阶段3 预留,无一阻断收口。建议:按文件规范归档 §4 全文入 `archive/stage2_候选决策_plan.md`,主文件 §4 清回占位;🔵#1/#2(候选基准日盘中回退 + 防重落库)与阶段1 遗留的 EOD 防重打磨项合并,留打磨/运维阶段统一处理;🔵#5(coach question 透传)随阶段3 教练大脑施工。
