# LinoN — 项目专属规范与坑(builder/reviewer 必读)

> 全局规范见 `~/.claude/CLAUDE.md`;权威施工件 `PROJECT_PLAN.md`。本文件只记 LinoN 专属。

## 仓库布局

- monorepo:`backend/`(Python 数据层/部署/冒烟)+ `client/`(SwiftUI iOS+macOS App)+ `archive/`(历史 plan/审查报告)。
- `backend/app/` 子包:`config / data / db / calendar / smoke`。
- 跑后端:`cd backend && source .venv/bin/activate`。建环境:`bash scripts/setup.sh`(幂等)。冒烟:`python scripts/smoke.py [code]`。测试:`python -m pytest`。
- 客户端:`client/` 下 `project.yml`(xcodegen 源)+ `LinoN/`(App/Networking/Calendar/Components/Views/Push/Resources)+ `LinoNTests/`+ 根契约 `DesignTokens.swift`/`Models.swift`。**改 project.yml 后必 `xcodegen generate` 重生 `.xcodeproj`**;`.xcodeproj` 入 git(`xcuserdata`/DerivedData 已 ignore)。

## 钉死的领域常量(单一事实源,禁止各处漂移)

- 止损线 = `buy_price×0.95`,**纯派生不落库**(`positions` 无 stop_line 列);止盈 ×1.15;D4 强平。
- 触发线口径**定死 -5.0**;展示侧 -4.9 仅显示阈(见 `Models.swift` 的 `hitStop`)。
- `kept_stop` 容差带 **[-6%, -4%]**(滑点不误判破纪律),常量在 `app/db/store.py` 顶部。
- 持仓交易日计数:**买入日=D1**,`count==4 ⟺ should_force_close`(D4 强平,可卖 D2/D3)。改这个语义=改契约,必须回 planner。
- 绿涨红跌(用户明确选择,与 A 股本地相反),**勿"纠正"**。

## 阶段1 track A:FastAPI 脊椎(已落地)

- **单 unit 架构**:监控是 app 内后台 asyncio 任务(`app/monitor/loop.py:monitor_loop`),由 `app/api/app.py` 的 `lifespan` 起停,**不另起进程**。测试时设 `app.api.app.ENABLE_MONITOR=False` 关后台轮询,免干扰。
- **代码分层**:`app/api`(app/deps/schemas)、`app/monitor`(hardline 纯判定 / escalation 升级状态机 / eod 摘要 / loop 轮询)、`app/push`(apns)。**硬线判定、EOD、升级全是纯函数/可注入**,单测不联网不真推。
- **规则常量唯一源**:`-5.0/+15.0/D4/容差带` 只在 `app/db/store.py` 顶部;`hardline.py`/`eod.py` 从 store import,**禁止再写一份**。
- **鉴权**:`require_token` 比对 `.env` `API_TOKEN`(Bearer,`hmac.compare_digest`);startup `require_api_token_ready()` fail-fast `len≥16`。本地测试 token 已写 `backend/.env`(64 字符,gitignored)。
- **buy_date 派生**:`open` 的 buy_date = 当前交易日(今天非交易日→`prev_trading_day`);周末/节假日录入会落到上一交易日(预期行为,非 bug)。
- **APNs JWT**:token-based(ES256),`build_jwt(key_pem,...)` 收 PEM 串,**单测用临时 EC P-256 key**(`cryptography.ec.generate_private_key(SECP256R1())`),不依赖真 `.p8`。`send_push(transport=...)` 注入假 transport 即不真连 Apple。`has_apns_config` 仅查四要素齐不齐;`.p8` 路径不存在时 `get_jwt()` 优雅返回 None。
- **依赖**:`PyJWT==2.9.0`/`cryptography==44.0.0`/`httpx[http2]==0.27.2`(钉死,兼容 3.9);`httpx` 也是 FastAPI `TestClient` 的依赖。装库走阿里云镜像(`PIP_INDEX_URL`)。
- **冒烟**:`bash scripts/smoke_api.sh`(起 uvicorn → curl 全闭环);需 `.env` 有 `API_TOKEN`。**真 APNs 实推/ECS/真机留 track C/B**(无设备 token,A.4 只到单测)。
- **pydantic v2 settings 可 monkeypatch**:测试里 `monkeypatch.setattr(settings, "API_TOKEN", x, raising=False)` 可行(模型非 frozen);上文"不能 setattr"指的是无 monkeypatch 的裸赋值场景。
- **监控一 tick 唯一拉价口(审后修复 #1)**:`run_one_tick` **不再二次拉价**——price 与两源一致性校验都复用 `two_source_fn`(默认 `_build_two_source_quotes`,两源各拉一次)的同一对结果;merged price 由 `_merge_price_quote(优先 sina、缺则 tencent)` 派生,口径同 `get_realtime_quotes`。`quotes_fn` 退化为**可选覆盖**:仅显式注入时才用它供 price(老测试/特殊场景),不传则不调。改监控拉价逻辑务必守"每源每 tick ≤1 拉"。
- **D4 时间升级重启不丢(审后修复 #2)**:升级状态仍只在内存。`classify` 只在 `count==4` 产 time 事件,`count≥5` 不产;故 D4 后/夜间重启会丢未 ack 的 D4 nag。修法 = monitor 层恢复(**不动** `should_force_close` 的 `count==4` 契约):lifespan 启动调 `rebuild_time_escalations` + 每 tick `_ensure_time_escalation`,对 `holding` 且 `count_holding_trade_days≥4` 的持仓**保证恒有一条 active time 升级**直到 ack/清仓。**幂等靠 `EscalationManager.has_track(code,kind)`**——已存在(含已 ack)即不重建、不重置 badge(`register` 本就只刷 event 不动 push_count,双保险)。改这块切记别让重跑把 badge 打回 1。

## 数据源坑(已验证)

- 新浪 `hq.sinajs.cn`:**必须带 `Referer: https://finance.sina.com.cn`**,否则返回 `Kinsoku jikou desu!` 无数据。GBK 解码。字段:volume=**股**(÷100→手)、amount=**元**;bid/ask 块「量先价后」。
- 腾讯 `qt.gtimg.cn`:GBK;index0=市场标记;volume(idx6)=**手**、amount(idx37)=**万元**(×1e4→元);bid/ask 块「价先量后」(**与新浪相反,易写反**)。ts(idx30)=`YYYYMMDDHHMMSS`。
- 归一目标(plan):`Quote.volume` 单位**手**、`Quote.amount` 单位**元**。两源已对齐(实测 603986 价/量/涨跌停完全一致)。

## 交易日历

- 静态兜底表 `app/calendar/static_holidays.py` = 官方 2025/2026 休市日 + **调休补班周末(股市仍休)**;来源已查证(国务院通知 + 上交所公告),注释在文件头。trade_cal 到位后用 `verify_against_trade_cal` 比对告警,**不自动改静态表**。
- `app/calendar` 包名与**标准库 calendar 同名**:包内一律绝对导入,**禁止 `import calendar`**(会拿到本包)。本模块只依赖 `datetime`。
- 静态表覆盖 2025–2026;超出年份 `is_trading_day` 退化为"工作日近似"并打 warning(本期不走到,待 trade_cal)。

## 配置

- `app/config/settings.py` 主路径用 pydantic-settings;另有**标准库 fallback**(仅当 pydantic-settings 未装时启用,供未 setup 前的 import 不崩)。装了依赖后 `_BACKEND == "pydantic-settings"`。
- pydantic v2 的 BaseSettings 实例**不能直接 setattr**;测试里要换 settings 用替身对象 monkeypatch 模块级 `settings` 名字 + `reset_client_cache()`。
- `.env` 不提交;`setup.sh` 首次会从 `.env.example` 拷一份占位。

## 依赖/环境

- 开发机 Python 3.9.6(系统自带);`requirements.txt` 钉死版本兼容 3.9(pandas 2.2.3 是支持 3.9 末版,pydantic-settings 2.7.1)。ECS Python 版本待定,这些版本 3.9~3.12 通吃。
- macOS 上 urllib3 报 `NotOpenSSLWarning`(LibreSSL)无害,ECS(OpenSSL)不出现,**勿当 bug 追**。
- `timeout` 命令 macOS 默认无;脚本验证用 `bash -n` 语法检查。

## 部署 / ECS(hz 杭州云)

- 目标 `deploy@118.178.122.194:/opt/linon`(阿里云 ECS,代号 hz;事实源 `~/Lino/hz_info.md`,**任何 hz 运维动作后必须更新它**)。SSH 仅公钥登录、用户 `deploy`。三要素已填 `backend/.env`(gitignored)。
- 这台机已跑 lf/lw/主页/xiaoran + nginx + postgres,**内存仅 1.6G + 2G swap,很紧**;阶段1 上 FastAPI 要挑没占的本地端口(已用 8000/8787/5432/80/443)。
- **坑1 pip 镜像**:ECS 直连公网 PyPI 超时卡死(hz_info 两次重申),`setup.sh` 已默认 `PIP_INDEX_URL=阿里云镜像` + `TIMEOUT=60`,可覆盖。
- **坑2 rsync**:本机 Mac 是 openrsync,与 `--delete` 不兼容;`sync.sh` 已加 GNU-rsync 守卫,需先 `brew install rsync`。
- **坑3 /opt 权限**:`/opt/linon` 未建,按惯例 `deploy:linon` setgid + 阶段1 建 nologin 系统用户;rsync `-a` 会带错 Mac 目录权限,远端需 chown/chmod 复原(同 lw/lf 旧坑)。
- **阶段0 不部署**(无服务);阶段1 接 FastAPI + systemd 后才真 rsync。

## 阶段1 track B:SwiftUI 客户端(已落地)

- **工程生成**:xcodegen multiplatform App(单 target,`supportedDestinations: [iOS, macOS]`),Bundle ID `top.linotsai.linon`,deploymentTarget iOS/macOS 26.0。验证双端:`xcodebuild -scheme LinoN -destination 'platform=iOS Simulator,name=LinoJ-iPhone16Pro' build` + `-destination 'platform=macOS' build`(CODE_SIGNING_ALLOWED=NO 免签名)。改 View 必跑 App target build(全局经验)。
- **iOS ATS 坑(关键)**:iOS 默认禁明文 HTTP,连本机 `http://127.0.0.1:8001` uvicorn 会**静默不发请求**(无报错、UI 空)。已在 `Info.plist` 加 `NSAppTransportSecurity`:`NSAllowsLocalNetworking` + `127.0.0.1` 例外。生产 `ln.linotsai.top` 走 HTTPS 不受影响。
- **clientProvider 时序坑**:`.onAppear` 晚于子视图 `.task`。后端连接注入务必在 `.task` 里 `model.bind(config:)` **先于** `refresh()`,放 `.onAppear` 会让首拉拿到 nil client。
- **API_TOKEN 不入源码**:`AppConfig` 解析优先级 UserDefaults(`LN_API_TOKEN`)→ 环境变量 → bundle 内 `LocalSecrets.plist`(已 gitignore)。模拟器注入:`xcrun simctl spawn <dev> defaults write top.linotsai.linon LN_API_TOKEN <tok>`。**卸载 app 会清 UserDefaults**,重装需重写。
- **签名组件契约 vs 设计**:`Models.swift` 的 `trackX` marker **钳到 98**(`min(98,…)`),设计 README 写 +15%→100% 是近似;组件与单测都对齐契约 98(不改契约)。`stop/take_line` 用 `(buy×ratio×100).rounded()/100`,浮点令 48.30×1.15=55.545→**55.54**(非 55.55),写单测断言注意。
- **平台分叉**:导航壳 `RootView` 内 `#if os(iOS)`(底部 TabView)/`#if os(macOS)`(240px 玻璃侧栏 + Settings 场景);开/清仓 iOS `.sheet` / macOS 居中 modal overlay;锁屏推送 `PushManager` 整文件 `#if os(iOS)`。**Scene body 内 `#if` 不能跨 WindowGroup + Settings 混写**,要整支 if/else 分两套 Scene。
- **本地真跑通**:iOS 模拟器(LinoJ-iPhone16Pro,iOS 26.5)启动到 TodayView 渲染 3 持仓 + 触损红卡 + 教练横幅 + 双线/D pips;macOS 侧栏 + KPI 横条 + 卡片渲染;`GET /positions 200`、开/清仓闭环 curl 走通(409 满仓/重复、404 重复清仓、stop_line 派生)。client 17 条单测全绿(formula/calendar/AppModel)。
- **Settings 屏(2026-06-22 增量)**:共享 `Views/SettingsView.swift`(跨端单一视图),iOS 经 TodayView 齿轮 `.sheet` 弹(包 `NavigationStack`+「完成」)、macOS 经 `Settings{}` 场景复用。**平台分叉**:推送段(device token / 重新注册)整段 `#if os(iOS)`——`PushManager` iOS 专属。**取 PushManager 的桥**:`AppModel` 加 `#if os(iOS) weak var pushManager`,`AppDelegate.attach` 注入(`model.pushManager = pm`),Settings 屏据此读 `lastDeviceToken`/`registerError` + 调 `requestAuthorizationAndRegister()`。`TodayViewIOS` 用 `@EnvironmentObject var config`(`LinoNApp` 已 `.environmentObject(config)`)。自检 = `health()` + `fetchPositions()`(401/noToken→token 错,余→网络错)。**改 project.yml 无须动**:新 .swift 在 `sources: LinoN` 下自动纳入,但**必须 `xcodegen generate` 重生 .xcodeproj** 否则报 "cannot find 'SettingsView' in scope"。
- **computer-use 模拟器点击坑(环境级,非代码)**:macOS Tahoe 的 Dock 持全屏 hit-test 层,computer-use `left_click` 落在模拟器/本 App 窗口上一律被守卫判为 "程序坞"(无法 allowlist Dock);`mouse_move`/`key`(Cmd+,)/`screenshot` 不受影响。验证 iOS `.sheet` 这类需点击的交互卡在此;退路:截图证明控件已渲染 + 跑同款共享视图于 macOS(全 tier、无通知弹窗)实点验证绑定。
- **后端唯一改动**:`GET /positions` 按需拉一拍实时价填 `price`(§4b 联调点,后端供 price 客户端算 pnl);拉价失败不阻塞(price=0,客户端按 buy_price 兜底,pnl=0)。`flow3d` 仍占位(需 Tushare,阶段2)。可注入 `app.api.app._quotes_fn` 免单测联网。
- **待 track C/真机**:真 APNs 投递、真 device token 注册(模拟器拿不到真 token)、锁屏通知卡 + 动作按钮、macOS 系统通知。`PushManager` 的注册/category/ack 行为已实现,真机才能端到端验。

## 待联调(token/SSH/真机就绪后)

- Tushare 有 token 真拉一条 daily/moneyflow(本期只验证无 token 降级)。
- 实时价真源**联网+盘中**复测(本期用收盘快照 + 样例报文单测;盘后源仍返回上一交易日快照)。
- `sync.sh` 填 host/user/path 后真 rsync 到 ECS,远端 `setup.sh` 跑通。
- `deploy/linon.service` 阶段1 接 FastAPI 后才 enable/start(本期注释态)。
