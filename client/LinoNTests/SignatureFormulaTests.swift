//
//  SignatureFormulaTests.swift
//  LinoN — 签名组件公式 + 派生 + 日历契约单测(§4b 钉死值)
//

import XCTest
@testable import LinoN

final class SignatureFormulaTests: XCTestCase {

    // MARK: - DualLineTrack marker:x% = clamp((pnlPct+5)/20*100, 2, 98)

    /// 用 Models.swift 的 trackX(0…100)与设计公式逐点核对。
    private func trackX(_ pnlPct: Double) -> Double {
        var p = Position(id: 0, code: "x", name: "x", buyPrice: 100, qty: 1,
                         entryReason: "x", entrySnapshot: nil, buyDate: Date())
        // 反推 price 使 pnlPct 成立:price = buy*(1+pnl/100)
        p.price = 100 * (1 + pnlPct / 100)
        return p.trackX
    }

    func testMarkerAtStopLoss() {
        // pnl = -5 → x = 2
        XCTAssertEqual(trackX(-5), 2, accuracy: 0.001)
    }

    func testMarkerAtCost() {
        // pnl = 0 → x = 25
        XCTAssertEqual(trackX(0), 25, accuracy: 0.001)
    }

    func testMarkerAtTakeProfit() {
        // pnl = +15 → 设计稿 100%,但 Models.swift(契约)marker 钳到 98。
        // DualLineTrack 组件同样 min(0.98,…),与契约一致(不改契约)。
        XCTAssertEqual(trackX(15), 98, accuracy: 0.001)
    }

    func testMarkerClampLowerBound() {
        // pnl 远低于 -5 → 钳到 2
        XCTAssertEqual(trackX(-50), 2, accuracy: 0.001)
    }

    func testMarkerClampUpperBound() {
        // pnl 远高于 +15 → 钳到 98
        XCTAssertEqual(trackX(40), 98, accuracy: 0.001)
    }

    func testMarkerMidpoint() {
        // pnl = +5 → (5+5)/20*100 = 50
        XCTAssertEqual(trackX(5), 50, accuracy: 0.001)
    }

    // MARK: - hitStop 触发(展示阈 -4.9)

    func testHitStopThreshold() {
        var p = Position(id: 0, code: "x", name: "x", buyPrice: 100, qty: 1,
                         entryReason: "x", entrySnapshot: nil, buyDate: Date())
        p.price = 95.1   // pnl = -4.9
        XCTAssertTrue(p.hitStop)
        p.price = 95.2   // pnl = -4.8
        XCTAssertFalse(p.hitStop)
    }

    // MARK: - 止损/止盈线派生(×0.95 / ×1.15)

    func testStopAndTakeLine() {
        let p = Position(id: 0, code: "x", name: "x", buyPrice: 48.30, qty: 1,
                         entryReason: "x", entrySnapshot: nil, buyDate: Date())
        // 契约 Models.swift:(buy×ratio×100).rounded()/100。
        XCTAssertEqual(p.stopLine, 45.89, accuracy: 0.001)  // 48.30 × 0.95 = 45.885 → 45.89
        XCTAssertEqual(p.takeLine, 55.54, accuracy: 0.001)  // 48.30 × 1.15 = 55.545(浮点→55.54)
    }

    // MARK: - HoldingDayPips / shouldForceClose == (count == 4)

    func testHoldingDayCountAndForceClose() {
        let cal = StaticTradingCalendar.shared
        // 2026-06-22(周一)是交易日;连续交易日 22(D1)/23(D2)/24(D3)/25(D4)
        let d = { (s: String) in cal.parseDate(s)! }
        XCTAssertEqual(cal.countHoldingTradeDays(buyDate: d("2026-06-22"), today: d("2026-06-22")), 1)
        XCTAssertEqual(cal.countHoldingTradeDays(buyDate: d("2026-06-22"), today: d("2026-06-23")), 2)
        XCTAssertEqual(cal.countHoldingTradeDays(buyDate: d("2026-06-22"), today: d("2026-06-24")), 3)
        XCTAssertEqual(cal.countHoldingTradeDays(buyDate: d("2026-06-22"), today: d("2026-06-25")), 4)
        // D4 强平 == count == 4
        XCTAssertFalse(cal.shouldForceClose(buyDate: d("2026-06-22"), today: d("2026-06-24"))) // D3
        XCTAssertTrue(cal.shouldForceClose(buyDate: d("2026-06-22"), today: d("2026-06-25")))  // D4
    }

    func testWeekendSkippedInCount() {
        let cal = StaticTradingCalendar.shared
        let d = { (s: String) in cal.parseDate(s)! }
        // 2026-06-26 周五(D5),周末 27/28 跳过,29 周一为 D6
        // 买入 6-22 周一,到 6-29 周一:交易日 22,23,24,25,26,29 = 6 个
        XCTAssertEqual(cal.countHoldingTradeDays(buyDate: d("2026-06-22"), today: d("2026-06-29")), 6)
    }

    func testHolidayIsNotTradingDay() {
        let cal = StaticTradingCalendar.shared
        let d = { (s: String) in cal.parseDate(s)! }
        // 2026-10-01 国庆休市
        XCTAssertFalse(cal.isTradingDay(d("2026-10-01")))
        // 2026-09-30 周三为交易日
        XCTAssertTrue(cal.isTradingDay(d("2026-09-30")))
    }
}
