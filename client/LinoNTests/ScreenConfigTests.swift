//
//  ScreenConfigTests.swift
//  LinoN — v1.3.1 Phase B3:客户端选股配置调参屏单测
//
//  覆盖:ScreenConfigSpec 键集完整性(21 键=9 权重+12 阈值,与后端 SCREEN_CONFIG_SPEC 对齐)、
//  GET/PUT 响应 DTO 编解码(camelCase 扁平 dict)、AppModel 正权和派生、恢复默认语义
//  (PUT 空 dict)、保存后不自动刷新候选(产品决策)。
//

import XCTest
@testable import LinoN

// MARK: - ScreenConfigSpec 键集完整性

final class ScreenConfigSpecTests: XCTestCase {

    /// 21 键 = 9 权重 + 12 阈值,键名与后端 SCREEN_CONFIG_SPEC 逐字对齐(plan §4 config 形状表)。
    func testAllFieldsCountIs21() {
        XCTAssertEqual(ScreenConfigSpec.weightFields.count, 9)
        XCTAssertEqual(ScreenConfigSpec.thresholdFields.count, 12)
        XCTAssertEqual(ScreenConfigSpec.allFields.count, 21)
    }

    func testWeightKeysMatchBackendSpec() {
        let keys = Set(ScreenConfigSpec.weightFields.map(\.key))
        XCTAssertEqual(keys, ["vol_ratio", "pos_health", "turnover", "vwap", "breakout",
                              "mv_elastic", "active", "fund", "day_surge"])
    }

    func testThresholdKeysMatchBackendSpec() {
        let keys = Set(ScreenConfigSpec.thresholdFields.map(\.key))
        XCTAssertEqual(keys, ["vol_ratio_min", "turnover_lo", "turnover_hi", "mv_lo", "mv_hi",
                              "mv_floor", "breakout_range_max", "breakout_vol_ratio_min",
                              "day_outflow_floor", "day_surge_warn_pct",
                              "active_lookback_days", "limit_up_pct"])
    }

    /// day_surge 是负权罚项,不进"正权之和"提示——positiveWeightKeys 应只有 8 项。
    func testPositiveWeightKeysExcludesDaySurge() {
        XCTAssertEqual(ScreenConfigSpec.positiveWeightKeys.count, 8)
        XCTAssertFalse(ScreenConfigSpec.positiveWeightKeys.contains("day_surge"))
    }

    /// day_surge 范围是 [-1,0](罚项),其余权重 [0,1]。
    func testDaySurgeRangeIsNegative() {
        let daySurge = ScreenConfigSpec.weightFields.first { $0.key == "day_surge" }
        XCTAssertEqual(daySurge?.range, -1...0)
        let others = ScreenConfigSpec.weightFields.filter { $0.key != "day_surge" }
        XCTAssertTrue(others.allSatisfy { $0.range == 0...1 })
    }

    /// active_lookback_days 是唯一整数阈值(后端 type=int)。
    func testActiveLookbackDaysIsIntegerField() {
        let f = ScreenConfigSpec.thresholdFields.first { $0.key == "active_lookback_days" }
        XCTAssertEqual(f?.isInteger, true)
        let nonInt = ScreenConfigSpec.thresholdFields.filter { $0.key != "active_lookback_days" }
        XCTAssertTrue(nonInt.allSatisfy { !$0.isInteger })
    }
}

// MARK: - GET/PUT 响应 DTO 编解码(camelCase 扁平 dict)

final class ScreenConfigDTODecodeTests: XCTestCase {

    func testDecodesGetResponseShape() throws {
        let json = """
        {
          "config": {"vol_ratio": 0.30, "pos_health": 0.16, "day_surge": -0.06,
                     "vol_ratio_min": 1.5, "active_lookback_days": 10},
          "defaults": {"vol_ratio": 0.30, "pos_health": 0.16, "day_surge": -0.06,
                       "vol_ratio_min": 1.5, "active_lookback_days": 10},
          "updated_at": "2026-07-05T10:00:00"
        }
        """.data(using: .utf8)!
        struct Probe: Decodable {
            let config: ScreenConfig
            let defaults: ScreenConfig
            let updated_at: String?
        }
        let p = try JSONDecoder().decode(Probe.self, from: json)
        XCTAssertEqual(p.config["vol_ratio"], 0.30)
        XCTAssertEqual(p.config["day_surge"], -0.06)
        XCTAssertEqual(p.defaults["active_lookback_days"], 10)
        XCTAssertEqual(p.updated_at, "2026-07-05T10:00:00")
    }

    func testDecodesGetResponseWithNullUpdatedAt() throws {
        // 无用户改动过 → updated_at 为 null(未 PUT 过)。
        let json = """
        {"config": {"vol_ratio": 0.30}, "defaults": {"vol_ratio": 0.30}, "updated_at": null}
        """.data(using: .utf8)!
        struct Probe: Decodable {
            let config: ScreenConfig
            let defaults: ScreenConfig
            let updated_at: String?
        }
        let p = try JSONDecoder().decode(Probe.self, from: json)
        XCTAssertNil(p.updated_at)
    }

    func testDecodesPutResponseShape() throws {
        let json = """
        {"ok": true, "config": {"vol_ratio": 0.28, "pos_health": 0.18}}
        """.data(using: .utf8)!
        struct Probe: Decodable { let ok: Bool; let config: ScreenConfig }
        let p = try JSONDecoder().decode(Probe.self, from: json)
        XCTAssertTrue(p.ok)
        XCTAssertEqual(p.config["vol_ratio"], 0.28)
    }

    /// PUT 请求体编码:空 config = 恢复默认语义(body 仍合法 JSON `{"config":{}}`)。
    func testPutBodyEncodesEmptyConfigForRestoreDefault() throws {
        let body = ScreenConfigPutBody(config: [:])
        let data = try JSONEncoder().encode(body)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let cfg = obj?["config"] as? [String: Any]
        XCTAssertNotNil(cfg)
        XCTAssertEqual(cfg?.count, 0)
    }

    func testPutBodyEncodesPartialConfig() throws {
        let body = ScreenConfigPutBody(config: ["vol_ratio_min": 2.0])
        let data = try JSONEncoder().encode(body)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let cfg = obj?["config"] as? [String: Double]
        XCTAssertEqual(cfg?["vol_ratio_min"], 2.0)
    }
}

// MARK: - AppModel 派生 / 状态机(正权和提示、恢复默认回填、不自动刷新候选)

@MainActor
final class ScreenConfigAppModelTests: XCTestCase {

    func testPositiveWeightSumSumsOnlyPositiveKeys() {
        let m = AppModel()
        m.screenConfig = [
            "vol_ratio": 0.30, "pos_health": 0.16, "turnover": 0.14, "vwap": 0.10,
            "breakout": 0.10, "mv_elastic": 0.08, "active": 0.06, "fund": 0.06,
            "day_surge": -0.06,   // 罚项不参与求和
        ]
        XCTAssertEqual(m.screenConfigPositiveWeightSum, 1.0, accuracy: 1e-9)
    }

    func testPositiveWeightSumMissingKeysTreatedAsZero() {
        let m = AppModel()
        m.screenConfig = ["vol_ratio": 0.5]   // 其余 7 项缺 → 视为 0
        XCTAssertEqual(m.screenConfigPositiveWeightSum, 0.5, accuracy: 1e-9)
    }

    /// 空 AppModel(尚未加载)→ 正权和为 0,不崩(UI 会显示提示而非崩溃)。
    func testPositiveWeightSumEmptyConfigIsZero() {
        let m = AppModel()
        XCTAssertEqual(m.screenConfigPositiveWeightSum, 0, accuracy: 1e-9)
    }

    /// 无 clientProvider(未配置后端)→ save/restore 静默失败提示 toast,不崩、不改动 screenConfig。
    func testSaveScreenConfigNoClientShowsToastNotCrash() async {
        let m = AppModel()
        m.screenConfig = ["vol_ratio": 0.5]
        await m.saveScreenConfig()
        XCTAssertNotNil(m.toast)
        XCTAssertEqual(m.screenConfig["vol_ratio"], 0.5)   // 未被清空/篡改
    }

    func testRestoreDefaultNoClientShowsToastNotCrash() async {
        let m = AppModel()
        await m.restoreDefaultScreenConfig()
        XCTAssertNotNil(m.toast)
    }

    /// loadScreenConfig 无 clientProvider → 静默不弹错(降级语义,同 loadReview/loadMemory)。
    func testLoadScreenConfigNoClientSilentNoToast() async {
        let m = AppModel()
        await m.loadScreenConfig()
        XCTAssertNil(m.toast)
        XCTAssertTrue(m.screenConfig.isEmpty)
    }
}
