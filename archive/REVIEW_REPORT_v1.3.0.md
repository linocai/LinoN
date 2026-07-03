# REVIEW_REPORT v1.3.0(实战反馈四件套)· reviewer(Fable)外部审计

> 审查范围:`git diff eb2f7a5 HEAD`(9c1332e Phase B / aec499e 后端批 A+C / 47e9ace 前端批 C3+D+E,共 27 文件)。
> 权威件:PROJECT_PLAN.md §4(关键技术选型 + Phase A–E 验收标准)。红线:项目 CLAUDE.md。
> 高危区(Phase B 金额+migration)另有主会话 Opus 复审,本报告与其取并集。

## 整体评估

- **实现完成度:约 96%**。四件套的后端(B/A/C)与前端 C3/D1/E 全部按 plan 落地且验收达标;**Phase D2(相关性护栏 UI)代码齐全但因一处 URL 构造 bug 在真后端下端到端完全失效**(见致命 #1),是唯一断链点。
- **整体代码质量:高**。migration/金额/纯函数/降级链姿势与既有先例严格一致,单测密度大(后端 +69 条、客户端 +19 条),plan 里的 🟡/🔵 预埋点(nullable 契约、只读缓存、最长前缀、派生 bool 着色)逐条兑现,注释可追溯。
- **主要亮点**:① `test_correlation.py` 用"load_industry_map 调用即抛 + industry_of 调用标记"双向钉死开仓不联网红线,姿势教科书级;② `test_v130_costs_migration.py` 覆盖 B 验收①–⑥ 全项,含"迁移失败时 close 抛 OperationalError 且 position 不被归档(同事务回滚,无幽灵闭合)"的后果固化测试;③ C4 门禁是真重写(含"满仓仍 20"“不足 20 原样返"新边界),并加了 `not hasattr` 负向断言防死码回潮。

## 门禁复跑(reviewer 亲跑,2026-07-03)

| 门禁 | 结果 |
|---|---|
| 后端 `python -m pytest` | **378 passed**(基线 337 + Phase B 24 + Phase A 16 + Phase C 净增 1,数字对上) |
| 客户端 XCTest(iOS Simulator,LinoJ-iPhone16Pro) | **63 tests, 0 failures**(基线 49 + 新增 14,含删 1 条 ClosedEmptyCard 快照) |
| macOS `xcodebuild build` | **BUILD SUCCEEDED**(iOS build 经 test 隐含通过) |
| 补充活体验证 | 本地 uvicorn + curl:`/positions/correlation?code=600519` 200 且返合法 JSON;`%3F` 编码路径 404(致命 #1 的实证) |

(macOS `test` destination 的"Could not find test host" quirk 为预存在环境问题,非本版引入,未计入。)

---

## 🔴 致命问题(必须修复)

1. **[client/LinoN/Networking/APIClient.swift:349 + :499] `fetchCorrelation` 的 query 会被 `appendingPathComponent` 百分号编码,真后端恒 404 → Phase D2 护栏 UI 在生产永远静默失效。**
   - 机理:`get("/api/v1/positions/correlation?code=\(code)")` → `baseURL.appendingPathComponent(path)` 把 `?` 编码为 `%3F`,请求路径变成 `/api/v1/positions/correlation%3Fcode=600519`。已实证:Swift 脚本打印该 URL 为 `...correlation%3Fcode=600519`;对本地真 uvicorn 发该编码路径返 **404**,literal `?` 返 **200**。
   - 后果链:`send()` 把 404 映射 `.notHolding` → `checkCorrelation` 的 catch **按设计静默**置 `correlationConflict=nil` → 警示条永不显示、无任何报错。"失败静默"(D2 契约)恰好把 bug 藏死——开仓 sheet 与深析买入两条路径的护栏全部形同虚设,D 验收②③ 端到端不成立。
   - 为何双端门禁没抓到:客户端 `CorrelationGuardrailTests` 只测 guard/静默分支(无 client、不走真 URL);后端 `test_correlation.py` 用 TestClient(不经 URLSession)。URL 构造层两边都没有门禁。
   - **修法**:`get()` 改用 `URL(string: path, relativeTo: baseURL)`(或 URLComponents 显式组 query),并补一条 URL 构造单测(断言含 `?` 的 path 生成的 absoluteString 不含 `%3F`)防回归;修后须对真后端手工点验一次警示条出现。

## 🟡 重要问题(应该修复)

1. **[client/LinoN/Networking/APIClient.swift:438-440] `fetchReview(week:)` 同族隐患(潜伏未爆)。** `path += "?week=\(w)"` 走同一个 `get()`,非 nil week 必 404。当前唯一调用方 `AppModel.loadReview()` 恒传 nil(ReviewView 四个调用点均无参),所以线上从未触发——但这是颗雷:未来接"翻看历史周"一开即断,且失败被"复盘拉取失败"toast 弱化。修致命 #1 的 `get()` 时**必须一并覆盖此分支并补测试**(这也是为什么修法应落在 helper 层而非 fetchCorrelation 单点)。
2. **[client/LinoN/Components/SharedUI.swift:32-46 + client/LinoN/App/AppModel.swift:291-295] 净额展示丢分位,且同一 toast 内精度不一致。** `LNFmt.netAmount` → `signedMoney`(`maximumFractionDigits=0` + `.rounded()`),复盘周合计/逐笔、记忆流水、清仓 toast 的净额全部整元;而 toast 里费用用 `String(format:"%.2f")` 两位小数——同一句话里 "净收益 +¥984(含费 ¥15.71)"。Phase B 的产品价值正是"与券商交割单对账的净额精确到分"(后端确实逐分落库),展示层抹掉分位会让用户对账差几毛时怀疑系统算错。建议净额金额(至少清仓 toast + 复盘逐笔)展示到分;若拍板"整元是设计语言",请在 plan/CLAUDE.md 记录该决策以免下轮 reviewer 再报。

## 🔵 建议改进(可以考虑)

1. **[backend/app/screen/fetch.py:66-72] `load_industry_map` 失败后 `_INDUSTRY_LOADED=True` 永久粘住,且全库无 `force=True` 调用点。** 首次拉取遇瞬时网络错误后,行业映射整个进程周期为空:开仓 industry 恒空串、护栏恒 conflict:false;plan A1"候选刷新会自然回填映射"的说法在该场景不成立(15:35 刷新经 `pipeline→load_industry_map()` 无 force,直接命中已加载空缓存)。阶段2 既有行为(当时只服务白酒黑名单,退化无感),v1.3.0 让它有了新受害者。建议候选刷新处改 `load_industry_map(force=True)` 或对"已加载但为空"允许重试。
2. **[backend/app/db/store/schema.py:180-187] `_ensure_v130_columns` 四个 ALTER 共用一个 try**:positions.industry 失败会连带跳过 trades 三列。逐列 try 可在部分失败时尽量多补。概率极低、姿势沿既有先例,可不改,记录在案。
3. **[client/LinoN/Views/CandidatesView.swift:62-72, 191-216] iOS 导出分享的是 String 而非 .txt 文件**:ShareLink(item: String) 在"存储到文件"/部分目标 App 时不保证落成带名 .txt(macOS 侧 NSSavePanel 是真文件)。plan 字面允许 ShareLink、验收达成;想更顺手可改临时文件 URL。另 macOS `try? text.write` 静默吞写盘失败,可补一个失败提示。
4. **[client/LinoN/App/AppModel.swift:601-613] `checkCorrelation` 无并发/乱序防护**:6 位边界 + 失焦双触发下快速改码,晚到的旧响应可能覆盖新状态(显示错票的警示)。低频、影响轻,可用请求序号或 Task 取消兜。
5. **[backend/app/trade/costs.py] Python `round()` 银行家舍入**:恰逢半分位时与券商常用"四舍五入"可能差 1 分(如 round(2.675,2)=2.67)。实现严格照 plan `round(…,2)`,非缺陷;与交割单逐分核对偶差时的解释预案,记一笔即可。
6. **[backend/tests/test_v130_costs_migration.py:132] `monkeypatch, caplog` 两个 fixture 形参未使用**,顺手可清(cleaner 阶段)。

---

## 对照 Plan §4 完整性核对表

### 关键技术选型(7 条)
| 选型 | 结论 |
|---|---|
| 费用单一源 = settings 4 字段 + costs.py 纯函数,不进 store/constants | ✅(`app/trade/__init__.py` 文档还显式声明与铁律分离) |
| 净额后端清仓算好落 trades;仅闭合/复盘/记忆展示;持仓卡不显未实现净额 | ✅(TodayView 零改动) |
| 净额契约 nullable(🟡1):旧 NULL 原样 null、不兜 0.0、netPnlTotal 只 sum 非空 | ✅(后端 `_net_pnl_of`/`_net_amount_of` 两 helper + 前端 `Double?`,真 0 与 None 区分有专测) |
| "主线"=行业(Tushare 口径),不依赖候选 sector 串 | ✅ |
| 护栏只提示不拦、只买入路径、不进候选列表、降级静默 | ✅ 代码层;❌ 端到端(致命 #1) |
| `rules.CANDIDATE_LIMIT=20` 单一源 | ✅(grep 无散落硬编;客户端 `prefix(20)` 为 plan C3 明写的安全带) |
| TXT 后缀最长前缀优先 + 未知前缀 nil 跳过 | ✅(920 先于 9、68 先于 6,顺序正确) |
| migration 合并一次 `_ensure_v130_columns` | ✅ |

### Phase B(🔴高危)验收 ①–⑦
① 迁移幂等/缺列自动补/异常吞不拖垮 startup ✅(连跑三次、旧库补列数据无损、view 假表不拖垮 init_db)
② costs 公式:佣金触底 5 元双边 ✅ / 印花税仅卖出 ✅ / 过户费双边 ✅ / 净额=毛−费精确到分 ✅ / 亏损也扣费 ✅ / 费率引用 settings 非硬编 ✅ / 费用展示值==净额扣减值(同一 total_fee,无裂缝)✅
③ 清仓落三列 + close 响应带 fee/net(真实 HTTP)✅
④ 复盘/记忆 null vs 实值 vs 真 0 三态 + netPnlTotal 只 sum 非空 + 读旧行不 500 ✅
⑤ 纪律打分回归:`_compute_kept_flags`/score.py 纪律口径零 diff + 专项回归测试 ✅
⑥ 迁移失败后果固化:close 侧已测(OperationalError + 不产幽灵闭合);open 侧模拟未做(plan 标"可选")✅
⑦ pytest 378 全绿 ✅

### Phase A 验收 ①–④
① 开仓落 industry + 绝不联网(load_industry_map 调用即炸 + industry_of 被调标记 + 冷缓存秒回三重钉死)✅
② 端点命中/不命中(单测+HTTP)✅ ③ 纯函数 4 态 + 同 code 排除 ✅ ④ 降级不误报恒 200 ✅
偏离(已在 plan §3 记录):预热只留 correlation 端点、未接 lifespan——理由(TestClient 单测不联网纪律)成立,认可。
route 无遮蔽(无 GET /positions/{param} 路由);`list_holdings` SELECT * 确保 industry 进 compute_correlation。

### Phase C 验收 ①–⑦
① 满仓仍返 20 无闭门 ✅(HTTP 测试) ② 单一源 ✅ ③ 前端删🔒展示 Top20 ✅ ④ degraded 空列表不变 ✅
⑤ `rules.MAX_HOLDINGS` 双定义已消 + `SLOTS_PER_CANDIDATE`/`free_slots()`/`truncation_limit()` 删净(负向断言)✅;`store.MAX_HOLDINGS`(开仓满仓 409)与 `free_slots` 字段保留未动 ✅——**满仓仍不能开第 4 仓,只删了候选闭门** ✅
⑥ 旧截断测试重写为 20 口径(非 skip),另加"不足 20 原样返"边界 ✅ ⑦ 双端 build 绿 ✅

### Phase D 验收 ①–⑥
① 清仓/复盘/记忆展示净额,nil 显"—"、派生 bool 着色(nil 中性灰)、持仓卡不显 ✅(精度问题见 🟡2)
② 开仓 sheet 警示条(amber、只提示不禁用)代码 ✅ / 端到端 ❌(致命 #1)
③ 深析买入路径触发 ✅(`buyFromAnalysis` 回调内 checkCorrelation);候选列表无护栏 ✅ / 端到端 ❌(同上)
④ 满 6 位/失焦触发不逐字符 ✅;失败静默 ✅(正是掩盖致命 #1 的机制)
⑤ 绿涨红跌不变 ✅ ⑥ 双端 build + XCTest 绿 ✅(本版无新文件,xcodegen 无需重生)

### Phase E 验收 ①–⑤
① 沪 600/603/688/689/9、深 000/300/301、北 920/8/4 后缀单测全对 ✅(920363 不被 9 误判是专项锚点)
② 未知前缀跳过(compactMap,100000 不出现在 TXT)✅ ③ iOS ShareLink / macOS NSSavePanel 代码在;实机分享/存盘操作未点验(环境 Dock 守卫限制,沿既往退路)⚠ 代码级达成 ④ 空候选/降级禁用 ✅ ⑤ 双端 build 绿 ✅

### 红线核查(CLAUDE.md)
- 离场铁律常量(-5.0/+15/D4/count==4/容差带):`store/constants.py` **零 diff** ✅
- 纪律打分 `kept_*/broke_rule/discipline_rate`:`_compute_kept_flags`、score.py 纪律口径**字节不变** ✅
- `close_position` 经 facade 取 `insert_memory` 的姿势**原样保留**(positions.py:259-260)✅
- 费用常量另起单一源(settings + costs.py),未碰 store/constants ✅
- 绿涨红跌、marker 钳 98、buy_date 派生等既有契约未触碰 ✅
- monitor/、llm/、calendar/、fetch.py、trades.py、review.py 全部零 diff ✅

## 总判

**不可直接收口。** 先修致命 #1(修在 `get()` helper 层,一并消掉 🟡1 同族分支,补 URL 构造门禁,真后端手工点验警示条);🟡2 建议同批处理或明确拍板"整元展示"为设计决策并记录。其余 6 条 🔵 可入 §5 Backlog。修复后重跑双端门禁 + 更新本报告状态即可收口。
