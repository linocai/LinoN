# REVIEW_REPORT_v1.4 — 盘中上下文:教练 + 候选续强确认(Phase A–D)

> reviewer(Fable 5)· 2026-07-05 · 外部审计视角从零审查,对照 PROJECT_PLAN.md §4 逐项。
> 审查范围:Phase A(`91dafcc`)/ Phase B+C(`0a73ead`)/ Phase D(`c86e2b8`)。
> Phase E(交易时段冒烟)按约定不在本次范围(周一执行),仅审其前置就绪度(见 🔵#7)。

## 门禁实测(reviewer 亲跑,2026-07-05 周日)

| 门禁 | 结果 |
|---|---|
| 后端 `python -m pytest` | **497 passed**(7.95s,0 fail;基线 450 + A 24 + B 13 + C 10)|
| 客户端 iOS Simulator `xcodebuild test` | **109 passed**(0 fail;基线 95 + D 14)|
| 客户端 macOS `xcodebuild build`(CODE_SIGNING_ALLOWED=NO) | **BUILD SUCCEEDED** |

周日跑全套仍全绿 = 涉 today 的测试冻结日期纪律(CLAUDE.md D5 副作用条)真正贯彻。

## 整体评估

- **实现完成度:~97%**。Plan §4 Phase A–D 的功能点、plan-critic 修订(致命#1、重要#2/#3/#4、建议#5–#11)**全部真实落地**,验收清单逐条有对应测试(A 24≥14 / B 13≥8 / C 10≥8 / D 14≥6)。缺口:iOS 叠加行缺「高开」字段(🔵#1)、prev5 基准窗口与 plan 字面口径差一天(🟡#2)。
- **代码质量:高**。分层干净(A 纯函数底座 / 编排层唯一组装路径 / 端点层只判窗口+拉价),降级链每个分支都闭合且有测试;`intraday.py` 模块头把"禁复用 loop 窗口"与 VWAP 系数坑(勿照抄 form.py ×1000)写成防御性文档。契约不变性全数守住。
- **主要亮点**:① VWAP 回归门是真门——单测用 `amount≈price×volume×100` 真实比例造假 Quote 并断言 vwap 落在个位数量级(`test_vwap_of_price_above_vwap_true` 的 `vwap < 11.0`),若误写 `amount/volume` 差 100 倍必被抓;② 窗口外"不拉盘中价"用抛异常替身负断言;③ `_freeze_now`(patch `app_mod.datetime`)与 `_freeze_today`(patch `datetime.date`)双轨冻结,Phase B 编排层测试刻意只断言时间无关字段(price/vwap),避免 `analyze_stock` 内 `datetime.now()` 引入的挂钟依赖;④ 3 处既有 fake 签名以"可选参默认值"方式兼容扩展,零破坏。

## 契约不变性核查(v1.4 铁律,逐条)

- 3 硬线 / `-5.0`·`-4.9` 口径 / D4 `count==4`:三个 commit 未触碰 `store/constants.py`、`hardline.py`、`Models.swift` 判定 ✓
- 守味隔离:`context` 仅进 `history_digest`;`review_ref` 仍只回客户端(`app.py:654,670`),盘中注入不经过 brain 路径 ✓
- verdict/advice 二元派生:`coach_advice_from_analysis` 未动;盘中信息只进 prompt ✓
- coach/chat 响应形状:无新增顶层字段 ✓
- 绿涨红跌:客户端 `chg >= 0 ? LN.up : LN.down` 数值派生(有 3 条镜像单测含负值不染绿)✓
- 候选 20 截断:复用 `rules.CANDIDATE_LIMIT` ✓;`GET /candidates` 零改动 ✓
- monitor「每源每 tick ≤1 拉」:`loop.py` 零改动;盘中拉价走独立 `_quotes_fn` on-demand ✓
- 全 repo 无对 `loop._is_trading_now` 的新引用(grep 干净),B/C 端点 + 客户端均以 `intraday._is_intraday_window` / 后端 `isTrading` 为唯一真值 ✓
- 零新表 / 零 migration / 零新数据源:`candidates_intraday` 只读 `latest_candidate_date`+`list_candidates`,不落库 ✓
- 鉴权:新端点 `Depends(require_token)` + 401 测试 ✓;无新输入面(端点无参数),无注入风险 ✓

## 问题清单

### 🔴 致命问题(必须修复)

(无)

### 🟡 重要问题(应该修复)

1. **[client/LinoN/Views/CandidatesView.swift:92-94(iOS)/ 246-248(macOS)]「盘中确认」按钮收到一次 `isTrading=false` 后在 app 会话内永久禁用,无复活路径。**
   `intradayButtonDisabled = intradayLoading || (intraday != nil && intraday?.isTrading == false)`,而 `model.intraday` 全工程只有 `loadIntradayConfirm()` 一个写点、无任何清空/重置点。用户盘前(如 9:15)或收盘后点一次 → 按钮灰死,9:30 开盘后仍不可点,只能杀 app 重启。plan D.4 只写了"响应回 isTrading=false 后再禁用"没写恢复机制(plan 盲区),但落地成"窗口外误点一次 brick 全天功能"违背 feature 本意——时段真值由后端定,后端下一次本可以返回 `isTrading=true`。**修法(任选)**:a) 不禁用,仅显示 banner(最简,与"客户端不自判时段"精神最一致);b) 禁用态仍允许点击重试;c) 收到 `isTrading=false` 后延时(如 5–10 分钟)自动恢复可点。修哪种建议回 planner 确认一句。**周一 Phase E 冒烟当天 9:30 前就可能踩到。**

2. **[backend/app/api/app.py:383 + backend/app/llm/analyze.py:77] prev5 基准窗口在盘中实际取 T-2..T-6,与 plan Phase C「取最近 5 条 vol 均值」(=T-1..T-5)差一天;偏差方向系统性抬高折算量比,且未记偏离。**
   盘中(快照唯一被组装的时段)Tushare daily 最新行是昨日 T-1,`vols[1:6]` 跳过 T-1 取 T-2..T-6。候选全是昨日放量票(T-1 量常为前 5 日均量的 2–3 倍),把 T-1 排除出基准 → `intraday_vol_ratio` 比 plan 字面口径偏大约 20–40%,方向恰是"利多怂恿追高"(plan 建议#11 特意防的方向)。**辩护面**:实现口径与「昨日 EOD 放量倍数」同分母,两个数直接可比("昨日 3.2x → 今日折算 2.0x = 缩量"读得通),也符合 plan"与选股放量口径同源"一语;`app.py:381` 注释亦点明与 `_fetch_form` 同口径——是一个自洽的工程选择,**但它是对 plan 量化口径的实质偏离,未进变更日志,且该注释首句("vols[0] 是今日/最新已收盘日")在盘中场景表述失真**。**修法**:要么保留现实现 → 变更日志补一条口径决策 + 修正注释 +(可选)prompt/客户端文案注明"基准=昨日放量前的 5 日均量";要么改 `vols[:5]`(含 T-1)对齐 plan 字面。**属量化口径拍板,建议回 planner/用户定,不宜 reviewer 单方改。**(附带:`app.py:383` 的 `len(vols)==1 → vols[:5]` 兜底分支与 `_fetch_form` 的"1 行 → 0.0/no_base"语义不一致,极边缘,顺手统一即可。)

3. **[backend/app/llm/analyze.py:337] `chat_stock` 盘中快照 `now=now or datetime.now()` 与形参类型 `Optional[date]` 冲突,潜伏 500。**
   `now` 形参本是给 `fund_asof_date`/事实缓存键用的 **date**;若调用方按签名传 `now=date(...)` 且同时命中 coach+盘中+有 Quote,`build_intraday_snapshot → elapsed_trading_minutes` 调 `now.time()` 直接 `AttributeError`,且该组装在 `try` 之外 → `/chat` 500。当前生产端点不传 `now`、现有测试也没传,故未爆;但与 `analyze_stock`(硬编 `datetime.now()`,不吃 `now`)行为也不一致,同 feature 两函数两套语义是给后人埋雷。**修法**:与 `analyze_stock` 对齐直接 `datetime.now()`(一行);或把注入点做正——形参拆 `now_dt: Optional[datetime]` 供快照、`now` 保持 date 供 fund_asof。

### 🔵 建议改进(可以考虑)

1. **[client/LinoN/Views/CandidatesView.swift:509-531] iOS 盘中叠加行缺「高开」(openChgPct)**——plan D.4 iOS 字段清单明确列了"高开",macOS 有(:539-542)iOS 无,未记偏离;§3 状态行的字段描述对 iOS 也因此不准确。补上(一行)或在变更日志记偏离。
2. **[CandidatesView.swift:509/533 + 570-578] 非交易响应后每候选行都渲染一条"非交易时段"叠加行**——顶部已有 banner(:46/:251),20 行重复噪声。可在 `volNote == "non_trading"` 时整行不渲染叠加。
3. **[AppModel.swift:97 / CandidatesView.swift] 响应 `asof` 已解码但 UI 全程未展示**——10:00 拉的快照 14:00 仍以"盘中"名义叠加显示,保鲜度不可见(plan 把 `asof` 钉进契约正是为此)。建议 banner/header 显示"盘中快照 {asof}"。
4. **[backend/app/api/app.py:400-411] 无候选/空候选时 `isTrading` 硬编 `false`**——交易时段内无候选缓存时,客户端按钮被禁 + 文案"非交易时段"误导(实际是无候选;还会连带 🟡#1 永久禁用)。plan 原文如此(措辞盲区);建议客户端对 `degraded=true` 显示"无候选缓存"而非非交易文案,或后端如实返回窗口值、让 degraded 单独表意。
5. **[backend/app/llm/prompt.py:101-103 / 281-283] 形态块标签「昨日 EOD」在盘后场景不准**——盘后 daily 已含今日行,form 数据实为"今日 EOD";标签固定"昨日"会让盘后候选深判把今日收盘数据误称昨日。plan 建议#8 原意针对盘中;建议改"最新 EOD"或按 `intraday` 键有无条件化。
6. **[backend/tests/test_candidates_api.py:444-464] `test_coach_non_trading_window_no_intraday_quote` 的 `_boom` 实际仍被 `_resolve_prices` 调用并吞掉**——"窗口外不拉盘中价"的负断言只对盘中专用路径成立(测试注释自知)。建议改计数替身,精确断言"`_resolve_intraday_quote` 路径未发生",避免后人误读测试强度。
7. **[Phase E 前置] `backend/scripts/smoke_intraday.sh/.py` 尚不存在**(plan E 交付物)。就绪度评估:E 要验的口径在代码里**均可验**——`intraday.py` 四函数纯函数可直接 import 打数字;`Quote` 带 `high/low`(E.2 VWAP∈[low,high] 可断);两源 `_fetch_sina/_fetch_tencent/_parse_sina/_parse_tencent` 均模块级可单独调用(E.1 两源一致性可对拍)。周一冒烟前需先写脚本;E.3 人工核对折算数字时注意按已实现的 prev5 口径(🟡#2)对账。
8. **[backend/app/api/app.py:361-388] `_PREV5_CACHE` 值依赖 `date.today()` 但键只有 `(code, td)`**——候选多日未手动刷新(刷新已改纯手动)时 td 不滚动,跨日命中旧值;此时整个视图本就语义过期,影响极小。可把 today 并入键或忽略。

## 测试质量核查

- **VWAP 反向公式回归门(plan 致命#1 单测要求)**:真实有效。`test_intraday.py::_make_quote` 默认 `amount=price×volume×100`;`test_vwap_of_price_above_vwap_true` 断言 `vwap < 11.0`(个位数量级)+ `is_above is True`——若实现少除 100,vwap≈1100 两断言双杀。`test_candidates_api.py::_fake_quote_for`、`test_llm.py::_quote` 同款真实比例。✓
- **时间确定性**:Phase A 全部固定 datetime;Phase C 冻结 `app_mod.datetime`(`_freeze_now_intraday`);coach 端点测试双冻结(`_freeze_today`+`_freeze_now`);Phase B 编排层测试因 `analyze_stock` 内部 `datetime.now()` 不可注入,**刻意只断言时间无关字段**(is_trading/price/is_above_vwap),不碰 `intraday_vol_ratio`——是清醒的取舍而非放水。周日实测全绿佐证。✓
- **镜像逻辑测试**(客户端按钮态/着色为 private 计算属性,测试复制表达式断言):与阶段3.1 `CandidateScoreDecodeTests` 同款已接受代理模式,注释点明镜像关系。可接受。
- **无放水断言**:抽查全部 61 条新增,断言均落在行为(HTTP 形状/context 键/数值),无 `assert True` 式凑数;3 处既有 fake 签名扩展是兼容性适配非放水。✓

## 施工残留核查

- 无 print/调试遗留;`intraday.py` 自批1 后零改动(0 diff);app.py 批2 diff 全部 hunks 在 plan 范围内;批3 未触碰 `AnalysisView`/`TodayView`;`project.pbxproj` 已 xcodegen 重生(新测试文件已注册)。无 plan 外私加实现。✓
- 变更日志:立项 + plan-critic 修订两条已记;三批施工记录在 §3 当前状态(符合工作流)。**缺**:🟡#2 prev5 口径、🔵#1 iOS 高开缺失两处偏离未记(修复/拍板时一并补)。

## 结论

**可收口前提 = 处理 3 条 🟡**:#1(按钮永久禁用)建议修复后再进 Phase E(周一盘中冒烟当天即可能踩中);#2(prev5 口径)需 planner/用户拍板留或改并补记变更日志;#3 一行对齐。三条均为小改,不涉契约、不涉 migration。8 条 🔵 可入 §5 Backlog 或收口时顺手处理(#7 是 Phase E 的行动项非缺陷)。
