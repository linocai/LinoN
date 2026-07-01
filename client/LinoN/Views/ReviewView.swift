//
//  ReviewView.swift
//  LinoN — 周复盘(双端;纪律评分 + 执行率趋势 + 每笔点评 + 下周注意;照 README §4)
//
//  评分 Hero(绿蓝渐变)+ 趋势柱状(近6周,最后周高亮,Y 轴 min-7~max+2 归一,柱顶标值)
//  + 每笔点评卡(good 绿 chip / red 红 chip + pnl + comment)+ 下周注意(琥珀渐变,可编辑)
//  + 未平持仓提示区(openHoldings)。空周态诚实展示 sampleNote。
//  iOS 大标题 ScrollView / macOS 内容区(内联标题栏)。绿涨红跌。
//

import SwiftUI

// MARK: - iOS

struct ReviewViewIOS: View {
    @Bindable var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                ReviewContent(model: model, compact: true)
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 104)
        }
        .background(LN.pageBgIOS)
        .refreshable { await model.loadReview() }
        .task { if model.review == nil { await model.loadReview() } }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("周复盘").font(LNFont.largeTitle).foregroundStyle(LN.textPrimary)
            Text(model.review.map { "本周 \($0.week) · 纪律执行率 \($0.disciplineRate)%" }
                 ?? "纪律评分 · 执行率趋势 · 每笔点评")
                .font(.system(size: 13)).foregroundStyle(LN.textSecondary)
        }
        .padding(.horizontal, 4)
    }
}

// MARK: - macOS

struct ReviewViewMac: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Text("周复盘").font(.system(size: 17, weight: .semibold)).foregroundStyle(LN.textPrimary)
                if let r = model.review {
                    Text(r.week).font(.system(size: 12, weight: .medium)).foregroundStyle(LN.textSecondary)
                        .padding(.horizontal, 8).padding(.vertical, 2)
                        .background(Capsule().fill(LN.textSecondary.opacity(0.08)))
                }
                Spacer()
                Button(action: { Task { await model.loadReview() } }) {
                    Image(systemName: "arrow.clockwise").font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(LN.accent)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 24).padding(.vertical, 16)
            Divider().overlay(LN.hairline)
            ScrollView {
                ReviewContent(model: model, compact: false)
                    .padding(24)
            }
        }
        .background(LN.pageBg)
        .task { if model.review == nil { await model.loadReview() } }
    }
}

// MARK: - 共享内容

private struct ReviewContent: View {
    @Bindable var model: AppModel
    let compact: Bool

    var body: some View {
        if let r = model.review {
            VStack(alignment: .leading, spacing: 16) {
                ScoreHero(review: r)
                TrendChart(points: r.trend)
                if r.trades.isEmpty {
                    emptyWeekCard(r.sampleNote)
                } else {
                    tradesSection(r)
                }
                if !r.openHoldings.isEmpty {
                    openHoldingsSection(r.openHoldings)
                }
                NextWeekNoteCard(model: model)
            }
        } else {
            loadingOrEmpty
        }
    }

    @ViewBuilder
    private var loadingOrEmpty: some View {
        if model.reviewLoading {
            HStack { Spacer(); ProgressView().controlSize(.large); Spacer() }
                .padding(.vertical, 60)
        } else {
            PlaceholderView(title: "暂无复盘数据",
                            subtitle: "本周还没有已闭合交易。清仓后这里会算出你的纪律执行率。",
                            systemImage: "chart.bar.xaxis")
        }
    }

    private func emptyWeekCard(_ note: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("本周点评").font(.system(size: 13, weight: .semibold)).foregroundStyle(LN.textPrimary)
            HStack(spacing: 10) {
                Image(systemName: "tray").font(.system(size: 16)).foregroundStyle(LN.textTertiary)
                Text(note.isEmpty ? "本周 0 笔闭合" : note)
                    .font(.system(size: 13)).foregroundStyle(LN.textSecondary)
                Spacer()
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 12).fill(LN.cardBg))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(LN.hairline, lineWidth: 0.5))
        }
    }

    private func tradesSection(_ r: Review) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("每笔点评").font(.system(size: 13, weight: .semibold)).foregroundStyle(LN.textPrimary)
                Spacer()
                Text(r.sampleNote).font(.system(size: 11)).foregroundStyle(LN.textTertiary)
            }
            ForEach(r.trades) { t in ReviewTradeCard(trade: t) }
        }
    }

    private func openHoldingsSection(_ items: [OpenHolding]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: "hourglass").font(.system(size: 12)).foregroundStyle(LN.amber)
                Text("还有 \(items.count) 只在持(未闭合,不计入本周执行率)")
                    .font(.system(size: 12, weight: .semibold)).foregroundStyle(LN.textSecondary)
            }
            ForEach(items) { h in
                HStack(spacing: 10) {
                    Text(h.name).font(.system(size: 13, weight: .semibold)).foregroundStyle(LN.textPrimary)
                    Text(h.code).font(.system(size: 11)).foregroundStyle(LN.textTertiary)
                    Spacer()
                    Text("成本 \(LNFmt.price(h.buyPrice))").font(.system(size: 12)).foregroundStyle(LN.textSecondary)
                    Text("D\(h.tradeDay)").font(.system(size: 11, weight: .bold)).foregroundStyle(LN.amber)
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(Capsule().fill(LN.amber.opacity(0.12)))
                }
                .padding(.horizontal, 14).padding(.vertical, 11)
                .background(RoundedRectangle(cornerRadius: 11).fill(LN.cardBg))
                .overlay(RoundedRectangle(cornerRadius: 11).stroke(LN.hairline, lineWidth: 0.5))
            }
        }
    }
}

// MARK: - 评分 Hero(绿蓝渐变卡)

private struct ScoreHero: View {
    let review: Review

    var body: some View {
        HStack(alignment: .center, spacing: 20) {
            VStack(alignment: .leading, spacing: 2) {
                Text("纪律评分").font(.system(size: 12, weight: .semibold)).foregroundStyle(.white.opacity(0.85))
                Text("\(review.score)")
                    .font(.system(size: 48, weight: .bold, design: .rounded)).foregroundStyle(.white)
                Text("执行率 \(review.disciplineRate)% · \(trendLabel)")
                    .font(.system(size: 12)).foregroundStyle(.white.opacity(0.9))
            }
            Spacer()
            HStack(spacing: 16) {
                stat("交易", "\(review.trades.count)")
                stat("盈利", "\(profitCount)")
                stat("标红", "\(review.redFlags.count)")
            }
        }
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 18)
                .fill(LinearGradient(colors: [LN.up, LN.accent],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
        )
    }

    private var trendLabel: String {
        if review.rateTrend > 0 { return "环比 ▲\(review.rateTrend)%" }
        if review.rateTrend < 0 { return "环比 ▼\(abs(review.rateTrend))%" }
        return "环比 持平"
    }

    // 盈利笔数(pnl 串以 '+' 开头即盈利;绿涨红跌)。
    private var profitCount: Int {
        review.trades.filter { $0.pnl.hasPrefix("+") }.count
    }

    private func stat(_ label: String, _ value: String) -> some View {
        VStack(spacing: 3) {
            Text(value).font(.system(size: 20, weight: .bold, design: .rounded)).foregroundStyle(.white)
            Text(label).font(.system(size: 11)).foregroundStyle(.white.opacity(0.8))
        }
    }
}

// MARK: - 趋势柱状(近6周;Y 轴 min-7~max+2 归一;最后周高亮)

private struct TrendChart: View {
    let points: [WeekPoint]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("近 6 周执行率趋势").font(.system(size: 13, weight: .semibold)).foregroundStyle(LN.textPrimary)
            HStack(alignment: .bottom, spacing: 10) {
                ForEach(Array(points.enumerated()), id: \.element.id) { idx, p in
                    let isLast = idx == points.count - 1
                    VStack(spacing: 6) {
                        Text("\(p.value)")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(isLast ? LN.up : LN.textSecondary)
                        RoundedRectangle(cornerRadius: 5)
                            .fill(isLast
                                  ? AnyShapeStyle(LinearGradient(colors: [LN.up, LN.accent],
                                                    startPoint: .top, endPoint: .bottom))
                                  : AnyShapeStyle(LN.textSecondary.opacity(0.28)))
                            .frame(height: barHeight(p.value))
                        Text(p.label).font(.system(size: 10)).foregroundStyle(LN.textTertiary)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            .frame(height: 130)
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 14).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.hairline, lineWidth: 0.5))
    }

    // Y 轴按 min-7 ~ max+2 归一(README §4:让差异可见);柱高映射到 [8, 90]px。
    private func barHeight(_ value: Int) -> CGFloat {
        let values = points.map(\.value)
        let lo = max(0, (values.min() ?? 0) - 7)
        let hi = min(100, (values.max() ?? 100) + 2)
        let span = max(1, hi - lo)
        let ratio = CGFloat(max(0, value - lo)) / CGFloat(span)
        return 8 + ratio * 82
    }
}

// MARK: - 每笔点评卡

private struct ReviewTradeCard: View {
    let trade: ReviewTrade

    var body: some View {
        let isRed = trade.tag == .red
        return HStack(alignment: .top, spacing: 12) {
            // good 绿 chip / red 红 chip
            Text(isRed ? "标红" : "肯定")
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(isRed ? LN.down : LN.up)
                .padding(.horizontal, 8).padding(.vertical, 3)
                .background(Capsule().fill((isRed ? LN.down : LN.up).opacity(0.12)))
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(trade.name).font(.system(size: 13.5, weight: .semibold)).foregroundStyle(LN.textPrimary)
                    Text(trade.code).font(.system(size: 11)).foregroundStyle(LN.textTertiary)
                    Spacer()
                    Text(trade.pnl)
                        .font(.system(size: 13, weight: .bold, design: .rounded))
                        .foregroundStyle(pnlColor)
                }
                Text(trade.comment).font(.system(size: 12)).foregroundStyle(LN.textSecondary)
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 12).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 12)
            .stroke(isRed ? LN.down.opacity(0.22) : LN.hairline, lineWidth: isRed ? 1 : 0.5))
    }

    // 绿涨红跌:pnl 串 '+' 开头 → 绿;'-' 开头 → 红。
    private var pnlColor: Color { trade.pnl.hasPrefix("-") ? LN.down : LN.up }
}

// MARK: - 下周注意(琥珀渐变,可编辑)

private struct NextWeekNoteCard: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: "flag.checkered").font(.system(size: 13)).foregroundStyle(LN.amber)
                Text("下周注意").font(.system(size: 13, weight: .semibold)).foregroundStyle(LN.textPrimary)
                Spacer()
                Text("会写入交易上下文").font(.system(size: 10)).foregroundStyle(LN.textTertiary)
            }
            TextEditor(text: $model.reviewNoteDraft)
                .font(.system(size: 13)).foregroundStyle(LN.textPrimary)
                .frame(minHeight: 64)
                .scrollContentBackground(.hidden)
                .padding(8)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.white.opacity(0.7)))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(LN.amber.opacity(0.2), lineWidth: 0.5))
            HStack {
                Spacer()
                Button(action: { Task { await model.saveReviewNote() } }) {
                    Group {
                        if model.reviewSaving {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("保存").font(.system(size: 13, weight: .semibold)).foregroundStyle(.white)
                        }
                    }
                    .padding(.horizontal, 20).padding(.vertical, 8)
                    .background(RoundedRectangle(cornerRadius: 10).fill(LN.amber))
                }
                .buttonStyle(.plain)
                .disabled(model.reviewSaving)
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(LinearGradient(colors: [Color(hex: 0xFFF8EC), Color(hex: 0xFFF1DA)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
        )
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.amber.opacity(0.22), lineWidth: 1))
    }
}
