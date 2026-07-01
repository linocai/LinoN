# 阶段3 全文归档:复盘闭环(纪律打分 + 复盘/记忆双端 + 教练接复盘历史)

> 从 PROJECT_PLAN.md 收口移出的完整 Plan(含 Phase 拆分与实施记录/plan-critic 修订记录)。审查报告见 `archive/REVIEW_REPORT_阶段3.md`。

## 4. 当前版本 Plan —— 阶段 3:复盘闭环(纪律打分 + 复盘/记忆双端 + 教练接复盘历史)

> **定位**:把"用户有没有守规则"的行为数据从沉睡的 `trades`/`reviews`/`memory` 表里**读出来、算出分、给用户看见**。核心价值 = 让用户**看见自己的行为模式**(纪律执行率、破线明细、每笔守没守线),从而下次自己纠正——**系统不替用户决策**(§1 四角色不变,扳机永远用户扣)。
>
> **与阶段2.5 的分界(不混为一谈)**:阶段2.5 回测「**系统选股准不准**」(信号有效性,`candidate_outcomes`);阶段3 打分「**用户有没有守规则**」(纪律执行,`trades.kept_*`)。两者底层统计各自独立,**本阶段不重建阶段2.5 的信号回测**;展示层的整合(周报里同时报"你的纪律率"+"系统选股这周准不准")列为 OUT(见 §4.5),留未来版本。
>
> **不重新发明纪律判定**:`trades` 表在清仓时已机械算好 `kept_stop/kept_take/kept_time/pnl/broke_rule`(容差带 [-6%,-4%] / 止盈 +15% / D4,`store._compute_kept_flags`)。阶段3 的"打分"= **对这些既有布尔字段做周期聚合统计**,不改任何判定口径、不动 `store.py` 常量。
>
> **全期铁律(不可触碰)**:① `-5.0/+15.0/D4/容差带` 仍只在 `store.py` 顶部,新逻辑禁止另起一份;② 止损止盈比例、D4 强平语义、持仓交易日计数(D1 起算)、`_compute_kept_flags` 的守线判定**均不触碰**;③ 降级铁律:无 DeepSeek key / 无历史数据 → 复盘/教练大脑优雅降级(空周报、无历史引用),守住"全链路不崩";④ 不新建 `reviews`/`memory` 之外的复盘表(两表阶段0 DDL 已建、从未写入,阶段3 首次真读写);⑤ **系统不替用户决策**——复盘只呈现事实与模式,不产生"该买/该卖"的自动指令。

### 4.0 技术选型(本阶段定死,不留给施工)

| 维度 | 决定 |
|---|---|
| 打分数据源 | **唯一读 `trades` 表既有 `kept_stop/kept_take/kept_time/pnl/broke_rule`** + 同时读未平 `positions`(§5 用户流程坑清单:扛过周末的套牢票只在 positions 不在 trades,复盘必须一并看见)。**不重算守线判定**,聚合 `store._compute_kept_flags` 已落库的结果。**⚠️ 致命订正(builder 必读)**:`trades` 表**无 `status` 列**(实测 `PRAGMA table_info(trades)` 列集 = `id/code/open_price/close_price/open_time/close_time/kept_stop/kept_take/kept_time/pnl/broke_rule/created_at`)——每一行**本身就是一笔已闭合交易**(`close_position` 落库时写入),不存在"未闭合的 trades 行"。`status='closed'` 是 `positions` 表的概念,**读 trades 禁止 `WHERE status='closed'`**(会抛 `no such column` 直接挂掉 G1)。`list_closed_trades` = **直接读 trades 全表**,可选按 `close_time` 的 since/until 过滤 |
| 打分算法(定死,纯确定性、非 LLM) | **纪律执行率 `discipline_rate` = round(未破纪律笔数 / 总闭合笔数 × 100)**(`broke_rule==0` 的笔数占比);**score(0–100)= discipline_rate**(本阶段一比一,不引入额外惩罚项,避免过度设计;`Review.score` 与 `disciplineRate` 同值)。空周(0 笔闭合)→ `discipline_rate=0`、`score=0`、`redFlags=[]`、`trades=[]`(诚实空态,不是满分) |
| 打分维度(每笔标红依据,定死) | 一笔 `broke_rule==1` 即入 `redFlags`;红旗文案由**机械模板**生成(`跌穿止损未走` if not kept_stop and pnl<-6;`持过 D4 未清` if not kept_time),不调 LLM。每笔在 `ReviewTrade` 上 `tag = broke_rule ? red : good`、`comment` = 机械模板短评(守线全绿→"守住铁律";破线→点破破了哪条) |
| 周口径 | **ISO 周(周一~周日)**,week 标识 `"YYYY-Www"`(如 `2026-W27`);一笔归属周 = 其 `close_time` 所在 ISO 周。趋势取**近 6 个 ISO 周**(`WeekPoint` 数组,无交易的周补 0)。**订正 reviewer 阶段1 🟡#3**:`trades.open_time` 目前仅 `buy_date` 日期粒度、`close_time` 是 `_now()` 时刻——归周用 `close_time`(已是时刻),持仓时长若展示则用 `close_time - open_time`(open_time 仅日期,时长粒度到天,**本阶段接受天粒度不阻塞**;真开仓时刻补录留 §4.5 OUT) |
| 复盘触发时机 | **on-demand 为主 + 端点实时聚合(不落表预计算)**:`GET /review?week=` 每次即时扫 `trades` 聚合返回,**不预写 `reviews` 表**;`reviews` 表仅在用户**主动确认/编辑 `nextWeekNote`(下周注意)** 时写一行(那是用户产出的、需持久化供教练大脑引用的东西,机械统计不落表避免陈旧)。**不新增定时任务**(EOD tick 已够忙、周界定时器易漏易重、内存紧;on-demand 端点足够,单用户低频访问) |
| `nextWeekNote` / 记忆持久化 | 用户在 ReviewView 编辑"下周注意" → `POST /review/{week}/note` 写 `reviews.next_week_note`;闭环结论/长期记忆/纪律里程碑 → 写 `memory` 表(`kind` ∈ 闭环结论/长期记忆/纪律里程碑,对齐 `MemoryKind`)。**记忆条目本阶段以"系统自动沉淀 + 用户可读"为主**:清仓落 `trades` 时若 `broke_rule` 顺手沉淀一条 milestone/conclusion(见 F3),用户主动写留 OUT |
| 教练大脑注入机制(定死) | **两条独立产物,严格分流,不混用**:① **`history_digest`(中性统计摘要)** → 注入 `/coach`+`/analyze` 的 DeepSeek prompt(如"近 5 笔:3 守线 / 2 破止损"),供 LLM 引用增说服力;② **`review_ref`(带情绪的第二人称文案,如"你上次追高硬扛那笔亏了 40%,也是没在 -5% 走")→ 只回给客户端 coach 卡展示,绝不进 LLM prompt**(带情绪强措辞进 context 会放大串味风险)。摘要均由**后端确定性拼**(不让 LLM 查库)。coach 卡的 `reviewQuotePlaceholder` 换成后端 `review_ref`。**guardrail 必须落到 `SYSTEM_PROMPT` 正文**——见 G4:增一节明确"【历史纪律】仅供 text/plan 引用,不得据此改 verdict 判定标准,verdict 一律只按当前这一笔的形态/资金/铁律客观判定"。**注入是"提供上下文"不是"改判定口径"**——铁律仍 -5/+15/D4 |
| 教练大脑数据 | ① `review_ref`(客户端展示)= 读 `trades` 里 `broke_rule==1` 的历史笔(按破止损 / 破时间分组)取最近 1–2 笔的 `code/pnl/破哪条` 拼第二人称一句话;**无历史破线笔 → `review_ref=None`**,coach 卡不显引用块(降级不硬造)。② `history_digest`(进 prompt)= 中性统计串(近 N 笔守/破计数),**无历史 → 空串**,DeepSeek 照常判。无 `trades` 数据(上线即空仓)→ 两者皆空,合法 |
| 前端契约来源 | `Models.swift` 的 `Review`/`WeekPoint`/`ReviewTrade`/`ReviewTag`/`MemoryItem`/`MemoryKind` **已定死**(设计稿钉),后端按此逐字段供 JSON;`TradeRecord` 有 `name`/`note` 两列后端 `trades` 表**未建**(阶段0 偏离记录),本阶段回补:`trades` 加 `name`/`note` 列(见 4.2 DDL 变更) |
| LLM 用量 | 打分/红旗/趋势/记忆沉淀**全部确定性代码**,零 LLM 调用;**仅教练大脑注入**用到 DeepSeek(且是复用现有 `/coach`/`/analyze` 调用,不新增调用点)。省钱、可测、不联网可跑 |

### 4.1 打分口径(定死,builder 照此实现,不自由发挥)

给定一个 ISO 周 `week`,读该周 `close_time` 落在其内的所有 `trades` 行:

1. **总闭合笔数** `n = len(trades_in_week)`。
2. **未破纪律笔数** `kept = count(broke_rule == 0)`。
3. **纪律执行率** `discipline_rate = round(kept / n * 100)`(n==0 → 0)。
4. **score = discipline_rate**(0–100,本阶段一比一)。
5. **环比 `rateTrend`** = 本周 discipline_rate − 上一 ISO 周 discipline_rate(上周无数据 → 0)。
6. **redFlags**(字符串数组):对每笔 `broke_rule==1`,按机械模板生成一条,如 `"沪电股份 破止损:-8.2% 未在 -5% 走"` / `"工业富联 破时间:持过 D4 未清"`。
7. **每笔 `ReviewTrade`**:`name/code`、`pnl`(展示串,如 `"+6.4%"`)、`tag`(`broke_rule?red:good`)、`comment`(机械短评)。
8. **trend**(近 6 ISO 周 `WeekPoint`):`label`(如 `"W25"`)+ `value`(该周 discipline_rate,无交易补 0)。
9. **未平持仓并读**:响应带 `openHoldings`(未平 `positions` 的精简列表:name/code/买入价/持仓天数),让复盘看得见扛单;**这些不计入本周 discipline_rate**(未闭合无守线结论),仅提示"还有 N 只在持"。

### 4.2 DDL 变更(权威,builder 严格照建;两表已存在,仅补列)

- **`trades` 表补两列 —— 项目首次真 migration,高危区,契约钉死(builder 严格照此,不自由发挥)**:回补阶段0 偏离,对齐 `Models.swift` `TradeRecord` 的 `name`/`note`。**(a) 探测逻辑硬编精确集合**(不做模糊匹配):
  ```python
  def _ensure_trades_columns(conn):
      existing = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}  # row[1] = 列名
      for col in ("name", "note"):
          if col not in existing:
              conn.execute(f"ALTER TABLE trades ADD COLUMN {col} TEXT")
  ```
  (SQLite 无 `ADD COLUMN IF NOT EXISTS`,故靠 `PRAGMA table_info` 探测。)
  **(b) migration 不能拖垮 init_db**:`_ensure_trades_columns` 整段 **try/except 包裹,ALTER 意外失败只 `log.error` 不 re-raise**(对齐"降级不崩"铁律)。理由:name/note 只是展示补列,缺了 G1 打分照跑(打分只读 `kept_*`/`broke_rule`/`pnl`/`close_time`);而 `init_db` 跑在 `app.py` lifespan 里、每次 ECS 重启都执行——**若迁移抛异常会让整个服务(监控/持仓/推送)起不来**,绝不允许一个展示列拖垮 startup。`init_db` 在 `executescript(_SCHEMA)` 建表之后调 `_ensure_trades_columns(conn)`,再 commit。
  **(c) 幂等硬断言(G3 验收)**:见 G3。**(d) 部署前置**:见 §5 用户侧收尾「阶段3 部署前置」。
  `close_position` 写 trades 时**顺手带 `name`(从 position 取)+ `note`(机械短评 `_mechanical_comment`)**。历史行 name/note 为 NULL(设计假设上线空仓无历史行——但**部署前须实测线上真实行数**,见 §5,别盲信空仓假设)。
- **`reviews` 表**:DDL 已足(§0.4),本阶段首次写入。**⚠️ 重要订正**:reviews 表**无 `UNIQUE(week)` 约束**(只有 id 主键),故 `upsert_review_note` **不能用 `ON CONFLICT(week) DO UPDATE`**(无冲突目标会报错)。实现为 **`SELECT id FROM reviews WHERE week=? → 有则 UPDATE、无则 INSERT`**(单用户无并发,可接受非原子;**不给 reviews 表另加 UNIQUE 约束**——SQLite 加约束要建新表搬数据、风险更大不值得)。**注**:`reviews.discipline_rate` 列存的是用户确认那一刻的快照(供历史留痕),端点返回的 `disciplineRate` 始终实时算。
- **`memory` 表**:DDL 已足。`close_position` 落 trades 时若 `broke_rule==1`,顺手 `insert_memory(kind='闭环结论', content=机械短评)` 沉淀一条(供教练大脑引用 + MemoryView 展示)。**去重/累积说明**:`insert_memory` 纯 INSERT 无去重——但**同一 position 只会 close 一次**(`close_position` 对非 holding 抛 ValueError),故"同一笔重复沉淀"不会发生;memory 无清理机制但破线低频、单用户可接受(**手动清理留 §4.5 OUT,不做**);`GET /memory` 加 `LIMIT 200`(最近 200 条)防未来极端累积。

### 4.3 接口契约(本版本对外新增/变更)

| 端点 | 方法 | 鉴权 | 说明 | 客户端 |
|---|---|---|---|---|
| `/review` | GET | Bearer | 实时聚合某 ISO 周复盘(缺 `week` 参数→本周)。返回 `Review` 形状 + `openHoldings` + `nextWeekNote`(读 reviews 表已存的) | ReviewView |
| `/review/{week}/note` | POST | Bearer | 写/覆盖某周 `nextWeekNote`(upsert reviews 表)。body `{note}` | ReviewView 下周注意保存 |
| `/memory` | GET | Bearer | 列 `memory` 表所有条目(倒序)+ 已平仓 `trades` 流水(供 MemoryView 历史区) | MemoryView |
| `/positions/{id}/coach` | POST | Bearer | **变更**:响应**新增可选字段 `review_ref: str?`**(教练大脑历史引用,无则省略);`advice/reason/analysis/fund_asof` **契约不变** | AnalysisView coach 卡换掉占位 |
| `/candidates/{code}/analyze` | POST | Bearer | **不变**(analyze 也可注入历史摘要进 prompt,但**响应结构零改动**——历史仅影响 DeepSeek text,不新增字段) | 无客户端改动 |

`GET /review` 响应形状(camelCase,逐字段对齐 `Models.swift` `Review`):
```
{ "week": "2026-W27",
  "score": 80, "disciplineRate": 80, "rateTrend": 5,
  "redFlags": ["沪电股份 破止损:-8.2% 未在 -5% 走"],
  "lessons": "",                         // 本阶段留空串(LLM 生成 lessons 属 OUT)
  "nextWeekNote": "reviews 表已存的用户注 or 空串",
  "trend": [{"label":"W22","value":100}, ..., {"label":"W27","value":80}],
  "trades": [{"name":"沪电股份","code":"002463","pnl":"-8.2%","tag":"red","comment":"破止损:跌穿 -5% 未走"}],
  "openHoldings": [{"name":"工业富联","code":"601138","buyPrice":18.3,"tradeDay":2}],
  "sampleNote": "本周 0 笔闭合" }     // 空周诚实标注
```
`GET /memory` 响应:
```
{ "items": [{"kind":"闭环结论","content":"...","date":"2026-06-30"}, ...],
  "closedTrades": [{"name":..,"code":..,"pnl":"+6.4%","keptStop":true,"keptTake":false,"keptTime":true,"brokeRule":false,"note":"..","date":"2026-06-30"}, ...] }
```

### 4.4 Phase 拆分(后端 G → 前端 H;依赖:G1→G2→G3→G4,H1/H2 依赖 G,H3 依赖 G4)

**Phase G1 · 打分聚合核心(后端)**
- 新建 `app/review/score.py`(新包 `app/review/`):
  - `iso_week(dt)→"YYYY-Www"`(用 `dt.isocalendar()` 的 (year, week));
  - `week_bounds(week)→(start,end)`:**用 `date.fromisocalendar(year, week, 1)` 算周一**,周日 = 周一 + 6 天;
  - `prev_week(week)→"YYYY-Www"`:**一律 = 当前周周一 − 1 天,再取 `isocalendar()`**——**禁止对周号做算术减一**(`W01-1` 会算错跨年:`2026-W01` 的上一周是 `2025-W52`,不是 `2026-W00`);
  - `aggregate_week(week, *, trades_fn, holdings_fn)→ReviewDict`(读该周 trades 聚合出 §4.1 全部字段,含 redFlags 机械模板 / ReviewTrade / 近6周 trend / openHoldings)。**纯函数、可注入 `trades_fn`/`holdings_fn` 免联库**;红旗/短评文案用机械模板(**统一 import `_mechanical_comment(flags)`,与 G3 close_position 同源,见 §4.2 重要7**),**零 LLM**。
  - `openHoldings[].tradeDay` **复用 `count_holding_trade_days(buy_date, today)`**(与 coach/EOD 同源),不在 review 层另算持仓天数。
- `store.py`:加 `list_closed_trades(since=None, until=None)`(**直接读 trades 全表**——每行即一笔已闭合交易,**不加 `WHERE status='closed'`**;可选按 `close_time` 的 since/until 过滤,按 close_time 升序)、`list_all_trades()`(供趋势跨6周)。
- **验收**:① 造多周 trades 样例(含守线全绿 + 破止损 + 破时间)→ `aggregate_week` 算出正确 discipline_rate/score/redFlags/每笔 tag;② 空周 → discipline_rate=0/score=0/空数组/sampleNote 标注,**不返满分**;③ rateTrend 用上一 ISO 周,**具体断言 `prev_week("2026-W01") == "2025-W52"`**(2025 年 ISO 共 52 周)+ 一条同年内 `prev_week("2026-W27")=="2026-W26"`;④ trend 近6周无交易的周补 0;⑤ openHoldings 读未平 positions、tradeDay 用 `count_holding_trade_days`、**不计入 discipline_rate**;⑥ `list_closed_trades` 直读全表(无 status 过滤),SQL 不含 `status` 字样(grep 断言防回归)。新增 `test_review_score.py`。

**Phase G2 · 复盘 + 记忆端点(后端)**
- `store.py`:`upsert_review_note(week, note)`(**`SELECT id WHERE week=?` → 有则 UPDATE、无则 INSERT**——reviews 无 `UNIQUE(week)`,**禁用 `ON CONFLICT(week)`**;存 note + 当刻 discipline_rate 快照)、`get_review_note(week)`、`list_memory(limit=200)`(倒序)。
- `app.py`:`GET {API_PREFIX}/review`(鉴权,缺 week→本周;调 `aggregate_week` + 附 `nextWeekNote`);`POST {API_PREFIX}/review/{week}/note`(鉴权,写 note);`GET {API_PREFIX}/memory`(鉴权,列 memory + 已平仓 trades 流水)。**组装 `closedTrades` 时 `name` 为 NULL 兜底回 `code`**(存量历史行可能 name=NULL,别让 None 进 JSON)。新增 schemas:`ReviewOut`/`ReviewNoteIn`/`MemoryOut`。
- **验收**:① `GET /review` 无 week 返本周实时聚合;带 week 返历史周;② `POST /review/{week}/note` 用 SELECT-then-UPDATE/INSERT(**SQL 不含 `ON CONFLICT(week)`**,grep 断言),写入后 `GET` 能读回 nextWeekNote、二次覆盖同 week 不新增行;③ `GET /memory` 返 memory 条目 + closedTrades 守线徽章字段、name=NULL 的行兜底回 code;④ 缺 token 401;⑤ 空库(无 trades/memory)→ 各端点返空态不 500。端点测试入新增 `test_review_api.py`。

**Phase G3 · 清仓沉淀记忆 + trades 补列(后端·高危迁移)**
- `store.py`:`_SCHEMA` 保持;`init_db` 在 `executescript(_SCHEMA)` 之后调 `_ensure_trades_columns(conn)`(§4.2 (a) 探测逻辑硬编精确集合 + (b) try/except 只 log 不 re-raise)再 commit;**短评模板单一事实源**——定义 `_mechanical_comment(flags)`(收 `_compute_kept_flags` 返回的 dict,产"守住铁律"/"破止损:跌穿 -5% 未走"/"破时间:持过 D4 未清"文案),放一处(`app/review/score.py`),**G1 aggregate 与 G3 close_position 都 import 它,不各写一份**(项目"单一事实源"铁律延伸)。`close_position` 写 trades 时带 `name`(从 position)+ `note`(`_mechanical_comment` 生成);`broke_rule==1` 时**在 `close_position` 的同一个连接/同一事务内**调 `insert_memory(kind='闭环结论', content=短评)`(**不 commit 后再开新连接**——保持原子:trades 写 + memory 写要么都成要么都不成;为此 `insert_memory` 需支持传入现有 conn 复用,或 close_position 内联 INSERT memory 后统一 commit)。
- **验收**:① **幂等硬断言**:连跑 `init_db` **两次/三次**(模拟服务反复重启)**不抛 `duplicate column`、不丢已有 trades 行、不改已有列值**;② 旧库(无 name/note 列)跑 `init_db` 自动补列、数据无损;③ 清仓破线笔 → trades.name/note 落库 + memory 表新增一条闭环结论,**且二者在同一事务**(可用"insert_memory 前强制抛异常"验 trades 也一并回滚,证明原子);④ 清仓守线笔 → 不沉淀 memory(只有破线才沉淀,避免噪声);⑤ `close_position` 返回值/既有契约不变(仅内部多写字段);⑥ `_mechanical_comment` 只定义一处(grep 断言 G1/G3 都 import 同一函数,无第二份文案)。回归 `test_db.py` + 新增用例。

**Phase G4 · 教练大脑注入(后端)**
- 新建 `app/review/brain.py`:
  - `build_review_ref(code, *, trades_fn)→Optional[str]`(**客户端展示用**,带情绪第二人称;读 `trades` 里 `broke_rule==1` 的历史笔按破止损/破时间分组取最近 1–2 笔拼"你上次 {code2} 也是 {破哪条} 亏了 {pnl}%";无破线历史→None)。**此串绝不进 LLM prompt**。
  - `build_history_digest(*, trades_fn)→str`(**进 prompt 用**,中性统计;如"近 5 笔:3 守线 / 2 破止损";无历史→空串)。
- `app/llm/prompt.py`:① **`SYSTEM_PROMPT` 增一节 guardrail(必须落正文)**——"若 user 消息含【历史纪律】一节,仅供你在 text/plan 里引用以增强说服力;**不得据此改变 verdict 判定标准**,verdict 一律只按当前这一笔的形态/资金/铁律客观判定";② `build_user_prompt` 的 context 支持可选 `history_digest`——**仅当非空**时在 user 消息加一节【历史纪律】(内容是中性 digest,**不是 review_ref**)。
- `app.py`:`coach_position` 调 `build_review_ref(code)` 填响应 `review_ref`(可选,客户端展示)+ 把 `build_history_digest()` 经 `analyze_stock` 编排注入 prompt context;`analyze_stock` 同样注入 `history_digest`(不改响应结构)。降级:无历史 → `review_ref` 省略、`history_digest` 空串(prompt 不加【历史纪律】节),DeepSeek 照常判。**顺手接 coach `question` 透传**(消化 reviewer 阶段2 🔵#5:`coach_position` 已收 `body.question`、`analyze_stock` 已有 `question` 形参,端点已透传;客户端 `coachPosition(id:question:)` 恒传 nil 的接线在 H3 一并接上 composer)。
- **验收**:① 造历史破止损 trades → `build_review_ref` 返正确第二人称一句话;无破线历史 → None;② coach 响应带/不带 `review_ref` 两态正确,`advice/reason/analysis/fund_asof` 契约不回归;③ prompt 注入 history_digest 后 DeepSeek 仍返合法 DeepAnalysis;**用假 deepseek_fn 断言:进 prompt 的 context 含 `history_digest`(中性串)、且 `review_ref`(情绪串)不出现在传给 deepseek_fn 的任何字段里**(两路径分流);④ **解耦断言**:同一票在"注入 history_digest"与"不注入"两种 context 下,mock deepseek_fn 收到的 verdict 判定输入不因历史而系统性变保守(验证"注入上下文"与"verdict 判定"两条路径解耦);⑤ 无历史/无 DeepSeek key → 全链路降级不崩。新增 `test_review_brain.py` + coach 端点回归。

**Phase H1 · ReviewView(前端·双端)**
- **先补 `Models.swift` 契约字段**:`Review` 结构体现**缺** `openHoldings`/`sampleNote`(只有 week/score/redFlags/disciplineRate/rateTrend/lessons/nextWeekNote/trend/trades),H1 要显示这两样 → 给 `Review` 加 `openHoldings: [OpenHolding]` + `sampleNote: String`,并新定义 `struct OpenHolding: Codable { name, code, buyPrice: Double, tradeDay: Int }`(逐字段对齐 §4.3 `openHoldings` JSON)。**改 `Models.swift` 属改契约,记变更日志**。
- 新建 `Views/ReviewView.swift`:评分 Hero(绿蓝渐变卡:大 score + disciplineRate + 本周交易/盈利/标红三联)+ 趋势柱状(近6周,最后周高亮,Y 轴 min-7~max+2 归一,柱顶标值)+ 每笔点评卡(good 绿 chip / red 红 chip + pnl + comment)+ 下周注意(琥珀渐变卡,可编辑 → `POST /review/{week}/note`)+ **未平持仓提示区**(openHoldings)。空周态诚实展示 sampleNote。iOS 大标题 ScrollView / macOS 内容区,照 README §4。
- `APIClient`:`fetchReview(week:)`/`saveReviewNote(week:note:)`;`AppModel`:`review` 状态 + `loadReview()`/`saveNote()`;RootView 替换 `reviewPlaceholder` 接真视图,macOS 侧栏"待"badge 逻辑接实际(有本周破线→红点)。
- **验收**:① 双端 `BUILD SUCCEEDED`;② 造后端样例(种 trades)→ ReviewView 渲染评分/趋势/每笔;③ 下周注意编辑保存回读;④ 空周态不崩、显 sampleNote;⑤ 绿涨红跌 + Liquid Glass 克制守恒。ImageRenderer 离屏快照核对(Dock 守卫退路,同阶段2)。

**Phase H2 · MemoryView(前端·双端)**
- 新建 `Views/MemoryView.swift`:结论卡网格(macOS 三列 / iOS 单列,kind chip 蓝/琥珀/绿 + 正文 + 状态行)+ 历史流水(已平仓 trades:股票/pnl/守线徽章〔止损·止盈·时间,守=绿/破=红删除线〕/note/date)。照 README §5。
- `APIClient`:`fetchMemory()`;`AppModel`:`memory`/`archived` 状态 + `loadMemory()`;RootView 替换 `memoryPlaceholder`。
- **验收**:① 双端 `BUILD SUCCEEDED`;② 造 memory + closedTrades → 网格 + 流水正确渲染;③ 守线徽章守/破着色 + 删除线正确;④ 空态(无记忆/无流水)友好占位。ImageRenderer 快照核对。

**Phase H3 · coach 卡接复盘历史(前端·全栈联调)**
- `AnalysisView.swift`:`reviewQuotePlaceholder` 换成消费后端 `review_ref` 的真实引用块(有 `review_ref`→显历史教训 + clock 图标；无→**整块不显**,不再显"阶段3 接入"占位);`AppModel` coach 流程解析 `review_ref` 填入。
- **验收**:① coach 有历史破线 → 卡内显真实教训引用;② 无历史 → 引用块消失(非占位);③ 双端 build + 快照核对;④ 与 G4 端到端联调(本地 uvicorn 种破线 trades → coach 拿到 review_ref)。

### 4.5 本版本明确不做(OUT — 留未来版本,防范围蔓延)

- **LLM 生成 `lessons`/周复盘小结**:`Review.lessons` 本阶段留空串。让 DeepSeek 写"本周经验总结"是额外 LLM 编排 + 成本 + 可测性负担,且非核心价值(核心是"看见数字",不是"读 AI 作文")。留 V2。
- **纪律回测 × 信号回测整合视图**:阶段2.5 的 `candidate_outcomes`(系统选股准不准)与阶段3 `trades.kept_*`(用户守没守规则)**不在本阶段做整合周报**。底层各自独立已足;整合展示留未来。
- **用户主动写长期记忆/自定义记忆条目**:本阶段 memory 以系统自动沉淀(破线闭环结论)为主 + 只读展示;用户手动增删改记忆条目留 V2。
- **真开仓时刻补录**(reviewer 阶段1 🟡#3):`trades.open_time` 仍日期粒度,持仓时长展示到天粒度即可,本阶段不改录入链路补真时刻。留后续。
- **定时任务/周界自动推送周复盘**:本阶段复盘 on-demand,不加"每周日推送本周复盘"的定时器(EOD tick 已够忙、内存紧、单用户低频)。留 V2 视需要。
- **破纪律的实时盘中告警升级**(区别于阶段1 硬线):阶段1 已有硬线升级;阶段3 复盘是事后聚合,不新增盘中告警。
- **教练大脑改判定口径**:历史注入仅"增说服力",铁律 -5/+15/D4 不因历史松动;不做"因为你老破线所以这次强制清仓"这类自动决策(违反§1 人扣扳机)。

**本阶段归档指针**:阶段2.5 全文已归档 `archive/stage2.5_选股数据质量_plan.md`,审查报告 `archive/REVIEW_REPORT_阶段2.5.md`。阶段3 收口时本节全文移入 `archive/stage3_复盘闭环_plan.md`,主文件本节清回占位。

