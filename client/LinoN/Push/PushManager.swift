//
//  PushManager.swift
//  LinoN — 锁屏硬线推送(iOS 专属;macOS 无锁屏推送,平台分叉)
//
//  B.4:请求通知权限 → 拿 APNs device token → POST /devices;
//  注册通知 category(动作「标记次日清仓」「问教练」);收到硬线推送 → 锁屏玻璃卡;
//  点动作 → 调端点 + POST /alerts/{code}/ack 停升级。
//
//  ⚠️ 真实推送投递留 track C.3(需 ECS 部署 + 真机 + 真签名)。本期实现
//     注册 + 通知处理 + UI 行为,本地可走授权→token→上报闭环(真机才有真 token)。
//

import Foundation
#if os(iOS)
import UIKit
import UserNotifications

/// 硬线通知 category 标识(与后端 send_push 的 category 对齐)。
enum LNNotificationCategory {
    // ⚠️ 必须与后端 apns.py 的 CATEGORY_HARDLINE 字面量一致("HARDLINE"),
    //    否则锁屏不显示动作按钮(category 标识不匹配)。
    static let hardline = "HARDLINE"
    static let actionMarkClose = "LN_MARK_CLOSE"
    static let actionAskCoach = "LN_ASK_COACH"
}

@MainActor
final class PushManager: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    private let config: AppConfig
    private weak var model: AppModel?

    @Published var authorizationStatus: UNAuthorizationStatus = .notDetermined
    @Published var lastDeviceToken: String? = nil
    @Published var registerError: String? = nil

    init(config: AppConfig, model: AppModel) {
        self.config = config
        self.model = model
        super.init()
    }

    /// 启动时挂载:设 delegate + 注册 category。
    func bootstrap() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        registerCategories()
        center.getNotificationSettings { settings in
            Task { @MainActor in self.authorizationStatus = settings.authorizationStatus }
        }
    }

    /// 注册硬线 category 的锁屏动作按钮。
    private func registerCategories() {
        let markClose = UNNotificationAction(
            identifier: LNNotificationCategory.actionMarkClose,
            title: "标记次日清仓",
            options: [.foreground])
        let askCoach = UNNotificationAction(
            identifier: LNNotificationCategory.actionAskCoach,
            title: "问教练",
            options: [.foreground])
        let category = UNNotificationCategory(
            identifier: LNNotificationCategory.hardline,
            actions: [markClose, askCoach],
            intentIdentifiers: [],
            options: [])
        UNUserNotificationCenter.current().setNotificationCategories([category])
    }

    /// 请求通知权限 → 注册远程通知(拿 device token)。
    /// 已决定(授权/拒绝)则不再弹系统对话框,只在已授权时补注册远程通知。
    func requestAuthorizationAndRegister() async {
        let center = UNUserNotificationCenter.current()
        let settings = await center.notificationSettings()
        authorizationStatus = settings.authorizationStatus
        switch settings.authorizationStatus {
        case .notDetermined:
            do {
                let granted = try await center.requestAuthorization(options: [.alert, .badge, .sound])
                authorizationStatus = granted ? .authorized : .denied
                if granted { UIApplication.shared.registerForRemoteNotifications() }
            } catch {
                registerError = error.localizedDescription
            }
        case .authorized, .provisional, .ephemeral:
            UIApplication.shared.registerForRemoteNotifications()
        default:
            break   // denied:不重复弹窗
        }
    }

    /// AppDelegate 回调:拿到 device token → 上报后端 POST /devices。
    func didRegister(deviceToken: Data) {
        let tokenHex = deviceToken.map { String(format: "%02x", $0) }.joined()
        lastDeviceToken = tokenHex
        #if DEBUG
        // track C.3 本地推送自测:从 Xcode 控制台抓真机 device token(沙盒)
        print("🔑 [LinoN] APNs device token (sandbox): \(tokenHex)")
        #endif
        Task {
            let client = APIClient(baseURL: config.resolvedBaseURL, token: config.apiToken)
            do {
                try await client.registerDevice(token: tokenHex)
                registerError = nil
            } catch {
                registerError = (error as? APIError)?.errorDescription ?? error.localizedDescription
            }
        }
    }

    func didFailToRegister(error: Error) {
        registerError = error.localizedDescription
    }

    // MARK: - UNUserNotificationCenterDelegate

    /// 前台收到推送:仍展示横幅(硬线警报不应被吞)。
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification) async
        -> UNNotificationPresentationOptions {
        return [.banner, .sound, .badge, .list]
    }

    /// 用户点了锁屏动作 → 调端点 + ack 停升级。
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse) async {
        let userInfo = response.notification.request.content.userInfo
        let code = (userInfo["code"] as? String) ?? (userInfo["thread_id"] as? String) ?? ""
        guard !code.isEmpty else { return }

        switch response.actionIdentifier {
        case LNNotificationCategory.actionMarkClose:
            await handleMarkClose(code: code)
        case LNNotificationCategory.actionAskCoach:
            // 问教练:打开 app 到该持仓上下文(阶段2 接深析/教练 thread)。
            model?.selectedCode = code
            model?.view = .today
            // ack:dismissed(用户已介入,停升级)
            await ack(code: code, action: "dismissed")
        case UNNotificationDefaultActionIdentifier:
            model?.view = .today
        default:
            break
        }
    }

    private func handleMarkClose(code: String) async {
        // 打开清仓 sheet + 回报 ack(标记次日清仓 → marked_close)
        model?.openClose(code: code)
        model?.view = .today
        await ack(code: code, action: "marked_close")
    }

    private func ack(code: String, action: String) async {
        let client = APIClient(baseURL: config.resolvedBaseURL, token: config.apiToken)
        try? await client.ackAlert(code: code, action: action)
    }
}
#endif
