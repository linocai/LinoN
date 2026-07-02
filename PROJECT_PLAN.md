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
- **v1.2.1(深析对话化 + 追问接 DeepSeek)施工中,Phase A+B+C 已完工,剩 Phase D(全量部署)**:三件事——① 候选行只有「深析」按钮进(双端,Phase B ✅);② 初始深析从结构化三轴卡改对话式自由文本(Phase C ✅);③ 追问框真接 DeepSeek 多轮问答(Phase C ✅)。**核心架构决定**:新增统一对话端点 `POST /chat`(不合并进 `/analyze`/`/coach`,二者保留);对话 = prose reply + 旁路抽 verdict 落库保回测链路(仅首条候选对话且非降级才落,决定2);后端无状态、多轮上下文客户端全量回传(`chatTurns(from:)` 收敛 user/assistant 两值、截断保留最近 8 轮且保留最近一条 assistant);守味隔离沿阶段3(只注入 history_digest,绝不注入 review_ref);对话专属超时 25s×2(不复用 `/analyze` 的 12s×3)。Phase B:候选行整行不可点、macOS/iOS 均改真「深析」Button 唯一入口,双端 build + 快照核对通过。Phase C:`APIClient.chat()` + `AppModel.runChat/sendComposer` 改接 `/chat`,`firstVerdict`/`firstAssistantMsgId` 只在 `isFirst` 时写(追问翻脸按钮不回溯消失),买入按钮组搬进对话气泡下方,`.analysis` 消息分支删(死代码,`DeepAnalysisCard` 本体保留供快照测试),资金时序标注移到对话区顶部常驻;coach 触损/中间地带路径不变仍走 `/coach`。后端 pytest 337 全绿(Phase A 新增 28);客户端 XCTest 49 全绿(Phase C 新增 5:`chatTurns` 序列化/截断 4 条 + `sendComposer` 新分支 1 条);双端 `BUILD SUCCEEDED`。**剩 Phase D 全量部署未做**(含 store 拆包重构 + v1.2.1 新增两步走)。Plan 全文见 §4。
- **门禁数字**:**已发布 2 阶段**(阶段1+阶段2,live `https://ln.linotsai.top`,阶段2 于 2026-06-28 上线;阶段2.5/阶段3/阶段3.1 为纯后端/全栈小版本,代码完工待用户部署;v1.2.1 施工中);**阶段4(K线/舆情/双端真机 E2E)待规划**。后端 pytest **309 全绿**(阶段1 基线 105 + 阶段2 新增 88 → 193 + 阶段2.5 新增 34 → 227 + 阶段3 新增 49 → 276 + 阶段3.1 新增 33);客户端 XCTest **44 全绿**(17 + 阶段2 新增 15 → 32,阶段2.5 无前端改动,阶段3 新增 8 → 40,阶段3.1 新增 4);**双端 build iOS Simulator + macOS 各 `BUILD SUCCEEDED`**;真 key 活体冒烟过(Tushare 5490 行/茅台白酒归类符合假设;DeepSeek `json_object` 真输出夹紧成合法 DeepAnalysis;analyze/coach 真 key curl 闭环;离屏快照逐屏目检候选行/满仓🔒/深析卡 fund_asof/教练红橙卡;阶段2.5 真 token 限频冒烟 65/65 天 adj_factor 全部成功,零限频失败,耗时 39s→45.5-45.7s)。阶段2 新增端点 **4 个**:`GET /candidates`、`POST /candidates/refresh`、`POST /candidates/{code}/analyze`、`POST /positions/{id}/coach`;阶段2.5 新增只读端点 **1 个**:`GET /candidates/outcomes`;阶段3 新增端点 **3 个**(`GET /review`、`POST /review/{week}/note`、`GET /memory`)+ `/coach` 新增可选字段 `review_ref`;阶段3.1 无新增端点,`GET /candidates` 候选 dict 新增可选展示字段 `score`(int,前向兼容)。
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

## 4. 当前版本 Plan —— v1.2.1 深析对话化 + 追问接 DeepSeek

> 立项 2026-07-02。三件事:① 候选行只有「深析」按钮进(双端);② 初始深析从结构化三轴卡改为对话式;③ 追问框真接 DeepSeek 自由问答。核心是引入**统一的对话式 DeepSeek 端点**。范围:全栈(后端新增对话端点 + 客户端渲染改造),含一次**全量部署**(顺带带上未部署的 store 拆包重构)。

### 4.0 核心架构决定(已拍死)

**决定 1:新增统一多轮对话端点 `POST /chat`,不合并进 `/analyze`/`/coach`。** 三件事的 2、3 共用它;`/analyze`(结构化三轴卡)与 `/coach`(二元建议)**保留原样不动**——回测链路(`analysis_verdicts`/`candidate_outcomes`)、教练红橙卡都依赖它们的结构化输出,砍不得。对话端点是**并行新增的一条自由文本链路**,与结构化链路共存。

**决定 2:对话 = prose 主体 + 旁路抽 verdict 落库(不断回测链路,降级绝不污染)。** 对话端点让 DeepSeek 返回**两段式 JSON**:`{ reply: "<自由中文分析,concise ~200–250 字>", verdict: "可进|观望|不进" }`。`reply` 是给用户看的自然语言(客户端渲染为 assistant 气泡);`verdict` 是机器可读旁路,**仅初始深析(候选第一条消息)且非降级时**落 `analysis_verdicts`(复用 `_maybe_persist_verdict`),追问轮不落。
- **落库门槛(堵 plan-critic 致命2:降级污染回测)**:`chat()`/`degraded_chat()` 返回体**必须带 `degraded: bool` 标记**(现 `_maybe_persist_verdict`[app.py:357] 只查 `verdict in _VERDICTS`、降级"观望"照落,现契约不存在"降级不落";`degraded_chat` 现也无标记 → 必须补)。端点落库分支收紧为 `if is_first and mode=="candidate" and not result["degraded"]:` 才落。
- **为什么必须堵**:对话化后 thread 退出即清、重开即 `is_first=true`,重复首判远比 `/analyze` 频繁;`upsert_analysis_verdict` 是**覆盖式** → 白天真"可进"会被晚上一次抽风降级的"观望"覆盖,回测静默污染。`not degraded` 门槛是硬要求,非可选优化。(`/analyze` 端点 `_maybe_persist_verdict` 同款降级污染隐患记 §5 Backlog,本版本不动其行为。)

**决定 3:多轮上下文由客户端持有、每次全量回传,后端无状态。** `POST /chat` 请求体带 `messages: [{role, content}]`(OpenAI 风格历史) + `context`(标的元信息)。后端**不落库 thread**(SQLite 不加会话表),每次把历史拼进 DeepSeek `messages` 数组。理由:单用户、thread 短暂(退出深析即清)、无状态最简、与现有降级链路一致。历史长度客户端截断(见 C3 上限),防 token 爆。

**决定 4:资金/形态事实由后端注入 system/context,不靠模型编。** 对话端点复用 `analyze.py` 的 `_fetch_form`/`_fetch_fund` 取真实放量倍数、东财净流入、`fund_asof`,拼进 DeepSeek 的 context 段(同 `build_user_prompt` 现有做法)。`fund_asof` 随响应返回,客户端**仍用 DeepAnalysisCard 那条资金时序标注**("资金面 = 截至 {date} EOD · 东财主力口径(非盘中实时)")显示在对话区顶部或每条 assistant 气泡下(见 E2)。system prompt 硬性要求模型只依据注入事实、诚实交代资金口径。

**决定 5:「全仓买入并录入」绿按钮从深析卡搬到对话区。** 对话式无三轴卡,故:初始深析 assistant 气泡返回后,**若旁路 verdict == 可进 且当前是候选模式**,在该气泡下方渲染「全仓买入并录入 / 看下一只」按钮组(复用现有 `buyFromAnalysis()`)。verdict 非"可进"则不显按钮。

**决定 6:护栏在 system prompt 定死,守味隔离沿用阶段3。** 对话 system prompt 硬编:诚实交代资金=东财 moneyflow_dc EOD(非盘中实时);绝不越 -5%/+15%/D4 铁律、不替用户扣扳机(只给判断不替决策);中性 `history_digest` 才进 prompt,带情绪 `review_ref` **绝不进对话 prompt**(沿 `brain.py` 两路径分流)。对话端点**只注入 history_digest,不取 review_ref**(review_ref 是 coach 红橙卡专属,对话区不用)。

**决定 7:对话超时不复用 `/analyze` 的 12s(堵 plan-critic 致命1:prose 生成慢会系统性降级)。** `stream=False` 下 DeepSeek 整段生成完才回首字节,read timeout 卡的是**整段生成时间**;现 `_READ_TIMEOUT=12s` 是按三轴紧凑结构(~3.3s)调的,对话 reply 几百字生成 15–25s 属正常 → 复用 12s×3 会全被掐死、每次被掐上游照样计费,且慢生成与卡死连接无法区分。**对策两条并用**:① `CHAT_SYSTEM_PROMPT` 硬限 reply 长度(~200–250 字)+ payload 设 `max_tokens`(防截断 JSON,取值见 A2)压住生成时长;② 对话**单列一组超时常量**:`_CHAT_READ_TIMEOUT=25s` / `_CHAT_CONNECT_TIMEOUT=6s` / `_CHAT_MAX_ATTEMPTS=2`。总预算重算:数据补全(form+fund+sentiment ~2–4s)+ 2×(connect + read 25)——**现实最坏 ≈ 2×25+4 ≈ 54s**(connect 实测亚秒,EdgeOne 0.009s);**理论最坏(含 connect 也超时)≈ 2×(6+25)+4 ≈ 66s > 客户端 60s**,该极端由客户端 60s 超时走 C3 失败路径(追加本地降级文案、不弹错不崩)兜底——服务端稍后完成的响应被丢弃、即便落库也是真 verdict 无污染,可接受。对话链路**不复用** `deepseek.py` 现有 `_READ_TIMEOUT/_MAX_ATTEMPTS`(那组留给 `/analyze`/`/coach` 结构化短响应)。

### 4.1 端点契约(定死,施工逐字段对齐)

**新增端点:`POST /api/v1/chat`**(鉴权同 `require_token`)。

请求体:
```json
{
  "mode": "candidate | coach",          // candidate=候选深析对话 / coach=持仓追问对话
  "code": "002184",                     // 6 位裸码(客户端已 _bare);coach 模式此码仅参考,
                                         //   后端一律以 position_id 对应持仓的 pos["code"] 为准(同现 /coach)
  "messages": [                          // 多轮历史(含本轮用户最新一条),OpenAI 风格
    {"role": "user", "content": "分析一下海得控制,这个位置能不能进?"},
    {"role": "assistant", "content": "..."},
    {"role": "user", "content": "那如果明天低开我该怎么办?"}
  ],
  "position_id": 12                      // 仅 coach 模式必带(取 pnl_pct/trade_day);candidate 模式省略
}
```
> 注:candidate 模式 name/sector 后端用现成 `_resolve_candidate_meta(bare)`[app.py:566] 从候选缓存补,**客户端不传**;role 只允许 `user`/`assistant` 两值(见 C3 序列化契约,`.coach`/`.analyze` 前端映射后不出现)。

响应体(**上游失败仍 HTTP 200,返降级占位**):
```json
{
  "ok": true,
  "code": "002184",
  "reply": "<DeepSeek 自由中文分析,concise ~200–250 字>",
  "verdict": "可进 | 观望 | 不进",       // 机器可读旁路(客户端据此决定是否显买入按钮)
  "fund_asof": "2026-07-02",            // 资金基准日(东财 EOD),客户端显时序标注
  "is_first": true,                      // 是否本 thread 首条(= messages 里 assistant 条数==0)
  "degraded": false                      // 上游降级标记(缺 key/超时/非法 JSON → true);
                                         //   落 analysis_verdicts 的必要条件之一(见契约要点)
}
```

契约要点:
- **`is_first` 判定**:后端按请求 `messages` 里 `role=="assistant"` 的条数为 0 判定"这是初始深析"。
- **买入按钮显示条件(客户端)**:`is_first==true && mode=="candidate" && verdict=="可进"`。
- **落 `analysis_verdicts` 条件(后端,三者同时)**:`is_first==true && mode=="candidate" && degraded==false`(verdict 已由 `clamp_chat` 保证 ∈{可进,观望,不进})。取 entry_date 复用 `candidate_entry_date_of`,查不到不落。**`degraded==false` 是硬门槛**(见决定2:堵降级观望覆盖真可进的回测污染)。
- **降级**:缺 `DEEPSEEK_API_KEY`/超时/非法 JSON/卡死重试耗尽 → `reply` 返诚实降级文案("深判暂不可用,维持纪律:止损 -5%、止盈 +15%、满 3 交易日第 4 日清仓。")、`verdict="观望"`、`degraded=true`、`fund_asof` 仍如实返回。**绝不抛崩**。走对话专属超时(决定7:read 25s / attempts 2,不复用 12s×3)。
- **coach 模式**:`position_id` 指向的持仓不存在/已 closed → **404 `not_holding`**(同 `/coach`)。存在则以 `pos["code"]` 为准,后端拉一拍实时价算 `pnl_pct` + `count_holding_trade_days` 算 `trade_day`,拼进 context(同 `/coach`)。
- **超时预算**:客户端 `/chat` 超时 **60s**;服务端对话链路总预算 ≈54s(决定7),留余量。

**DeepSeek 输出契约(对话式)**:新增 system prompt(`prompt.py` 的 `CHAT_SYSTEM_PROMPT`),要求模型返回 `{"reply": "...", "verdict": "可进|观望|不进"}` 的 JSON(仍走 `response_format=json_object`;prompt 天然含 "json" 字样满足 json mode 要求)。`reply` 是自然语言(concise ~200–250 字,可含换行分段),**不是三轴结构**。服务端 `clamp_chat(raw)` 夹紧:`reply` 非空字符串否则降级文案(空/非法 → `degraded_chat`);`verdict` 越界 → 观望。复用 `_loads_lenient` 容错(长 reply 撞 `max_tokens` 截成非法 JSON → 降级,与限长同解)。

**不改的端点**:`/candidates/{code}/analyze`、`/positions/{id}/coach`、`GET /candidates`、回测端点全部原样保留(客户端 openCoach 触损分支仍调 `/coach` 走红橙卡,见 C4 决策)。

### 4.2 Phase 拆分

依赖顺序:A(后端对话端点)→ B(前端候选行按钮,可与 A 并行)→ C(前端对话渲染,依赖 A)→ D(部署)。A 是全栈枢纽,先落。

---

**Phase A —— 后端对话端点 `POST /chat`(后端)**

A1. **`prompt.py` 加对话 system prompt + user prompt 拼装**:
- 新增 `CHAT_SYSTEM_PROMPT`:蒸馏现 `SYSTEM_PROMPT` 的三维度方法论(形态主轴→资金确认→消息排雷)+ 离场铁律(-5%/+15%/D4)+ 中间地带二元 + 历史纪律 guardrail,但**输出格式改为**:严格 JSON `{"reply": "<自由中文分析,可分段,用『』或换行组织,不用 markdown 标题>", "verdict": "可进|观望|不进"}`。硬编护栏:只依据注入事实、诚实交代资金=东财 EOD 非盘中实时、绝不越铁律、不替用户扣扳机(只判断不替决策)、verdict 只按当前这一笔客观判定(不因历史破线系统性调保守)。
- 新增 `build_chat_context_block(context) -> str`:把标的/形态/资金/舆情/fund_asof/history_digest 拼成一段**注入事实**(复用 `build_user_prompt` 的形态/资金/舆情文案逻辑),作为一条 `role=system` 或首条 `role=user` 的事实前缀。不含 review_ref。

A2. **`deepseek.py` 加 `chat(messages, context, *, transport=None) -> dict`**:
- 拼 `payload.messages` = `[{system: CHAT_SYSTEM_PROMPT}, {system: build_chat_context_block(context)}, *messages]`(历史原样透传;事实块用 system 角色)。`response_format=json_object`、`temperature=0.3`、`max_tokens=700`(压住 ~250 字中文 reply + verdict 的 JSON 不被截断)。
- **对话专属超时常量(决定7,不复用 12s×3)**:`_CHAT_CONNECT_TIMEOUT=6.0` / `_CHAT_READ_TIMEOUT=25.0` / `_CHAT_MAX_ATTEMPTS=2`;循环结构复用现 `analyze()` 的"全新连接重试"骨架,仅换这组常量。
- 新增 `degraded_chat(reason) -> dict` = `{"reply": "深判暂不可用,维持纪律:止损 -5%、止盈 +15%、满 3 交易日第 4 日清仓。", "verdict": "观望", "degraded": True}`;`chat()` 成功路径返回 `{..., "degraded": False}`(**degraded 标记是决定2 的硬要求**)。`clamp_chat(raw)` 夹紧 reply(空/非法 → 走 `degraded_chat`)/verdict(越界→观望),成功夹紧的结果标 `degraded=False`。缺 key/超时/非 200/非 JSON → `degraded_chat`。
- 可注入 `transport`(`httpx.MockTransport`)免单测联网。

A3. **`analyze.py` 加 `chat_stock(code, messages, *, mode, name, sector, pnl_pct, trade_day, history_digest, now, *_fn)` 编排**:
- 复用 `_fetch_form`/`_fetch_fund` 取真实形态+资金(东财 `ts_moneyflow_dc`),算 `fund_asof`(取实际数据最新交易日,同现逻辑);best-effort 舆情。
- **事实块每轮都注入(堵 plan-critic 重要6:口径统一)**:`chat_stock` **不判 is_first、每轮都补全 form/fund/sentiment**,保证追问轮 DeepSeek 也拿到真实事实(用户常在追问里问资金/形态)。为免每轮重拉 daily(130 天)+adj_factor+moneyflow+舆情白付 2–4s,**加进程内 `(bare_code, fund_asof_date)` 级缓存(当日 TTL)**:`_fetch_form`/`_fetch_fund`/`sentiment` 结果按 `(code, 当日 YYYYMMDD)` 缓存,同一 thread 内追问命中缓存不重拉。缓存为模块级 dict + 简单日期键失效(跨日自然失效),失败不缓存(下轮重试)。不引第三方缓存库。
- 拼 context dict(含 history_digest,**不含 review_ref**)→ 调 `deepseek.chat(messages, context)` → 返回 `{"reply", "verdict", "fund_asof", "degraded"}`(degraded 透传自 `deepseek.chat`)。可注入 `chat_fn`/`daily_fn`/`moneyflow_fn`/`sentiment_fn`/`adj_factor_fn`。全链路降级不崩。

A4. **`app.py` 加 `POST /api/v1/chat` 端点 + schema**:
- `schemas.py` 加 `ChatRequest`(mode: Literal["candidate","coach"]、code: str、messages: List[ChatMessageIn{role: Literal["user","assistant"], content: str}]、position_id: Optional[int])。role 只允许 user/assistant → 非法 role 由 pydantic 抛 422(客户端已保证映射,见 C3)。
- 端点逻辑:① `bare = _bare_code(body.code)`(candidate 模式用它;coach 模式下方以 pos code 覆盖);② coach 模式校验 `position_id` 持仓存在否则 404 `not_holding`,**取 `bare = pos["code"]`**(忽略 body.code,同现 `/coach`);③ coach 拉实时价算 `pnl_pct` + `count_holding_trade_days` 算 `trade_day`(candidate 模式两者 None);④ candidate 模式 `name, sector = _resolve_candidate_meta(bare)`(客户端不传);⑤ `history_digest, _ = _coach_brain(bare)`(**只取 digest,丢弃 review_ref**);⑥ `is_first = sum(1 for m in body.messages if m.role=="assistant") == 0`;⑦ 调 `_chat_fn(bare, messages, mode, name, sector, pnl_pct, trade_day, history_digest)`(可注入桥,同 `_analyze_fn` 模式);⑧ **落库(决定2 硬门槛)**:`if is_first and body.mode=="candidate" and not result["degraded"]: _maybe_persist_verdict(bare, {"verdict": result["verdict"]})`;⑨ 返回 `{ok, code: bare, reply, verdict, fund_asof, is_first, degraded}`。
- 加模块级 `_chat_fn = _default_chat_fn` 可注入替身(签名对齐 ⑦)。

A5. **单测(注入 transport/替身,不联网)**:candidate 首条对话返 reply+verdict+degraded=false、is_first=true、可进时落 analysis_verdicts;追问轮(messages 含 assistant)is_first=false、不落库;**降级路径(缺 key/超时)返 degraded=true 且 is_first=true 时也不落 analysis_verdicts**(堵决定2 污染);coach 模式非持仓 404;coach 模式 body.code 与 pos code 不一致时以 pos code 为准(拉 pnl/trade_day 用 pos code);缺 key/超时 → 降级 reply + verdict=观望 + 仍 200;history_digest 进 prompt 而 review_ref 不进(断言 build_chat_context_block 输出不含 review_ref 措辞);多轮 messages 原样透传进 payload;`chat_stock` 同一 thread 追问命中数据缓存不重拉(断言 daily_fn 调用次数)。

**验收标准 A**:`POST /chat` candidate 模式真 key 冒烟返 concise 自由中文 reply(~200–250 字)+ 合法 verdict + fund_asof + degraded=false;coach 模式非持仓 404、持仓存在以 pos code 为准;缺 key 降级返 200 占位 reply + degraded=true;`analysis_verdicts` 仅首条候选对话**且非降级**时落库(追问不落、降级不落);回测端点 `GET /candidates/outcomes` 的 verdict 维度仍能 join 到对话产生的 verdict;对话超时用专属 25s×2(不复用 12s×3);pytest 全绿(新增 ≥7 条),无回归。

---

**Phase B —— 候选行只有「深析」按钮进(前端 · iOS + macOS)**

B1. **去掉整行 Button**:`CandidatesView.swift` iOS `candidateList`(:80-84)与 macOS `candidateList`(:196-200)的 `ForEach` 里,去掉包裹整行的 `Button(action: openAnalysis)`,`CandidateRow` 直接渲染(整行不可点)。

B2. **iOS 行「深析」真按钮**:iOS 行(`iosRow`)当前右侧竖排是"价/涨/chevron"。**改为**:去掉 chevron,右侧竖排价/涨之下放一个**紧凑「深析」Button**(复用 macOS 的 `analyzeButton` 样式,尺寸按 iOS 窄屏缩小),`action: { Task { await model.openAnalysis(code: c.code) } }`。照 CLAUDE.md「iOS 候选行布局 ≠ macOS」——按钮放右侧竖排、不挤中列(名/警告/放量条)。

B3. **macOS「深析」真按钮**:`analyzeButton`(:482-496)当前是纯 `Text`(假按钮),macOS `macRow` 的 `analyzeButton.frame(...)`(:403)包成真 `Button(action: { Task { await model.openAnalysis(code: c.code) } })`。行其余列不可点;去外层整行 Button 后,**顺手删 `macRow` 的 `.contentShape(Rectangle())`(:407)**(整行热区已无意义,留着徒增行级 hit-test)。iOS `iosRow` 的 `.contentShape(:362)` 同理评估:若整行不再可点则一并删。

B4. **`xcodegen generate` 后双端 App target build**(改 View 必跑,全局经验;无新增 .swift 文件,B 只改现有文件,可不重生 project,但仍必须双端 build 验证)。

**验收标准 B**:iOS + macOS 候选行点行空白区**不进深析**,点「深析」按钮**进深析**;iOS 行布局窄屏不挤坏中列(名字不被省略号截断);双端 `BUILD SUCCEEDED`;客户端单测无回归。可视核对走 `ImageRenderer` 离屏快照(Dock 守卫下的退路,见 CLAUDE.md)。

---

**Phase C —— 初始深析对话化 + 追问接 DeepSeek(前端 · iOS + macOS)**

C1. **`APIClient.swift` 加 `chat(...)`**:
- 新增 `ChatResult { reply: String; verdict: Verdict; fundAsof: String; isFirst: Bool }` + 私有 `ChatResponse`(ok/code/reply/verdict/fund_asof/is_first)。
- `func chat(mode: String, code: String, messages: [ChatTurn], positionId: Int? = nil) async throws -> ChatResult`,`POST /api/v1/chat`,**timeout: 60**。`ChatTurn` = `{role: String, content: String}` Encodable。verdict 解码用现 `Verdict`(rawValue 中文)。

C2. **`AppModel.openAnalysis` 改走 `/chat`(候选深析对话化)**:
- 保留进全屏 + 顶栏 context + 首条 user 气泡逻辑;**`runAnalyze` 改为 `runChat`**:调 `client.chat(mode:"candidate", code:, messages: 由 thread 映射为 [ChatTurn])`,把 `r.reply` 追加为 **assistant 气泡**(`ChatMessage(role:.assistant, text: r.reply)`),`self.fundAsof = r.fundAsof`。**不再 append `.analysis` 结构化卡**。
- **买入按钮判定用专用字段,不留三选一(堵 plan-critic 重要4)**:`AppModel` 新增 `var firstVerdict: Verdict? = nil`、`var firstAssistantMsgId: UUID? = nil`。**仅当 `r.isFirst == true`** 时写这两个字段(记首条 assistant 气泡的 id + 其 verdict);追问轮(`isFirst==false`)**不覆盖**——这样追问翻"不进"不会让买入按钮回溯消失。`backFromAnalysis()` 清空这两字段(与 thread 一起 reset)。

C3. **`sendComposer` 真接 DeepSeek(多轮追问)**:
- `sendComposer()` **改 async**:append user 气泡后,把当前 thread 映射为 `[ChatTurn]`(见下序列化契约)回传 `client.chat(mode:, code: selectedCode, messages:, positionId:)`,追加返回 `reply` 为 assistant 气泡,刷新 `fundAsof`。**删除写死文案 `"我先看量能…"`**(AppModel.swift:421)。失败追加降级 assistant 文案(不弹 toast)。composer 发送时 `analysisLoading` 转圈(复用 thinkingRow)。
- **mode 判定不复用 `chatMode`(堵 plan-critic 致命3-b)**:`chatMode` 是 UI 语义(`openCoach` 中间地带刻意设 `.analyze`,AppModel.swift:375),复用它会把持仓中间地带追问当候选发出、丢 position_id + pnl/trade_day。**改为按业务状态判**:`let isHolding = holding(byCode: selectedCode ?? "") != nil`;`mode = isHolding ? "coach" : "candidate"`;`positionId = isHolding ? holding(byCode:)?.id : nil`。是持仓一律 coach 模式带 positionId。
- **thread→[ChatTurn] 序列化契约(堵 plan-critic 致命3-a)**:`ChatRole` 四值需显式映射到后端只认的 `user`/`assistant`:`.user → "user"`;`.assistant → "assistant"`;`.coach →` 序列化为 `"assistant"`(content 取 `msg.text`,即红橙卡的 reason 文案);`.analysis →` **跳过不序列化**(结构卡无自然语言 content,序列化会污染上下文)。**非法映射会撞后端 `Literal["user","assistant"]` 422**,故映射必须收敛到两值。抽成 `AppModel.chatTurns(from thread) -> [ChatTurn]` 纯函数便于单测。
- **截断(堵 plan-critic 建议)**:映射后**保留最近 8 轮(≤16 条)**,且**从 `user` 边界截起**(截断后首条必须是 user,避免 assistant 打头的畸形序列);**必须保留最近一条 assistant**(保证追问轮后端 `is_first` 判定恒 false)。首条深析被截出窗无妨(事实块每轮后端重注入)。
- **AnalysisView 调用点同步改(堵 plan-critic 重要8)**:`AnalysisView.swift:264`(`.onSubmit { model.sendComposer() }`)与 `:266`(发送按钮 `action`)两处 `sendComposer()` 调用改 `{ Task { await model.sendComposer() } }`。
- **失败路径预期行为(plan-critic 重要8 记录)**:C3 失败追加降级 assistant 文案后,该 thread 此后 `is_first` 恒 false(assistant 条数≥1),真 verdict 落不了库除非退出重进——**这是可接受的预期行为**(降级本就不该落库,退出重进会重新首判),不视为缺陷。

C4. **「全仓买入并录入」按钮在对话区承接 + 死代码诚实处理**:
- **买入按钮渲染条件(不留三选一,配 C2 专用字段)**:在 assistant 气泡下方,当 **`msg.id == model.firstAssistantMsgId && model.firstVerdict == .enter && !isHolding(selectedCode)`**(candidate 模式)时,渲染「全仓买入并录入 / 看下一只」按钮组(复用现 `buyFromAnalysis()`,iOS cover↔sheet 同帧交接坑照旧 `presentModalAfterCoverDismiss`)。追问轮 verdict 变化不影响该判定(firstVerdict 只在 isFirst 时写)。
- **资金时序标注**:("资金面 = 截至 {fundAsof} EOD · 东财主力口径(非盘中实时)")移到**对话区顶部 context 条下方一行**,持续可见(`fundAsof` 非空时显)。不再依赖 DeepAnalysisCard。
- **`.analysis` 渲染分支处理(堵 plan-critic 重要5:承认是死代码,不用不成立理由保留)**:v1.2.1 后候选深析不再产 `.analysis` 消息、coach 触损走 `.coach`(从不产 `.analysis`),故 `AnalysisView.swift` 的 `.analysis` case(:97)+ `analysisBlock`(:142-172)含其内旧买入按钮(:151-168)是**彻底死代码**,与 C4 新按钮构成两条买入路径。**处理:删除 `messageView` 的 `.analysis` case 分派 + `analysisBlock` 整个方法**(`DeepAnalysisCard` 结构体本体**保留**——`SnapshotRenderTests.swift` 快照测试引用它,删本体会破测试)。`ChatMessage.analysis` 字段(Models.swift:166)保留(契约字段,coach `.coach` 卡的 `analysis` 参数仍用)。若 builder 认为删分支风险高,退路是保留分支但**在代码注释标注"dead since v1.2.1,回滚锚"**——二选一,不得用"coach 红橙卡仍用"这类不成立理由搪塞(coach 红橙卡走 `.coach` 不走 `.analysis`)。
- **coach 触损路径决策(定死)**:`openCoach` 触损分支**保持走 `/coach`**(红橙卡 + review_ref 历史引用 + 标记次日清仓按钮),**不改对话式**——反情绪教练红橙卡是纪律干预 UI,结构化更有威慑力且依赖 review_ref 展示。**本版本:openCoach 触损走 /coach 红橙卡不动;中间地带(非触损)分支也暂留 /coach 二元气泡;只有候选深析(openAnalysis)+ composer 追问走 /chat**。coach 卡入口不变,红橙卡与回测 verdict 都不受影响。

C5. **`xcodegen generate`(APIClient 无新文件则免;若拆新文件则必跑)后双端 App target build**。

**验收标准 C**:候选点「深析」→ 进全屏 → 首条 user 气泡 + assistant **自由中文分析气泡**(非三轴卡)+ 顶部资金时序标注;首条 verdict==可进 时对应气泡下显「全仓买入并录入」按钮、追问翻"不进"按钮**不消失**(firstVerdict 只在 isFirst 写),点击预填开仓 sheet;composer 追问 → 真调 `/chat` 多轮 → assistant 返上下文相关回答(不再固定文案);**持仓中间地带 composer 追问以 coach 模式 + 带 positionId 发出**(mode 不复用 chatMode);`chatTurns(from:)` 映射把 `.coach→assistant`/`.analysis→跳过`、截断从 user 边界起且保留最近一条 assistant(单测断言);`AnalysisView:264/266` 两处 sendComposer 调用改 async;缺 token/降级返占位 reply 不弹错;双端 `BUILD SUCCEEDED`;客户端单测无回归(`testSendComposer*` 改 async + 新增 chatTurns 序列化/截断单测)。

---

**Phase D —— 全量部署上线(全栈 · 运维,两步走)**

> 拆两步(堵 plan-critic 重要7:store 拆包从没上生产 + v1.2.1 一次全量出问题无法归因)。**部署前记录当前 `git rev-parse HEAD` 作回滚锚**;每步前 ECS `cp linon.db linon.db.bak-YYYYMMDD`(无新 migration,照高危区姿势)。

D1. **第一步:先部署当前 main(store 拆包 + moneyflow_dc 收口态,清"已完工未部署"欠账)**:全量 `sync.sh` rsync(不再单文件热补丁)→ 重启 `linon.service` → 冒烟 `/candidates`·`/analyze`·`/coach` 三端点公网 200 照常。**两项 rsync 后检查**(store.py→包重构首上生产的坑):① ECS 上 `app/db/store.py`(旧单文件)**应不存在**——openrsync `--delete` 若未生效/守卫被绕会留 stale 单文件与包并存;并清 `app/db/__pycache__/store.*.pyc`(旧字节码残留会遮蔽包)。② 确认 `app/db/store/__init__.py` 等包文件在位。验通(服务 active + 三端点照常)才进 D2。

D2. **第二步:部署 v1.2.1 新增**(`prompt.py`/`deepseek.py`/`analyze.py`/`app.py`/`schemas.py`)→ 重启 → 端到端验通:`POST /chat` candidate 模式公网 HTTPS 200 返真实 concise reply + verdict + fund_asof + degraded=false;coach 模式非持仓 404、持仓存在返对话;缺 key 时降级 reply(ECS `.env` 已有 key,应返真);`analysis_verdicts` 首条候选对话落库、追问/降级不落;客户端 Release 换包核对候选行只深析按钮进 + 对话渲染。**内存峰值观察**(那台 1.6G+2G swap 箱子,对话端点 messages 更长但不批量拉全市场,压力应低于 refresh 的 926MB 峰;若逼近上限记 Backlog)。

**验收标准 D**:D1 后 store 拆包重构上 ECS **无 stale 单文件残留**、309 行为无回归(服务 active、`/candidates`/`/analyze`/`/coach` 照常);D2 后公网 `/chat` 端到端返真实对话 + verdict + degraded 标记正确、落库门槛生效;客户端 Release 包候选行交互 + 对话渲染真机/真窗口核对通过;记录了回滚 git SHA;`~/Lino/hz_info.md` 同步更新(两步部署动作事实)。

### 4.3 施工纪律与坑提示(施工必读)

- **绿涨红跌**、规则常量单一源(`store/constants.py` 的 -5.0/+15/D4/容差带,禁另写)、`count==4⟺should_force_close` 契约**全部不动**。对话 prompt 引用铁律只是文案,不新立常量。
- **守味隔离铁律**:对话端点 context **只注入 history_digest(中性统计),绝不注入 review_ref(带情绪)**。`_coach_brain` 返回 `(digest, ref)`,对话端点丢弃 ref。违反即串味。
- **DeepSeek 降级链全程不崩**(缺 key/超时/卡死→降级 reply + verdict=观望 + degraded=true);对话**不复用** `/analyze` 的 12s×3(决定7:prose 生成慢会系统性降级),用对话专属 `_CHAT_READ_TIMEOUT=25`/`_CHAT_CONNECT_TIMEOUT=6`/`_CHAT_MAX_ATTEMPTS=2` + `max_tokens=700` + reply 限长 ~250 字;客户端 `/chat` 超时 60s。全新连接重试骨架沿 CLAUDE.md 坑6。
- **资金源=东财 `moneyflow_dc`**,`fund_asof` 取实际数据最新交易日(本会话刚修);对话 reply 里资金口径由 system prompt 约束诚实交代,日期由客户端标签权威显示(prompt 不写死日期)。
- **改 .swift**:B 只改现有文件、C 若拆新文件必 `xcodegen generate`;改 View 必跑 **iOS + macOS 双端 App target build**。Dock 守卫下可视核对走 `ImageRenderer` 离屏快照(注意不渲 ScrollView 内容,组件单独裹 VStack 渲)。
- **后端可注入替身免联网**:`_chat_fn`/`chat_fn`/`transport` 沿 `_analyze_fn`/`send_push(transport=)` 模式。
- **回测链路不能断,且降级绝不污染**:对话首条候选 verdict 必须经 `_maybe_persist_verdict` 落 `analysis_verdicts`(取 `candidate_entry_date_of` entry_date,查不到不落),否则 `GET /candidates/outcomes` verdict 维度断供;但**落库前必过 `not degraded` 门槛**(决定2:对话 thread 重开频繁 + upsert 覆盖式,降级观望会覆盖真可进污染回测)。
- **买入按钮判定单一事实源**:`firstVerdict`/`firstAssistantMsgId` 只在 `isFirst==true` 写、`backFromAnalysis` 清;不用"每轮覆盖的 lastVerdict",防追问翻脸让按钮回溯消失。
- **mode 是业务状态非 UI 状态**:composer 追问 mode 按 `holding(byCode:) != nil` 判,**不复用 `chatMode`**(那是 UI 语义,中间地带刻意设 .analyze);role 序列化收敛到 user/assistant 两值,否则后端 422。

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
