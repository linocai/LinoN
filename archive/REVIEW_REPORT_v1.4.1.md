# REVIEW_REPORT_v1.4.1 — 今日盈亏 + 选股分绝对口径 + 刷新基准日修复

> reviewer(Fable 5)外部审计视角,从零对照 PROJECT_PLAN.md §4(v1.4.1,含 plan-critic 5🟡+7🔵 修订 + 2026-07-07 增补 Phase D)逐项检查。
> 审查对象:commit `6d9898a`(批1 后端 A+C+D)+ `90a37cb`(批2 前端 B)。审查日 2026-07-07(交易日,门禁于盘中 10:04 实跑)。

## 整体评估

- **实现完成度:~98%**。Phase A/C/D 后端与 Phase B 前端逐条对齐 plan(含全部 plan-critic 修订点);唯一缺口是 Phase B 验收③(离屏快照核对)未执行、无证据(见 🟡1)。
- **整体代码质量:高**。纯函数分层干净(today_pnl.py 零依赖可注入)、降级姿势与既有契约一致、注释把口径与坑写死;测试改写有理有据、非放水(两票池断言反而从"值断言"升级为"公式重放锁定")。
- **门禁实测(reviewer 亲跑)**:
  - 后端 `python -m pytest` → **532 passed**(498+A18+C12+D4,与 plan 对账吻合);
  - 客户端 iOS Simulator `test` → **118 passed / 0 failures**(115+B3),`TEST SUCCEEDED`;
  - macOS `build CODE_SIGNING_ALLOWED=NO` → `BUILD SUCCEEDED`;
  - 特别验证:全部门禁在**真实交易日盘中(周二 10:04)**跑通——Phase D 引入的时刻依赖被正确冻结(date+datetime 双冻结),无一时间敏感测试裸奔。

### 重点验算记录(对应审查任务 7 项)

1. **今日盈亏金额(核心)**:纯函数逐分支手工验算通过——用户实景(今日割一票净 −370 + 持 3 票,其一今日新买)`realized=-370 + float=520 → today_pnl=150`,数字精确;次日视角昨割票归零;date-only close_time 经"裸 since 超集(SQL 字典序)+ 纯函数 `[:10]` 精确判定"两层一致(🟡3 修订落实);NULL net_pnl_amount 跳过;price 先判(🟡1,停牌不抛 TypeError);pre_close 缺失仅非新买降级;整体聚合异常兜底 `partial=true` 三字段回 0(🟡2,绝不假 false);冻结周六 + buy_date=下周一(D5 坑)走 pre_close 分支如实显上一交易日变动(🟡4)。验收 ①–⑧ 全有对应测试。
2. **`_resolve_quotes_map`**:独立新增,`_resolve_prices` 逐字节未动,coach 两调用点(app.py:715/803)无恙;`getattr`+dict 回退兼容 `_Q(price)`/`lambda: {}` 替身(存量 498 测试零改动佐证);每次 `GET /positions` 仍只经 `_quotes_fn` 拉一拍,拉价次数未变;空仓短路不空拉。
3. **Phase C 绝对分**:`_normalize_scores = int(round(clamp(raw×100, 0, 100)))` 实测 `[-0.06,0,0.404,0.9999,1.2]→[0,0,40,100,100]`;两曲线拐点与 plan §4.2 逐字一致(vol [1.0,3.0]/fund [0,15]%),输入字段亲证为 `s.volume_ratio`(官方量比)与 `s.net_mf_rate_3d`(%,近3日占比合计,pipeline.py:120-121);`SCORE_FLOOR`/`_normalize` 孤儿全库 grep 仅余注释提及;score NULL→省键经迁移测试 `test_null_score_reads_back_omits_key` 锁死,`CandidatesList` dict 透传 + 客户端 `Candidate.score: Int?` 前向兼容;`candidates/intraday` 只读 code/name 零波及;`backtest.py` 零 `score` 引用、零 app.api 依赖亲证(另有 source-grep 守卫测试)。正权和实测 1.0、day_surge −0.06,clamp 域封死。
4. **Phase D**:`_CANDIDATE_EOD_READY = time(15,35)` 模块级常量 + 语义注释(与 `_is_intraday_window` 明示"勿混用");docstring 与实现对齐;15:35:00 归 today 有专测;`_disp_date`/`upsert_candidates` 链路未动;三个时间窗口(loop `_EOD_AFTER` 15:05 回填 / basis 15:35 / intraday 09:30–15:00)三常量三语义互不引用。**活体验证**:盘中真实时钟下 `_candidate_basis_date() == "20260706"`(上一交易日)——用户 07-07 早 9:22 刷新空转的 bug 场景直接修复;存量 refresh 测试全走注入替身、不断言 basis,无时刻脆性。
5. **Phase B 客户端**:4 字段 `Double?/Bool?` 可选解码 + `?? 0/false` 兜底(旧后端缺键不崩,有专测);染色 `Double.pnlColor(self >= 0 ? up : down)` 数值派生,避开 Unicode − 坑(有专测含 0→绿);partial 文案双端就位;KPIHeroIOS/KPIStripMac 均在空仓判断之前无条件渲染 → 空仓且今日有已平时今日盈亏仍显示;`fetchPositions` 全部 2 个调用点(AppModel/SettingsView)已适配;批1 scoreNote 文案改绝对口径措辞(含"常态 30–70"🔵11)。
6. **测试质量**:新增 18+12+4+3 与门禁增量对账吻合;涉时测试 date+datetime 双冻结;存量改写(`test_pipeline_candidate_shape`→值域断言、`two_stock_pool`→rank_score 公式重放锁定、`single_and_all_equal`→等值输入等分)语义合理非放水。
7. **契约不变性**:`store/constants.py`、`hardline/eod`、`intraday.py`、`Models.swift` 本版零改动(diff 文件清单亲证);守味隔离/D4/绿涨红跌未触碰;`GET /candidates` 形状仅 score 键"NULL 时省略"这一处已拍板变化(🔵9);零 migration、零新表、零新端点属实;无 scratch/死代码残留。

## 问题清单

### 🔴 致命问题(必须修复)

- 无。

### 🟡 重要问题(应该修复)

1. **[Phase B 验收③ 未执行]** plan §4 Phase B 验收③"离屏快照核对今日盈亏卡渲染"无任何执行证据:`SnapshotRenderTests.swift` 无 KPIHeroIOS/KPIStripMac 渲染用例,commit/plan §3 也未记人工目检。本版 KPIHeroIOS 是唯一实质布局重构(单列 hero → 双列 HStack + 注脚),而本项目两次"build 绿但布局翻车"前科(候选 pill 窄屏挤竖排、macOS 窗口 sizing)都只有可视核对能抓。**修法**:批3 部署/换包前补一次 `ImageRenderer` 快照(KPI 卡非 ScrollView 包裹,可直接渲)或人工目检双端一次,结果记入收口记录即可,不必改代码。

### 🔵 建议改进(可以考虑)

1. **[PROJECT_PLAN.md §3 / commit 90a37cb message]** "SettingsView `fetchPositions()` 编译坑(批1 遗留,未跑客户端门禁所致)"归因不实:批1 客户端仅改 CandidatesView 文案、未动 APIClient,批1 后客户端可正常编译;该"坑"实为批2 自身把返回元组 2→6 后的调用点适配(正常重构步骤)。建议收口变更日志更正一句,免未来读史误判"批1 曾破坏客户端构建"。
2. **[client/LinoN/Networking/APIClient.swift:381]** `fetchPositions` 返回 6 元命名元组,再扩就难维护;下次动它时改具名 struct(如 `PositionsFetchResult`)。
3. **[backend/app/api/today_pnl.py:60-61]** 今日新买分支未防 `buy_price<=0`(base=0 → 浮动虚增为 price×qty)。唯一写入口 API 层 `Field(gt=0)` 已挡死、现实不可达;但该函数自称独立可注入纯函数,补一行"`buy_price<=0` → 记 0+partial"防御更自洽。
4. **[client 前向兼容展示]** 对旧后端(缺 4 键)今日盈亏显"+¥0"绿而非隐藏/"—"(plan §4.1 写"可隐藏或显—",措辞是允许式;前后端同机同发窗口极小,可接受)。顺手项:macOS partial 文案"部分持仓缺今日行情"比 iOS/plan 少"数据"二字,可对齐。
5. **[backend/tests/test_screen.py:809-818]** `test_backtest_does_not_consume_score_field` 用 `inspect.getsource` 子串断言,注释里若未来出现 `["score"]` 字样会误报——与阶段3 `status=` grep 守卫同款已知脆性,记录在案、可不改。
6. **[backend/app/api/app.py:238-252]** prices/pre_closes 派生(含 `float()` 转换)在今日盈亏 try 块之外——真 Quote 恒 float、暴露面与旧 `_resolve_prices` 完全相同(非回归);若追求绝对稳可把派生挪进聚合 try。
7. **[process]** 本地 main 领先 origin/main 2 commits 未 push;批3 收口时随部署一并 push(项目记忆已明确"直接 commit 别留待手动",push 同理不要挂着)。

## 结论

**可进入批3(部署/收口)**。零致命、零代码级重要问题;唯一 🟡 是验收流程缺口(部署前补一次 KPI 卡可视核对即闭合),7 条 🔵 均不阻断、可收口时顺手或入 Backlog。三 Phase 与 plan(含全部 plan-critic 修订)逐条吻合,契约不变性守住,门禁三项 reviewer 亲跑全绿且经受了"交易日盘中实跑"的时刻压力测试。
