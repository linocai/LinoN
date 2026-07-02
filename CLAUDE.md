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
- `kept_stop` 容差带 **[-6%, -4%]**(滑点不误判破纪律),常量在 `app/db/store/constants.py`(经 store 包 re-export)。
- 持仓交易日计数:**买入日=D1**,`count==4 ⟺ should_force_close`(D4 强平,可卖 D2/D3)。改这个语义=改契约,必须回 planner。
- 绿涨红跌(用户明确选择,与 A 股本地相反),**勿"纠正"**。

## 阶段1 track A:FastAPI 脊椎(已落地)

- **单 unit 架构**:监控是 app 内后台 asyncio 任务(`app/monitor/loop.py:monitor_loop`),由 `app/api/app.py` 的 `lifespan` 起停,**不另起进程**。测试时设 `app.api.app.ENABLE_MONITOR=False` 关后台轮询,免干扰。
- **代码分层**:`app/api`(app/deps/schemas)、`app/monitor`(hardline 纯判定 / escalation 升级状态机 / eod 摘要 / loop 轮询)、`app/push`(apns)。**硬线判定、EOD、升级全是纯函数/可注入**,单测不联网不真推。
- **`app/db/store` 是包不是单文件(2026-07-02 拆包)**:原 909 行 `store.py` god-module 按实体拆为 `app/db/store/{constants,_common,schema,positions,trades,review,device_tokens,candidates,outcomes}.py`,**`__init__.py` 原样 re-export 全部公开 API + 外部用到的私有名(`_compute_kept_flags`/`_ensure_*`/`_CANDIDATE_KEYS`/`_SCHEMA`/`_now`/`_db_path`)**——所有调用点(`from app.db.store import X` / `store.X` / `store_mod.X`)逐字节零改动,309 测试无回归。**坑**:`close_position` 沉淀 memory 经 **facade 取 `insert_memory`**(`from app.db import store as _store; _store.insert_memory(...)`)而非顶部直接 import 绑定——否则 `monkeypatch(app.db.store.insert_memory)` 拦不到、原子回滚测试失效。改 store 内跨模块调"被 monkeypatch 拦截的函数"时切记走 facade。
- **规则常量唯一源**:`-5.0/+15.0/D4/容差带` 只在 `app/db/store/constants.py`(经 store 包 `__init__` re-export,import 口径不变 `from app.db.store import …`);`hardline.py`/`eod.py` 从 store import,**禁止再写一份**。
- **鉴权**:`require_token` 比对 `.env` `API_TOKEN`(Bearer,`hmac.compare_digest`);startup `require_api_token_ready()` fail-fast `len≥16`。本地测试 token 已写 `backend/.env`(64 字符,gitignored)。
- **buy_date 派生**:`open` 的 buy_date = 当前交易日(今天非交易日→`prev_trading_day`);周末/节假日录入会落到上一交易日(预期行为,非 bug)。
- **APNs JWT**:token-based(ES256),`build_jwt(key_pem,...)` 收 PEM 串,**单测用临时 EC P-256 key**(`cryptography.ec.generate_private_key(SECP256R1())`),不依赖真 `.p8`。`send_push(transport=...)` 注入假 transport 即不真连 Apple。`has_apns_config` 仅查四要素齐不齐;`.p8` 路径不存在时 `get_jwt()` 优雅返回 None。
- **依赖**:`PyJWT==2.9.0`/`cryptography==44.0.0`/`httpx[http2]==0.27.2`(钉死,兼容 3.9);`httpx` 也是 FastAPI `TestClient` 的依赖。装库走阿里云镜像(`PIP_INDEX_URL`)。
- **冒烟**:`bash scripts/smoke_api.sh`(起 uvicorn → curl 全闭环);需 `.env` 有 `API_TOKEN`。**真 APNs 实推/ECS/真机留 track C/B**(无设备 token,A.4 只到单测)。
- **pydantic v2 settings 可 monkeypatch**:测试里 `monkeypatch.setattr(settings, "API_TOKEN", x, raising=False)` 可行(模型非 frozen);上文"不能 setattr"指的是无 monkeypatch 的裸赋值场景。
- **监控一 tick 唯一拉价口(审后修复 #1)**:`run_one_tick` **不再二次拉价**——price 与两源一致性校验都复用 `two_source_fn`(默认 `_build_two_source_quotes`,两源各拉一次)的同一对结果;merged price 由 `_merge_price_quote(优先 sina、缺则 tencent)` 派生,口径同 `get_realtime_quotes`。`quotes_fn` 退化为**可选覆盖**:仅显式注入时才用它供 price(老测试/特殊场景),不传则不调。改监控拉价逻辑务必守"每源每 tick ≤1 拉"。
- **D4 时间升级重启不丢(审后修复 #2)**:升级状态仍只在内存。`classify` 只在 `count==4` 产 time 事件,`count≥5` 不产;故 D4 后/夜间重启会丢未 ack 的 D4 nag。修法 = monitor 层恢复(**不动** `should_force_close` 的 `count==4` 契约):lifespan 启动调 `rebuild_time_escalations` + 每 tick `_ensure_time_escalation`,对 `holding` 且 `count_holding_trade_days≥4` 的持仓**保证恒有一条 active time 升级**直到 ack/清仓。**幂等靠 `EscalationManager.has_track(code,kind)`**——已存在(含已 ack)即不重建、不重置 badge(`register` 本就只刷 event 不动 push_count,双保险)。改这块切记别让重跑把 badge 打回 1。

## 阶段2:选股 + 决策(后端 D1–D5 已落地)

- **新包**:`app/screen/{rules,fetch,pipeline}.py`(选股数据层)+ `app/llm/{prompt,deepseek,sentiment,analyze}.py`(DeepSeek 深判层)。新增 4 端点:`GET /candidates`、`POST /candidates/refresh`、`POST /candidates/{code}/analyze`、`POST /positions/{id}/coach`。新增 `candidates` 缓存表(DDL §4.2,`UNIQUE(trade_date,code)`)。
- **规则单一源不漂移**:选股硬规则(黑名单按**板块前缀**:创业板 `30*`/科创 `688*`+`689*`/北交所 `8*`+`4*`+`920*`、ST、白酒行业;高位线 ≥100% 排除·≥50% warn、截断 `5×free_slots`、排序权重 `vol0.4/fund0.25/turnover0.2/low0.15`)全在 `app/screen/rules.py` 顶部;`-5.0/+15/D4/容差带` 仍只在 `app/db/store/constants.py`(选股层不碰)。**代码段黑名单坑(2026-06-28 三次同类漏后统一修)**:枚举精确段易随交易所新增子段漏挡,**已统一收为板块整段正则 `^(30|688|689|8|4|920)`**——创业板旧 `300` 漏 301/302(信濠光电 301051)、科创旧 `688` 漏 689 CDR(九号 689009)、旧无 `920` 漏北交所新段(莱赛激光 920363)。**教训:黑名单按板块整段、勿枚举精确子段**。**铁律:技术面交 LLM 判**——`rules.py` 的宽筛阈(`VOL_MULTIPLE_MIN=1.5`/`NEW_HIGH_DAYS=20`/`MA_DAYS=20`/近3日净流入>0)都标注"宁松勿紧、复盘迭代、不卡生死",不当死阈值。
- **Tushare 真实字段口径(2026-06 冒烟校验,务必照此解析)**:全市场批量接口不带 `ts_code`、只带 `trade_date` → 一次返回全市场。`daily_basic`:`close`/`turnover_rate`(%)/`total_mv`(**万元**,÷1e4→亿)/`volume_ratio`(量比,本期未用)。`moneyflow_dc`(**选股资金面唯一信号,东财源,见下条**):`net_amount`(**万元**,主力净额)。`daily`:`vol`(手)/`amount`(**千元**)/`close`/`pre_close`/`pct_chg`(%)。放量倍数=当日 vol/前5日均 vol(自己算,非 volume_ratio)。`moneyflow`(原始源,保留供 LLM 深判层 `analyze.py`):`net_mf_amount`(**万元**,同花顺式主力口径)。
- **资金源已切东财 `moneyflow_dc`(2026-06-28,6000 积分解锁)**:选股数据层(`screen/fetch.py` 经 `tushare_client.ts_moneyflow_dc_all`)读 `net_amount`(**万元**)替代原始 `moneyflow.net_mf_amount`(**同单位万元**,展示侧 `_fmt_flow` ÷1e4→亿 不变)。**`net_amount` = `buy_elg_amount`(超大单)+ `buy_lg_amount`(大单)**——东财"主力"口径(实测 6/26 茅台 `-62432.45`万 = `-28934.93` + `-33497.52`,逐分对齐)。东财源全市场**给到上一交易日**(今天 6/28 → 数据 6/26,5887 行),比原始 `moneyflow` 偶发"几天到约一周"发布延迟更优。与原始 `moneyflow` **数值有口径差(东财主力 vs 同花顺式)属预期非 bug**——这正是用户在东财/同花顺 App 里看到的那套主力净额,更标准。字段全集:`trade_date/ts_code/name/pct_change/close/net_amount/net_amount_rate/buy_{elg,lg,md,sm}_amount(及各 _rate)`。**降级守恒**:无 token / 2000 积分无 `moneyflow_dc` 权限(Tushare 抛权限异常)/ 拉取失败 → 资金面退化为 0(`fetch` 不崩;但粗筛"近3日净流入>0"会把全市场挡掉 → degraded 空列表,符合契约)。
- **白酒黑名单口径(Review 拍板)**:用 `stock_basic.industry` 精确归类,**非名称关键词**。实测 Tushare 酒类 industry 值:`白酒`(19 只,茅台 600519/五粮液 000858 均在)、`啤酒`、`红黄酒`(注意是"红黄酒"非"黄酒",我的关键词 `黄酒` 子串命中它)。**`酒店餐饮` 不是酒企,不能排除**——我的关键词列表(`白酒/酿酒/黄酒/啤酒/葡萄酒/其他酒`)都不是 `酒店餐饮` 的子串,正确放行。行业映射 `fetch.load_industry_map()` 进程内缓存(启动/EOD 拉一次),无 token → 空映射,白酒黑名单退化为仅代码段/ST(不崩)。
- **Tushare 聚合数据发布延迟(订正旧说法)**:旧记"2000 积分滞后到 2026-05-06、非 bug"是误判——实测真相:Tushare 聚合资金/指标接口(原始 `moneyflow`、`daily_basic` 等)**发布有几天到约一周延迟、会逐步补齐**(2026-06 端午期叠加积压,原始 moneyflow 一度滞后到 6/12 后补齐),并非固定停在某日的"会员档数据"。**东财 `moneyflow_dc`(6000 积分)当前给到上一交易日**(6/28→6/26),已是更优源。候选 EOD 基准日 = 今天(交易日)或上一交易日;拉不到该日 → `fetch` 失败/资金退化 → pipeline degraded 空列表(不崩)。时序不确定性由深判 `fund_asof` 标注 + 降级链兜住。
- **DeepSeek 降级链(全链路不崩)**:`deepseek.analyze(ctx, transport=...)` 可注入 `httpx.MockTransport` 免单测联网(沿 `send_push(transport=...)` 模式)。缺 `DEEPSEEK_API_KEY`/超时/非 200/非法 JSON → `degraded_analysis()` 占位卡(verdict=观望、三轴 tone=neutral)。`clamp_analysis` 把 tone 越界→neutral、verdict 越界→观望、空 plan→兜底文案。`_loads_lenient` 容忍 markdown 围栏/前后杂字。**真模型冒烟**:`deepseek-chat`+`response_format=json_object` 真输出字段/枚举与我的 schema 完全吻合,candidate 模式返 verdict=可进、coach 恶化持仓返 verdict=不进→advice=清,fund.text 自动带 EOD 时序标注。
- **资金时序铁律**:`analyze.fund_asof_date()` 一律取**上一交易日**(`prev_trading_day(today)`,不含今天),深判响应带 `fund_asof` 标注"资金面=截至上一交易日 EOD,今日盘中资金未知"。
- **coach 二元映射**:`coach_advice_from_analysis(analysis)` = `verdict=='不进'→'清'`,否则 `'拿'`(观望/可进→拿)。中间地带**仅二元无减仓**。`/positions/{id}/coach` 收 `position_id`(int),非持仓(不存在/已 closed)→ 404 `not_holding`。
- **候选刷新 tick(15:35)**:`loop._is_after_candidate_window`(>=15:35,晚于 EOD 推送 15:05);`monitor_loop` 用 `last_candidate_date` 防重(每交易日一次),`run_candidate_refresh` 失败吞异常不掀翻轮询。端点/EOD tick 共用 `run_pipeline`,均可注入 `_pipeline_fn` 免单测联网。
- **D5 buy_date(reviewer 🔵#1 已修)**:`app.api.app._current_trade_date` 周末/节假日录入改取 `next_trading_day`(不再 `prev_trading_day`),免 D 计数从已收盘上一交易日提前起算;**不破** `should_force_close` 的 `count==4` 契约。`_candidate_basis_date`(候选 EOD 基准)仍用 `prev_trading_day`(那是数据口径,不是 buy_date)。
- **D5 副作用:依赖 today 的 D 计数测试必须冻结日期**:任何"经 `/positions/open` 开仓(buy_date=`_current_trade_date()`)后断言 `trade_day`/D 计数(vs `date.today()`)"的测试,**周末/节假日跑会假性失败**——非交易日 buy_date 取下一交易日(未来),`count[buy_date, today]=0`。修法 = 冻结 today 到交易日:`monkeypatch.setattr("datetime.date", _FixedDate)`(`_FixedDate(date)` 重写 `today()`,见 `test_api.py` D5 三态测试 / `test_candidates_api._freeze_today`)。`_current_trade_date` 与 coach 端点都 `from datetime import date; date.today()`,patch `datetime.date` 类两处都生效。**别用 `pytest.skip`/`--deselect` 绕**——那是把门禁做假。

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
- **坑4 rsync exclude 误伤 `app/data/`(2026-06-28 阶段2 部署才暴露)**:`sync.sh` 的 `--exclude 'data/'`(本意排 SQLite 库 `backend/data/`)**无前导斜杠 → rsync 匹配任意层级目录**,把数据层包 `app/data/`(realtime+tushare_client)也一起排掉了;阶段0/1 至今 ECS 上**从没有 `app/data/`**(惰性导入+降级让服务照常 active,但实时拉价一直静默失败/price=0,故阶段1 prod 端到端一直没真验)。**修:`--exclude '/data/'` 锚定根**(只排 backend 那个 SQLite 库)。教训:rsync exclude 排根级目录**必须前导斜杠锚定**。
- **坑5 tushare `set_token` 写家目录炸 nologin 用户(2026-06-28)**:`ts.set_token(t)` 会往 `~/`(用户家目录)写 token 缓存文件;ECS 服务用户 `linon` 是 nologin、无可写家目录 → `[Errno 13] Permission denied: '/home/linon'` 致 **Tushare 初始化整条崩、全市场拉取静默降级**(`refresh` 返 count=0 degraded)。单测/本地(跑在有家目录的 deploy/Mac 用户)抓不到——真环境坑。**修 `tushare_client._get_pro`:改 `ts.pro_api(token)` 直传**(不调 set_token,不碰家目录)。
- **阶段0 不部署**(无服务);阶段1 接 FastAPI + systemd 后才真 rsync。**阶段2 已部署上线(2026-06-28)**:app/data 首次真上 ECS、选股+深判端到端验通(refresh 71 候选 degraded=false、内存峰 926MB/swap 0、/analyze 真 DeepSeek 返合法卡、公网 HTTPS 200)。

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

## 阶段2 track E:候选 + 深析客户端(已落地)

- **新增视图**:`Views/CandidatesView.swift`(E1)+ `Views/AnalysisView.swift`(E2),均双端共享内容、布局分叉(iOS 大标题 ScrollView / macOS 工具栏+内容区)。改 .swift 后**必 `xcodegen generate`**(同 track B 坑)。
- **契约对接**(D1–D5 builder 移交,逐字段对齐):① `GET /candidates` 返 `Candidate` camelCase dict(`volMultiple/volPct/flow/turnover/warn?`),**列表里 `analysis` 省略**——客户端用 `CandidateListDTO` 解码后填**占位 DeepAnalysis**(深判 on-demand 时 `/analyze` 覆盖)。**勿直接 decode 进 `Candidate`**(其 `analysis` 非可选会失败)。② `analyze`/`coach` 返回的 `analysis` dict 形状与 `Models.swift` `DeepAnalysis` **逐字段一致**(form/fund/news 各 {value,tone,text} + verdict 可进/观望/不进 + plan,tone good/warn/bad/neutral),`JSONDecoder().decode(DeepAnalysis.self)` 直接吃,**无需自定义 CodingKeys**。③ `coach` 返 `advice∈{拿,清}`+`reason`(=plan)+`analysis`+`fund_asof`;教练卡文案取 `reason`。④ 上游失败仍 HTTP 200 返降级占位卡(verdict=观望/三轴 neutral),E2 不处理 502。
- **满仓闭门联动**:`AppModel.shownCandidates = openSlots>0 ? candidates.prefix(5*openSlots) : []`(后端已按 `free_slots` 运行时截断,客户端再夹一层做满仓即时闭门 + 安全带)。`refresh()` 末尾追 `loadCandidates()`,使**清仓后候选自动重开**(持仓变 → 重拉 → 后端按新 free_slots 截断)。
- **深析全屏分叉**:iOS 用 `.fullScreenCover(isPresented: model.inAnalysis)` 包 `AnalysisView`(天然隐藏 TabBar,满足 README §3);macOS 在 `macShell` 内容区 `if model.inAnalysis { AnalysisView } else { content }` 覆盖(非新窗)。两端共用 `AnalysisView(compact:)`。
- **导航入口**:候选卡整卡 `Button → Task { await model.openAnalysis(code:) }`;TodayView 持仓卡 `onCoach → Task { await model.openCoach(code:) }`(触损→coach 红橙卡 / 中间地带→助手气泡)。深析卡「全仓买入并录入」绿按钮 → `buyFromAnalysis()` 退深析 + 预填开仓 sheet(code/name/price/reason,reason 取 candidate.tag)。
- **iOS fullScreenCover↔sheet 同帧交接坑(审后修)**:`buyFromAnalysis`/`markCloseFromAnalysis` 不能"`inAnalysis=false` 同步紧跟 `modal=.open`"——关 cover 会触发其 binding `set:{ backFromAnalysis() }`,与同一 transaction 内呈现 `.sheet` 打架,sheet 可能不弹。修法 = `presentModalAfterCoverDismiss`:iOS 把 modal 呈现推到 `Task.sleep(~0.35s)`(等 cover 退场)后,macOS 无 cover 即时呈现。表单先备在局部 `EntryForm` 再于回调赋值。**对应单测改 async**(等过推迟窗口再断言 modal)。
- **绿涨红跌一致性(审后修)**:`openAnalysis` 顶栏 `chgIsUp` **必须从 `c.chg` 派生**(`!c.chg.contains("-")`),勿硬编 true——候选粗筛不卡正涨幅,负跌候选存在,硬编会把跌染绿。候选 chg/flow 后端是 **ASCII `-`**(Python `:+.2f`),`.contains("-")` 可判;但**持仓 pnl 串走 `LNFmt.signedPct` 是 Unicode `−`(U+2212)**,`.contains("-")` 判不出——持仓侧一律用派生 bool(`pnl>=0`)不要字符串判负。
- **侧栏切 Tab 退深析(审后修)**:macOS `navItem` action 里 `if model.inAnalysis { backFromAnalysis() }` 再切 `view`,否则 `inAnalysis` 覆盖内容区会让侧栏选中态与可见内容失同步。
- **`@MainActor` 派生坑**:`CandidatesCopy`(读 `AppModel` 派生的文案工具)枚举必须标 `@MainActor`,否则 SwiftUI 视图 body(nonisolated 上下文)调用报 "main actor-isolated property can not be referenced from a nonisolated context"。
- **复盘历史引用 = 阶段3 占位**:coach 红橙卡内嵌 `reviewQuotePlaceholder`(clock + "阶段3 接入"文案),破纪律检测/真实复盘引用大脑留阶段3(对齐 §4b 教练 UI-大脑 拆分)。
- **资金时序标注**:`DeepAnalysisCard` 底部显著展示 `fund_asof`("资金面 = 截至 {date} EOD,今日盘中资金未知");`fundAsof` 由 `analyze`/`coach` 响应填 `AppModel.fundAsof`。
- **computer-use 本机全屏 Dock 守卫(环境级,加重版)**:本轮 macOS App **及 iOS Simulator** 的 `left_click`/drag **全屏一律被判 "程序坞"**(连菜单栏 y=8、居中弹窗都拦),非位置相关——比 track B 记录的更彻底;`screenshot`/`zoom`/`mouse_move`/`key` 仍可用。AppleScript 移窗需"辅助功能"权限(未授,失败)。**可视核对退路**=`ImageRenderer` 离屏快照(`LinoNTests/SnapshotRenderTests.swift`,产物落 sim 沙盒 `tmp/`,`simctl` 路径拷出)。**`ImageRenderer` 坑**:不渲染 `ScrollView` 内容(产出空白页),要核对 ScrollView 内组件须**单独渲染组件本体(裹 VStack 而非 ScrollView)**;非 ScrollView 包裹的卡(DeepAnalysisCard / ClosedEmptyCard / 顶栏 / composer)渲染正常。
- **iOS 候选行布局 ≠ macOS**(照各自设计稿):iOS 行 = rank chip + 弹性中列(名/警告·板块/[放量条54px·放量·主力])+ 右侧价/涨/chevron 竖排;macOS 行 = 横向多列(#/股票/现价涨幅/放量条·倍数/主力/换手/深析按钮)。**别把 macOS 横列套到 iOS**(iPhone 宽度放不下会把名字挤成省略号)。
- **本地真数据联调**:`uvicorn` 起 dev(`ENABLE_MONITOR=0 DB_PATH=/tmp/xxx.db`,避动真 DB)→ 客户端 dev 指 `127.0.0.1:8001`(iOS Simulator 也走 host loopback)→ token 注入 `defaults write top.linotsai.linon LN_API_TOKEN <tok>`(macOS App / `simctl spawn <dev> defaults write` for sim)。Tushare 聚合数据**发布有几天到约一周延迟、逐步补齐**(订正旧"滞后到 2026-05-06"误判;东财 `moneyflow_dc` 6000 积分给到上一交易日),`refresh` 拉的基准日若 EOD 未出会 count=0 非 degraded;可直接 `store.upsert_candidates(td, rows, db_path=...)` 种样例验渲染。深析卡 fund.text 会按真 daily 数据给真 verdict(种的样例价仅占位)。
