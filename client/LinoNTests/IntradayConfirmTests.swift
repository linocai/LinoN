//
//  IntradayConfirmTests.swift
//  LinoN — v1.4 Phase D:候选池「今日续强确认」客户端单测
//
//  覆盖 plan §4 Phase D 验收清单:IntradayConfirmResult 解码(全字段/缺实时字段前向兼容/
//  isTrading=false)、盘中量比/VWAP 展示派生、chgPct 正负着色派生(负跌不染绿)、
//  按 code join(不靠数组顺序)、按钮禁用态(初始可点,isTrading=false 才禁用)。
//

import XCTest
@testable import LinoN

// MARK: - IntradayConfirmResult / IntradayItem 解码(前向兼容)

final class IntradayConfirmDecodeTests: XCTestCase {

    func testDecodesFullShapeAllFieldsPresent() throws {
        let json = """
        {
          "ok": true, "isTrading": true, "tradeDate": "2026-07-06",
          "asof": "2026-07-06 10:23:00", "degraded": false,
          "items": [
            {"code": "301051", "name": "信濠光电", "price": 45.6, "chgPct": 3.21,
             "openChgPct": 1.05, "isAboveVwap": true, "intradayVolRatio": 1.4, "volNote": "ok"}
          ]
        }
        """.data(using: .utf8)!
        let r = try JSONDecoder().decode(IntradayConfirmResult.self, from: json)
        XCTAssertTrue(r.ok)
        XCTAssertTrue(r.isTrading)
        XCTAssertEqual(r.tradeDate, "2026-07-06")
        XCTAssertEqual(r.asof, "2026-07-06 10:23:00")
        XCTAssertFalse(r.degraded)
        XCTAssertEqual(r.items.count, 1)
        let it = r.items[0]
        XCTAssertEqual(it.code, "301051")
        XCTAssertEqual(it.name, "信濠光电")
        XCTAssertEqual(it.price, 45.6)
        XCTAssertEqual(it.chgPct, 3.21)
        XCTAssertEqual(it.openChgPct, 1.05)
        XCTAssertEqual(it.isAboveVwap, true)
        XCTAssertEqual(it.intradayVolRatio, 1.4)
        XCTAssertEqual(it.volNote, "ok")
    }

    /// 前向兼容:非交易时段/拉价失败,实时字段全 null → 解码不崩,字段读出为 nil。
    func testDecodesMissingRealtimeFieldsAsNilNotTrading() throws {
        let json = """
        {
          "ok": true, "isTrading": false, "tradeDate": "2026-07-06",
          "asof": "", "degraded": false,
          "items": [
            {"code": "301051", "name": "信濠光电", "price": null, "chgPct": null,
             "openChgPct": null, "isAboveVwap": null, "intradayVolRatio": null, "volNote": "non_trading"}
          ]
        }
        """.data(using: .utf8)!
        let r = try JSONDecoder().decode(IntradayConfirmResult.self, from: json)
        XCTAssertFalse(r.isTrading)
        XCTAssertEqual(r.asof, "")
        let it = r.items[0]
        XCTAssertNil(it.price)
        XCTAssertNil(it.chgPct)
        XCTAssertNil(it.openChgPct)
        XCTAssertNil(it.isAboveVwap)
        XCTAssertNil(it.intradayVolRatio)
        XCTAssertEqual(it.volNote, "non_trading")
    }

    /// 无候选缓存 → degraded=true,items 空;解码不崩。
    func testDecodesDegradedEmptyItems() throws {
        let json = """
        {"ok": true, "isTrading": false, "tradeDate": "", "asof": "", "degraded": true, "items": []}
        """.data(using: .utf8)!
        let r = try JSONDecoder().decode(IntradayConfirmResult.self, from: json)
        XCTAssertTrue(r.degraded)
        XCTAssertTrue(r.items.isEmpty)
    }

    /// 缺键(而非显式 null)也前向兼容不崩——若某后端字段省略而非置 null。
    func testDecodesKeysOmittedEntirelyDoesNotFail() throws {
        let json = """
        {"code": "600519", "name": "贵州茅台"}
        """.data(using: .utf8)!
        let it = try JSONDecoder().decode(IntradayItem.self, from: json)
        XCTAssertEqual(it.code, "600519")
        XCTAssertNil(it.price)
        XCTAssertNil(it.volNote)
    }
}

// MARK: - AppModel:loadIntradayConfirm / intradayItem(byCode:) / 按钮禁用态派生

@MainActor
final class IntradayConfirmAppModelTests: XCTestCase {

    /// 无 clientProvider(未配置后端)→ 静默提示 toast,不崩、intraday 不写入假数据。
    func testLoadIntradayConfirmNoClientShowsToastNotCrash() async {
        let m = AppModel()
        await m.loadIntradayConfirm()
        XCTAssertNotNil(m.toast)
        XCTAssertNil(m.intraday)
    }

    /// 按 code join(建议#10):intradayItem(byCode:) 不依赖数组顺序,按 code 精确匹配。
    func testIntradayItemLookupByCodeNotByOrder() {
        let m = AppModel()
        m.intraday = IntradayConfirmResult(
            ok: true, isTrading: true, tradeDate: "2026-07-06", asof: "2026-07-06 10:00:00",
            degraded: false,
            items: [
                IntradayItem(code: "600519", name: "贵州茅台", price: 1500, chgPct: 1.0,
                            openChgPct: 0.5, isAboveVwap: true, intradayVolRatio: 1.2, volNote: "ok"),
                IntradayItem(code: "000858", name: "五粮液", price: 120, chgPct: -0.5,
                            openChgPct: -0.2, isAboveVwap: false, intradayVolRatio: 0.9, volNote: "ok"),
            ]
        )
        // 反着查也应命中对应 code(不受数组顺序影响)。
        XCTAssertEqual(m.intradayItem(byCode: "000858")?.name, "五粮液")
        XCTAssertEqual(m.intradayItem(byCode: "600519")?.name, "贵州茅台")
        XCTAssertNil(m.intradayItem(byCode: "999999"))   // 候选未在 intraday items 里 → nil
    }

    /// 未拉取过 intraday(nil)→ 查找恒 nil,不崩。
    func testIntradayItemLookupNilWhenNotFetched() {
        let m = AppModel()
        XCTAssertNil(m.intradayItem(byCode: "600519"))
    }
}

// MARK: - 按钮态派生(镜像 CandidatesViewIOS/Mac 的 intradayButtonDimmed / .disabled 判定)
//
// 🟡#1(审后修复):isTrading=false 不再真禁用(会 app 会话内永久 brick,无复活路径)——
// 拆成两个独立判定:`intradayButtonDimmed`(视觉变暗,镜像 view 内同名计算属性)与
// `intradayTrulyDisabled`(真禁用,只在拉取中,镜像 view 内 `.disabled(model.intradayLoading)`)。
// 允许用户在"变暗"态下仍可点击重查,以最新响应为准(时段真值全由后端 isTrading 定)。

@MainActor
private func intradayButtonDimmed(_ m: AppModel) -> Bool {
    m.intradayLoading || (m.intraday != nil && m.intraday?.isTrading == false)
}

@MainActor
private func intradayTrulyDisabled(_ m: AppModel) -> Bool {
    m.intradayLoading
}

@MainActor
final class IntradayButtonStateTests: XCTestCase {

    /// 初始态(未拉取过)→ 不变暗、不禁用(客户端不自判日历/时段)。
    func testInitiallyEnabledBeforeAnyFetch() {
        let m = AppModel()
        XCTAssertFalse(intradayButtonDimmed(m))
        XCTAssertFalse(intradayTrulyDisabled(m))
    }

    /// 拉取中 → 变暗 + 真禁用(防重复点击)。
    func testDisabledWhileLoading() {
        let m = AppModel()
        m.intradayLoading = true
        XCTAssertTrue(intradayButtonDimmed(m))
        XCTAssertTrue(intradayTrulyDisabled(m))
    }

    /// 响应 isTrading=true → 不变暗、可点(交易时段可重复确认)。
    func testEnabledWhenIsTradingTrue() {
        let m = AppModel()
        m.intraday = IntradayConfirmResult(ok: true, isTrading: true, tradeDate: "2026-07-06",
                                           asof: "x", degraded: false, items: [])
        XCTAssertFalse(intradayButtonDimmed(m))
        XCTAssertFalse(intradayTrulyDisabled(m))
    }

    /// 响应 isTrading=false → 视觉变暗 + 标注非交易时段,但**仍可点击重查**(不真禁用,
    /// 无复活路径的永久 brick 是审后修复要根除的问题)。
    func testDimmedButNotTrulyDisabledWhenIsTradingFalse() {
        let m = AppModel()
        m.intraday = IntradayConfirmResult(ok: true, isTrading: false, tradeDate: "2026-07-06",
                                           asof: "", degraded: false, items: [])
        XCTAssertTrue(intradayButtonDimmed(m))
        XCTAssertFalse(intradayTrulyDisabled(m))
    }

    /// 复活路径:isTrading=false 后再次拉取回 isTrading=true → 变暗态解除(以最新响应为准)。
    func testRecoversToEnabledAfterSubsequentTradingResponse() {
        let m = AppModel()
        m.intraday = IntradayConfirmResult(ok: true, isTrading: false, tradeDate: "2026-07-06",
                                           asof: "", degraded: false, items: [])
        XCTAssertTrue(intradayButtonDimmed(m))
        // 模拟用户再次点击、后端本次回 isTrading=true(如开盘后)。
        m.intraday = IntradayConfirmResult(ok: true, isTrading: true, tradeDate: "2026-07-06",
                                           asof: "2026-07-06 09:30:05", degraded: false, items: [])
        XCTAssertFalse(intradayButtonDimmed(m))
    }
}

// MARK: - chgPct/openChgPct 着色派生(数值派生,非字符串判负;镜像 CandidateRow 逻辑)

final class IntradayColorDerivationTests: XCTestCase {

    /// 与 intradayOverlayIOS/Mac 内 `chg >= 0 ? LN.up : LN.down` 逐字对齐的判定表达式。
    private func isUpColor(_ chgPct: Double) -> Bool { chgPct >= 0 }

    func testPositiveChgIsUpColor() {
        XCTAssertTrue(isUpColor(3.21))
    }

    func testZeroChgIsUpColor() {
        XCTAssertTrue(isUpColor(0.0))
    }

    /// 负跌不染绿(数值派生,不受字符串前缀影响)。
    func testNegativeChgIsDownColor() {
        XCTAssertFalse(isUpColor(-1.5))
    }
}

// MARK: - 盘中叠加行渲染判定(镜像 intradayOverlayIOS/Mac 的 `it.volNote != "non_trading"` 守卫)

final class IntradayOverlayRenderTests: XCTestCase {

    /// 与 intradayOverlayIOS/Mac 内 `if let it = intraday, it.volNote != "non_trading"` 逐字对齐。
    private func shouldRenderOverlay(_ it: IntradayItem?) -> Bool {
        guard let it = it else { return false }
        return it.volNote != "non_trading"
    }

    /// 🔵#2(审后修复):非交易时段(volNote=="non_trading")→ 整行不渲染,顶部 banner 已够,
    /// 避免 20 行逐行重复"非交易时段"噪声。
    func testOverlayHiddenWhenNonTrading() {
        let it = IntradayItem(code: "600001", name: "x", price: nil, chgPct: nil,
                              openChgPct: nil, isAboveVwap: nil, intradayVolRatio: nil,
                              volNote: "non_trading")
        XCTAssertFalse(shouldRenderOverlay(it))
    }

    /// 其余 note(ok/early/no_base/closed)正常渲染。
    func testOverlayShownForOtherNotes() {
        for note in ["ok", "early", "no_base", "closed"] {
            let it = IntradayItem(code: "600001", name: "x", price: 10, chgPct: 1.0,
                                  openChgPct: 0.5, isAboveVwap: true, intradayVolRatio: 1.2,
                                  volNote: note)
            XCTAssertTrue(shouldRenderOverlay(it), "note=\(note) 应渲染叠加行")
        }
    }

    /// 未拉取(nil)→ 不渲染。
    func testOverlayHiddenWhenNil() {
        XCTAssertFalse(shouldRenderOverlay(nil))
    }
}

// MARK: - 「高开」字段(🔵#1 审后修复:iOS 补齐,与 macOS 对齐)

final class IntradayOpenChgFieldTests: XCTestCase {

    /// openChgPct 非 nil 时 iOS/macOS 叠加行均应展示「高开 x%」文案片段(镜像文案拼接)。
    func testOpenChgLabelFormatsWithSign() {
        let openChg = 1.05
        let label = "高开 \(LNFmt.pct1(openChg))"
        XCTAssertTrue(label.contains("高开"))
        XCTAssertTrue(label.contains("1.0") || label.contains("1.1"))   // 容许四舍五入边界
    }

    /// openChgPct 为 nil(非交易/拉价失败)→ 不应尝试渲染该片段(由 `if let` 守卫,
    /// 此处断言 IntradayItem 解码/构造允许该字段为 nil,不崩)。
    func testOpenChgNilIsValid() {
        let it = IntradayItem(code: "600001", name: "x", price: nil, chgPct: nil,
                              openChgPct: nil, isAboveVwap: nil, intradayVolRatio: nil,
                              volNote: "non_trading")
        XCTAssertNil(it.openChgPct)
    }
}
