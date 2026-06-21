//
//  DesignTokens.swift
//  LinoN — A 股短线纪律辅助系统
//
//  设计令牌,从高保真 HTML 稿抽取。颜色为 hifi 精确值。
//  涨跌色:绿涨红跌(国际惯例 / 用户明确选择,勿改回 A 股本地红涨绿跌)。
//

import SwiftUI

// MARK: - Colors

extension Color {
    init(hex: UInt, alpha: Double = 1) {
        self.init(
            .sRGB,
            red:   Double((hex >> 16) & 0xff) / 255,
            green: Double((hex >> 8)  & 0xff) / 255,
            blue:  Double( hex        & 0xff) / 255,
            opacity: alpha
        )
    }
}

enum LN {
    // 语义色
    static let up      = Color(hex: 0x0FA968)   // 涨 / 守纪律 / 止盈 / 盈利
    static let down    = Color(hex: 0xE5443B)   // 跌 / 破线 / 止损 / 标红
    static let amber   = Color(hex: 0xE8910A)   // 中间地带 / 高位警告 / 待办
    static let accent  = Color(hex: 0x0B6BCB)   // 交互蓝 / 主按钮 / 选中

    // 文本
    static let textPrimary   = Color(hex: 0x1D1D1F)
    static let textSecondary = Color(hex: 0x3C3C43, alpha: 0.55)   // rgba(60,60,67,.55)
    static let textTertiary  = Color(hex: 0x3C3C43, alpha: 0.40)
    static let hairline      = Color(hex: 0x3C3C43, alpha: 0.10)   // 分隔线 / 卡边

    // 背景
    static let cardBg     = Color.white
    static let pageBg     = Color(hex: 0xFBFBFD)
    static let pageBgIOS  = Color(hex: 0xF3F4F7)
    static let fieldBg    = Color(hex: 0xF7F8FA)
    static let chipNeutral = Color(hex: 0x3C3C43, alpha: 0.05)

    // 品牌渐变(◆ 头像 / Logo / 复盘 Hero)
    static let brand = LinearGradient(
        colors: [Color(hex: 0x16A06A), Color(hex: 0x0B6BCB)],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )
    // 反情绪教练头像渐变
    static let coach = LinearGradient(
        colors: [Color(hex: 0xE5443B), Color(hex: 0xE8910A)],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )
}

// MARK: - Radius / Spacing

enum LNRadius {
    static let card: CGFloat   = 18    // 持仓卡(macOS 16,iOS 18)
    static let hero: CGFloat   = 20
    static let field: CGFloat  = 12
    static let glassBar: CGFloat = 26  // 底部玻璃标签栏
    static let sheet: CGFloat  = 28    // bottom sheet 顶圆角
    static let pill: CGFloat   = 999
}

enum LNSpace {
    static let pagePad: CGFloat = 16
    static let cardPad: CGFloat = 18
    static let gap: CGFloat     = 12
}

// MARK: - Typography
// 数字务必加 .monospacedDigit()(对应 HTML tabular-nums)

enum LNFont {
    static let largeTitle = Font.system(size: 30, weight: .heavy)          // 大标题"今日/候选…"
    static let heroNumber = Font.system(size: 34, weight: .semibold).monospacedDigit()  // KPI 浮动盈亏
    static let price      = Font.system(size: 25, weight: .semibold).monospacedDigit()  // 持仓现价
    static let priceMac   = Font.system(size: 30, weight: .semibold).monospacedDigit()
    static let scoreHero  = Font.system(size: 60, weight: .bold)           // 复盘评分
    static let stockName  = Font.system(size: 17, weight: .semibold)
    static let body       = Font.system(size: 13.5)
    static let caption    = Font.system(size: 11.5)
    static let chip       = Font.system(size: 11, weight: .bold)
}

// MARK: - Materials
// Liquid Glass 克制使用:仅栏/浮层/锁屏。数据卡用不透明 cardBg。
//   底部 TabBar / 侧栏 / 工具栏: .ultraThinMaterial + 描边 + 内高光
//   锁屏通知:               .regularMaterial(深色壁纸上)
