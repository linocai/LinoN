//
//  HoldingCardModel.swift
//  LinoN — 持仓卡展示派生(对齐 iOS/macOS HTML 稿 vmHolding)
//
//  算力分工(§4b):后端供 price + flow3d;此处客户端本地算
//  pnl / dist* / 双线 / 天数标签 / 理由 tone(Models.swift 已实现核心派生,直接用)。
//

import Foundation

struct HoldingCardModel {
    let position: Position
    let day: Int
    let isForceClose: Bool

    var pnlPct: Double { position.pnlPct }
    var hitStop: Bool { position.hitStop }
    var price: Double { position.price }
    var flow3d: String { position.flow3d }

    /// 进场理由 tone:触损 → stop;中间地带(理由含"中间地带")→ mid;否则 neutral。
    var reasonTone: ReasonTone {
        if hitStop { return .stop }
        if position.entryReason.contains("中间地带") || position.entryReason.contains("问教练") {
            return .mid
        }
        return .neutral
    }

    var reasonText: String { position.entryReason }

    /// 距盈 / 距损(%)
    var distTakeStr: String { LNFmt.pct1(position.distTakePct) }
    var distStopStr: String { LNFmt.pct1(position.distStopPct) }

    var stopLabel: String { "止损 " + LNFmt.price(position.stopLine) }
    var takeLabel: String { "止盈 " + LNFmt.price(position.takeLine) }
    var costLabel: String { "成本 " + LNFmt.price(position.buyPrice) }

    /// 天数标签(对齐 HTML vmHolding):D1 不可卖、D3 明日强平、D4 今日强平…
    var dayLabel: String {
        switch day {
        case 1: return "D1 · 今日不可卖(T+1)"
        case 3: return "D3 · 明日即强平"
        default:
            if day >= 4 { return "D4 · 今日无条件强平" }
            return "D\(day) · 第 4 日强平"
        }
    }
    var dayIsRed: Bool { day >= 3 }
}
