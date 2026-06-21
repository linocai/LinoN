//
//  SharedUI.swift
//  LinoN — 跨视图共享小组件 + 格式化工具
//

import SwiftUI

// MARK: - 数字格式化(数字一律 monospacedDigit)

enum LNFmt {
    static func price(_ v: Double) -> String { String(format: "%.2f", v) }

    static func signedPct(_ v: Double, decimals: Int = 2) -> String {
        let s = String(format: "%.\(decimals)f", abs(v))
        return (v >= 0 ? "+" : "−") + s + "%"
    }

    static func pct1(_ v: Double) -> String {
        (v >= 0 ? "+" : "") + String(format: "%.1f", v) + "%"
    }

    /// 金额带千分位 + ¥ 前缀,正负用 +¥ / −¥
    static func money(_ v: Double) -> String {
        let nf = NumberFormatter()
        nf.numberStyle = .decimal
        nf.maximumFractionDigits = 0
        let abs = Swift.abs(v.rounded())
        let body = nf.string(from: NSNumber(value: abs)) ?? "0"
        return "¥" + body
    }

    static func signedMoney(_ v: Double) -> String {
        let nf = NumberFormatter()
        nf.numberStyle = .decimal
        nf.maximumFractionDigits = 0
        let abs = Swift.abs(v.rounded())
        let body = nf.string(from: NSNumber(value: abs)) ?? "0"
        return (v >= 0 ? "+¥" : "−¥") + body
    }
}

extension Double {
    var pnlColor: Color { self >= 0 ? LN.up : LN.down }
    var arrow: String { self >= 0 ? "▲" : "▼" }
}

// MARK: - 进场理由 chip(中性 / 触损 / 中间地带)

enum ReasonTone { case neutral, stop, mid }

struct ReasonChip: View {
    let text: String
    let tone: ReasonTone

    var body: some View {
        let (fg, bg): (Color, Color) = {
            switch tone {
            case .neutral: return (LN.textSecondary, LN.chipNeutral)
            case .stop:    return (LN.down, LN.down.opacity(0.10))
            case .mid:     return (LN.amber, LN.amber.opacity(0.10))
            }
        }()
        return HStack(spacing: 4) {
            if tone == .stop { Text("⚑") }
            Text(text)
        }
        .font(.system(size: 11.5, weight: tone == .neutral ? .regular : .semibold))
        .foregroundStyle(fg)
        .padding(.horizontal, 9).padding(.vertical, 3)
        .background(Capsule().fill(bg))
    }
}

// MARK: - Toast(底部淡入,2.4s 自动消失)

struct ToastView: View {
    let toast: Toast
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: toast.isError ? "exclamationmark.circle.fill" : "checkmark.circle.fill")
                .foregroundStyle(toast.isError ? LN.down : Color(hex: 0x28C840))
            Text(toast.message)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.white)
        }
        .padding(.horizontal, 18).padding(.vertical, 11)
        .background(
            RoundedRectangle(cornerRadius: 13)
                .fill(Color(hex: 0x1C2028, alpha: 0.94))
        )
        .shadow(color: .black.opacity(0.3), radius: 15, y: 8)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

// MARK: - 占位空视图(候选 / 复盘 / 记忆,阶段2/3 重建)

struct PlaceholderView: View {
    let title: String
    let subtitle: String
    let systemImage: String

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: systemImage)
                .font(.system(size: 44, weight: .light))
                .foregroundStyle(LN.textTertiary)
            Text(title)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(LN.textPrimary)
            Text(subtitle)
                .font(.system(size: 13))
                .foregroundStyle(LN.textSecondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }
}

// MARK: - Logo 标(L 字母 + 品牌渐变圆角方)

struct LNLogo: View {
    var size: CGFloat = 27
    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.26, style: .continuous)
            .fill(LN.brand)
            .frame(width: size, height: size)
            .overlay(
                Text("L")
                    .font(.system(size: size * 0.52, weight: .bold))
                    .foregroundStyle(.white)
            )
    }
}

// MARK: - 教练 ◆ 头像

struct CoachAvatar: View {
    var size: CGFloat = 30
    var body: some View {
        Circle()
            .fill(LN.brand)
            .frame(width: size, height: size)
            .overlay(Text("◆").font(.system(size: size * 0.46)).foregroundStyle(.white))
    }
}
