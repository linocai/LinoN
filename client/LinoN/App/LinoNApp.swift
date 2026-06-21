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
                .frame(minWidth: 920, minHeight: 600)
        }
        .windowResizability(.contentSize)
        Settings {
            SettingsView(config: config)
        }
        #else
        WindowGroup {
            RootView(model: model, config: config)
                .environmentObject(config)
                .onAppear { wire() }
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

// MARK: - 设置(后端连接 + API Token 填入,token 不入源码)

struct SettingsView: View {
    @ObservedObject var config: AppConfig
    @State private var healthOK: Bool? = nil
    @State private var checking = false

    var body: some View {
        Form {
            Section("后端连接") {
                Picker("环境", selection: $config.environment) {
                    ForEach(LNEnvironment.allCases) { env in
                        Text(env.label).tag(env)
                    }
                }
                TextField("baseURL 覆盖(可选)", text: $config.baseURLOverride)
                    .font(.system(.body).monospaced())
                LabeledContent("生效 baseURL", value: config.resolvedBaseURL.absoluteString)
            }
            Section("鉴权") {
                SecureField("API Token(不入源码)", text: $config.apiToken)
                    .font(.system(.body).monospaced())
                Text("Token 存于本机,绝不提交进 git。dev 用 backend/.env 的 API_TOKEN。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("连通性自检") {
                Button(checking ? "检测中…" : "测试 /health") {
                    Task { await checkHealth() }
                }
                .disabled(checking)
                if let ok = healthOK {
                    Label(ok ? "后端可达" : "后端不可达",
                          systemImage: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundStyle(ok ? LN.up : LN.down)
                }
            }
        }
        .padding(20)
        .frame(width: 460)
    }

    private func checkHealth() async {
        checking = true
        let client = APIClient(baseURL: config.resolvedBaseURL, token: config.apiToken)
        healthOK = (try? await client.health()) ?? false
        checking = false
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
            // 启动即请求授权 + 注册(真机才拿得到真 token)。
            Task { await pm.requestAuthorizationAndRegister() }
            if let t = pendingToken { pm.didRegister(deviceToken: t); pendingToken = nil }
        }
    }

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
