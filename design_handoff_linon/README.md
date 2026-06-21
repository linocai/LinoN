# Handoff: LinoN — A 股短线纪律辅助系统(iOS + macOS SwiftUI 客户端)

## Overview
LinoN 是一个**辅助决策、非自动交易**的 A 股短线系统:约束纪律、放大信息、解释概念,**最终扳机由用户自己扣**。本交接包覆盖**客户端 UI**:今日持仓、候选列表、深度分析/对话(含反情绪教练)、周复盘、记忆,以及锁屏硬线推送。

后端契约(FastAPI + SQLite 四表 + DeepSeek + APNs)已在 `PROJECT_PLAN.md` 锁定;本包的数据模型与之对齐,见 `Models.swift`。

## About the Design Files
本包内的 `LinoN.dc.html`(macOS)与 `LinoN iPhone.dc.html`(iOS)是**用 HTML 制作的设计参考稿** —— 用于表达最终外观与交互意图的高保真原型,**不是用来直接搬运的生产代码**。

任务是**在原生 SwiftUI 工程里重建这些设计**,使用 SwiftUI 的既有范式(`NavigationStack`、`TabView`、`.sheet`、`List`、`@Observable` / `@State`、SF Symbols、`.ultraThinMaterial` 等)。HTML 仅供查看像素级外观与行为;所有取值(颜色/字号/间距)已抽取到 `DesignTokens.swift`,直接用。

> 客户端在 `PROJECT_PLAN.md §2` 锁定为**原生 SwiftUI**(开发者账号直装自有设备,不上架)。第一优先级平台见各团队需要——设计稿两端都给了,iOS 是计划里的正式客户端,macOS 是大屏决策台。

## Fidelity
**高保真(hifi)**。最终配色、字号、字重、间距、圆角、阴影、交互态均已确定,请按 `DesignTokens.swift` 像素级还原。数据为示意,真实数据来自后端。

## Design Language
- **Apple iOS 26 / macOS 26 "Liquid Glass"**,克制使用:玻璃材质(`.ultraThinMaterial` / `.regularMaterial`)只用于**侧栏、工具栏、底部标签栏、浮层、锁屏通知**;**看盘数据一律落在不透明白卡**上,清晰第一。
- **浅色为主**;锁屏推送在深色壁纸上用玻璃。
- **字体**:SF Pro(系统默认),数字一律 `.monospacedDigit()`(等宽对齐,对应 HTML 里的 `font-variant-numeric: tabular-nums`)。
- **涨跌色:绿涨红跌(国际惯例)** —— 注意这是用户明确选择,**与 A 股本地红涨绿跌相反**,请勿"纠正"。

## 签名组件(两个,务必精确还原)
1. **双线轨道 DualLineTrack** —— 把 `-5% 止损 → +15% 止盈`的中间地带可视化的水平轨道。左 25% 为止损红区,中线(成本 0%)在 25% 处竖刻度,当前盈亏映射为轨道上的圆点 marker,两端标注止损价/止盈价。触止损时 marker 红色 + 呼吸光环动画。
   - marker 位置算法:`x% = clamp((pnlPct + 5) / 20 * 100, 2, 98)`(−5%→2%,0%→25%,+15%→100%)。
2. **D1–D4 计数器 HoldingDayPips** —— 4 个圆点表示持仓交易日。已过的日=实心黑;当前日=蓝色描边环(触止损时红环);第 4 日=红色虚边(强平日);未到=灰。**D4 无条件强平**(`should_force_close == (count==4)`)。

## Screens / Views

### 1. 今日持仓 TodayView
- **Purpose**:20 秒看懂"哪只该走"。盯持仓盈亏、双线位置、距第 4 日还有几天。
- **Layout**(iOS):`ScrollView` 垂直;大标题"今日" + 副标题日期/持仓数 + 右上 `+`(开仓录入);下接 **KPI Hero 卡**(浮动盈亏大字 + 市值/仓位/纪律三联);若有触线持仓则 **教练横幅**(红);再下是**持仓卡列表**。底部玻璃 TabBar。
  - macOS:左 240px 玻璃侧栏 + 右内容区;顶部内联工具栏;KPI 为顶部四联横条。
- **Components**:
  - **KPI Hero**:白卡 `radius 20`,浮动盈亏 `34px / weight 680 / monospacedDigit`,颜色随正负(绿 `#0FA968` / 红 `#E5443B`);下方三个 `#F7F8FA` 小块(市值/仓位/纪律)。
  - **教练横幅**:`linear-gradient(120deg, rgba(229,68,59,.08), rgba(232,145,10,.05))` 背景 + `rgba(229,68,59,.18)` 边;◆ 头像(绿蓝渐变圆);一句教练话 + 红色「标记次日清仓」按钮。
  - **持仓卡 HoldingCard**:白卡 `radius 16–18`,`padding 16–20`。触止损卡:左侧 3px 红条 + 红边 + 红色阴影。内容:股票名 `16–17px/680` + 代码灰;理由 chip(中性灰 / 触损红 / 中间地带琥珀 `#E8910A`);右侧现价 `25–30px/660/monospacedDigit` + 涨跌幅;**DualLineTrack**;距盈/距损 + **HoldingDayPips**;底部分隔线下:D 标签 + 「问教练」「清仓」按钮。
- **Copy**:示例持仓"兆易创新 603986 / 沪电股份 002463 / 工业富联 601138";教练横幅文案见 HTML。

### 2. 候选列表 CandidatesView
- **Purpose**:机械排序(放量权重最大)+ 轻量数据;挑中一只才深析。**满仓时闭门**。
- **Layout**:大标题"候选";解释条(蓝)说明"空 N 仓位 → 截断取前 5×N";若满仓显示 🔒 空态卡;否则候选卡列表。
- **Components**:
  - **候选卡 CandidateRow**:白卡;左排名 chip(第 1 名蓝底白字,其余灰);股票名+代码;板块·标签 或 ⚠ 高位警告降级(琥珀 chip);放量进度条(≥80% 绿,否则灰)+ 放量倍数 + 主力净流入;右侧现价/涨幅 + chevron。**整卡可点 → 深析**。
  - 截断脚注:"截断线以下 N 只合格但不在注意力范围内"。
- **排序权重**:放量 ▸ 资金 ▸ 换手 ▸ 低位;**已排除 300/688/白酒/ST**。

### 3. 深度分析 / 对话 AnalysisView
- **Purpose**:on-demand DeepSeek 结构化深析(挑中一只才发起)+ 持仓对话 + 反情绪教练。
- **Layout**:全屏(隐藏 TabBar);顶部返回 + 股票上下文条(名/代码/价/涨跌幅/放量·主力);中间聊天 thread(`ScrollView`);底部 composer(玻璃,圆角输入 + 发送)。
- **Message 类型**:
  - `user`:右侧蓝气泡 `#0B6BCB` 白字,圆角 `18 18 5 18`。
  - `assistant`:左侧白气泡 + ◆ 头像。
  - `analysis`:**结构化深析卡** —— ①形态面 ②资金面 ③消息面(每节带强/确认/无雷等 pill)+ 底部「建议 · 可进/观望/不进」渐变区 + 进场计划。`可进`时附「全仓买入并录入」绿按钮(→ 打开开仓 sheet 预填)。
  - `coach`:**反情绪教练**红橙 `!` 头像 + 红边卡:点破"感觉会反弹"、**调出 5/14 复盘的 4000 块教训**、给出「好,标记次日清仓」。
- **触发逻辑**:对触止损持仓点「问教练」→ coach 介入;对中间地带持仓 → 普通持仓对话;对候选点深析 → analysis 卡。

### 4. 周复盘 ReviewView
- **Purpose**:评分 + 纪律执行率趋势 + 每笔点评(标红/肯定)+ 下周注意(写入交易上下文)。
- **Components**:评分 Hero(绿蓝渐变卡,大分数 + 执行率 + 本周交易/盈利/标红三联);趋势柱状(近 6 周,最后一周高亮渐变,**Y 轴按 min-7~max+2 归一**让差异可见,柱顶标数值);每笔点评卡(肯定绿 chip / 标红红 chip + 盈亏 + 点评);下周注意(琥珀渐变卡)。
- **数据源提醒**:复盘须**同时读未平 `positions`**(扛过周末的套牢票只在 positions 不在 trades)。

### 5. 记忆 MemoryView
- **Purpose**:历史流水 + 闭环结论 + 长期记忆。
- **Components**:结论卡网格(macOS 三列 / iOS 单列)—— kind chip(闭环结论蓝/长期记忆琥珀/纪律里程碑绿)+ 正文 + 底部状态行(如"已绑定反情绪教练触发词");历史流水(已平仓)—— 股票/盈亏/守线徽章(止损·止盈·时间,守住=绿 / 破=红删除线)/点评/日期。

### 6. 锁屏硬线推送 LockScreenPush(仅 iOS,设计示意)
- **Purpose**:系统"脊椎"。硬线触发 → APNs 推送,**升级重复至用户确认**(录动作或主动 dismiss 才停)。
- **Components**:深色壁纸 + 时钟;玻璃通知卡(顶部红橙 3px 条):LinoN 图标 + "硬线警报" + **"第 2 次升级"角标**;标题"沪电股份 已触 −5% 止损线";正文(现价/浮亏 + 双线+时间线两条铁律同时到期 + "次日开盘无条件清仓");「标记次日清仓」「问教练」动作;脚注"未确认每 15 分钟升级重复"。下方盘后摘要/心跳通知。
- **行为契约(PROJECT_PLAN)**:T+1 与涨跌停感知(买入日命中只说"记录,明日处理";一字板说"封死,明日处理");D4 时间止损需多次升级提醒(无券商兜底)。

## Interactions & Behavior
- **导航**:iOS 底部 `TabView`(今日/候选/复盘/记忆);深析为 push 全屏(隐藏 TabBar)。macOS 为侧栏选择。
- **开仓录入**(`+` 或深析「全仓买入」):底部 `.sheet`(iOS)/居中 modal(macOS)。字段=代码/名称/买入价/数量/进场理由。**止损线为只读派生字段**,实时显示 `买入价 × 0.95`,**拒绝手填**(PROJECT_PLAN 硬约束)。确认 → 写持仓、回 Today、toast。
- **清仓录入**(卡上「清仓」或教练「标记次日清仓」或横幅按钮):sheet 显示该票 + 实时盈亏 + 卖出价 + 时间(次日开盘 09:30)。确认 → 从 positions 移除、落 trades、归档到记忆、回 Today、toast。**全仓卖出,无减仓/做 T**。
- **满仓联动**:持仓达 3 → 候选列表闭门(🔒);清掉一只 → 候选按 `5 × 空仓位` 重新打开。
- **动画**:消息/横幅入场 `translateY(6px)→0`,~0.3s ease;sheet `translateY(100%)→0` ~0.3s `cubic-bezier(.2,.8,.2,1)`;触止损 marker 呼吸光环 `lnRing` 1.8s 无限;toast 底部淡入 2.4s 自动消失。
- **空仓位计数**`freeSlots = max(0, 3 - holdings.count)`。

## State Management
建议 `@Observable` AppModel:
- `view`(当前 Tab / 是否在深析)、`holdings: [Position]`、`archived: [TradeRecord]`、`candidates: [Candidate]`、`memory: [MemoryItem]`、`review: Review`
- `selectedCode`、`chatMode('analyze'|'coach')`、`thread: [ChatMessage]`、`composer`
- `modal('open'|'close'|nil)`、`closeCode`、`form`(录入草稿)、`toast`
- 派生:`pnlOf(position)`、`freeSlots`、`shownCandidates`(截断)、`portfolioKPIs`、`shouldForceClose(buyDate, today)`(交易日历)。
- **持仓天数不落库**:用 `buyDate + 交易日历` 按需算(单一事实源)。

## Design Tokens
见 `DesignTokens.swift`(颜色/字阶/间距/圆角/阴影,Swift 可直接用)。核心色:
- 绿(涨/守纪律)`#0FA968` · 红(跌/破线/止损)`#E5443B` · 琥珀(中间地带/警告)`#E8910A` · 交互蓝 `#0B6BCB`
- 文本主 `#1D1D1F` · 文本次 `rgba(60,60,67,.55)` · 卡背 `#FFFFFF` · 页背 `#FBFBFD` / `#F3F4F7`
- 圆角:卡 16–20 · 输入 12 · chip 99(pill) · 玻璃栏 26
- 字号关键值见 README §Screens 与 tokens 文件。

## Assets
- **图标**:全部用 **SF Symbols** 替换 HTML 内联 SVG(导航:`circle.circle`/`list.bullet`/`chart.bar`/`bookmark`;箭头/时钟/info 等就近映射)。HTML 里的 SVG 仅为占位示意。
- **Logo**:"L" 字母标 + 绿蓝渐变圆角方,可用 `Text("L")` + `LinearGradient`,或后续出正式 app icon。
- 无第三方图片资源;K 线/分时图为阶段 4,本包不含。

## Files
- `LinoN.dc.html` — macOS 高保真交互原型(今日方向 A 全流程)
- `LinoN iPhone.dc.html` — iOS 高保真交互原型(5 屏 + 锁屏推送)
- `DesignTokens.swift` — 设计令牌(Color/Font/spacing)
- `Models.swift` — 数据模型,对齐后端 SQLite 四表(positions/trades/reviews/memory)
- `screenshots/` — 全屏导出截图(`ios/` 8 张 + `macos/` 7 张),见 `screenshots/README.md`
- 打开 HTML:浏览器直接打开即可点击走流程(满仓→清仓→候选解锁→深析→开仓回填)。

## 实施建议顺序
1. 先落 `DesignTokens.swift` + `Models.swift` + 两个签名组件(DualLineTrack、HoldingDayPips)。
2. TodayView(含 KPI Hero、HoldingCard、教练横幅)→ TabView 骨架。
3. CandidatesView + 满仓联动。
4. AnalysisView(三类消息 + 结构化深析卡 + 反情绪教练)。
5. 开/清仓 sheet(止损派生只读)+ toast。
6. ReviewView、MemoryView。
7. APNs / 锁屏推送行为(对齐 PROJECT_PLAN 阶段 1)。
