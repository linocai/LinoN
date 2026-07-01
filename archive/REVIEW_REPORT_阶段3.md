# LinoN 阶段3(复盘闭环)审查报告

> reviewer:外部审计员视角从零审查(异源审:施工 builder-pro/Opus,审查独立跑),对照 `PROJECT_PLAN.md` §4(约75–210 行)+ §4b 客户端契约 + `Models.swift`。
> 审查日期 2026-07-01。**门禁均亲自跑通(非信 builder 自述)**;迁移幂等/失败态、原子回滚、防串味隔离、ISO 周边界均**独立构造场景实跑复现**。

## 整体评估

- **实现完成度:约 98%**。四件事(周复盘打分 / 复盘·记忆端点 / trades 首次真 migration / 教练大脑注入)全部落地,§4.4 G1–G4 + H1–H3 验收标准逐项命中。范围严格收敛在 plan 列举模块内,§4.5 OUT 五项(LLM 生成 lessons、纪律×信号整合视图、用户手动记忆 CRUD、真开仓时刻补录、定时推送)**均未实现**(已亲验),无 plan 之外的多余功能。剩余 2% 为下文一条 🟡（malformed week → 500）+ 若干 🔵 打磨/清理,均不影响收口。
- **整体代码质量:高**。分层清晰(review/ 纯函数可注入,零 LLM),两条最高危施工——**数据迁移**与**教练大脑防串味**——都做了正确的工程姿势(迁移 try/except 只 log 不 re-raise + 幂等探测精确集合;两串严格分流 + guardrail 落 SYSTEM_PROMPT 正文),且**单测是真断言、非占位**。注释把"为什么"和踩过的坑写清,可维护性好。
- **主要亮点**:
  1. **首次真 migration 姿势教科书级**:`_ensure_trades_columns` 用 `PRAGMA table_info` 精确列名集合判断(非模糊匹配),整段 try/except 只 `log.error(exc_info=True)` 不 re-raise;挂在 `init_db`(lifespan 启动路径)`executescript` 之后、`commit` 之前。独立实跑三场景(全新连跑 3 次 / 旧库补列数据无损 / 半迁移库只补缺列)+ ALTER 真失败被吞,均通过。§5 部署前置(实测线上行数 + `cp .bak` 备份)已文档化,builder 诚实标注"本次未部署 ECS,留待部署阶段"。
  2. **教练大脑防串味是真隔离**:用**真 brain 函数 + 真 DB** 端到端追踪 `review_ref`("你上次…别再让同样的死法重演")→ 遍历传入 deepseek_fn 的 context 全部字段 + 拼出的 user prompt,**情绪串零泄漏**;`history_digest`(中性统计"近 N 笔:X 守线")正确进 prompt 的【历史纪律】节。`test_injection_decoupled_from_verdict_judgement` 断言注入前后 form/fund/news 判定素材字节一致(历史不改判定输入)。guardrail 措辞清晰有效(明确"不得据此改变 verdict 判定标准，一律只按当前这一笔客观判定，铁律仍 -5/+15/D4")。
  3. **close_position 原子性真验**:破线笔在**同一连接同一事务**内 `insert_memory`(conn 复用不自 commit）+ trades 写 + position 归档。独立构造"insert_memory 前强制抛异常"→ 断言 trades 行数不变 + position 仍 holding + memory 为 0，三者一并回滚。测的是**真会调 insert_memory 的破线路径**（pnl=-10%），非伪场景。
  4. **单一事实源纪律严守**:`_mechanical_comment` 全库仅 `score.py` 一处 def，G1 aggregate 与 G3 close_position 都 `from app.review.score import` 同一函数（grep + `inspect.getsource` 双证）；`-5.0/+15.0/D4/容差带` 常量段 git diff 零改动，`_compute_kept_flags` 函数体未动。
  5. **降级/契约保全到位**:`GET /review`/`/memory` 空库返诚实空态（discipline_rate=0、非满分）HTTP 200；`upsert_review_note` 用 SELECT-then-UPDATE/INSERT（reviews 无 UNIQUE(week)，全库无 `ON CONFLICT(week)`）；`closedTrades.name`=NULL 兜底回 code；`_coach_brain` 任何异常降级为 `('', None)` 不崩。

### 门禁亲验结果（全部真实跑通）

| 门禁 | 结果 |
|---|---|
| 后端 `python -m pytest` | **276 passed**，1 warning（urllib3 LibreSSL 无害）。阶段3 新增 49：test_review_score 19 / test_review_api 9 / test_review_migration 8 / test_review_brain 13。基线 227→276，与 builder 自述一致。 |
| iOS build（LinoJ-iPhone16Pro） | **BUILD SUCCEEDED** |
| macOS build | **BUILD SUCCEEDED** |
| client 测试方法计数 | **40**（ReviewMemoryTests 新增 8 + 基线 32：AppModel 6 / CandidatesAnalysis 11 / SnapshotRender 4 / SignatureFormula 11），与 builder 自述 32→40 一致。断言有意义（disciplineRate=67 / rateTrend=-33 / KPI 接真值 / coachReviewRef 回退清空 / tag·kind 映射含 unknown→nil），非空测试。 |
| 迁移三场景独立实跑 | 全新库连跑 init_db 3 次不抛 duplicate、旧库补列 pnl 无损 name=NULL、半迁移库只补 note 不重复——**全过**。 |
| ALTER 失败态独立实跑 | 构造 execute 对 ALTER 抛异常 → `_ensure_trades_columns` 吞掉不 re-raise（log.error 落痕），init_db 路径不掀翻——**通过**。 |
| close_position 原子回滚独立实跑 | insert_memory 抛异常 → trades/position/memory 全回滚——**通过**。 |
| 防串味端到端独立实跑 | 真 brain 函数产的 review_ref 情绪串零泄漏进 prompt/context；history_digest 已进——**通过**。 |
| ISO 周边界独立验算 | `prev_week("2026-W01")=="2025-W52"`、`prev_week("2026-W27")=="2026-W26"`、跨 53 周年 `prev_week("2021-W01")=="2020-W53"`——**全对**（用 `date.fromisocalendar` + "周一−1 天再 isocalendar"，无对周号算术减一）。 |

---

## 🔴 致命问题（必须修复）

**无。** 无契约漂移、无解码失败风险、无鉴权缺口、无数据迁移崩溃/丢数据路径、无防串味泄漏、无密钥泄漏。

逐项核实结论：
- **①trades 无 status 残留**：✅ grep 全仓 `WHERE status` / `FROM trades ... status` 均无——所有 `status='holding'/'closed'` 都在 `positions` 表；`list_closed_trades` 直读全表；`test_list_closed_trades_no_status_filter_in_sql` grep 断言防回归。
- **②迁移彻底**：✅ 精确集合探测 + try/except 只 log + 幂等 + 挂 lifespan；代码无死循环/递归风险（单次 for 两列）。§5 部署前置文档化，未触碰生产 ECS。
- **③reviews upsert**：✅ SELECT-then-UPDATE/INSERT，无 `ON CONFLICT(week)`。
- **④ISO 周**：✅ 见上表，跨年正确。
- **⑤防串味**：✅ review_ref 全程不进任何传 LLM 字段（真函数端到端验），guardrail 落正文。
- **⑥短评单一源 / ⑦原子性 / ⑧前端契约 / ⑨不可触碰契约 / ⑩OUT 边界**：✅ 全部符合（见亮点 3/4 + 下方核实）。

---

## 🟡 重要问题（应该修复）

### 1. [backend/app/api/app.py:469,489 → app/review/score.py:64,46] malformed `week` 参数 → HTTP 500（客户端可触发的未捕获异常）

`GET /review?week=<非法>` 与 `POST /review/{week}/note`（week 是**路径参数**）传入非 ISO 周格式时，`aggregate_week` 内 `_split_week`（`week.split("-W")` 解包）或 `date.fromisocalendar`（周号越界）抛 `ValueError`，端点未捕获 → **FastAPI 返 HTTP 500**。独立实跑复现：
```
GET  /review?week=garbage    → 500
GET  /review?week=2026-W99   → 500
POST /review/garbage/note    → 500
POST /review/2026-W88/note   → 500
```
- **影响**：违反 plan 降级铁律"全链路不崩"精神，客户端 curl 拼错 week / 未来客户端会拿到不透明 500（而非 400/422）。**非安全问题**（鉴权门后、单用户），**当前 iOS/macOS App 不触发**（前端只发后端产出的合法 ISO 周：`fetchReview(week:)` 缺省不带 week 走本周，`saveReviewNote` 的 week 取自 `review?.week`）。故实际风险低，但属客户端可达端点的输入健壮性缺口。
- **修复建议**：在两端点入口校验 week 格式（正则 `^\d{4}-W\d{2}$` + 周号 1–53），非法则 `raise HTTPException(422, {...})`；或在 `aggregate_week` 外包一层 try/except ValueError → 400。改动 1 文件（app.py），不动契约。

---

## 🔵 建议改进（可以考虑）

### 1. [backend/app/api/app.py:52,62 vs app/review/score.py:189] 周末/节假日开仓的 openHoldings.tradeDay 可能为 0
`_current_trade_date` 周末录入取 `next_trading_day`（未来日期，D5 修复的正确行为）；而 `aggregate_week` 的 `openHoldings[].tradeDay = count_holding_trade_days(buy_date, today)`——若 buy_date 在未来（周末刚录、还没到那个交易日），闭区间 `[buy_date, today]` 交易日数会算成 0。这是 D5 buy_date 落点与"当下"错位的既有副作用（CLAUDE.md 已记 D5 副作用坑），非阶段3 引入；展示"D0"轻微怪但不误导（很快自愈）。可在复盘展示侧对 tradeDay<1 显示"D1（待开盘）"之类。不阻断。

### 2. [backend/app/review/score.py:195,201] test grep 守卫 `status=` 子串过宽
`test_list_closed_trades_no_status_filter_in_sql` 检查 `"status="` 等子串——若未来该函数正当出现 `status='holding'` 也会误报。当前函数无任何 status 引用故通过；作为纯防回归守卫可接受，但子串匹配比 AST 检查脆。可忽略。

### 3. [backend/app/db/store.py:462] `insert_review` 遗留函数
阶段3 端点已改用 `upsert_review_note`；`insert_review` 仅 `test_db.py:142` 引用、无生产调用点。非阶段3 引入（阶段0 建），属既有遗留死码，清理可留 cleaner。不影响功能。

### 4. [PROJECT_PLAN.md §3 门禁数字] 待收口时更新
§3"门禁数字"仍写"227 全绿 / 32 全绿 / 阶段3 待规划"，收口时应更新为 276 / 40 + 阶段3 已完工。属 cleaner 收口动作，非 builder 缺陷。

---

## 逐项核实（重点审查项对照）

| # | 审查项 | 结论 |
|---|---|---|
| 1 | trades 无 status 残留 | ✅ grep 无 `WHERE status` on trades；全在 positions |
| 2 | trades 迁移（探测精确集合 / try-except 不 re-raise / 幂等 / 挂 lifespan / 无死循环 / §5 部署前置 / 未碰生产） | ✅ 全部满足，四场景独立实跑通过，builder 诚实声明未部署 |
| 3 | reviews upsert 避开不存在的 UNIQUE | ✅ SELECT-then-UPDATE/INSERT，无 ON CONFLICT(week) |
| 4 | ISO 周边界 prev_week | ✅ 独立验算 2026-W01→2025-W52、跨 53 周年正确 |
| 5 | 防串味真隔离（review_ref 数据流 / guardrail 措辞 / 冒烟等价验证） | ✅ 真函数端到端零泄漏；guardrail 清晰有效；无 token 时以代码审 + 现有测试覆盖该场景 |
| 6 | 短评模板单一事实源 | ✅ 仅 score.py 一处 def，G1/G3 同源 import（双证） |
| 7 | insert_memory 原子性（前强制抛异常验回滚，测真场景） | ✅ 破线路径真回滚，非伪测试 |
| 8 | 前端 Review.openHoldings/sampleNote + OpenHolding | ✅ 字段/类型逐字段对齐后端 JSON |
| 9 | 不可触碰契约（常量/止损止盈/D4/计数语义/_compute_kept_flags/现有端点） | ✅ git diff 常量零改动，coach 仅新增可选 review_ref，analyze 响应结构零改 |
| 10 | §4.5 OUT 五项未越界 | ✅ lessons 空串、无用户记忆 CRUD、无定时推送、无整合视图、无真开仓时刻补录 |
| 11 | H3 composer↔coach 偏离说明属实合理 | ✅ 属实（见下） |

### 关于 H3 偏离（composer↔coach 真问答）

builder 自述"H3 后端 question 透传已接，客户端 sendComposer 仍走本地固定文案"——**核实属实**：
- 后端链路已通：`coach_position` 收 `body.question`（app.py:381,413）→ `analyze_stock(question=)` → `build_user_prompt` 输出【我的问题】节（prompt.py:88-89）。
- 客户端 `coachPosition(id:question:)` 形参存在（APIClient:345），但 `runCoach` 调用恒传 nil（AppModel:396），`sendComposer`（AppModel:416-422）append **硬编固定文案**、不打后端。
- **合理性判断**：plan §4.4 H3 **正式验收（line 194）只列 4 项**（review_ref 引用块显示/无历史消失/双端 build/端到端联调），composer 真问答**不在 H3 验收清单**内；它是 §4.4 G4（line 178）/§5 backlog（line 253）的"顺手一并接上"的**期望性描述**，非硬验收项。故属**可接受的范围收敛**（H3 核心——reviewQuotePlaceholder 换真实 review_ref 引用块——已完整落地，占位彻底移除）。建议在收口变更日志"偏离说明"里显式记一行，并把 composer 真问答留 backlog（阶段4 打磨），避免语义悬空。

---

## 结论

**零致命、一个 🟡（malformed week → 500，客户端当前不触发、非安全问题、修复 1 文件）、四个 🔵（均为打磨/清理/文档，不阻断）。**

两处最高危施工——**首次真数据迁移**与**教练大脑防串味**——经独立构造场景实跑，均**姿势正确、隔离到位、单测真实**，未发现设计层或实现层缺陷。契约零漂移、OUT 边界严守、单一事实源纪律保持。

**可以收口**（🟡#1 建议随手修掉再收，或作为已知 backlog 带走；两者皆可，不阻断发布）。收口时请：① 更新 §3 门禁数字（276/40）；② 变更日志记 H3 composer 偏离说明 + 🟡#1 处置；③ 部署 ECS 前**务必执行 §5 阶段3 部署前置**（实测线上 trades 行数 + `cp linon.db .bak` 备份）——这是首次真 migration，虽设计假设空仓、但 plan 已明确"别盲信空仓假设"。
