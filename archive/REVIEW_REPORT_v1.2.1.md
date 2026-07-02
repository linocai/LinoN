# REVIEW_REPORT_v1.2.1 — 深析对话化 + 追问接 DeepSeek(Phase A–C)

> reviewer(Fable 5,异源外部审计)· 2026-07-02
> 审查对象:commit `c872f1c`(基线 `b326fb6`,即 v1.2.1 立项后单提交);权威契约 PROJECT_PLAN.md §4(v1.2.1)。
> Phase D(两步部署)未做,不在本次审查范围;上生产判断针对代码本身。

---

## 一、整体评估

- **实现完成度:~97%(Phase A/B/C 范围内)**。plan §4 的 6 项核心架构决定、§4.1 端点契约、A1–A5 / B1–B4 / C1–C5 全部落地;plan-critic 一轮堵的 3 致命(对话专属超时 / degraded 落库门槛 / mode 业务判 + role 收敛)**经逐行核实 + 亲跑门禁 + 真 key 活体冒烟,确认全部真堵住**。扣分项是两处 🟡(coach 上下文措辞注入假事实、事实缓存部分失败也缓存)——均为一行级小修,不破数据、不崩链路。
- **整体代码质量:高**。后端纯增量(`/analyze`/`/coach`/`GET /candidates`/回测端点逐字节零改动,diff 验证仅 import 一行变更 + 新增段落),分层清晰(prompt/deepseek/analyze/app 各司其职),降级链完整,可注入替身贯彻到位;客户端状态机(`firstVerdict`/`firstAssistantMsgId` 只在 isFirst 写、`backFromAnalysis` 清空)按 plan 钉死,买入路径收敛为单一路径。
- **主要亮点**:
  - 落库门槛 `is_first && mode=="candidate" && not result["degraded"]`(app.py:502-503)三条件齐备,`degraded` 标记链路端到端闭合:`degraded_chat()` 恒 True → `clamp_chat()` 成功恒 False → `chat_stock` `bool(result.get("degraded", False))` 透传 → 端点判定。降级"观望"**不可能** upsert 覆盖真 verdict。
  - 守味隔离干净:端点 `history_digest, _ = _coach_brain(bare)` 显式丢弃 review_ref(app.py:492);`chat_stock` 签名根本不收 review_ref;`build_chat_context_block` 不读该字段且有单测锁定。三层防线。
  - 对话专属超时真独立:`_CHAT_READ_TIMEOUT=25 / _CHAT_CONNECT_TIMEOUT=6 / _CHAT_MAX_ATTEMPTS=2`(deepseek.py)只被 `chat()` 使用,`analyze()` 仍用 12s×3,常量断言进单测。
  - 事实缓存设计克制:链路层专属 `_chat_fact_cache`,不碰共享 `_fetch_form`/`_fetch_fund`,`/analyze`/`/coach` 行为零影响(亲验:追问轮 2.0s vs 首轮 3.1s,缓存命中真省了数据补全)。

---

## 二、问题清单

### 🔴 致命问题(必须修复)

**无。**

### 🟡 重要问题(应该修复;均为小改动,建议 Phase D 部署前顺手修)

1. **[backend/app/llm/prompt.py:207,209] coach 模式上下文硬编"中间地带",触损/触盈持仓追问时向 LLM 注入假事实。**
   `build_chat_context_block` 对 `mode=="coach"` 无条件写 `"当前处于 -5%~+15% 中间地带"` 和 `f"{pnl_pct:+.2f}%(在 -5%~+15% 中间地带)"`。但按 C3 设计,**持仓一律 coach 模式**——触损红橙卡 thread 里的 composer 追问(用户典型行为:"真的不能再等等吗?")也走这里,此时 pnl_pct 可能是 -7.2%,注入文本自相矛盾("−7.20%(在 -5%~+15% 中间地带)")。这违反决定4"事实由后端注入、不靠模型编"的初衷——注入的必须是**真事实**。系统 prompt 铁律 guardrail 大概率仍能兜住结论,但在纪律最关键的场景给模型喂矛盾框架是不该有的质量隐患。
   **修复建议**:按 pnl_pct 派生措辞——`-5<pnl<+15` 才写"中间地带",越界写中性事实(如"已触及止损线下方,按铁律应离场"/"已越止盈线");pnl_pct 为 None 时只说"用户已持有该票"。
   **注**:同款硬编在老路径 `build_user_prompt:84-86` 早已存在(阶段2 起 `/coach` 触损也走它),非 v1.2.1 引入;`/coach` 属本版本"不改的端点",建议把老路径的同款修复记入 §5 Backlog 一并收口,勿在本版本顺手改。

2. **[backend/app/llm/analyze.py:252-253] 事实缓存"部分失败也缓存",偏离 plan A3"失败不缓存(下轮重试)",且偏离未记录。**
   `if not form.get("_degraded") or not fund.get("_degraded")` 意为"form 或 fund 任一成功即缓存"。若首轮 moneyflow_dc 瞬时失败而 daily 成功,**降级的资金面(net_mf="—" + fund_asof 退回占位)会被钉一整天**:同 code 当日所有追问、以及**退出重开的新 thread(新 is_first=true、会再落 verdict)**都拿不到资金数据、也不再重试——回测里落的 verdict 基于缺失资金判出。plan 原文"失败不缓存(下轮重试)"意图正是让下一轮有机会补回。
   **修复建议**:改为 `if not form.get("_degraded") and not fund.get("_degraded")`(两者均成功才缓存);或分段缓存(form/fund 各自成功各自缓存)。舆情降级可豁免(plan 本就 best-effort)。若维持现状,至少把该偏离补进变更日志。

### 🔵 建议改进(可以考虑;不阻断)

1. **[client/LinoN/Views/AnalysisView.swift:264-283] composer 发送未在 `analysisLoading` 时禁用,可并发双发。** 首判在途(openAnalysis 的 runChat 未返回)时用户即可再发一问:两个请求的 messages 都无 assistant → 后端**双双 is_first=true**,非降级时同一 code 落库两次(upsert 幂等但后写覆盖,两次 verdict 可能不同)、`firstAssistantMsgId` 挂到后返回的那条气泡。单用户低频、危害小,但 `Button`/`onSubmit` 加 `.disabled(model.analysisLoading)` 一行即可根除。
2. **[client/LinoN/App/AppModel.swift:442-459] `chatTurns` 截断的"必须保留最近一条 assistant"只靠现实交替性保证,且 while 修剪分支无测试覆盖。** 极端序列(窗口内 assistant 打头连续堆积)下 while-loop 可把 assistant 修剪殆尽甚至清空数组(空 messages 撞后端 `min_length=1` 422);现实对话交替不会发生,但两条截断单测构造的 20 条序列 `suffix(16)` 恰好都已是 user 边界,**while 循环从未被执行到**。建议补一条奇数错位样例(如 19 条,`suffix(16)` 以 assistant 打头)锁住修剪分支。
3. **[backend/tests/test_chat_api.py:236-255] `test_chat_stock_degraded_data_safe` / `test_chat_stock_deepseek_exception_safe` 未清 `_chat_fact_cache`,实跑时命中 `test_chat_stock_full_chain`(同 code 同日)留下的缓存,`_fail_fn` 根本没被调到**——断言碰巧仍成立(chat_fn 直接返降级),但"降级取数路径"并未被真正测过。两测开头各加 `analyze._chat_fact_cache.clear()`。
4. **[backend/tests/test_chat_api.py:427-449] `test_chat_missing_key_degrades_via_real_chat_stock` 不注入 `daily_fn/moneyflow_fn/sentiment_fn`,本机 `.env` 有真 TUSHARE_TOKEN 时单测真联网(Tushare×3 + 东财舆情)**,违反"单测不联网"纪律;离线仍绿(降级兜底)但时延不定。建议注入 `_fail_fn` 替身,或 monkeypatch 掉 TUSHARE_TOKEN。
5. **[backend/app/llm/analyze.py:211] `_chat_fact_cache` 跨日旧键只"自然失效"不清除**,长驻进程无限累积(量级极小,数月才 MB 级,ECS 1.6G 无实际威胁)。写入时顺手清掉非当日键即可。
6. **[client/LinoN/Networking/APIClient.swift:373] `analyzeCandidate`/`AnalyzeResult` 自 v1.2.1 起客户端无调用点(死代码)。** 后端 `/analyze` 保留是 plan 拍死的(回测链路),但客户端方法已孤儿;留给 Phase 5 cleaner 清或注释标注。同文件 `ChatResult.degraded` 解码后 AppModel 未使用——可留作未来降级 UI 提示(如气泡角标"降级答复"),或删字段。
7. **[backend/app/api/app.py:448] `/chat` 不设 messages 条数/单条长度上限,完全信任客户端截断(决定3 如此设计)。** 单用户 + token 鉴权下可接受;若想加防御,`ChatRequest.messages` 加 `max_length=32`、content 加 `max_length` 即可,防误用打爆 DeepSeek token 费。

---

## 三、完整性核对表(plan §4 逐项)

### 用户重点盯查项(9 项)

| # | 盯查项 | 结论 |
|---|---|---|
| 1 | 回测 verdict 落库不被污染 | ✅ 门槛三条件齐备(app.py:502);degraded 链路闭合(degraded_chat→clamp_chat→chat_stock→端点);降级"观望"不落已有单测 + 亲验;`_maybe_persist_verdict` 两调用点口径一致(同 `candidate_entry_date_of` + 覆盖式 upsert,幂等)。/analyze 无门槛为 plan 明示的 Backlog 遗留,非本版本问题 |
| 2 | 守味隔离 | ✅ 端点丢弃 review_ref;chat_stock 不收该参;build_chat_context_block 只拼 history_digest,单测锁定 |
| 3 | 对话超时不掐死 prose | ✅ 专属 25s×2 常量仅 `chat()` 用;`analyze()` 仍 12s×3;max_tokens=700 与 ~250 字 reply 自洽(超长截断→_loads_lenient 失败→降级,plan 认可);理论最坏 66s>客户端 60s 的极端由 plan 决定7 明示接受 |
| 4 | role 序列化 + mode 判定 | ✅ `chatTurns` 四值全覆盖(coach→assistant/analysis→跳过),单测断言收敛两值;截断 suffix(16)+user 边界修剪;mode 按 `holding(byCode:)` 业务判,持仓带 positionId(AppModel:433-435);后端 Literal 422 亲验 |
| 5 | 买入按钮判定 | ✅ 四条件 `firstAssistantMsgId + firstVerdict==.enter + 非持仓 + 是候选`(AnalysisView:159-161);两字段仅 isFirst 写(AppModel:371-374)、backFromAnalysis 清(509-510),均有单测 |
| 6 | 死代码 + 编译 | ✅ `analysisBlock` 已删;`case .analysis: EmptyView()` 留防 exhaustive-switch(ChatRole 契约保留 .analysis 的必然解,已注释"死代码");DeepAnalysisCard 本体在(快照测试引用);买入路径唯一(旧卡内按钮随 analysisBlock 一并删除) |
| 7 | 绿涨红跌 | ✅ v1.2.1 未新增字符串判负;openAnalysis `!c.chg.contains("-")`(候选 ASCII '-',合法)与 openCoach `pnl >= 0` 派生 bool 均为既有正确写法;对话气泡无染色逻辑 |
| 8 | 降级链不崩 | ✅ 缺 key/超时/非 200/非法 JSON/编排异常 → 200 + 降级 reply + 观望 + degraded=true,fund_asof 仍如实返;单测 6 条 + 缺 key 真链路测过 |
| 9 | 不改的端点零改动 | ✅ `git show c872f1c` 逐文件核验:app.py 纯增量(import 一行 + 新端点段);llm 三文件纯增量(deepseek.py 仅 import 行变更);/analyze、/coach、GET /candidates、/candidates/outcomes 无一字节改动 |

### Phase 验收标准

| Phase | 结论 |
|---|---|
| A1 prompt | ✅ CHAT_SYSTEM_PROMPT(三维度+铁律+护栏+verdict 只判当笔+json 字样满足 json mode)+ build_chat_context_block(无 review_ref)。⚠️ 见 🟡1(coach 措辞) |
| A2 deepseek.chat | ✅ payload=2×system+历史透传、json_object、temp 0.3、max_tokens 700、专属超时、全新连接重试骨架、degraded_chat/clamp_chat、transport 可注入 |
| A3 chat_stock | ✅ 每轮注入事实、(code,当日) TTL 缓存、不碰共享 _fetch_*、*_fn 全可注入、双层异常兜底。⚠️ 见 🟡2(部分失败缓存) |
| A4 端点+schema | ✅ ChatRequest(Literal 两值 role/min_length=1)、coach 404 not_holding、以 pos.code 为准、_chat_fn 可注入、响应 7 字段逐一对齐 §4.1 |
| A5 单测 | ✅ 28 条全绿,plan 列举 ①–⑦ 全覆盖 + 缓存/夹紧补充。⚠️ 见 🔵3/🔵4(两处测试卫生) |
| 验收 A | ✅ 含 reviewer 独立真 key 冒烟(见下节) |
| B1–B3 | ✅ 双端整行 Button 已去、.contentShape 双双删除;iOS 去 chevron 加紧凑深析真按钮(右列竖排,不挤中列);macOS 假按钮变真;深析按钮为唯一入口 |
| B4/验收 B | ✅ 双端 BUILD SUCCEEDED(reviewer 亲跑);行内无其他手势,代码层"点空白不进"成立;快照测试 6 条含候选行渲染通过 |
| C1 APIClient.chat | ✅ ChatTurn/ChatRequestBody/ChatResult,timeout 60s,position_id 为 nil 时 JSONEncoder 省略(pydantic 默认 None 兼容)。ChatResult 多带 degraded(plan 未列,无害超集,见 🔵6) |
| C2 runChat | ✅ openAnalysis 走 /chat,assistant 气泡替代 .analysis 卡,fundAsof 刷新,firstVerdict/Id 仅 isFirst 写 |
| C3 sendComposer | ✅ async 化 + 两调用点改 Task;写死文案已删;失败追加降级 assistant 气泡(plan 认可的 is_first 恒 false 副作用已记录);mode 业务判 |
| C4 | ✅ 买入按钮组搬对话气泡下、fundAsofBanner 常驻顶部、.analysis 死代码诚实处理、coach 触损/中间地带仍走 /coach 未动(openCoach/runCoach 零改动) |
| C5/验收 C | ✅ 无新增 .swift(xcodegen 免重生成立);XCTest 49 全绿含新增 5 条 |
| Phase D | ⛔ 未做(与用户任务书一致);部署时注意 plan D1 的 stale store.py/pyc 检查两项 |

### 偏离记录核对

- `.analysis` case 以 `EmptyView()` 保留分派(而非删 case):ChatRole 契约保留 `.analysis` 下 exhaustive switch 的必然解,§3 状态与代码注释均已说明 → 合理,不算未记录偏离。
- 🟡2 缓存条件与 plan 文字不符 → **未记录的偏离**,需修或补记。
- v1.2.1 施工完工的 §6 变更日志条目未补(仅立项条目)→ 收口(cleaner)时补,流程正常,提醒勿漏。

---

## 四、门禁复跑结果(reviewer 亲跑,非采信自述)

| 门禁 | 结果 |
|---|---|
| 后端 `python -m pytest` | ✅ **337 全绿**(0 失败;test_chat_api.py 单独 28/28) |
| 客户端 macOS build | ✅ BUILD SUCCEEDED |
| 客户端 iOS Simulator build(LinoJ-iPhone16Pro) | ✅ BUILD SUCCEEDED |
| 客户端 XCTest(iOS Simulator) | ✅ **49 全绿**(0 失败,含 SnapshotRenderTests 6 条) |
| git 状态 | ✅ 工作区干净,c872f1c 已提交 |

**真 key 活体冒烟(reviewer 独立执行,TestClient + 临时 DB,不碰真库)**:

- 首轮 candidate 对话:HTTP 200 / 3.1s,is_first=true、degraded=false、verdict=不进、fund_asof=**2026-07-02**(盘后=今日,资金时序修正生效),reply 155 字自由中文、诚实交代东财 EOD 口径;**verdict"不进"如实落 `analysis_verdicts`**(落库门槛按 plan 不筛 verdict 值,✓)。
- 追问轮(带 assistant 历史):HTTP 200 / 2.0s(**事实缓存命中,快于首轮**),is_first=false、上下文相关回答且主动引用铁律。
- coach 非持仓:404 `not_holding` ✓;非法 role="coach":422 ✓。
- 小观察:模型 reply 在正文写了具体日期("截至2026-07-02"),与 prompt"不要在正文重复日期"轻微不符——LLM 行为非代码缺陷,无害,不入问题清单。

---

## 五、结论

**🔴 0 / 🟡 2 / 🔵 7。可上生产(Phase D 可以走),不阻断。**

两处 🟡 都是一行级小修(prompt 措辞按 pnl 派生 + 缓存条件 or→and),建议在 Phase D 部署前顺手修掉再上——尤其 🟡1 触及"反情绪教练"这一产品核心场景的 prompt 事实正确性;若选择先上后修,风险边界清楚:不崩、不破数据、不污染回测,只影响触损追问的措辞质量与降级资金的当日黏性。
