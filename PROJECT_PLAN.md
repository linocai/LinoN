# LinoN — A 股小资金短线交易系统 · PROJECT_PLAN

> 唯一权威施工件。上半部为生效 Plan,下半部为变更日志。设计源:`archive/交易系统_ProjectPlan_v2.md`(已完全闭合)。

## 1. 项目概述

辅助"我"做 A 股短线决策的系统——**约束纪律、放大信息、解释概念;扳机永远由我自己扣,不全自动**。

- **交易者画像**:A 股短线投机,资金约 3.6 万(当作可全亏的钱);当日买、次日卖(T+1),最多持 2–3 天;有本职工作不能盯盘,约 20–30 分钟看一次。
- **要治的病根**:选股不是主问题,**纪律执行不到位、情绪主导**才是。两笔典型亏损(抄底接刀亏 1500、追高硬扛亏 4000)死法相同:**进场靠"觉得"、离场没规则**。
- **系统四角色**:① 纪律执行器(到线逼我走)② 信息放大器(扫指标/资金/消息)③ 翻译官(解释概念)④ 人做最终决策。
- **风控两道闸**(不靠择时歇手):**进场质量**(过滤+排序)+ **离场铁律**(止损 -5% / 止盈 +15% / 满 3 交易日第 4 日无条件清仓)。
- **仓位**:同时最多 3 票,全买全卖,无加仓/减仓/做 T。

## 2. 技术选型(锁定,不留给施工阶段选择)

| 维度 | 决定 |
|---|---|
| 后端语言/框架 | Python 3.x + **FastAPI**(阶段1 起)、交易时段调度(阶段1) |
| 客户端 | 原生 **SwiftUI —— iOS + macOS 多平台**(开发者账号直装自有设备,不上架;共享核心 + 平台分叉壳) |
| 推送 | ECS **直连 APNs**(Bark 仅临时验证) |
| 宿主 | 阿里云 **ECS 1C2G / 30G SSD**,**systemd** 守护 |
| 数据存储 | **SQLite** 单文件 |
| LLM | **DeepSeek**(国内 ECS 直连;前置词 + skills) |
| 实时价 | 免费 **新浪(主)→ 腾讯(降级)**,GBK 解码,多源兜底 |
| 历史/资金/日历 | **Tushare 2000 积分会员**:`moneyflow` / `daily_basic` / `daily` / `trade_cal` |
| 配置/密钥 | **pydantic-settings 读 `.env`**;`.env` 进 gitignore |
| 依赖管理 | **venv + 钉死版本 `requirements.txt`** |
| 部署 | **rsync over SSH**,脚本参数化 `host/user/path` |
| 下单/持仓 | 不接券商 API,快捷指令手动录入 |

### 锁定的 5 项施工约束(全期生效)

1. **持仓交易日计数(D1 起算,off-by-one 用代码级措辞钉死)**:买入日 = 第 1 个交易日。`count_holding_trade_days(buy_date, today)` = 用交易日历数闭区间 `[buy_date, today]` 内的交易日个数。**该计数 == 4 当天(即买入日之后第 3 个交易日)无条件清仓**。可卖日:D2、D3(D1 因 T+1 不可卖),**D4 强平**。
2. **交易日历降级**:内置 **2025–2026 沪市静态交易日历**兜底(工作日扣节假日表);Tushare token 到位后自动切 `trade_cal` 并与静态表**校验对齐**。**缺 token 时不能崩**。
3. **部署通道**:rsync over SSH,部署脚本参数化 `host/user/path`(SSH 连接方式用户稍后提供,**先留占位**)。
4. **依赖管理**:venv + 钉死版本 `requirements.txt`(配合 1C2G ECS + systemd + 一键部署)。
5. **止损 -5% 的 ±1% 执行容差**:实盘无法精准锁 -5%,执行价在 -5% 上下约 ±1% 浮动属正常。① 监控用 -5% 线触发即可,**无需亚百分点精度**(每分钟轮询 + 免费实时源足够);② `trades.kept_stop` 判定**带容差带**——在 -5% 线附近(约 -6%~-4%)离场都算"守了止损",**不因正常滑点误标破纪律**。

### 已先行确定的工程实现选择

- **持仓天数不落库**:不存"计数字段",用 `买入日 + 交易日历` 按需算(单一事实源,免每日跑批漂移)。
- **`trades` 表**:一行 = 一笔买卖闭合;**开仓写 `positions`,清仓时落 `trades` 并归档该持仓**。
- **secrets**:走 `.env`,先放 `TUSHARE_TOKEN` 占位,`DEEPSEEK_API_KEY` / APNs key 留空位等后续阶段。

## 3. 当前状态(新会话从此接手)

- 设计已闭合(v2);**阶段 0(基建)已完工**(详见 `archive/stage0_基建_plan.md`)。**阶段 1(脊椎+今日台)已完工并上线**——后端脊椎/客户端双端/ECS 部署三轨齐,真机 APNs 端到端验通,reviewer 审查零致命,审后修复 #1/#2 已部署。详见 `archive/stage1_脊椎今日台_plan.md` + `archive/REVIEW_REPORT_阶段1.md`。
- **阶段 2(选股+决策)已完工收口**——后端选股三段式(粗筛/排序截断/on-demand DeepSeek 深判)+ 中间地带 B + 4 端点,前端 CandidatesView/AnalysisView 双端 + 满仓闭门联动;reviewer 审查**零致命零重要**(6 建议入 §5 Backlog)。**代码完工、门禁全绿、真 key 活体冒烟过;已部署上线 ECS(2026-06-28),选股+深判端到端验通**(refresh 71 候选 degraded=false/内存峰 926MB·swap 0/`moneyflow_dc` 东财源当日资金/`/analyze` 真 DeepSeek 合法卡/公网 HTTPS 200)。全文 `archive/stage2_候选决策_plan.md` + `archive/REVIEW_REPORT_阶段2.md`。
- **阶段 2.5(选股数据质量 + 信号回测闭环)已完工收口**——纯后端小版本:① 给选股/深判技术指标(放量倍数/新高/均线/60日涨幅)补前复权(新建 `app/screen/form.py` 的 `qfq_closes`+`compute_form`,消除 `fetch.py`/`analyze.py` 两处重复计算);② 给候选/DeepSeek 深判加事后回测闭环(候选事后3交易日实际收益回填 + 排序分位/tag/verdict 三维度统计,新建 `app/screen/backtest.py`、新表 `candidate_outcomes`/`analysis_verdicts`、新只读端点 `GET /candidates/outcomes`)。reviewer 审查**零致命零重要**(6 建议全 🔵,不阻断,3 条已收口处理 + 3 条入 §5 Backlog)。全文 `archive/stage2.5_选股数据质量_plan.md` + `archive/REVIEW_REPORT_阶段2.5.md`。
- **阶段 3(复盘闭环)已完工收口**——四件事:① 周复盘打分(确定性聚合 `trades` 表既有 `kept_*`/`broke_rule` 字段,`discipline_rate=score` 一比一,零 LLM);② 复盘/记忆端点(`GET /review`、`POST /review/{week}/note`、`GET /memory`);③ **`trades` 表加 `name`/`note` 两列(项目首次真 schema migration,已按高危区姿势——PRAGMA 探测 + try/except 不拖垮 startup + 连跑幂等验证——安全落地)**;④ 教练大脑(中性 `history_digest` 统计注入 DeepSeek prompt / 带情绪 `review_ref` 只回客户端展示,两路径严格隔离 + `SYSTEM_PROMPT` guardrail 防串味)。前端新增 ReviewView/MemoryView 双端 + AnalysisView coach 卡换真实历史引用。reviewer 审查**零致命**、1 个重要问题(`GET /review`/`POST /review/{week}/note` 非法 week 格式抛未捕获 `ValueError`→500)**已由主会话直接修复**(两端点加 try/except 捕获 `ValueError`/`TypeError` 返回 422,已验证真实 HTTP 请求 422 + pytest 276 全绿无回归),4 条建议入 §5 Backlog。全文 `archive/stage3_复盘闭环_plan.md` + `archive/REVIEW_REPORT_阶段3.md`。
- **阶段 3.1(选股信号增强)已完工收口**——把杨永兴"一夜持股法"6 类选股信号(收盘站 VWAP / 量价形态交 LLM 深判 / 换手健康区间 / 市值弹性 / 近期活跃有涨停 / 单日强弩之末软闸)以纯软信号方式(排序权重从 4 键扩为 8 键 + LLM 深判输入 + warn 软闸)融入现有粗筛/排序/深判,零新增硬排除、零新增 Tushare 接口调用;并把排序内部加权综合分暴露为候选卡「当日相对分」`score`(候选池内 min-max 归一 `[10,100]`,不跨天可比)。`candidates` 表加 `score` 列(项目第二次真 schema migration,复用阶段3 `_ensure_*_columns` 迁移姿势)。plan-critic 两轮审查抓住并堵住 5 个风险点(候选缓存迁移链路断层/信号5-6 互斥打架/涨停判定数据源口径/客户端前向兼容/打分归一边界),施工用 builder-pro(Opus,触及高危 schema migration)。reviewer 审查**零致命零代码级重要**(1 条流程性重要——Plan 状态滞后+未 commit,本次收口已处理;5 条建议入下方说明/Backlog,不阻断)。全文 `archive/stage3.1_选股信号增强_plan.md` + `archive/REVIEW_REPORT_阶段3.1.md`。
- **v1.2.1(深析对话化 + 追问接 DeepSeek)已完工收口并上线**:三件事——① 候选行只有「深析」按钮进(双端);② 初始深析从结构化三轴卡改对话式自由文本;③ 追问框真接 DeepSeek 多轮问答。新增统一对话端点 `POST /chat`(不合并进 `/analyze`/`/coach`,二者保留供回测链路/教练红橙卡);对话 prose reply + 旁路抽 verdict 落库(仅首条候选对话且非降级才落);后端无状态、多轮上下文客户端全量回传;守味隔离沿阶段3(只注入 history_digest);对话专属超时 25s×2。reviewer 审查**零致命**,2 个重要问题(coach 区间措辞按 pnl 派生 / 事实缓存条件改 and)已修复。**两步全量部署已上线 ECS**(先收 store 拆包重构欠账、再上 v1.2.1 新增),端到端验通:`/chat` 生产返 181 字自由对话、fund_asof 07-02、东财资金流入正常。7 条 🔵 建议 + 1 条遗留入 §5 Backlog。全文 `archive/v1.2.1_plan.md` + `archive/REVIEW_REPORT_v1.2.1.md`。
- **v1.3.0(实战反馈四件套)已完工收口**:四条用户实战反馈驱动的改动——② 三仓相关性护栏(行业 Tushare 口径·只提示不拦·只在买入路径)、④ 交易成本自动化+净额复盘(🔴高危·金额计算+第三次真 migration)、⑤ 候选放开固定 20(删满仓闭门)、⑥ 导出同花顺 TXT(纯前端)。⑦选股大改+③买入理由结构化推迟到 v1.3.1。走完整工作流:planner→plan-critic(零致命3重要8建议·修订)→builder-pro(Phase B高危)+主会话Opus复审→builder(后端A+C)→builder(前端C3+D+E)→reviewer(Fable·1 致命[URL `?` 编码坏致相关性护栏生产静默失效]→已修/2 重要/6 建议)→主会话审后修复。门禁:后端 pytest **337→378 全绿**(新增 41,Phase A 相关性 16 条 + Phase C 截断口径重写净增 3);客户端 XCTest **49→65 全绿**;双端 `BUILD SUCCEEDED`。新增端点 **1 个**:`GET /positions/correlation`。第三次真 migration:`positions.industry` + `trades.qty/fee/net_pnl_amount`(均 nullable 前向兼容)。全文 `archive/v1.3.0_plan.md` + `archive/REVIEW_REPORT_v1.3.0.md`。
- **门禁数字**:**已发布 3 阶段**(阶段1+阶段2+v1.2.1,live `https://ln.linotsai.top`,阶段2 于 2026-06-28 上线、v1.2.1 于 2026-07-02 两步上线;阶段2.5/阶段3/阶段3.1 为纯后端/全栈小版本随部署链路一并上线;`app/db/store.py` 单文件在 ECS 已不存在,store 拆包首次真上生产;**v1.3.0 已部署上线(2026-07-04)**)。**阶段4(K线/舆情/双端真机 E2E)待规划**。后端 pytest **378 全绿**(阶段1 基线 105 + 阶段2 新增 88 → 193 + 阶段2.5 新增 34 → 227 + 阶段3 新增 49 → 276 + 阶段3.1 新增 33 → 309 + v1.2.1 新增 28 → 337 + v1.3.0 新增 41);客户端 XCTest **65 全绿**(17 + 阶段2 新增 15 → 32,阶段2.5 无前端改动,阶段3 新增 8 → 40,阶段3.1 新增 4 → 44,v1.2.1 新增 5 → 49,v1.3.0 新增 16);**双端 build iOS Simulator + macOS 各 `BUILD SUCCEEDED`**;真 key 活体冒烟过(Tushare 5490 行/茅台白酒归类符合假设;DeepSeek `json_object` 真输出夹紧成合法 DeepAnalysis;analyze/coach/chat 真 key curl 闭环;离屏快照逐屏目检候选行/满仓🔒/深析卡 fund_asof/教练红橙卡;阶段2.5 真 token 限频冒烟 65/65 天 adj_factor 全部成功,零限频失败,耗时 39s→45.5-45.7s)。阶段2 新增端点 **4 个**:`GET /candidates`、`POST /candidates/refresh`、`POST /candidates/{code}/analyze`、`POST /positions/{id}/coach`;阶段2.5 新增只读端点 **1 个**:`GET /candidates/outcomes`;阶段3 新增端点 **3 个**(`GET /review`、`POST /review/{week}/note`、`GET /memory`)+ `/coach` 新增可选字段 `review_ref`;阶段3.1 无新增端点,`GET /candidates` 候选 dict 新增可选展示字段 `score`(int,前向兼容);v1.2.1 新增端点 **1 个**:`POST /chat`;v1.3.0 新增端点 **1 个**:`GET /positions/correlation`。
- **v1.3.1(盘后选股完善)施工中**:三块——① 新选股逻辑(删高位硬排除改只标注红/琥珀分级、粗筛量比口径、排序 9 因子集含距60日高点/横盘突破、量比接 `daily_basic.volume_ratio`、warnLevel 经 candidates 缓存表往返=**第四次真 migration `warn_level` 列**)、② 选股配置可调化(档 B·App 内调参屏 + 新表 `screen_config` 存 JSON 增量 + `GET/PUT` 端点 + 显式穿参生效,rules 常量降级为默认值/fallback)、③ 候选刷新改纯手动(删 15:35 自动 tick + `last_candidate_date` 防重,回填改挂 EOD 块)。持仓教练深判重做 + 盘中选股独立板块已定移 **v1.4**,本版不碰。§4 有完整 Phase(已过 plan-critic 一轮:1 致命[缓存断层]+6 重要+6 建议全吸收)。
  - **批1(后端 Phase A1/A2/A2.5 + C1)已完工**:A1(`rules.py` WEIGHTS 换9键新向量、`high_position_verdict`删exclude只留warn分级、`high_warn_text`补≥100%红级文案;`form.py` 新增 `pos_health`/`breakout_ok` 字段 + 可选 `volume_ratio` 入参)→ A2(`fetch.py` `StockRow` 加 `volume_ratio` 字段 NaN 安全读取 `_safe_float`;`pipeline.py` `passes_coarse`/`build_candidates`/`rank_score` 全接新因子集,删高位 exclude 分支)→ A2.5(`candidates` 表加 `warn_level` 列——**项目第四次真 migration**,`_ensure_candidates_columns` 扩展;`_CANDIDATE_KEYS`/`upsert_candidates`/`list_candidates` 三处同步;端到端穿透缓存回环测试覆盖 high/amber/nil 三态)→ C1(`monitor/loop.py` 删 15:35 自动候选刷新 tick + `run_candidate_refresh` 死码 + `_is_after_candidate_window`/`_CANDIDATE_AFTER`;候选回测回填移入 `last_eod_date` 守卫的 EOD 块内,每交易日仅触发一次)。**未做**:Phase B(配置可调化)、A3/B3/C2(前端)。后端 pytest **378→403 全绿**(新增 25:A1/A2 约 20 条 + A2.5 迁移/回环测试 13 条 - C1 删 4 条旧 tick 测试 + C1 新增 5 条)。
  - **批2(后端 Phase B1+B2,配置可调化)已完工**:B1 新表 `screen_config`(`CREATE TABLE IF NOT EXISTS` 单行 JSON,建表非 ALTER,零风险)+ 新子模块 `app/db/store/screen_config.py`(`get/put_screen_config`,坏 JSON/非 dict 降级空 dict)。`rules.py` 新增 `SCREEN_CONFIG_SPEC`(21 键=9 权重+12 阈值,类型/范围/类别/默认值,`default` 引用常量构造不手写第二份数字)+ `DEFAULT_SCREEN_CONFIG` + `validate_screen_config(cfg, normalize_weights=False)`(逐键类型/`math.isfinite`/越界夹紧;`normalize_weights=True` 才归一——**显式布尔而非"凑齐权重键即归一"的隐式判断**,严格对应"PUT 不归一/resolve 才归一")+ `resolve_screen_config`(默认浅合并增量→`validate(normalize_weights=True)`)。`passes_coarse`/`rank_score`/`turnover_health_score`/`mv_elastic_score`/`day_surge_penalty_norm`/`day_surge_warn_text`/`compute_form`/`_enrich_form`/`fetch_market_snapshot`/`build_candidates`/`run_pipeline` 全部加尾部可选 `cfg` 参数,`cfg=None` 时回落**模块级常量**(非 `DEFAULT_SCREEN_CONFIG` 快照 dict,保 `test_form.py` 对 `rules.ACTIVE_LOOKBACK_DAYS` 的 monkeypatch 测试不回归)。`_recompute_candidates` 显式 `resolve_screen_config(store.get_screen_config())` 穿参给 `run_pipeline`(注入测试替身路径不变,仍 1 参调用,不回归)。新增端点 `GET/PUT /api/v1/screen/config`(PUT 逐键夹紧存增量、不归一;空 `{}` = 恢复默认清行)。深判层 `app/llm/analyze.py` 零改动、不读 `screen_config`(grep 断言覆盖)。后端 pytest **403→443 全绿**(新增 40 条:B1 存储 7 + SPEC/DEFAULT 等值 3 + validate 分支 13 + resolve 4 + 穿参真生效 3 + 深判边界 2 + 端点 GET/PUT 8)。**未做**:B3(客户端调参屏)。
- **上线即空仓**:无存量持仓迁移,无 legacy / 既往不咎机制,`positions` 从 0 行起。
- **止损线机械派生**:`stop_line = buy_price × 0.95`,**纯派生、不落库**(-10% 极强趋势例外已砍,止损恒为 ×0.95;与持仓天数同样按读取时算,单一事实源),系统自动算,**拒绝用户手填**。
- **ECS 现实**:`deploy@118.178.122.194:/opt/linon`,systemd **单 unit** `linon.service` **active**(端口 **8001**,监控作 app 内后台轮询、不另起进程),nginx `ln.linotsai.top` + certbot 证书;内存紧(1.6G+2G swap),已占端口 8000/8787/5432/80/443/8001;`.env`/`.p8` 均 600 `linon:linon`。
- **APNs**:Key ID `Q963AP3VY8` / Team ID `HX73DFL88G` / Bundle ID `top.linotsai.linon`;dev 直装走 **sandbox** 网关(`api.sandbox.push.apple.com`),`.p8` 已搬 ECS;真机已注册 device token,ECS→APNs sandbox→iPhone 推送实测 200。**prod `API_TOKEN` 已配客户端**(prod 端到端完整闭环列 §5 用户侧收尾)。
- **落地目录**:`backend/`(`app/{config,data,db,calendar,api,monitor,push,smoke}` + `scripts/{setup.sh,sync.sh,smoke.py,smoke_api.sh}` + `deploy/linon.service` + `tests/` + `requirements.txt` + `.env.example`)、`client/`(`project.yml` + `LinoN/` + `LinoNTests/` + 根契约 `DesignTokens.swift`/`Models.swift`)、`archive/`、根 `.gitignore` + `CLAUDE.md`。
- **路线图**(后端/前端双轨;**每屏照设计终稿做、无 throwaway 最小壳;阶段4 缩水**):

| 阶段 | 后端 | 前端(照终稿,双端) |
|---|---|---|
| 0 基建 ✅ | 数据层四件套(实时价 / Tushare / SQLite / 日历)+ 部署脚手架 + 冒烟脚本 | 仅纳入 `DesignTokens.swift`/`Models.swift` 作客户端契约;客户端工程骨架可选 |
| 1 脊椎+今日台 ✅ | 监控 / 3 硬线 / 心跳 / APNs / 开·清仓录入 API | 客户端地基(multiplatform:tokens+models+AppModel+导航壳+两签名组件)+ TodayView 终稿 + 开/清仓 sheet + 锁屏推送行为(iOS) |
| 2 候选+决策 ✅ | 粗筛 / 排序截断 / on-demand 深析 / 中间地带 ✅ | CandidatesView + AnalysisView(四类消息 + 结构化深析卡 + 教练 UI 壳)+ 满仓闭门联动 ✅ |
| 3 复盘闭环 ✅ | 纪律打分(聚合 `trades.kept_*`,确定性非 LLM)/ 复盘·记忆端点 / 清仓沉淀记忆 / 教练大脑注入历史 ✅ | ReviewView + MemoryView + coach 卡接复盘历史(换掉占位)✅ |
| 3.1 选股信号增强 ✅ | 6 类软信号(VWAP/量价形态/换手区间/市值弹性/近期活跃/单日软闸)进排序权重+深判 prompt+warn 软闸,零新接口;候选 dict 加当日相对分 `score` | 候选卡加 `score` 展示(10–100)+ 解释条文案(双端小改)✅ |
| 4 收尾(**待规划**) | — | K 线/分时图、舆情展示、双端真机 E2E 打磨 |
| V2(推后) | 历史行情重放 / 纪律陪练沙盒(陪练非裁判) | 临场纪律陪练 |

## 4. 当前版本 Plan(v1.3.1 · 盘后选股完善)

> **范围三块**:A 新选股逻辑(后端为主 + 前端展示微调)/ B 选股配置可调化(档 B·App 内调参,全栈)/ C 候选刷新改手动(后端 + 前端)。**明确移 v1.4,本版不碰**:② 持仓教练深判重做(层2 盘中资金失真问题)、③ 盘中选股独立板块(Level-2 资金缺口)。v1.3.0 已收口归档 `archive/v1.3.0_plan.md`。
> **红线**:离场铁律常量(`-5.0/+15/D4/count==4/±1%容差带`)本版**四层都不碰**;选股规则单一源仍在 `rules.py`,配置化后**配置是运行时源、rules 常量作默认/fallback**;费用常量(v1.3.0)/离场常量各自单一源不动。铁律"技术面交 LLM 判":新因子/新阈值同样标"经验默认·可迭代·不卡生死"。

### 已定稿背景(SOP·不落 Phase)

**盘后操作周期 SOP**(T-1 盘后驱动 → T 日操作,循环):T-1 收盘后 ~16:00 手动点刷新 → 拉全市场 EOD → 20 候选 → 导出同花顺(明日观察池)→ 可选深析。T 日盘前~盘中视线 = 3 持仓 + 20 候选,优先看持仓 → 执行卖持仓/买候选。候选**固定 20 只**(沿用 v1.3.0,不闭门)。

### 施工顺序与依赖

`Phase A1(rules/form 新因子·纯函数)` → `A2(fetch/pipeline 接线)` → `A3(前端 warn 分级展示)`;`Phase B1(新表+存取)` → `B2(GET/PUT 端点 + rules 读配置)` → `B3(客户端调参屏)`;`Phase C1(删自动 tick)` → `C2(前端刷新提示微调,可选)`。**A 与 C 独立可并行**;**B2 依赖 A2**(配置字段必须覆盖 A 新引入的全部权重/阈值,否则漏项)——故 **B 整体在 A 之后施工**。**B1 建表 + B2 配置校验/降级是 plan-critic 重点审面**(配置成为新单一源,校验/优先级/非法降级必须无懈可击)。

---

### Phase A —— 新选股逻辑(后端为主 · A1/A2/A2.5 后端,A3 前端)

选股四层重构。**离场四层不碰**;选股常量单一源仍 `rules.py`(B 之后由配置覆盖,本 Phase 先改 rules 默认值)。子 Phase:A1 rules/form 纯函数 → A2 fetch/pipeline 接线 → **A2.5 warnLevel 缓存链路(第四次真 migration,致命#1)** → A3 前端展示。

**第1层 硬排除(改:删高位硬排除)**:
- 删除高位线 ≥100% 排除 —— `high_position_verdict` **不再产 `'exclude'`**,只保留 `'warn'`/`'ok'` 两态(≥100% 与 [50,100%) 都归 warn,分级见 A3)。`pipeline.build_candidates` 里 `if verdict == "exclude": continue` **整段删除**。
- 其余硬排除**不变**:黑名单代码段(`^(30|688|689|8|4|920)` 板块整段正则,只做主板 60*/00*)、ST、白酒行业(`stock_basic.industry` 精确归类)。

**第2层 粗筛(改:①放量倍数→官方量比)**:保留四条,任一不过淘汰:
1. **量比 ≥ `VOL_RATIO_MIN`(默认 1.5)** —— 口径从"自算放量倍数(当日量/5日均量)"换成 **Tushare `daily_basic.volume_ratio`**(现成字段,`ts_daily_basic_all` 已返回,当前未用)。`passes_coarse` 的 `sr.vol_multiple < VOL_MULTIPLE_MIN` 改为 `sr.volume_ratio < VOL_RATIO_MIN`。
2. 近 3 日主力净流入 > 0(东财 `moneyflow_dc.net_amount` 合计,不变)。
3. 当日主力非大幅出货 ≥ `DAY_OUTFLOW_FLOOR`(默认 -5000 万,不变)。
4. 创 20 日新高 或 站 20 日均线(任一,不变)。

**第3层 机械排序(新因子集,首版权重,全部进配置可调)**:`WEIGHTS` 换为下表(正权之和 = 1.00,单日软闸为负权罚项):

| 键 | 因子 | 首版默认权重 | 口径 |
|---|---|---|---|
| `vol_ratio` | 量比 | **0.30** | `daily_basic.volume_ratio`(归一后进分) |
| `pos_health` | 位置健康(距高点) | **0.16** | `今日收盘 / 近60日最高收盘`,越近高点分越高 |
| `turnover` | 换手健康 | **0.14** | 满分带 **[7,15]%**(旧 [5,10]) |
| `vwap` | VWAP 站均价 | **0.10** | 收盘 ≥ 当日 VWAP,布尔 0/1(不变) |
| `breakout` | 横盘突破(新增) | **0.10** | 近25日振幅收窄 + 今日放量突破区间上沿,布尔 0/1 |
| `mv_elastic` | 市值弹性 | **0.08** | 满分带 **[50,500]亿**、微盘 floor **30亿**(旧 [20,200]/floor 15) |
| `active` | 近期活跃 | **0.06** | 近10日有涨停,布尔 0/1(不变) |
| `fund` | 资金面 | **0.06** | `net_mf_rate_3d` 相对口径 min-max(veto 主要在粗筛,正权拉低) |
| `day_surge` | 单日软闸 | **-0.06** | 今日 ≥9% 罚(penalty,不变) |

- **关键替换 `low_position` → `pos_health`**:旧 `low_position = 1 - normalize(pct_60d)` 偏好"涨幅越低"→ 系统性给左侧下跌票高分(方向反了)。新 `pos_health` = `today_close / max(近60日收盘)`(∈(0,1],越接近 1 = 越贴近高点越强),直接进分**不再 min-max**(已是 [0,1] 绝对刻度);左侧持续下跌票距高点远 → 自然低分被压(**不排除**,只压分)。
- 量比因子 `vol_ratio` 走 min-max 相对归一(同 `fund`);`turnover`/`mv_elastic`/`day_surge` 走各自评分函数(现有);`vwap`/`breakout`/`active` 布尔转 0/1。
- 展示分 `score`([10,100] 池内 min-max 归一,不跨天可比)口径不变。
- **展示口径解耦(建议#10)**:候选卡 `volMultiple`/`volPct` 展示**仍为自算放量倍数(当日量/5日均量)不变**——排序换官方量比、展示保留放量倍数,两者解耦。builder 勿顺手把展示串也换成量比。`sr.vol_multiple`(自算,form 仍产)供展示;`sr.volume_ratio`(官方)供粗筛/排序。

**第4层 标注分级(改:高位分级 + 叠加)**:
- 固定 Top 20(`CANDIDATE_LIMIT=20`,不变)。
- warn 分级(前端 A3 用):高位 ≥100% → **红标**(新增 `high` 级)/ [50,100%) → **琥珀标**;单日强弩之末(≥9%)→ 琥珀标;**可叠加**(既高位又暴涨则两条都显)。级别取最高(有 high 则 warnLevel=high,否则有 amber 则 amber,否则 nil)。
- 后端产 warn 需带级别信息(见 A3 契约:`warn` 串 + 新增 `warnLevel` 可选字段)。**`warnLevel` 必须穿过 `candidates` 缓存表往返**(A2.5 加列,否则生产静默失效——致命#1)。
- **≥100% 票 warn 文案必须有人产(重要#6)**:旧 `high_warn_text` 只对 [50,100) 返文案、≥100% 返 None(旧逻辑 ≥100% 已 exclude 轮不到);A1 补 `high_warn_text` 对 ≥100% 返红级文案(如"60日累涨 X%,极高位,追高高危"),使 ≥100% 票 warnLevel=high 与 warn 文案配套一致。
- **组合效应(预期行为,非回归·建议#12)**:删 ≥100% 硬排除 + `pos_health` 奖励贴高点 两刀同向,Top20 可能被高位强势票批量占据(红标兜底提示)——这是动量逻辑的**刻意选择**,reviewer 勿当回归追。

**新形态计算(`form.py`,纯函数可单测,数据不足降级)**——从已有近60日复权 `closes`(新→旧)派生,新增两个 `FormResult` 字段:
- `pos_health: float`(距60日高点)= `closes[0] / max(closes[:min(60,len)])`,分母 ≤0 → `0.0`;**数据不足 `len<20` → `0.0`(建议#9)**——次新股只几天数据会贴短命高点白拿满权,压掉;保守压分不误抬。范围 (0,1]。
- `breakout_ok: bool`(横盘突破)= 满足全部三条才 True,否则 False:① 近24日(**排除今日**)振幅收窄:`(max(closes[1:25]) - min(closes[1:25])) / min(closes[1:25]) < BREAKOUT_RANGE_MAX`(默认 0.15);② 今日突破区间上沿:`closes[0] > max(closes[1:25])`(今日收盘高于过去24日最高);③ 量比配合:`volume_ratio >= BREAKOUT_VOL_RATIO_MIN`(默认 1.5)。**振幅窗口必须排除今日(重要#5)**:若把今日纳入振幅窗口,而突破条又令今日=最高,则振幅退化为 `(今日−最低)/最低`、越有力突破越判 False(把窄横盘+大阳线突破自己掐灭);故振幅与突破都在 `closes[1:25]`(过去24日,不含今日)上算。量比不在 `closes` 序列里 → `compute_form` 新增可选入参 `volume_ratio: Optional[float]=None`,缺失(None)→ 条③视为不满足 → `breakout_ok=False`(向后兼容旧调用)。数据不足 25 日 → False。

**A1 验收(后端·纯函数)**:
- `rules.py`:`WEIGHTS` 为上表 9 键、正权和 == 1.00(加断言测试);新增 `VOL_RATIO_MIN=1.5`、换手带 `[7,15]`、市值带 `[50,500]`/floor `30`、`BREAKOUT_RANGE_MAX=0.15`/`BREAKOUT_VOL_RATIO_MIN=1.5`;`high_position_verdict` 不再返 `'exclude'`(单测断言 pct_60d=200 → `'warn'` 非 `'exclude'`)。`pos_health` 因子进分不走 min-max(单测:两票 pos_health 0.99 vs 0.30 → 0.99 得高分)。所有新常量标注"经验默认·可迭代·不卡生死"。
- `high_warn_text` 对 ≥100% 返红级文案(重要#6):单测 `high_warn_text(200)` 非空 + 该票 warnLevel 派生为 `"high"`(文案与级别配套断言)。
- `form.py`:`compute_form` 新增 `pos_health`/`breakout_ok` 字段 + 可选 `volume_ratio` 入参;单测覆盖:pos_health 贴高点(≈1)/远离(小)、**数据不足 `len<20` → pos_health=0.0**(建议#9);breakout 三条件——**"窄横盘 + 大阳线突破今日=最高" → True**(重要#5 门禁用例:按"振幅含今日"的错误公式这条会 False,正好当回归护栏)、任一条不满足 → False、缺 volume_ratio → False、数据不足 25 日 → False。**复权序列方向契约不碰**(沿用 `qfq_closes` 新→旧、基准 `[0]`)。
- 后端 pytest 全绿、无回归(旧 `low_position`/`vol_multiple` 相关测试相应改写,不 skip/deselect)。

**A2 验收(后端·接线)**:
- `fetch.StockRow` 新增 `volume_ratio: float=0.0`(从 `daily_basic.volume_ratio` 读);`_enrich_form` 把 `volume_ratio` 传入 `compute_form`,写回 `sr.pos_health`/`sr.breakout_ok`。
- **NaN 守卫(重要#4)**:Tushare DataFrame 缺值是 **NaN 非 None**,`float(x or 0)` 拦不住(nan 是 truthy,`nan<1.5==False` → 该票会**放行**进池,再毒化 `rank_score` 的 min-max、整池分数 NaN 乱序)。`volume_ratio`(及本 Phase 新读的所有数值列)读入必须用 `pd.isna(x)` 守卫 → `0.0`;**A2 加 NaN 单测**:`volume_ratio=NaN` 的票粗筛被淘汰、不进 rank_score、不产 NaN 分数。
- `pipeline`:`passes_coarse` 用量比;`build_candidates` 删高位 exclude 分支;`rank_score` 入参换新因子集(传 `volume_ratios`/`pos_healths`/`breakout_oks`,去掉旧 `pct_60ds`+`low_position` 用法,`pct_60d` 仅留给 warn 分级判定)。
- 降级守恒不破:量比字段缺失/NaN → 该票量比=0(粗筛淘汰,不崩);pos_health/breakout 数据不足 → 保守压分/False。
- 端到端本地冒烟:种样例或真 token 拉一次,`GET /candidates` 返 20 只、`degraded=false`、排序合理(距高点近的强票靠前、下跌左侧票被压)。

**A2.5 验收(后端 · warnLevel 缓存链路 + 第四次真 migration · 致命#1)**:
> `GET /candidates` 读的是 `candidates` **缓存表**(非 pipeline 直出),表不存 `pct_60d`、读取时派生不出级别;`upsert_candidates` 逐列白名单 INSERT 会**静默丢弃** `warnLevel`。不做本子 Phase = 红标功能生产静默失效(与 v1.3.0 URL bug 同源盲区:单测走内存、真链路走缓存表)。
- **`candidates` 表加 `warn_level TEXT` 列**——**项目第四次真 migration**:扩 `schema._ensure_candidates_columns`(沿 PRAGMA `table_info` 探测 + `ALTER ADD COLUMN` + try/except 只 `log.error` 不 re-raise 姿势,同 score);`_SCHEMA` 的 candidates DDL 补一行注释指明 `warn_level` 由迁移补充(同 score 惯例)。为何 ALTER 不 DROP:候选历史行供回测回填扫描,不可丢(同 score 理由)。
- **三处同步**:`candidates._CANDIDATE_KEYS`(列名映射)+ `upsert_candidates` INSERT 列 + `list_candidates` 输出,三处同增 `warn_level`;NULL 省键(同 `warn`/`score` 惯例,旧行 warn_level=NULL → 输出省略 → 客户端 nil,前向兼容)。
- **穿透缓存回环测试(封死断层盲区)**:A2.5 验收必含一条端到端测试——pipeline 产 `warnLevel="high"` 的候选 → `upsert_candidates` 落库 → `list_candidates`/`GET /candidates` 读回**仍带 `warnLevel="high"`**(不是内存直测,必须过缓存表往返)。amber、nil 各一条。
- 后端 pytest 全绿;新表列迁移连跑幂等无异常。**部署前置见 §5**(第四次 ALTER,先 `cp` 备份)。

**A3 验收(前端·展示微调)**:
- `Candidate` 新增可选 `warnLevel: String?`(`"high"`/`"amber"`/nil,前向兼容);`CandidatesListResponse` DTO 解码。后端 `pipeline` 产候选时按级别填(≥100% high、其余 warn 场景 amber)。
- `CandidateRow.warnOrSector`:`warnLevel=="high"` → **红色**警告 pill(`LN.down`/红系)、`"amber"` → 琥珀 pill(现状)、nil → 板块标签。卡片背景 high 用红系极浅、amber 用琥珀极浅(现状 `LN.amber.opacity(0.04)`)。
- 绿涨红跌不变;派生 bool 不字符串判负(warn 级别走后端 `warnLevel` 字段,不靠客户端解析 warn 文案)。
- 双端 `xcodegen generate` + iOS Simulator + macOS `BUILD SUCCEEDED`;XCTest 全绿(新增 warnLevel 解码 + 红/琥珀分级测试)。

---

### Phase B —— 选股配置可调化(档 B · 全栈 · plan-critic 重点审)

用户在 App 里调参 → PUT 存后端 → 下次手动刷新生效。**配置化后配置成为新单一事实源,`rules.py` 常量降级为默认值/fallback**。

**config 形状(钉死 · 重要#2)——扁平单层键注册表**:config 是**扁平单层 dict**(9 权重键 + 各阈值键平铺,不嵌套——浅合并语义才成立)。定义一份「键注册表」`SCREEN_CONFIG_SPEC`(在 `rules.py`,每键含:类型 / 范围 / 类别(`weight` vs `threshold`)/ 默认值),校验/归一/UI 都以它为准。键集(值 == 各 rules 常量,建议#8 用**引用构造**):

```
权重(类别 weight,∈[0,1];day_surge ∈[-1,0]):
  vol_ratio=0.30  pos_health=0.16  turnover=0.14  vwap=0.10
  breakout=0.10   mv_elastic=0.08  active=0.06    fund=0.06   day_surge=-0.06
阈值(类别 threshold):
  vol_ratio_min=1.5   turnover_lo=7    turnover_hi=15   mv_lo=50   mv_hi=500   mv_floor=30
  breakout_range_max=0.15   breakout_vol_ratio_min=1.5
  day_outflow_floor=-5000   day_surge_warn_pct=9   active_lookback_days=10   limit_up_pct=9.8
```

**B1 —— 配置存储(后端 · 新表)验收**:
- **存储选型(钉死)**:SQLite **新表 `screen_config`**,存**单行 JSON**(字段随迭代增删,JSON 单行避免频繁 migration)。表结构:`CREATE TABLE IF NOT EXISTS screen_config (id INTEGER PRIMARY KEY CHECK(id=1), config_json TEXT NOT NULL, updated_at TEXT NOT NULL)`。**`CREATE TABLE IF NOT EXISTS` 非 ALTER**(建表不是列迁移,风险低于 v1.3.0 真 migration;仍幂等,进 `init_db` 的 `_SCHEMA` executescript)。
- 存取放 `app/db/store/` 新子模块 `screen_config.py`(re-export 进 `__init__`,沿拆包纪律):`get_screen_config() -> dict`(读单行 JSON,**无行/JSON 损坏 → 返回 `{}` 空 dict**,由上层合默认)、`put_screen_config(cfg: dict) -> None`(upsert id=1,写 `updated_at`)。**PUT 存增量(重要#2)**:只存用户显式提交的键(部分覆盖),不存全量——`get` 拿回的就是用户改过的那几个键,其余靠 resolve 合默认。
- **默认值单一源仍在 `rules.py`**:`DEFAULT_SCREEN_CONFIG` = **由常量/`WEIGHTS` 引用构造**(`{"vol_ratio_min": VOL_RATIO_MIN, "turnover_lo": TURNOVER_HEALTHY_LO, ...}`、权重段引用 `WEIGHTS`),不手写第二份数字(建议#8 防双写漂移)+ **等值断言测试**(`DEFAULT_SCREEN_CONFIG` 各键 == 对应常量)。
- B1 验收:新表建立幂等(连跑 `init_db` 无异常);`get/put` 往返一致;空表/坏 JSON `get` 返 `{}`;PUT 存的是增量(只含提交键);pytest 覆盖建表+存取+坏 JSON 降级。

**B2 —— 配置合并/校验 + 生效机制 + 端点(后端 · plan-critic 重点)验收**:
- **合并优先级(钉死)**:`resolve_screen_config() -> dict` = `DEFAULT_SCREEN_CONFIG`(基底)**浅合并**用户增量 `get_screen_config()`(只覆盖用户显式给的键,缺键用默认;未知键忽略)→ 得全量 → **再跑校验+权重归一**(见下)。返回全量已夹紧配置。
- **生效机制(钉死 · 重要#3)——显式穿参,不 monkeypatch 常量**:常量消费点散在多个纯函数(`passes_coarse`/`rank_score`/`turnover_health_score`/`mv_elastic_score`/`day_surge_*`/`high_warn_text`/`compute_form`)。生效方式 = **`resolve_screen_config()` 出 cfg dict,由刷新链路显式穿参**:`_recompute_candidates → run_pipeline(cfg) → build_candidates(cfg)/passes_coarse(sr,cfg)/rank_score(...,cfg)` + `fetch 层 compute_form(...,cfg 相关阈值)`。**禁止 monkeypatch 模块级常量**(与 `/analyze` 并发时不安全 + 破单一源)——纯函数改为收 cfg 参数(缺省 = None 时回落 `DEFAULT_SCREEN_CONFIG`,保测试/旧调用可用)。
- **深判层边界(钉死 · 重要#3)**:**`analyze.py`(深判)明确不吃用户配置,继续用 rules 默认常量**——深判里的 `LIMIT_UP_PCT` 等只作喂 DeepSeek 的 prompt 素材、不进选股打分,不引入并发配置态。此边界写进 B2 验收(断言深判路径不读 `screen_config`)。
- **校验/夹紧(钉死)**:`validate_screen_config(cfg) -> dict` 按 `SCREEN_CONFIG_SPEC` 逐字段:① 类型不符/缺失/**非有限值(非 `math.isfinite`,重要#4)** → 用默认值;② 阈值越界夹到范围(`vol_ratio_min∈[1.0,5.0]`、换手带 lo<hi 且 ∈[0,50]、市值带 lo<hi 且 floor<lo、`day_surge`∈[-1,0]、`active_lookback_days∈[1,60]` 取整、权重每项 ∈[0,1] 等);③ **权重归一只在 resolve 合并出全量后做(重要#2)**:8 项正权之和 ≠1.0 → 按比例归一到和=1.0(`day_surge` 负权夹 [-1,0] 不参与归一);全 0 → 退回默认权重。**PUT 时逐键按范围夹紧但不归一**(部分提交无法归一,归一只对全量);归一发生在 `resolve`。**非法/异常配置 → 逐字段回退默认,绝不崩、绝不产空候选**(配置非法必须仍能出候选,与"无 token→degraded 空列表"两回事)。
- **端点**(鉴权 `require_token`,`makeURL` 无 query):
  - `GET /api/v1/screen/config` → `200 {config: {全量 resolve 后活配置}, defaults: {DEFAULT_SCREEN_CONFIG}, updated_at: str|null}`(config 供 UI 显示生效值,defaults 供"恢复默认")。
  - `PUT /api/v1/screen/config` body `{config: {部分或全部键}}` → 逐键夹紧(不归一)→ `put_screen_config` 存**增量** → 返 `200 {ok:true, config: {resolve 后全量活配置}}`。**幂等**;越界键夹紧不 422(**能夹的夹、未知键忽略,一律 200 返夹紧结果**)。
  - **恢复默认 = PUT 空 config `{}`(重要#2)** → 清空用户行(`put_screen_config({})` 或删行),resolve 全回默认。**不是** PUT 全量默认值(那会把当前 DEFAULT 冻结进库、挡未来默认演进)。
- B2 验收:`resolve` 合并优先级(默认+增量覆盖)+ 全量后归一;校验各分支(类型错/NaN/越界/权重不归一/全0/未知键)都产合法配置;端点 GET/PUT 往返 + 夹紧 + 恢复默认(PUT `{}` 清行)真实 HTTP 验证;**`pipeline` 真读活配置**(改 `vol_ratio_min` 后 refresh,粗筛行为随之变——证穿参生效非 monkeypatch);深判路径不读配置;pytest 全绿。

**B3 —— 客户端调参屏(前端)验收**:
- 新增 `Views/ScreenConfigView.swift`(双端共享内容,布局分叉同其他屏):权重区(9 个滑块/步进,实时显示各权重 + 正权和,和≠1 时提示"保存时后端自动归一"——**客户端不自算归一**,归一在后端 resolve)+ 阈值区(量比min/换手带 lo·hi/市值带 lo·hi·floor/横盘突破振幅·量比/单日软闸阈/活跃回看天数,数字输入或步进)。底部「保存」→ `PUT {config: 用户改过的全部当前值}` → 用响应回填(展示归一/夹紧后的生效值)+ 提示"下次刷新生效";「恢复默认」→ **`PUT {config: {}}`**(空 → 后端清用户行)→ 用响应(全默认)回填。
- 入口:挂在 `SettingsView`(现有设置屏)加一段/一个 `NavigationLink`(iOS)/区块(macOS)"选股参数",进 `ScreenConfigView`。**沿 SettingsView 跨端复用姿势**。
- `APIClient` 新增 `fetchScreenConfig()`(GET)+ `putScreenConfig(_:)`(PUT,走 `makeURL` 无 query)。**PUT 方法**:现有 `APIClient` 只有 `get`/`post`,新增私有 `put(_:body:)`(同 post,`httpMethod="PUT"`)。
- 客户端**只调参不重算**:保存后仅提示"下次手动刷新生效"(不自动触发 refresh);用户回候选页手动点刷新才生效——契约与"配置下次刷新读"一致。
- 双端 `xcodegen generate` + iOS Simulator + macOS `BUILD SUCCEEDED`;XCTest 全绿(config DTO 编解码 + 归一提示逻辑测试)。

---

### Phase C —— 候选刷新改纯手动(C1 后端,C2 前端可选)

**C1 验收(后端·删自动 tick)**:
- 删 `monitor/loop.py` 的 **15:35 自动 candidate refresh tick**:`monitor_loop` 里 `if _is_after_candidate_window(now) and last_candidate_date != now.date(): run_candidate_refresh(...)` **整段删除** + `last_candidate_date` 变量删除 + `_is_after_candidate_window`/`_CANDIDATE_AFTER` 删除。
- **`run_candidate_refresh` 编排函数是死码,直接删(订正·建议#11)**:`POST /candidates/refresh` 端点走 `app.py._recompute_candidates`、**从不经** `loop.run_candidate_refresh`;删自动 tick 后该函数无任何调用点 → **直接删除**(连同其单测改写/删除),不写"可保留复用"。
- **⚠ 保留不动**:① EOD 摘要 tick(`run_eod_tick` + `last_eod_date`,那是**持仓推送**,不是候选,grep 确认别误删);② **候选回测回填 `run_candidate_backfill`**(阶段2.5 F3,现与 refresh 绑在同一 if 块内)——把它**移出**该 if 块,**挂进现有 `elif _is_after_close(now) and last_eod_date != now.date():` 块内**(EOD 推送后顺跑,借 `last_eod_date` 天然每交易日一次)。
- **回填触发防重(钉死 · 重要#7)**:回填的"自扫描幂等"(`UNIQUE(entry_date,code)`)只防重复**落库**、防不了重复**打 Tushare**。若按字面 `if _is_after_close: run_backfill`(无日期守卫),15:05–24:00 每 5min 跑一遍、pending 时每条打 4 次全市场拉,1.6G ECS 整晚空耗+蹭限频。**故必须有每交易日一次的触发节流**:挂进 `last_eod_date` 守卫块(优先),或独立 `last_backfill_date` 守卫;UNIQUE 只作落库兜底、不作触发节流。
- `POST /candidates/refresh` 端点(经 `_recompute_candidates`)**保留不动**——删自动 tick 后它是**唯一**刷新途径。
- C1 验收:后端 pytest 全绿(删自动 tick + `run_candidate_refresh` 相关测试改写/删除,回测回填测试仍绿——验证回填不依赖已删的 candidate tick、每交易日仅触发一次);手动 `POST /candidates/refresh` 仍正常产候选;EOD 持仓摘要推送不受影响(grep + 测试双证)。

**C2 验收(前端·可选微调)**:候选页已有 trade_date 标新旧 + 手动刷新按钮(v1.3.0/阶段2 已做),**无需新功能**。可选:解释条/脚注文案微调为"候选为上次手动刷新结果,点刷新重算"(明确手动语义)。若无文案改动则本 Phase 前端零改动,仅需确认候选页刷新链路照常。

---

**接口契约汇总(v1.3.1 新增/变更)**:
| 端点 | 方法 | 变更 | 形状 |
|---|---|---|---|
| `/api/v1/screen/config` | GET | **新增** | `{config: 全量活配置(扁平单层), defaults: DEFAULT(扁平), updated_at:str|null}` |
| `/api/v1/screen/config` | PUT | **新增** | in `{config: 部分/全部键}`(空 `{}`=恢复默认清行) → 逐键夹紧存增量 → out `{ok:bool, config: resolve 后全量}` |
| `/api/v1/candidates` | GET | 变更 | candidate dict 新增可选 `warnLevel:"high"|"amber"|null`(**经 candidates 缓存表 `warn_level` 列往返**,第四次 migration);`score`/`warn` 不变 |
| `/api/v1/candidates/refresh` | POST | 不变 | 手动刷新入口(自动 tick 删除后成为唯一刷新途径) |

**待 v1.4(本版不碰,留指针)**:② 持仓教练深判重做(层2 盘中资金 T-1 失真 + 实时化边界:价/pnl/量/涨幅/VWAP 可实时、主力资金盘中缺)、③ 盘中选股独立板块(App 盘后/盘中分离,Level-2 资金缺口决策)。②③ 共享"实时价可得、实时资金不可得"同一数据现实,可能共用实时数据层。

## 4b. 客户端契约(设计稿钉死,阶段 1+ 生效)

设计权威参考:`design_handoff_linon/`(`DesignTokens.swift`+`Models.swift` 进 `client/` 工程)。以下契约由设计稿定死,后端按对应阶段实现。

- **数据形状**:`entry_snapshot` JSON = `{formNote, fundNote}` 两串;`DeepAnalysis`(三轴 form/fund/news 各 `{value, tone, text}` + `verdict`∈{可进/观望/不进} + `plan`)= **DeepSeek 结构化输出 schema**(阶段2 后端按此返回)。
- **算力分工**:后端只供 `price` + `flow3d`(主力近 3 日净流入串);客户端算 `pnl/pnlAmount/trackX/hitStop/dist*`。
- **规则常量单一事实源**:`-5%(触发)/ +15% / D4 / ±1% 容差带(-6%~-4%)` 定义一份,**后端监控(报警)与客户端展示共用,禁止各写一份漂移**。设计展示用 `hitStop ≤ -4.9`——**报警触发线口径定死为 `-5.0`**(展示侧 -4.9 仅作显示阈,触发判定一律引用 -5.0 常量;两端引用同一份)。
- **签名组件**(双端精确还原):DualLineTrack(marker `x% = clamp((pnlPct+5)/20*100, 2, 98)`)、HoldingDayPips(D1–D4,`should_force_close == (count==4)`)。
- **UI 锁定**:**绿涨红跌(国际惯例,用户明确选择,与 A 股本地相反,builder 勿"纠正")**;Liquid Glass 克制(仅栏/浮层/锁屏用玻璃,数据卡不透明白底)。
- **平台分叉**:共享核心(tokens/models/AppModel/签名组件/视图内容);分叉仅限导航壳(iOS 底部 TabBar / macOS 240px 侧栏)、KPI 布局、sheet vs 居中 modal;锁屏推送 iOS 专属。
- **教练拆分**:反情绪教练 **UI 壳在阶段2(AnalysisView)**,**"大脑"(调复盘历史 + 破纪律检测)在阶段3**。

## 5. Backlog / 用户侧收尾

### 用户侧收尾清单(builder 不碰)

- **阶段3 部署前置(高危迁移·首次真 migration 前必做)**:部署阶段3 前,ECS 上先 `sqlite3 linon.db "SELECT COUNT(*) FROM trades;"` **实测线上真实行数**(别盲信"设计假设空仓",若真有历史行则那些行 name/note=NULL,`GET /memory` 已兜底回 code),并 `cp linon.db linon.db.bak-YYYYMMDD` **备份一次**再跑 `_ensure_trades_columns` 的 ALTER。零成本兜底,标准高危区施工姿势。
- **阶段3.1 部署前置(第二次真 migration,candidates 表加 score 列)**:部署阶段3.1 前 `cp linon.db linon.db.bak-YYYYMMDD` 备份一次,再让服务重启触发 `_ensure_candidates_columns` 的 ALTER(幂等、只 log 不 re-raise)。`candidates` 是每日全量替换缓存、迁移风险低于 trades,但备份照旧做(§4.5)。
- **v1.3.0 部署前置(第三次真 migration,🔴高危·positions/trades 均有真实交易数据)**:部署 v1.3.0 前 `cp linon.db linon.db.bak-YYYYMMDD` 备份一次(比前两次更重要——positions/trades 是真实持仓/成交,非缓存),再让服务重启触发 `_ensure_v130_columns` 的 ALTER(`positions.industry` + `trades.qty/fee/net_pnl_amount`,幂等、只 log 不 re-raise)。存量已闭合 trades 的新列为 NULL(净额契约 nullable、原样传 null → 客户端显"—/未知",复盘 `netPnlTotal` 只 sum 非空行,不 500);存量 holding 持仓 industry=NULL(相关性护栏对 NULL 行业 → 跳过、降级不误报)。**行业映射预热**:v1.3.0 起 lifespan 启动/`GET /positions/correlation` 端点承担 `load_industry_map()` 预热,**开仓路径绝不联网**(只读缓存,冷缓存 industry 落空串,候选刷新回填)。
- **v1.3.1 部署前置(第四次真 migration,`candidates.warn_level` 列)**:部署 v1.3.1 前 `cp linon.db linon.db.bak-YYYYMMDD` 备份一次,再让服务重启触发 `_ensure_candidates_columns` 扩展的 ALTER(加 `candidates.warn_level TEXT`,幂等、只 log 不 re-raise)。`candidates` 是每日全量替换缓存、迁移风险低(旧行 warn_level=NULL → 输出省键 → 客户端 nil,前向兼容),备份照旧做(同阶段3.1 惯例)。**另**:v1.3.1 建 `screen_config` 表走 `CREATE TABLE IF NOT EXISTS`(非 ALTER,零风险),无额外前置。
- **prod 端到端完整闭环**(阶段1 收尾):本期 sandbox 链路已验通;剩 App 切 prod 环境 + 填 prod `API_TOKEN`(已生成)→ 注册 device token 到 prod DB → 真机开仓/监控真推完整走一遍。
- ~~**阶段2 部署到 ECS**~~:✅ 已部署上线(2026-06-28)。修两枚真环境坑(见 §6 + CLAUDE.md 坑4/5):① `sync.sh` `--exclude 'data/'` 误排 `app/data/`(阶段0/1 起数据层从没上 ECS)→ 锚定 `/data/`;② tushare `set_token` 写家目录炸 nologin `linon` 用户 → 改 `pro_api(token)` 直传。验通:refresh 71 候选 degraded=false、**内存峰 926MB/swap 0**(那台紧箱子扛得住)、`/analyze` 真 DeepSeek 合法卡、公网 HTTPS 200。`sync.sh`+`tushare_client.py` 两处修复 + 阶段2 全量**已 commit**(`716af79`)。
- **Tushare token / DeepSeek key 录入 ECS `.env`**(阶段2 部署前):两把真 key 已由用户提供、本地 `backend/.env` 已填(gitignored、未进任何 tracked 文件,供本地冒烟);**ECS `.env` 仍需写入 `TUSHARE_TOKEN`/`DEEPSEEK_API_KEY`** 部署后功能才生效(无 token→候选 `degraded:true` 空列表;无 key→深判降级占位卡,均不崩)。国内 ECS 直连 `api.deepseek.com` 无障碍。注意 **Tushare 聚合数据发布有几天到约一周延迟、会逐步补齐**(订正旧"滞后到 2026-05-06"误判;选股资金源已切东财 `moneyflow_dc`,6000 积分给到上一交易日,见 §6 变更日志)。
- ~~`.p8` 交接到 ECS~~:已搬(`/opt/linon` 下 600 `linon:linon`)。
- ~~iOS 真机 + 真签名验证~~:已通(ECS→APNs sandbox→真机推送 200,锁屏卡 + 动作按钮)。
- ~~ECS SSH 连接方式~~:已配(`deploy@118.178.122.194:/opt/linon`,公钥登录,`backend/.env` 已填三要素)。

### 用户网页操作清单(必须在网页手动办理)

- **Tushare 充值/积分**(阶段2):`https://tushare.pro/`(2000 积分会员)。
- ~~DNS A 记录 `ln.linotsai.top → 118.178.122.194`~~:✅ 已加并生效(certbot 证书已签)。
- ~~APNs 鉴权密钥(.p8)~~:✅ 已生成(Key ID `Q963AP3VY8`)+ App ID 已注册开 Push,`.p8` 已搬 ECS。

### reviewer 阶段1 推迟项(阶段2/3 启动前消化;全文见 `archive/REVIEW_REPORT_阶段1.md`)

- **(阶段3 前)`trades.open_time` 仅日期粒度**(🟡#3,`store.py:316`):存 `buy_date` 非开仓时刻,复盘算持仓时长会失真;阶段3 复盘前补真开仓时刻。
- ~~**(阶段2 前可选)周末/节假日录入 `buy_date` 落上一交易日**(🔵#1)~~ → **已排入阶段2 Phase D5**:改取下一交易日 + 开仓回包带 buy_date。
- **(运维)`deploy/linon.service` 仓库仍是阶段0 草稿**(🔵#4,`ExecStart=/usr/bin/true`)与 ECS 真 unit 脱节:把 ECS 真 unit(hardening + 正确 ExecStart)回写仓库作权威模板。
- **(打磨)客户端 `-4.9` 红卡 vs 后端 `-5.0` 推送**(🔵#2):pnl∈(-5.0,-4.9] 窗口横幅文案偏早,可改"逼近止损线"。
- **(打磨)EOD 推送"当日已推"依赖内存 `last_eod_date`**(🔵#3,`loop.py:211`):重启/错过窗口可能漏/重推,可落库防重启漏重推。
- **(打磨)开仓 `_resolve_name` 拉名失败落 code 当 name**(🔵#5);`Info.plist` 对 `127.0.0.1` 的 `NSIncludesSubdomains` 无意义(🔵#6)可删。

### reviewer 阶段2 推迟项(全 🔵 建议级,零致命零重要;全文见 `archive/REVIEW_REPORT_阶段2.md`)

- **(打磨)候选刷新基准日盘中不回退**(🔵#1,`loop.py:327`/`app.py:280`):手动 `POST /candidates/refresh` 在交易日盘中调用时 basis=今天、Tushare 当日 EOD 未出 → degraded(不崩、符合契约),拿不到昨日候选;可对"交易日但未过 15:35"回退上一交易日。
- **(打磨)`last_candidate_date` 内存防重**(🔵#2,`loop.py:327`):重启/错过窗口可能重算(upsert 幂等无数据损坏,仅冗余拉取);与阶段1 EOD `last_eod_date` 防重同源,**合并一并落库**。
- **(清理)`StockRow.total_mv_yi` 死字段**(🔵#3,`fetch.py:110,218`):已算未用;若不纳入市值过滤可删,纳入则标 TODO。
- **(可选)深判单票换手恒 `—`**(🔵#4,`analyze.py:85`):plan 未要求;想补则加单票 `ts_daily_basic(code, fund_asof)` 取 turnover_rate 喂 LLM。
- **(阶段3)coach `question` 未透传**(🔵#5,`AppModel.swift:343,360`)→ **已排入阶段3**:后端透传在 G4(端点已收 `body.question`→`analyze_stock`),客户端 composer↔coach 真问答接线在 H3。
- **(可忽略)`chgIsUp` 零涨幅染绿**(🔵#6,`AppModel.swift:310`):`0.00%`/`+0.00%` 判为 up(绿),中性本应灰,极小视觉边角。

### reviewer 阶段2.5 推迟项(全 🔵 建议级,零致命零重要;全文见 `archive/REVIEW_REPORT_阶段2.5.md`)

- **(可选)`analyze._fetch_form` 补单票除权跳变测试**(🔵#3):现有单测覆盖 `fetch.py` 路径的除权样例,`analyze.py` 单票路径对称位置未补一条含除权跳变因子的样例(验 pct_60d 复权后与不复权不同 + join 命中);与 fetch 路径对称补一条即可。
- **(清理)`backtest.py` 回填多拉一次 entry 当天 daily**(🔵#4):回填读 entry_date 后第 1/2/3 个交易日的 daily 之外,实现额外拉了 entry 当天(共 4 次而非文字描述的 3 次);无害(仅多一次 API 调用,不影响 `ret_3d` 计算正确性),可作小优化去掉。
- **(清理)`schemas.py` `OutcomeTierStat` 模型定义未使用**(🔵#5):`OutcomesStatsOut` 的三维度字段实际用 `List[Dict[str, Any]]`,`OutcomeTierStat` 无引用;可删,或收紧为三个子模型类型让 schema 更严。

### reviewer 阶段3 推迟项(全 🔵 建议级,零致命,1 个 🟡 已修复;全文见 `archive/REVIEW_REPORT_阶段3.md`)

- **(打磨)周末/节假日开仓的 `openHoldings.tradeDay` 可能显 D0**:`_current_trade_date` 周末录入取 `next_trading_day`(D5 正确行为,未来日期),但 `aggregate_week` 的 `openHoldings[].tradeDay = count_holding_trade_days(buy_date, today)` 在 buy_date 尚未到达时闭区间交易日数算 0。阶段2 D5 遗留副作用,非阶段3 引入;展示"D0"轻微怪但很快自愈(不误导),不阻断。可选修法:复盘展示侧对 `tradeDay<1` 显示"D1(待开盘)"。
- **(可忽略)`test_list_closed_trades_no_status_filter_in_sql` grep 守卫 `status=` 子串偏宽**:纯防回归守卫,子串匹配比 AST 检查脆(若未来函数正当引用 `status='holding'` 会误报),当前无该引用故通过;可忽略不改。
- **(清理)`store.py` `insert_review` 遗留死码**:阶段0 建、阶段3 端点已改用 `upsert_review_note`,仅 `test_db.py` 引用、无生产调用点;非阶段3 引入,留未来 cleaner 清理。
- **(backlog)H3 composer↔coach 真问答未接**:H3 后端 `question` 透传链路已完整(`coach_position` 收 `body.question` → `analyze_stock(question=)` → prompt 附【我的问题】节),但客户端 `sendComposer` 仍走本地固定文案、`runCoach` 恒传 `question=nil`,未真正打通用户在 composer 里追问 → 后端 DeepSeek 真回答的闭环。reviewer 确认此偏离在 H3 正式验收范围之外(H3 验收只列 review_ref 引用块显示/无历史消失/双端 build/端到端联调 4 项),属合理范围收敛,非缺陷。留未来版本(阶段4 或某个小版本)接上 `sendComposer` 真调用。

### 选股增强候选(杨永兴"一夜持股法"信号借鉴)→ 已升级为阶段 3.1 正式 Plan,已完工收口

> 原 Backlog 6 类信号已于 2026-07-02 立项为阶段 3.1(纯后端选股信号增强 + 候选打分展示),2026-07-02 完工收口,全文归档 `archive/stage3.1_选股信号增强_plan.md`。此节保留一行索引,不再展开。

### reviewer 阶段3.1 推迟项(全 🔵 建议级,零致命零代码级重要;全文见 `archive/REVIEW_REPORT_阶段3.1.md`)

- **(已知接受模式,不阻断)`upsert_candidates` 不在 `_recompute_candidates` 的 try 外层保护范围内**:若 ALTER 迁移极端情况静默失败(列缺失,概率极低),INSERT 硬编 `score` 列会抛 `no such column` → `POST /candidates/refresh` 500(EOD tick 由 loop 外层 try 吞,不掀翻轮询)。与阶段3 `trades` INSERT(name/note 无条件入列)完全同款,项目已接受的先例;不改代码,记录在案。
- **(已收口)DDL 注释**:`candidates`/`trades` 两张表的 `CREATE TABLE` 语句已各补一行注释,指明 `score`/`name`+`note` 列由对应 `_ensure_*_columns` 迁移函数补充、不在 DDL 里(`backend/app/db/store.py`)。
- **(已知接受行为,不阻断)部署后首个 refresh 前旧缓存行显示"0 分"**:值域 `[10,100]` 之外,是 plan §4.1 已拍板的 NULL→0 兜底行为,≤1 交易日(15:35 下次 refresh)自愈,不需要改代码。
- **(测试加固,留未来)`test_form.py::test_had_limit_up_from_qfq_no_false_positive_on_dividend`**:现有样例传入已复权平滑序列,建议未来补一版走"raw 跳变 + adj_factor → qfq → compute_form"组合路径的对照样例(送股 raw+adj 复权后无假涨停 / 同 raw 不复权反证会假涨停),把复权必要性更严格地锁进门禁。
- **(测试加固,留未来)`CandidatesAnalysisTests.swift::CandidateScoreDecodeTests`**:前向兼容测试代理解码 `Candidate`(public)而非列表实际路径的 `CandidateListDTO`(private,无法直测);两者同为 synthesized optional decode、行为等价,是合理代理,未来可在测试注释里点明这层间接性。

### v1.2.1 立项发现(plan-critic 提出,本版本不动)

- **`/analyze` 端点 `_maybe_persist_verdict` 同款降级污染隐患**:`POST /candidates/{code}/analyze` 的 `_maybe_persist_verdict`(app.py:357)只查 `verdict in _VERDICTS`,DeepSeek 降级返回的"观望"会照落 `analysis_verdicts`(覆盖式 upsert),理论上真"可进"可能被一次降级观望覆盖污染回测。v1.2.1 只给**新增的 `/chat` 端点**加了 `not degraded` 落库门槛(对话 thread 重开频繁,污染概率高);`/analyze` 是 on-demand 单次触发、污染概率低,**本版本不动其行为**,留未来给 `degraded_analysis` 补 degraded 标记后统一收口。

### reviewer v1.2.1 推迟项(全 🔵 建议级 + 1 遗留,零致命零重要;全文见 `archive/REVIEW_REPORT_v1.2.1.md`)

- **(打磨)composer loading 时未禁用**:发送中可并发再次点发送,产生双份 `is_first` 请求;可给 composer 输入框/发送按钮在 `analysisLoading` 时禁用。
- **(测试加固)`chatTurns` while 修剪分支无测试覆盖**:截断逻辑"从 user 边界起、保留最近一条 assistant"的 while 循环分支未补对应单测,行为靠人工验证。
- **(测试加固)两条 `chat_stock` 降级测试受前序缓存影响**:进程内 `(code,date)` 事实缓存改 `and` 条件后需复核这两条降级测试是否仍独立可信(不因跑序污染)。
- **(测试环境)`test_chat_missing_key` 本机有真 token 时会单测联网**:该测试依赖环境无 `DEEPSEEK_API_KEY` 才触发降级路径,本机若已配置真 key 会绕过降级分支实际联网。
- **(清理)`_chat_fact_cache` 旧键不清除**:进程内 dict 缓存按 `(code,date)` 键只增不减,单用户长期运行体量可控可接受,重启即清。
- **(清理)客户端死代码**:`analyzeCandidate` 已无调用点、`ChatResult.degraded` 字段解出后未被读取,可删。
- **(打磨)`/chat` 后端无 `messages` 条数上限**:客户端已截断到 8 轮,但后端未做防御性上限校验,理论上可传超长 messages 拖慢/拖垮请求。
- **(遗留)`build_user_prompt:84-86` 同款硬编"中间地带"**:阶段2 遗留的硬编中间地带措辞,v1.2.1 已在对话层 `build_chat_context_block` 改为按 pnl 派生,但结构化 `/analyze`/`/coach` 走的 `build_user_prompt` 同款硬编仍在,留 Backlog 统一收口。

### reviewer v1.3.0 推迟项(全 🔵 建议级,🔵1 已修复;全文见 `archive/REVIEW_REPORT_v1.3.0.md`)

- **(已知接受)`_ensure_v130_columns` 四 ALTER 共用一个 try**:PRAGMA 探测缺列后四条 ALTER 语句包在同一个 try/except 里,任一列 ALTER 失败会连坐影响后续列(partial 失败)。Plan 已按"best-effort、只 log 不 re-raise"姿势设计,记录接受、不改代码。
- **(打磨)导出同花顺 TXT 的分享/写入体验**:iOS `ShareLink` 分享的是纯 `String`(非 `.txt` 文件),macOS `try? write` 静默吞写失败错误。可打磨为分享真正的 `.txt` 文件 + 写失败时给用户提示。
- **(打磨)`checkCorrelation` 无乱序响应防护**:快速改代码触发多次相关性查询存在 race,末位到达的响应会覆盖前面的(而非请求发出顺序),可加请求序号丢弃过期响应。
- **(已知接受)`costs.py` 银行家舍入偏差**:`round(…, 2)` 银行家舍入(round half to even)在半分位可能与部分券商的四舍五入相差 1 分,Plan 已按此实现,记录接受不改。
- **(清理,留未来)`_ensure_v130_columns` 迁移测试两个未用 fixture 形参**:测试函数签名里声明了但未实际使用的 fixture 参数,下次碰这块顺手清。
- **(环境备注)macOS test destination 测试宿主解析 quirk**:主会话验证发现 macOS `-destination 'platform=macOS' test` 有预存在的测试宿主解析问题(`.xcodeproj` 与 committed 版本逐字节一致,非 v1.3.0 引入),本轮 XCTest 门禁改走 iOS Simulator、macOS 侧用纯 build 验证;供后续 reviewer/builder 知晓,避免误判为回归。

### iOS 快捷指令截图录买卖(设计已讨论,未立项,下一版本候选)

> 2026-07-02 用户提出、已讨论定型架构,**未开工**,待用户后续下达立项指令再召唤 planner。目标:买/卖完在同花顺App截图后,通过 Apple 快捷指令自动把该笔买入/卖出录入 LinoN,免手动敲代码/价格/数量。

**已定型的架构**(讨论中逐步收敛,记录下来避免下次重新推导):

1. **触发方式 = Apple 快捷指令(用户自建,不是 LinoN App 内代码)**,买/卖各一条快捷指令(触发时用户自己知道是买是卖,不需要系统去猜)。
2. **OCR 用快捷指令内置动作**"从图像中提取文本"(苹果原生 Vision OCR,免费、零 LinoN 代码):快捷指令步骤 = 取最新截图 → 提取文本 → "获取URL内容"POST纯文字(+买/卖标记)到 LinoN 后端新端点(带现有 `API_TOKEN`)。**客户端不需要相册权限、不需要 Vision 框架代码、不需要新 UI 入口**——这是相对最初讨论方案(客户端内 Photos picker + Vision 框架)的简化版,工作量小很多。
3. **后端新端点**:收纯文字(同花顺买入/卖出确认页 OCR 出来的文字)+ 买卖标记,喂 DeepSeek 做结构化提取(复用 `analyze.py`/`deepseek.py` 现有的 system prompt + 严格 JSON schema + 服务端校验夹紧 + 失败降级模式,不是新架构),返回 `{code, name, price, qty}`。**只传文字不传图片**,图片不离开用户手机。
4. **回传 App 用自定义 URL Scheme**:快捷指令拿到后端返回的 JSON 后,拼 `linon://open?code=...&name=...&price=...&qty=...`(买入)或 `linon://close?code=...&price=...`(卖出)唤起 App;App 加一个 URL Scheme handler,把这几个字段**预填进现有的开仓/清仓 sheet**(不新建确认 UI,复用现成的、已经打磨过的表单)。
5. **人工确认闸门不动**:URL 唤起只是预填表单,用户仍需在 sheet 里过目/可改/手动点确认,提交走**现成的** `POST /positions/open` / `POST /positions/{id}/close`,不新增开仓/清仓逻辑,不碰 stop_line 派生/buy_date 派生/满仓校验等任何已锁定契约。
6. **截图来源固定同花顺**(用户已确认,格式相对稳定),但用户不介意文字过后端,故提取逻辑放后端 DeepSeek(方案B),没有采用纯客户端正则方案(方案A)。

**未决细节(留给 planner 展开时定)**:DeepSeek 提取 prompt/schema 具体字段与容错(同花顺买入页 vs 卖出页字段差异、佣金/规费等噪声文字怎么过滤);卖出场景如何从 OCR 出的代码匹配到具体哪个 `position_id`(现有持仓最多 3 票,按 code 匹配持仓表即可,但要处理"同代码不在持仓"的降级文案);URL Scheme 传参的长度/编码边界(中文名称需要 URL encode);新后端端点鉴权与现有 `require_token` 是否复用;快捷指令本身的具体步骤配置需要输出成一份用户可照抄的教程(不在代码范围内,是"用户网页/手机操作清单"性质)。

### 用户流程坑清单(走查沉淀,分阶段回填)

> 阶段1 条目已折叠进 §4 对应 Phase,下方保留为可追溯索引;阶段2/3 条目待后续回填。

- ✅折叠 A.2/B.3 — **录入是关键单点故障**:开/清仓录入须回传成功/失败确认;漏录→幽灵持仓(监控空盯+假警报+`trades` 不闭合+D4 空跑);成交价手敲易错需校核。
- ✅折叠 A.3/B.4 — **推送需 T+1 与涨跌停感知**:买入日命中硬线只说"记录,明日开盘处理"不喊"必走";一字跌停说"封死,明日处理"。
- ✅折叠 A.4/B.4 — **硬线推送需升级/重复至确认**(录动作或 dismiss 才停),单次 APNs 易被漏。
- ✅折叠 A.3 — **实时多源归一一致性校验**(Sina/Tencent 的 pre_close/除权口径差→假报警)。
- ✅折叠 A.1 — **录入 API 加 token 鉴权**(单用户,顺手)。
- ✅折叠 C.3 — **ECS→APNs 真实可达性/延迟一上来就真机实测**(进程活着但推不出去更隐蔽)。
- ✅折叠 A.5 — **盘后 EOD 摘要**(每持仓盈亏%/D几/明日 D4 预警 + 资金校验占位降级)。
- (阶段1 末/可滑 backlog)**盘前~09:00 今晨待办推送**(强制卖出/+15%/中间地带)——本期主线不含,A.5 落地后视余量做。
- (阶段2,**本期暂不做**)**系统持仓 vs 券商现实对账**:定期"你现持有这 N 只对吗""持有 N 天无任何记录动作"提醒,防无声漂移。本期靠 A.2 录入防护(拒重复/拒满仓/拒非持仓)做第一道,完整对账推后。
- (阶段2)**满仓闭门联动**:持仓达 3 → 候选列表闭门(🔒);清掉一只 → 候选按 `5 × 空仓位` 重开。**(UI 已设计;后端粗筛截断待阶段2)**
- (阶段2)**候选列表是 EOD/拉取式**,结构上只服务 D 型(次日续强)进场、不喂 A 型盘中突破——认账写清(正好对治盘中追高病根);A/C/D 进场时机可行性据此校准。
- (阶段2)**on-demand 深判延迟 vs 时间敏感进场**的张力;深判界面显著标注"资金面=截至昨日 EOD,今日盘中资金未知"。
- (阶段2/3)**中间地带不能纯拉取**:持仓恶化(逼近线/量能萎缩/主力撤)转主动推,否则反情绪教练永不触发;中间地带核心依据(主力资金)EOD 滞后,建议里诚实标注。
- (阶段3)**复盘"垃圾进垃圾出"**:依赖录入保真,需配合对账;复盘须**同时读未平的 `positions`**(扛过周末的套牢票只在 positions 不在 trades),不能只读闭合流水。**(ReviewView 已按"同时读未平 positions"设计;后端 Reviewer 待阶段3)**

### 待后续阶段细化(阶段2+ 不动)

- **`design_handoff_linon/` 为客户端设计权威参考**;`DesignTokens.swift`+`Models.swift` 进 `client/` 工程(阶段0 纳入作契约,阶段1+ 照终稿重建)。
- **-10% 极强趋势止损例外**(后期细化):当前砍除,止损统一 `buy×0.95`;届时若恢复,`stop_line` 改为落库列。
- 实时行情多源兜底细节(限频退避、源健康探测、第三源)——用户处理,实现细节阶段 1 打磨。
- DeepSeek 前置词/skills、选股过滤排序、复盘闭环、反情绪教练 —— 阶段 2/3。

## 6. 变更日志

> 每条 = 摘要 + 关键决策/偏离 + archive 全文指针。过程细节、逐 Phase 记录、plan-critic 逐轮修订一律在 `archive/`,此处只留可追溯索引。

- **[2026-06-20] 立项**:v2 设计蒸馏为权威 PROJECT_PLAN.md,锁定 4 项施工决策(持仓计数 D1 起算 / 日历静态兜底 / rsync 部署 / venv+requirements),进入阶段 0。
- **[2026-06-21] 用户视角走查修订**:锁定空仓起步、止损 -5% 自动派生 + ±1% 执行容差;修正阶段0 契约(`trading_window` 两段 / Quote 补涨跌停价 / `positions` 止损线改派生去手填);"用户流程坑清单"入 Backlog 分阶段回填。
- **[2026-06-21] 设计稿并入**:客户端 hi-fi 完成稿到位(`design_handoff_linon/`),路线图重切后端/前端双轨、锁 iOS+macOS 多平台。**关键决策**:-10% 极强趋势止损例外砍除,止损统一 `buy×0.95` 纯派生不落库(schema 移除 `stop_line` 列);收编客户端↔后端契约新增 §4b;monorepo 重组 `backend/`+`client/`。
- **[2026-06-21] 阶段0 完工(0.1–0.7)**:数据层四件套 + 部署脚手架 + 冒烟脚本落地,pytest 40 绿,git init 首提交。**偏离**:`trades` 照 plan DDL 建、未加 Models.swift 的 `name`/`note` 列(留阶段3)。全文 `archive/stage0_基建_plan.md`。
- **[2026-06-21] 阶段1 track A(后端脊椎)完工**:FastAPI(:8001,单 unit——监控作 app 内后台 asyncio 轮询)+ 6 端点(Bearer 鉴权)+ 3 硬线监控(止损/止盈/D4,T+1 感知)+ APNs JWT 升级状态机 + EOD 摘要,pytest 96 绿,本地 curl 闭环。规则常量单一源复用 `store.py`。全文见阶段1 归档。
- **[2026-06-21] 阶段0 归档 + 阶段1 立项**:阶段0 §4 全文移 `archive/stage0_基建_plan.md`;阶段1 Plan(A 后端脊椎 / B 客户端地基 / C 部署)落定——端口 8001、API 单密钥鉴权、子域名 `ln.linotsai.top`、监控单 unit、APNs sandbox 网关。
- **[2026-06-21] 阶段1 track B(客户端)完工**:SwiftUI iOS+macOS 多平台 App 地基(工程/AppModel/导航壳/两签名组件/TodayView/开清仓 sheet/iOS 推送),双端 `BUILD SUCCEEDED`,client 17 + 后端 98 绿。**唯一允许的后端改动**:`GET /positions` 按需拉一拍实时价填 `price`(拉价失败 price=0 客户端兜底)。iOS ATS/marker 钳 98 等实现坑记 CLAUDE.md。
- **[2026-06-22] iOS Settings 屏(小增量)**:共享 `SettingsView`(环境 dev/prod + API Token + 连接自检 + iOS 重注册推送),双端绿,仅动客户端。
- **[2026-06-22] 阶段1 审后修复(reviewer 🟡#1/#2)**:#1 监控每 tick 拉价 3→2(复用 `two_source_fn` 派生 price);#2 D4 时间升级重启不丢(lifespan `rebuild_time_escalations` + 每 tick `_ensure_time_escalation`,幂等靠 `has_track`)。**未触碰契约**,pytest 105 绿。机理详见 CLAUDE.md 阶段1 track A + `archive/REVIEW_REPORT_阶段1.md`。
- **[2026-06-22] 阶段1 track C(ECS 部署 + 真机 APNs)完工**:真上 hz ECS(nologin `linon` 用户 + `/opt/linon` + nginx + certbot + systemd 单 unit active),ECS→APNs sandbox→iPhone 真机推送实测 200(锁屏卡 + 动作按钮)。修真机才暴露的接缝(category 对齐 / iOS entitlement / rsync 守卫 / setgid 复原)。
- **[2026-06-22] 阶段1 收口归档**:三轨完工并上线 `https://ln.linotsai.top`,reviewer 零致命,审后修复 #1/#2 已部署,pytest 105 绿。§4 全文移 `archive/stage1_脊椎今日台_plan.md` + `archive/REVIEW_REPORT_阶段1.md`,推迟项入 §5。
- **[2026-06-23] 阶段2(选股+决策)立项**:§4 落定 6 Phase(后端 D1–D5 / 前端 E1–E2)。**关键选型**:全市场 Tushare 按 `trade_date` 单次拉 + pandas 内存粗筛、只落当日候选;DeepSeek `response_format=json_object` 强制结构化 + 降级占位卡;白酒黑名单用 `stock_basic.industry` 行业分类;候选刷新 15:35;铁律"技术面交 LLM 判"。规则常量单一源仍在 `store.py`/`rules.py`。
- **[2026-06-23] 阶段2 后端 D1–D5 完工**:新建 `app/screen/` + `app/llm/` + 4 端点 + `candidates` 缓存表,pytest 183 绿,真 key(Tushare+DeepSeek)冒烟过。全链路降级(缺 Tushare→degraded 空列表 / 缺 DeepSeek→占位卡 / 舆情失败→news neutral)。字段口径、白酒 industry 归类等细节记 CLAUDE.md。
- **[2026-06-23] 阶段2 前端 E1/E2 完工**:CandidatesView + AnalysisView 双端 + 满仓闭门联动,client 32 绿,双端 `BUILD SUCCEEDED`,未碰 `backend/`。客户端实现坑(camelCase DTO / `@MainActor` / fullScreenCover 隐 TabBar / ImageRenderer 不渲 ScrollView / iOS≠macOS 行布局 / Dock 守卫)记 CLAUDE.md。
- **[2026-06-23] 阶段2 审查 + 收口归档**:reviewer 亲跑门禁 + 真 key 活体冒烟,零致命零重要 6 建议(~97% 完成度)。§4 全文移 `archive/stage2_候选决策_plan.md` + `archive/REVIEW_REPORT_阶段2.md`,6 建议入 §5。
- **[2026-06-28] 选股资金源切东财 `moneyflow_dc`(6000 积分)**:替代原始 `moneyflow`(发布延迟),读 `net_amount`(万元,东财主力口径 = 超大单+大单)。**顺手一并修**:测试日期脆弱(冻结 today)、黑名单统一收为板块整段正则 `^(30|688|689|8|4|920)`(消枚举精确子段漏挡 301/689/920)。pytest 193 绿。口径与"黑名单按板块整段"教训记 CLAUDE.md。
- **[2026-06-28] 阶段2 部署上线 ECS**:refresh 71 候选 degraded=false、内存峰 926MB/swap 0、`/analyze` 真 DeepSeek 合法卡、公网 HTTPS 200。**修两枚真环境坑**:`sync.sh --exclude 'data/'` 误排 `app/data/`(阶段0/1 起从没上 ECS)→ 锚定 `/data/`;tushare `set_token` 炸 nologin 家目录 → `pro_api(token)` 直传。详见 CLAUDE.md 坑4/5。
- **[2026-06-28] 候选页 iOS 解释条布局快修**:定宽 pill 与可压缩文本同 HStack 窄屏挤成竖排 → 平台分叉(iOS VStack / macOS 横排)。
- **[2026-06-28] 幽灵 App 图标角标快修(iOS)**:`PushManager` 全程无清角标逻辑致图标红点残留 → 加 `clearBadge()`(启动/前台/ack 三处清零,iOS 26 `setBadgeCount`)。
- **[2026-06-28] 候选页补手动刷新按钮(iOS+macOS)**:APIClient 从未接 `POST /candidates/refresh` → 补 `refreshCandidates()`(90s 长超时,全市场拉取实测 ~39s)+ 双端刷新按钮。
- **[2026-06-29] macOS 候选页布局快修(minWidth 920→1080)**:窗口开在 minWidth 致内容区容不下候选列宽、右侧深析/刷新按钮被裁 → 撑 minWidth(此修不彻底,见下条)。
- **[2026-06-29] macOS 窗口 sizing 真修**:根因不是 minWidth 数值,是 `.windowResizability(.contentSize)` 把窗口锁死在系统记住的旧 frame → 改 `.contentMinSize` + `.defaultSize(1240×780)` + 清 stale frame 键 + `alignment:.leading` 兜底。**教训**:macOS 窗口尺寸先查 windowResizability + 持久化 frame,且必真窗口截图核对(ImageRenderer 组件级快照不暴露窗口 sizing)。
- **[2026-06-29] 夜间模式不可见快修**:App 为浅色稿、token 无深色变体 → `.preferredColorScheme(.light)` 强制浅色外观。真·深色模式留阶段4。
- **[2026-07-01] 阶段2.5(选股数据质量 + 信号回测)立项**:纯后端 4 Phase——① 技术指标补前复权(新建 `app/screen/form.py`,消 `fetch.py`/`analyze.py` 两处重复);② 候选信号事后回测(N=3 交易日,新表 `candidate_outcomes`/`analysis_verdicts` + 只读 `GET /candidates/outcomes`,不接客户端)。plan-critic 两轮修订(复权方向钉死 / 回测收益改 `pct_chg` 累乘 / Tushare 限频评估 / verdict join 取 entry_date)全文见阶段2.5 归档。
- **[2026-07-01] 选股排序资金因子改相对口径快修**:资金因子用绝对金额 min-max 归一系统性偏大盘股(量纲不一致,设计层疏漏)→ 改喂 `net_amount_rate`(净额占成交额比%)相对口径,绝对值字段保留供粗筛。pytest 193 绿。
- **[2026-07-01] 阶段3(复盘闭环)立项**:§4 落定 7 Phase(后端 G1–G4 / 前端 H1–H3)。**关键选型**:打分=聚合 `trades.kept_*` 布尔做 ISO 周确定性统计(零 LLM);复盘 on-demand 实时聚合不预落表、不加定时任务;`trades` 补 `name`/`note` 两列(首次真 migration,PRAGMA 探测 + try/except 只 log 不拖垮 startup);教练大脑中性 `history_digest` 进 prompt / 带情绪 `review_ref` 只回展示,两路径严格隔离 + `SYSTEM_PROMPT` guardrail。plan-critic 两轮修订记阶段3 归档。
- **[2026-07-01] 阶段2.5 完工收口**:F1–F4 落地,reviewer 零致命零重要 6 建议。前复权 `form.py` + 回测 `backtest.py` + 2 新表 + `GET /candidates/outcomes`;真 token 冒烟 `adj_factor` 65/65 天零限频(45.7s)。pytest 227 绿。**订正**:`min_trade_days=4` 经 reviewer 验算为正确值(代码未改,plan 文字订正)。§4 全文移 `archive/stage2.5_选股数据质量_plan.md` + `archive/REVIEW_REPORT_阶段2.5.md`。
- **[2026-07-01] 阶段3 完工收口**:G1–G4 + H1–H3 落地,reviewer 零致命、1 重要已修、4 建议入 Backlog。`review/score.py` 确定性打分 + 3 端点 + `trades` name/note 首次真 migration(幂等原子性验证达标)+ 教练大脑两路径隔离。**已修重要**:`GET /review`/`POST /review/{week}/note` 非法 week 抛未捕获 `ValueError`→500 已加 try/except 返 422(真 HTTP + pytest 验过)。**H3 偏离(reviewer 确认合理)**:composer↔coach 真问答未接线,留 Backlog。pytest 276 / client 40 绿。§4 全文移 `archive/stage3_复盘闭环_plan.md` + `archive/REVIEW_REPORT_阶段3.md`。
- **[2026-07-02] 阶段3.1(选股信号增强)立项**:把 §5"选股增强候选"(杨永兴"一夜持股法")6 类信号以纯软信号(排序 4→8 键 + 深判 prompt + warn 软闸,零新硬排除、零新 Tushare 接口)融入选股;用户 review 后追加候选卡展示当日相对分 `score`([10,100] 池内归一、不跨天可比,客户端 `Int?` 前向兼容),范围扩为后端 + 客户端小改。plan-critic 两轮抓住 5 风险点(迁移链路断层 / 信号5-6 打架 / 涨停数据源口径 / 客户端前向兼容 / 归一边界),记阶段3.1 归档。
- **[2026-07-02] 阶段3.1 施工完工 + 审查 + 收口**:Phase A–D 落地。**candidates 表加 score 列——项目第二次真 migration**,复用阶段3 PRAGMA+ALTER 姿势,施工用 builder-pro(Opus,高危区)。reviewer + 主会话独立复审零致命零代码级重要,5 建议入 §5(1 条 DDL 迁移注释已顺手补上)。pytest 309 / client 44 绿。§4 全文移 `archive/stage3.1_选股信号增强_plan.md` + `archive/REVIEW_REPORT_阶段3.1.md`。
- **[2026-07-02] 文档收口**:压缩本变更日志(每条阶段完工原为长篇小作文、全文已在 `archive/`,按规范收敛为"摘要 + 关键决策/偏离 + archive 指针",§6 由 ~27k tokens 减到约 1/6);三个根级历史设计文档(`交易系统_ProjectPlan_v1/v2.md`、`交易系统_施工总结_v1.md`)移入 `archive/`,§1 设计源指针同步改指 `archive/`。纯文档整理,不动代码/契约。
- **[2026-07-02] store 拆包重构**:`app/db/store.py`(909 行 god-module)按实体拆为 `app/db/store/` 包(constants/_common/schema/positions/trades/review/device_tokens/candidates/outcomes),`__init__.py` 原样 re-export 全部公开 API + 外部私有名,**所有调用点零改动**;规则常量单一源移到 `store/constants.py`(import 口径不变)。坑:`close_position` 经 facade 取 `insert_memory` 以保 monkeypatch 可拦截(记 CLAUDE.md)。纯结构重构,pytest 309 无回归(重构前后同数)。
- **[2026-07-02] 候选页 macOS 两处前端小修**:① 删掉工具栏假的「排序:放量强度 ▾」静态标签(不可点、后端无 sort 参数、且口径错——真实排序是 8 因子综合分而非放量;分数列+权重 chip 已说清);② 给 macOS `columnHeader` 补「分数」表头(阶段3.1 Phase D 加了行内 54px 分数格却漏表头,顺带修正右侧列 66px 错位)。仅动 `CandidatesView.swift`,macOS build 通过、已 Release 换包 `/Applications`。附:该页"全 0 分"经排查为**旧缓存 NULL 分数**(阶段3.1 打分 `_normalize_scores` 归一 `[10,100]` 不产 0),刷新重算即恢复,非代码 bug。
- **[2026-07-02] 深析/教练超时快修**:点「深析」报"网络错误"——根因是 `analyzeCandidate`/`coachPosition` 用客户端 `post` 默认 **12s** 超时,而两端点后端**同步走 DeepSeek(超时 30s)+ 舆情/行情拉取**常 >12s → URLSession 超时误报 `.transport`(非真断网)。同款坑 `refreshCandidates` 早用 90s 修过(全市场 ~39s),这是同源第 2/3 处。修:两端点客户端超时提到 **60s**(> 后端 30s DeepSeek 超时,慢时后端先返降级 200 占位卡)。仅动 `APIClient.swift`,macOS build 通过、已 Release 换包。
- **[2026-07-02] ECS→DeepSeek 偶发卡死 → 重试快修(真环境·已上线)**:客户端超时修完后露出后端"调用异常 ReadTimeout"降级卡。上 ECS 只读诊断确认**非资源/非 MTU/非 DeepSeek 慢**——内存/负载全闲、`ping -M do` 1500B 全通、DeepSeek 从 Mac ~4s·从 ECS 连打 8 次全 <1s;**是 ECS→api.deepseek.com(腾讯 EdgeOne CDN)偶发单连接读响应体卡死**(`TTFB=0.2s` 秒回但 `total` 打满超时空体)。修 `deepseek.py`:**短读超时(12s)+ 每次全新连接重试(3 次)**,好连接亚秒~数秒、撞卡死的快速放弃重试;最坏 36s < 客户端 60s。pytest 309 无回归;单文件热补丁 scp 到 ECS + restart,3/3 `/analyze` 端到端返真实卡 ~3.3s 验通。详见 CLAUDE.md 坑6。
- **[2026-07-02] v1.2.1(深析对话化 + 追问接 DeepSeek)立项**:§4 落定 4 Phase(A 后端对话端点 / B 候选行按钮 / C 前端对话渲染 / D 全量部署)。**核心架构决定(6 条,已拍死)**:① 新增统一多轮对话端点 `POST /chat`,**不合并进** `/analyze`/`/coach`(二者结构化输出被回测链路 `analysis_verdicts` + coach 红橙卡依赖,保留不动);② 对话 = prose `reply` + 旁路抽 `verdict` 落库(仅候选首条对话落 `analysis_verdicts`,不断回测链路);③ 后端无状态,多轮上下文客户端持有、每次全量回传(截断保留最近 8 轮)、不落会话表;④ 资金/形态事实由后端 `_fetch_form`/`_fetch_fund` 注入 context(不靠模型编)、`fund_asof` 随响应返回;⑤「全仓买入并录入」按钮从三轴卡搬到对话区(首条 assistant 气泡下、verdict==可进 时显);⑥ 守味隔离沿阶段3——对话端点**只注入 history_digest,绝不注入 review_ref**。coach 触损红橙卡入口不变(不改对话式),只有候选深析(openAnalysis)+ composer 追问走 /chat。含一次全量部署(顺带带上未部署的 store 拆包重构,不再单文件热补丁)。**plan-critic 一轮修订(3 致命 + 5 重要,均已改)**:致命——① 对话 prose 生成慢会被 `/analyze` 的 12s×3 超时系统性掐死降级 → 对话单列超时常量(read 25s×2)+ reply 限长 250 字 + `max_tokens=700`(决定7);② 降级"观望"覆盖式落 `analysis_verdicts` 污染回测 → `chat/degraded_chat` 加 `degraded` 标记、落库门槛收紧 `not degraded`(决定2);③ 追问 mode 复用 UI 状态 `chatMode` 会把持仓中间地带当候选发出丢 position_id + `.coach`/`.analysis` role 序列化撞后端 422 → mode 改按 `holding(byCode:)` 业务判、role 显式映射收敛到 user/assistant 两值(C3)。重要——④ 买入按钮判定钉死 `firstVerdict`/`firstAssistantMsgId` 只在 isFirst 写(防追问翻脸按钮回溯消失);⑤ `.analysis` 渲染分支承认是死代码删除(DeepAnalysisCard 本体留给快照测试),不用"coach 卡仍用"不成立理由保留;⑥ 事实块每轮注入 + 进程内 `(code,date)` 缓存免重拉;⑦ Phase D 拆两步部署(先 store 拆包收欠账、再 v1.2.1)+ stale 单文件/pyc 清理检查 + 回滚 SHA;⑧ 客户端漏改的 `AnalysisView:264/266` 两处 sendComposer 调用点补 async。`/analyze` 同款降级污染隐患记 §5 Backlog(本版本不动)。待 plan-critic 复核 3 致命是否堵死。
- **[2026-07-02] 深析资金源修正:切东财 `moneyflow_dc`(6000 积分)+ fund_asof 如实标注(真环境·已上线)**:用户发现深析卡「主力净流出」与候选列表「+4473万流入」及其同花顺 App 相反。查因:**深析层 `analyze.py` 误用原始 `moneyflow`(同花顺式,与东财口径不同、能符号相反),没用上 6000 积分买的东财 `moneyflow_dc`**;且 `fund_asof` 写死 `prev_trading_day`,盘后把 07-02 的数据误标成 07-01。实测四源(用户同花顺 +1627 / 东财 +2657 / 原始 moneyflow −2102 / Tushare 同花顺源 moneyflow_ths −2105)确认"主力资金"无统一标准、各家口径不同,东财是唯一与用户方向一致且干净的。**修**:① `analyze.py` 深析资金源切 `ts_moneyflow_dc`(`_fetch_fund` 兼容 `net_amount`/`net_mf_amount` 字段);② `fund_asof` 取实际数据最新交易日(盘后=今日、盘中=上一交易日),失败才退回占位;③ `prompt.py` 去掉写死"截至上一交易日",正文聚焦资金强弱、日期由客户端标签权威显示;④ 客户端文案改"资金面 = 截至 {date} EOD · 东财主力口径(非盘中实时)"。pytest 309 / macOS build 无回归。三文件热补丁 scp 到 ECS + restart,端到端验通:002184 现返 **fund_asof=07-02、近3日+4473万流入、当日+2657万、verdict 可进**、正文无"上一交易日"。CLAUDE.md 资金时序两条同步订正。
- **[2026-07-02] v1.2.1 完工收口并上线**:新增统一 `POST /chat` 多轮对话端点(不动 `/analyze`/`/coach`,回测链路与教练红橙卡照旧)+ 对话 prose reply + 旁路 verdict 落库(仅首条候选对话且非降级才落,堵覆盖式污染)+ 对话专属超时 25s×2 + 双端候选行改真「深析」按钮唯一入口 + 初始深析对话化 + composer 追问真接 DeepSeek + 删 `.analysis` 结构化卡死代码(`DeepAnalysisCard` 本体留供快照测试)。走完整工作流:planner→plan-critic 一轮修订(3 致命堵死:对话专属超时/降级不落库门槛/mode 按业务状态判非 UI 状态)→builder(Phase A–C)→reviewer(致命 0、2 重要——coach 区间措辞按 pnl 派生、事实缓存条件改 and——均已修)。门禁:后端 pytest 337、客户端 XCTest 49、双端 `BUILD SUCCEEDED`。**两步全量部署**(先补 store 拆包重构首次真上生产、再上 v1.2.1 新增)端到端验通:`/chat` 生产返 181 字自由对话、fund_asof 07-02、东财资金流入正常。全文 `archive/v1.2.1_plan.md` + `archive/REVIEW_REPORT_v1.2.1.md`。
- **[2026-07-03] v1.3.0(实战反馈四件套)完工收口**:四条用户实战反馈——② 三仓相关性护栏(行业 Tushare 口径·只提示不拦·只在买入路径)、④ 交易成本自动化+净额复盘(🔴高危·金额计算+第三次真 migration)、⑤ 候选放开固定 20(删满仓闭门)、⑥ 导出同花顺 TXT(纯前端)。⑦选股大改+③买入理由结构化推迟 v1.3.1。走完整工作流:planner→plan-critic(零致命3重要8建议·修订)→builder-pro(Phase B高危)+主会话Opus复审→builder(后端A+C)→builder(前端C3+D+E)→reviewer(Fable·1 致命[URL `?` 编码坏致相关性护栏生产静默失效]→已修/2 重要/6 建议)→主会话审后修复。**关键决策/偏离**:Phase A 开仓路径绝不联网(只读 `industry_of` 缓存,预热挪到 correlation 端点 + 候选刷新,lifespan 不预热免单测联网);Phase B `close_position` 保持返 int(trade_id)、清仓端点经 `_read_trade_flags` 回读两键,净额 nullable 三态(旧 NULL 不兜 0);审后修复致命#1(`get()` 把 `?` 编码成 `%3F` 致 correlation/review?week= 真后端 404、护栏静默失效)+ 🟡1 同族 + 🟡2 净额展示到分 + 🔵1 行业映射自愈,已修复并补门禁单测。门禁:后端 pytest 337→378、客户端 XCTest 49→65、双端 `BUILD SUCCEEDED`;新增端点 1 个 `GET /positions/correlation`;第三次真 migration `positions.industry`+`trades.qty/fee/net_pnl_amount`。全文 `archive/v1.3.0_plan.md` + `archive/REVIEW_REPORT_v1.3.0.md`。
- **[2026-07-05] v1.3.1(盘后选股完善)立项**:§4 落定 3 块 8 Phase——**A 新选股逻辑**(A1 rules/form 新因子纯函数 / A2 fetch/pipeline 接线 / A3 前端 warn 分级)、**B 选股配置可调化**(B1 新表 `screen_config` 存 JSON 单行 / B2 `GET|PUT /screen/config` + 校验合并 / B3 客户端调参屏)、**C 刷新改手动**(C1 删 15:35 自动 tick,保留 EOD 摘要 + 回测回填 / C2 前端可选文案微调)。**关键选型**:① 删高位 ≥100% 硬排除改只标注(红/琥珀分级,新增 `warnLevel` 前向兼容字段);② 粗筛/排序量比口径接 `daily_basic.volume_ratio`(现成字段替自算放量);③ 排序换 9 因子集(量比0.30/位置健康距60日高点0.16/换手健康[7,15]%0.14/VWAP0.10/横盘突破0.10/市值弹性[50,500]亿0.08/活跃0.06/资金0.06/单日软闸-0.06,正权和1.00),**`pos_health=today_close/max(60日高)` 替旧 `low_position`**(修反向偏好左侧下跌票);④ 横盘突破 = 近25日振幅<15%+今日突破24日上沿+量比≥1.5;⑤ **配置成新单一源、rules 常量降为默认/fallback**,存储 = SQLite `screen_config` 表单行 JSON(`CREATE TABLE IF NOT EXISTS` 非 ALTER),`resolve` 默认浅合并用户覆盖 + 逐字段校验夹紧 + 权重和归一,非法配置逐字段回退默认绝不崩;⑥ 删自动 tick 后手动 `POST /candidates/refresh` 成唯一刷新途径,回测回填移出 refresh if 块改自扫描防重。**依赖**:B 整体在 A 之后(配置字段须覆盖 A 新因子);A 与 C 可并行。**plan-critic 重点审面**:B1 建表 + B2 配置校验/优先级/非法降级(新单一源不能有洞)。
- **[2026-07-05] v1.3.1 plan-critic 修订(1 致命+6 重要+6 建议,全吸收)**:**致命#1** warnLevel 缓存链路断层(`GET /candidates` 读 candidates 缓存表、`upsert_candidates` 白名单 INSERT 静默丢 warnLevel、表无 pct_60d 派生不出)→ 拆出 **Phase A2.5**:candidates 加 `warn_level` 列(**第四次真 migration**,扩 `_ensure_candidates_columns`)+ 三处同步(`_CANDIDATE_KEYS`/INSERT/输出)+ **穿透缓存回环测试**封死断层 + §5 部署前置。**6 重要**:#2 config 形状钉死(扁平单层键注册表 `SCREEN_CONFIG_SPEC`、PUT 存增量不归一、归一只在 resolve 全量后、恢复默认=PUT 空清行);#3 生效机制=**显式穿参 cfg dict 进刷新链路、禁 monkeypatch 常量**、深判层不吃用户配置;#4 NaN 守卫(Tushare 缺值是 NaN,`float(x or 0)` 拦不住、`math.isfinite`+`pd.isna` 守卫);#5 breakout 振幅窗口**排除今日**(否则今日=最高使振幅退化、越突破越判 False);#6 ≥100% 票 `high_warn_text` 补红级文案;#7 回填触发防重(自扫描幂等防落库不防打 Tushare,挂 `last_eod_date` 块每交易日一次)。**6 建议全收**:#8 `DEFAULT_SCREEN_CONFIG` 引用构造+等值断言;#9 pos_health `len<20→0.0`;#10 展示口径解耦(`volMultiple` 仍自算放量);#11 `run_candidate_refresh` 是死码直接删;#12 组合效应(删硬排除+奖励贴高点同向)标"预期非回归"。修订全落 §4 对应 Phase。
- **[2026-07-04] v1.3.0 部署上线 ECS**:第三次真 migration(`_ensure_v130_columns`)幂等落地,**项目首次非空仓部署**(存量 3 持仓 + 0 trades,`cp` 备份 `linon.db.bak-20260704-203407` 校验后再动)。重启 health 2s 就绪(监控空档极短);端到端验通:② `GET /positions/correlation?code=600519`→`白酒`/conflict:false·200(存量 3 持仓 industry=NULL 护栏跳过、逐行无损)、⑤ 满仓 `GET /candidates` 仍返 20 只 degraded=false。内存 780M/1612M·swap 0。**④净额需真实清仓触发(列已就位)、⑥导出纯客户端;客户端 v1.3.0 UI 尚未 Release 换包(iOS 真机留用户 Xcode 分发)**。回滚锚 = DB 备份 + GitHub `da045c1`。运维详情 `~/Lino/hz_info.md`。
