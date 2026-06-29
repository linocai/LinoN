//
//  LinoNApp.swift
//  LinoN — 多平台 App 入口(iOS + macOS 单 target)
//
//  Bundle ID top.linotsai.linon · deploymentTarget iOS 26 / macOS 26。
//  iOS 接 AppDelegate 拿 APNs device token → PushManager 上报。
//

import SwiftUI

@main
struct LinoNApp: App {
    @StateObject private var config = AppConfig()
    @State private var model: AppModel

    #if os(iOS)
    @Environment(\.scenePhase) private var scenePhase
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    #endif

    init() {
        // model 的 clientProvider 在 onAppear 注入(依赖 config)。
        _model = State(initialValue: AppModel())
    }

    var body: some Scene {
        #if os(macOS)
        WindowGroup {
            RootView(model: model, config: config)
                .environmentObject(config)
                .onAppear { wire() }
                .frame(minWidth: 1080, minHeight: 640)
        }
        // contentMinSize:窗口最小 = 内容最小(可放大、不能小于),避免 contentSize 把窗口锁死在
        // 旧尺寸却把内容撑大致居中裁切;defaultSize 让首开就够宽容下侧栏 + 候选数据表列宽。
        .windowResizability(.contentMinSize)
        .defaultSize(width: 1240, height: 780)
        Settings {
            SettingsView(model: model, config: config)
                .frame(width: 460)
                .padding(20)
        }
        #else
        WindowGroup {
            RootView(model: model, config: config)
                .environmentObject(config)
                .onAppear { wire() }
                .onChange(of: scenePhase) { _, phase in
                    if phase == .active { appDelegate.clearBadge() }   // 进前台清幽灵角标
                }
        }
        #endif
    }

    private func wire() {
        // 后端连接在 RootView.task 里 model.bind(config:) 注入(保证早于 refresh)。
        #if os(iOS)
        appDelegate.attach(config: config, model: model)
        #endif
    }
}

#if os(iOS)
import UIKit

/// iOS 远程通知 token 回调桥。
final class AppDelegate: NSObject, UIApplicationDelegate {
    private var pushManager: PushManager?
    private var pendingToken: Data?

    @MainActor
    func attach(config: AppConfig, model: AppModel) {
        if pushManager == nil {
            let pm = PushManager(config: config, model: model)
            pm.bootstrap()
            self.pushManager = pm
            model.pushManager = pm   // 供 Settings 屏读 device token / 重新注册
            // 启动即请求授权 + 注册(真机才拿得到真 token)。
            Task { await pm.requestAuthorizationAndRegister() }
            if let t = pendingToken { pm.didRegister(deviceToken: t); pendingToken = nil }
        }
    }

    @MainActor
    func clearBadge() { pushManager?.clearBadge() }

    func application(_ application: UIApplication,
                     didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in
            if let pm = pushManager { pm.didRegister(deviceToken: deviceToken) }
            else { pendingToken = deviceToken }
        }
    }

    func application(_ application: UIApplication,
                     didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Task { @MainActor in pushManager?.didFailToRegister(error: error) }
    }
}
#endif
