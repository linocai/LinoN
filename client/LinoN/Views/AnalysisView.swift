//
//  AnalysisView.swift
//  LinoN — 深度分析 / 对话(双端;照 README §3)
//
//  全屏(iOS 隐藏 TabBar via fullScreenCover / macOS 覆盖内容区)。
//  顶部返回 + 股票上下文条 + 聊天 thread + 底部 composer。
//  四类消息(ChatRole):user 蓝气泡 / assistant 白气泡+◆ / analysis 结构化深析卡
//  (三轴 pill + verdict 渐变区 + plan,可进附「全仓买入并录入」绿按钮)/ coach 红橙卡。
//  深析卡显著标注 fund_asof(资金面=截至 {date} EOD,今日盘中资金未知)。
//

import SwiftUI

struct AnalysisView: View {
    @Bindable var model: AppModel
    var compact: Bool        // iOS=true 单列堆叠 / macOS=false 双列

    var body: some View {
        VStack(spacing: 0) {
            contextBar
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(model.thread) { msg in
                            messageView(msg).id(msg.id)
                        }
                        if model.analysisLoading {
                            thinkingRow
                        }
                        Color.clear.frame(height: 1).id("bottom")
                    }
                    .padding(.horizontal, compact ? 16 : 26)
                    .padding(.vertical, compact ? 16 : 22)
                }
                .background(LN.pageBg)
                .onChange(of: model.thread.count) { _, _ in
                    withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo("bottom", anchor: .bottom) }
                }
            }
            composer
        }
        .background(LN.pageBg)
    }

    // MARK: - 顶部上下文条

    private var contextBar: some View {
        let ctx = model.analysisContext
        return HStack(spacing: 12) {
            Button(action: { model.backFromAnalysis() }) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 15, weight: .semibold)).foregroundStyle(LN.textSecondary)
                    .frame(width: 30, height: 30)
                    .background(RoundedRectangle(cornerRadius: 8).fill(LN.textSecondary.opacity(0.06)))
            }
            .buttonStyle(.plain)

            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(ctx?.name ?? "")
                    .font(.system(size: 15, weight: .semibold)).foregroundStyle(LN.textPrimary)
                Text(ctx?.code ?? "")
                    .font(.system(size: 12).monospacedDigit()).foregroundStyle(LN.textTertiary)
            }
            if let ctx {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(LNFmt.price(ctx.price))
                        .font(.system(size: 15, weight: .semibold).monospacedDigit())
                        .foregroundStyle(LN.textPrimary)
                    Text(ctx.chg)
                        .font(.system(size: 12.5, weight: .semibold).monospacedDigit())
                        .foregroundStyle(ctx.chgIsUp ? LN.up : LN.down)
                }
                if !compact {
                    Text(ctx.meta)
                        .font(.system(size: 11.5)).foregroundStyle(LN.textSecondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 6)
            if !compact, let hint = model.analysisContext?.hint {
                Text(hint).font(.system(size: 12)).foregroundStyle(LN.textTertiary).lineLimit(1)
            }
        }
        .padding(.horizontal, compact ? 14 : 22)
        .frame(height: 60)
        .background(.ultraThinMaterial)
        .overlay(Divider().overlay(LN.hairline), alignment: .bottom)
    }

    // MARK: - 消息分发

    @ViewBuilder
    private func messageView(_ msg: ChatMessage) -> some View {
        switch msg.role {
        case .user:      userBubble(msg.text)
        case .assistant: assistantBubble(msg.text)
        case .analysis:  analysisBlock(msg)
        case .coach:     coachBlock(msg)
        }
    }

    private func userBubble(_ text: String) -> some View {
        HStack {
            Spacer(minLength: 60)
            Text(text)
                .font(.system(size: 13.5)).foregroundStyle(.white)
                .lineSpacing(2)
                .padding(.horizontal, 16).padding(.vertical, 11)
                .background(
                    UnevenRoundedRectangle(cornerRadii: .init(topLeading: 16, bottomLeading: 16,
                                                              bottomTrailing: 4, topTrailing: 16))
                        .fill(LN.accent)
                )
        }
        .padding(.vertical, 8)
    }

    private func assistantBubble(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            CoachAvatar(size: 30)
            Text(text)
                .font(.system(size: 13.5)).foregroundStyle(LN.textPrimary)
                .lineSpacing(3)
                .padding(.horizontal, 16).padding(.vertical, 13)
                .background(
                    UnevenRoundedRectangle(cornerRadii: .init(topLeading: 4, bottomLeading: 16,
                                                              bottomTrailing: 16, topTrailing: 16))
                        .fill(LN.cardBg)
                )
                .overlay(
                    UnevenRoundedRectangle(cornerRadii: .init(topLeading: 4, bottomLeading: 16,
                                                              bottomTrailing: 16, topTrailing: 16))
                        .stroke(LN.hairline, lineWidth: 0.5)
                )
            Spacer(minLength: 40)
        }
        .padding(.vertical, 8)
    }

    // MARK: - analysis 结构化深析卡

    @ViewBuilder
    private func analysisBlock(_ msg: ChatMessage) -> some View {
        if let a = msg.analysis {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top, spacing: 12) {
                    CoachAvatar(size: 30)
                    DeepAnalysisCard(analysis: a, fundAsof: model.fundAsof, compact: compact)
                    Spacer(minLength: compact ? 0 : 30)
                }
                // 可进 → 「全仓买入并录入」绿按钮(候选模式 + 当前为候选)
                if model.chatMode == .analyze, a.verdict == .enter,
                   model.candidate(byCode: model.selectedCode ?? "") != nil {
                    HStack(spacing: 10) {
                        Button(action: { model.buyFromAnalysis() }) {
                            Text("全仓买入并录入")
                                .font(.system(size: 13, weight: .semibold)).foregroundStyle(.white)
                                .padding(.horizontal, 18).padding(.vertical, 10)
                                .background(RoundedRectangle(cornerRadius: 10).fill(LN.up))
                        }
                        .buttonStyle(.plain)
                        Text("看下一只")
                            .font(.system(size: 13, weight: .medium)).foregroundStyle(LN.textSecondary)
                            .padding(.horizontal, 18).padding(.vertical, 10)
                            .background(RoundedRectangle(cornerRadius: 10).fill(LN.textSecondary.opacity(0.06)))
                    }
                    .padding(.leading, 42)
                }
            }
            .padding(.vertical, 9)
        }
    }

    // MARK: - coach 反情绪教练红橙卡

    private func coachBlock(_ msg: ChatMessage) -> some View {
        HStack(alignment: .top, spacing: 12) {
            CoachAlertAvatar(size: 30)
            VStack(alignment: .leading, spacing: 11) {
                VStack(alignment: .leading, spacing: 9) {
                    Text("反情绪教练介入")
                        .font(.system(size: 11, weight: .bold)).tracking(0.5)
                        .foregroundStyle(LN.down)
                    Text(msg.text)
                        .font(.system(size: 13.5)).foregroundStyle(LN.textPrimary).lineSpacing(3)
                    // 复盘历史引用(阶段3 H3):有 review_ref → 显真实历史教训;无 → 整块不显。
                    if let ref = model.coachReviewRef, !ref.isEmpty {
                        reviewQuoteBlock(ref)
                    }
                }
                .padding(.horizontal, 18).padding(.vertical, 16)
                .background(
                    UnevenRoundedRectangle(cornerRadii: .init(topLeading: 4, bottomLeading: 16,
                                                              bottomTrailing: 16, topTrailing: 16))
                        .fill(LinearGradient(colors: [LN.cardBg, Color(hex: 0xFFF4F3, alpha: 0.9)],
                                             startPoint: .topLeading, endPoint: .bottomTrailing))
                )
                .overlay(
                    UnevenRoundedRectangle(cornerRadii: .init(topLeading: 4, bottomLeading: 16,
                                                              bottomTrailing: 16, topTrailing: 16))
                        .stroke(LN.down.opacity(0.22), lineWidth: 1)
                )

                HStack(spacing: 9) {
                    Button(action: { model.markCloseFromAnalysis() }) {
                        Text("好,标记次日清仓")
                            .font(.system(size: 13, weight: .semibold)).foregroundStyle(.white)
                            .padding(.horizontal, 16).padding(.vertical, 9)
                            .background(RoundedRectangle(cornerRadius: 10).fill(LN.down))
                    }
                    .buttonStyle(.plain)
                    Text("再给我看一眼分时")
                        .font(.system(size: 13, weight: .medium)).foregroundStyle(LN.textSecondary)
                        .padding(.horizontal, 16).padding(.vertical, 9)
                        .background(RoundedRectangle(cornerRadius: 10).fill(LN.textSecondary.opacity(0.06)))
                }
            }
            Spacer(minLength: compact ? 0 : 30)
        }
        .padding(.vertical, 9)
    }

    /// 复盘历史引用(阶段3 H3):消费后端 review_ref(带情绪第二人称的真实历史教训)。
    /// 仅在有 review_ref 时由 coachBlock 调用;无历史破线笔则整块不显(非占位)。
    private func reviewQuoteBlock(_ ref: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.system(size: 14, weight: .semibold)).foregroundStyle(LN.down)
            Text(ref)
                .font(.system(size: 12.5, weight: .medium)).foregroundStyle(LN.textPrimary)
                .lineSpacing(2)
        }
        .padding(.horizontal, 14).padding(.vertical, 11)
        .background(RoundedRectangle(cornerRadius: 11).fill(LN.down.opacity(0.05)))
        .overlay(RoundedRectangle(cornerRadius: 11).stroke(LN.down.opacity(0.16), lineWidth: 0.5))
    }

    // MARK: - thinking 占位

    private var thinkingRow: some View {
        HStack(alignment: .top, spacing: 12) {
            CoachAvatar(size: 30)
            HStack(spacing: 6) {
                ProgressView().controlSize(.small)
                Text("正在深判…").font(.system(size: 13)).foregroundStyle(LN.textSecondary)
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 14).fill(LN.cardBg))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(LN.hairline, lineWidth: 0.5))
            Spacer(minLength: 40)
        }
        .padding(.vertical, 8)
    }

    // MARK: - 底部 composer

    private var composer: some View {
        HStack(spacing: 12) {
            TextField("问点什么…分析候选、解释概念、聊聊中间地带的票", text: $model.composer)
                .textFieldStyle(.plain)
                .font(.system(size: 13.5)).foregroundStyle(LN.textPrimary)
                #if os(iOS)
                .submitLabel(.send)
                .onSubmit { model.sendComposer() }
                #endif
            Button(action: { model.sendComposer() }) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 15, weight: .bold)).foregroundStyle(.white)
                    .frame(width: 32, height: 32)
                    .background(RoundedRectangle(cornerRadius: 9).fill(LN.accent))
            }
            .buttonStyle(.plain)
            #if os(macOS)
            .keyboardShortcut(.return, modifiers: [])
            #endif
        }
        .padding(.horizontal, 9).padding(.vertical, 9).padding(.leading, 7)
        .background(RoundedRectangle(cornerRadius: 13).fill(LN.textSecondary.opacity(0.05)))
        .overlay(RoundedRectangle(cornerRadius: 13).stroke(LN.textSecondary.opacity(0.12), lineWidth: 0.5))
        .padding(.horizontal, compact ? 16 : 26)
        .padding(.top, 12).padding(.bottom, compact ? 16 : 18)
        .background(LN.cardBg)
        .overlay(Divider().overlay(LN.hairline), alignment: .top)
    }
}

// MARK: - 结构化深析卡(三轴 pill + verdict 渐变区 + plan + fund_asof 标注)

struct DeepAnalysisCard: View {
    let analysis: DeepAnalysis
    let fundAsof: String
    var compact: Bool

    var body: some View {
        VStack(spacing: 0) {
            if compact {
                axisSection("①", "形态面 · 主轴", analysis.form)
                Divider().overlay(LN.hairline)
                axisSection("②", "资金面 · 确认", analysis.fund)
                Divider().overlay(LN.hairline)
                axisSection("③", "消息面 · 排雷", analysis.news)
            } else {
                HStack(alignment: .top, spacing: 0) {
                    axisSection("①", "形态面 · 主轴", analysis.form)
                        .overlay(Divider().overlay(LN.hairline), alignment: .trailing)
                    axisSection("②", "资金面 · 确认", analysis.fund)
                }
                Divider().overlay(LN.hairline)
                axisSection("③", "消息面 · 排雷", analysis.news)
            }
            verdictSection
        }
        .background(RoundedRectangle(cornerRadius: 16).fill(LN.cardBg))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(LN.hairline, lineWidth: 0.5))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .shadow(color: Color(hex: 0x141E3C, alpha: 0.05), radius: 3, y: 1)
        .frame(maxWidth: compact ? .infinity : 640)
    }

    private func axisSection(_ idx: String, _ title: String, _ axis: AnalysisAxis) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 7) {
                Text(idx).font(.system(size: 11, weight: .bold)).foregroundStyle(LN.accent)
                Text(title).font(.system(size: 12, weight: .semibold)).foregroundStyle(LN.textPrimary)
                Spacer(minLength: 8)
                tonePill(axis.value, axis.tone)
            }
            Text(axis.text.isEmpty ? "—" : axis.text)
                .font(.system(size: 12.5)).foregroundStyle(LN.textSecondary).lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 18).padding(.vertical, 15)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func tonePill(_ value: String, _ tone: AxisTone) -> some View {
        let (fg, bg): (Color, Color) = {
            switch tone {
            case .good:    return (LN.up, LN.up.opacity(0.10))
            case .warn:    return (LN.amber, LN.amber.opacity(0.12))
            case .bad:     return (LN.down, LN.down.opacity(0.10))
            case .neutral: return (LN.textSecondary, LN.textSecondary.opacity(0.07))
            }
        }()
        return Text(value)
            .font(.system(size: 10.5, weight: .semibold)).foregroundStyle(fg)
            .padding(.horizontal, 8).padding(.vertical, 2)
            .background(Capsule().fill(bg))
            .fixedSize()
    }

    private var verdictSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 14) {
                verdictChip
                Text(analysis.plan.isEmpty ? "—" : analysis.plan)
                    .font(.system(size: 12.5)).foregroundStyle(LN.textPrimary).lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            // 资金时序标注(显著展示;深判端点返回 fund_asof)。
            if !fundAsof.isEmpty {
                HStack(spacing: 5) {
                    Image(systemName: "info.circle")
                        .font(.system(size: 10, weight: .semibold)).foregroundStyle(LN.textTertiary)
                    Text("资金面 = 截至 \(fundAsof) EOD · 东财主力口径(非盘中实时)")
                        .font(.system(size: 10.5)).foregroundStyle(LN.textTertiary)
                }
            }
        }
        .padding(.horizontal, 18).padding(.vertical, 15)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            LinearGradient(colors: [LN.up.opacity(0.07), LN.accent.opacity(0.05)],
                           startPoint: .leading, endPoint: .trailing)
        )
        .overlay(Divider().overlay(LN.hairline), alignment: .top)
    }

    private var verdictChip: some View {
        let (fg, border): (Color, Color) = {
            switch analysis.verdict {
            case .enter: return (LN.up, LN.up.opacity(0.3))
            case .watch: return (LN.amber, LN.amber.opacity(0.35))
            case .avoid: return (LN.down, LN.down.opacity(0.3))
            }
        }()
        return Text("建议 · \(analysis.verdict.rawValue)")
            .font(.system(size: 13, weight: .bold)).foregroundStyle(fg)
            .padding(.horizontal, 15).padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 10).fill(LN.cardBg))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(border, lineWidth: 1))
            .fixedSize()
    }
}

// MARK: - 反情绪教练 ! 头像(红橙渐变)

struct CoachAlertAvatar: View {
    var size: CGFloat = 30
    var body: some View {
        Circle()
            .fill(LN.coach)
            .frame(width: size, height: size)
            .overlay(Text("!").font(.system(size: size * 0.5, weight: .bold)).foregroundStyle(.white))
    }
}
