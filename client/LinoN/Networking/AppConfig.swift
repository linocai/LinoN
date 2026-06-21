//
//  AppConfig.swift
//  LinoN — 后端连接配置(baseURL + apiToken 可配)
//
//  dev 默认 http://127.0.0.1:8001(本地 uvicorn);留好切到
//  https://ln.linotsai.top(track C)的口子。
//
//  ⚠️ API_TOKEN 绝不硬编码进提交源码(plan 硬约束):
//   解析优先级 ——
//    1. UserDefaults("LN_API_TOKEN")  ← App 内 Settings 填入,或预置 plist
//    2. 构建期环境变量 LN_API_TOKEN(scheme 注入,本地开发用)
//    3. gitignored 本地配置 LocalSecrets.plist(若打进 bundle)
//   都缺则 token 为空 —— 业务端点会收 401,Settings 里提示用户填。
//

import Foundation

enum LNEnvironment: String, CaseIterable, Identifiable {
    case dev      // 本地 uvicorn :8001
    case prod     // ln.linotsai.top(track C 上线后)
    var id: String { rawValue }

    var baseURL: URL {
        switch self {
        case .dev:  return URL(string: "http://127.0.0.1:8001")!
        case .prod: return URL(string: "https://ln.linotsai.top")!
        }
    }

    var label: String {
        switch self {
        case .dev:  return "Dev · 127.0.0.1:8001"
        case .prod: return "Prod · ln.linotsai.top"
        }
    }
}

/// 运行期可配置的后端连接。持久化到 UserDefaults;token 不入源码。
@MainActor
final class AppConfig: ObservableObject {
    static let envKey = "LN_ENVIRONMENT"
    static let tokenKey = "LN_API_TOKEN"
    static let baseOverrideKey = "LN_BASE_URL_OVERRIDE"

    @Published var environment: LNEnvironment {
        didSet { UserDefaults.standard.set(environment.rawValue, forKey: Self.envKey) }
    }
    /// 手填覆盖 baseURL(可选;空则用 environment.baseURL)
    @Published var baseURLOverride: String {
        didSet { UserDefaults.standard.set(baseURLOverride, forKey: Self.baseOverrideKey) }
    }
    @Published var apiToken: String {
        didSet { UserDefaults.standard.set(apiToken, forKey: Self.tokenKey) }
    }

    init() {
        let defaults = UserDefaults.standard
        self.environment = LNEnvironment(rawValue: defaults.string(forKey: Self.envKey) ?? "") ?? .dev
        self.baseURLOverride = defaults.string(forKey: Self.baseOverrideKey) ?? ""

        // token 解析:UserDefaults → 环境变量 → 本地 plist
        if let t = defaults.string(forKey: Self.tokenKey), !t.isEmpty {
            self.apiToken = t
        } else if let env = ProcessInfo.processInfo.environment["LN_API_TOKEN"], !env.isEmpty {
            self.apiToken = env
        } else if let plistToken = Self.tokenFromLocalPlist() {
            self.apiToken = plistToken
        } else {
            self.apiToken = ""
        }
    }

    var resolvedBaseURL: URL {
        let trimmed = baseURLOverride.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty, let u = URL(string: trimmed) { return u }
        return environment.baseURL
    }

    var hasToken: Bool { !apiToken.trimmingCharacters(in: .whitespaces).isEmpty }

    /// gitignored 本地配置:Bundle 内 LocalSecrets.plist 的 LN_API_TOKEN 键。
    private static func tokenFromLocalPlist() -> String? {
        guard let url = Bundle.main.url(forResource: "LocalSecrets", withExtension: "plist"),
              let dict = NSDictionary(contentsOf: url),
              let token = dict["LN_API_TOKEN"] as? String,
              !token.isEmpty else { return nil }
        return token
    }
}
