//
//  Models.swift
//  LinoN — 客户端数据模型
//
//  对齐后端 SQLite 四表(见 PROJECT_PLAN.md §4 Phase 0.4):
//    positions / trades / reviews / memory
//  关键约束:
//   · 持仓"全有全无",无部分仓位字段;最多 3 行。
//   · stop_line 系统派生 = buy_price × 0.95,拒绝用户手填。
//   · 持仓天数【不落库】——用 buyDate + 交易日历按需算。
//   · 离场铁律:止损 -5% / 止盈 +15% / 第 4 交易日(D4)无条件清仓。
//

import Foundation

// MARK: - positions(最多 3 行,status == holding)

struct Position: Identifiable, Codable {
    var id: Int
    var code: String
    var name: String
    var buyPrice: Double
    var qty: Int
    var entryReason: String          // 用户录入:进场理由(一句话)
    var entrySnapshot: EntrySnapshot? // 系统自动:开仓瞬间形态+资金快照(JSON)
    var buyDate: Date                // 交易日历基准(D1 起算)
    var status: String = "holding"

    /// 系统派生,拒绝手填
    var stopLine: Double { (buyPrice * 0.95 * 100).rounded() / 100 }
    /// 止盈线 +15%
    var takeLine: Double { (buyPrice * 1.15 * 100).rounded() / 100 }

    // —— 实时态(来自行情源,非落库)——
    var price: Double = 0            // 现价
    var flow3d: String = "—"         // 主力近 3 日净流入(展示串)

    var pnlPct: Double { buyPrice == 0 ? 0 : (price - buyPrice) / buyPrice * 100 }
    var pnlAmount: Double { (price - buyPrice) * Double(qty) }
    var hitStop: Bool { pnlPct <= -4.9 }          // 含 ±1% 容差语义,见 PROJECT_PLAN 约束5
    var distTakePct: Double { price == 0 ? 0 : (takeLine - price) / price * 100 }
    var distStopPct: Double { price == 0 ? 0 : (stopLine - price) / price * 100 }

    /// 双线轨道 marker 位置(2…98)。−5%→2、0%→25、+15%→100
    var trackX: Double { min(98, max(2, (pnlPct + 5) / 20 * 100)) }
}

struct EntrySnapshot: Codable {
    var formNote: String   // 形态快照
    var fundNote: String   // 资金快照
}

// MARK: - trades(每笔一买一卖闭合;清仓时由 positions 归档而来)

struct TradeRecord: Identifiable, Codable {
    var id: Int
    var code: String
    var name: String
    var openPrice: Double
    var closePrice: Double
    var openTime: Date
    var closeTime: Date
    var keptStop: Bool       // 守住止损(带 -6%~-4% 容差带)
    var keptTake: Bool       // 守住止盈
    var keptTime: Bool       // 守住时间(D4)
    var pnl: Double          // 百分比
    var brokeRule: Bool      // 标红依据
    var note: String         // 复盘点评
    /// v1.3.0 Phase D1:净收益金额(元,可空)。迁移前的旧行 → nil,展示"—"(区分"没数据"vs"真0元")。
    var netPnlAmount: Double? = nil
}

// MARK: - reviews(周复盘)

struct Review: Codable {
    var week: String
    var score: Int                  // 纪律评分 0–100
    var redFlags: [String]          // 标红项(JSON)
    var disciplineRate: Int         // 纪律执行率 %
    var rateTrend: Int              // 环比 ▲
    var lessons: String
    var nextWeekNote: String        // 下周注意 → 写入交易上下文
    var trend: [WeekPoint]          // 近 6 周执行率趋势
    var trades: [ReviewTrade]
    // 阶段3 补(设计 §4「复盘须同时读未平 positions」):未平持仓 + 空周诚实标注。
    var openHoldings: [OpenHolding] = []   // 扛过周末的套牢票(只在 positions 不在 trades)
    var sampleNote: String = ""            // 样本量提示(如"本周 0 笔闭合")
    /// v1.3.0 Phase D1:周净额合计(元,可空)。周内无任何非空净额行 → nil(显"—");
    /// 否则 = 该周所有非空 netPnlAmount 之和(跨迁移周部分行仍显"—",合计只 sum 非空行)。
    var netPnlTotal: Double? = nil
}

struct WeekPoint: Identifiable, Codable { var id = UUID(); var label: String; var value: Int }

/// 未平持仓精简视图(复盘展示"还有 N 只在持",不计入本周纪律率)。
struct OpenHolding: Identifiable, Codable {
    var id = UUID()
    var name: String; var code: String
    var buyPrice: Double
    var tradeDay: Int                // 持仓交易日 D 几(后端 count_holding_trade_days)
}

struct ReviewTrade: Identifiable, Codable {
    var id = UUID()
    var name: String; var code: String
    var pnl: String
    var tag: ReviewTag               // 肯定 / 标红
    var comment: String
    /// v1.3.0 Phase D1:净收益金额(元,可空;旧行 nil → 展示"—")。
    var netPnlAmount: Double? = nil
}
enum ReviewTag: String, Codable { case good, red }

// MARK: - memory(闭环结论 / 长期记忆 / 纪律里程碑)

struct MemoryItem: Identifiable, Codable {
    var id = UUID()
    var kind: MemoryKind
    var content: String
    var date: String
}
enum MemoryKind: String, Codable {
    case conclusion = "闭环结论"
    case longTerm   = "长期记忆"
    case milestone  = "纪律里程碑"
}

// MARK: - Candidate(EOD 候选;不落 positions,选中才深析)

struct Candidate: Identifiable, Codable {
    var id = UUID()
    var rank: Int
    var name: String; var code: String
    var sector: String; var tag: String
    var price: Double; var chg: String
    var volMultiple: String          // 放量倍数 "2.8x"
    var volPct: Int                  // 进度条 0–100(≥80 用绿)
    var flow: String                 // 主力净流入
    var turnover: String             // 换手
    var warn: String?                // 高位警告降级(非空则降级展示)
    var score: Int? = nil            // 阶段3.1:当日候选池相对分 0–100(展示;可选,前向兼容旧后端)
    /// v1.3.1 A3:warn 分级("high"/"amber"/nil,前向兼容旧后端)。展示走此字段派生红/琥珀,
    /// 绝不字符串解析 warn 文案判级(CLAUDE.md 红线)。
    var warnLevel: String? = nil
    var analysis: DeepAnalysis
}

// MARK: - DeepSeek 结构化深析

struct DeepAnalysis: Codable {
    var form: AnalysisAxis           // ①形态面
    var fund: AnalysisAxis           // ②资金面
    var news: AnalysisAxis           // ③消息面/排雷
    var verdict: Verdict             // 可进 / 观望 / 不进
    var plan: String                 // 进场计划 / 止损
}
struct AnalysisAxis: Codable {
    var value: String                // "强" / "确认" / "无雷" …
    var tone: AxisTone               // 着色
    var text: String
}
enum AxisTone: String, Codable { case good, warn, bad, neutral }
enum Verdict: String, Codable {
    case enter = "可进"
    case watch = "观望"
    case avoid = "不进"
}

// MARK: - 对话消息

enum ChatRole: String, Codable { case user, assistant, analysis, coach }
struct ChatMessage: Identifiable, Codable {
    var id = UUID()
    var role: ChatRole
    var text: String = ""
    var analysis: DeepAnalysis? = nil   // role == .analysis 时
}

// MARK: - v1.3.1 Phase B3:选股配置(GET/PUT /api/v1/screen/config;21 键扁平单层)

/// 选股配置扁平字典(21 键=9 权重+12 阈值,与后端 `SCREEN_CONFIG_SPEC` 键名逐字对齐)。
/// 用 `[String: Double]` 承载(建议#形状之一):字段随后端迭代增删时前向兼容——
/// 缺键的键在 UI 侧用 `ScreenConfigSpec.defaults` 兜底,不因新增/缺失键崩解码。
/// `active_lookback_days` 后端是 int,JSON 数字层面用 Double 解码不失真(展示时四舍五入)。
typealias ScreenConfig = [String: Double]

/// 键注册表(键名 / 中文标签 / 类别 / 客户端侧滑块步进范围)。范围仅供 UI 交互参考——
/// 真正的越界夹紧在后端 `validate_screen_config` 做,客户端范围只是不让用户瞎拖到离谱值,
/// 提交后仍以后端回填的夹紧值为准(不本地假装夹紧)。
enum ScreenConfigCategory: String { case weight, threshold }

struct ScreenConfigField {
    let key: String
    let label: String
    let category: ScreenConfigCategory
    let range: ClosedRange<Double>
    let step: Double
    let isInteger: Bool
    let unit: String   // 展示后缀,如 "%"/"亿"/"天"/""
}

/// 21 键顺序与展示分组,对齐后端 `SCREEN_CONFIG_SPEC`(plan §4 Phase B config 形状表)。
enum ScreenConfigSpec {
    static let weightFields: [ScreenConfigField] = [
        .init(key: "vol_ratio", label: "量比", category: .weight, range: 0...1, step: 0.01, isInteger: false, unit: ""),
        .init(key: "pos_health", label: "位置健康(距高点)", category: .weight, range: 0...1, step: 0.01, isInteger: false, unit: ""),
        .init(key: "turnover", label: "换手健康", category: .weight, range: 0...1, step: 0.01, isInteger: false, unit: ""),
        .init(key: "vwap", label: "站 VWAP", category: .weight, range: 0...1, step: 0.01, isInteger: false, unit: ""),
        .init(key: "breakout", label: "横盘突破", category: .weight, range: 0...1, step: 0.01, isInteger: false, unit: ""),
        .init(key: "mv_elastic", label: "市值弹性", category: .weight, range: 0...1, step: 0.01, isInteger: false, unit: ""),
        .init(key: "active", label: "近期活跃", category: .weight, range: 0...1, step: 0.01, isInteger: false, unit: ""),
        .init(key: "fund", label: "资金面", category: .weight, range: 0...1, step: 0.01, isInteger: false, unit: ""),
        .init(key: "day_surge", label: "单日软闸(罚项)", category: .weight, range: -1...0, step: 0.01, isInteger: false, unit: ""),
    ]

    /// 正权 8 项(day_surge 是负权罚项,不参与"权重之和"提示)。
    static let positiveWeightKeys: [String] = weightFields.filter { $0.key != "day_surge" }.map(\.key)

    static let thresholdFields: [ScreenConfigField] = [
        .init(key: "vol_ratio_min", label: "量比下限", category: .threshold, range: 1...5, step: 0.1, isInteger: false, unit: ""),
        .init(key: "turnover_lo", label: "换手健康带下限", category: .threshold, range: 0...50, step: 0.5, isInteger: false, unit: "%"),
        .init(key: "turnover_hi", label: "换手健康带上限", category: .threshold, range: 0...50, step: 0.5, isInteger: false, unit: "%"),
        .init(key: "mv_lo", label: "市值弹性带下限", category: .threshold, range: 0...2000, step: 5, isInteger: false, unit: "亿"),
        .init(key: "mv_hi", label: "市值弹性带上限", category: .threshold, range: 0...2000, step: 5, isInteger: false, unit: "亿"),
        .init(key: "mv_mega_ceil", label: "市值衰减上限(亿)", category: .threshold, range: 500...5000, step: 50, isInteger: false, unit: "亿"),
        .init(key: "mv_floor", label: "市值微盘 floor", category: .threshold, range: 0...2000, step: 5, isInteger: false, unit: "亿"),
        .init(key: "breakout_range_max", label: "横盘振幅上限", category: .threshold, range: 0...1, step: 0.01, isInteger: false, unit: ""),
        .init(key: "breakout_vol_ratio_min", label: "突破量比下限", category: .threshold, range: 1...5, step: 0.1, isInteger: false, unit: ""),
        .init(key: "day_outflow_floor", label: "单日主力出货下限", category: .threshold, range: -20000...0, step: 100, isInteger: false, unit: "万"),
        .init(key: "day_surge_warn_pct", label: "单日软闸阈", category: .threshold, range: 0...20, step: 0.5, isInteger: false, unit: "%"),
        .init(key: "active_lookback_days", label: "活跃回看天数", category: .threshold, range: 1...60, step: 1, isInteger: true, unit: "天"),
        .init(key: "limit_up_pct", label: "涨停判定阈", category: .threshold, range: 0...20, step: 0.1, isInteger: false, unit: "%"),
    ]

    static let allFields: [ScreenConfigField] = weightFields + thresholdFields
}

// MARK: - 交易日历原语(对齐 PROJECT_PLAN Phase 0.5;持仓天数靠它按需算)
//
//   count_holding_trade_days(buyDate, today): 闭区间[buyDate,today]内交易日个数,买入日 = 1
//   shouldForceClose: 当且仅当 count == 4(D4 强平);可卖日 = D2/D3(D1 因 T+1 不可卖)
//
protocol TradingCalendar {
    func isTradingDay(_ date: Date) -> Bool
    func nextTradingDay(_ date: Date) -> Date
    func prevTradingDay(_ date: Date) -> Date
    func countHoldingTradeDays(buyDate: Date, today: Date) -> Int
    func shouldForceClose(buyDate: Date, today: Date) -> Bool   // == (count == 4)
}
