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

- 设计已闭合(v2);**阶段 0(基建)已完工**(详见 `archive/stage0_基建_plan.md`);**阶段 1(脊椎+今日台)在施工**——**track A 后端脊椎(A.1–A.5)已完工**(本地真跑通,见 §6 [2026-06-21] 条),track B(客户端)/ track C(ECS 部署)待开工。
- **上线即空仓**:无存量持仓迁移,无 legacy / 既往不咎机制,`positions` 从 0 行起。
- **止损线机械派生**:`stop_line = buy_price × 0.95`,**纯派生、不落库**(-10% 极强趋势例外已砍,止损恒为 ×0.95;与持仓天数同样按读取时算,单一事实源),系统自动算,**拒绝用户手填**。
- **门禁数字**:已发布 **0** 个阶段;在施工 **1** 个阶段(阶段1,track A 完工 / B、C 未开工)。阶段0 验收 = "数据能稳定拉" ✅。**pytest 96 条全绿**(阶段0 的 40 + track A 新增 56)。
- **track A 已真跑过**(本地):FastAPI 6 端点 `uvicorn` 起、curl 走通 health/401/open→list→close 闭环 + 漏录防护 409/404 + device/ack(`scripts/smoke_api.sh`);APNs JWT 用临时 EC key 单测验签通过(ES256/header/claims)。**待联调(留 track B/C)**:真 APNs 实推(无设备 token、客户端未建)、ECS 真部署、真机锁屏。
- **阶段1 验收主线**:**① 铁律能逼我走**(3 硬线触发 → APNs 推送 → 升级重复至确认)+ **② 状态闭环**(开/清仓录入有成功/失败回传、漏录防护、positions↔trades 闭合)+ **③ 今日台真机可用**(TodayView 双端 + 开/清仓 sheet + 锁屏推送 iOS,真机装得上、推得到、操作得了)。
- **基建落地目录**:`backend/`(`app/{config,data,db,calendar,smoke}` + `scripts/{setup.sh,sync.sh,smoke.py}` + `deploy/linon.service` + `tests/` + `requirements.txt` + `.env.example`)、`client/`(`DesignTokens.swift`+`Models.swift` 契约拷贝)、`archive/`、根 `.gitignore` + `CLAUDE.md`。
- **APNs 凭证已齐**:Key ID `Q963AP3VY8` / Team ID `HX73DFL88G` / Bundle ID `top.linotsai.linon`(App ID 已注册并开 Push);`.p8` 在用户本地,阶段1 搬 ECS secret(mode 600,不入 git)。dev 直装走 APNs **sandbox** 网关(`api.sandbox.push.apple.com`)。
- **ECS 现实**:`deploy@118.178.122.194:/opt/linon`(已配 `backend/.env`);内存紧(1.6G+2G swap),已占端口 8000/8787/5432/80/443 → 阶段1 FastAPI 取 **8001**。
- **路线图**(后端/前端双轨;**每屏照设计终稿做、无 throwaway 最小壳;阶段4 缩水**):

| 阶段 | 后端 | 前端(照终稿,双端) |
|---|---|---|
| **0 基建**(本期) | 数据层四件套(实时价 / Tushare / SQLite / 日历)+ 部署脚手架 + 冒烟脚本 | 仅纳入 `DesignTokens.swift`/`Models.swift` 作客户端契约;客户端工程骨架可选 |
| 1 脊椎+今日台 | 监控 / 3 硬线 / 心跳 / APNs / 开·清仓录入 API | 客户端地基(multiplatform:tokens+models+AppModel+导航壳+两签名组件)+ TodayView 终稿 + 开/清仓 sheet + 锁屏推送行为(iOS) |
| 2 候选+决策 | 粗筛 / 排序截断 / on-demand 深析 / 中间地带 | CandidatesView + AnalysisView(三类消息 + 结构化深析卡 + 教练 UI 壳)+ 满仓闭门联动 |
| 3 复盘闭环 | Reviewer / 打分 / 闭环注入 / 教练"大脑" | ReviewView + MemoryView + 教练 UI 接复盘历史 |
| 4 收尾 | — | K 线/分时图、舆情展示、双端真机 E2E 打磨 |
| V2(推后) | 历史行情重放 / 纪律陪练沙盒(陪练非裁判) | 临场纪律陪练 |

## 4. 当前版本 Plan —— 阶段 1:脊椎 + 今日台

目标:**铁律能逼我走 + 状态闭环 + 今日台真机可用**。三组并行——A 后端脊椎(监控/3 硬线/APNs/录入)、B 客户端地基(multiplatform + TodayView + sheet + 锁屏推送)、C 部署 infra(真上 ECS)。
依赖:B 的录入/拉持仓依赖 A.2/A.3 端点;C.2 nginx 依赖用户加 DNS;A.4 APNs 真测依赖 C 上线 + B 注册设备 token。**OUT(推后)**:候选/深析/复盘/记忆视图(B 只留导航占位);教练"大脑"(阶段3,本期横幅占位文案);Tushare 资金校验(无 token 降级跳过)。

**全期共用规则常量**(§4b 单一事实源,后端监控与客户端展示引用同一份):止损触发 **-5.0**(展示阈 -4.9)/ `kept_stop` 容差带 **[-6%,-4%]** / 止盈 **+15%** / **D4 强平**(`count==4`)。

### A. 后端脊椎(FastAPI on :8001)

#### Phase A.1 FastAPI 骨架 + 鉴权 + 设备注册(后端)

- FastAPI 应用,绑 `127.0.0.1:8001`(nginx 反代)。`/api/v1/health` → `{status, version}` 不需鉴权。
- **鉴权**:单用户共享密钥,沿 lw 单密钥惯例。`require_token` 依赖比对 `Authorization: Bearer <API_TOKEN>` 与 `.env` 的 `API_TOKEN`(`hmac.compare_digest`,启动 fail-fast 校验 `len≥16`)。除 health 外所有端点必过。Shortcuts 录入端点同一密钥。
- 设备 token 注册:
  ```
  POST /api/v1/devices    body{token: str, platform: "ios"}    -> {ok: true}
      # 客户端上报 APNs device token;落库(新表 device_tokens(id, token UNIQUE, platform, created_at))
      # 重复 token upsert 不报错;监控推送时遍历此表
  ```
- **验收**:health 免鉴权可访问;带错/缺 token 调任意业务端点返 401;`POST /devices` upsert 落库,重复上报不增行。

#### Phase A.2 开/清仓录入 API + 漏录防护(后端 · 接 Shortcuts)

- 接口契约(均需鉴权,**回传明确成功/失败**给客户端 & Shortcuts):
  ```
  POST /api/v1/positions/open
    body{ code, buy_price: float, qty: int, entry_reason: str }
    -> 200 { ok, position_id, stop_line, take_line, buy_date }   # stop_line 服务端派生 buy_price×0.95
    -> 409 { ok:false, reason:"slots_full" }     # 已持 3 票
    -> 409 { ok:false, reason:"duplicate_holding" }  # 同 code 已在持仓(漏录/重复防护)
    -> 422 { ok:false, reason:"<字段校验>" }
    # 系统自动补 entry_snapshot(开仓瞬间 form/fund 快照串)、buy_date(= 当前交易日)
  POST /api/v1/positions/{id}/close
    body{ sell_price: float, sell_time: ISO8601 }
    -> 200 { ok, trade_id, pnl, kept_stop, kept_take, kept_time, broke_rule }
    -> 404 { ok:false, reason:"not_holding" }     # 已清/不存在 → 防重复清仓
    # 落 trades(一买一卖闭合)+ 归档该 position;kept_*/broke_rule 用机械规则判(容差带/+15%/D4)
  GET  /api/v1/positions    -> { holdings: [Position...], free_slots: int }
    # Position 形状对齐 Models.swift:含 code/name/buy_price/qty/entry_reason/buy_date;不含 stop_line(客户端派生)
  ```
- **漏录防护(幽灵持仓)意识**:open 拒重复 code、拒满仓;close 拒非持仓;每个端点回传结构化 reason,Shortcuts/客户端据此弹成功/失败提示。
- **验收**:开一仓返 position_id + 正确 stop_line(=buy×0.95);满 3 仓再开返 409 slots_full;重复 code 开返 409 duplicate_holding;清仓返 trade_id 且 positions 归档;重复清同一 id 返 404。

#### Phase A.3 监控守护进程 + 3 硬线判定(后端 · 同机)

- 交易时段(用 0.5 `trading_window` 判 + 每分钟轮询)对所有在持仓票拉实时价(0.2 `get_realtime_quotes`);非交易时段休眠。
- **3 硬线判定**(常量引用 §4b,与客户端同源):
  - **止损** `pnl_pct ≤ -5.0`(触发口径定死 -5.0)。
  - **止盈** `pnl_pct ≥ +15.0`。
  - **D4 时间** `should_force_close(buy_date, today) == True`(`count==4`)。
- **T+1 感知**:买入日(D1)命中价格硬线 → 文案"**记录,明日开盘处理**",不喊"必走"(T+1 当日不可卖)。
- **涨跌停感知**(用 0.2 `limit_up/limit_down`):一字跌停封死 → "**封死,明日处理**";触线但可成交 → 正常"必走"。
- **多源一致性校验**:同票新浪 vs 腾讯 `pre_close`/现价口径差超阈值 → 标记"行情存疑"、**不据此触发硬线**(防除权口径差导致假报警)。
- 判定结果产出"待推送事件"交 A.4;不直接写库。
- **验收**:单测注入构造行情——D1 触损出"明日处理"文案、D2+ 触损出"必走"、一字跌停出"封死明日处理"、D4 出强平;两源 pre_close 差异样本被标存疑不触发;非交易时段轮询不跑。

#### Phase A.4 APNs 直连 + 硬线升级重复(后端)

- **APNs token-based JWT**:`.p8` + `KeyID=Q963AP3VY8` + `TeamID=HX73DFL88G` + `BundleID=top.linotsai.linon`;dev 网关 **`api.sandbox.push.apple.com`**(`.env` 开关 `APNS_USE_SANDBOX=true`)。JWT 复用(≤1h 刷新)。
  ```
  send_push(device_token, title, body, *, category, thread_id, badge_escalation: int)
  # category 决定锁屏动作按钮(见 B);thread_id 按持仓 code 聚合;badge_escalation = 第几次升级
  ```
- **硬线推送升级/重复至确认**:同一硬线事件未确认则按固定间隔(`.env` `ESCALATE_INTERVAL_MIN`,默认 15)重复推,角标递增"第 N 次升级";**录动作(标记次日清仓 / 清仓)或客户端 dismiss 上报才停**。需端点:
  ```
  POST /api/v1/alerts/{code}/ack   body{ action: "marked_close"|"dismissed" }  -> {ok}
  # 客户端在用户操作后回报,后端停止该 code 的升级
  ```
- D4 时间止损无券商兜底 → 沿用同一升级机制(多次重复提醒)。
- **验收**:真机(见 C.3)收到推送;未 ack 时 15 分钟后收到角标递增的升级推送;ack 后停推;sandbox 网关连通(JWT 不被拒)。

#### Phase A.5 心跳 → EOD 摘要(后端)

- 收盘后(用 0.5 判收盘时点)对每持仓推一条 **EOD 摘要**(非升级类、`category` 普通):每持仓**盈亏%** + **持仓第几交易日(D 几)** + **明日 D4 预警**(明日 `should_force_close` 为真则标"明日强平")。
- **当日资金二次校验占位**:需 Tushare `moneyflow`/`daily_basic`,**无 token 降级跳过**(摘要里注明"资金校验:已跳过 token 缺失"),不崩。
- **验收**:收盘后每持仓推一条摘要含 盈亏%/D几/明日预警;无 Tushare token 时资金段降级且整条照推。

### B. 客户端地基(SwiftUI multiplatform,照设计终稿)

#### Phase B.1 Xcode 多平台工程 + tokens/models(客户端)

- 新建 Xcode **multiplatform App**(iOS + macOS 单 target),Bundle ID `top.linotsai.linon`。纳入 `client/DesignTokens.swift` + `client/Models.swift`(设计契约,直接用,不改契约)。
- **deploymentTarget**:iOS 26 / macOS 26(设计要 Liquid Glass 原生 `.glassEffect`;玻璃仅栏/浮层/锁屏,数据卡不透明白底)。
- 入 git(`client/` 下工程文件;`*.xcuserstate` 等入 `.gitignore`)。
- **验收**:iOS + macOS 两 scheme 各能 build 通过并起空壳(沿用全局经验:改 View 必须 xcodebuild 跑 App target,不能只 SwiftPM build)。

#### Phase B.2 AppModel + 导航壳 + 两签名组件(客户端)

- `AppModel`(`@Observable`,照 README §State Management):`holdings/archived/candidates/memory/review`、`view/selectedCode/chatMode/thread/composer`、`modal/closeCode/form/toast`;派生 `pnlOf/freeSlots/shownCandidates/portfolioKPIs/shouldForceClose`。本期只接 `holdings`(拉持仓)真数据,其余可空/占位。
- **导航壳分叉**:iOS 底部 `TabView`(今日/候选/复盘/记忆,**后三只放占位空视图**);macOS **240px 玻璃侧栏** + 内容区。
- **两签名组件精确还原**(双端,公式钉死,引用 §4b 常量):
  - `DualLineTrack`:marker `x% = clamp((pnlPct+5)/20*100, 2, 98)`;左 25% 红区、中线 25% 处成本刻度;触损 marker 红 + 呼吸光环。
  - `HoldingDayPips`:D1–D4,过=实心黑/当前=蓝环(触损红)/D4=红虚边/未到=灰;`should_force_close == (count==4)`。
- **验收**:两组件按公式渲染(pnl=-5→x=2、0→25、+15→100;D 计数 1/2/3/4 对应四态);两端导航壳可切 Tab/侧栏项,占位视图不崩。

#### Phase B.3 TodayView 终稿 + 开/清仓 sheet(客户端 · 双端)

- **TodayView 双端**(照 README §1):大标题"今日" + 日期/持仓数 + 右上 `+`;**KPI Hero**(浮动盈亏大字 + 市值/仓位/纪律三联);**教练横幅**(触损持仓时显示,**占位文案**——本期按"触止损持仓"规则触发,大脑阶段3);**HoldingCard 列表**(触损卡红条/红边;DualLineTrack + 距盈距损 + HoldingDayPips + 「问教练」「清仓」按钮)。iOS 垂直 ScrollView + 玻璃 TabBar;macOS 顶部四联横条 + 内联工具栏。
- **算力分工**(§4b):后端供 `price` + `flow3d`;客户端本地算 `pnl/pnlAmount/trackX/hitStop/dist*`(Models.swift 已实现,直接用)。
- **开仓 sheet**(`+` 触发):字段 代码/名称/买入价/数量/进场理由;**止损线只读派生显示 `买入价×0.95`,拒绝手填**。确认 → `POST /positions/open` → 成功回 Today + toast,失败按 reason 弹提示(满仓/重复)。iOS `.sheet` / macOS 居中 modal。
- **清仓 sheet**(卡上「清仓」/教练「标记次日清仓」/横幅按钮):显示该票 + 实时盈亏 + 卖出价 + 时间(默认次日开盘 09:30)。确认 → `POST /positions/{id}/close` → 回 Today + toast。全仓卖出,无减仓。
- **验收**:真机 iOS + macOS 启动进 TodayView;开仓走通(填表→提交→toast→列表出现持仓,满仓再开弹 409 提示);清仓走通(提交→持仓消失→toast);触损持仓显示红卡 + 教练横幅占位文案。

#### Phase B.4 客户端↔后端联调 + 锁屏推送(客户端,iOS 推送专属)

- **拉持仓 + 实时价**:启动/前台拉 `GET /positions`,渲染 holdings;现价由后端 `Position.price` 带(监控已拉)或客户端按需补;客户端本地算 pnl/track/hitStop。
- **APNs 设备 token 上报**:iOS 请求通知权限 → 拿 device token → `POST /devices`。
- **锁屏推送展示(iOS)**:注册通知 `category` 含动作「标记次日清仓」「问教练」;收到硬线推送展示玻璃通知卡(对齐 README §6:红橙条 + "硬线警报" + 升级角标 + 标题/正文);点动作 → 调对应端点 + `POST /alerts/{code}/ack` 停升级;app 内 toast。
- **macOS** 无锁屏推送(平台分叉),可选系统通知,不强制本期。
- **验收**:iOS 真机授权后 device token 成功注册;后端真推一条硬线 → 锁屏出现通知卡 + 动作按钮;点「标记次日清仓」→ 写清仓意图 + ack 停升级;15 分钟未操作收到升级推送。

### C. 部署 / infra(阶段1 真上 ECS)

#### Phase C.1 ECS 落地目录 + 系统用户 + secret(部署)

- 远端建 `/opt/linon`,owner `deploy:linon` mode `2770`(setgid,沿 lw 惯例);新建 **nologin 系统用户 `linon`**(供 systemd 跑服务)。
- secret:`.p8`(APNs)+ `API_TOKEN` 写入 `/opt/linon/.env` 或 `/etc/linon/`,**mode 600,owner `linon`,不入 git**。`.p8` 同样 600。
- rsync `-a` 后**权限复原**(`chown deploy:linon` + `chmod 2770`,同 lw/lf 旧坑);`sync.sh` 已 GNU rsync 守卫 + 阿里云镜像;远端 pip 走阿里云镜像(`setup.sh` 已配)。
- **运维事实同步**:本 Phase 完成后更新 `~/Lino/hz_info.md`(新增 `/opt/linon`、用户 `linon`、端口 8001)。
- **验收**:rsync 推 `backend/` 到 `/opt/linon` 权限正确;远端 `setup.sh` 建出 venv + 库;`.p8`/`.env` 为 600;`hz_info.md` 已更新。

#### Phase C.2 nginx 子域名 + 证书(部署 · 需用户 DNS)

- 新 nginx 站点反代 `127.0.0.1:8001`,子域名 **`ln.linotsai.top`**(已定);certbot 签证书(沿 lf/lw `listen 443 ssl http2;` 旧写法,nginx 1.24)。
- **依赖用户**:加 DNS A 记录 **`ln.linotsai.top → 118.178.122.194`**(列入用户网页操作清单)。
- **验收**:DNS 解析生效后 `https://ln.linotsai.top/api/v1/health` 返 `{status:ok}`;`nginx -t` 干净;邻居站点(lf/lw/主页/xiaoran)未受影响。

#### Phase C.3 systemd 启用 + APNs 真机实测(部署 · 脊椎)

- `deploy/linon.service` enable/start(`User=linon`,沿 lw hardening:`ProtectSystem=strict`/`NoNewPrivileges` 等)。**单 unit(已定)**:FastAPI 与监控守护进程同机,**API 内起后台轮询任务**(内存紧、进程少好管;不拆双 unit)。完成后更新 `hz_info.md` 记端口/unit/子域名。
- **APNs 链路一上来就真机实测**(脊椎,进程活着但推不出去更隐蔽——见坑清单):服务起来后立即从 ECS 真推一条到 iOS 真机,确认 sandbox 网关可达、延迟可接受、通知到锁屏。
- **验收**:`systemctl is-active` 服务在;`/api/v1/health` 经公网返 ok;**ECS → APNs sandbox → iOS 真机锁屏推送实测成功**(这条不过 = 阶段1 主线①未达成);`systemctl --failed` 为 0;`hz_info.md` 记录端口/unit/子域名。

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

- **`.p8` 交接到 ECS**(阶段1):APNs 密钥 `.p8` 在用户本地,需提供给部署流程搬到 ECS secret(C.1 落 mode 600);或用户自行 scp 到 `/opt/linon/`。Key/Team/Bundle 已齐(见 §3)。
- **iOS 真机 + 真签名验证**(阶段1):APNs sandbox 推送、TodayView 开/清仓、锁屏通知动作均需真机走一遍(单测/构建通过 ≠ 推得出去,见全局经验)。dev 直装走 sandbox 网关。
- **Tushare token 待购/录入**(阶段2):2000 积分会员(约 200 元/年),购后写入 ECS `.env`;**阶段1 EOD 资金校验无 token 自动降级跳过**,不阻塞。
- ~~ECS SSH 连接方式~~:已配(`deploy@118.178.122.194:/opt/linon`,公钥登录,`backend/.env` 已填三要素)。

### 用户网页操作清单(必须在网页手动办理)

- **DNS A 记录(阶段1,C.2 前置)**:加 **`ln.linotsai.top → 118.178.122.194`**(子域名已定)。在域名服务商 DNS 控制台加 A 记录,生效后 builder 才能签 certbot 证书。
- ~~APNs 鉴权密钥(.p8)~~:✅ 已生成(Key ID `Q963AP3VY8`)+ App ID `top.linotsai.linon` 已注册并开 Push。剩 `.p8` 交接到 ECS(见上)。
- **Tushare 充值/积分**(阶段2):`https://tushare.pro/`(2000 积分会员)。

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
