# LinoN 阶段2(选股 + 决策)Plan 全文 + 实施记录(归档)

> 版本收口归档(2026-06-23)。本文件 = 阶段2 生效 Plan 全文 + 实施记录 + 审查结论指针。
> 主 `PROJECT_PLAN.md` §4 已清回占位待阶段3;§4b 客户端契约跨阶段保留主文件。
> 审查全文见 `archive/REVIEW_REPORT_阶段2.md`(零致命/零重要/6 建议,达可收口标准)。

---

## 阶段 2:选股 + 决策(Plan 全文)

> 后端三段式选股(粗筛 → 排序截断 → on-demand 深判)+ DeepSeek 决策层 + 中间地带 B;前端 CandidatesView + AnalysisView + 满仓闭门联动。**铁律:技术面/选股不定死阈值,交给 LLM 判;只有真二元项(黑名单、高位线 ≥100%/≥50%、截断 5×空仓位)写硬规则;粗筛宽区间给"宁松勿紧"经验默认值,可复盘迭代,不卡死生死。**

### 4.0 技术选型(定死)

| 维度 | 决定 |
|---|---|
| 全市场扫描 | Tushare `daily_basic`(按 `trade_date` **一次返回全市场** ~5400 行)+ `moneyflow`(同理)拉当日 EOD + `stock_basic`(全市场代码→`industry` 行业映射,进程内缓存、启动/EOD 拉一次,供白酒/酿酒行业黑名单),pandas 内存粗筛+排序。**不落原始全市场数据**(内存紧);只把**当日候选结果**落 `candidates` 缓存表(按 `trade_date`) |
| 候选刷新触发 | EOD 收盘后(`>=15:35`,等 Tushare 当日数据稳定)算一次当日候选,落 `candidates` 表;`GET /candidates` 读缓存表,不每次重算。手动 `POST /candidates/refresh`(鉴权)可强制重算 |
| 形态数据 | 粗筛形态用 `daily_basic` 的涨跌幅/换手 + `daily` 近 N 日批量(全市场 `daily` 按 trade_date 单次拉,内存算"创 N 日新高/放量倍数/站均线");深判时按需补单票 `ts_daily(code, 近 60 交易日)` 给 LLM |
| DeepSeek 接入 | `https://api.deepseek.com/v1/chat/completions`(OpenAI 兼容),model `deepseek-chat`,**`response_format={"type":"json_object"}`** 强制结构化;system prompt 武装 v2 §6 方法论;`httpx` 同步调用,超时 30s |
| 结构化输出保证 | system prompt 内嵌 `DeepAnalysis` JSON schema 样例 + 字段枚举约束;解析后**服务端校验+夹紧**(tone∈{good,warn,bad,neutral}/verdict∈{可进,观望,不进});解析失败/超时 → 降级返回 `verdict=观望` + 各轴 `tone=neutral` 占位文案,**绝不抛崩** |
| 舆情(消息面) | best-effort 抓东财股吧标题页(免费),低频、仅对选中候选;超时 4s;失败/无数据 → news 轴 `tone=neutral` 文案"未获取到舆情,仅技术+资金判定";**绝不阻塞深判**。板块资金流(5000 积分)不升档,题材热度用免费板块涨幅占位 |
| 资金时序口径 | `moneyflow` 为 EOD;候选与深判的资金面**一律截至昨日 EOD**;深判响应**显式标注**"资金面=截至上一交易日 EOD,今日盘中资金未知" |
| 无 token 降级 | 缺 `TUSHARE_TOKEN` → `GET /candidates` 返回空列表 + `degraded:true` + reason;缺 `DEEPSEEK_API_KEY` → 深判返回降级占位卡。两者皆不崩(沿用阶段0/1 降级契约) |

**新增 `.env` 键**(用户写入 ECS;键已在 `settings.py` 预留):`TUSHARE_TOKEN`、`DEEPSEEK_API_KEY`。无新增基建键。

### 4.1 钉死的选股规则(单一事实源,常量入 `app/screen/rules.py` 顶部)

- **黑名单硬排除**(二元):代码 `300*`/`688*`/`8*`/`4*`(创业板/科创/北交)、名称含 `ST`/`*ST`、**行业属白酒/酿酒**(用 Tushare `stock_basic` 的 `industry` 字段精确归类,进程内缓存全市场代码→行业映射,启动/EOD 拉一次;比名称关键词覆盖更全——Review 拍板)。
- **高位排除**(二元):`pct_60d`(近 60 交易日累计涨幅)`≥100% → 排除`;`≥50% → 不排除但 `warn` 降级`(对齐 `Candidate.warn`)。
- **截断公式**(二元):`limit = 5 × free_slots`,`free_slots = max(0, 3 - holding_count)`;`free_slots==0 → limit=0`(满仓闭门);候选数 `< limit` 时取全部;**当日零合格 → 空列表(唯一的"歇")**。
- **粗筛宽条件**(经验默认值,**非生死阈,可调**):近几日主力净流入为正(`moneyflow` 近 3 日 `net_mf_amount` 合计 > 0)、当日非大幅净流出、放量(当日量 / 5 日均量 ≥ `1.5`,宽)、形态近似(创 20 日新高 **或** 站上 20 日均线,任一即可);均落 `rules.py` 注释标"宁松勿紧、复盘迭代"。
- **排序加权**(机械层,**不卡生死,只定先看谁**):四因子归一打分加权,**放量强度权重最大**,其余 资金面 > 换手 > 低位程度;权重常量入 `rules.py`(首版经验值 `0.4/0.25/0.2/0.15`,注明可迭代)。
- 规则常量 `-5.0/+15.0/D4/容差带` **仍只在 `store.py` 顶部**,选股模块 import 复用,**禁止再写一份**。

### Phase 拆分(后端 D / 前端 E;D 先行,E 依赖 D 的契约)

#### D1 选股数据层(后端)
- 新建 `app/screen/`:`rules.py`(常量+黑名单+权重)、`fetch.py`(全市场 EOD 拉取:`daily_basic`/`moneyflow`/`daily` 按 trade_date 单次批量 + `stock_basic` 行业映射缓存,pandas 归一,内存算放量/新高/60日涨幅)、`pipeline.py`(粗筛→排序→截断,产 `Candidate` dict 列表)。`tushare_client` 补 `ts_stock_basic` 第 5 接口(沿四接口状态降级模式)。
- 新建 `candidates` 表(见 4.2 DDL)+ `store` CRUD(`upsert_candidates` / `list_candidates` / `latest_candidate_date`)。
- **验收**:无 token → `pipeline` 返回空列表+reason 不崩;样例 DataFrame → 黑名单/高位线/截断/排序按规则产出;放量/新高/60日涨幅内存正确计算;截断随 `free_slots`(3→15、1→5、0→0);pytest 覆盖各分支。

#### D2 候选端点 + EOD 刷新(后端)
- `GET /api/v1/candidates`(鉴权):读 `candidates` 缓存表最新 trade_date,按 `5×free_slots` 运行时再截断(满仓→空),返回对齐 `Candidate` 形状列表;`analysis` 列表里省略(深判 on-demand)。
- `POST /api/v1/candidates/refresh`(鉴权):强制重算 upsert,返回 `{ok, trade_date, count}`。
- 监控 loop EOD tick:收盘后 `>=15:35` 算当日候选 upsert(每交易日一次,`last_candidate_date` 防重;失败吞异常不掀翻轮询)。
- **验收**:有缓存→200 截断列表(满仓返空 holdings-aware);无缓存/无 token→`degraded:true` 空列表;refresh 重算落表;EOD tick 注入假 fetch 单测验证落表一次。

#### D3 DeepSeek 深判层(后端)
- 新建 `app/llm/`:`deepseek.py`(httpx + `response_format=json_object` + 超时/失败降级)、`prompt.py`(system 前置词:v2 §6 方法论 + `DeepAnalysis` schema 样例 + 枚举约束 + "泡沫=暴涨/乖离+情绪过热,不看 PE")、`sentiment.py`(东财股吧 best-effort + 降级)、`analyze.py`(编排:补单票 daily 形态 + moneyflow 资金 + 舆情 → 拼 prompt → 调 DeepSeek → 校验夹紧 → 返回 `DeepAnalysis`)。
- **验收**:注入假 transport → 合法 `DeepAnalysis`;非法 JSON/超时 → 降级占位卡(verdict=观望,tone=neutral)不崩;舆情失败 → news neutral;缺 key → 降级卡;tone/verdict 越界被夹紧。

#### D4 深判 + 中间地带端点(后端)
- `POST /api/v1/candidates/{code}/analyze`(鉴权):on-demand 深判,返回 `{ok, code, analysis, fund_asof}`。
- `POST /api/v1/positions/{id}/coach`(鉴权):中间地带 B 剂量,对在持仓给二元建议(最看重量能萎缩 + 主力资金还在不在),返回 `{ok, advice:"拿"|"清", reason, analysis, fund_asof}`;仅二元无减仓;非持仓 404。
- **验收**:analyze on-demand 调 D3 编排返结构化卡;coach 返二元 advice + 理由;非持仓 404;降级路径返占位不崩;curl 闭环。

#### D5 buy_date 修复(后端,小)
- 修 reviewer 🔵#1:`_current_trade_date()` 周末/节假日改取**下一交易日**(`next_trading_day`),D 计数不提前;开仓回包已带 `buy_date`;**不破** `should_force_close` 的 `count==4` 契约。
- **验收**:周末/节假日录入→下一交易日;工作日盘中→当天;单测三态;契约未动。
- 其余 reviewer 项(open_time 粒度→阶段3、linon.service 回写→运维、-4.9 文案→打磨)本阶段不纳入。

#### E1 CandidatesView + 满仓闭门(前端,iOS+macOS)
- 照 handoff README §2 重建 `Views/CandidatesView.swift`:大标题 + 蓝解释条 + 候选卡 `CandidateRow`(排名 chip/名+代码/板块·标签 或 ⚠高位警告琥珀/放量进度条 volPct≥80 绿/放量倍数/主力净流入/现价涨幅/chevron,整卡可点→push AnalysisView)+ 截断脚注 + 满仓 🔒 空态。
- 满仓闭门联动 `shownCandidates`;清仓后重拉重开;`APIClient.fetchCandidates()` + `AppModel.candidates` 真数据。
- **验收**:双端 BUILD SUCCEEDED;渲染候选卡 + 满仓空态;清仓后重开;无候选空态。

#### E2 AnalysisView + 反情绪教练 UI 壳(前端,iOS+macOS)
- 照 README §3 重建 `Views/AnalysisView.swift`:全屏(iOS 隐藏 TabBar)+ 返回 + 股票上下文条 + 聊天 thread + composer。四类消息(user 蓝气泡/assistant 白气泡+◆/analysis 结构化深析卡:三轴 pill+verdict 渐变区+plan,可进附绿按钮→开仓 sheet 预填/coach 红橙卡)。
- 触发:候选点深析→`analyzeCandidate`;中间地带/触损「问教练」→`coachPosition`。教练 UI 壳:卡渲染+触发+复盘引用占位(大脑阶段3,文案取后端 reason)。深析卡显著标注 `fund_asof`。
- **验收**:双端 BUILD SUCCEEDED;深析卡三轴+verdict+plan;可进绿按钮跳开仓;coach 卡;fund_asof 可见;macOS 实点验证绑定(iOS sheet 点击受 computer-use 限制,截图+macOS 实点)。

### 4.2 新增表 DDL(`candidates` 候选缓存)

```sql
CREATE TABLE IF NOT EXISTS candidates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date  TEXT    NOT NULL,          -- EOD 计算基准 'YYYY-MM-DD'
    rank        INTEGER NOT NULL,          -- 机械排序名次(1 起)
    code        TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    sector      TEXT,                      -- 板块(免费板块归类/占位)
    tag         TEXT,                      -- 标签
    price       REAL,                      -- EOD 收盘价
    chg         TEXT,                      -- 涨跌幅展示串
    vol_multiple TEXT,                     -- 放量倍数 "2.8x"
    vol_pct     INTEGER,                   -- 放量进度 0-100
    flow        TEXT,                      -- 主力净流入展示串
    turnover    TEXT,                      -- 换手展示串
    warn        TEXT,                      -- 高位警告降级(≥50% 时非空)
    created_at  TEXT    NOT NULL,
    UNIQUE(trade_date, code)
);
```
(候选不落 `positions`;`analysis` 不缓存——on-demand 实时算。)

### 4.3 接口契约(阶段2 新增端点;均 Bearer 鉴权,沿 `require_token`)

| 端点 | 方法 | 请求 | 响应(200) | 错误 |
|---|---|---|---|---|
| `/api/v1/candidates` | GET | — | `{candidates:[Candidate…], free_slots:int, trade_date:str, degraded:bool, reason?:str}` | 401 |
| `/api/v1/candidates/refresh` | POST | — | `{ok:true, trade_date:str, count:int, degraded:bool}` | 401 |
| `/api/v1/candidates/{code}/analyze` | POST | — | `{ok:true, code, analysis:DeepAnalysis, fund_asof:str}` | 401 / 上游降级仍返占位卡 200 |
| `/api/v1/positions/{id}/coach` | POST | `{question?:str}` | `{ok:true, advice:"拿"\|"清", reason:str, analysis:DeepAnalysis, fund_asof:str}` | 401 / 404 not_holding |

**`Candidate` 形状**(对齐 `Models.swift`,camelCase,列表端点 `analysis` 省略):
`{rank:int, name:str, code:str, sector:str, tag:str, price:float, chg:str, volMultiple:str, volPct:int, flow:str, turnover:str, warn:str?}`
**`DeepAnalysis` 形状**(DeepSeek 结构化输出,逐字段对齐 `Models.swift`):
`{form:{value,tone,text}, fund:{value,tone,text}, news:{value,tone,text}, verdict:"可进"|"观望"|"不进", plan:str}`;`tone∈{good,warn,bad,neutral}`。
**降级语义**:`degraded=true`(无 token/无缓存)时 `candidates=[]`;深判上游失败返回 `verdict=观望`、三轴 `tone=neutral`、文案诚实标注,HTTP **仍 200**。

---

## 实施记录

### 后端 D1–D5(builder,2026-06-23)

- **D1 选股数据层**:`app/screen/{rules,fetch,pipeline}.py`。`rules.py` 黑名单(300/688/8/4/ST/白酒行业)+ 高位线(≥100% 排除 / ≥50% warn)+ 截断 `5×free_slots` + 排序权重 `vol0.4/fund0.25/turnover0.2/low0.15`,全单一源;宽筛阈标注"宁松勿紧、不卡生死"。`fetch.py` 全市场 EOD 拉取(`daily_basic`/`moneyflow` 单次 + 近65日 `daily` 逐日拼)+ pandas 归一(放量/新高/均线/60日涨幅)+ 进程内行业映射缓存。`pipeline.py` 粗筛→排序→截断产 camelCase `Candidate` dict。`tushare_client` 补第5接口 `ts_stock_basic` + 三个全市场批量接口;`store` 加 `candidates` 表 + CRUD。
- **D2 候选端点 + EOD 刷新**:`GET /candidates`(读缓存,运行时 `5×free_slots` 截断,满仓闭门返空,无缓存/无 token→degraded)+ `POST /candidates/refresh`;监控 loop 加 15:35 候选刷新 tick(`last_candidate_date` 防重、失败吞异常)。
- **D3 DeepSeek 深判层**:`app/llm/{prompt,deepseek,sentiment,analyze}.py`;system 前置词武装 v2 §6 + DeepAnalysis schema/枚举约束;`response_format=json_object` httpx(可注入 transport);服务端 `clamp_analysis` 校验夹紧 + 全链路降级占位卡;东财股吧 best-effort 舆情。
- **D4 深判 + 中间地带端点**:`POST /candidates/{code}/analyze`(带 `fund_asof`)+ `POST /positions/{id}/coach`(二元 advice 拿/清,非持仓 404,带 `fund_asof`)。
- **D5 buy_date 修复**:`_current_trade_date` 周末/节假日改取 `next_trading_day`(reviewer 🔵#1),不破 `count==4` 契约。
- **门禁**:pytest **183 全绿**(阶段1 基线 105 + 阶段2 新增 78:D1 选股 34 / D2 端点+tick 12 / D3 LLM 20 / D4 深判+coach 8 / D5 buy_date 4)。
- **真实冒烟**:Tushare 全市场 5490 行,字段口径符合解析假设(`total_mv` 万元/`net_mf_amount` 万元/`daily.amount` 千元);茅台 600519 `industry='白酒'` 命中黑名单,306 条真候选零黑名单/零白酒泄漏。DeepSeek `deepseek-chat`+`json_object` 真输出字段/枚举与 schema 吻合,可夹紧成合法 `DeepAnalysis`;`/analyze`、`/coach` 真 key curl 闭环走通。**Tushare 2000 积分档当日数据有延迟,冒烟时最新可用 trade_date 落 2026-05-06(数据档现实,非 bug)**。
- **偏离**:无。规则常量未漂移;`Candidate`/`DeepAnalysis` 逐字段对齐 `Models.swift`;端点签名/错误码照 §4.3。Tushare 真实字段口径 + 白酒 industry 集合沉淀进根 `CLAUDE.md`。

### 前端 E1–E2(builder,2026-06-23)

- **E1 CandidatesView**:双端候选列表(排名 chip/名+代码/板块·标签 或 ⚠高位警告/放量进度条/放量倍数/主力净流入/现价涨幅/chevron,整卡可点)+ 截断脚注 + 满仓 🔒 空态;iOS 行竖排、macOS 行横向多列(照各自终稿)。共享 `CandidatesExplainBar`/`ClosedEmptyCard`/`CandidatesCopy`。
- **E2 AnalysisView**:双端深析全屏 + 顶部返回 + 股票上下文条 + 聊天 thread + composer;四类消息(user 蓝/assistant 白+◆/analysis `DeepAnalysisCard` 三轴 pill+verdict 渐变+plan+显著 `fund_asof`,可进附绿按钮/coach 红橙卡含复盘引用阶段3 占位+标记次日清仓)。
- **改动**:`AppModel`(候选状态 + thread/chatMode/fundAsof + openAnalysis/openCoach/loadCandidates/buyFromAnalysis + shownCandidates 满仓闭门派生)、`APIClient`(`fetchCandidates`/`analyzeCandidate`/`coachPosition`)、`RootView`(接真视图 + iOS fullScreenCover / macOS 内容区覆盖)、`TodayView`(持仓卡 onCoach 接 openCoach)。
- **门禁**:iOS + macOS 各 BUILD SUCCEEDED;XCTest **17→32 全绿**(新增 15)。
- **验证**:macOS App 实跑 live 绑定(侧栏候选 badge=5 走真 `GET /candidates`);Dock 全屏守卫拦一切点击 → 退路用 `ImageRenderer` 离屏快照逐屏目检(候选行/满仓空态/深析卡/教练卡像素 faithful);真 DeepSeek `/analyze` curl 闭环。
- **自审修 5 处**(medium code-review):① `openAnalysis` 顶栏 `chgIsUp` 硬编 true→`!c.chg.contains("-")`;② iOS fullScreenCover↔sheet 同帧 race→推下一 runloop;③ macOS 侧栏切 Tab 退深析;④ 删 dead 字段 `candidatesTotalQualified`;⑤ 对应单测改 async。坑沉淀根 CLAUDE.md。
- **偏离**:无。Models.swift 未改、绿涨红跌、签名公式、Liquid Glass 克制均守。复盘历史引用 + 破纪律检测大脑按 §4b 留阶段3。

### 审查结论(reviewer,2026-06-23,全文 `archive/REVIEW_REPORT_阶段2.md`)

- **零致命、零重要、6 建议;达可收口标准**(完成度 ~97%)。门禁亲验:pytest 183 / iOS+macOS BUILD SUCCEEDED / client 32;真 key 活体冒烟(analyze 603986 真 DeepSeek 返合法 DeepAnalysis、fund_asof=2026-06-22、coach 非持仓 404、缺 auth 401、无 traceback/无 key 泄漏)。
- 核心契约逐条核过:铁律(rules.py 只硬编真二元项,宽筛非生死阈)/ 规则常量单一源(grep 全仓确认仅 store.py)/ 契约逐字段对齐 / 绿涨红跌+签名组件未动 / 满仓闭门双保险 / buy_date 不破 count==4 / 路由顺序无冲突 / EOD 防重——全部通过。
- **6 建议**(均入主文件 §5 Backlog,无一阻断收口):①候选刷新基准日盘中回退上一交易日 ②`last_candidate_date` 落库防重(合并阶段1 EOD 防重打磨)③`total_mv_yi` 死字段清理 ④深判单票换手补 daily_basic(可选)⑤coach `question` 透传(阶段3 真问答)⑥`chgIsUp` 零涨幅染绿边角。
