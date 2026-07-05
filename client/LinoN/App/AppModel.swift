//
//  AppModel.swift
//  LinoN — 应用状态(@Observable,照 README §State Management)
//
//  本期(阶段1 track B)只接 holdings 真数据(GET /positions);candidates/
//  memory/review 留占位(阶段2/3)。导航 view、modal/form/toast、派生 KPI 在此。
//

import Foundation
import Observation

enum AppView: String, CaseIterable, Identifiable {
    case today, candidates, review, memory
    var id: String { rawValue }
    var title: String {
        switch self {
        case .today: return "今日"
        case .candidates: return "候选"
        case .review: return "复盘"
        case .memory: return "记忆"
        }
    }
}

enum ModalKind: Equatable { case open, close }

/// 深析模式:候选深析 / 持仓教练对话。
enum ChatMode: Equatable { case analyze, coach }

/// 深析全屏顶部上下文条(候选 or 持仓)。
struct AnalysisContext: Equatable {
    var name: String
    var code: String
    var price: Double
    var chg: String              // 展示串(候选:涨跌幅;持仓:浮盈%)
    var chgIsUp: Bool
    var meta: String             // 候选:放量·主力·换手;持仓:成本·D几
    var hint: String             // 右侧提示语
}

/// 开仓录入草稿(止损线只读派生,不在 form 内手填)。
struct EntryForm {
    var code = ""
    var name = ""
    var price = ""    // 买入价(字符串,便于输入校验)
    var qty = ""
    var reason = ""

    var buyPrice: Double? { Double(price.trimmingCharacters(in: .whitespaces)) }
    /// 系统派生止损线 = 买入价 × 0.95(只读展示)
    var derivedStop: Double? {
        guard let p = buyPrice, p > 0 else { return nil }
        return (p * 0.95 * 100).rounded() / 100
    }
    var qtyInt: Int? { Int(qty.trimmingCharacters(in: .whitespaces)) }
}

struct Toast: Identifiable, Equatable {
    let id = UUID()
    let message: String
    var isError: Bool = false
}

struct PortfolioKPIs {
    var marketValue: Double = 0    // 持仓市值
    var floatPnl: Double = 0       // 浮动盈亏(金额)
    var floatPnlPct: Double = 0    // 浮动盈亏 %
    var positionCount: Int = 0
    var disciplineRate: Int = 86   // 纪律执行率(占位 · 阶段3 复盘真值)
    var disciplineTrend: Int = 4
}

@MainActor
@Observable
final class AppModel {
    // —— 导航 ——
    var view: AppView = .today
    var selectedCode: String? = nil

    // —— 真数据 ——
    var holdings: [Position] = []
    var freeSlots: Int = 3
    var isLoading = false
    var loadError: String? = nil

    // —— 阶段2:候选(GET /candidates;v1.3.0 起后端固定返 Top CANDIDATE_LIMIT=20,不再满仓闭门)——
    var candidates: [Candidate] = []
    var candidatesTradeDate: String = ""
    var candidatesDegraded: Bool = false
    var candidatesDegradedReason: String? = nil
    var candidatesLoading = false
    var candidatesRefreshing = false   // 手动强制重算中(全市场拉取,可能数十秒)

    // —— v1.4 Phase D:候选池「今日续强确认」(GET /candidates/intraday)——
    /// 盘中续强结果;nil = 尚未拉取过。非交易时段(isTrading=false)不清空 EOD 候选列表,
    /// 只更新盘中态(按钮禁用 + 标注),叠加展示按 code join(见 CandidatesView)。
    var intraday: IntradayConfirmResult? = nil
    var intradayLoading = false

    // —— 阶段2:深析/对话 thread(AnalysisView)——
    var inAnalysis: Bool = false           // 是否在深析全屏(iOS push / macOS 覆盖内容区)
    var chatMode: ChatMode = .analyze
    var thread: [ChatMessage] = []
    var composer: String = ""
    var analysisLoading = false
    /// 当前深析上下文条用:候选(价/放量/主力)或持仓(成本/D几)。
    var analysisContext: AnalysisContext? = nil
    /// 当前深析卡的资金时序标注(显著展示;深判端点返回 fund_asof)。
    var fundAsof: String = ""
    /// v1.2.1 Phase C:首条 assistant 气泡的 verdict/id(仅 isFirst==true 时写;追问轮不覆盖,
    /// 防止追问翻"不进"时买入按钮回溯消失;backFromAnalysis 清空)。
    var firstVerdict: Verdict? = nil
    var firstAssistantMsgId: UUID? = nil

    // —— 阶段3:复盘 / 记忆 ——
    var review: Review? = nil
    var reviewLoading = false
    var reviewNoteDraft: String = ""       // 下周注意编辑草稿
    var reviewSaving = false
    var memoryItems: [MemoryItem] = []
    var archivedTrades: [ClosedTradeRow] = []
    var memoryLoading = false
    /// 阶段3 G4:当前 coach 卡的复盘历史引用(带情绪第二人称;无历史破线 → nil,卡不显引用块)。
    var coachReviewRef: String? = nil

    // —— v1.3.1 Phase B3:选股配置调参屏(SettingsView → ScreenConfigView)——
    var screenConfig: ScreenConfig = [:]           // 当前(已 resolve)活配置,滑块/输入绑定此值
    var screenConfigDefaults: ScreenConfig = [:]   // DEFAULT_SCREEN_CONFIG(供本地校验/兜底展示)
    var screenConfigUpdatedAt: String? = nil
    var screenConfigLoading = false
    var screenConfigSaving = false

    // —— 模态 / 录入 / toast ——
    var modal: ModalKind? = nil
    var closeCode: String? = nil
    var form = EntryForm()
    var closeSellPrice = ""
    var toast: Toast? = nil

    // —— v1.3.0 Phase D2:三仓相关性护栏(只在买入路径;只提示不拦)——
    /// 命中同行业已持仓 → 非 nil,表单内显警示条;nil → 不显(无冲突/降级/请求失败静默)。
    var correlationConflict: CorrelationResult? = nil

    // —— 依赖(运行期注入)——
    private let calendar: TradingCalendar
    private var clientProvider: () -> APIClient?
    /// iOS 通知动作回报(标记次日清仓 / 问教练 → ack)的钩子,由 PushManager 注册。
    var onAlertAction: ((_ code: String, _ action: String) -> Void)? = nil
    #if os(iOS)
    /// iOS 推送管理器(AppDelegate 注入),供 Settings 屏读 device token / 重新注册。
    weak var pushManager: PushManager? = nil
    #endif

    init(calendar: TradingCalendar = StaticTradingCalendar.shared,
         clientProvider: @escaping () -> APIClient? = { nil }) {
        self.calendar = calendar
        self.clientProvider = clientProvider
    }

    func setClientProvider(_ p: @escaping () -> APIClient?) {
        self.clientProvider = p
    }

    /// 用 config 绑定后端连接(随 config 实时取值)。幂等,可重复调。
    func bind(config: AppConfig) {
        self.clientProvider = { [weak config] in
            guard let c = config, c.hasToken else { return nil }
            return APIClient(baseURL: c.resolvedBaseURL, token: c.apiToken)
        }
    }

    // MARK: - 派生

    /// 持仓交易日计数(D 几),买入日 = D1。
    func holdingDay(_ p: Position, today: Date = Date()) -> Int {
        max(1, calendar.countHoldingTradeDays(buyDate: p.buyDate, today: today))
    }

    func shouldForceClose(_ p: Position, today: Date = Date()) -> Bool {
        calendar.shouldForceClose(buyDate: p.buyDate, today: today)
    }

    var portfolioKPIs: PortfolioKPIs {
        var k = PortfolioKPIs()
        var mkt = 0.0, cost = 0.0
        for h in holdings {
            mkt += h.price * Double(h.qty)
            cost += h.buyPrice * Double(h.qty)
        }
        k.marketValue = mkt
        k.floatPnl = mkt - cost
        k.floatPnlPct = cost > 0 ? (mkt - cost) / cost * 100 : 0
        k.positionCount = holdings.count
        // 阶段3:纪律执行率接真值(有复盘数据时);无则保留占位默认。
        if let r = review {
            k.disciplineRate = r.disciplineRate
            k.disciplineTrend = r.rateTrend
        }
        return k
    }

    /// 侧栏"待"badge:本周有破线笔(redFlags 非空)→ 提示复盘。
    var hasReviewFlags: Bool { !(review?.redFlags.isEmpty ?? true) }

    /// 触止损持仓(教练横幅触发依据 · 本期占位文案)。
    var alertHolding: Position? { holdings.first(where: { $0.hitStop }) }

    var hasFreeSlot: Bool { holdings.count < 3 }

    /// 空仓位数 = max(0, 3 - 持仓数)。v1.3.0 起不再驱动候选闭门,仅供开仓校验类场景参考。
    var openSlots: Int { max(0, 3 - holdings.count) }

    /// v1.3.0 Phase C3:满仓闭门已删,固定展示 Top 20(后端已限 20,此处安全带再夹一层)。
    var shownCandidates: [Candidate] {
        Array(candidates.prefix(20))
    }

    func holding(byCode code: String) -> Position? {
        holdings.first(where: { $0.code == code })
    }

    func candidate(byCode code: String) -> Candidate? {
        candidates.first(where: { $0.code == code })
    }

    // MARK: - 网络动作

    func refresh() async {
        guard let client = clientProvider() else {
            loadError = "未配置后端连接"
            return
        }
        isLoading = true
        loadError = nil
        do {
            let (positions, free) = try await client.fetchPositions()
            self.holdings = positions
            self.freeSlots = free
        } catch let e as APIError {
            self.loadError = e.errorDescription
            if case .noToken = e {} else { showToast(e.errorDescription ?? "拉取失败", isError: true) }
        } catch {
            self.loadError = error.localizedDescription
        }
        isLoading = false
        // 持仓变化后重拉候选(候选本身固定 Top 20,不再随持仓数量截断,但保持数据新鲜)。
        await loadCandidates()
    }

    /// 开仓提交。成功 → 刷新 + toast;失败按 reason 弹提示。
    func submitOpen() async {
        guard let client = clientProvider() else {
            showToast("未配置后端连接", isError: true); return
        }
        guard let buyPrice = form.buyPrice, buyPrice > 0 else {
            showToast("请填写有效买入价", isError: true); return
        }
        guard let qty = form.qtyInt, qty > 0 else {
            showToast("请填写有效数量", isError: true); return
        }
        let code = form.code.trimmingCharacters(in: .whitespaces)
        guard !code.isEmpty else { showToast("请填写代码", isError: true); return }
        let reason = form.reason.trimmingCharacters(in: .whitespaces)
        guard !reason.isEmpty else { showToast("请填写进场理由", isError: true); return }

        let req = OpenPositionRequest(
            code: code,
            name: form.name.trimmingCharacters(in: .whitespaces),
            buy_price: buyPrice, qty: qty, entry_reason: reason
        )
        do {
            _ = try await client.openPosition(req)
            dismissModal()
            await refresh()
            view = .today
            showToast("开仓已录入 · 已自动快照形态+资金")
        } catch let e as APIError {
            showToast(e.errorDescription ?? "开仓失败", isError: true)
        } catch {
            showToast("开仓失败:\(error.localizedDescription)", isError: true)
        }
    }

    /// 清仓提交。成功 → 刷新 + toast + ack 停升级。
    func submitClose() async {
        guard let client = clientProvider() else {
            showToast("未配置后端连接", isError: true); return
        }
        guard let code = closeCode, let pos = holding(byCode: code) else {
            showToast("找不到该持仓", isError: true); return
        }
        let sell = Double(closeSellPrice.trimmingCharacters(in: .whitespaces)) ?? pos.price
        guard sell > 0 else { showToast("请填写有效卖出价", isError: true); return }

        do {
            let resp = try await client.closePosition(id: pos.id, ClosePositionRequest(sell_price: sell, sell_time: nil))
            // 清仓即录动作 → ack 停该 code 升级(无害:无升级时后端返 stopped:0)
            try? await client.ackAlert(code: code, action: "marked_close")
            dismissModal()
            await refresh()
            view = .today
            // v1.3.0 Phase D1:有实值净额/费用才展示打磨版 toast(旧行/异常兜底不显假数字)。
            if let net = resp.net_pnl_amount {
                let feeText = resp.fee.map { "(含费 ¥\(String(format: "%.2f", $0)))" } ?? ""
                showToast("已清仓 · 净收益 \(LNFmt.signedMoneyCents(net))\(feeText)")
            } else {
                showToast("已清仓 · 写入流水,监控已停止")
            }
        } catch let e as APIError {
            showToast(e.errorDescription ?? "清仓失败", isError: true)
        } catch {
            showToast("清仓失败:\(error.localizedDescription)", isError: true)
        }
    }

    // MARK: - 阶段2:候选

    /// 拉候选(GET /candidates)。无 token/无缓存 → degraded 空列表(不弹错)。
    func loadCandidates() async {
        guard let client = clientProvider() else {
            candidates = []; candidatesDegraded = true
            candidatesDegradedReason = "no_client"; return
        }
        candidatesLoading = true
        do {
            let r = try await client.fetchCandidates()
            self.candidates = r.candidates
            self.candidatesTradeDate = r.tradeDate
            self.candidatesDegraded = r.degraded
            self.candidatesDegradedReason = r.reason
        } catch let e as APIError {
            // 候选拉取失败不弹错(降级语义);noToken 静默。
            self.candidatesDegraded = true
            self.candidatesDegradedReason = (e == .noToken) ? "no_token" : "error"
            if case .noToken = e {} else { self.candidates = [] }
        } catch {
            self.candidatesDegraded = true
            self.candidatesDegradedReason = "error"
        }
        candidatesLoading = false
    }

    /// 手动强制重算候选(POST /candidates/refresh:全市场 EOD 拉取,可能数十秒)→ 再拉新缓存 + toast。
    func recomputeCandidates() async {
        guard let client = clientProvider() else {
            showToast("未配置后端连接", isError: true); return
        }
        candidatesRefreshing = true
        defer { candidatesRefreshing = false }
        do {
            let r = try await client.refreshCandidates()
            await loadCandidates()
            showToast(r.degraded ? "数据源未就绪,暂无候选" : "候选已刷新 · \(r.count) 只合格")
        } catch {
            showToast("刷新失败,请稍后重试", isError: true)
        }
    }

    /// v1.4 Phase D:拉候选池「今日续强确认」(GET /candidates/intraday)。
    /// 客户端不自判日历/时段——按钮初始可点,响应回 isTrading=false 才禁用(时段真值全由后端定)。
    /// 非交易时段(isTrading=false)也正常写入 intraday(供按钮态/提示文案),不清空 EOD 候选列表。
    func loadIntradayConfirm() async {
        guard let client = clientProvider() else {
            showToast("未配置后端连接", isError: true); return
        }
        intradayLoading = true
        defer { intradayLoading = false }
        do {
            let r = try await client.fetchCandidatesIntraday()
            self.intraday = r
            if !r.isTrading {
                showToast("非交易时段 · 盘中确认仅交易时段可用")
            }
        } catch let e as APIError {
            showToast(e.errorDescription ?? "盘中确认拉取失败", isError: true)
        } catch {
            showToast("盘中确认拉取失败", isError: true)
        }
    }

    /// 按 code join 盘中续强字段(建议#10:不靠数组顺序对齐)。无 intraday 结果 → nil。
    func intradayItem(byCode code: String) -> IntradayItem? {
        intraday?.items.first(where: { $0.code == code })
    }

    // MARK: - 阶段2:深析 / 对话(AnalysisView)

    /// 候选点深析 → 进全屏 + user 气泡 + /chat 对话式深判(v1.2.1 Phase C,自由文本非三轴卡)。
    func openAnalysis(code: String) async {
        guard let c = candidate(byCode: code) else { return }
        selectedCode = code
        chatMode = .analyze
        analysisContext = AnalysisContext(
            name: c.name, code: c.code, price: c.price, chg: c.chg,
            chgIsUp: !c.chg.contains("-"),   // 候选 chg 后端 ASCII '-';负跌涨幅勿染绿
            meta: "放量 \(c.volMultiple) · 主力 \(c.flow) · 换手 \(c.turnover)",
            hint: "深析 = on-demand,仅你挑中这只"
        )
        thread = [ChatMessage(role: .user, text: "分析一下\(c.name),这个位置能不能进?")]
        inAnalysis = true
        await runChat(mode: "candidate", code: code, positionId: nil)
    }

    /// v1.2.1 Phase C:统一对话调用(候选深析首条 / composer 追问共用)。
    /// 成功 → 追加 assistant 气泡 + 刷新 fundAsof;仅 isFirst 时写 firstVerdict/firstAssistantMsgId。
    private func runChat(mode: String, code: String, positionId: Int?) async {
        guard let client = clientProvider() else {
            appendAssistant("未配置后端连接,无法发起深判。去设置填 API Token。"); return
        }
        analysisLoading = true
        do {
            let r = try await client.chat(mode: mode, code: code, messages: chatTurns(from: thread), positionId: positionId)
            self.fundAsof = r.fundAsof
            let msg = ChatMessage(role: .assistant, text: r.reply)
            thread.append(msg)
            if r.isFirst {
                firstVerdict = r.verdict
                firstAssistantMsgId = msg.id
            }
        } catch {
            appendAssistant("深判失败:\((error as? APIError)?.errorDescription ?? error.localizedDescription)")
        }
        analysisLoading = false
    }

    /// 持仓「问教练」→ 进全屏。触损 → coach 卡;中间地带 → 持仓对话(走 coach 端点取建议)。
    func openCoach(code: String) async {
        guard let h = holding(byCode: code) else { return }
        selectedCode = code
        let hit = h.hitStop
        chatMode = hit ? .coach : .analyze
        let pnl = h.pnlPct
        analysisContext = AnalysisContext(
            name: h.name, code: h.code, price: h.price,
            chg: LNFmt.signedPct(pnl), chgIsUp: pnl >= 0,
            meta: "成本 \(LNFmt.price(h.buyPrice)) · 持仓 D\(holdingDay(h))",
            hint: hit ? "反情绪教练 · 持仓对话" : "持仓中间地带 · 拿还是清"
        )
        let opener = hit ? "\(h.name)我想再拿一天,感觉明天会反弹…"
                         : "\(h.name)现在卡在中间地带,我该拿还是清?"
        thread = [ChatMessage(role: .user, text: opener)]
        inAnalysis = true
        await runCoach(id: h.id, hit: hit)
    }

    private func runCoach(id: Int, hit: Bool) async {
        guard let client = clientProvider() else {
            appendAssistant("未配置后端连接,无法请教练。去设置填 API Token。"); return
        }
        analysisLoading = true
        do {
            let r = try await client.coachPosition(id: id)
            self.fundAsof = r.fundAsof
            self.coachReviewRef = r.reviewRef   // 阶段3 G4:历史引用(无则 nil,coach 卡不显引用块)
            if hit {
                // 触损 → coach 红橙卡(文案取后端 reason;复盘历史引用换真实 review_ref,阶段3 H3)。
                thread.append(ChatMessage(role: .coach, text: r.reason, analysis: r.analysis))
            } else {
                // 中间地带 → 普通助手气泡(advice 拿/清 + 理由)。
                let prefix = r.advice == "清" ? "建议清。" : "建议继续拿。"
                thread.append(ChatMessage(role: .assistant, text: prefix + r.reason))
            }
        } catch let e as APIError {
            appendAssistant("教练失败:\(e.errorDescription ?? "未知错误")")
        } catch {
            appendAssistant("教练失败:\(error.localizedDescription)")
        }
        analysisLoading = false
    }

    /// 发送 composer 文本 → 真接 DeepSeek 多轮追问(v1.2.1 Phase C)。
    /// mode 按业务状态判(持仓中间地带 → coach + positionId),不复用 UI 语义的 chatMode。
    func sendComposer() async {
        let t = composer.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, let code = selectedCode else { return }
        thread.append(ChatMessage(role: .user, text: t))
        composer = ""
        let holdingPos = holding(byCode: code)
        let mode = holdingPos != nil ? "coach" : "candidate"
        await runChat(mode: mode, code: code, positionId: holdingPos?.id)
    }

    /// v1.2.1 Phase C:thread → [ChatTurn] 序列化契约(纯函数,单测覆盖)。
    /// .user→user / .assistant→assistant / .coach→assistant(content=text) / .analysis→跳过(结构卡无自然语言内容)。
    /// 截断保留最近 8 轮(≤16 条),从 user 边界截起,且必须保留最近一条 assistant
    /// (保证追问轮后端 is_first 判定恒 false)。后端 role 只认 user/assistant 两值,否则 422。
    func chatTurns(from thread: [ChatMessage]) -> [ChatTurn] {
        let mapped: [ChatTurn] = thread.compactMap { msg in
            switch msg.role {
            case .user:      return ChatTurn(role: "user", content: msg.text)
            case .assistant: return ChatTurn(role: "assistant", content: msg.text)
            case .coach:     return ChatTurn(role: "assistant", content: msg.text)
            case .analysis:  return nil
            }
        }
        let maxCount = 16
        guard mapped.count > maxCount else { return mapped }
        var truncated = Array(mapped.suffix(maxCount))
        // 从 user 边界截起:丢弃开头非 user 的消息,避免 assistant 打头的畸形序列。
        while let first = truncated.first, first.role != "user" {
            truncated.removeFirst()
        }
        return truncated
    }

    private func appendAssistant(_ text: String) {
        thread.append(ChatMessage(role: .assistant, text: text))
    }

    /// 深析卡「全仓买入并录入」→ 退出深析,预填开仓 sheet。
    /// iOS:fullScreenCover 与 .sheet 不能同一 runloop 交接(cover 关闭回调会 reset),
    /// 故先关全屏、表单预填到 form,modal 推到下一 tick 再弹。
    func buyFromAnalysis() {
        guard let code = selectedCode, let c = candidate(byCode: code) else { return }
        var f = EntryForm()
        f.code = c.code
        f.name = c.name
        f.price = LNFmt.price(c.price)
        f.reason = c.tag.isEmpty ? "平台突破" : c.tag
        inAnalysis = false           // 关全屏(触发 backFromAnalysis 清 thread)
        presentModalAfterCoverDismiss { [weak self] in
            self?.form = f
            self?.correlationConflict = nil
            self?.modal = .open
            // v1.3.0 Phase D2:深析卡买入路径预填代码后也要触发相关性护栏(同开仓 sheet 手填路径)。
            Task { await self?.checkCorrelation(code: f.code) }
        }
    }

    /// 教练「标记次日清仓」→ 退出深析,打开清仓 sheet(同上,推下一 tick)。
    func markCloseFromAnalysis() {
        guard let code = selectedCode, holding(byCode: code) != nil else { return }
        inAnalysis = false
        presentModalAfterCoverDismiss { [weak self] in
            self?.openClose(code: code)
        }
    }

    /// 在全屏 cover 关闭后的下一 runloop 呈现模态,避开 iOS cover↔sheet 同帧交接。
    private func presentModalAfterCoverDismiss(_ present: @escaping () -> Void) {
        #if os(iOS)
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 350_000_000)   // 等 cover 退场动画 ~0.3s
            present()
        }
        #else
        present()   // macOS 无 fullScreenCover,内容区即时切换,直接呈现
        #endif
    }

    func backFromAnalysis() {
        inAnalysis = false
        thread = []
        analysisContext = nil
        composer = ""
        coachReviewRef = nil
        firstVerdict = nil
        firstAssistantMsgId = nil
    }

    // MARK: - 阶段3:复盘 / 记忆网络动作

    /// 拉周复盘(GET /review;缺 week → 本周)。降级不弹错(空态由视图诚实展示)。
    func loadReview(week: String? = nil) async {
        guard let client = clientProvider() else {
            review = nil; return
        }
        reviewLoading = true
        do {
            let r = try await client.fetchReview(week: week)
            self.review = r
            self.reviewNoteDraft = r.nextWeekNote
        } catch {
            // 复盘拉取失败不弹错(降级语义);保留旧值或清空
            if case APIError.noToken = error {} else {
                showToast("复盘拉取失败", isError: true)
            }
        }
        reviewLoading = false
    }

    /// 保存下周注意(POST /review/{week}/note)→ 回读 nextWeekNote。
    func saveReviewNote() async {
        guard let client = clientProvider(), let wk = review?.week else {
            showToast("未配置后端连接", isError: true); return
        }
        reviewSaving = true
        defer { reviewSaving = false }
        do {
            try await client.saveReviewNote(week: wk, note: reviewNoteDraft)
            review?.nextWeekNote = reviewNoteDraft
            showToast("下周注意已保存 · 会写入交易上下文")
        } catch {
            showToast("保存失败,请重试", isError: true)
        }
    }

    /// 拉记忆 + 已平仓流水(GET /memory)。降级不弹错。
    func loadMemory() async {
        guard let client = clientProvider() else {
            memoryItems = []; archivedTrades = []; return
        }
        memoryLoading = true
        do {
            let m = try await client.fetchMemory()
            self.memoryItems = m.items
            self.archivedTrades = m.closedTrades
        } catch {
            if case APIError.noToken = error {} else {
                showToast("记忆拉取失败", isError: true)
            }
        }
        memoryLoading = false
    }

    // MARK: - v1.3.1 Phase B3:选股配置调参屏

    /// 拉活配置(GET /screen/config)。降级不弹错(视图按空 dict 展示默认占位)。
    func loadScreenConfig() async {
        guard let client = clientProvider() else { return }
        screenConfigLoading = true
        do {
            let r = try await client.fetchScreenConfig()
            self.screenConfig = r.config
            self.screenConfigDefaults = r.defaults
            self.screenConfigUpdatedAt = r.updatedAt
        } catch {
            if case APIError.noToken = error {} else {
                showToast("选股配置拉取失败", isError: true)
            }
        }
        screenConfigLoading = false
    }

    /// 保存当前配置(PUT 全部当前值)→ 用响应(归一/夹紧后)回填 + 提示"下次刷新生效"
    /// (不自动触发候选 refresh;客户端不自算归一,归一在后端 resolve)。
    func saveScreenConfig() async {
        guard let client = clientProvider() else {
            showToast("未配置后端连接", isError: true); return
        }
        screenConfigSaving = true
        defer { screenConfigSaving = false }
        do {
            let r = try await client.putScreenConfig(screenConfig)
            self.screenConfig = r.config
            showToast("已保存 · 下次手动刷新候选生效")
        } catch {
            showToast("保存失败,请重试", isError: true)
        }
    }

    /// 恢复默认 = PUT 空 config `{}`(后端清用户行,resolve 全回默认)→ 用响应回填。
    func restoreDefaultScreenConfig() async {
        guard let client = clientProvider() else {
            showToast("未配置后端连接", isError: true); return
        }
        screenConfigSaving = true
        defer { screenConfigSaving = false }
        do {
            let r = try await client.putScreenConfig([:])
            self.screenConfig = r.config
            showToast("已恢复默认 · 下次手动刷新候选生效")
        } catch {
            showToast("恢复默认失败,请重试", isError: true)
        }
    }

    /// 当前正权(排除 day_surge 罚项)之和,供 UI 提示"和≠1 时保存后端自动归一"。
    var screenConfigPositiveWeightSum: Double {
        ScreenConfigSpec.positiveWeightKeys.reduce(0.0) { $0 + (screenConfig[$1] ?? 0) }
    }

    // MARK: - 模态控制

    func openEntry() {
        form = EntryForm()
        correlationConflict = nil
        modal = .open
    }

    func openClose(code: String) {
        guard let pos = holding(byCode: code) else { return }
        closeCode = code
        closeSellPrice = String(format: "%.2f", pos.price)
        modal = .close
    }

    func dismissModal() {
        modal = nil
        closeCode = nil
        correlationConflict = nil
    }

    // MARK: - v1.3.0 Phase D2:三仓相关性护栏

    /// 代码满 6 位或输入框失焦时调一次(不逐字符打请求)。只在买入路径(开仓 sheet + 深析
    /// 「全仓买入」预填)触发,不进候选列表。网络失败/超时/降级 → 静默清空,不显警示条、不阻塞开仓。
    func checkCorrelation(code: String) async {
        let bare = code.trimmingCharacters(in: .whitespaces)
        guard bare.count >= 6, let client = clientProvider() else {
            correlationConflict = nil
            return
        }
        do {
            let r = try await client.fetchCorrelation(code: bare)
            correlationConflict = r.conflict ? r : nil
        } catch {
            // 提示性功能:请求失败/超时静默,不弹错、不阻塞开仓(与后端降级不误报对称)。
            correlationConflict = nil
        }
    }

    // MARK: - Toast

    func showToast(_ message: String, isError: Bool = false) {
        let t = Toast(message: message, isError: isError)
        toast = t
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 2_400_000_000)
            if self.toast?.id == t.id { self.toast = nil }
        }
    }
}
