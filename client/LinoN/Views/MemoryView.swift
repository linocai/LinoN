//
//  MemoryView.swift
//  LinoN — 记忆(双端;闭环结论 / 长期记忆 / 已平仓流水;照 README §5)
//
//  结论卡网格(macOS 三列 / iOS 单列):kind chip(闭环结论蓝 / 长期记忆琥珀 / 纪律里程碑绿)
//  + 正文 + 状态行。历史流水(已平仓 trades):股票 / pnl / 守线徽章(止损·止盈·时间,
//  守=绿 / 破=红删除线)/ 净额(v1.3.0 Phase D1,nil→"—") / note / date。空态友好占位。
//

import SwiftUI

// MARK: - iOS

struct MemoryViewIOS: View {
    @Bindable var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                MemoryContent(model: model, columns: 1)
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 104)
        }
        .background(LN.pageBgIOS)
        .refreshable { await model.loadMemory() }
        .task { if model.memoryItems.isEmpty && model.archivedTrades.isEmpty { await model.loadMemory() } }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("记忆").font(LNFont.largeTitle).foregroundStyle(LN.textPrimary)
            Text("闭环结论 · 长期记忆 · 已平仓流水")
                .font(.system(size: 13)).foregroundStyle(LN.textSecondary)
        }
        .padding(.horizontal, 4)
    }
}

// MARK: - macOS

struct MemoryViewMac: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Text("记忆").font(.system(size: 17, weight: .semibold)).foregroundStyle(LN.textPrimary)
                Spacer()
                Button(action: { Task { await model.loadMemory() } }) {
                    Image(systemName: "arrow.clockwise").font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(LN.accent)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 24).padding(.vertical, 16)
            Divider().overlay(LN.hairline)
            ScrollView {
                MemoryContent(model: model, columns: 3)
                    .padding(24)
            }
        }
        .background(LN.pageBg)
        .task { if model.memoryItems.isEmpty && model.archivedTrades.isEmpty { await model.loadMemory() } }
    }
}

// MARK: - 共享内容

private struct MemoryContent: View {
    @Bindable var model: AppModel
    let columns: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            conclusionsSection
            archivedSection
        }
    }

    // —— 结论卡网格 ——
    @ViewBuilder
    private var conclusionsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("结论 · 记忆").font(.system(size: 13, weight: .semibold)).foregroundStyle(LN.textPrimary)
            if model.memoryItems.isEmpty {
                emptyCard("还没有沉淀的记忆。破线清仓时会自动记一条闭环结论。", "bookmark")
            } else {
                let cols = Array(repeating: GridItem(.flexible(), spacing: 12), count: columns)
                LazyVGrid(columns: cols, alignment: .leading, spacing: 12) {
                    ForEach(model.memoryItems) { MemoryCard(item: $0) }
                }
            }
        }
    }

    // —— 历史流水(已平仓)——
    @ViewBuilder
    private var archivedSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("已平仓流水").font(.system(size: 13, weight: .semibold)).foregroundStyle(LN.textPrimary)
            if model.archivedTrades.isEmpty {
                emptyCard("还没有已平仓记录。清仓后这里会记录每一笔的守线情况。", "tray")
            } else {
                ForEach(model.archivedTrades) { ArchivedTradeRowView(row: $0) }
            }
        }
    }

    private func emptyCard(_ text: String, _ icon: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon).font(.system(size: 16)).foregroundStyle(LN.textTertiary)
            Text(text).font(.system(size: 13)).foregroundStyle(LN.textSecondary)
            Spacer()
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 12).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(LN.hairline, lineWidth: 0.5))
    }
}

// MARK: - 结论卡

private struct MemoryCard: View {
    let item: MemoryItem

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Text(item.kind.rawValue)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(kindColor)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Capsule().fill(kindColor.opacity(0.12)))
                Spacer()
                Text(item.date).font(.system(size: 10)).foregroundStyle(LN.textTertiary)
            }
            Text(item.content)
                .font(.system(size: 13)).foregroundStyle(LN.textPrimary).lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 12).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(kindColor.opacity(0.18), lineWidth: 1))
    }

    // kind chip:闭环结论蓝 / 长期记忆琥珀 / 纪律里程碑绿。
    private var kindColor: Color {
        switch item.kind {
        case .conclusion: return LN.accent
        case .longTerm:   return LN.amber
        case .milestone:  return LN.up
        }
    }
}

// MARK: - 已平仓流水行

private struct ArchivedTradeRowView: View {
    let row: ClosedTradeRow

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(row.name).font(.system(size: 13.5, weight: .semibold)).foregroundStyle(LN.textPrimary)
                    Text(row.code).font(.system(size: 11)).foregroundStyle(LN.textTertiary)
                }
                if !row.note.isEmpty {
                    Text(row.note).font(.system(size: 11.5)).foregroundStyle(LN.textSecondary)
                }
            }
            Spacer()
            // 守线徽章:止损 · 止盈 · 时间(守=绿 / 破=红删除线)
            HStack(spacing: 5) {
                KeptBadge(label: "损", kept: row.keptStop)
                KeptBadge(label: "盈", kept: row.keptTake)
                KeptBadge(label: "时", kept: row.keptTime)
            }
            VStack(alignment: .trailing, spacing: 3) {
                Text(row.pnl)
                    .font(.system(size: 14, weight: .bold, design: .rounded))
                    .foregroundStyle(row.pnl.hasPrefix("-") ? LN.down : LN.up)
                // v1.3.0 Phase D1:净收益金额(nil → "—";着色用派生 bool,非字符串判负)。
                Text(LNFmt.netAmount(row.netPnlAmount))
                    .font(.system(size: 11.5).monospacedDigit())
                    .foregroundStyle(netPnlColor(row.netPnlAmount))
                Text(row.date).font(.system(size: 10)).foregroundStyle(LN.textTertiary)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: 12).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 12)
            .stroke(row.brokeRule ? LN.down.opacity(0.20) : LN.hairline, lineWidth: row.brokeRule ? 1 : 0.5))
    }
}

/// 守线徽章:守=绿实心 / 破=红删除线。
private struct KeptBadge: View {
    let label: String
    let kept: Bool

    var body: some View {
        Text(label)
            .font(.system(size: 10, weight: .bold))
            .foregroundStyle(kept ? LN.up : LN.down)
            .strikethrough(!kept, color: LN.down)
            .frame(width: 20, height: 20)
            .background(Circle().fill((kept ? LN.up : LN.down).opacity(0.12)))
    }
}
