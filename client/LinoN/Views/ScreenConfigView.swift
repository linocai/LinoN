//
//  ScreenConfigView.swift
//  LinoN — 选股参数调参屏(双端共享内容;plan §4 Phase B3)
//
//  权重区(9 滑块 + 正权和提示)+ 阈值区(12 项数字步进)。保存 → PUT 全部当前值(后端
//  归一/夹紧后回填,提示"下次刷新生效",不自动触发候选 refresh);恢复默认 → PUT 空
//  config `{}`(后端清用户行,回填全默认)。入口挂 SettingsView(iOS NavigationLink /
//  macOS 区块,均用 sheet 呈现,避开 macOS Settings 场景无 NavigationStack 的坑)。
//

import SwiftUI

struct ScreenConfigView: View {
    @Bindable var model: AppModel

    var body: some View {
        Form {
            weightSection
            thresholdSection
            actionSection
        }
        .formStyle(.grouped)
        #if os(iOS)
        .navigationTitle("选股参数")
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .task { await model.loadScreenConfig() }
    }

    // MARK: - 权重区

    private var weightSection: some View {
        Section {
            ForEach(ScreenConfigSpec.weightFields, id: \.key) { field in
                weightRow(field)
            }
            weightSumNote
        } header: {
            Text("排序权重")
        } footer: {
            Text("正权 8 项之和应为 1.00;和≠1 时保存后端自动归一(客户端不自算归一)。")
        }
    }

    private func weightRow(_ field: ScreenConfigField) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(field.label).font(.system(size: 13.5))
                Spacer()
                Text(String(format: "%.2f", binding(for: field.key).wrappedValue))
                    .font(.system(size: 13).monospacedDigit())
                    .foregroundStyle(LN.textSecondary)
            }
            Slider(value: binding(for: field.key), in: field.range, step: field.step)
        }
        .padding(.vertical, 2)
    }

    private var weightSumNote: some View {
        let sum = model.screenConfigPositiveWeightSum
        let ok = abs(sum - 1.0) < 0.005
        return HStack(spacing: 6) {
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(ok ? LN.up : LN.amber)
            Text("正权之和 \(String(format: "%.2f", sum))")
                .font(.system(size: 12.5))
                .foregroundStyle(ok ? LN.textSecondary : LN.amber)
        }
    }

    // MARK: - 阈值区

    private var thresholdSection: some View {
        Section {
            ForEach(ScreenConfigSpec.thresholdFields, id: \.key) { field in
                thresholdRow(field)
            }
        } header: {
            Text("阈值")
        } footer: {
            Text("越界值保存时由后端夹紧到合法范围,不会报错。")
        }
    }

    private func thresholdRow(_ field: ScreenConfigField) -> some View {
        HStack {
            Text(field.label).font(.system(size: 13.5))
            Spacer()
            Stepper(value: binding(for: field.key), in: field.range, step: field.step) {
                Text(thresholdValueText(field))
                    .font(.system(size: 13).monospacedDigit())
                    .foregroundStyle(LN.textSecondary)
            }
            .fixedSize()
        }
    }

    private func thresholdValueText(_ field: ScreenConfigField) -> String {
        let v = binding(for: field.key).wrappedValue
        let numStr = field.isInteger ? "\(Int(v.rounded()))" : String(format: "%.2f", v)
        return numStr + field.unit
    }

    // MARK: - 保存 / 恢复默认

    private var actionSection: some View {
        Section {
            Button {
                Task { await model.saveScreenConfig() }
            } label: {
                HStack {
                    if model.screenConfigSaving { ProgressView().controlSize(.small) }
                    Text("保存")
                }
            }
            .disabled(model.screenConfigSaving)

            Button(role: .destructive) {
                Task { await model.restoreDefaultScreenConfig() }
            } label: {
                Text("恢复默认")
            }
            .disabled(model.screenConfigSaving)

            if let updatedAt = model.screenConfigUpdatedAt {
                LabeledContent("最近保存") {
                    Text(updatedAt).font(.system(size: 12).monospaced()).foregroundStyle(LN.textTertiary)
                }
            }
        } footer: {
            Text("保存/恢复默认后不自动重算候选,下次手动点「刷新」时生效。")
        }
    }

    // MARK: - 绑定辅助

    /// 缺键(旧后端/尚未加载)时兜 `screenConfigDefaults`,仍缺则兜 0——不崩、不闪断连击。
    private func binding(for key: String) -> Binding<Double> {
        Binding(
            get: { model.screenConfig[key] ?? model.screenConfigDefaults[key] ?? 0 },
            set: { model.screenConfig[key] = $0 }
        )
    }
}
