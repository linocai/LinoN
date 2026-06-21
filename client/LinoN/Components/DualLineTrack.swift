//
//  DualLineTrack.swift
//  LinoN — 签名组件①:双线轨道(止损 → 止盈中间地带可视化)
//
//  公式钉死(§4b / README):marker x% = clamp((pnlPct+5)/20*100, 2, 98)
//    −5%→2 · 0%→25(成本刻度)· +15%→100
//  左 25% 为止损红区;中线 25% 处竖刻度(成本 0%);
//  盈利:从 25% 向右绿色填充到 marker;亏损:从 marker 向右红色填充到 25%。
//  触止损:marker 红 + 呼吸光环动画(lnRing 1.8s)。
//

import SwiftUI

struct DualLineTrack: View {
    let pnlPct: Double
    let hitStop: Bool
    var stopLabel: String? = nil   // "止损 93.58"
    var takeLabel: String? = nil   // "止盈 113.28"
    var costLabel: String? = nil   // macOS 显示成本刻度文字

    /// marker 位置(0…1),= clamp((pnlPct+5)/20, 0.02, 0.98)
    private var markerFraction: Double {
        min(0.98, max(0.02, (pnlPct + 5) / 20))
    }
    private var costFraction: Double { 0.25 }
    private var gain: Bool { pnlPct >= 0 }
    private var markerColor: Color {
        hitStop ? LN.down : (gain ? LN.up : LN.amber)
    }

    @State private var ringPhase = false

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let trackY: CGFloat = 18
            let markerX = w * markerFraction
            let costX = w * costFraction

            ZStack(alignment: .topLeading) {
                // 基线轨道
                Capsule()
                    .fill(Color(hex: 0xEDEEF1))
                    .frame(width: w, height: 6)
                    .offset(y: trackY)

                // 左 25% 止损红区
                Capsule()
                    .fill(LN.down.opacity(0.15))
                    .frame(width: costX, height: 6)
                    .offset(y: trackY)

                // 填充段(盈利:cost→marker 绿;亏损:marker→cost 红)
                fillSegment(w: w, costX: costX, markerX: markerX, trackY: trackY)

                // 成本竖刻度(25% 处)
                Rectangle()
                    .fill(Color(hex: 0x3C3C43, alpha: 0.25))
                    .frame(width: 1.5, height: 16)
                    .offset(x: costX - 0.75, y: 13)

                // marker
                markerDot
                    .offset(x: markerX - 7.5, y: 9)

                // 端点标签
                if let s = stopLabel {
                    Text(s)
                        .font(.system(size: 10.5, weight: .semibold).monospacedDigit())
                        .foregroundStyle(LN.down)
                        .offset(x: 0, y: 29)
                }
                if let c = costLabel {
                    Text(c)
                        .font(.system(size: 10.5).monospacedDigit())
                        .foregroundStyle(LN.textTertiary)
                        .offset(x: costX - 8, y: 30)
                }
                if let t = takeLabel {
                    Text(t)
                        .font(.system(size: 10.5, weight: .semibold).monospacedDigit())
                        .foregroundStyle(LN.up)
                        .frame(width: w, alignment: .trailing)
                        .offset(x: 0, y: 29)
                }
            }
        }
        .frame(height: 44)
        .onAppear { if hitStop { ringPhase = true } }
    }

    @ViewBuilder
    private func fillSegment(w: CGFloat, costX: CGFloat, markerX: CGFloat, trackY: CGFloat) -> some View {
        if gain {
            let width = max(0, markerX - costX)
            Capsule()
                .fill(LinearGradient(
                    colors: [LN.up.opacity(0.18), LN.up.opacity(0.42)],
                    startPoint: .leading, endPoint: .trailing))
                .frame(width: width, height: 6)
                .offset(x: costX, y: trackY)
        } else {
            let width = max(0, costX - markerX)
            Capsule()
                .fill(LinearGradient(
                    colors: [LN.down.opacity(0.5), LN.down.opacity(0.2)],
                    startPoint: .leading, endPoint: .trailing))
                .frame(width: width, height: 6)
                .offset(x: markerX, y: trackY)
        }
    }

    private var markerDot: some View {
        Circle()
            .fill(markerColor)
            .frame(width: 15, height: 15)
            .overlay(Circle().stroke(Color.white, lineWidth: 3))
            .background(
                Group {
                    if hitStop {
                        Circle()
                            .stroke(LN.down.opacity(ringPhase ? 0.05 : 0.18),
                                    lineWidth: ringPhase ? 9 : 5)
                            .frame(width: 15, height: 15)
                            .animation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true),
                                       value: ringPhase)
                    } else {
                        Circle().fill(Color.clear)
                    }
                }
            )
            .shadow(color: hitStop ? .clear : Color.black.opacity(0.22), radius: 2, y: 1)
    }
}

#if DEBUG
#Preview("DualLineTrack") {
    VStack(spacing: 30) {
        DualLineTrack(pnlPct: -5, hitStop: true, stopLabel: "止损 93.58", takeLabel: "止盈 113.28")
        DualLineTrack(pnlPct: 0, hitStop: false, stopLabel: "止损 40.18", takeLabel: "止盈 48.65")
        DualLineTrack(pnlPct: 6.8, hitStop: false, stopLabel: "止损 93.58", takeLabel: "止盈 113.28")
        DualLineTrack(pnlPct: 15, hitStop: false, stopLabel: "止损 20.4", takeLabel: "止盈 27.6")
    }
    .padding(40)
    .frame(width: 360)
}
#endif
