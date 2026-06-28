//
//  SnapshotRenderTests.swift
//  LinoN — E1/E2 离屏快照(ImageRenderer)用于人工核对渲染,不做像素断言。
//
//  在 iOS 模拟器测试宿主跑(client 测试宿主在 iOS Simulator);产物落
//  NSTemporaryDirectory()/linon_snap_*.png,测试日志打印路径供 builder 目检。
//  computer-use 在本机受 Dock 守卫无法点击驱动 UI,以此离屏渲染替代可视核对。
//

import XCTest
import SwiftUI
@testable import LinoN

@MainActor
final class SnapshotRenderTests: XCTestCase {

    private func model(withCandidates: Bool, full: Bool = false) -> AppModel {
        let m = AppModel()
        if full {
            m.holdings = (0..<3).map {
                Position(id: $0, code: "h\($0)", name: "持仓\($0)", buyPrice: 10, qty: 100,
                         entryReason: "x", entrySnapshot: nil, buyDate: Date())
            }
        }
        if withCandidates {
            let g = AnalysisAxis(value: "—", tone: .neutral, text: "")
            let a = DeepAnalysis(form: g, fund: g, news: g, verdict: .watch, plan: "")
            m.candidates = [
                Candidate(rank: 1, name: "东方电缆", code: "603606", sector: "海缆", tag: "低位平台突破",
                          price: 48.30, chg: "+4.20%", volMultiple: "2.8x", volPct: 92, flow: "+0.9亿",
                          turnover: "6.2%", warn: nil, analysis: a),
                Candidate(rank: 2, name: "紫光国微", code: "002049", sector: "半导体", tag: "主力连续净流入",
                          price: 76.50, chg: "+3.10%", volMultiple: "2.1x", volPct: 68, flow: "+1.5亿",
                          turnover: "5.1%", warn: nil, analysis: a),
                Candidate(rank: 3, name: "三安光电", code: "600703", sector: "光电", tag: "底部放量启动",
                          price: 15.20, chg: "+2.70%", volMultiple: "1.9x", volPct: 60, flow: "+0.7亿",
                          turnover: "3.8%", warn: nil, analysis: a),
                Candidate(rank: 4, name: "中航光电", code: "002179", sector: "军工", tag: "",
                          price: 41.80, chg: "+1.90%", volMultiple: "1.7x", volPct: 52, flow: "+0.5亿",
                          turnover: "2.9%", warn: "前期涨幅 +58% · 高位警告降级", analysis: a),
            ]
            m.candidatesTradeDate = "2026-06-23"
        }
        return m
    }

    private func render<V: View>(_ view: V, size: CGSize, name: String) {
        let renderer = ImageRenderer(content:
            view.frame(width: size.width, height: size.height)
                .background(LN.pageBg)
        )
        renderer.scale = 2
        #if os(iOS)
        guard let img = renderer.uiImage, let png = img.pngData() else {
            XCTFail("渲染失败: \(name)"); return
        }
        #else
        guard let img = renderer.nsImage,
              let tiff = img.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:]) else {
            XCTFail("渲染失败: \(name)"); return
        }
        #endif
        let path = NSTemporaryDirectory() + "linon_snap_\(name).png"
        try? png.write(to: URL(fileURLWithPath: path))
        print("SNAPSHOT \(name) -> \(path)")
        XCTAssertGreaterThan(png.count, 1000, "\(name) 渲染产物过小")
    }

    func testRenderCandidateRows() {
        // ImageRenderer 不渲染 ScrollView 内容,直接渲染卡列表组件本体(VStack)。
        let m = model(withCandidates: true)
        let list = VStack(alignment: .leading, spacing: 14) {
            CandidatesExplainBar(headline: CandidatesCopy.headline(m))
            VStack(spacing: 0) {
                ForEach(Array(m.shownCandidates.enumerated()), id: \.element.id) { idx, c in
                    CandidateRow(candidate: c, compact: true)
                    if idx < m.shownCandidates.count - 1 {
                        Divider().overlay(LN.hairline).padding(.leading, 16)
                    }
                }
            }
            .background(RoundedRectangle(cornerRadius: 14).fill(LN.cardBg))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.hairline, lineWidth: 0.5))
        }
        .padding(16)
        render(list, size: CGSize(width: 390, height: 420), name: "candidate_rows_ios")
    }

    func testRenderCandidatesClosed() {
        // 满仓闭门空态(ClosedEmptyCard 非 ScrollView 包裹)。
        render(ClosedEmptyCard().padding(16),
               size: CGSize(width: 390, height: 320), name: "candidates_closed")
    }

    func testRenderCoachCardBlock() {
        // 教练红橙卡本体(直接渲染 coachBlock 等价的红橙卡组件,避开 ScrollView)。
        let card = VStack(alignment: .leading, spacing: 11) {
            VStack(alignment: .leading, spacing: 9) {
                Text("反情绪教练介入")
                    .font(.system(size: 11, weight: .bold)).foregroundStyle(LN.down)
                Text("停一下。「感觉会反弹」——这句话我们听过。沪电股份已触 -5% 止损线、明天就是第 4 个交易日,两条铁律同时到期,没有「再拿一天」的选项。明早开盘清掉它。")
                    .font(.system(size: 13.5)).foregroundStyle(LN.textPrimary).lineSpacing(3)
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "clock").font(.system(size: 14, weight: .semibold)).foregroundStyle(LN.down)
                    Text("复盘历史引用 · 阶段3 接入 —— 破纪律检测与历史教训引用将在复盘大脑就绪后填充(本期为占位)。")
                        .font(.system(size: 12)).foregroundStyle(LN.textSecondary)
                }
                .padding(.horizontal, 14).padding(.vertical, 11)
                .background(RoundedRectangle(cornerRadius: 11).fill(LN.textSecondary.opacity(0.04)))
            }
            .padding(.horizontal, 18).padding(.vertical, 16)
            .background(RoundedRectangle(cornerRadius: 16)
                .fill(LinearGradient(colors: [LN.cardBg, Color(hex: 0xFFF4F3, alpha: 0.9)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing)))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(LN.down.opacity(0.22), lineWidth: 1))
            HStack(spacing: 9) {
                Text("好,标记次日清仓").font(.system(size: 13, weight: .semibold)).foregroundStyle(.white)
                    .padding(.horizontal, 16).padding(.vertical, 9)
                    .background(RoundedRectangle(cornerRadius: 10).fill(LN.down))
                Text("再给我看一眼分时").font(.system(size: 13, weight: .medium)).foregroundStyle(LN.textSecondary)
                    .padding(.horizontal, 16).padding(.vertical, 9)
                    .background(RoundedRectangle(cornerRadius: 10).fill(LN.textSecondary.opacity(0.06)))
            }
        }
        .padding(16)
        render(card, size: CGSize(width: 390, height: 360), name: "coach_card_ios")
    }

    func testRenderDeepAnalysisCardIOS() {
        let card = DeepAnalysisCard(
            analysis: DeepAnalysis(
                form: AnalysisAxis(value: "强", tone: .good, text: "前期低位横盘 27 个交易日,今日放量 2.8x 突破平台上沿并收盘站稳,属平台突破型,非左侧抄底。"),
                fund: AnalysisAxis(value: "确认", tone: .good, text: "主力连续 3 日净流入(+0.6/+0.7/+0.9 亿),当日无大幅净流出,小单未爆量。资金确认成立。"),
                news: AnalysisAxis(value: "无雷", tone: .neutral, text: "海风板块近 5 日 +8% 有资金承接,非情绪一日游;无监管警告与高位减持。"),
                verdict: .enter,
                plan: "不追高:现价距突破上沿仅 +1.8%,可直接进;回踩平台更稳。止损设平台下沿 45.9(-5%)。"),
            fundAsof: "2026-06-22", compact: true)
        render(card.padding(16), size: CGSize(width: 390, height: 460), name: "deepcard_ios")
    }
}
