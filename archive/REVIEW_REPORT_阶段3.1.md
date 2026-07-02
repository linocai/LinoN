# LinoN 阶段3.1(选股信号增强)审查报告

> reviewer:外部审计员视角从零审查(异源审:施工 builder-pro/Opus,审查独立跑),对照 `PROJECT_PLAN.md` §4(阶段3.1 全文,§4.0–§4.5)+ §4b 客户端契约。
> 审查日期 2026-07-02。**门禁均亲自跑通(非信 builder 自述)**;candidates 迁移风暴、信号5/6 交互、除权假涨停、两票池归一、边界守卫均**独立构造场景实跑复现**(45 条独立断言全过)。

## 整体评估

- **实现完成度:约 99%**。Phase A(rules 常量+评分函数+8 键权重)/ B(form/fetch 派生 vwap_ok·had_limit_up)/ C(pipeline 传参+warn 合并+score 输出+store 迁移+prompt 喂信号 1/2)/ D(客户端可选 score+双端徽章+解释条文案)全部落地,验收标准逐项命中。plan-critic 两轮抓出的 5 个风险点(迁移链路断层/信号5-6 打架/涨停数据源/客户端前向兼容/归一边界)**施工全部按修订方案落到位,独立验证无一走样**。剩余 1% 为下文一条 🟡(权威文件状态滞后,收口必修)+ 若干 🔵 打磨。
- **整体代码质量:高**。常量单一源纪律严守(新阈值只在 `rules.py` 顶部,fetch/pipeline/form 全经 `rules.` 引用,非注释零裸写);第二次真 migration 与阶段3 首例完全同套姿势且注释把"为何 ALTER 不 DROP"的因果(回填样本不可丢)写进了函数 docstring;新增测试全是真断言(含 grep 守卫防 DROP 回归),无占位/伪测试。
- **主要亮点**:
  1. **迁移按高危区姿势精确复刻先例**:`_ensure_candidates_columns`(store.py:190)= `PRAGMA table_info` 精确集合探测 + `ALTER TABLE ADD COLUMN score INTEGER` + 整段 try/except **只 log.error 不 re-raise**,挂 `init_db`(app.py:70 lifespan 启动路径)`executescript` 之后 `commit` 之前。独立实跑:手工造阶段2 旧表(13 列无 score)+ 3 行历史 → **连跑 init_db 3 次**不抛 duplicate column、历史行值逐字节不变、旧行 NULL 经 `list_candidates` 回读 0(int)、`pending_backfill_entries` 迁移后仍命中全部历史行(证明未 DROP)、迁移后新写行 score round-trip 一致——全过。`test_candidates_migration.py` 6 条断言真实覆盖同场景,另含 `inspect.getsource` grep 守卫(init_db/迁移函数无 `DROP TABLE`、迁移方式=`ADD COLUMN score`)防回归。
  2. **信号5/6 时间窗互斥真的落地了**:`compute_form`(form.py:140-151)涨停扫描循环 `i ∈ [1, 1+ACTIVE_LOOKBACK_DAYS)`,pct[i] 用 closes[i]/closes[i+1]——**index 0(今日)确实不在窗口内**。独立构造:仅今日 +10% 暴涨、历史 10 日全温和 → `had_limit_up=False`(今日只交信号6 罚+warn,不被信号5 奖励);历史第 3 日涨停 → True;涨停恰在窗口边界 i=10 → True、i=11(窗口外)→ False——语义各归其位,plan-critic 🟡#1 修订无走样。
  3. **涨停判定从复权 closes 内部派生,除权不产假涨停**:`compute_form` 签名只新增 `amounts_new_to_old` 一个可选入参,**无 `raw_pcts_new_to_old`**(plan-critic 🟡#2 修订按删)。独立构造 10 送 10 除权(raw 5.05/5.0/10.0... + adj [2,2,1...])→ 复权后除权日 pct=0%,无假涨停;**反证**同 raw 不复权直接算会产 +102% 假涨停(证明复权路径是必要且生效的);合股(价格翻倍)场景同验通过。
  4. **score 归一口径逐条对齐 plan**:`_normalize_scores`(pipeline.py:156)在 `build_candidates` 内对**全部 survivors 截断前**调用(截断在端点 `all_rows[:limit]`,读库后才做);区间 `[SCORE_FLOOR=10, 100]`;两票池 [0.5001, 0.5000] → **[100, 10]**(非 100/0);单票/全相等 → 全 100;单调保序(与 rank 同源同序,rank=1 恒 100、末位恒 10)。候选 dict 键集合精确 = 阶段2 的 12 键 + score(test_candidates_api 有精确集合断言)。
  5. **契约变更最小化到极致**:`app/api/app.py` **零改动**(score 经 pipeline→upsert→list dict 直透,`CandidatesList.candidates` 是 `List[Dict]` 不吞键);monitor/review/api 三目录 git diff 为空;`store.py` 顶部 `-5.0/+15.0/D4/容差带/MAX_HOLDINGS` 原样未动;`tushare_client.py` 未动(**零新增 Tushare 接口**——amount 从既有 `ts_daily_all` DataFrame 顺手取列);coach 模式 prompt 不加吸筹/出货提示(仍二元拿/清,有测试锁死)。
  6. **客户端前向兼容是真的**:`Candidate.score: Int? = nil` + `CandidateListDTO.score: Int?` 均可选;`testDecodesOldResponseWithoutScoreDoesNotFail` 真解码一份**不含 score 键**的 JSON 断言 `score==nil` 且其余字段照常——非伪测试。iOS 徽章置于 rank chip **下方竖排**(不新增横向列、不抢中列宽,避开"macOS 横列套 iOS 挤省略号"旧坑),macOS 加 54pt 窄列;nil 时 `@ViewBuilder` 整段不渲染、布局不塌(双端各有离屏快照测试)。解释条护栏文案走可换行 Text(避开窄屏 pill 换行旧坑)。

### 门禁亲验结果(全部真实跑通)

| 门禁 | 结果 |
|---|---|
| 后端 `python -m pytest` | **309 passed, 0 failed, 0 skipped**(基线 276 + 阶段3.1 新增 33),与 builder 自述一致。 |
| 客户端 XCTest(iOS Simulator, LinoJ-iPhone16Pro) | **44 passed, 0 failures, TEST SUCCEEDED**(基线 40 + 新增 4:score 双解码 ×2 + macOS 行快照 + nil-score 不塌快照),与自述一致。build 隐含 SUCCEEDED(test 前置 build 通过)。 |
| 迁移风暴独立实跑 | 阶段2 旧表(无 score)+ 3 历史行 → init_db ×3:补列一次、无 duplicate、行值不变、NULL→0、回填扫描命中、迁移后写读一致——**全过**。 |
| 信号5/6 独立实跑 | 仅今日涨停→False / 历史涨停→True / 窗口边界 i=10 含·i=11 不含——**全过**。 |
| 除权假涨停独立实跑 | 送股+合股两向复权后无假涨停 + 不复权反证会假涨停——**全过**。 |
| 归一/边界独立实跑 | 两票 [100,10]、单票/全相等 100、保序;mv≤0→0.5、vols[0]=0 不除零、缺 amounts→False、turnover/day_surge 分段——**全过**(45/45)。 |
| 常量单一源 grep | 新阈值(TURNOVER_HEALTHY/MV_*/ACTIVE_LOOKBACK/LIMIT_UP/DAY_SURGE/SCORE_FLOOR)非 `rules.py` 处的命中**全为注释**,代码一律 `rules.` 引用——**通过**(Phase A 验收4)。 |
| 不可触碰契约 | store.py 常量段/monitor/review/api/loop(15:35 tick)/tushare_client 全零 diff;黑名单/高位线未被新信号污染(6 条全软:权重/LLM 输入/warn);无新端点、无盘中选股、无效果分析视图(§4.4 OUT 逐条核过)——**通过**。 |

---

## 🔴 致命问题(必须修复)

**无。** 无迁移丢数据/崩溃路径、无契约漂移、无解码失败窗口、无排序语义走样、无钉死常量漂移、无密钥泄漏。任务书 9 项重点审查全部核实通过(见亮点与门禁表)。

---

## 🟡 重要问题(应该修复)

### 1. [PROJECT_PLAN.md §3(52行)+ §6 变更日志] 权威文件状态滞后于施工——收口前必须更新

§3「当前状态」仍写 **"阶段 3.1(选股信号增强)规划中"**、门禁数字停在 **pytest 276 / XCTest 40**(实际已 309/44),§6 变更日志只有立项与 plan-critic 修订两条、**无施工完成条目**;整个阶段3.1 改动(17 文件 + 新测试文件)也**尚未 git commit**。PROJECT_PLAN.md 是"新会话从此接手"的唯一权威入口,此刻开新会话会误判阶段3.1 还没施工。
- **影响**:纯文档/流程,不碰代码;但按全局工作流"每个 Phase 完成后更新 plan 的『当前状态』节"属施工侧欠账,且不修会让收口/部署链路(§4.5 备份→重启触发迁移)失去准确基线。
- **修复建议**:收口时一并处理——§3 状态改"代码完工待部署"、门禁数字刷 309/44、变更日志补施工完成条(含本报告指针),git commit 全部改动。

---

## 🔵 建议改进(可以考虑)

1. **[backend/app/api/app.py:306 + store.py:194 docstring]** `_recompute_candidates` 的 `store.upsert_candidates(td, rows)` 在 try 之外:若生产上 ALTER 迁移静默失败(列缺失,概率极低——SQLite ADD COLUMN 基本只败于磁盘/锁),INSERT 硬编 score 列会抛 `no such column` → `POST /candidates/refresh` 返 500(EOD tick 由 loop 外层 try 吞,不掀翻轮询)。与迁移 docstring "score 缺了候选照跑"的表述不符(实际是候选刷新不照跑)。此模式与阶段3 trades INSERT(name/note 无条件入列)完全同款,系项目已接受的先例,不阻断;下版本可把 upsert 挪进 try 或订正 docstring 措辞。
2. **[backend/app/db/store.py:109(_SCHEMA candidates DDL)]** DDL 不含 score 列、也无指向迁移函数的注释,新库靠 ALTER 补列(与 trades name/note 先例一致,功能正确、我已实测)。随补列增多,"DDL ≠ 真实 schema"会越来越隐晦;建议在两张表的 CREATE TABLE 注释里各加一行"另有 X 列由 _ensure_*_columns 迁移补充"。
3. **[部署过渡窗口观感]** 旧行 NULL→0 兜底使部署后**首个 refresh 前**(≤1 交易日,15:35 自愈)客户端对上一交易日缓存行显示"0分"徽章——0 在 [10,100] 值域之外,与解释条"当日相对分"口径略冲突(plan §4.1 已明示拍板 NULL→0、"显示 0 分属预期",实现照 plan,故仅记观感);备选方案是 list_candidates 对 NULL 仿 warn 省略键、客户端 nil 不显徽章。另 `CandidatesExplainBar` 的相对分护栏文案在全 nil-score(旧后端)时也恒显示,同属过渡窗口小观感。
4. **[backend/tests/test_form.py:test_had_limit_up_from_qfq_no_false_positive_on_dividend]** 该测试传入的是**已复权的平滑序列**,略同义反复(没走"raw 跳变 + adj_factor → qfq → compute_form"的组合路径);建议收进本审查用的对照样例(送股 raw+adj 复权后无假涨停 / 同 raw 不复权反证会假涨停),把复权必要性锁进门禁。
5. **[client/LinoNTests/CandidatesAnalysisTests.swift:CandidateScoreDecodeTests]** 前向兼容测试解码的是 `Candidate`(public)而非列表实际解码路径的 `CandidateListDTO`(private,无法直测);两者同为 synthesized optional decode、行为等价,是合理代理——可在测试注释里点明"DTO private 不可直测,以 Candidate 同构代理"。

---

## 结论

**零致命、零代码级重要问题,可以收口。** 唯一 🟡 是权威文件状态滞后(收口动作本身),连同 git commit 在收口阶段一并完成即可。plan-critic 规划阶段抓出的全部风险点(candidates 迁移链路、信号5/6 打架、涨停数据源、客户端前向兼容、归一边界)经独立构造场景实跑,确认施工按修订方案不折不扣落地。部署时按 §4.5:先 `cp linon.db linon.db.bak-YYYYMMDD` 备份,再重启触发 ALTER(幂等已验)。
