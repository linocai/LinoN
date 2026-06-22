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

    // —— 真数据(本期只接 holdings)——
    var holdings: [Position] = []
    var freeSlots: Int = 3
    var isLoading = false
    var loadError: String? = nil

    // —— 模态 / 录入 / toast ——
    var modal: ModalKind? = nil
    var closeCode: String? = nil
    var form = EntryForm()
    var closeSellPrice = ""
    var toast: Toast? = nil

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
        return k
    }

    /// 触止损持仓(教练横幅触发依据 · 本期占位文案)。
    var alertHolding: Position? { holdings.first(where: { $0.hitStop }) }

    var hasFreeSlot: Bool { holdings.count < 3 }

    func holding(byCode code: String) -> Position? {
        holdings.first(where: { $0.code == code })
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
            _ = try await client.closePosition(id: pos.id, ClosePositionRequest(sell_price: sell, sell_time: nil))
            // 清仓即录动作 → ack 停该 code 升级(无害:无升级时后端返 stopped:0)
            try? await client.ackAlert(code: code, action: "marked_close")
            dismissModal()
            await refresh()
            view = .today
            showToast("已清仓 · 写入流水,监控已停止")
        } catch let e as APIError {
            showToast(e.errorDescription ?? "清仓失败", isError: true)
        } catch {
            showToast("清仓失败:\(error.localizedDescription)", isError: true)
        }
    }

    // MARK: - 模态控制

    func openEntry() {
        form = EntryForm()
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
