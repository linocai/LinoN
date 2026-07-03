//
//  EntrySheets.swift
//  LinoN — 开仓 / 清仓录入(iOS .sheet 底部 · macOS 居中 modal)
//
//  开仓字段:代码/名称/买入价/数量/进场理由;止损线只读派生 买入价×0.95,拒绝手填。
//  清仓:该票 + 实时盈亏 + 卖出价 + 时间(默认次日开盘 09:30,只读)。
//  v1.3.0 Phase D2:代码满 6 位或输入框失焦时查一次相关性护栏(GET /positions/correlation);
//  命中同行业已持仓 → 表单内警示条(警告色,只提示不拦)。
//

import SwiftUI

// MARK: - 开仓表单内容(共享)

struct OpenFormContent: View {
    @Bindable var model: AppModel
    var compact: Bool
    @FocusState private var codeFieldFocused: Bool

    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                field("代码", text: $model.form.code, placeholder: "603606", mono: true, focused: $codeFieldFocused)
                field("名称", text: $model.form.name, placeholder: "东方电缆")
            }
            HStack(spacing: 12) {
                field("买入价", text: $model.form.price, placeholder: "48.30", mono: true)
                field("数量(股)", text: $model.form.qty, placeholder: "200", mono: true)
            }
            derivedStopRow
            field("进场理由(一句话)", text: $model.form.reason, placeholder: "平台突破 · 放量站稳")
            correlationWarningRow
        }
        // 代码满 6 位即查一次(不逐字符打请求);失焦再兜底查一次(改小/粘贴场景)。
        .onChange(of: model.form.code) { _, newValue in
            let bare = newValue.trimmingCharacters(in: .whitespaces)
            if bare.count == 6 { Task { await model.checkCorrelation(code: bare) } }
        }
        .onChange(of: codeFieldFocused) { wasFocused, isFocused in
            if wasFocused, !isFocused { Task { await model.checkCorrelation(code: model.form.code) } }
        }
    }

    /// 相关性警示条(警告色 amber,非红,不误导;只提示不禁用确认按钮)。命中才显示。
    @ViewBuilder private var correlationWarningRow: some View {
        if let conflict = model.correlationConflict, conflict.conflict, let first = conflict.conflictWith.first {
            HStack(alignment: .top, spacing: 8) {
                Text("⚠").font(.system(size: 13, weight: .semibold)).foregroundStyle(LN.amber)
                Text("与持仓 \(first.name)(\(first.industry))同主线,注意仓位集中")
                    .font(.system(size: 12, weight: .medium)).foregroundStyle(LN.amber)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            .frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: 12).fill(LN.amber.opacity(0.08)))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(LN.amber.opacity(0.25), lineWidth: 0.5))
        }
    }

    /// 止损线只读派生展示(虚边红框 + ×0.95)。
    private var derivedStopRow: some View {
        HStack(spacing: 8) {
            Image(systemName: "checkmark.seal")
                .font(.system(size: 13, weight: .semibold)).foregroundStyle(LN.down)
            Text("止损线 · 系统派生").font(.system(size: 12, weight: .semibold)).foregroundStyle(LN.textSecondary)
            Spacer()
            Text(model.form.derivedStop.map { "¥" + LNFmt.price($0) } ?? "待填买入价")
                .font(.system(size: 15, weight: .semibold).monospacedDigit())
                .foregroundStyle(LN.down)
            Text("×0.95").font(.system(size: 11)).foregroundStyle(LN.textTertiary)
        }
        .padding(.horizontal, 14).padding(.vertical, 11)
        .frame(maxWidth: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(LN.down.opacity(0.04))
                .overlay(RoundedRectangle(cornerRadius: 12)
                    .strokeBorder(style: StrokeStyle(lineWidth: 1, dash: [4]))
                    .foregroundStyle(LN.textTertiary))
        )
    }

    private func field(_ label: String, text: Binding<String>, placeholder: String, mono: Bool = false,
                       focused: FocusState<Bool>.Binding? = nil) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(.system(size: 11.5, weight: .semibold)).foregroundStyle(LN.textSecondary)
            Group {
                if let focused {
                    TextField(placeholder, text: text).focused(focused)
                } else {
                    TextField(placeholder, text: text)
                }
            }
                .textFieldStyle(.plain)
                .font(.system(size: 15).monospacedDigit())
                .foregroundStyle(LN.textPrimary)
                .padding(.horizontal, 14).padding(.vertical, 12)
                .background(RoundedRectangle(cornerRadius: 12).fill(LN.cardBg))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(LN.textSecondary.opacity(0.16), lineWidth: 1))
                #if os(iOS)
                .autocorrectionDisabled()
                #endif
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - 清仓表单内容(共享)

struct CloseFormContent: View {
    @Bindable var model: AppModel

    private var pos: Position? { model.closeCode.flatMap { model.holding(byCode: $0) } }

    var body: some View {
        VStack(spacing: 14) {
            if let p = pos {
                HStack {
                    HStack(spacing: 8) {
                        Text(p.name).font(.system(size: 16, weight: .semibold)).foregroundStyle(LN.textPrimary)
                        Text(p.code).font(.system(size: 12).monospacedDigit()).foregroundStyle(LN.textTertiary)
                    }
                    Spacer()
                    Text(LNFmt.signedPct(currentPnl))
                        .font(.system(size: 15, weight: .semibold).monospacedDigit())
                        .foregroundStyle(currentPnl.pnlColor)
                }
                .padding(.horizontal, 16).padding(.vertical, 14)
                .background(RoundedRectangle(cornerRadius: 14).fill(LN.down.opacity(0.06)))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.down.opacity(0.18), lineWidth: 0.5))

                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("卖出价").font(.system(size: 11.5, weight: .semibold)).foregroundStyle(LN.textSecondary)
                        TextField("", text: $model.closeSellPrice)
                            .textFieldStyle(.plain)
                            .font(.system(size: 15).monospacedDigit())
                            .foregroundStyle(LN.textPrimary)
                            .padding(.horizontal, 14).padding(.vertical, 12)
                            .background(RoundedRectangle(cornerRadius: 12).fill(LN.cardBg))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(LN.textSecondary.opacity(0.16), lineWidth: 1))
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        Text("时间").font(.system(size: 11.5, weight: .semibold)).foregroundStyle(LN.textSecondary)
                        Text("次日开盘 09:30")
                            .font(.system(size: 14)).foregroundStyle(LN.textSecondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 14).padding(.vertical, 12)
                            .background(RoundedRectangle(cornerRadius: 12).fill(Color(hex: 0xF6F6F8)))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(LN.textSecondary.opacity(0.16), lineWidth: 1))
                    }
                }
                (Text("清仓后停止监控、结算流水并归档到「记忆」。")
                    .foregroundStyle(LN.textSecondary)
                 + Text("全仓卖出,无减仓/做 T。").font(.system(size: 12, weight: .semibold)).foregroundStyle(LN.textSecondary))
                    .font(.system(size: 12))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var currentPnl: Double {
        guard let p = pos else { return 0 }
        let sell = Double(model.closeSellPrice) ?? p.price
        return p.buyPrice == 0 ? 0 : (sell - p.buyPrice) / p.buyPrice * 100
    }
}

// MARK: - iOS bottom sheet 容器

struct EntrySheetIOS: View {
    @Bindable var model: AppModel

    var body: some View {
        let isOpen = model.modal == .open
        VStack(spacing: 0) {
            Capsule().fill(LN.textSecondary.opacity(0.22)).frame(width: 38, height: 5)
                .padding(.top, 10).padding(.bottom, 16)
            VStack(alignment: .leading, spacing: 3) {
                Text(isOpen ? "开仓录入" : "清仓录入")
                    .font(.system(size: 19, weight: .bold)).foregroundStyle(LN.textPrimary)
                Text(isOpen ? "全仓买入 · 录入即建仓并快照" : "全仓卖出 · 结算并归档")
                    .font(.system(size: 12.5)).foregroundStyle(LN.textSecondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.bottom, 18)

            if isOpen { OpenFormContent(model: model, compact: true) }
            else { CloseFormContent(model: model) }

            HStack(spacing: 10) {
                Button(action: { model.dismissModal() }) {
                    Text("取消").font(.system(size: 14.5, weight: .semibold))
                        .foregroundStyle(LN.textSecondary)
                        .padding(.horizontal, 22).padding(.vertical, 14)
                        .background(RoundedRectangle(cornerRadius: 14).fill(LN.textSecondary.opacity(0.08)))
                }
                .buttonStyle(.plain)
                Button(action: { Task { isOpen ? await model.submitOpen() : await model.submitClose() } }) {
                    Text(isOpen ? "确认开仓" : "确认清仓")
                        .font(.system(size: 14.5, weight: .semibold)).foregroundStyle(.white)
                        .frame(maxWidth: .infinity).padding(.vertical, 14)
                        .background(RoundedRectangle(cornerRadius: 14).fill(isOpen ? LN.up : LN.down))
                }
                .buttonStyle(.plain)
            }
            .padding(.top, 20)
        }
        .padding(.horizontal, 20).padding(.bottom, 30)
        .background(Color(hex: 0xFCFCFD))
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.hidden)
    }
}

// MARK: - macOS 居中 modal 容器

struct EntryModalMac: View {
    @Bindable var model: AppModel

    var body: some View {
        let isOpen = model.modal == .open
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 3) {
                Text(isOpen ? "开仓录入" : "清仓录入")
                    .font(.system(size: 18, weight: .bold)).foregroundStyle(LN.textPrimary)
                Text(isOpen ? "全仓买入 · 录入即建仓并快照" : "全仓卖出 · 结算并归档")
                    .font(.system(size: 12)).foregroundStyle(LN.textSecondary)
            }
            .padding(.bottom, 18)

            if isOpen { OpenFormContent(model: model, compact: false) }
            else { CloseFormContent(model: model) }

            HStack(spacing: 10) {
                Spacer()
                Button(action: { model.dismissModal() }) {
                    Text("取消").font(.system(size: 13.5, weight: .semibold))
                        .foregroundStyle(LN.textSecondary)
                        .padding(.horizontal, 18).padding(.vertical, 11)
                        .background(RoundedRectangle(cornerRadius: 10).fill(LN.textSecondary.opacity(0.08)))
                }
                .buttonStyle(.plain)
                Button(action: { Task { isOpen ? await model.submitOpen() : await model.submitClose() } }) {
                    Text(isOpen ? "确认开仓" : "确认清仓")
                        .font(.system(size: 13.5, weight: .semibold)).foregroundStyle(.white)
                        .padding(.horizontal, 22).padding(.vertical, 11)
                        .background(RoundedRectangle(cornerRadius: 10).fill(isOpen ? LN.up : LN.down))
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.return, modifiers: [])
            }
            .padding(.top, 20)
        }
        .padding(24)
        .frame(width: 520)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color(hex: 0xFCFCFD)))
    }
}
