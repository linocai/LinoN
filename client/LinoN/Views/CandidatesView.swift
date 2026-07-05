//
//  CandidatesView.swift
//  LinoN — 候选列表(双端;EOD 机械排序 + 固定 Top 20;照 README §2)
//
//  v1.3.0 Phase C3:满仓闭门已删,任何持仓状态固定展示 Top 20(shownCandidates 直接
//  取 candidates.prefix(20),后端已限 20,前端只做安全带)。
//  iOS:大标题"候选" + 蓝解释条 + 候选卡列表 + 截断脚注;导出按钮见 header。
//  macOS:内联工具栏(候选列表 · EOD 截至昨日收盘 + 排序徽章)+ 蓝解释条 + 列表。
//  整卡可点 → 深析(push iOS / 覆盖内容区 macOS)。
//

import SwiftUI
#if os(macOS)
import AppKit
import UniformTypeIdentifiers
#endif

// MARK: - iOS

struct CandidatesViewIOS: View {
    @Bindable var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                intradayNonTradingBanner
                explainBar
                if model.shownCandidates.isEmpty {
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

    /// v1.4 Phase D4:非交易时段标注(建议#9)。仅在拉取过盘中确认且 isTrading=false 时显示。
    @ViewBuilder private var intradayNonTradingBanner: some View {
        if let intraday = model.intraday, !intraday.isTrading {
            Text("非交易时段 · 盘中确认仅交易时段可用")
                .font(.system(size: 12)).foregroundStyle(LN.textTertiary)
                .padding(.horizontal, 4)
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 5) {
                Text("候选").font(LNFont.largeTitle).foregroundStyle(LN.textPrimary)
                Text(model.candidatesTradeDate.isEmpty
                     ? "EOD 数据 · 机械排序 · 截至昨日收盘"
                     : "EOD 数据 · 截至 \(model.candidatesTradeDate) 收盘")
                    .font(.system(size: 13)).foregroundStyle(LN.textSecondary)
            }
            Spacer()
            exportButton
            intradayButton
            refreshButton
        }
        .padding(.horizontal, 4)
    }

    /// v1.4 Phase D4:「盘中确认」按钮——初始可点(建议#9:客户端不自判日历/时段),
    /// 拉回 isTrading=false 只**变暗 + 标注非交易时段**(视觉提示),不真禁用点击
    /// (🟡#1 审后修复:真禁用会致 app 会话内永久 brick——无清空/重置点,用户盘前/
    /// 收盘后误点一次就再也点不动,只能杀 app。时段真值全由后端 isTrading 定,允许
    /// 用户随时再点重查、以最新响应为准)。仅"拉取中"才真禁用(防重复点击)。
    private var intradayButton: some View {
        Button(action: { Task { await model.loadIntradayConfirm() } }) {
            Group {
                if model.intradayLoading {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: "bolt.horizontal.circle")
                }
            }
            .font(.system(size: 16, weight: .semibold))
            .frame(width: 40, height: 40)
            .background(Circle().fill(intradayButtonDimmed ? LN.chipNeutral : LN.cardBg))
            .overlay(Circle().stroke(LN.hairline, lineWidth: 0.5))
            .foregroundStyle(intradayButtonDimmed ? LN.textTertiary : LN.accent)
        }
        .buttonStyle(.plain)
        .disabled(model.intradayLoading)
    }

    /// 视觉变暗态(非真禁用):拉取中,或上次响应 isTrading=false。
    private var intradayButtonDimmed: Bool {
        model.intradayLoading || (model.intraday != nil && model.intraday?.isTrading == false)
    }

    /// v1.3.0 Phase E:导出同花顺 TXT(ShareLink 分享 sheet)。空候选/降级时禁用。
    private var exportButton: some View {
        let text = thsExportText(model.shownCandidates)
        return ShareLink(item: text) {
            Image(systemName: "square.and.arrow.up").font(.system(size: 16, weight: .semibold))
                .frame(width: 40, height: 40)
                .background(Circle().fill(LN.cardBg))
                .overlay(Circle().stroke(LN.hairline, lineWidth: 0.5))
                .foregroundStyle(LN.accent)
        }
        .disabled(model.shownCandidates.isEmpty || model.candidatesDegraded)
    }

    /// 手动刷新候选(强制重算全市场,可能数十秒;重算中转圈+禁用)。
    private var refreshButton: some View {
        Button(action: { Task { await model.recomputeCandidates() } }) {
            Group {
                if model.candidatesRefreshing {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: "arrow.clockwise").font(.system(size: 16, weight: .semibold))
                }
            }
            .frame(width: 40, height: 40)
            .background(Circle().fill(LN.cardBg))
            .overlay(Circle().stroke(LN.hairline, lineWidth: 0.5))
            .foregroundStyle(LN.accent)
        }
        .buttonStyle(.plain)
        .disabled(model.candidatesRefreshing)
    }

    private var explainBar: some View {
        CandidatesExplainBar(headline: CandidatesCopy.headline(model))
    }

    private var candidateList: some View {
        VStack(spacing: 0) {
            ForEach(Array(model.shownCandidates.enumerated()), id: \.element.id) { idx, c in
                CandidateRow(candidate: c, compact: true, model: model)
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
                    intradayNonTradingBanner
                    CandidatesExplainBar(headline: CandidatesCopy.headline(model))
                    if model.shownCandidates.isEmpty {
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
            exportButton
            intradayToolbarButton
            Button(action: { Task { await model.recomputeCandidates() } }) {
                HStack(spacing: 5) {
                    if model.candidatesRefreshing { ProgressView().controlSize(.small) }
                    else { Image(systemName: "arrow.clockwise") }
                    Text(model.candidatesRefreshing ? "刷新中…" : "刷新")
                }
                .font(.system(size: 12, weight: .medium))
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 8).fill(LN.accent.opacity(0.10)))
                .foregroundStyle(LN.accent)
            }
            .buttonStyle(.plain)
            .disabled(model.candidatesRefreshing)
        }
        .padding(.horizontal, 22)
        .frame(height: 52)
        .background(.ultraThinMaterial)
        .overlay(Divider().overlay(LN.hairline), alignment: .bottom)
    }

    /// v1.4 Phase D4:「盘中确认」工具栏按钮(同 iOS 语义:初始可点,isTrading=false 只
    /// 变暗+标注、不真禁用——🟡#1 审后修复,允许随时再点重查,以最新响应为准)。
    private var intradayToolbarButton: some View {
        Button(action: { Task { await model.loadIntradayConfirm() } }) {
            HStack(spacing: 5) {
                if model.intradayLoading { ProgressView().controlSize(.small) }
                else { Image(systemName: "bolt.horizontal.circle") }
                Text(model.intradayLoading ? "确认中…" : "盘中确认")
            }
            .font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 12).padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 8).fill(intradayButtonDimmed ? LN.chipNeutral : LN.accent.opacity(0.10)))
            .foregroundStyle(intradayButtonDimmed ? LN.textTertiary : LN.accent)
        }
        .buttonStyle(.plain)
        .disabled(model.intradayLoading)
    }

    /// 视觉变暗态(非真禁用):拉取中,或上次响应 isTrading=false。
    private var intradayButtonDimmed: Bool {
        model.intradayLoading || (model.intraday != nil && model.intraday?.isTrading == false)
    }

    /// v1.4 Phase D4:非交易时段标注(建议#9)。仅在拉取过盘中确认且 isTrading=false 时显示。
    @ViewBuilder private var intradayNonTradingBanner: some View {
        if let intraday = model.intraday, !intraday.isTrading {
            Text("非交易时段 · 盘中确认仅交易时段可用")
                .font(.system(size: 12)).foregroundStyle(LN.textTertiary)
        }
    }

    /// v1.3.0 Phase E:导出同花顺 TXT(macOS 用 NSSavePanel 存 .txt)。空候选/降级时禁用。
    private var exportButton: some View {
        Button(action: exportToFile) {
            HStack(spacing: 5) {
                Image(systemName: "square.and.arrow.up")
                Text("导出")
            }
            .font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 12).padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 8).fill(LN.accent.opacity(0.10)))
            .foregroundStyle(LN.accent)
        }
        .buttonStyle(.plain)
        .disabled(model.shownCandidates.isEmpty || model.candidatesDegraded)
    }

    private func exportToFile() {
        #if os(macOS)
        let text = thsExportText(model.shownCandidates)
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "候选_\(model.candidatesTradeDate.isEmpty ? "today" : model.candidatesTradeDate).txt"
        panel.allowedContentTypes = [.plainText]
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            try? text.write(to: url, atomically: true, encoding: .utf8)
        }
        #endif
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
            Text("分数").frame(width: 54, alignment: .trailing)
            Spacer().frame(width: 70)
        }
        .font(.system(size: 11, weight: .semibold)).tracking(0.4)
        .foregroundStyle(LN.textTertiary)
        .padding(.horizontal, 16)
    }

    private var candidateList: some View {
        VStack(spacing: 0) {
            ForEach(Array(model.shownCandidates.enumerated()), id: \.element.id) { idx, c in
                CandidateRow(candidate: c, compact: false, model: model)
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
                scoreNote                 // 阶段3.1:相对分说明(可换行文本,避开窄屏 pill 换行坑)
                pills
            }
            #else
            // macOS 宽屏:headline 左、pill 右横排(放得下,保持原设计)。
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .center, spacing: 12) {
                    headlineText
                    Spacer(minLength: 8)
                    pills
                }
                scoreNote                 // 阶段3.1:相对分说明
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

    /// 阶段3.1:相对分护栏文案。走可换行 Text(非定宽 pill),避开阶段2 已修的窄屏 pill 换行坑。
    private var scoreNote: some View {
        Text("分数为当日候选池内相对评分,不同日期不可横向比较。")
            .font(.system(size: 11)).foregroundStyle(LN.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
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

// MARK: - 候选卡 CandidateRow(共享内容,布局微分叉)

struct CandidateRow: View {
    let candidate: Candidate
    var compact: Bool = true
    let model: AppModel

    private var c: Candidate { candidate }
    private var volIsHigh: Bool { c.volPct >= 80 }
    private var rankIsFirst: Bool { c.rank == 1 }
    /// v1.4 Phase D4:盘中续强字段按 code join(建议#10,不靠数组顺序)。nil = 未拉取/该票缺失。
    private var intraday: IntradayItem? { model.intradayItem(byCode: c.code) }

    var body: some View {
        if compact { iosRow } else { macRow }
    }

    // MARK: - iOS:rank + 弹性中列(名/警告·板块/[放量条·放量·主力])+ 右侧价/涨/chevron

    private var iosRow: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 13) {
                VStack(spacing: 5) {
                    rankChip
                    scoreBadge            // 阶段3.1:分数徽章置于 rank chip 下方(窄屏不抢中列宽)
                }
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
                VStack(alignment: .trailing, spacing: 6) {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(LNFmt.price(c.price))
                            .font(.system(size: 15, weight: .semibold).monospacedDigit())
                            .foregroundStyle(LN.textPrimary)
                        Text(c.chg)
                            .font(.system(size: 12, weight: .semibold).monospacedDigit())
                            .foregroundStyle(c.chg.contains("-") ? LN.down : LN.up)
                    }
                    compactAnalyzeButton
                }
                .fixedSize()
            }
            intradayOverlayIOS
        }
        .padding(.horizontal, 15).padding(.vertical, 14)
        .background(rowBackground)
    }

    // MARK: - macOS:横向列(# / 股票 / 现价涨幅 / 放量条·倍数 / 主力 / 换手 / 深析)

    private var macRow: some View {
        VStack(alignment: .leading, spacing: 0) {
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
                scoreBadge.frame(width: 54, alignment: .trailing)   // 阶段3.1:分数窄列(nil 时空)
                analyzeButton.frame(width: 70, alignment: .trailing)
            }
            intradayOverlayMac
        }
        .padding(.horizontal, 16).padding(.vertical, 15)
        .background(rowBackground)
    }

    // MARK: - v1.4 Phase D4:盘中续强叠加行(按 code join;无 intraday 结果时不显示,布局不塌)

    /// iOS:紧凑一行——现价/今日涨幅/高开幅度/站 VWAP 徽章/折算量比 + volNote 文案。
    /// 🔵#1(审后修复):补齐「高开」字段(plan D.4 字段清单明列,此前 iOS 缺、macOS 有)。
    /// 🔵#2(审后修复):`volNote=="non_trading"` 时整行不渲染——顶部已有非交易时段
    /// banner(intradayNonTradingBanner),20 行逐行重复标注是噪声。
    @ViewBuilder private var intradayOverlayIOS: some View {
        if let it = intraday, it.volNote != "non_trading" {
            HStack(spacing: 8) {
                if let price = it.price {
                    Text("盘中 \(LNFmt.price(price))")
                        .font(.system(size: 11).monospacedDigit()).foregroundStyle(LN.textSecondary)
                }
                if let chg = it.chgPct {
                    Text(LNFmt.pct1(chg))
                        .font(.system(size: 11, weight: .semibold).monospacedDigit())
                        .foregroundStyle(chg >= 0 ? LN.up : LN.down)
                }
                if let openChg = it.openChgPct {
                    Text("高开 \(LNFmt.pct1(openChg))")
                        .font(.system(size: 10.5).monospacedDigit()).foregroundStyle(LN.textTertiary)
                }
                if let above = it.isAboveVwap {
                    vwapBadge(above)
                }
                Text(intradayVolNoteText(it))
                    .font(.system(size: 10.5)).foregroundStyle(LN.textTertiary)
                    .lineLimit(1)
            }
            .padding(.top, 8)
        }
    }

    /// macOS:同语义横排,略宽字号。🔵#2(审后修复):non_trading 整行不渲染(同 iOS)。
    @ViewBuilder private var intradayOverlayMac: some View {
        if let it = intraday, it.volNote != "non_trading" {
            HStack(spacing: 10) {
                Text("盘中续强").font(.system(size: 11, weight: .semibold)).foregroundStyle(LN.textTertiary)
                if let price = it.price {
                    Text(LNFmt.price(price))
                        .font(.system(size: 12).monospacedDigit()).foregroundStyle(LN.textSecondary)
                }
                if let chg = it.chgPct {
                    Text(LNFmt.pct1(chg))
                        .font(.system(size: 12, weight: .semibold).monospacedDigit())
                        .foregroundStyle(chg >= 0 ? LN.up : LN.down)
                }
                if let openChg = it.openChgPct {
                    Text("高开 \(LNFmt.pct1(openChg))")
                        .font(.system(size: 11).monospacedDigit()).foregroundStyle(LN.textTertiary)
                }
                if let above = it.isAboveVwap {
                    vwapBadge(above)
                }
                Text(intradayVolNoteText(it))
                    .font(.system(size: 11)).foregroundStyle(LN.textTertiary)
                Spacer()
            }
            .padding(.top, 8)
        }
    }

    private func vwapBadge(_ above: Bool) -> some View {
        Text(above ? "站VWAP" : "破VWAP")
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(above ? LN.up : LN.down)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(Capsule().fill((above ? LN.up : LN.down).opacity(0.10)))
    }

    /// volNote 文案(照 plan §4 技术选型 note 语义;early 特别标"估算通常偏高"提示)。
    private func intradayVolNoteText(_ it: IntradayItem) -> String {
        guard let ratio = it.intradayVolRatio else {
            switch it.volNote {
            case "early": return "开盘初,量能待观察"
            case "no_base": return "量能基准缺失"
            case "non_trading": return "非交易时段"
            default: return "量能—"
            }
        }
        return "量比\(String(format: "%.1f", ratio))x(估算,早盘通常偏高)"
    }

    // MARK: - 共享小部件

    /// v1.3.1 A3:卡片背景——high 红系极浅、amber 琥珀极浅(现状)、无 warn 透明。
    private var rowBackground: Color {
        switch c.warnLevel {
        case "high": return LN.down.opacity(0.04)
        case "amber": return LN.amber.opacity(0.04)
        default: return c.warn != nil ? LN.amber.opacity(0.04) : Color.clear
        }
    }

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

    /// 阶段3.1 当日相对分徽章(0–100)。score 为 nil 时不显示(前向兼容旧后端,布局不塌)。
    /// 风格贴近现有数值元素:monospacedDigit,rank1 用 accent 高亮,余票中性。
    @ViewBuilder private var scoreBadge: some View {
        if let s = c.score {
            HStack(spacing: 2) {
                Text("\(s)")
                    .font(.system(size: compact ? 11 : 12, weight: .bold).monospacedDigit())
                Text("分")
                    .font(.system(size: compact ? 8.5 : 9, weight: .semibold))
                    .baselineOffset(-0.5)
            }
            .foregroundStyle(rankIsFirst ? LN.accent : LN.textSecondary)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(Capsule().fill(rankIsFirst ? LN.accent.opacity(0.10) : LN.chipNeutral))
        }
    }

    /// v1.3.1 A3:warn 分级展示——`warnLevel=="high"` 红色警告 pill、`"amber"` 琥珀 pill(现状)、
    /// nil 板块标签。分级严格走后端 `warnLevel` 字段派生,不字符串解析 `warn` 文案判级(CLAUDE.md 红线)。
    @ViewBuilder private var warnOrSector: some View {
        if let warn = c.warn, c.warnLevel == "high" {
            Text("⚠ \(warn)")
                .font(.system(size: 10.5, weight: .semibold)).foregroundStyle(LN.down)
                .padding(.horizontal, 8).padding(.vertical, 2)
                .background(Capsule().fill(LN.down.opacity(0.12)))
                .lineLimit(1)
        } else if let warn = c.warn {
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

    /// macOS:横列深析按钮(真按钮,唯一可点入口)。
    private var analyzeButton: some View {
        Button(action: { Task { await model.openAnalysis(code: c.code) } }) {
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
        .buttonStyle(.plain)
    }

    /// iOS:右侧竖排价/涨下方的紧凑深析按钮(唯一可点入口,行其余区域不可点)。
    private var compactAnalyzeButton: some View {
        Button(action: { Task { await model.openAnalysis(code: c.code) } }) {
            Text("深析")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(rankIsFirst ? .white : LN.accent)
                .padding(.horizontal, 10).padding(.vertical, 4)
                .background(
                    Group {
                        if rankIsFirst {
                            RoundedRectangle(cornerRadius: 7).fill(LN.accent)
                        } else {
                            RoundedRectangle(cornerRadius: 7).stroke(LN.accent.opacity(0.3), lineWidth: 1)
                        }
                    }
                )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - 文案派生(共享)

@MainActor
enum CandidatesCopy {
    static func headline(_ m: AppModel) -> String {
        let shown = m.shownCandidates.count
        return "Top \(shown) 候选 · 机械排序,满仓也照常展示"
    }

    static func footnote(_ m: AppModel) -> String {
        let shown = m.shownCandidates.count
        // v1.3.1 C2:候选为上次手动刷新结果,明确刷新语义(自动 tick 已删,手动刷新为唯一途径)。
        return "已展示前 \(shown) 只(固定 Top 20 · 上次手动刷新结果,点刷新重算)· 买不买你自己判断"
    }
}
