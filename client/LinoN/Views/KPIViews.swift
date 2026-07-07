//
//  KPIViews.swift
//  LinoN — KPI Hero(iOS) / KPI 四联横条(macOS) + 教练横幅
//

import SwiftUI

// MARK: - iOS KPI Hero(浮动盈亏大字 + 市值/仓位/纪律三联)

struct KPIHeroIOS: View {
    let kpis: PortfolioKPIs

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 20) {
                VStack(alignment: .leading, spacing: 0) {
                    Text("浮动盈亏").font(.system(size: 12)).foregroundStyle(LN.textSecondary)
                        .padding(.bottom, 4)
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(LNFmt.signedMoney(kpis.floatPnl))
                            .font(LNFont.heroNumber)
                            .foregroundStyle(kpis.floatPnl.pnlColor)
                        Text(LNFmt.signedPct(kpis.floatPnlPct))
                            .font(.system(size: 16, weight: .semibold).monospacedDigit())
                            .foregroundStyle(kpis.floatPnl.pnlColor)
                    }
                }
                // 🔵#4 审后修:旧后端(缺 4 键,todayPnlAvailable==false)→ 隐藏今日盈亏卡位,
                // 不显示误导性的假 ¥0(plan §4.1"缺字段时可隐藏或显—")。
                if kpis.todayPnlAvailable {
                    VStack(alignment: .leading, spacing: 0) {
                        Text("今日盈亏").font(.system(size: 12)).foregroundStyle(LN.textSecondary)
                            .padding(.bottom, 4)
                        Text(LNFmt.signedMoney(kpis.todayPnl))
                            .font(.system(size: 22, weight: .semibold).monospacedDigit())
                            .foregroundStyle(kpis.todayPnl.pnlColor)
                        if kpis.todayPnlPartial {
                            Text("部分持仓缺今日行情数据")
                                .font(.system(size: 10.5)).foregroundStyle(LN.textTertiary)
                                .padding(.top, 2)
                        }
                    }
                }
            }
            Text(kpis.todayPnlAvailable ? "浮动=持仓开仓以来 · 今日=今日已实现+今日浮动" : "浮动=持仓开仓以来")
                .font(.system(size: 10.5)).foregroundStyle(LN.textTertiary)
                .padding(.top, 6)
            HStack(spacing: 10) {
                miniStat("持仓市值", LNFmt.money(kpis.marketValue), nil)
                miniStat("仓位", "\(kpis.positionCount)/3",
                         kpis.positionCount >= 3 ? "满仓" : "\(3 - kpis.positionCount) 可用",
                         noteColor: LN.amber)
                miniStat("纪律", "\(kpis.disciplineRate)%", "▲\(kpis.disciplineTrend)",
                         noteColor: LN.up)
            }
            .padding(.top, 16)
        }
        .padding(EdgeInsets(top: 18, leading: 20, bottom: 18, trailing: 20))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: LNRadius.hero, style: .continuous).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: LNRadius.hero, style: .continuous)
            .stroke(LN.hairline, lineWidth: 0.5))
        .shadow(color: Color(hex: 0x141E3C, alpha: 0.05), radius: 3, y: 1)
    }

    private func miniStat(_ title: String, _ value: String, _ note: String?, noteColor: Color = LN.textSecondary) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.system(size: 11)).foregroundStyle(LN.textSecondary)
            HStack(spacing: 4) {
                Text(value).font(.system(size: 16, weight: .semibold).monospacedDigit())
                    .foregroundStyle(LN.textPrimary)
                if let n = note {
                    Text(n).font(.system(size: 11, weight: .semibold)).foregroundStyle(noteColor)
                }
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(LN.fieldBg))
    }
}

// MARK: - macOS KPI 四联横条

struct KPIStripMac: View {
    let kpis: PortfolioKPIs

    var body: some View {
        HStack(spacing: 12) {
            card("持仓市值", value: LNFmt.money(kpis.marketValue), valueColor: LN.textPrimary)
            card("浮动盈亏", value: LNFmt.signedMoney(kpis.floatPnl),
                 note: LNFmt.signedPct(kpis.floatPnlPct), valueColor: kpis.floatPnl.pnlColor,
                 caption: "持仓开仓以来")
            // v1.4.1 Phase B:今日盈亏与浮动盈亏并排,各自标注口径。
            // 🔵#4 审后修:旧后端(缺 4 键)→ todayPnlAvailable==false,隐藏此卡而非显示假 ¥0。
            if kpis.todayPnlAvailable {
                card("今日盈亏", value: LNFmt.signedMoney(kpis.todayPnl),
                     note: kpis.todayPnlPartial ? "部分持仓缺今日行情数据" : nil,
                     noteColor: LN.textTertiary, valueColor: kpis.todayPnl.pnlColor,
                     caption: "今日已实现+今日浮动")
            }
            card("仓位", value: "\(kpis.positionCount)/3",
                 note: kpis.positionCount >= 3 ? "满仓" : "\(3 - kpis.positionCount) 可用",
                 noteColor: LN.amber, valueColor: LN.textPrimary)
            card("本周纪律执行率", value: "\(kpis.disciplineRate)%",
                 note: "▲\(kpis.disciplineTrend)", noteColor: LN.up, valueColor: LN.textPrimary)
        }
    }

    private func card(_ title: String, value: String, note: String? = nil,
                      noteColor: Color = LN.up, valueColor: Color, caption: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 11)).foregroundStyle(LN.textSecondary)
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                Text(value).font(.system(size: 23, weight: .semibold).monospacedDigit())
                    .foregroundStyle(valueColor)
                if let n = note {
                    Text(n).font(.system(size: 13, weight: .semibold).monospacedDigit())
                        .foregroundStyle(noteColor)
                }
            }
            if let c = caption {
                Text(c).font(.system(size: 9.5)).foregroundStyle(LN.textTertiary)
            }
        }
        .padding(EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 13, style: .continuous).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 13, style: .continuous).stroke(LN.hairline, lineWidth: 0.5))
        .shadow(color: Color(hex: 0x141E3C, alpha: 0.04), radius: 2, y: 1)
    }
}

// MARK: - 教练横幅(触损持仓时显示;本期占位文案 · 大脑阶段3)

struct CoachBanner: View {
    let stockName: String
    var compact: Bool = true
    let onMarkClose: () -> Void

    /// 占位文案(本期非真大脑;阶段3 接复盘历史)。
    private var bannerText: String {
        compact
        ? "已触止损线。铁律是铁律——别再「觉得会反弹」。次日开盘清掉它,我陪你。"
        : "已触止损线。铁律是铁律——你上次「总觉得会反弹」那 4000 块,就是这么没的。次日开盘清掉它,我陪你。"
    }

    var body: some View {
        let content = HStack(alignment: compact ? .top : .center, spacing: compact ? 11 : 13) {
            CoachAvatar(size: compact ? 30 : 32)
            VStack(alignment: .leading, spacing: compact ? 10 : 0) {
                (Text("\(stockName)").font(.system(size: compact ? 13.5 : 13.5, weight: .bold))
                    .foregroundStyle(LN.textPrimary)
                 + Text(bannerText).font(.system(size: compact ? 13.5 : 13.5))
                    .foregroundStyle(LN.textSecondary))
                    .lineSpacing(3)
                if compact { markButton }
            }
            if !compact { Spacer(); markButton }
        }

        return content
            .padding(compact ? EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16)
                             : EdgeInsets(top: 14, leading: 18, bottom: 14, trailing: 18))
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: compact ? 16 : 14, style: .continuous)
                    .fill(LinearGradient(
                        colors: [LN.down.opacity(0.08), LN.amber.opacity(0.05)],
                        startPoint: .leading, endPoint: .trailing))
            )
            .overlay(RoundedRectangle(cornerRadius: compact ? 16 : 14, style: .continuous)
                .stroke(LN.down.opacity(compact ? 0.18 : 0.16), lineWidth: 0.5))
    }

    private var markButton: some View {
        Button(action: onMarkClose) {
            Text("标记次日清仓")
                .font(.system(size: 12.5, weight: .semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, compact ? 15 : 14).padding(.vertical, compact ? 8 : 7)
                .background(RoundedRectangle(cornerRadius: compact ? 10 : 9).fill(LN.down))
        }
        .buttonStyle(.plain)
        .fixedSize()
    }
}
