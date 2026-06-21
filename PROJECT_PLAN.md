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

- 设计已闭合(v2);**PROJECT_PLAN.md 已立**;**阶段 0(基建)已完工(0.1–0.7)**,已 git init 并干净提交;**阶段 1 待开工**。
- **上线即空仓**:无存量持仓迁移,无 legacy / 既往不咎机制,`positions` 从 0 行起。
- **止损线机械派生**:`stop_line = buy_price × 0.95`,**纯派生、不落库**(-10% 极强趋势例外已砍,止损恒为 ×0.95;与持仓天数同样按读取时算,单一事实源),系统自动算,**拒绝用户手填**。
- 门禁数字:已发布 0 个阶段;在施工 0 个阶段;阶段 0 验收 = **"数据能稳定拉"** ✅(冒烟脚本一次性可见:实时价拉到 / 日历正确 / 库已建 / Tushare 按 token 降级)。
- **阶段0 验收结果**:
  - **已真跑过**(本地):config 无 .env 不崩 / 实时价真源拉到非空 Quote(新浪实测 + 降级编排单测)/ Tushare 无 token 四接口优雅降级 / SQLite 四表 + 开仓→清仓闭合 / 日历 D1–D4 与跨周末·跨国庆 / `setup.sh` 幂等建 venv+库 / `sync.sh` 未配 host 优雅退出 / `smoke.py` 全段可见。**pytest 40 条全绿**(realtime14 / calendar10 / db10 / tushare6)。
  - **待联调**(token/SSH/真机就绪后):Tushare 有 token 真拉 daily/moneyflow;实时价**联网+盘中**复测(本期用收盘快照+样例报文);`sync.sh` 真 rsync 到 ECS + 远端 setup;`linon.service` 阶段1 接 FastAPI 后才 enable。
- **落地目录**:`backend/`(`app/{config,data,db,calendar,smoke}` + `scripts/{setup.sh,sync.sh,smoke.py}` + `deploy/linon.service` + `tests/`(4 文件)+ `requirements.txt` + `.env.example`)、`client/`(`DesignTokens.swift`+`Models.swift` 契约拷贝)、`archive/`、根 `.gitignore` + `CLAUDE.md`。
- **路线图**(后端/前端双轨;**每屏照设计终稿做、无 throwaway 最小壳;阶段4 缩水**):

| 阶段 | 后端 | 前端(照终稿,双端) |
|---|---|---|
| **0 基建**(本期) | 数据层四件套(实时价 / Tushare / SQLite / 日历)+ 部署脚手架 + 冒烟脚本 | 仅纳入 `DesignTokens.swift`/`Models.swift` 作客户端契约;客户端工程骨架可选 |
| 1 脊椎+今日台 | 监控 / 3 硬线 / 心跳 / APNs / 开·清仓录入 API | 客户端地基(multiplatform:tokens+models+AppModel+导航壳+两签名组件)+ TodayView 终稿 + 开/清仓 sheet + 锁屏推送行为(iOS) |
| 2 候选+决策 | 粗筛 / 排序截断 / on-demand 深析 / 中间地带 | CandidatesView + AnalysisView(三类消息 + 结构化深析卡 + 教练 UI 壳)+ 满仓闭门联动 |
| 3 复盘闭环 | Reviewer / 打分 / 闭环注入 / 教练"大脑" | ReviewView + MemoryView + 教练 UI 接复盘历史 |
| 4 收尾 | — | K 线/分时图、舆情展示、双端真机 E2E 打磨 |
| V2(推后) | 历史行情重放 / 纪律陪练沙盒(陪练非裁判) | 临场纪律陪练 |

## 4. 当前版本 Plan —— 阶段 0:基建(数据能稳定拉)

边界:**只建"日历原语"不让调度器跑起来;只建"持仓交易日数计算函数"不接第 4 日触发推送。** FastAPI 接口本体、轮询守护进程、调度器、APNs、报警判定、开/清仓录入、选股、复盘 → 全部 OUT,推后到阶段 1+。

### Phase 0.1 项目骨架与配置(后端 · monorepo)

- **monorepo 重组**:后端收进 `backend/`(`app/`(config / data / db / calendar / smoke 子模块)、`scripts/`、`data/`(SQLite 落盘)、`requirements.txt`、`.env.example` 均在 `backend/` 下);客户端占位 `client/`(SwiftUI 多平台 Xcode 工程,本期可只放 `DesignTokens.swift`+`Models.swift` 占位、工程骨架可选);根 `.gitignore`。
- 配置模块:**pydantic-settings** `Settings` 读 `.env`,字段含 `TUSHARE_TOKEN`(占位可空)、`DEEPSEEK_API_KEY`(留空)、`DB_PATH`;`.env` 与 `data/*.db` 入 `.gitignore`。
- 依赖钉死版本写入 `requirements.txt`;`git init`(builder 执行)。
- **验收**:在 `backend/` 下 `python -c "from app.config import settings"`,无 `.env`(仅 `.env.example`)时不崩,缺失 token 字段为 None/空串。

### Phase 0.2 实时价(免费多源,后端)

- 接口契约:
  ```
  get_realtime_quote(code: str) -> Quote | None    # 单票;全失败返回 None,不抛崩
  get_realtime_quotes(codes: list[str]) -> dict[str, Quote]
  Quote = {
    code, name, price(现价,float),
    pre_close, open, high, low,
    limit_up, limit_down(涨跌停价;主板±10%、ST±5%;以 pre_close 算或源带均可),
    volume(手), amount(成交额,元),
    bid1..bid5/ask1..ask5(可选), ts(数据时间,str),
    source("sina"|"tencent")
  }
  ```
- **新浪主源 → 腾讯降级**,GBK 解码,归一为统一 `Quote` 结构;源全挂时逐票返回 None / 跳过,整体不崩。
- **涨跌停价**:阶段0 只需让 `Quote` 携带或可推算 `limit_up`/`limit_down`(300/688 已黑名单不做,不涉 ±20%);**用途是阶段1 识别一字板"必走但物理不可执行"**。
- **验收**:对一只真实在交易票拉到非空 `Quote`;主源人为不可用时自动走腾讯。

### Phase 0.3 Tushare 封装(后端)

- 四接口薄封装,**统一带状态返回,token 缺失优雅降级不抛崩**:
  ```
  TushareResult = { ok: bool, data: DataFrame | None, reason: str }   # ok=False 时 reason 说明"token 缺失/限频/网络"
  ts_moneyflow(code, start, end) -> TushareResult      # 主力/小单净额
  ts_daily_basic(code, trade_date) -> TushareResult    # 换手率/涨跌幅/PE-PB
  ts_daily(code, start, end) -> TushareResult          # 日线·形态
  ts_trade_cal(start, end) -> TushareResult            # 交易日历
  ```
- token 缺失/初始化失败时,所有调用返回 `ok=False` 且 `data=None`,**不抛异常**。
- **验收**:无 token 时四接口均返回 `ok=False, reason` 可读;有 token 时 `ts_daily` / `ts_moneyflow` 各拉到一条真实数据。

### Phase 0.4 SQLite 四表(后端)

- 建表 + 初始化 + 基础 CRUD。DDL 摘要(对齐 v2 §11;**持仓为"全有全无",无部分仓位字段;持仓天数不落库**):
  ```
  positions(id, code, name, buy_price, qty, entry_reason,
            entry_snapshot(JSON:形态+资金快照), buy_date(交易日历基准),
            status('holding'), created_at)            -- 最多 3 行
            -- 止损线 = buy_price×0.95,读取时派生、不落库(单一事实源,同持仓天数)
            -- 开仓录入(用户): 代码/买入价/数量/进场理由
            -- 开仓自动补(系统): 形态资金快照(entry_snapshot)/买入日(止损线读取时派生,不存列)
  trades(id, code, open_price, close_price, open_time, close_time,
         kept_stop(bool), kept_take(bool), kept_time(bool),
         pnl, broke_rule(bool), created_at)            -- 每笔一买一卖闭合
  reviews(id, week, score, red_flags(JSON), discipline_rate,
          lessons, next_week_note, created_at)
  memory(id, kind, content, created_at)                -- 闭环结论/长期记忆
  ```
- CRUD 最小集:`open_position`(写 `positions`)、`close_position`(落 `trades` + 归档对应 `positions`)、`list_holdings`、`insert_review`、`insert_memory`。
- **验收**:初始化建四表;开一仓→清一仓,`positions` 归档且 `trades` 落一条闭合记录。

### Phase 0.5 交易日历原语(后端 · 含锁定约束 1+2)

- `trade_cal` 驱动 + **静态 2025–2026 兜底**;**缺 token 用静态表,不崩**;有 token 时拉 `trade_cal` 并与静态表校验对齐(不一致告警)。
- 接口契约:
  ```
  is_trading_day(date) -> bool
  next_trading_day(date) -> date
  prev_trading_day(date) -> date
  trading_window(date) -> [(am_open,am_close),(pm_open,pm_close)] | None
      # 两段(A股有午休): 上午 09:30–11:30 + 下午 13:00–15:00;非交易日 None
      # 注: 集合竞价(9:15–9:25、14:57–15:00)价格行为不同,阶段0 不实现竞价逻辑,仅留注释
  count_holding_trade_days(buy_date, today) -> int       # 闭区间[buy_date,today]内交易日个数;买入日=1
  should_force_close(buy_date, today) -> bool            # == True 当且仅当 count==4(D4 强平)
  ```
- **锁定语义(钉死,builder 不得改)**:`count_holding_trade_days` 数闭区间 `[buy_date, today]` 的交易日个数,**买入日计为 1**;计数 == 4(买入日之后第 3 个交易日)即 `should_force_close` 为真。可卖日 = D2/D3,D4 强平。
- **验收**:用静态表跑一组用例:连续交易日的 D1/D2/D3/D4 计数为 1/2/3/4,`should_force_close` 仅在 D4 为真;跨周末/节假日时按交易日(非自然日)计数正确。
- **已知限制(阶段1 处理)**:① **个股停牌盲区**——`trade_cal` 是市场级,个股停牌时实时价拿不到、硬线无法算、D4 撞停牌卖不掉,日历原语照不到;② **D4 时间止损无独立兜底**——价格线(-5%/+15%)有券商到价提醒人工兜底,**时间触发的 D4 没有**,D4 当天用户无暇则无第二重保险,阶段1 设计应对(如多次升级提醒)。

### Phase 0.6 部署脚手架(运维 · 含锁定约束 3+4)

- `scripts/setup.sh`:**幂等**——建 venv、装 `requirements.txt`、建库(调 0.4 初始化)。可重复执行不报错。
- `scripts/sync.sh`:rsync over SSH,**只同步 `backend/`(显式排除 `client/` 和 `data/`)**,参数化 `host/user/path`,**SSH 连接方式留占位**(读环境变量或 `.env`,未配置时打印提示并退出,不误同步)。
- `deploy/linon.service`:systemd unit **草稿**,留给阶段 1,**本期不启用**(不写 enable/start)。
- **验收**:`setup.sh` 在干净目录跑通建出可用 venv 与库;再跑一次不破坏现状;`sync.sh` 未配 host 时优雅提示退出。

### Phase 0.7 冒烟脚本(可见验收)

- `scripts/smoke.py`:① 拉一只票实时价并打印 `Quote`;② 有 token 时拉一条 `daily` + 一条 `moneyflow` 打印(无 token 打印"已降级:token 缺失");③ 打印 today 附近交易日历(prev/today/next + 是否交易日);④ 建库(调 0.4)。
- **验收(阶段 0 总验收)**:运行 `smoke.py` 一次性可见——实时价拉到、日历原语正确、库已建、Tushare 按 token 有无给出对应结果。即 **"数据能稳定拉"**。

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

- **Tushare token 待购/录入**:2000 积分会员(约 200 元/年),购后将 token 写入 ECS 上的 `.env`。
- **ECS SSH 连接方式待给**:host / user / 鉴权方式 / 部署 path,提供后填入 `sync.sh` 占位。
- **真机部署与验证**(阶段 0 后):rsync 同步到 ECS、`setup.sh` 真机跑通、冒烟脚本在 ECS 上拉到真实数据。

### 用户网页操作清单(必须在网页手动办理)

- **APNs 鉴权密钥(.p8)**:Apple 开发者账号生成,留待阶段 1。生成入口:Apple Developer → Certificates, Identifiers & Profiles → Keys → 创建 APNs Key,下载 `.p8`(只能下一次)。URL:`https://developer.apple.com/account/resources/authkeys/list`
- **Tushare 充值/积分**:`https://tushare.pro/`(2000 积分会员)。

### 用户流程坑清单(走查沉淀,分阶段回填,本期不展开)

- (阶段1)**录入是关键单点故障**:开/清仓录入须回传成功/失败确认到手机;漏录→幽灵持仓(监控空盯+假警报+`trades` 不闭合+D4 空跑);部分成交/成交价手敲易错,需校核。**(录入 sheet UI 已设计;后端 API + 确认回传待阶段1)**
- (阶段1)**推送需 T+1 与涨跌停感知**:买入日命中硬线只说"记录,明日开盘处理"不喊"必走";一字跌停说"封死,明日处理"。**(锁屏推送文案 UI 已设计;后端判定待阶段1)**
- (阶段1)**硬线推送需升级/重复至确认**(录动作或主动 dismiss 才停),单次 APNs 易被漏。**(升级角标 UI 已设计;后端升级逻辑待阶段1)**
- (阶段2)**满仓闭门联动**:持仓达 3 → 候选列表闭门(🔒);清掉一只 → 候选按 `5 × 空仓位` 重开。**(UI 已设计;后端粗筛截断按空仓位数待阶段2)**
- (阶段1)**阿里云 ECS→APNs 真实可达性/延迟一上来就真机实测**(推送是脊椎,进程活着但推不出去更隐蔽)。
- (阶段1)**实时多源切换做归一一致性校验**(Sina/Tencent 的 pre_close/除权口径差→假报警)。
- (阶段1)**录入 API 加 token 鉴权**(单用户,顺手)。
- (阶段1/2)**时点化主动触点**:盘前(~09:00)推"今日候选 + 今晨待办(强制卖出/+15%/中间地带)";盘后推"EOD 摘要 + 当日资金二次校验(小单爆量/主力净流出预警)"——不全靠拉。
- (阶段1)**系统持仓 vs 券商现实对账**:定期"你现持有这 N 只对吗""持有 N 天无任何记录动作"提醒,防无声漂移。
- (阶段2)**候选列表是 EOD/拉取式**,结构上只服务 D 型(次日续强)进场、不喂 A 型盘中突破——认账写清(正好对治盘中追高病根);A/C/D 进场时机可行性据此校准。
- (阶段2)**on-demand 深判延迟 vs 时间敏感进场**的张力;深判界面显著标注"资金面=截至昨日 EOD,今日盘中资金未知"。
- (阶段2/3)**中间地带不能纯拉取**:持仓恶化(逼近线/量能萎缩/主力撤)转主动推,否则反情绪教练永不触发;中间地带核心依据(主力资金)EOD 滞后,建议里诚实标注。
- (阶段3)**复盘"垃圾进垃圾出"**:依赖录入保真,需配合对账;复盘须**同时读未平的 `positions`**(扛过周末的套牢票只在 positions 不在 trades),不能只读闭合流水。**(ReviewView 已按"同时读未平 positions"设计;后端 Reviewer 待阶段3)**

### 待后续阶段细化(本期不动)

- **`design_handoff_linon/` 为客户端设计权威参考**;`DesignTokens.swift`+`Models.swift` 进 `client/` 工程(阶段0 纳入作契约,阶段1+ 照终稿重建)。
- **-10% 极强趋势止损例外**(后期细化):当前砍除,止损统一 `buy×0.95`;届时若恢复,`stop_line` 改为落库列。
- 实时行情多源兜底细节(限频退避、源健康探测、第三源)——用户处理,实现细节阶段 1 打磨。
- DeepSeek 前置词/skills、选股过滤排序、复盘闭环、反情绪教练 —— 阶段 2/3。

## 6. 变更日志

- **[2026-06-20] 立项**:v2 设计蒸馏为权威 PROJECT_PLAN.md,锁定 4 项施工决策(持仓计数 D1 起算 / 日历静态兜底 / rsync 部署 / venv+requirements),进入阶段 0 施工准备。
- **[2026-06-21] 用户视角走查修订**:锁定空仓起步、止损 -5% 自动派生 + ±1% 执行容差;修正阶段0 契约(`trading_window` 两段 / Quote 补涨跌停价 / `positions` 止损线改派生、开仓录入去手填);补阶段0 已知限制(停牌盲区、D4 无兜底);沉淀"用户流程坑清单"入 Backlog 待分阶段回填。
- **[2026-06-21] 设计稿并入**:客户端 hi-fi 完成稿到位(`design_handoff_linon/`:5 屏+锁屏推送、两签名组件、DesignTokens/Models),路线图重切为后端/前端双轨(每屏照终稿、无 throwaway 最小壳、阶段4 缩水)。锁 **iOS+macOS 多平台**(共享核心+平台分叉壳)。**-10% 极强趋势止损例外砍除**——止损统一 `buy×0.95` 纯派生不落库(反转上一版"必须落库",对齐 Models.swift 单一事实源);0.4 schema 移除 `stop_line` 列。收编客户端↔后端契约(DeepAnalysis schema / entry_snapshot 两串 / 规则常量单一事实源(触发线口径定死 -5.0)/ 签名组件公式 / 绿涨红跌 / 教练 UI-大脑 拆分),新增 §4b。monorepo 重组 `backend/`+`client/`,`sync.sh` 只同步 `backend/`。-10% 例外列入后期 backlog。
- **[2026-06-21] 阶段0 完工(0.1–0.7)**:数据层四件套 + 部署脚手架 + 冒烟脚本全部落地并本地验收;git init + 干净首提交。目录 = `backend/app/{config,data,db,calendar,smoke}` + `scripts/{setup,sync}.sh` + `smoke.py` + `deploy/linon.service`(草稿态)+ `tests/`(pytest 40 条全绿)+ `client/` 两 .swift 契约。**关键决策/偏离**:① 后端 schema 严格照 plan §4 DDL(`positions` 无 stop_line 列、止损线读取时 ×0.95 派生);**偏离记**:`trades` 表照 plan DDL 建,**未加** Models.swift 上展示用的 `name`/`note` 列(plan DDL 为后端权威,客户端那两列留阶段3 复盘细化时评估,已记 CLAUDE.md)。② `kept_stop/kept_take/kept_time/broke_rule` 用机械规则(止损容差带 [-6%,-4%]、止盈 +15%、D4),**注明阶段3 细化**。③ config 加标准库 fallback(仅 pydantic-settings 未装时启用,不掩盖正式安装)。④ 静态日历表查证官方 2025/2026 休市+调休补班日硬编码,`verify_against_trade_cal` 留作 token 到位后比对。**待联调**:Tushare 真 token 拉数 / 实时价联网+盘中复测 / ECS rsync+远端 setup / systemd enable(均列入 §5 用户侧收尾)。项目专属坑沉淀入根 `CLAUDE.md`(新浪 Referer、两源 bid/ask 顺序相反、calendar 包名撞标准库、pydantic v2 不可 setattr 等)。
