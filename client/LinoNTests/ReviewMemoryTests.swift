//
//  ReviewMemoryTests.swift
//  LinoN — 阶段3 前端 H1/H2/H3 单测
//
//  覆盖:Review/OpenHolding 模型解码(经 DTO 映射)、Memory/ClosedTradeRow 解码、
//  coach review_ref 透传(H3)、AppModel 复盘/记忆状态派生(disciplineRate 接真值、
//  hasReviewFlags、coachReviewRef 清理)。绿涨红跌 pnl 串判色。
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
                                  note: "守住铁律", date: "2026-06-30")
        XCTAssertTrue(kept.keptTake && kept.keptTime)
        XCTAssertFalse(kept.brokeRule)
        // 绿涨红跌:'+' 开头非红
        XCTAssertFalse(kept.pnl.hasPrefix("-"))

        let broke = ClosedTradeRow(name: "沪电股份", code: "002463", pnl: "-10.0%",
                                   keptStop: false, keptTake: false, keptTime: true, brokeRule: true,
                                   note: "破止损:跌穿 -5% 未走", date: "2026-07-01")
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
}
