//
//  TodayView.swift
//  LinoN — 今日持仓(双端;iOS 垂直 ScrollView / macOS 顶部四联横条 + 内联工具栏)
//
//  照 README §1:大标题/KPI Hero/教练横幅(触损占位文案)/HoldingCard 列表。
//

import SwiftUI

// MARK: - iOS

struct TodayViewIOS: View {
    @Bindable var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                KPIHeroIOS(kpis: model.portfolioKPIs)
                if let alert = model.alertHolding {
                    CoachBanner(stockName: alert.name, compact: true) {
                        model.openClose(code: alert.code)
                    }
                    .transition(.move(edge: .top).combined(with: .opacity))
                }
                ForEach(model.holdings) { pos in
                    HoldingCard(model: cardModel(pos), compact: true,
                                onCoach: { model.selectedCode = pos.code; /* 阶段2 深析/教练 */ },
                                onClose: { model.openClose(code: pos.code) })
                }
                if model.holdings.isEmpty {
                    Text("空仓中 · 去候选挑一只 →")
                        .font(.system(size: 13.5)).foregroundStyle(LN.textTertiary)
                        .frame(maxWidth: .infinity).padding(.vertical, 50)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 104)
        }
        .background(LN.pageBgIOS)
        .refreshable { await model.refresh() }
        .animation(.easeOut(duration: 0.3), value: model.holdings.map(\.id))
    }

    private var header: some View {
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 5) {
                Text("今日").font(LNFont.largeTitle).foregroundStyle(LN.textPrimary)
                Text("\(dateLine) · \(model.holdings.count)/3 持仓")
                    .font(.system(size: 13)).foregroundStyle(LN.textSecondary)
            }
            Spacer()
            Button(action: { model.openEntry() }) {
                Image(systemName: "plus")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(LN.accent)
                    .frame(width: 38, height: 38)
                    .background(Circle().fill(LN.accent.opacity(0.1)))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 4)
    }

    private func cardModel(_ p: Position) -> HoldingCardModel {
        HoldingCardModel(position: p, day: model.holdingDay(p), isForceClose: model.shouldForceClose(p))
    }

    private var dateLine: String { LNDate.todayChinese() }
}

// MARK: - macOS

struct TodayViewMac: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    KPIStripMac(kpis: model.portfolioKPIs)
                    if let alert = model.alertHolding {
                        CoachBanner(stockName: alert.name, compact: false) {
                            model.openClose(code: alert.code)
                        }
                    }
                    VStack(spacing: 12) {
                        ForEach(model.holdings) { pos in
                            HoldingCard(model: cardModel(pos), compact: false,
                                        onCoach: { model.selectedCode = pos.code },
                                        onClose: { model.openClose(code: pos.code) })
                        }
                    }
                    if model.holdings.isEmpty {
                        Text("空仓中 · 注意力交给候选列表 →")
                            .font(.system(size: 13.5)).foregroundStyle(LN.textTertiary)
                            .frame(maxWidth: .infinity).padding(.vertical, 60)
                    }
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 22)
            }
            .background(LN.pageBg)
        }
    }

    private var toolbar: some View {
        HStack(spacing: 10) {
            Text("今日持仓").font(.system(size: 15, weight: .semibold)).foregroundStyle(LN.textPrimary)
            Text("\(LNDate.todayChinese()) · \(model.holdings.count)/3 持仓")
                .font(.system(size: 12.5)).foregroundStyle(LN.textTertiary)
            Spacer()
            Button(action: { model.openEntry() }) {
                Label("开仓录入", systemImage: "plus")
                    .font(.system(size: 12.5, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .background(RoundedRectangle(cornerRadius: 8).fill(LN.accent))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 22)
        .frame(height: 52)
        .background(.ultraThinMaterial)
        .overlay(Divider().overlay(LN.hairline), alignment: .bottom)
    }

    private func cardModel(_ p: Position) -> HoldingCardModel {
        HoldingCardModel(position: p, day: model.holdingDay(p), isForceClose: model.shouldForceClose(p))
    }
}

// MARK: - 日期

enum LNDate {
    static func todayChinese(_ date: Date = Date()) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        f.dateFormat = "M 月 d 日 EEEE"
        return f.string(from: date)
    }
}
