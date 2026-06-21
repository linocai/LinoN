//
//  AppModelTests.swift
//  LinoN — AppModel 派生 KPI + 触损教练横幅触发 + form 止损派生 单测
//

import XCTest
@testable import LinoN

@MainActor
final class AppModelTests: XCTestCase {

    private func makePosition(code: String, buy: Double, price: Double, qty: Int,
                              reason: String = "x") -> Position {
        var p = Position(id: Int.random(in: 1...9999), code: code, name: code,
                         buyPrice: buy, qty: qty, entryReason: reason,
                         entrySnapshot: nil, buyDate: Date())
        p.price = price
        return p
    }

    func testPortfolioKPIs() {
        let m = AppModel()
        m.holdings = [
            makePosition(code: "a", buy: 100, price: 110, qty: 100),  // +1000
            makePosition(code: "b", buy: 50, price: 45, qty: 200),    // -1000
        ]
        let k = m.portfolioKPIs
        XCTAssertEqual(k.marketValue, 110*100 + 45*200, accuracy: 0.001)   // 11000+9000=20000
        XCTAssertEqual(k.floatPnl, 0, accuracy: 0.001)                     // +1000 -1000
        XCTAssertEqual(k.positionCount, 2)
    }

    func testAlertHoldingTriggersOnHitStop() {
        let m = AppModel()
        m.holdings = [
            makePosition(code: "ok", buy: 100, price: 102, qty: 100),
            makePosition(code: "hit", buy: 100, price: 94, qty: 100),  // pnl -6% → hitStop
        ]
        XCTAssertEqual(m.alertHolding?.code, "hit")
    }

    func testNoAlertWhenAllHealthy() {
        let m = AppModel()
        m.holdings = [makePosition(code: "ok", buy: 100, price: 105, qty: 100)]
        XCTAssertNil(m.alertHolding)
    }

    func testFreeSlot() {
        let m = AppModel()
        m.holdings = [makePosition(code: "a", buy: 1, price: 1, qty: 1),
                      makePosition(code: "b", buy: 1, price: 1, qty: 1),
                      makePosition(code: "c", buy: 1, price: 1, qty: 1)]
        XCTAssertFalse(m.hasFreeSlot)
        m.holdings.removeLast()
        XCTAssertTrue(m.hasFreeSlot)
    }

    func testEntryFormDerivedStop() {
        var f = EntryForm()
        f.price = "48.30"
        XCTAssertEqual(f.derivedStop!, 45.89, accuracy: 0.001)  // 拒手填,只读派生
        f.price = ""
        XCTAssertNil(f.derivedStop)
    }
}

// MARK: - APIError reason 映射

final class APIErrorTests: XCTestCase {
    func testReasonsAreDistinct() {
        XCTAssertNotEqual(APIError.slotsFull, APIError.duplicateHolding)
        XCTAssertNotEqual(APIError.notHolding, APIError.slotsFull)
    }
}
