# REVIEW_REPORT v1.3.1(盘后选股完善)— 外部审计(reviewer @Fable)

> 审查范围:`git diff 31c9d9e HEAD`(6dbcfd8 批1后端A+C / 8721cab 批2后端B / e113744 批3前端)。
> 权威对照:PROJECT_PLAN.md §4 Phase A(A1/A2/A2.5/A3)/ B(B1/B2/B3)/ C(C1/C2)+ 契约汇总表。
> 红线:项目 CLAUDE.md。审查日期 2026-07-05。已知项(mv_elastic >500 硬台阶,待用户决定)不计入。

## 整体评估

- **实现完成度:约 97%**。三块(A 新选股逻辑 / B 配置可调化 / C 刷新改手动)全部落地,plan-critic 的 1 致命 + 6 重要 + 6 建议逐条有对应实现与门禁测试;缺口集中在 B2 的跨字段校验(plan 明列未实现)与 B3 调参屏一处状态守卫。
- **代码质量:高**。分层清晰(配置存取/校验归一/穿参生效三层职责分明),cfg=None 回落路径对旧调用零扰动,测试针对性强(穿透缓存回环、grep 守卫、真实 HTTP、端到端穿参各就各位),注释把"为什么"写透。
- **主要亮点**:① 致命#1(warnLevel 缓存断层)封得干净——migration/三处同步/三态回环 + `build_candidates→upsert→list` 端到端,同类盲区(v1.3.0 URL 坑)不复发;② `validate_screen_config` 的 `normalize_weights` 显式布尔严格对应"PUT 不归一/resolve 才归一",并防了 bool-是-int-子类混入;③ `test_recompute_candidates_reads_user_config_from_store` 走真实 store→resolve→run_pipeline 全链,"穿参真生效"不是嘴上说的。

## 门禁复跑(reviewer 亲跑)

| 门禁 | 结果 | 预期 |
|---|---|---|
| 后端 `python -m pytest` | **443 passed**(8.09s) | 443 ✓(378→443,批1+25/批2+40) |
| 客户端 XCTest(iOS Simulator LinoJ-iPhone16Pro) | **90 tests, 0 failures, TEST SUCCEEDED** | 90 ✓(65→90,+25 数目逐一对上) |
| iOS Simulator build | **BUILD SUCCEEDED** | ✓ |
| macOS build | **BUILD SUCCEEDED** | ✓(macOS test destination quirk 按 CLAUDE.md 未用) |

git 工作树干净,三批全部已 commit。

## 对照 Plan 完整性核对表

### Phase A(新选股逻辑)
| 验收项 | 结果 | 证据 |
|---|---|---|
| A1 WEIGHTS 9 键、正权和==1.00 + 断言 | ✅ | `rules.py` WEIGHTS;`test_weights_positive_sum_to_one` 断键集+和+vol_ratio=0.30 |
| A1 新常量(VOL_RATIO_MIN/换手[7,15]/市值[50,500]·floor30/BREAKOUT_*)+"经验默认"标注 | ✅ | rules.py 常量区,注释齐 |
| A1 `high_position_verdict` 不再产 exclude(200→warn) | ✅ | `test_high_position_verdict` + `_no_exclude_branch` 全值域扫 |
| A1 `high_warn_text` ≥100% 红级文案(重要#6) | ✅ | "极高位,追高高危";`test_high_warn_text` 断非空+含"极高位";`high_warn_level` 配套 |
| A1 pos_health 不走 min-max(0.99 vs 0.30) | ✅ | rank_score 直接乘权;`test_rank_score_pos_health_not_min_maxed` |
| form pos_health len<20→0.0(建议#9)+ 恰好20 边界 | ✅ | `test_pos_health_data_insufficient_under_20_days_zero` / `_exactly_20_days` |
| form breakout 三条件、振幅窗口 closes[1:25] 排除今日(重要#5)、门禁用例"窄横盘+大阳线→True" | ✅ | `test_breakout_ok_narrow_range_then_today_breaks_out_with_volume`(docstring 论证按错误公式该例必 False,回归护栏成立)+ 4 条反例/边界 |
| A2 StockRow.volume_ratio NaN 安全(重要#4) | ✅ | `_safe_float`(pd.isna+pd.NA+异常兜底);NaN→0.0→粗筛淘汰测试;不进 rank_score min-max |
| A2 passes_coarse 换量比 / build_candidates 删 exclude 分支 / rank_score 新九参 | ✅ | pipeline.py;`test_pipeline_blacklist_kept_high_position_no_longer_excluded` 关键回归断言 `600002 in codes` |
| A2 展示口径解耦(volMultiple/volPct 仍自算放量,建议#10) | ✅ | `_fmt_vol_multiple(sr.vol_multiple)`/`_vol_pct` 未换源 |
| A2.5 第四次 migration `warn_level TEXT`(PRAGMA+ALTER+只 log 不 re-raise) | ✅ | `schema._ensure_candidates_columns` 扩展,同 score 姿势;旧表补列/幂等/历史行无损测试 |
| A2.5 三处同步(_CANDIDATE_KEYS / INSERT / list 输出,NULL 省键) | ✅ | candidates.py 三处齐;`SELECT *` 读回不受列序影响 |
| A2.5 穿透缓存回环 high/amber/nil(致命#1 门禁) | ✅ | 三条单态回环 + `test_warn_level_mixed_pool_roundtrip_via_end_to_end_pipeline`(pipeline 真产→upsert→list) |
| A3 Candidate.warnLevel 可选 + DTO 解码 + 红/琥珀 pill + 背景 + 不字符串判负 | ✅ | Models.swift/`CandidateListDTO`/`warnOrSector`·`rowBackground` 严格 switch warnLevel;decode 3 条 + 派生 4 条测试;旧后端 nil→琥珀兜底 |

### Phase B(配置可调化)
| 验收项 | 结果 | 证据 |
|---|---|---|
| B1 `screen_config` 表 CREATE TABLE IF NOT EXISTS(非 ALTER)、幂等 | ✅ | `_SCHEMA` + 连跑 init_db 测试 |
| B1 `store/screen_config.py` get/put/updated_at;无行/坏 JSON/非 dict→{} | ✅ | 模块 + 7 条存储测试 |
| B1 PUT 存增量(只存提交键、覆盖式替换整行) | ✅ | `test_put_screen_config_overwrites_whole_row` |
| B1 DEFAULT_SCREEN_CONFIG 引用构造 + 等值断言(建议#8) | ✅ | SPEC default 引用 WEIGHTS/常量;21 键逐一等值测试 + 正权和≈1 |
| B2 resolve = DEFAULT⊕user→validate(normalize=True);未知键忽略 | ✅ | 4 条 resolve 测试 |
| B2 校验:类型错/缺失/非有限值(nan/inf,math.isfinite)/bool 拒绝/越界夹紧/int 取整/day_surge[-1,0]/全0退默认/垃圾输入不崩 | ✅ | 13 条 validate 分支测试 |
| B2 跨字段约束(换手带 lo<hi、市值带 lo<hi 且 floor<lo) | ⚠️ **未实现** | 见 🟡#1 |
| B2 权重归一只在 resolve 全量后;PUT 逐键夹不归一(显式布尔) | ✅ | `normalize_weights` 参数;PUT 全 9 权重键也不归一的测试 |
| B2 生效=显式穿参 cfg、禁 monkeypatch 常量;cfg=None 回落模块常量保旧测试 | ✅ | 全链尾参 cfg;`test_passes_coarse_respects_cfg_vol_ratio_min`(断 rules.VOL_RATIO_MIN 未动)+ run_pipeline 端到端 + `_recompute_candidates` 经真实 store 三层证据 |
| B2 深判层不读配置(断言守卫) | ✅ | analyze.py 零 diff;grep 断言 ×2(无 screen_config 字样 / compute_form 无 cfg=) |
| B2 端点 GET/PUT 契约(鉴权/夹紧不 422/未知键忽略/恢复默认 PUT{} 清行/updated_at) | ✅ | 8 条真实 HTTP 测试(TestClient) |
| B3 调参屏(9 滑块+正权和提示不自算归一 / 12 阈值步进 / 保存回填 / 恢复默认 PUT{} / 不自动触发刷新) | ✅* | ScreenConfigView + AppModel;*入口实现为双端 sheet(plan 写 iOS NavigationLink/macOS 区块),注释了原因(macOS Settings 场景无 NavigationStack),合理偏离,见 🔵#8 |
| B3 APIClient put() 走 makeURL + URL 门禁测试 | ✅ | `put(_:body:)` 走 makeURL;`testMakeURLScreenConfigNoQuery` |

### Phase C(刷新改手动)
| 验收项 | 结果 | 证据 |
|---|---|---|
| C1 删 15:35 tick + `last_candidate_date` + `_is_after_candidate_window`/`_CANDIDATE_AFTER` + `run_candidate_refresh` 死码(建议#11) | ✅ | loop.py;`test_candidate_auto_refresh_helpers_removed`(hasattr 四连);backend/app+scripts 无残留引用 |
| C1 EOD 摘要保留;回填移入 `last_eod_date` 守卫 EOD 块(重要#7) | ✅ | grep 守卫测试(backfill 调用位置在 elif 块内、无 last_candidate_date)+ 端到端 run-once 测试(同日多轮 tick 各只跑一次) |
| C1 手动 POST /candidates/refresh 仍唯一入口 | ✅ | 端点未动,现有 api 测试绿 |
| C2 文案微调(手动语义) | ✅ | footnote"上次手动刷新结果,点刷新重算" |

### 契约与红线
- 契约表 4 行逐一对上:GET/PUT `/screen/config` 形状 ✓、candidates dict 增可选 `warnLevel`(经缓存表往返)✓、`score`/`warn` 不变 ✓、refresh 不变 ✓。
- **离场铁律零触碰**:`store/constants.py`/`hardline.py`/`eod.py`/`escalation.py` diff 为空 ✓。
- 选股常量单一源:SPEC/DEFAULT 由常量引用构造,等值断言在门禁 ✓;高位分级阈(HIGH_*)/MV_MEGA_CEIL 不进配置,注释点明 ✓。
- 绿涨红跌未碰;warn 分级走后端字段派生,无字符串判负 ✓。

## 🔴 致命问题(必须修复)

(无)

## 🟡 重要问题(应该修复)

1. **[backend/app/screen/rules.py:334 `validate_screen_config`] plan B2 明列的跨字段约束未实现**:「换手带 lo<hi 且 ∈[0,50]、市值带 lo<hi 且 floor<lo」只做了逐键独立夹紧,没有 lo/hi/floor 互相校验。用户可经调参屏合法存入 `turnover_lo=20, turnover_hi=10` 或 `mv_lo>mv_hi`、`mv_floor>mv_lo`:评分函数因既有 `span<=0` 守卫**不崩、不产 NaN、输出仍夹在 [0,1]**,但反转带令因子单调性畸形(如 turnover t 略低于 lo 得 ~1 分、落入 [hi,lo] 反而骤降到 0),排序静默失真且 UI 无任何提示。修复建议:`validate_screen_config` 在逐键夹紧后补一步带内一致性收口(如 hi<lo 时交换或把 hi 抬到 lo、floor≥lo 时把 floor 压到 lo 之下/回退默认),并补 3 条反转带测试。
2. **[client/LinoN/Views/ScreenConfigView.swift:106-123 + AppModel.swift:588] 「保存/恢复默认」未挂加载态守卫,可意外清空用户配置**:`screenConfigLoading` 在 AppModel 里维护但视图从未消费;`.task { loadScreenConfig() }` 异步未返回(或拉取失败)时 `screenConfig` 仍是 `[:]`,此刻点「保存」= `PUT {config:{}}` = **恢复默认语义,把用户已存的增量整行清掉**(滑块此时显示 0 兜底值,UI 看着就不对,但按钮可点)。修复建议:`保存`/`恢复默认` 按钮 `.disabled(model.screenConfigSaving || model.screenConfigLoading || model.screenConfig.isEmpty)`,一行收口。
3. **[流程/文档] 项目 CLAUDE.md 两处描述已被本版推翻 + PROJECT_PLAN §3 未记批3**:CLAUDE.md「阶段2」节仍写"高位线 ≥100% 排除·≥50% warn、排序权重 vol0.4/fund0.25/turnover0.2/low0.15"(三代前口径)与"候选刷新 tick(15:35):`loop._is_after_candidate_window`…`run_candidate_refresh`"(机制本版已整体删除);§3 的 v1.3.1 施工记录止于批2,批3(前端 A3/B3/C2,e113744)未入。CLAUDE.md 是 builder/reviewer 必读红线文件,过期条目会直接误导下一个会话。收口(cleaner/主会话)时同步更新。

## 🔵 建议改进(可以考虑)

1. **[backend/app/screen/rules.py:441] `rank_score` cfg=None 时权重取 `DEFAULT_SCREEN_CONFIG`(import 时快照)而非活的 `WEIGHTS`**:`c.get(k, WEIGHTS[k])` 永远命中快照,对 `rules.WEIGHTS` 的 monkeypatch 不生效——与批2记录"cfg=None 回落模块级常量、monkeypatch 仍生效"的措辞在权重维度不符(阈值函数维度成立)。当前无测试受累(grep 无 WEIGHTS monkeypatch),属埋给未来测试作者的暗坑;可改为 `w = {k: (cfg or {}).get(k, WEIGHTS[k]) ...}` 或在注释里如实写明差异。
2. **[backend/app/api/schemas.py:159] `ScreenConfigIn.config` 有 `default_factory=dict`**:PUT body 漏掉 `config` 键(如 `{}`)会被当成 `{config:{}}` 即"恢复默认"执行——把最有破坏性的语义设成缺省不妥;建议 `config: Dict[str, Any]`(必填),缺键 422。
3. **[backend/tests/test_candidates_api.py] 缺一条 HTTP 层 `GET /candidates` 带 `warnLevel` 的断言**:store 层回环已封死、端点是 `List[Dict[str,Any]]` 原样透传,风险极低,但 A2.5 验收措辞点了"`list_candidates`/`GET /candidates`"两处,补一条 3 行测试即闭环到字面。
4. **[client/LinoN/App/AppModel.swift:604 `saveScreenConfig`] 保存 PUT 全量 21 键会把未改过的默认值也冻结进用户增量**:plan B3 原文即"PUT {config: 用户改过的全部当前值}",实现合规;但与「恢复默认=PUT{} 防把 DEFAULT 冻结进库挡未来默认演进」的设计动机存在内在张力——用户存过一次后,未来版本调整默认权重对其不再生效(除非手动恢复默认)。记录该权衡;若要消除,客户端 diff-vs-defaults 只提交改动键即可。
5. **[backend/app/screen/rules.py:127] `VOL_MULTIPLE_MIN` 已无消费点**(粗筛换 VOL_RATIO_MIN 后仅剩注释引用),留给 cleaner 删除或注明"仅文档锚点"。
6. **[client/LinoNTests/ScreenConfigTests.swift:7] 文件头声称覆盖"保存后不自动刷新候选(产品决策)"但无对应断言**(saveScreenConfig 代码路径确实无 refresh 调用,行为正确);删掉该句或补一条断言,避免注释过度声称。
7. **[backend/app/monitor/loop.py:333] 回填触发点从 ≥15:35 提前到 ≥15:05 的时序观察(无行动项)**:`min_trade_days=4` 下第 3 个 exit 交易日可能恰=今天,15:05 时 Tushare 当日 daily 若未发布则该 entry skip、次日 EOD 自愈(扫描式防重兜住);与旧 15:35 同级风险,且挂 EOD 块是 plan 明令,仅记录。
8. **[client/LinoN/Views/SettingsView.swift:50 偏离说明]** B3 入口 plan 写"iOS NavigationLink / macOS 区块",实现为双端统一 sheet(注释已说明 macOS Settings 场景无 NavigationStack 推不动)——偏离合理,但按纪律应在变更日志「偏离说明」记一句(可并入收口条目)。

## 结论

**可以收口**。致命 0;🟡#1(跨字段夹紧)与 🟡#2(调参屏加载态守卫)建议收口前顺手修掉(各为小改+补测),🟡#3 属收口动作本身;🔵 按惯例入 §5 Backlog。四道门禁(pytest 443 / XCTest 90 / 双端 build)reviewer 亲跑全绿。部署前置(第四次 migration 先 `cp` 备份)§5 已备案,待部署时执行。
