//
//  RootView.swift
//  LinoN — 导航壳(平台分叉:iOS 底部 TabView / macOS 240px 玻璃侧栏)
//
//  本期 today 真数据;候选/复盘/记忆为占位空视图(阶段2/3 重建)。
//

import SwiftUI

struct RootView: View {
    @Bindable var model: AppModel
    @ObservedObject var config: AppConfig

    var body: some View {
        #if os(iOS)
        iosShell
        #else
        macShell
        #endif
    }

    // MARK: - iOS:底部 TabView

    #if os(iOS)
    private var iosShell: some View {
        TabView(selection: Binding(get: { model.view }, set: { model.view = $0 })) {
            tabContent(.today) { TodayViewIOS(model: model) }
                .tabItem { Label("今日", systemImage: "circle.circle") }.tag(AppView.today)
            tabContent(.candidates) { candidatesPlaceholder }
                .tabItem { Label("候选", systemImage: "list.bullet") }.tag(AppView.candidates)
            tabContent(.review) { reviewPlaceholder }
                .tabItem { Label("复盘", systemImage: "chart.bar") }.tag(AppView.review)
            tabContent(.memory) { memoryPlaceholder }
                .tabItem { Label("记忆", systemImage: "bookmark") }.tag(AppView.memory)
        }
        .tint(LN.accent)
        .overlay(alignment: .bottom) { toastOverlay.padding(.bottom, 96) }
        .sheet(isPresented: Binding(get: { model.modal != nil },
                                    set: { if !$0 { model.dismissModal() } })) {
            EntrySheetIOS(model: model)
        }
        .task { model.bind(config: config); await model.refresh() }
    }

    private func tabContent<V: View>(_ v: AppView, @ViewBuilder _ content: () -> V) -> some View {
        content()
    }
    #endif

    // MARK: - macOS:240px 玻璃侧栏

    #if os(macOS)
    private var macShell: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 240)
            Divider().overlay(LN.hairline)
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(minWidth: 920, minHeight: 600)
        .overlay(alignment: .bottom) { toastOverlay.padding(.bottom, 24) }
        .overlay { if model.modal != nil { modalOverlay } }
        .task { model.bind(config: config); await model.refresh() }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 9) {
                LNLogo(size: 27)
                Text("LinoN").font(.system(size: 14.5, weight: .semibold)).foregroundStyle(LN.textPrimary)
                Spacer()
                HStack(spacing: 4) {
                    Circle().fill(LN.up).frame(width: 6, height: 6)
                    Text("盯盘中").font(.system(size: 10, weight: .semibold)).foregroundStyle(LN.up)
                }
            }
            .padding(.horizontal, 16).padding(.top, 18).padding(.bottom, 16)

            Text("交易").font(.system(size: 10.5, weight: .semibold)).tracking(0.6)
                .foregroundStyle(LN.textTertiary)
                .padding(.horizontal, 16).padding(.bottom, 7)

            navItem(.today, "今日持仓", "circle.circle", badge: "\(model.holdings.count)")
            navItem(.candidates, "候选列表", "list.bullet", badge: "0")
            navItem(.review, "周复盘", "chart.bar", badge: "待", badgeColor: LN.amber)
            navItem(.memory, "记忆", "bookmark")

            Spacer()

            HStack(spacing: 10) {
                CoachAvatar(size: 30)
                VStack(alignment: .leading, spacing: 1) {
                    Text("教练在线").font(.system(size: 12, weight: .semibold)).foregroundStyle(LN.textPrimary)
                    Text("纪律执行率 \(model.portfolioKPIs.disciplineRate)%")
                        .font(.system(size: 11)).foregroundStyle(LN.textSecondary)
                }
                Spacer()
                Image(systemName: "chevron.right").font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(LN.textTertiary)
            }
            .padding(11)
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.62)))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(LN.hairline, lineWidth: 0.5))
            .padding(14)
        }
        .background(.ultraThinMaterial)
    }

    private func navItem(_ v: AppView, _ title: String, _ icon: String,
                         badge: String? = nil, badgeColor: Color = LN.textSecondary) -> some View {
        let active = model.view == v
        return Button(action: { model.view = v }) {
            HStack(spacing: 9) {
                Image(systemName: icon).font(.system(size: 14, weight: .medium))
                    .foregroundStyle(active ? LN.accent : LN.textSecondary)
                    .frame(width: 18)
                Text(title).font(.system(size: 13, weight: active ? .semibold : .regular))
                    .foregroundStyle(active ? LN.textPrimary : LN.textSecondary)
                Spacer()
                if let b = badge {
                    Text(b).font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(b == "待" ? badgeColor : (active ? LN.accent : LN.textTertiary))
                        .padding(.horizontal, 7).padding(.vertical, 1)
                        .background(Capsule().fill((b == "待" ? badgeColor : LN.textSecondary).opacity(0.14)))
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 9)
            .background(RoundedRectangle(cornerRadius: 9)
                .fill(active ? LN.accent.opacity(0.10) : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 10)
    }

    @ViewBuilder
    private var content: some View {
        switch model.view {
        case .today: TodayViewMac(model: model)
        case .candidates: candidatesPlaceholder
        case .review: reviewPlaceholder
        case .memory: memoryPlaceholder
        }
    }

    private var modalOverlay: some View {
        ZStack {
            Color.black.opacity(0.32).ignoresSafeArea()
                .onTapGesture { model.dismissModal() }
            EntryModalMac(model: model)
                .shadow(color: .black.opacity(0.2), radius: 30, y: 10)
        }
    }
    #endif

    // MARK: - 占位视图(阶段2/3)

    private var candidatesPlaceholder: some View {
        PlaceholderView(title: "候选列表 · 阶段2",
                        subtitle: "EOD 机械排序 + on-demand 深析。\n本期为导航占位,阶段2 重建。",
                        systemImage: "list.bullet.rectangle")
    }
    private var reviewPlaceholder: some View {
        PlaceholderView(title: "周复盘 · 阶段3",
                        subtitle: "纪律评分 + 执行率趋势 + 每笔点评。\n本期为导航占位,阶段3 重建。",
                        systemImage: "chart.bar.xaxis")
    }
    private var memoryPlaceholder: some View {
        PlaceholderView(title: "记忆 · 阶段3",
                        subtitle: "闭环结论 + 长期记忆 + 已平仓流水。\n本期为导航占位,阶段3 重建。",
                        systemImage: "bookmark")
    }

    @ViewBuilder
    private var toastOverlay: some View {
        if let toast = model.toast {
            ToastView(toast: toast)
                .id(toast.id)
        }
    }
}
