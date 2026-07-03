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

    /// v1.3.0 Phase D1:净额到分(带 +¥/−¥;与 Phase B 逐分对账口径一致,区别于 signedMoney 整元)。
    static func signedMoneyCents(_ v: Double) -> String {
        let nf = NumberFormatter()
        nf.numberStyle = .decimal
        nf.minimumFractionDigits = 2
        nf.maximumFractionDigits = 2
        let body = nf.string(from: NSNumber(value: Swift.abs(v))) ?? "0.00"
        return (v >= 0 ? "+¥" : "−¥") + body
    }

    /// v1.3.0 Phase D1:可空净额展示。nil(旧行/无数据)→ "—"(区分"没数据"vs"真0元");
    /// 有值 → 到分金额(🟡2:Phase B 逐分对账,展示到分)。颜色另用 `netPnlColor(_:)` 派生,不解析字符串。
    static func netAmount(_ v: Double?) -> String {
        guard let v else { return "—" }
        return signedMoneyCents(v)
    }
}

/// v1.3.0 Phase D1:净额金额着色 —— 派生 bool(非字符串判负,避开 Unicode 减号"−"坑)。
/// nil → 中性灰(未知,不该染红染绿);非 nil → (v>=0) 绿 / 红。
func netPnlColor(_ v: Double?) -> Color {
    guard let v else { return LN.textTertiary }
    return v >= 0 ? LN.up : LN.down
}

// MARK: - v1.3.0 Phase E:导出同花顺 TXT —— 裸 6 位代码 → 市场后缀(纯函数,可单测)

/// 裸 6 位代码 → 同花顺市场后缀。**最长前缀优先**:920 必须先于 9 判、68 必须先于 6 判,
/// 否则北交所 920xxx 会被 "9" 前缀误判成 .SH、科创 68xxxx 会被 "6" 前缀误判成 .SH。
/// 判定顺序:920→.BJ → 8/4→.BJ → 68/9→.SH → 60→.SH → 00/30→.SZ。
/// 不匹配任何已知前缀 → 返回 nil(调用方 compactMap 跳过该行,不硬崩不猜)。
func thsMarketSuffix(_ code: String) -> String? {
    let bare = code.trimmingCharacters(in: .whitespaces)
    guard bare.count == 6, bare.allSatisfy({ $0.isNumber }) else { return nil }
    if bare.hasPrefix("920") { return ".BJ" }
    if bare.hasPrefix("8") || bare.hasPrefix("4") { return ".BJ" }
    if bare.hasPrefix("68") || bare.hasPrefix("9") { return ".SH" }
    if bare.hasPrefix("60") { return ".SH" }
    if bare.hasPrefix("00") || bare.hasPrefix("30") { return ".SZ" }
    return nil
}

/// 从候选列表生成同花顺导入 TXT:每行 `裸6位.后缀`,未知前缀行跳过(compactMap)。
func thsExportText(_ candidates: [Candidate]) -> String {
    candidates.compactMap { c -> String? in
        guard let suffix = thsMarketSuffix(c.code) else { return nil }
        return c.code + suffix
    }.joined(separator: "\n")
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
