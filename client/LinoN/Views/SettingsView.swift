//
//  SettingsView.swift
//  LinoN — 设置屏(后端连接 + API Token + 连接自检 + 推送注册)
//
//  极简设置:在手机上把后端从 dev 切到 prod(ln.linotsai.top)并填 API_TOKEN。
//  存储/解析逻辑全在 AppConfig(已持久化 UserDefaults),本屏只做 UI 绑定。
//
//  平台分叉:device token / 重新注册推送 段仅 iOS(PushManager iOS 专属)。
//  macOS 经 Settings 场景复用本视图(自动隐去 iOS 推送段)。
//

import SwiftUI

/// 连接自检结果(分别对 /health 与 /positions)。
private enum SelfCheckState: Equatable {
    case idle
    case running
    case ok(String)          // 成功描述,如 "health ok · positions ok(2 持仓)"
    case tokenError          // 401
    case networkError(String)
}

struct SettingsView: View {
    @Bindable var model: AppModel
    @ObservedObject var config: AppConfig

    @State private var tokenRevealed = false
    @State private var check: SelfCheckState = .idle
    @State private var showScreenConfig = false

    var body: some View {
        Form {
            envSection
            tokenSection
            overrideSection
            selfCheckSection
            #if os(iOS)
            pushSection
            #endif
            screenConfigSection
            footerSection
        }
        .formStyle(.grouped)
        #if os(iOS)
        .navigationTitle("设置")
        .navigationBarTitleDisplayMode(.inline)
        #endif
        // v1.3.1 Phase B3:iOS/macOS 统一走 sheet 呈现(macOS Settings 场景无 NavigationStack,
        // NavigationLink 在此推不动;sheet 双端都能用,行为一致)。
        .sheet(isPresented: $showScreenConfig) {
            #if os(iOS)
            NavigationStack {
                ScreenConfigView(model: model)
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("完成") { showScreenConfig = false }
                        }
                    }
            }
            #else
            VStack(spacing: 0) {
                HStack {
                    Text("选股参数").font(.system(size: 15, weight: .semibold))
                    Spacer()
                    Button("完成") { showScreenConfig = false }
                }
                .padding(16)
                Divider()
                ScreenConfigView(model: model)
            }
            .frame(width: 480, height: 560)
            #endif
        }
    }

    // MARK: - 选股参数入口

    private var screenConfigSection: some View {
        Section {
            Button {
                showScreenConfig = true
            } label: {
                HStack {
                    Label("选股参数", systemImage: "slider.horizontal.3")
                    Spacer()
                    Image(systemName: "chevron.right").font(.system(size: 12)).foregroundStyle(LN.textTertiary)
                }
            }
            .buttonStyle(.plain)
        } header: {
            Text("选股")
        } footer: {
            Text("调整排序权重与阈值;保存后下次手动刷新候选生效。")
        }
    }

    // MARK: - 环境

    private var envSection: some View {
        Section {
            Picker("环境", selection: $config.environment) {
                ForEach(LNEnvironment.allCases) { env in
                    Text(env.label).tag(env)
                }
            }
            LabeledContent("生效 baseURL") {
                Text(config.resolvedBaseURL.absoluteString)
                    .font(.system(size: 12.5).monospaced())
                    .foregroundStyle(LN.textSecondary)
                    .lineLimit(1).truncationMode(.middle)
            }
        } header: {
            Text("后端连接")
        } footer: {
            Text("Dev 连本机 uvicorn;Prod 连 ECS(ln.linotsai.top,HTTPS)。切换即时生效。")
        }
    }

    // MARK: - API Token(可粘贴 / 明文掩码切换)

    private var tokenSection: some View {
        Section {
            HStack(spacing: 8) {
                Group {
                    if tokenRevealed {
                        TextField("粘贴 API Token", text: $config.apiToken)
                    } else {
                        SecureField("粘贴 API Token", text: $config.apiToken)
                    }
                }
                .font(.system(size: 14).monospaced())
                #if os(iOS)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                #endif
                Button {
                    tokenRevealed.toggle()
                } label: {
                    Image(systemName: tokenRevealed ? "eye.slash" : "eye")
                        .foregroundStyle(LN.textSecondary)
                }
                .buttonStyle(.plain)
            }
            LabeledContent("当前状态") {
                Label(config.hasToken ? "已填入" : "未填入",
                      systemImage: config.hasToken ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(config.hasToken ? LN.up : LN.amber)
            }
        } header: {
            Text("鉴权 Token")
        } footer: {
            Text("Token 仅存本机 UserDefaults,绝不提交进 git。dev 用 backend/.env 的 API_TOKEN;prod 用 ECS 的。")
        }
    }

    // MARK: - baseURL 覆盖(可选)

    private var overrideSection: some View {
        Section {
            TextField("留空则用环境默认", text: $config.baseURLOverride)
                .font(.system(size: 14).monospaced())
                #if os(iOS)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                #endif
        } header: {
            Text("baseURL 覆盖(可选)")
        } footer: {
            Text("临时连别的地址时填,例如 http://192.168.x.x:8001。空则按上方环境。")
        }
    }

    // MARK: - 连接自检

    private var selfCheckSection: some View {
        Section {
            Button {
                Task { await runSelfCheck() }
            } label: {
                HStack {
                    if check == .running {
                        ProgressView().controlSize(.small)
                        Text("自检中…")
                    } else {
                        Image(systemName: "wifi")
                        Text("连接自检")
                    }
                }
            }
            .disabled(check == .running)

            switch check {
            case .idle, .running:
                EmptyView()
            case .ok(let desc):
                Label(desc, systemImage: "checkmark.circle.fill")
                    .font(.system(size: 13))
                    .foregroundStyle(LN.up)
            case .tokenError:
                Label("401 · Token 错或缺(/health 通但 /positions 被拒)",
                      systemImage: "xmark.circle.fill")
                    .font(.system(size: 13))
                    .foregroundStyle(LN.down)
            case .networkError(let m):
                Label(m, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 13))
                    .foregroundStyle(LN.amber)
            }
        } header: {
            Text("连接自检")
        } footer: {
            Text("GET /health(免鉴权)+ GET /positions(带 token)。")
        }
    }

    // MARK: - 推送(iOS 专属)

    #if os(iOS)
    @ViewBuilder
    private var pushSection: some View {
        Section {
            LabeledContent("Device Token") {
                Text(model.pushManager?.lastDeviceToken ?? "未注册")
                    .font(.system(size: 12).monospaced())
                    .foregroundStyle(model.pushManager?.lastDeviceToken == nil ? LN.textTertiary : LN.textSecondary)
                    .lineLimit(1).truncationMode(.middle)
                    .textSelection(.enabled)
            }
            if let err = model.pushManager?.registerError {
                LabeledContent("注册错误") {
                    Text(err)
                        .font(.system(size: 12.5))
                        .foregroundStyle(LN.down)
                        .multilineTextAlignment(.trailing)
                }
            }
            Button {
                Task { await model.pushManager?.requestAuthorizationAndRegister() }
            } label: {
                Label("重新注册推送", systemImage: "bell.badge")
            }
        } header: {
            Text("锁屏推送")
        } footer: {
            Text("切到 prod 后点此,把 device token 重新注册到 prod 库(同一 token 会重发)。模拟器拿不到真 token。")
        }
    }
    #endif

    // MARK: - 页脚

    private var footerSection: some View {
        Section {
            LabeledContent("版本", value: appVersion)
        }
    }

    private var appVersion: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—"
        let b = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "—"
        return "\(v) (\(b))"
    }

    // MARK: - 自检逻辑

    private func runSelfCheck() async {
        check = .running
        let client = APIClient(baseURL: config.resolvedBaseURL, token: config.apiToken)

        // 1) /health(免鉴权)
        let healthOK = (try? await client.health()) ?? false
        guard healthOK else {
            check = .networkError("/health 不可达 · 检查环境 / 网络")
            return
        }

        // 2) /positions(带 token)
        do {
            let r = try await client.fetchPositions()
            check = .ok("health ok · positions ok(\(r.holdings.count) 持仓)")
        } catch APIError.unauthorized, APIError.noToken {
            check = .tokenError
        } catch let e as APIError {
            check = .networkError(e.errorDescription ?? "请求失败")
        } catch {
            check = .networkError(error.localizedDescription)
        }
    }
}
