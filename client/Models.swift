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
