//
//  CandidatesView.swift
//  LinoN — 候选列表(双端;EOD 机械排序 + 满仓闭门;照 README §2)
//
//  iOS:大标题"候选" + 蓝解释条 + 候选卡列表 + 截断脚注;满仓 🔒 空态。
//  macOS:内联工具栏(候选列表 · EOD 截至昨日收盘 + 排序徽章)+ 蓝解释条 + 列表。
//  整卡可点 → 深析(push iOS / 覆盖内容区 macOS);满仓闭门联动由 shownCandidates 派生。
//

import SwiftUI

// MARK: - iOS

struct CandidatesViewIOS: View {
    @Bindable var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                explainBar
                if model.candidatesClosed {
                    ClosedEmptyCard()
                } else if model.shownCandidates.isEmpty {
                    noCandidateCard
                } else {
                    candidateList
                    footnote
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 104)
        }
        .background(LN.pageBgIOS)
        .refreshable { await model.loadCandidates() }
        .task { if model.candidates.isEmpty { await model.loadCandidates() } }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("候选").font(LNFont.largeTitle).foregroundStyle(LN.textPrimary)
            Text(model.candidatesTradeDate.isEmpty
                 ? "EOD 数据 · 机械排序 · 截至昨日收盘"
                 : "EOD 数据 · 截至 \(model.candidatesTradeDate) 收盘")
                .font(.system(size: 13)).foregroundStyle(LN.textSecondary)
        }
        .padding(.horizontal, 4)
    }

    private var explainBar: some View {
        CandidatesExplainBar(headline: CandidatesCopy.headline(model))
    }

    private var candidateList: some View {
        VStack(spacing: 0) {
            ForEach(Array(model.shownCandidates.enumerated()), id: \.element.id) { idx, c in
                Button(action: { Task { await model.openAnalysis(code: c.code) } }) {
                    CandidateRow(candidate: c, compact: true)
                }
                .buttonStyle(.plain)
                if idx < model.shownCandidates.count - 1 {
                    Divider().overlay(LN.hairline).padding(.leading, 16)
                }
            }
        }
        .background(RoundedRectangle(cornerRadius: 14).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.hairline, lineWidth: 0.5))
    }

    private var footnote: some View {
        Text(CandidatesCopy.footnote(model))
            .font(.system(size: 12)).foregroundStyle(LN.textTertiary)
            .frame(maxWidth: .infinity)
            .multilineTextAlignment(.center)
            .padding(.top, 4)
    }

    private var noCandidateCard: some View {
        VStack(spacing: 8) {
            Text("🟢").font(.system(size: 30))
            Text("今日零合格候选")
                .font(.system(size: 15, weight: .semibold)).foregroundStyle(LN.textPrimary)
            Text(model.candidatesDegraded
                 ? "数据源未就绪(无 Tushare token 或 EOD 未算)。\n配齐后 EOD 收盘自动产出候选。"
                 : "按规则今日无合格票。空仓也是一种纪律——不勉强进场。")
                .font(.system(size: 13)).foregroundStyle(LN.textSecondary)
                .multilineTextAlignment(.center).lineSpacing(3)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 60).padding(.horizontal, 24)
        .background(RoundedRectangle(cornerRadius: 14).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.hairline, lineWidth: 0.5))
    }
}

// MARK: - macOS

struct CandidatesViewMac: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    CandidatesExplainBar(headline: CandidatesCopy.headline(model))
                    if model.candidatesClosed {
                        ClosedEmptyCard()
                    } else if model.shownCandidates.isEmpty {
                        noCandidateCard
                    } else {
                        columnHeader
                        candidateList
                        Text(CandidatesCopy.footnote(model))
                            .font(.system(size: 12)).foregroundStyle(LN.textTertiary)
                            .frame(maxWidth: .infinity).multilineTextAlignment(.center)
                    }
                }
                .padding(.horizontal, 24).padding(.vertical, 20)
            }
            .background(LN.pageBg)
        }
        .task { if model.candidates.isEmpty { await model.loadCandidates() } }
    }

    private var toolbar: some View {
        HStack(spacing: 10) {
            Text("候选列表").font(.system(size: 15, weight: .semibold)).foregroundStyle(LN.textPrimary)
            Text(model.candidatesTradeDate.isEmpty
                 ? "EOD 数据 · 截至昨日收盘"
                 : "EOD 数据 · 截至 \(model.candidatesTradeDate) 收盘")
                .font(.system(size: 12.5)).foregroundStyle(LN.textTertiary)
            Spacer()
            Text("排序:放量强度 ▾")
                .font(.system(size: 12)).foregroundStyle(LN.textSecondary)
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 8).fill(LN.textSecondary.opacity(0.06)))
        }
        .padding(.horizontal, 22)
        .frame(height: 52)
        .background(.ultraThinMaterial)
        .overlay(Divider().overlay(LN.hairline), alignment: .bottom)
    }

    private var columnHeader: some View {
        HStack(spacing: 12) {
            Text("#").frame(width: 28, alignment: .leading)
            Text("股票").frame(minWidth: 130, alignment: .leading)
            Spacer()
            Text("现价/涨幅").frame(width: 92, alignment: .trailing)
            Text("放量倍数").frame(width: 132, alignment: .leading)
            Text("主力净流入").frame(width: 92, alignment: .trailing)
            Text("换手").frame(width: 56, alignment: .trailing)
            Spacer().frame(width: 70)
        }
        .font(.system(size: 11, weight: .semibold)).tracking(0.4)
        .foregroundStyle(LN.textTertiary)
        .padding(.horizontal, 16)
    }

    private var candidateList: some View {
        VStack(spacing: 0) {
            ForEach(Array(model.shownCandidates.enumerated()), id: \.element.id) { idx, c in
                Button(action: { Task { await model.openAnalysis(code: c.code) } }) {
                    CandidateRow(candidate: c, compact: false)
                }
                .buttonStyle(.plain)
                if idx < model.shownCandidates.count - 1 {
                    Divider().overlay(LN.hairline)
                }
            }
        }
        .background(RoundedRectangle(cornerRadius: 14).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.hairline, lineWidth: 0.5))
    }

    private var noCandidateCard: some View {
        VStack(spacing: 8) {
            Text("🟢").font(.system(size: 30))
            Text("今日零合格候选")
                .font(.system(size: 15, weight: .semibold)).foregroundStyle(LN.textPrimary)
            Text(model.candidatesDegraded
                 ? "数据源未就绪(无 Tushare token 或 EOD 未算)。配齐后 EOD 收盘自动产出候选。"
                 : "按规则今日无合格票。空仓也是一种纪律——不勉强进场。")
                .font(.system(size: 13)).foregroundStyle(LN.textSecondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 64).padding(.horizontal, 24)
        .background(RoundedRectangle(cornerRadius: 14).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.hairline, lineWidth: 0.5))
    }
}

// MARK: - 蓝解释条(共享)

struct CandidatesExplainBar: View {
    let headline: String
    var body: some View {
        Group {
            #if os(iOS)
            // iOS 窄屏:headline 占满宽在上、pill 行在下。
            // 旧版与两个定宽(.fixedSize)pill 挤一个 HStack,窄屏 pill 抢光宽度→ headline 被压成一字一行竖排。
            VStack(alignment: .leading, spacing: 10) {
                headlineText.frame(maxWidth: .infinity, alignment: .leading)
                pills
            }
            #else
            // macOS 宽屏:headline 左、pill 右横排(放得下,保持原设计)。
            HStack(alignment: .center, spacing: 12) {
                headlineText
                Spacer(minLength: 8)
                pills
            }
            #endif
        }
        .padding(.horizontal, 18).padding(.vertical, 13)
        .background(RoundedRectangle(cornerRadius: 13).fill(LN.accent.opacity(0.05)))
        .overlay(RoundedRectangle(cornerRadius: 13).stroke(LN.accent.opacity(0.16), lineWidth: 0.5))
    }

    private var headlineText: some View {
        Text(headline)
            .font(.system(size: 13)).foregroundStyle(LN.textPrimary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var pills: some View {
        HStack(spacing: 6) {
            tag("权重 放量▸资金▸换手▸低位")
            tag("已排除 300/688/白酒/ST")
        }
    }

    private func tag(_ s: String) -> some View {
        Text(s)
            .font(.system(size: 11)).foregroundStyle(LN.textSecondary)
            .padding(.horizontal, 9).padding(.vertical, 3)
            .background(Capsule().fill(LN.cardBg))
            .overlay(Capsule().stroke(LN.textSecondary.opacity(0.12), lineWidth: 0.5))
            .fixedSize()
    }
}

// MARK: - 满仓闭门空态(共享)

struct ClosedEmptyCard: View {
    var body: some View {
        VStack(spacing: 8) {
            Text("🔒").font(.system(size: 34))
            Text("满仓 · 候选已闭门")
                .font(.system(size: 15, weight: .semibold)).foregroundStyle(LN.textPrimary)
            Text("3 个仓位已满,按规则注意力交还给已持仓的票。\n清掉一只腾出仓位后,候选才会按「5 × 空仓位」重新打开。")
                .font(.system(size: 13)).foregroundStyle(LN.textSecondary)
                .multilineTextAlignment(.center).lineSpacing(4)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 70).padding(.horizontal, 24)
        .background(RoundedRectangle(cornerRadius: 14).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.hairline, lineWidth: 0.5))
    }
}

// MARK: - 候选卡 CandidateRow(共享内容,布局微分叉)

struct CandidateRow: View {
    let candidate: Candidate
    var compact: Bool = true

    private var c: Candidate { candidate }
    private var volIsHigh: Bool { c.volPct >= 80 }
    private var rankIsFirst: Bool { c.rank == 1 }

    var body: some View {
        if compact { iosRow } else { macRow }
    }

    // MARK: - iOS:rank + 弹性中列(名/警告·板块/[放量条·放量·主力])+ 右侧价/涨/chevron

    private var iosRow: some View {
        HStack(spacing: 13) {
            rankChip
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 6) {
                    Text(c.name).font(.system(size: 14.5, weight: .semibold))
                        .foregroundStyle(LN.textPrimary).lineLimit(1).fixedSize()
                    Text(c.code).font(.system(size: 11).monospacedDigit()).foregroundStyle(LN.textTertiary)
                }
                warnOrSector
                HStack(spacing: 7) {
                    volBar(width: 54)
                    Text("放量 \(c.volMultiple)")
                        .font(.system(size: 11, weight: .semibold).monospacedDigit())
                        .foregroundStyle(volIsHigh ? LN.up : LN.textSecondary)
                    Text("主力 \(c.flow)")
                        .font(.system(size: 11).monospacedDigit())
                        .foregroundStyle(c.flow.contains("-") ? LN.down : LN.textTertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            VStack(alignment: .trailing, spacing: 2) {
                Text(LNFmt.price(c.price))
                    .font(.system(size: 15, weight: .semibold).monospacedDigit())
                    .foregroundStyle(LN.textPrimary)
                Text(c.chg)
                    .font(.system(size: 12, weight: .semibold).monospacedDigit())
                    .foregroundStyle(c.chg.contains("-") ? LN.down : LN.up)
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold)).foregroundStyle(LN.textTertiary)
                    .padding(.top, 2)
            }
            .fixedSize()
        }
        .padding(.horizontal, 15).padding(.vertical, 14)
        .background(c.warn != nil ? LN.amber.opacity(0.04) : Color.clear)
        .contentShape(Rectangle())
    }

    // MARK: - macOS:横向列(# / 股票 / 现价涨幅 / 放量条·倍数 / 主力 / 换手 / 深析)

    private var macRow: some View {
        HStack(spacing: 12) {
            rankChip.frame(width: 28)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(c.name).font(.system(size: 14.5, weight: .semibold))
                        .foregroundStyle(LN.textPrimary).lineLimit(1)
                    Text(c.code).font(.system(size: 11).monospacedDigit()).foregroundStyle(LN.textTertiary)
                }
                warnOrSector
            }
            .frame(minWidth: 130, alignment: .leading)
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 2) {
                Text(LNFmt.price(c.price))
                    .font(.system(size: 14, weight: .semibold).monospacedDigit()).foregroundStyle(LN.textPrimary)
                Text(c.chg)
                    .font(.system(size: 12, weight: .semibold).monospacedDigit())
                    .foregroundStyle(c.chg.contains("-") ? LN.down : LN.up)
            }
            .frame(width: 92, alignment: .trailing)
            HStack(spacing: 8) {
                volBar(width: nil)
                Text(c.volMultiple)
                    .font(.system(size: 12, weight: .semibold).monospacedDigit())
                    .foregroundStyle(volIsHigh ? LN.up : LN.textPrimary).fixedSize()
            }
            .frame(width: 132)
            Text(c.flow)
                .font(.system(size: 13, weight: .semibold).monospacedDigit())
                .foregroundStyle(c.flow.contains("-") ? LN.down : LN.up)
                .frame(width: 92, alignment: .trailing)
            Text(c.turnover)
                .font(.system(size: 13).monospacedDigit()).foregroundStyle(LN.textSecondary)
                .frame(width: 56, alignment: .trailing)
            analyzeButton.frame(width: 70, alignment: .trailing)
        }
        .padding(.horizontal, 16).padding(.vertical, 15)
        .background(c.warn != nil ? LN.amber.opacity(0.04) : Color.clear)
        .contentShape(Rectangle())
    }

    // MARK: - 共享小部件

    private var rankChip: some View {
        Text("\(c.rank)")
            .font(.system(size: compact ? 14 : 16, weight: .bold).monospacedDigit())
            .foregroundStyle(rankIsFirst ? .white : LN.textSecondary)
            .frame(width: compact ? 26 : 28, height: compact ? 26 : 28)
            .background(
                Group {
                    if rankIsFirst {
                        RoundedRectangle(cornerRadius: 8).fill(LN.accent)
                    } else if compact {
                        RoundedRectangle(cornerRadius: 8).fill(LN.chipNeutral)
                    } else {
                        Color.clear
                    }
                }
            )
    }

    @ViewBuilder private var warnOrSector: some View {
        if let warn = c.warn {
            Text("⚠ \(warn)")
                .font(.system(size: 10.5, weight: .semibold)).foregroundStyle(LN.amber)
                .padding(.horizontal, 8).padding(.vertical, 2)
                .background(Capsule().fill(LN.amber.opacity(0.12)))
                .lineLimit(1)
        } else if !sectorTag.isEmpty {
            Text(sectorTag)
                .font(.system(size: 11)).foregroundStyle(LN.textSecondary).lineLimit(1)
        }
    }

    private var sectorTag: String {
        switch (c.sector.isEmpty, c.tag.isEmpty) {
        case (false, false): return "\(c.sector) · \(c.tag)"
        case (false, true):  return c.sector
        case (true, false):  return c.tag
        default:             return ""
        }
    }

    /// 放量进度条。width=nil 时占满父(macOS 弹性);给定宽度时固定(iOS 54)。
    @ViewBuilder private func volBar(width: CGFloat?) -> some View {
        let bar = GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color(hex: 0xEDEEF1))
                Capsule().fill(volIsHigh ? LN.up : LN.textSecondary.opacity(0.45))
                    .frame(width: geo.size.width * CGFloat(min(100, max(0, c.volPct))) / 100)
            }
        }
        .frame(height: compact ? 5 : 6)
        if let w = width { bar.frame(width: w) } else { bar }
    }

    private var analyzeButton: some View {
        Text("深析")
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(rankIsFirst ? .white : LN.accent)
            .padding(.horizontal, 13).padding(.vertical, rankIsFirst ? 6 : 5)
            .background(
                Group {
                    if rankIsFirst {
                        RoundedRectangle(cornerRadius: 8).fill(LN.accent)
                    } else {
                        RoundedRectangle(cornerRadius: 8).stroke(LN.accent.opacity(0.3), lineWidth: 1)
                    }
                }
            )
    }
}

// MARK: - 文案派生(共享)

@MainActor
enum CandidatesCopy {
    static func headline(_ m: AppModel) -> String {
        if m.candidatesClosed { return "满仓 · 候选闭门 · 注意力交还给持仓" }
        let shown = m.shownCandidates.count
        return "空 \(m.openSlots) 仓位 → 按规则截断取前 \(shown)(5 × 空仓位)"
    }

    static func footnote(_ m: AppModel) -> String {
        let shown = m.shownCandidates.count
        return "已展示前 \(shown) 只 · 截断线以下合格但不在注意力范围内 · 满仓时此列表为空,注意力交还给持仓"
    }
}
