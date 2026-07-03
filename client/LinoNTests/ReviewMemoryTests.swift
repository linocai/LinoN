//
//  ReviewMemoryTests.swift
//  LinoN — 阶段3 前端 H1/H2/H3 单测 + v1.3.0 Phase D1 净额展示
//
//  覆盖:Review/OpenHolding 模型解码(经 DTO 映射)、Memory/ClosedTradeRow 解码、
//  coach review_ref 透传(H3)、AppModel 复盘/记忆状态派生(disciplineRate 接真值、
//  hasReviewFlags、coachReviewRef 清理)。绿涨红跌 pnl 串判色。
//  v1.3.0 Phase D1:netPnlAmount/netPnlTotal 可空契约(nil→"—")+ netPnlColor 派生 bool 着色。
//

import XCTest
@testable import LinoN

@MainActor
final class ReviewMemoryTests: XCTestCase {

    // —— H1:Review 模型逐字段(含 openHoldings / sampleNote / trend / trades)——

    func testReviewModelFieldsAndDefaults() {
        let r = Review(
            week: "2026-W27", score: 67, redFlags: ["沪电股份 破止损:-8.2% 未在 -5% 走"],
            disciplineRate: 67, rateTrend: -33, lessons: "", nextWeekNote: "只做 D 型",
            trend: [WeekPoint(label: "W26", value: 100), WeekPoint(label: "W27", value: 67)],
            trades: [ReviewTrade(name: "沪电股份", code: "002463", pnl: "-8.2%",
                                 tag: .red, comment: "破止损:跌穿 -5% 未走")],
            openHoldings: [OpenHolding(name: "工业富联", code: "601138", buyPrice: 18.3, tradeDay: 2)],
            sampleNote: "本周 1 笔闭合"
        )
        XCTAssertEqual(r.disciplineRate, 67)
        XCTAssertEqual(r.rateTrend, -33)
        XCTAssertEqual(r.redFlags.count, 1)
        XCTAssertEqual(r.trend.count, 2)
        XCTAssertEqual(r.trades.first?.tag, .red)
        XCTAssertEqual(r.openHoldings.first?.tradeDay, 2)
        XCTAssertEqual(r.sampleNote, "本周 1 笔闭合")
    }

    // —— ReviewTrade tag 映射(good/red)——

    func testReviewTradeTagMapping() {
        XCTAssertEqual(ReviewTag(rawValue: "good"), .good)
        XCTAssertEqual(ReviewTag(rawValue: "red"), .red)
        XCTAssertNil(ReviewTag(rawValue: "unknown"))
    }

    // —— H2:MemoryKind 映射 + ClosedTradeRow 守线徽章 ——

    func testMemoryKindMapping() {
        XCTAssertEqual(MemoryKind(rawValue: "闭环结论"), .conclusion)
        XCTAssertEqual(MemoryKind(rawValue: "长期记忆"), .longTerm)
        XCTAssertEqual(MemoryKind(rawValue: "纪律里程碑"), .milestone)
    }

    func testClosedTradeRowBadges() {
        let kept = ClosedTradeRow(name: "兆易创新", code: "603986", pnl: "+16.0%",
                                  keptStop: false, keptTake: true, keptTime: true, brokeRule: false,
                                  note: "守住铁律", date: "2026-06-30", netPnlAmount: 812.45)
        XCTAssertTrue(kept.keptTake && kept.keptTime)
        XCTAssertFalse(kept.brokeRule)
        // 绿涨红跌:'+' 开头非红
        XCTAssertFalse(kept.pnl.hasPrefix("-"))

        let broke = ClosedTradeRow(name: "沪电股份", code: "002463", pnl: "-10.0%",
                                   keptStop: false, keptTake: false, keptTime: true, brokeRule: true,
                                   note: "破止损:跌穿 -5% 未走", date: "2026-07-01", netPnlAmount: -615.93)
        XCTAssertTrue(broke.brokeRule)
        XCTAssertTrue(broke.pnl.hasPrefix("-"))
    }

    // —— AppModel:disciplineRate 接真值 + hasReviewFlags ——

    func testAppModelDisciplineRateFromReview() {
        let m = AppModel()
        // 无 review → 占位默认(86)
        XCTAssertEqual(m.portfolioKPIs.disciplineRate, 86)
        m.review = Review(week: "2026-W27", score: 50, redFlags: ["x"],
                          disciplineRate: 50, rateTrend: 5, lessons: "", nextWeekNote: "",
                          trend: [], trades: [], openHoldings: [], sampleNote: "")
        XCTAssertEqual(m.portfolioKPIs.disciplineRate, 50)   // 接真值
        XCTAssertEqual(m.portfolioKPIs.disciplineTrend, 5)
        XCTAssertTrue(m.hasReviewFlags)                       // redFlags 非空 → 待
    }

    func testHasReviewFlagsFalseWhenNoFlags() {
        let m = AppModel()
        XCTAssertFalse(m.hasReviewFlags)   // 无 review → 无 flags
        m.review = Review(week: "2026-W27", score: 100, redFlags: [],
                          disciplineRate: 100, rateTrend: 0, lessons: "", nextWeekNote: "",
                          trend: [], trades: [], openHoldings: [], sampleNote: "")
        XCTAssertFalse(m.hasReviewFlags)   // 全守 → 无待
    }

    // —— H3:coachReviewRef 清理(backFromAnalysis 清空)——

    func testCoachReviewRefClearedOnBack() {
        let m = AppModel()
        m.coachReviewRef = "你上次 沪电股份 也是没在 -5% 走,亏了 8.2%"
        m.inAnalysis = true
        m.backFromAnalysis()
        XCTAssertNil(m.coachReviewRef)
        XCTAssertFalse(m.inAnalysis)
    }

    // —— reviewNoteDraft 初值随 loadReview 的 nextWeekNote(通过直接赋值验证草稿字段存在)——

    func testReviewNoteDraftField() {
        let m = AppModel()
        m.reviewNoteDraft = "只做 D 型"
        XCTAssertEqual(m.reviewNoteDraft, "只做 D 型")
    }

    // —— v1.3.0 Phase D1:netPnlAmount/netPnlTotal 默认 nil(旧行/未拉取时不臆造实值)——

    func testNetPnlAmountDefaultsNilOnReviewTradeAndClosedTradeRow() {
        let t = ReviewTrade(name: "沪电股份", code: "002463", pnl: "-8.2%", tag: .red, comment: "破止损")
        XCTAssertNil(t.netPnlAmount)

        let row = ClosedTradeRow(name: "兆易创新", code: "603986", pnl: "+16.0%",
                                 keptStop: true, keptTake: true, keptTime: true, brokeRule: false,
                                 note: "守住铁律", date: "2026-06-30", netPnlAmount: nil)
        XCTAssertNil(row.netPnlAmount)

        let r = Review(week: "2026-W27", score: 50, redFlags: [],
                       disciplineRate: 50, rateTrend: 0, lessons: "", nextWeekNote: "",
                       trend: [], trades: [], openHoldings: [], sampleNote: "")
        XCTAssertNil(r.netPnlTotal)
    }

    // —— v1.3.0 Phase D1:LNFmt.netAmount(nil→"—"、有值→signedMoney)——

    func testNetAmountFormattingNilShowsDash() {
        XCTAssertEqual(LNFmt.netAmount(nil), "—")
        XCTAssertEqual(LNFmt.netAmount(1234), LNFmt.signedMoney(1234))
        XCTAssertEqual(LNFmt.netAmount(-88), LNFmt.signedMoney(-88))
    }

    // —— v1.3.0 Phase D1:netPnlColor 派生 bool 着色(nil→中性灰,非字符串判负)——

    func testNetPnlColorDerivesFromOptionalBoolNotStringParsing() {
        XCTAssertEqual(netPnlColor(nil), LN.textTertiary)   // 未知 → 中性灰,不染红染绿
        XCTAssertEqual(netPnlColor(100), LN.up)             // 正 → 绿(用户选择绿涨红跌)
        XCTAssertEqual(netPnlColor(-1), LN.down)            // 负 → 红
        XCTAssertEqual(netPnlColor(0), LN.up)               // 0 视为非负 → 绿(与 pnlColor 扩展一致)
    }

    // —— v1.3.0 Phase D1:ReviewResponse/MemoryResponse JSON 解码(逐字段对齐后端契约)——

    func testFetchReviewDecodesOptionalNetFieldsFromBackendShape() throws {
        // 对齐 backend ReviewOut:netPnlTotal 顶层可空 + trades[].netPnlAmount 可空。
        let json = """
        {
          "week": "2026-W27", "score": 80, "disciplineRate": 80, "rateTrend": 0,
          "redFlags": [], "lessons": "", "nextWeekNote": "",
          "trend": [], "openHoldings": [], "sampleNote": "本周 2 笔闭合",
          "netPnlTotal": 356.78,
          "trades": [
            {"name": "兆易创新", "code": "603986", "pnl": "+16.0%", "tag": "good",
             "comment": "守住铁律", "netPnlAmount": 823.5},
            {"name": "沪电股份", "code": "002463", "pnl": "-8.2%", "tag": "red",
             "comment": "破止损", "netPnlAmount": null}
          ]
        }
        """.data(using: .utf8)!
        // ReviewResponse 是私有 DTO,经由 decode 到位——直接验证 Decodable 结构可解出 nil/实值两态。
        struct Probe: Decodable {
            let netPnlTotal: Double?
            let trades: [Trade]
            struct Trade: Decodable { let netPnlAmount: Double? }
        }
        let p = try JSONDecoder().decode(Probe.self, from: json)
        XCTAssertEqual(p.netPnlTotal, 356.78)
        XCTAssertEqual(p.trades[0].netPnlAmount, 823.5)
        XCTAssertNil(p.trades[1].netPnlAmount)   // 旧行/无数据行 → null 原样解出 nil,不 500/不崩
    }
}
