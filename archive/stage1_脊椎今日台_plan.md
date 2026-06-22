# 阶段 1 归档 —— 脊椎 + 今日台(全文 + 实施记录)

> 本文件 = 阶段1 当前版本 Plan 全文(从主 `PROJECT_PLAN.md` §4 收口移入)+ 顶部实施记录。
> 配套审查报告:`archive/REVIEW_REPORT_阶段1.md`。客户端契约(§4b)跨阶段保留在主文件,不在此归档。

---

## 实施记录(收口时回填,2026-06-22)

**结论:阶段1 已完工 + 上线 ECS + 审查通过 + 审后修复(#1/#2)已部署。三项主线全达成。**

- **三轨全落地**:
  - **track A 后端脊椎(A.1–A.5)**:FastAPI on `127.0.0.1:8001`,**单 unit**(监控作 app 内后台 asyncio 轮询,不另起进程);6 端点(health/devices/open/close/positions/ack)过 Bearer 鉴权;3 硬线判定(止损 -5.0 / 止盈 +15.0 / D4 强平)+ T+1 + 涨跌停 + 两源一致性校验;APNs token-based JWT(ES256);升级状态机(未 ack 角标递增重复推,ack 停);EOD 摘要(无 Tushare token 资金段降级)。
  - **track B 客户端(B.1–B.4)**:SwiftUI **iOS + macOS 多平台**(单 target,xcodegen,Bundle ID `top.linotsai.linon`,deploymentTarget 26.0);`@Observable AppModel` + 导航壳分叉(iOS 底部 TabView / macOS 240px 玻璃侧栏)+ 两签名组件精确还原(`DualLineTrack` / `HoldingDayPips`);TodayView 双端 + 开/清仓 sheet + iOS 锁屏推送 `PushManager`;后端唯一改动 = `GET /positions` 按需拉一拍实时价填 `price`。
  - **track C ECS 部署(C.1–C.3)**:真上 hz ECS(`deploy@118.178.122.194`);nologin 用户 `linon` + `/opt/linon`(2770 setgid);nginx 反代 `:8001` + certbot 证书;systemd **单 unit** `linon.service` active(hardening 齐);**ECS→APNs sandbox→iPhone 真机推送实测 status 200**(锁屏硬线卡 + 动作按钮)。
- **测试**:后端 pytest **98→105** 全绿(审后修复 +7 监控测试);客户端 XCTest **17** 全绿;双端 `BUILD SUCCEEDED` 无 body 超时。
- **上线**:live `https://ln.linotsai.top`,公网 health ok、无 token 401;`.env`/`.p8` 均 600 `linon:linon`。
- **reviewer 结论**:**零致命(🔴 无)**,可以收口;三项主线(铁律逼走 / 状态闭环 / 今日台真机可用)均实跑/ECS/真机验证。🟡 重要 3 项(#1 监控每 tick 拉价 / #2 升级状态重启丢失 / #3 open_time 粒度)+ 🔵 建议 6 项 → 详见 `REVIEW_REPORT_阶段1.md`,部分入主文件 §5 Backlog 作阶段2/3 前置。
- **审后修复(已部署)**:
  - **#1 监控每 tick 拉价 3→2 次**:`run_one_tick` 改为每 tick 仅 `two_source_fn`(两源各拉一次),price 从同一对结果派生(优先 sina、缺则 tencent),一致性校验复用同对结果不额外再拉;`quotes_fn` 仅显式注入时才覆盖 price。
  - **#2 D4 时间升级重启不丢**:启动 lifespan 调 `rebuild_time_escalations` + 每 tick `_ensure_time_escalation`,对 `status='holding'` 且 `count≥4` 的逾期持仓始终保证一条 active 未 ack 的 time 升级(补 D4 后 count≥5 时 `classify` 不再产 time 事件的缺口),幂等(`has_track` 已存在即不重建)。**未触碰任何契约**(monitor 层恢复逻辑)。
- **待真机 prod 端到端**(本期 sandbox 已通,prod 闭环列主文件 §5 用户侧收尾):App 切 prod + 填 prod `API_TOKEN`(已生成)→ 注册 device token 到 prod DB → 开仓/监控真推完整闭环。

---

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
