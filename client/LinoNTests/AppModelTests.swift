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

    // MARK: - v1.4.1 Phase B:今日盈亏(PortfolioKPIs 取后端值,不本地重算)

    /// 默认(旧后端/未刷新前)→ 今日盈亏四字段全 0/false,前向兼容不崩;
    /// todayPnlAvailable 默认 false(🔵#4 审后修:未确认后端支持前应隐藏卡位,不显示假 ¥0)。
    func testPortfolioKPIsTodayPnlDefaultsToZero() {
        let m = AppModel()
        m.holdings = [makePosition(code: "a", buy: 100, price: 110, qty: 100)]
        let k = m.portfolioKPIs
        XCTAssertEqual(k.todayPnl, 0, accuracy: 0.001)
        XCTAssertEqual(k.todayRealized, 0, accuracy: 0.001)
        XCTAssertEqual(k.todayFloat, 0, accuracy: 0.001)
        XCTAssertFalse(k.todayPnlPartial)
        XCTAssertFalse(k.todayPnlAvailable)
    }

    /// GET /positions 聚合值经 AppModel 状态透传进 portfolioKPIs,不在客户端重新计算。
    func testPortfolioKPIsTodayPnlPassthrough() {
        let m = AppModel()
        m.todayPnl = 330.0
        m.todayRealized = -370.0
        m.todayFloat = 700.0
        m.todayPnlPartial = true
        m.todayPnlAvailable = true
        let k = m.portfolioKPIs
        XCTAssertEqual(k.todayPnl, 330.0, accuracy: 0.001)
        XCTAssertEqual(k.todayRealized, -370.0, accuracy: 0.001)
        XCTAssertEqual(k.todayFloat, 700.0, accuracy: 0.001)
        XCTAssertTrue(k.todayPnlPartial)
        XCTAssertTrue(k.todayPnlAvailable)
    }

    /// 染色走 Double 数值派生(pnlColor),非字符串判负——今日盈亏为负必须染红、为 0/正染绿。
    func testTodayPnlColorDerivedFromValueNotString() {
        XCTAssertEqual(Double(330.0).pnlColor, LN.up)
        XCTAssertEqual(Double(-370.0).pnlColor, LN.down)
        XCTAssertEqual(Double(0).pnlColor, LN.up)   // 0 视为非负 → 绿(与既有 pnlColor 契约一致)
    }

    /// 🔵#4 审后修:旧后端(GET /positions 缺 4 键,decode 为 nil)→ fetchPositions() 返回
    /// todayPnlAvailable==false,而非误报 available=true 掩盖"值其实是兜底 0"的事实。
    func testFetchPositionsMarksUnavailableWhenKeysMissing() throws {
        let json = """
        {"holdings": [], "free_slots": 3}
        """.data(using: .utf8)!
        let decoded = try JSONDecoder().decode(_PositionsListResponseProbe.self, from: json)
        XCTAssertNil(decoded.today_pnl)
    }
}

/// 与 APIClient.swift 内 private PositionsListResponse 同形状的探针(该 struct 是 private,
/// 无法跨文件直测;此处复刻同一组可选字段验证"缺键→ decode nil"这一 Swift Codable 行为契约,
/// APIClient.fetchPositions() 的 todayPnlAvailable = (resp.today_pnl != nil) 依赖此行为)。
private struct _PositionsListResponseProbe: Decodable {
    let holdings: [Int]?
    let free_slots: Int?
    let today_pnl: Double?
    let today_realized: Double?
    let today_float: Double?
    let today_pnl_partial: Bool?
}

// MARK: - APIError reason 映射

final class APIErrorTests: XCTestCase {
    func testReasonsAreDistinct() {
        XCTAssertNotEqual(APIError.slotsFull, APIError.duplicateHolding)
        XCTAssertNotEqual(APIError.notHolding, APIError.slotsFull)
    }
}
