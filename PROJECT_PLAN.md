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
- **门禁数字**:**已发布 3 阶段**(阶段1+阶段2+v1.2.1,live `https://ln.linotsai.top`,阶段2 于 2026-06-28 上线、v1.2.1 于 2026-07-02 两步上线;阶段2.5/阶段3/阶段3.1 为纯后端/全栈小版本随部署链路一并上线;`app/db/store.py` 单文件在 ECS 已不存在,store 拆包首次真上生产;**v1.3.0 已部署上线(2026-07-04)**;**v1.3.1 已部署上线(2026-07-05)**)。**阶段4(K线/舆情/双端真机 E2E)待规划**。后端 pytest **450 全绿**(阶段1 基线 105 + 阶段2 新增 88 → 193 + 阶段2.5 新增 34 → 227 + 阶段3 新增 49 → 276 + 阶段3.1 新增 33 → 309 + v1.2.1 新增 28 → 337 + v1.3.0 新增 41 → 378 + v1.3.1 新增 72);客户端 XCTest **95 全绿**(17 + 阶段2 新增 15 → 32,阶段2.5 无前端改动,阶段3 新增 8 → 40,阶段3.1 新增 4 → 44,v1.2.1 新增 5 → 49,v1.3.0 新增 16 → 65,v1.3.1 新增 30);**双端 build iOS Simulator + macOS 各 `BUILD SUCCEEDED`**;真 key 活体冒烟过(Tushare 5490 行/茅台白酒归类符合假设;DeepSeek `json_object` 真输出夹紧成合法 DeepAnalysis;analyze/coach/chat 真 key curl 闭环;离屏快照逐屏目检候选行/满仓🔒/深析卡 fund_asof/教练红橙卡;阶段2.5 真 token 限频冒烟 65/65 天 adj_factor 全部成功,零限频失败,耗时 39s→45.5-45.7s)。阶段2 新增端点 **4 个**:`GET /candidates`、`POST /candidates/refresh`、`POST /candidates/{code}/analyze`、`POST /positions/{id}/coach`;阶段2.5 新增只读端点 **1 个**:`GET /candidates/outcomes`;阶段3 新增端点 **3 个**(`GET /review`、`POST /review/{week}/note`、`GET /memory`)+ `/coach` 新增可选字段 `review_ref`;阶段3.1 无新增端点,`GET /candidates` 候选 dict 新增可选展示字段 `score`(int,前向兼容);v1.2.1 新增端点 **1 个**:`POST /chat`;v1.3.0 新增端点 **1 个**:`GET /positions/correlation`;v1.3.1 新增端点 **2 个**:`GET/PUT /api/v1/screen/config`,`GET /candidates` 新增可选字段 `warnLevel`。**第四次真 migration**:`candidates.warn_level` 列;**新表**:`screen_config`。
- **v1.3.1(盘后选股完善)已完工收口(已部署上线)**:三块——① 新选股逻辑(删高位硬排除改只标注红/琥珀分级、粗筛量比口径接 `daily_basic.volume_ratio`、排序换 9 因子集含距60日高点 `pos_health`/横盘突破 `breakout_ok`、warnLevel 经 candidates 缓存表往返=**第四次真 migration `warn_level` 列**)、② 选股配置可调化(档 B·App 内调参屏 + 新表 `screen_config` 存 JSON 增量 + `GET/PUT` 端点 + 显式穿参生效不 monkeypatch、rules 常量降级为默认值/fallback、深判层不吃配置)、③ 候选刷新改纯手动(删 15:35 自动 tick + `run_candidate_refresh` 死码,回填改挂 `last_eod_date` 守卫的 EOD 块)。持仓教练深判重做②/盘中选股独立板块③已定移 **v1.4**,本版不碰。走完整工作流:planner→plan-critic(1 致命[warnLevel 缓存断层]+6 重要+6 建议全吸收)→builder 三批(批1 后端 A+C/批2 后端 B/批3 前端)→reviewer(Fable·0 致命/3 🟡/8 🔵)→主会话审后修复(🟡#1 跨字段带内一致性 `_enforce_band_consistency` + 🟡#2 调参屏按钮加载态守卫 + 用户新增 `mv_mega_ceil` 可调化 500→1500)。门禁:后端 pytest **378→450 全绿**(批1+25/批2+40/批3 前端/审后+7);客户端 XCTest **65→95 全绿**;双端 `BUILD SUCCEEDED`。新增端点 **2 个**:`GET/PUT /api/v1/screen/config`。第四次真 migration:`candidates.warn_level` 列。新表:`screen_config`(`CREATE TABLE IF NOT EXISTS`,非 ALTER)。全文 `archive/v1.3.1_plan.md` + `archive/REVIEW_REPORT_v1.3.1.md`;8 🔵 建议入 §5。**已部署上线 2026-07-05**(第四次 migration + `screen_config` 建表幂等落地、479 候选历史无损;prod 验通:配置端点 22 键默认 + PUT/恢复默认清行、新 9 因子 refresh count=168、warnLevel amber 经缓存表往返;macOS 已 Release 换包,iOS 留用户;详见 `~/Lino/hz_info.md`)。
- **v1.4 施工中**:Phase A(后端盘中数据层)已完工——新建 `backend/app/data/intraday.py`(4 个纯函数:`_is_intraday_window`/`elapsed_trading_minutes`/`intraday_vol_ratio`/`vwap_of`/`build_intraday_snapshot`),不自拉价不联网。门禁:后端 pytest **450→474 全绿**(新增 24 条,覆盖 plan 验收清单全部 14+ 项,含 VWAP 真实比例假 Quote 反向公式回归门)。下一步 Phase B(coach 盘中上下文注入)+ Phase C(候选盘中确认端点)可并行。
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

## 4. 当前版本 Plan(v1.4 · 盘中上下文:教练 + 候选续强确认)

> 立项 2026-07-05。**核心前提(用户拍板)**:盘中主力资金层整个砍掉(用户自己肉眼看盘口),v1.4 **零新增外部数据源、零 schema migration、零新表**,只复用现有新浪/腾讯实时源 + 现有 Tushare EOD。两件事:② 给持仓教练/对话注入实时盘中上下文;③ 候选池「今日续强确认」视图(收窄=次日续强进场确认,非全市场盘中选股)。旧债一并收:两源盘中真复测。

### 不动的契约(v1.4 全期铁律,builder 越界即回 planner)

- **3 硬线**:止损 -5.0 触发 / 止盈 +15% / D4 强平(`count==4 ⟺ should_force_close`),口径与判定全不动;`hitStop` 展示阈 -4.9 不动。
- **规则常量单一源** `app/db/store/constants.py`;选股规则单一源 `screen_config`/`rules.py`;v1.4 **不碰选股规则、不碰排序因子**。
- **守味隔离**:教练/对话只注入中性 `history_digest`,**绝不注入 `review_ref`**(情绪串只回客户端展示)。
- **绿涨红跌**(用户明确选择,勿"纠正");monitor「每源每 tick ≤1 拉」纪律不破。
- **两源单位坑**(CLAUDE.md 数据源坑):归一后 `Quote.volume`=手、`Quote.amount`=元;VWAP=`amount/(volume×100)`(元/股,见技术选型钉死)用**归一后**字段,不碰原始报文。

### 技术选型(本阶段定死,不留给施工)

**盘中量能口径(定死,唯一)**:采用「**已开盘时长折算日量**」估算。
- `elapsed_min` = 从 09:30 起已交易分钟数(**跨午休**:09:30–11:30=120min + 13:00–15:00=120min,共 240min;午休 11:30–13:00 定格在 120;`now<09:30`→0;`now≥15:00`→240)。**盘中窗口内**(见下"盘中窗口判定")才调用折算,午休时 `elapsed=120`、折算照常有效(用上午累计量)。
- `projected_full_vol = current_vol / elapsed_min × 240`(current_vol 用归一后**手**数);`intraday_vol_ratio = projected_full_vol / prev5_avg_vol`(prev5_avg_vol = 前 5 交易日日均成交量手数,复用 Tushare `daily` 拉取,与选股放量口径同源)。
- **边界(定死)**:① `elapsed_min < 60`(**早盘头 60min·建议#11**:含集合竞价噪声 + A 股早盘量能前置,10:30 前折算系统性高估、偏差方向恰好利多怂恿进场,故把 early 阈提到 60min 更保守)→ 折算不可靠,`intraday_vol_ratio` 置 `null` + 标 `note:"early"`(客户端显"开盘初,量能待观察");② `elapsed_min ≥ 240`(仅 `now==15:00` 收盘边缘可达,因窗口是 `<15:00`)→ 折算=当日实际全量,`note:"closed"`(近乎死分支,保留兜底不删);③ **盘中窗口外**(见下判定)整个视图降级 `note:"non_trading"`,不算折算;④ `prev5_avg_vol` 缺失/为 0 → `intraday_vol_ratio=null` + `note:"no_base"`。展示只给 `intraday_vol_ratio`(保留 1 位小数)+ note,**不承诺精度**(文案标"折算估算,非实时精确;早盘折算通常偏高")。
- **不做**:「现量 vs 昨日同时段」(需分时历史,Tushare 免费口径不稳、成本高)——明确不选。

**VWAP(定死,单位口径钉死·致命#1 修正)**:`vwap = amount / (volume × 100)`(**元/股**)——`Quote.amount` 归一后是**元**、`Quote.volume` 归一后是**手**(1 手=100 股),故须 ÷(volume×100) 才得每股均价,与 `Quote.price`(元/股)同口径可比。**先例互指**:`app/screen/form.py:173` `vwap=(today_amount×1000)/(today_vol×100)`——form.py 是**千元/手**故 ×1000;realtime 归一后已是**元/手**故只 ×100,**别照抄 form 的 ×1000 系数**。`is_above_vwap = price ≥ vwap`。**警示**:若误写 `amount/volume`(元/手 = 100×每股均价),`price≥vwap` 恒 false(如茅台 1400 vs 140000),且假 Quote 单测按错误公式造数据会全绿——单测必须用**真实比例的 amount/volume**(amount≈price×volume×100)造假 Quote,才能暴露反向错误。**降级**:`volume ≤ 0`(停牌/开盘前/无成交)→ `vwap=null`、`is_above_vwap=null`(不猜),客户端显"—"。VWAP 用**当日累计** amount 与 volume(两源报文即当日累计值),非分时。

**盘中窗口判定(定死·重要#2 修正,单一函数,禁复用 loop 窗口)**:本 feature 专用 `_is_intraday_window(now: datetime) -> bool` = **交易日 且 `09:30 ≤ now.time() < 15:00`**(即 `is_trading_day(now.date())` 且落在开盘~收盘的整段内,**含午休 11:30–13:00**)。理由:午休时当日累计成交量/累计 amount/VWAP/现价都是**有效的上午终态**,盘中确认与 coach 上下文照常有意义,不该像 loop 那样把午休判为"非交易"。**明令不复用** `loop._is_trading_now`(它按 `trading_window` 的两段区间判、午休/15:00 后返 False)——若复用则午休 coach 不注入、盘中视图全 null,`elapsed_trading_minutes` 跨午休设计与 `closed` 分支全成死码。响应体里的 `is_trading` 字段 = `_is_intraday_window(now)` 的值。

**非交易(窗口外)行为(定死)**:`_is_intraday_window(now)==false` 即窗口外(非交易日 / 09:30 前 / 15:00 后)。
- 后端盘中端点(③)/coach 盘中上下文(②):窗口外仍**返回结构**,但 `is_trading=false` + 实时字段(现价/涨幅/VWAP/量能)全置 `null` 或标 `note:"non_trading"`(实时源盘后返上一交易日快照,不可当"今日盘中",一律不采信)。coach 深判照常出(用 EOD 事实),prompt 盘中块不渲染(资金约束句照旧钉死)。
- 客户端候选盘中视图:`is_trading=false` 时刷新按钮**禁用** + 顶部标"非交易时段 · 盘中确认仅交易时段可用";已有 EOD 候选列表照常展示(不清空)。客户端**不自己判日历/时段**,一律以后端回传的 `isTrading` 为准(见 Phase D.4)。

**拉价路径(定死)**:③ 盘中确认批量拉 = 复用 `realtime.get_realtime_quotes(codes)`(新浪批量天然支持多 code;主源缺则腾讯补,已实现)。② coach = on-demand 单票 `get_realtime_quote(code)`。**均走 HTTP 请求线程内同步拉一拍,不接入 monitor tick、不共享 monitor 的 `_build_two_source_quotes`**——monitor「每源每 tick ≤1 拉」纪律只约束后台轮询,on-demand 端点各自独立拉一次不违反(与现 `/coach` 的 `_resolve_prices` 同款)。

**prompt 注入(定死,②)**:coach/chat 的 context 增一段 `intraday`(盘中语境),**仅 coach 模式、仅 `is_trading` 时注入实数**;候选 candidate 模式不注入(候选是次日进场判断,不需要盘中持仓语境)。
- 注入字段:实时价 `price`、今日涨幅 `chg_pct`、现量估算 `intraday_vol_ratio`(带 note)、是否站 VWAP `is_above_vwap`。
- 持仓语境(coach 已有,复用不重取):成本 `buy_price`、`pnl_pct`、`trade_day`(D 几)、距止损线%、距止盈线%。
- **T-1 EOD 资金 prompt 约束(钉死措辞)**:资金段前置固定句——「以下资金数据截至 {fund_asof} 收盘(东财主力 EOD),**今日盘中资金未知,不得据此推测今日盘中资金动向或据此说"主力今日在/撤"**」。防 DeepSeek 拿 T-1 编盘中故事。
- **盘中段护栏句**:「盘中量能为按已开盘时长折算的估算值,非精确,**早盘折算通常偏高**(A 股早盘量能前置,勿据此怂恿追高);VWAP 为当日累计均价(元/股)」。
- 层1 机械纪律(3 硬线)不进 prompt 判定(照旧);盘中上下文只作 LLM 判断的**补充事实**,不改 verdict/advice 的二元派生逻辑。

**鉴权(定死)**:③ 新端点复用 `require_token`(Bearer,同全部现有端点);无新鉴权路径。

### Phase 拆分

依赖:**A(后端盘中数据层)→ B(② coach 注入)+ C(③ 盘中端点)可并行**;D(前端)依赖 B/C 接口契约定稿;E(盘中真复测)最后。A 是 B/C 共同底座。

---

#### Phase A — 盘中数据层(后端·纯函数)

新建 `backend/app/data/intraday.py`,四个**纯函数**(不自己拉价——拉价/拉 daily 在端点层做,函数只吃已拿到的 quote 对象 + prev5 均量数值,便于单测不联网 + 端点批量复用一拍拉价)。

0. `_is_intraday_window(now: datetime) -> bool`(**本 feature 唯一时段判定**,B/C 端点都调它,禁复用 `loop._is_trading_now`——重要#2):`is_trading_day(now.date())` 且 `09:30 ≤ now.time() < 15:00`(**含午休**)。这是 `is_trading` 字段的唯一真值源。
1. `elapsed_trading_minutes(now: datetime) -> int`:按上述口径算已开盘分钟(跨午休、边界)。纯 datetime 运算(时段有效性由调用方先经 `_is_intraday_window` 判)。
2. `intraday_vol_ratio(current_vol, prev5_avg_vol, elapsed_min) -> tuple[Optional[float], str]`:返回 `(ratio_or_None, note)`,note∈{"ok","early","closed","no_base"}。`elapsed_min<60→(None,"early")`(建议#11 提保守阈);`prev5_avg_vol<=0→(None,"no_base")`;`elapsed_min>=240→(ratio,"closed")`;否则 `(ratio,"ok")`。ratio 保留 1 位小数。
3. `vwap_of(quote) -> tuple[Optional[float], Optional[bool]]`:`vwap = amount/(volume×100)`(**元/股**,致命#1),`is_above_vwap = price ≥ vwap`;`volume<=0`(或 quote None)→`(None,None)`。单测须用 `amount≈price×volume×100` 的真实比例假 Quote(否则反向错误单测照样绿)。
4. `build_intraday_snapshot(quote, prev5_avg_vol, *, now, is_trading) -> dict`:**纯编排**,吃 `quote`(Quote|None)+ `prev5_avg_vol`(float)→ 单票盘中快照 = `{is_trading, price, pre_close, chg_pct, open_chg_pct, vwap, is_above_vwap, intraday_vol_ratio, vol_note, asof(quote.ts if quote else "")}`。分支:① `is_trading=false` → 各实时字段 `None`、`vol_note="non_trading"`;② `is_trading=true` 但 `quote is None`(拉价失败)→ 实时字段 `None`、`vol_note="no_base"`(或复用 non_trading,施工钉一处);③ 正常 → 各字段实算,`vol_note` 由 `intraday_vol_ratio(...)` 返回。`chg_pct=(price-pre_close)/pre_close×100`、`open_chg_pct=(open-pre_close)/pre_close×100`,**均加 `pre_close>0` 除零守卫**(建议#6:`pre_close<=0` → 该 pct 置 `None`)。`intraday_vol_ratio` 走 A.2(先经 `elapsed_trading_minutes(now)` 算 elapsed)。**不在此函数内拉价/拉 daily**。

**验收**:pytest 新增 ≥14 条覆盖:`_is_intraday_window` **午休(12:00)返 True**、09:20/15:01/非交易日返 False;折算跨午休(elapsed 定格 120)/头 60min→early/收盘边缘;VWAP 用**真实比例 amount(≈price×vol×100)** 断言 `is_above_vwap` 正确(致命#1,反向公式会被此测抓)+ volume=0 降级;快照 is_trading=false 全 null;quote=None 全 null;prev5=0→no_base;chg_pct/open_chg_pct 计算 + **pre_close=0 除零→null(建议#6)**。全部传假 Quote/数值,不联网。

---

#### Phase B — 持仓教练盘中上下文注入(后端·全栈接口)

改 `app/llm/analyze.py`(`analyze_stock` coach 分支 + `chat_stock` coach 分支)与 `app/llm/prompt.py`(`build_user_prompt` + `build_chat_context_block` 的 coach 段)。

1. `analyze_stock`/`chat_stock` 新增可选参 `intraday_quote: Optional[Quote] = None` 与 `is_trading: bool = False`(端点层传入,深判层不自己拉盘中价——保持可注入)。仅 `mode=="coach"` 且 `is_trading` 且 `intraday_quote is not None` 时,用 `form["prev5_avg_vol"]` + `intraday_quote` 调 `intraday.build_intraday_snapshot(...)` 得 snapshot dict,拼进 context 的 `intraday` 键;否则 context 无 `intraday`(prompt 盘中块不渲染)。**candidate 模式一律不组装**(候选是次日进场判断,无盘中持仓语境)。
2. **端点层(`coach_position` / `chat` 的 coach 分支)只做两件事:判窗口 + 拉价**,snapshot 组装下沉到编排层(唯一路径,不给 builder 留分处组装的打架空间——修重要#2/#4):
   - 判 `is_trading = intraday._is_intraday_window(datetime.now())`(**用 A 里的单一 `_is_intraday_window`,禁复用 `loop._is_trading_now`**——重要#2)。
   - `is_trading` 时单票 `_quotes_fn([code])` 拉一拍拿**完整 Quote**(VWAP 需 amount/volume,`_resolve_prices` 只回 float 不够);**pnl_pct 复用同一 Quote 的 price**(不重复拉)。把 `intraday_quote=Quote|None` 与 `is_trading=bool` 作新参传给 `_analyze_fn`/`_chat_fn`(→ `analyze_stock`/`chat_stock`)。窗口外不拉价,传 `intraday_quote=None, is_trading=False`。
   - **prev5 由编排层的 `_fetch_form` 顺带吐,端点绝不再拉 daily(修重要#4)**:改 `_fetch_form` 多返回 `prev5_avg_vol`(它已拉近 65 日 daily、`vols` 序列现成,取前 5 交易日 vol 均值;daily `vol` 单位=手,与 realtime 归一后同口径)。`analyze_stock`/`chat_stock` 在 coach 模式内、拿到 `form` 后,用 `form["prev5_avg_vol"]` + 端点传入的 `intraday_quote` 调 `intraday.build_intraday_snapshot(...)` 组装 snapshot 存进 context——**quote 与 form 同处(编排层)组装,唯一路径**。这样 `/chat` 每轮追问不叠额外 daily 拉取(coach 最坏链 ~45s < 客户端 60s,前提是不再叠这一拍)。
3. `prompt.py`:coach 段增「盘中上下文」块(仅 context 含 `intraday` 键时渲染),含实时价/今日涨幅/`intraday_vol_ratio`(带 note 文案:early→"开盘初量能待观察"/no_base→"量能基准缺失")/站 VWAP;资金段前置钉死约束句(见技术选型);末尾盘中护栏句(含"早盘折算通常偏高",建议#11)。**两个量能数标签必须显著区分(建议#8),防 LLM 混谈**:现有形态块里 `form.vol_multiple` 标签明确改「**昨日 EOD 放量倍数**」,盘中块里 `intraday_vol_ratio` 标「**盘中折算量比(估算,非精确)**」——两者语义不同(一个是昨日收盘、一个是今日盘中折算)。**candidate 模式与窗口外:盘中块不渲染**(资金约束句照旧钉死)。
4. `SYSTEM_PROMPT`/`CHAT_SYSTEM_PROMPT` 补一句:「若提供盘中上下文,它是按已开盘时长折算的估算实时数据,可参考但不精确;资金面仍是 EOD、不代表盘中资金」。
5. **响应契约**:`/coach`、`/chat` 响应结构**不变**(不新增顶层字段;盘中信息只进 prompt 影响 LLM 文本)。客户端 `fund_asof` 文案已标注 EOD,复用即可(见 Phase D 文案微调)。

**接口契约(不变,仅行为增强)**:`POST /positions/{id}/coach`、`POST /chat`(coach 模式)请求/响应形状全不变。降级:非交易时段/拉价失败 → 盘中块不注入,coach 照常出(退化为纯 EOD 判定,同 v1.3.x 现状)。

**验收**:pytest 新增 ≥8 条:coach 盘中时 prompt 含盘中块 + 资金约束句(断言 `build_user_prompt`/`build_chat_context_block` 输出含钉死句、含 VWAP 字样);非交易时段 coach prompt **不含**盘中块但**含**资金约束句;candidate 模式不含盘中块;`analyze_stock(mode=coach, intraday=注入假快照)` 端到端注入(deepseek_fn 打桩断言收到的 context 含 intraday)。守味隔离回归:coach 注入盘中后仍不含 review_ref(现有测试不回归)。

---

#### Phase C — 候选池「今日续强确认」端点(后端)

新端点 `GET /api/v1/candidates/intraday`(`require_token`)。**读时叠加、不落库**(candidates 表不动)。

- **入参**:无(读当日最新候选缓存的 codes)。
- **逻辑**:`td = store.latest_candidate_date()` → `codes = [c["code"] for c in store.list_candidates(td)][:rules.CANDIDATE_LIMIT]` → `is_trading = intraday._is_intraday_window(datetime.now())`(重要#2 单一判定) → `is_trading` 时 `realtime.get_realtime_quotes(codes)` **批量拉一拍**(一次请求 20 code)+ 逐票取 `prev5_avg_vol`(缓存,见下)→ 逐票 `intraday.build_intraday_snapshot(quote, prev5, now=..., is_trading=True)` 构造 items。窗口外/无候选 → 返回结构但 `isTrading=false` + items 实时字段 null(见非交易行为)。
- **prev5 均量口径 + 缓存(建议#5)**:批量拉价一次请求即可(新浪多 code),prev5 均量需逐票 `tc.ts_daily`(单票近 10 自然日,取最近 5 条 `vol` 均值,与选股放量口径同源)。**prev5 按 `(code, trade_date)` 进程内缓存(仿 `fetch.load_industry_map` 模式)**——prev5 是 EOD 派生、当日内不变,首次算完缓存,同日重复调 `/candidates/intraday` 热路径只剩一拍批量拉价(~1s),不必每次 20 拍 daily(冷路径 ~5-10s)。某票 Tushare 未配/失败 → 该票 `intradayVolRatio=null` + `volNote="no_base"`(不崩,不缓存失败结果、留下次重试),其余票正常。客户端配 30s 长超时。
- **`asof` 口径(建议#7)**:顶层 `asof` = **items 里第一个非空 `quote.ts` 的值**(多票 ts 可能不同、两源格式已由 realtime 归一;无任一 quote → `""`)。不取"当前系统时间",取真实快照时刻。
- **响应形状(逐字段钉死,camelCase,前向兼容)**:
  ```
  {
    "ok": true,
    "isTrading": true,            // 非交易时段 false
    "tradeDate": "2026-07-06",    // 候选缓存基准日(EOD 圈选日);空缓存 ""
    "asof": "2026-07-06 10:23:00",// 实时快照时刻(取自 quote.ts;非交易时段 "")
    "degraded": false,            // 无候选/无 token → true
    "items": [
      {
        "code": "301051", "name": "信濠光电",
        "price": 45.6,             // 现价;非交易/拉价失败 null
        "chgPct": 3.21,            // 今日涨幅%(price vs pre_close);null 同上
        "openChgPct": 1.05,        // 高开幅度%(open vs pre_close);null 同上
        "isAboveVwap": true,       // 站 VWAP;volume<=0 或非交易 null
        "intradayVolRatio": 1.4,   // 盘中折算量比;early/no_base/非交易 null
        "volNote": "ok"            // ok|early|closed|no_base|non_trading
      }
    ]
  }
  ```
  `items` 顺序 = 候选缓存 rank 序(续强判断按原推荐序看),但**客户端叠加到 EOD 候选行时一律按 `code` join(建议#10),不以顺序作对齐依据**(候选列表与 intraday items 理论同序,但拉价失败/条数差时顺序不可靠)。客户端解码用**前向兼容**(所有实时字段 `Optional`,缺键/null 都不崩)。

**验收**:pytest 新增 ≥8 条:交易时段注入假 quotes → items 带实时字段 + volNote;窗口外 → isTrading=false + 实时字段 null;无候选缓存 → degraded=true items 空;单票拉价缺失 → 该票 price=null 其余票正常;openChgPct 计算(open vs pre_close)正确;VWAP 降级(volume=0);**`pre_close=0` → chgPct/openChgPct=null(建议#6 除零守卫)**;**`asof` 取第一个非空 quote.ts(建议#7)**。全部注入 `_quotes_fn`/`daily_fn` 假替身,不联网。端点走 `require_token`(补一条无 token 401)。

---

#### Phase D — 客户端(前端·双端,布局分叉照既有模式)

1. **新增模型**(`Models.swift`):`IntradayItem`(逐字段对齐 C 响应,实时字段全 `Optional`)、`IntradayConfirmResult`(`isTrading/tradeDate/asof/degraded/items`)。
2. **APIClient**(`Networking/APIClient.swift`):`fetchCandidatesIntraday() async throws -> IntradayConfirmResult`,走 `get("/api/v1/candidates/intraday", timeout: 30)`。**重要#3:现有 `private func get(_ path:)` 写死 `timeoutInterval=12`(APIClient.swift:550/558),须给 `get` 加 `timeout: TimeInterval = 12` 可选参**(同现有 `post`/`put` 已有 timeout 参的模式),本端点传 30(20 票 prev5 daily + 批量拉价 12s 会间歇超时)。**经 makeURL**(虽无 query 仍统一走,防 `?` 编码坑)。前向兼容解码(private DTO,实时字段 optional)。
3. **AppModel**:`@Published var intraday: IntradayConfirmResult?` + `intradayLoading` + `func loadIntradayConfirm() async`(非交易时段 isTrading=false 时不清空 EOD 候选列表,只更新盘中态)。
4. **CandidatesView**(双端):候选页增「盘中确认」入口/态。**按钮初始态钉死(建议#9)**:客户端**不自己判日历/时段**——「盘中确认」按钮**初始可点**,点击拉 `loadIntradayConfirm()`,响应回 `isTrading=false` 后再禁用 + 标注"非交易时段 · 盘中确认仅交易时段可用"(时段真值全由后端 `isTrading` 定,客户端不造日历)。iOS:header 增「盘中确认」按钮,拉到后候选行叠加盘中字段(现价/今日涨幅/高开/站 VWAP 徽章/折算量比 + volNote 文案);macOS:工具栏加「盘中确认」按钮 + 列表列叠加盘中字段(照既有 macOS 横列扩列模式,别把横列套 iOS)。**叠加按 `code` join(建议#10),不靠顺序**。**布局分叉照 CLAUDE.md 既有约定**(iOS 竖排弹性中列 / macOS 横向多列)。绿涨红跌:`chgPct`/`openChgPct` 着色**从数值派生**(`>=0` 绿),不字符串判负。
5. **文案微调**:coach 卡/深析卡 `fund_asof` 标注**已有**"截至 {date} EOD · 东财主力口径(非盘中实时)";v1.4 盘中态下补一句区分——盘中确认视图内 VWAP/量能标"盘中折算估算,非精确"。改 .swift 后**必 `xcodegen generate`**(CLAUDE.md 坑)。

**验收**:双端 `BUILD SUCCEEDED`(iOS Simulator + macOS build);XCTest 新增 ≥6 条:`IntradayConfirmResult` 解码(全字段/缺实时字段前向兼容/isTrading=false);盘中量比/VWAP 展示派生;chgPct 正负着色派生(负跌不染绿)。非交易时段视图态(按钮禁用逻辑)可离屏快照或状态断言。**computer-use Dock 守卫**下用 `ImageRenderer` 离屏快照核对(非 ScrollView 组件本体,CLAUDE.md 坑),不硬点。

---

#### Phase E — 两源盘中真复测(旧债,交易时段手动冒烟)

**收 §3「待联调」旧债**:新浪/腾讯实时源从未在交易时段真盘中复测(此前只验收盘快照 + 样例报文单测)。②③均建在两源上,交易时段跑一次冒烟。

- **冒烟脚本**:`backend/scripts/smoke_intraday.sh`(或 `.py`),交易时段手动跑,对一组固定测试 code(如 3 只不同板块在持仓/候选票)真拉两源,打印并断言:
  1. **两源价量一致性**:同 code 新浪 vs 腾讯 `price`/`pre_close`/涨跌停一致(容差内);单位归一后 `volume`(手)/`amount`(元)量级一致(校验两源单位坑无回归)。
  2. **VWAP 合理性**:`amount/(volume×100)`(元/股,致命#1 口径)落在当日 `[low, high]` 价区间内(若误用 `amount/volume` 会大 100 倍显著出界,正好反证单位口径)。
  3. **盘中量能口径落地数字**:打印 `elapsed_min`、`current_vol`、`projected_full_vol`、`prev5_avg_vol`、`intraday_vol_ratio` 具体数值 + note,人工核对折算合理(如 10:30 时 elapsed≈60、折算≈现量×4 量级)。
- **验收**:交易时段跑一次,三项均通过并把落地数字(两源一致性差异%、VWAP 样例、量能折算样例)记进变更日志/CLAUDE.md;若发现两源盘中口径新坑,记 CLAUDE.md 数据源坑并按需修 `intraday.py`。**此 Phase 依赖交易时段窗口**(A 股 09:30–15:00),排在最后,非交易时段先跑单测门禁、E 留交易时段补跑。

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

### v1.4 立项清单(②③已立项·2026-07-05,范围按用户拍板收窄;④维持推迟)

- **② 持仓教练盘中上下文重做 → 已立项(v1.4 Phase B)**。范围收窄:给 coach/持仓对话注入实时盘中上下文(实时价/涨幅/现量折算/站 VWAP + 持仓语境),T-1 EOD 资金**保留但 prompt 钉死约束**防 DeepSeek 编盘中故事。**盘中主力资金层已砍**(用户自己肉眼看盘口),零新数据源。3 硬线/守味隔离/常量单一源不动。
- **③ 盘中选股 → 收窄为「今日续强确认」视图,已立项(v1.4 Phase C/D)**。**不是全市场盘中选股**(那喂追高病根,明确不做):只读当日盘后圈的 20 只候选缓存 codes,盘中叠加实时价/涨幅/高开/站 VWAP/折算量能,回答"昨日圈的谁走出续强、现在是否进场时机"。盘中量能口径定死=已开盘时长折算日量(见 §4 技术选型)。**盘中主力资金已砍**,零新数据源、零 schema。
- **明确不做(v1.4 防蔓延)**:盘中资金层(任何形式,含东财 push2)、全市场盘中选股、④选股展示分绝对口径、miniQMT/Level-2。
- **④ 选股展示分改绝对口径 + 因子绝对化 + 评分组成 UI**(2026-07-05 用户提出,**维持推迟至选股策略稳定后**):
  - **现状问题**:展示分 `_normalize_scores` 是**池内 min-max→[10,100]**(排名赋分)——池内最高恒 100、不跨天可比、隐藏绝对质量(弱势日最好的票哪怕原始分 0.4 也显 100)。
  - **改法**:展示分 = **原始加权分×100**(艾迪精密 0.8586→86),绝对、跨天可比、弱势日诚实显低分。
  - **连带(必须一起做,否则半吊子)**:`rank_score` 里 `vol_ratio`/`fund` 两因子现仍用 `_normalize`(池内 min-max、相对)→ 改成**绝对评分曲线**(量比/资金率各自 [0,1] 曲线,像 `pos_health`/`turnover_health_score`/`mv_elastic_score` 那样);否则总分仍含两池相对项、不真跨天可比。
  - **评分组成 UI**:候选卡展开"评分解释"面板(9 因子 权重×因子分=贡献 表 + 横条);需后端把每因子贡献落库或 on-demand 算返回(现 `rank_score` 只存最终分)。
  - 上线即空仓/低样本期这条价值不大,待选股策略稳定后做。

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

### reviewer v1.3.1 推迟项(全 🔵 建议级,零致命,2 🟡 已修复;全文见 `archive/REVIEW_REPORT_v1.3.1.md`)

- **(打磨)`rank_score` cfg=None 时权重取 `DEFAULT_SCREEN_CONFIG` 快照而非活的 `WEIGHTS`**:对 `rules.WEIGHTS` 的 monkeypatch 在权重维度不生效(阈值函数维度成立),当前无测试受累,是埋给未来测试作者的暗坑,可改用活引用或注释说明差异。
- **(打磨)`ScreenConfigIn.config` 用 `default_factory=dict`**:PUT body 漏掉 `config` 键会被当成 `{config:{}}` 即"恢复默认"执行,建议改必填、缺键 422。
- **(测试加固)缺一条 HTTP 层 `GET /candidates` 带 `warnLevel` 断言**:store 层回环已封死,风险低,补一条 3 行测试可闭环到字面。
- **(记录权衡)客户端保存 PUT 全量 21 键会把未改默认值也冻结进用户增量**:与"恢复默认=PUT{}"设计动机存在内在张力,若要消除可改客户端只提交 diff-vs-defaults 键。
- ~~**(清理)`VOL_MULTIPLE_MIN` 已无消费点**~~:已由 cleaner 收口时删除(`backend/app/screen/rules.py`,纯死常量,零行为影响)。
- **(打磨)`ScreenConfigTests.swift` 文件头声称覆盖"保存后不自动刷新候选"但无对应断言**:行为正确,可删该句或补一条断言。
- **(观察,无行动项)回填触发点从 ≥15:35 提前到 ≥15:05 的时序**:与旧 15:35 同级风险,挂 EOD 块是 plan 明令,仅记录。
- **(偏离说明记录)B3 入口实现为双端统一 sheet**:plan 原写"iOS NavigationLink / macOS 区块",实现因 macOS Settings 场景无 NavigationStack 改为共享 sheet,reviewer 判定合理偏离。

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
- **[2026-07-05] v1.3.1(盘后选股完善)完工收口**:三块——① 新选股逻辑(删高位硬排除改只标注红/琥珀、粗筛/排序量比换 `daily_basic.volume_ratio`、排序换 9 因子集含 `pos_health`/`breakout_ok`,warnLevel 经 candidates 缓存表往返=第四次真 migration `warn_level` 列)、② 选股配置可调化(新表 `screen_config` + `GET/PUT /api/v1/screen/config` + 显式穿参生效不 monkeypatch + 深判层不吃配置)、③ 候选刷新改纯手动(删 15:35 自动 tick + 死码 `run_candidate_refresh`,回测回填移挂 `last_eod_date` 守卫)。走完整工作流:planner→plan-critic(1 致命+6 重要+6 建议全吸收)→builder 三批→reviewer(Fable·0 致命/3 🟡/8 🔵)→主会话审后修复(🟡#1 带内一致性 `_enforce_band_consistency`/🟡#2 调参屏按钮加载态守卫/用户新增 `mv_mega_ceil` 可调化)。**关键决策/偏离**:B3 调参屏入口用双端统一 sheet(非 plan 原写 NavigationLink/区块分叉,macOS Settings 场景约束所致,reviewer 判定合理偏离)。门禁:后端 pytest 378→450、客户端 XCTest 65→95、双端 `BUILD SUCCEEDED`;新增端点 2 个 `GET/PUT /api/v1/screen/config`;第四次真 migration `candidates.warn_level`;新表 `screen_config`。**收口清理**:删死常量 `VOL_MULTIPLE_MIN`(`rules.py`,零消费点)、CLAUDE.md 订正 3 处过期口径(候选自动刷新→纯手动/高位硬排除→只标注/排序 4 键→9 因子)。全文 `archive/v1.3.1_plan.md` + `archive/REVIEW_REPORT_v1.3.1.md`。(部署见下条)
- **[2026-07-05] v1.3.1 部署上线 ECS + macOS 换包**:第四次真 migration(`candidates.warn_level`)+ `screen_config` 建表幂等落地,**479 候选历史行无损**(备份 `linon.db.bak-20260705-124531`)。prod 端到端验通:`GET /screen/config` 22 键默认(含 `mv_mega_ceil=1500`)+ PUT 存增量/`PUT {}` 恢复默认清行、`POST /candidates/refresh` **新 9 因子 count=168 degraded=false**、`GET /candidates` 20 只含 **2 amber**(warnLevel 经缓存表往返 = 致命#1 修复 prod 验证)、内存 895M/1612M。macOS Release `ditto` 换包 `/Applications`(含 v1.3.0+v1.3.1 全 UI);iOS 留用户 Xcode 分发。回滚锚 = DB 备份 + GitHub `df8985e`。运维详情 `~/Lino/hz_info.md`。
- **[2026-07-05] v1.4(盘中上下文:教练 + 候选续强确认)立项**:§4 落定 5 Phase。**核心前提(用户拍板)**:盘中主力资金层整个砍掉(用户肉眼看盘口),**零新增外部数据源、零 schema migration、零新表**,只复用现有新浪/腾讯实时源 + Tushare EOD。**两件事**:② coach/持仓对话注入实时盘中上下文(实时价/涨幅/现量折算/站 VWAP + 持仓语境),T-1 EOD 资金保留但 prompt 钉死约束防 DeepSeek 编盘中故事(Phase B);③ 候选池「今日续强确认」视图——**收窄=只对当日盘后圈的 20 只候选叠加实时态,非全市场盘中选股**(那喂追高病根,明确不做),新端点 `GET /candidates/intraday` 读时叠加不落库(Phase C)+ 双端盘中确认视图(Phase D)。**关键选型(定死不留施工;口径以下一条 plan-critic 修订条为最终准)**:盘中量能口径 = **已开盘时长折算日量**(`current_vol/elapsed_min×240`,跨午休 240min,头 **60min**→early、收盘→closed、缺基准→no_base;明确不选"vs 昨日同时段");VWAP=`amount/(volume×100)`(元/股,`volume<=0`→null 降级);盘中时段以本 feature 专用 `_is_intraday_window`(交易日 09:30–15:00 含午休)判定、窗口外实时字段全 null + 刷新禁用;拉价 on-demand 独立拉一拍(不接 monitor tick、不破"每源每 tick ≤1 拉"纪律);盘中上下文只作 LLM 补充事实不改 verdict/advice 二元派生;新端点复用 `require_token`。**旧债一并收(Phase E)**:两源盘中真复测(§3 待联调挂久),交易时段冒烟验两源价量一致性/VWAP 合理性/量能折算落地数字。**不动契约**:3 硬线/-5.0·-4.9 口径/D4 count==4/守味隔离(只注 history_digest)/绿涨红跌/规则常量单一源/选股因子。门禁基线 pytest 450 / XCTest 95 起步(预计 A+B+C 新增后端 ≥30、D 新增客户端 ≥6)。
- **[2026-07-05] v1.4 plan-critic 修订(1 致命+3 重要+6 建议,全吸收)**:**致命#1** VWAP 单位写反差 100 倍(`amount/volume`=元/手=100×每股均价、`price≥vwap` 恒 false 且假 Quote 单测照绿)→ 全文改 `vwap=amount/(volume×100)`(元/股),与 `form.py:173` 口径互指(form 是千元/手 ×1000,realtime 归一后元/手只 ×100,勿照抄系数),Phase A.3/E.2/§4 三处同步 + 单测要求用真实比例 amount 造假 Quote。**重要#2** is_trading 判定与折算口径打架(量能设计跨午休/closed,但复用 `loop._is_trading_now` 会把午休判 False 致跨午休设计与 closed 成死码)→ 本 feature 单立 `intraday._is_intraday_window(now)`=交易日且 09:30≤now<15:00(**含午休**,午休累计量/VWAP 有效),B/C 端点均调它、**明令禁复用 loop 窗口**;closed 仅 now==15:00 边缘兜底。**重要#3** 客户端 `get()` 写死 12s 无 timeout 参 → Phase D.2 明写给 `get` 加 `timeout=12` 可选参、盘中确认传 30。**重要#4** coach 路径对同 code 拉两遍 daily(端点 prev5 + `_fetch_form` 各一)→ 改 `_fetch_form` 顺带吐 `prev5_avg_vol`、snapshot 组装下沉编排层(quote 由端点传入、prev5 复用 form,唯一路径),`/chat` 每轮追问不叠额外拉取。**6 建议全收**:#5 prev5 按 `(code,trade_date)` 进程内缓存(仿 `load_industry_map`);#6 chg/openChg 加 `pre_close>0` 除零守卫→null;#7 `asof` 取第一个非空 quote.ts;#8 prompt 两量能数标签区分(「昨日 EOD 放量倍数」vs「盘中折算量比(估算)」)防混谈;#9 客户端「盘中确认」按钮初始可点、以后端 `isTrading` 定禁用(不造日历);#10 客户端叠加按 `code` join 不靠顺序;#11 early 阈 30→**60min**(A 股早盘量能前置、10:30 前折算系统性高估偏多头,提保守阈)+ prompt 护栏句/UI 文案点明"早盘折算通常偏高"。**建议#11 取舍**:采纳"提 early 阈到 60min"这一支(而非仅文案点明),因偏差方向恰好利多怂恿追高、正撞用户追高病根,值得用更保守阈直接屏蔽早盘不可靠折算,并叠加文案双保险。门禁预计后端 ≥30(A≥14/B≥8/C≥8)、客户端 ≥6。待施工。
