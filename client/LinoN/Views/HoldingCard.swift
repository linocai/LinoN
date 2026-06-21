//
//  HoldingCard.swift
//  LinoN — 持仓卡(白卡;触损红条+红边+红阴影)
//
//  iOS(compact=true):名/理由 在左,现价+涨跌 在右;双线;距盈距损+D pips;底部分隔线下 D 标签+按钮。
//  macOS(compact=false):名/理由 · 现价+涨跌 · 右侧"持仓交易日"D pips 横排;双线含成本刻度;
//                        距盈/距损/主力近 3 日 + 问教练/清仓录入。
//

import SwiftUI

struct HoldingCard: View {
    let model: HoldingCardModel
    var compact: Bool = true
    let onCoach: () -> Void
    let onClose: () -> Void

    private var pos: Position { model.position }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if compact { iosBody } else { macBody }
        }
        .padding(compact ? EdgeInsets(top: 16, leading: 18, bottom: 16, trailing: 18)
                         : EdgeInsets(top: 18, leading: 20, bottom: 16, trailing: 20))
        .background(
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: compact ? 18 : 16, style: .continuous)
                    .fill(LN.cardBg)
                if model.hitStop {
                    Rectangle().fill(LN.down).frame(width: 3)
                        .clipShape(RoundedRectangle(cornerRadius: compact ? 18 : 16, style: .continuous))
                }
            }
        )
        .overlay(
            RoundedRectangle(cornerRadius: compact ? 18 : 16, style: .continuous)
                .stroke(model.hitStop ? LN.down.opacity(0.28) : LN.hairline, lineWidth: 0.5)
        )
        .shadow(color: model.hitStop ? LN.down.opacity(0.09) : Color(hex: 0x141E3C, alpha: 0.05),
                radius: model.hitStop ? 12 : 3, y: model.hitStop ? 2 : 1)
    }

    // MARK: - iOS

    private var iosBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        Text(pos.name).font(.system(size: 17, weight: .semibold)).foregroundStyle(LN.textPrimary)
                        Text(pos.code).font(.system(size: 12).monospacedDigit()).foregroundStyle(LN.textTertiary)
                    }
                    ReasonChip(text: model.reasonText, tone: model.reasonTone)
                }
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 4) {
                    Text(LNFmt.price(model.price))
                        .font(.system(size: 25, weight: .semibold).monospacedDigit())
                        .foregroundStyle(LN.textPrimary)
                    Text("\(model.pnlPct.arrow) \(LNFmt.signedPct(model.pnlPct))")
                        .font(.system(size: 13, weight: .semibold).monospacedDigit())
                        .foregroundStyle(model.pnlPct.pnlColor)
                }
            }

            DualLineTrack(pnlPct: model.pnlPct, hitStop: model.hitStop,
                          stopLabel: model.stopLabel, takeLabel: model.takeLabel)
                .padding(.top, 14)

            HStack(spacing: 14) {
                distLabel("距盈", model.distTakeStr, LN.up)
                distLabel("距损", model.distStopStr, LN.textSecondary)
                Spacer()
                HoldingDayPips(day: model.day, hitStop: model.hitStop)
            }
            .padding(.top, 8)

            Divider().overlay(LN.hairline).padding(.top, 13)

            HStack {
                Text(model.dayLabel)
                    .font(.system(size: 11.5, weight: .semibold))
                    .foregroundStyle(model.dayIsRed ? LN.down : LN.textSecondary)
                Spacer()
                coachButton
                closeButton(label: "清仓")
            }
            .padding(.top, 13)
        }
    }

    // MARK: - macOS

    private var macBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(pos.name).font(.system(size: 17, weight: .semibold)).foregroundStyle(LN.textPrimary)
                        Text(pos.code).font(.system(size: 12).monospacedDigit()).foregroundStyle(LN.textTertiary)
                    }
                    ReasonChip(text: model.reasonText, tone: model.reasonTone)
                }
                .frame(minWidth: 150, alignment: .leading)

                VStack(alignment: .trailing, spacing: 4) {
                    Text(LNFmt.price(model.price))
                        .font(.system(size: 30, weight: .semibold).monospacedDigit())
                        .foregroundStyle(LN.textPrimary)
                    Text("\(model.pnlPct.arrow) \(LNFmt.signedPct(model.pnlPct))")
                        .font(.system(size: 14, weight: .semibold).monospacedDigit())
                        .foregroundStyle(model.pnlPct.pnlColor)
                }
                .frame(minWidth: 120, alignment: .trailing)

                Spacer(minLength: 8)

                VStack(alignment: .trailing, spacing: 6) {
                    Text("持仓交易日")
                        .font(.system(size: 10.5, weight: .semibold))
                        .tracking(0.5)
                        .foregroundStyle(LN.textTertiary)
                    HoldingDayPips(day: model.day, hitStop: model.hitStop)
                    Text(model.dayLabel.replacingOccurrences(of: "D\(model.day) · ", with: "D\(model.day) · "))
                        .font(.system(size: 11.5, weight: model.dayIsRed ? .semibold : .regular))
                        .foregroundStyle(model.dayIsRed ? LN.down : LN.textSecondary)
                }
            }

            DualLineTrack(pnlPct: model.pnlPct, hitStop: model.hitStop,
                          stopLabel: model.stopLabel, takeLabel: model.takeLabel,
                          costLabel: model.costLabel)
                .padding(.top, 12)

            HStack(spacing: 22) {
                distLabel("距止盈", model.distTakeStr, LN.up)
                distLabel("距止损", model.distStopStr, LN.textSecondary)
                HStack(spacing: 5) {
                    Text("主力近 3 日").font(.system(size: 12.5)).foregroundStyle(LN.textSecondary)
                    Text(model.flow3d).font(.system(size: 12.5, weight: .semibold).monospacedDigit())
                        .foregroundStyle(model.flow3d.contains("-") ? LN.down : LN.up)
                }
                Spacer()
                coachButtonBordered
                closeButton(label: "清仓录入")
            }
            .padding(.top, 10)
        }
    }

    // MARK: - 小部件

    private func distLabel(_ k: String, _ v: String, _ color: Color) -> some View {
        HStack(spacing: 4) {
            Text(k).font(.system(size: 11.5)).foregroundStyle(LN.textSecondary)
            Text(v).font(.system(size: 11.5, weight: .semibold).monospacedDigit()).foregroundStyle(color)
        }
        .fixedSize()
    }

    private var coachButton: some View {
        Button(action: onCoach) {
            Text("问教练")
                .font(.system(size: 12.5, weight: .semibold))
                .foregroundStyle(LN.accent)
                .padding(.horizontal, 14).padding(.vertical, 7)
                .background(RoundedRectangle(cornerRadius: 9).fill(LN.accent.opacity(0.09)))
        }
        .buttonStyle(.plain)
    }

    private var coachButtonBordered: some View {
        Button(action: onCoach) {
            Text("问教练")
                .font(.system(size: 12.5, weight: .semibold))
                .foregroundStyle(LN.accent)
                .padding(.horizontal, 14).padding(.vertical, 6)
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(LN.accent.opacity(0.3), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    private func closeButton(label: String) -> some View {
        Button(action: onClose) {
            Text(label)
                .font(.system(size: 12.5, weight: .semibold))
                .foregroundStyle(model.hitStop ? .white : LN.textSecondary)
                .padding(.horizontal, 14).padding(.vertical, 7)
                .background(RoundedRectangle(cornerRadius: 9)
                    .fill(model.hitStop ? LN.down : LN.chipNeutral))
        }
        .buttonStyle(.plain)
    }
}
