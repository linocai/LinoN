# LinoN — A 股小资金短线交易系统 · PROJECT_PLAN

> 唯一权威施工件。上半部为生效 Plan,下半部为变更日志。设计源:`交易系统_ProjectPlan_v2.md`(已完全闭合)。

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
- **门禁数字**:已发布 **1** 个阶段(阶段1,live `https://ln.linotsai.top`);在施工 **0**;下一阶段(阶段2 选股+决策)待规划。**后端 pytest 105 条全绿**(阶段0 的 40 + track A 56 + track B 联调 2 + 审后修复 7);**客户端 XCTest 17 条全绿**;**双端 build iOS Simulator + macOS 各 `BUILD SUCCEEDED`**。
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
| **2 候选+决策**(下一期) | 粗筛 / 排序截断 / on-demand 深析 / 中间地带 | CandidatesView + AnalysisView(三类消息 + 结构化深析卡 + 教练 UI 壳)+ 满仓闭门联动 |
| 3 复盘闭环 | Reviewer / 打分 / 闭环注入 / 教练"大脑" | ReviewView + MemoryView + 教练 UI 接复盘历史 |
| 4 收尾 | — | K 线/分时图、舆情展示、双端真机 E2E 打磨 |
| V2(推后) | 历史行情重放 / 纪律陪练沙盒(陪练非裁判) | 临场纪律陪练 |

## 4. 当前版本 Plan —— 阶段 2:选股 + 决策(待规划)

阶段2 开工时由 @planner 填充(粗筛过滤 + 排序截断 + 候选列表 + on-demand DeepSeek 深判 + 中间地带;需 Tushare token)。阶段1 全文已归档 `archive/stage1_脊椎今日台_plan.md`。

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

- **prod 端到端完整闭环**(阶段1 收尾):本期 sandbox 链路已验通;剩 App 切 prod 环境 + 填 prod `API_TOKEN`(已生成)→ 注册 device token 到 prod DB → 真机开仓/监控真推完整走一遍。
- **Tushare token 待购/录入**(阶段2):2000 积分会员(约 200 元/年),购后写入 ECS `.env`;**阶段1 EOD 资金校验无 token 自动降级跳过**,不阻塞。
- ~~`.p8` 交接到 ECS~~:已搬(`/opt/linon` 下 600 `linon:linon`)。
- ~~iOS 真机 + 真签名验证~~:已通(ECS→APNs sandbox→真机推送 200,锁屏卡 + 动作按钮)。
- ~~ECS SSH 连接方式~~:已配(`deploy@118.178.122.194:/opt/linon`,公钥登录,`backend/.env` 已填三要素)。

### 用户网页操作清单(必须在网页手动办理)

- **Tushare 充值/积分**(阶段2):`https://tushare.pro/`(2000 积分会员)。
- ~~DNS A 记录 `ln.linotsai.top → 118.178.122.194`~~:✅ 已加并生效(certbot 证书已签)。
- ~~APNs 鉴权密钥(.p8)~~:✅ 已生成(Key ID `Q963AP3VY8`)+ App ID 已注册开 Push,`.p8` 已搬 ECS。

### reviewer 阶段1 推迟项(阶段2/3 启动前消化;全文见 `archive/REVIEW_REPORT_阶段1.md`)

- **(阶段3 前)`trades.open_time` 仅日期粒度**(🟡#3,`store.py:316`):存 `buy_date` 非开仓时刻,复盘算持仓时长会失真;阶段3 复盘前补真开仓时刻。
- **(阶段2 前可选)周末/节假日录入 `buy_date` 落上一交易日**(🔵#1,`app.py:43`)→ D 计数提前一天、D4 早一交易日;考虑改取**下一**交易日,或开仓回包带 buy_date 供确认。
- **(运维)`deploy/linon.service` 仓库仍是阶段0 草稿**(🔵#4,`ExecStart=/usr/bin/true`)与 ECS 真 unit 脱节:把 ECS 真 unit(hardening + 正确 ExecStart)回写仓库作权威模板。
- **(打磨)客户端 `-4.9` 红卡 vs 后端 `-5.0` 推送**(🔵#2):pnl∈(-5.0,-4.9] 窗口横幅文案偏早,可改"逼近止损线"。
- **(打磨)EOD 推送"当日已推"依赖内存 `last_eod_date`**(🔵#3,`loop.py:211`):重启/错过窗口可能漏/重推,可落库防重启漏重推。
- **(打磨)开仓 `_resolve_name` 拉名失败落 code 当 name**(🔵#5);`Info.plist` 对 `127.0.0.1` 的 `NSIncludesSubdomains` 无意义(🔵#6)可删。

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

- **[2026-06-20] 立项**:v2 设计蒸馏为权威 PROJECT_PLAN.md,锁定 4 项施工决策(持仓计数 D1 起算 / 日历静态兜底 / rsync 部署 / venv+requirements),进入阶段 0 施工准备。
- **[2026-06-21] 用户视角走查修订**:锁定空仓起步、止损 -5% 自动派生 + ±1% 执行容差;修正阶段0 契约(`trading_window` 两段 / Quote 补涨跌停价 / `positions` 止损线改派生、开仓录入去手填);补阶段0 已知限制(停牌盲区、D4 无兜底);沉淀"用户流程坑清单"入 Backlog 待分阶段回填。
- **[2026-06-21] 设计稿并入**:客户端 hi-fi 完成稿到位(`design_handoff_linon/`:5 屏+锁屏推送、两签名组件、DesignTokens/Models),路线图重切为后端/前端双轨(每屏照终稿、无 throwaway 最小壳、阶段4 缩水)。锁 **iOS+macOS 多平台**(共享核心+平台分叉壳)。**-10% 极强趋势止损例外砍除**——止损统一 `buy×0.95` 纯派生不落库(反转上一版"必须落库",对齐 Models.swift 单一事实源);0.4 schema 移除 `stop_line` 列。收编客户端↔后端契约(DeepAnalysis schema / entry_snapshot 两串 / 规则常量单一事实源(触发线口径定死 -5.0)/ 签名组件公式 / 绿涨红跌 / 教练 UI-大脑 拆分),新增 §4b。monorepo 重组 `backend/`+`client/`,`sync.sh` 只同步 `backend/`。-10% 例外列入后期 backlog。
- **[2026-06-21] 阶段0 完工(0.1–0.7)**:数据层四件套 + 部署脚手架 + 冒烟脚本全部落地并本地验收;git init + 干净首提交。目录 = `backend/app/{config,data,db,calendar,smoke}` + `scripts/{setup,sync}.sh` + `smoke.py` + `deploy/linon.service`(草稿态)+ `tests/`(pytest 40 条全绿)+ `client/` 两 .swift 契约。**关键决策/偏离**:① 后端 schema 严格照 plan §4 DDL(`positions` 无 stop_line 列、止损线读取时 ×0.95 派生);**偏离记**:`trades` 表照 plan DDL 建,**未加** Models.swift 上展示用的 `name`/`note` 列(plan DDL 为后端权威,客户端那两列留阶段3 复盘细化时评估,已记 CLAUDE.md)。② `kept_stop/kept_take/kept_time/broke_rule` 用机械规则(止损容差带 [-6%,-4%]、止盈 +15%、D4),**注明阶段3 细化**。③ config 加标准库 fallback(仅 pydantic-settings 未装时启用,不掩盖正式安装)。④ 静态日历表查证官方 2025/2026 休市+调休补班日硬编码,`verify_against_trade_cal` 留作 token 到位后比对。**待联调**:Tushare 真 token 拉数 / 实时价联网+盘中复测 / ECS rsync+远端 setup / systemd enable(均列入 §5 用户侧收尾)。项目专属坑沉淀入根 `CLAUDE.md`(新浪 Referer、两源 bid/ask 顺序相反、calendar 包名撞标准库、pydantic v2 不可 setattr 等)。
- **[2026-06-21] 阶段1 track A(后端脊椎)完工**:实现 FastAPI 应用(绑 `127.0.0.1:8001`,单 unit——监控作 app 内后台 asyncio 轮询,不另起进程)。**端点 6 个**(均过 `require_token` Bearer 鉴权,`hmac.compare_digest`,启动 fail-fast `len≥16`;health 免鉴权):`GET /api/v1/health`、`POST /devices`(token upsert)、`POST /positions/open`(派生 stop_line=buy×0.95、自动补 entry_snapshot/buy_date、拒满仓 409 slots_full / 拒重复 code 409 duplicate_holding / 字段错 422)、`POST /positions/{id}/close`(落 trades+归档、非持仓 404 not_holding、回 pnl/kept_*/broke_rule)、`GET /positions`(holdings+free_slots,形状对齐 Models.swift 含 name、不含 stop_line)、`POST /alerts/{code}/ack`(停升级)。**监控 A.3**:交易时段每分钟拉价判 3 硬线(止损≤-5.0/止盈≥+15.0/D4),T+1 感知(D1 命中→"明日处理"不喊"必走")、涨跌停一字封死感知、两源一致性校验(差超阈标"行情存疑"不触发)。**APNs A.4**:token-based JWT(ES256,`send_push` 可注入 transport,测试用临时 EC key 验签、不真连 Apple);升级状态机(未 ack 按 `ESCALATE_INTERVAL_MIN` 重复推+角标递增,ack 停)。**EOD A.5**:盘后每持仓推盈亏%/D几/明日 D4 预警,无 Tushare token 资金段降级注明。新增 `app/{api,monitor,push}` 包 + `store.device_tokens` 表 + 6 个测试文件(56 条);依赖钉版本 `PyJWT==2.9.0`/`cryptography==44.0.0`/`httpx[http2]==0.27.2`(兼容 Py3.9)。**本地真跑通**:`uvicorn` 起服务 curl 全闭环 + pytest 96 全绿。**关键决策/偏离**:① 规则常量(-5.0/+15.0/D4/容差带)单一事实源复用 `store.py` 顶部常量,监控不另写;② ack 按 code 维度停该票所有未确认硬线(一推可聚合止损+D4 两线);③ `entry_snapshot` 本期占位串(资金快照阶段2 接 Tushare);④ EOD 资金二次校验本期纯占位(有/无 token 都不真查 moneyflow,口径校验留联调)——**未偏离 plan**(plan A.5 即"占位+无 token 降级")。**待 track C/真机**:真 APNs 实推(无设备 token,客户端未建——A.4 已实现+单测,真机实推留 C.3)、ECS 部署、`.p8` 搬 ECS。
- **[2026-06-21] 阶段0 归档 + 阶段1 立项**:按文件规范收口阶段0——§4 全文(Phase 0.1–0.7)+ §3 验收实施记录移入 `archive/stage0_基建_plan.md`,主文件 §4 清空改写为阶段1 Plan,§3 阶段0 压一行;§4b 客户端契约跨阶段保留主文件。**阶段1(脊椎+今日台)Plan 落定**:三组并行——A 后端脊椎(A.1 FastAPI:8001+单密钥鉴权+设备注册 / A.2 开清仓录入 API+漏录防护 / A.3 监控+3 硬线+T+1+涨跌停+多源校验 / A.4 APNs 直连+升级重复至确认 / A.5 EOD 摘要)、B 客户端地基(B.1 多平台工程+tokens/models / B.2 AppModel+导航壳+两签名组件 / B.3 TodayView+开清仓 sheet / B.4 联调+锁屏推送 iOS)、C 部署(C.1 ECS 目录+linon 用户+secret / C.2 nginx 子域名+证书 / C.3 systemd+APNs 真机实测)。**关键决策**:端口定 8001(避已占)、API 单密钥鉴权(沿 lw)、子域名 `ln.linotsai.top`(已定)、监控**单 unit**(API 内起轮询,内存紧)、APNs sandbox 网关(dev 直装)、规则常量继续引用 §4b 单一事实源(-5.0/+15/D4/容差带)。**用户侧新增**:DNS A 记录 `ln.linotsai.top`、`.p8` 交接 ECS、iOS 真机验证;Tushare 推后阶段2(EOD 资金校验无 token 降级)。"对账"暂缓阶段2。
- **[2026-06-21] 阶段1 track B(客户端)完工**:SwiftUI **iOS + macOS 多平台** App(单 target,xcodegen 生成 `.xcodeproj`,Bundle ID `top.linotsai.linon`,deploymentTarget 26.0)。**B.1** 工程结构 `client/LinoN/{App,Networking,Calendar,Components,Views,Push,Resources}` + `LinoNTests/` + 根契约 `DesignTokens.swift`/`Models.swift`(直接用不改契约)。**B.2** `@Observable AppModel`(holdings 真数据+派生 KPI/触损横幅/form 派生止损)+ 导航壳分叉(iOS 底部 TabView 今日/候选/复盘/记忆,后三占位;macOS 240px 玻璃侧栏+Settings 场景)+ 两签名组件精确还原(`DualLineTrack` marker `clamp((pnl+5)/20,2,98)`+左红区+成本刻度+触损呼吸光环;`HoldingDayPips` D1–D4 四态)。**B.3** TodayView 双端(KPI Hero/横条 + 教练横幅占位文案 + HoldingCard 触损红卡/双线/距盈距损/D pips/按钮)+ 开仓 sheet(止损只读派生 ×0.95 拒手填)+ 清仓 sheet(实时盈亏+次日09:30)+ toast/reason 提示;iOS `.sheet` / macOS 居中 modal。**B.4** 启动拉 `GET /positions` 渲染+客户端本地算 pnl/track/hitStop;`APIClient` 全端点+结构化错误映射(slots_full/duplicate/not_holding);iOS `PushManager` 通知授权→device token→`POST /devices`+硬线 category(标记次日清仓/问教练)+点动作调端点+`/alerts/{code}/ack` 停升级;后端连接 `AppConfig`(dev 默认 `127.0.0.1:8001` + Settings 填 token,**留 prod `ln.linotsai.top` 口子**)。**验证**:双端 `BUILD SUCCEEDED`(iOS Simulator LinoJ-iPhone16Pro 26.5 + macOS)无 body 超时;iOS 模拟器启动渲染 3 持仓+触损红卡;开/清仓闭环 curl 验全路径;客户端 17 单测 + 后端 98 单测全绿。**关键决策/偏离**:① **唯一允许的后端改动**——`GET /positions` 按需拉一拍实时价填 `price`(§4b 联调点,拉价失败 price=0 客户端兜底),`flow3d` 仍占位待 Tushare(+2 后端测);② iOS ATS 例外(`NSAllowsLocalNetworking`+127.0.0.1)解明文连本机 uvicorn——**记 CLAUDE.md**;③ marker 钳 98(对齐 Models.swift 契约,非设计 README 的 100)、`take_line` 浮点 55.545→55.54——单测按契约断言;④ API_TOKEN 不入源码(UserDefaults/env/gitignored plist),`LocalSecrets.plist` 加 .gitignore;⑤ candidates/review/memory 仅导航占位(阶段2/3),教练横幅占位文案(大脑阶段3)——**未偏离 plan OUT 范围**。**待 track C/真机**:真 APNs 投递、真 device token(模拟器拿不到)、锁屏通知卡+动作、macOS 系统通知、ECS 部署。
- **[2026-06-22] iOS Settings 屏**(小增量):新建共享 `SettingsView`(环境 Picker dev/prod + API Token 明文/掩码切换 + baseURL 覆盖 + 只读 resolvedBaseURL/device token/registerError + 连接自检 GET /health 与 /positions + iOS「重新注册推送」);iOS TodayView 顶部加齿轮按钮 `.sheet` 弹出,macOS Settings 场景复用同一视图(平台分叉:无推送段)。双端 `BUILD SUCCEEDED` + 17 单测全绿;macOS 实跑验通环境切换 dev→prod 即时改 resolvedBaseURL(https://ln.linotsai.top)。仅动客户端(`AppModel` 加 iOS-only `pushManager` 弱引用、`LinoNApp` 注入并复用共享视图),未碰后端/存储解析逻辑。
- **[2026-06-22] 阶段1 审后修复(reviewer 🟡#1/#2)**:**#1 监控每 tick 拉价从 3 次降到 2 次**——`run_one_tick` 不再既调 `get_realtime_quotes`(1–2 拉)又调 `_build_two_source_quotes`(2 拉);改为每 tick 仅 `two_source_fn`(两源各拉一次),price 从这同一对结果**派生**(优先 sina、缺则 tencent,与原降级口径一致),一致性校验复用同对结果(不额外再拉)。`quotes_fn` 仅显式注入时才覆盖 price(向后兼容/老测试)。**#2 D4 时间升级重启不丢**——升级状态仍内存,但启动 lifespan 调 `rebuild_time_escalations` + 每 tick `_ensure_time_escalation`:对 `status='holding'` 且 `count_holding_trade_days≥4` 的逾期持仓,始终保证一条 active 未 ack 的 time 升级(补 D4 后 count≥5 时 `classify` 不再产 time 事件的缺口),直到 ack 或清仓;**幂等**——`EscalationManager.has_track(code,kind)` 已存在(含已 ack)即不重建、不重置 badge。**未触碰任何契约**(`should_force_close` 的 `count==4`、规则常量 -5.0/+15.0/D4/容差带均未动;这是 monitor 层恢复逻辑)。改 `app/monitor/{loop,escalation}.py` + `app/api/app.py` lifespan + 新增 7 条监控测试;`pytest 105 全绿`(原 98 无回归),uvicorn `/health` 冒烟 ok。
- **[2026-06-22] 阶段1 track C(ECS 部署 + 真机 APNs)完工**:真上 hz ECS(`deploy@118.178.122.194`)。**C.1** 建 nologin 用户 `linon` + `/opt/linon`(`deploy:linon` 2770 setgid);`sync.sh` rsync `backend/` + 远端 `setup.sh`(阿里云镜像);`.p8` + `.env`(生产 `API_TOKEN`/APNs 凭证)`linon:linon` 600,`data/` owner linon。**C.2** nginx site `linon` 反代 `:8001` + certbot 证书 `ln.linotsai.top`(health ok)。**C.3** systemd **单 unit** `linon.service`(User=linon+hardening,active);**ECS→APNs sandbox→iPhone 真机推送实测 status 200**(锁屏硬线卡+动作按钮)。**修真机才暴露的接缝/部署 bug**:① 客户端 category `LN_HARDLINE`→`HARDLINE` 对齐后端(否则锁屏无动作按钮);② 补 iOS `aps-environment` entitlement(`[sdk=iphone*]` 仅 iOS);③ `sync.sh` GNU-rsync 守卫在 `pipefail` 下被 SIGPIPE 误判(改命令替换+case);④ `push_test.py` 补 sys.path;⑤ rsync `-a` 冲 `/opt/linon` setgid 复原(同 lw/lf)。App 图标 icon_N→1024 不透明各档。**环境坑**:Mac 代理(Stash)把 Apple 开发者/登录端点走直连被 GFW SNI 重置 → Xcode 登录 -1200 TLS 失败 → 改走节点解(`hz_info.md` 已同步)。**待真机 prod 端到端**:App 切 prod + 填 `API_TOKEN`(已生成)→ 注册 device token 到 prod DB → 开仓/监控真推完整闭环。
- **[2026-06-22] 阶段1 收口归档**:阶段1 三轨(后端脊椎 / 客户端双端 / ECS 部署)完工并上线 `https://ln.linotsai.top`,真机 APNs sandbox 端到端验通;reviewer 审查**零致命**,审后修复 #1(监控每 tick 拉价 3→2)/#2(D4 时间升级重启不丢)已部署,pytest 98→105 全绿。按文件规范收口:§4 全文(A.1–A.5 / B.1–B.4 / C.1–C.3 + 接口契约)+ 实施记录移入 `archive/stage1_脊椎今日台_plan.md`,主文件 §4 清回占位待阶段2(选股+决策,需 Tushare token);§4b 客户端契约跨阶段保留主文件。reviewer 推迟项(open_time 粒度 / 周末录入 buy_date / linon.service 草稿回写 / 文案与 EOD 落库打磨)入 §5 Backlog 作阶段2/3 前置。门禁:已发布 1 / 在施工 0 / 下一阶段2 待规划。
