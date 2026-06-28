//
//  APIClient.swift
//  LinoN — 后端 REST 客户端(track A FastAPI on :8001)
//
//  端点契约见 PROJECT_PLAN §4 A.1/A.2/A.4 + backend/app/api/app.py:
//    GET  /api/v1/positions                 → { holdings:[Position], free_slots }
//    POST /api/v1/positions/open            → { ok, position_id, stop_line, take_line, buy_date }
//                                             409 slots_full / duplicate_holding · 422 字段
//    POST /api/v1/positions/{id}/close      → { ok, trade_id, pnl, kept_*, broke_rule }
//                                             404 not_holding
//    POST /api/v1/devices                   → { ok }
//    POST /api/v1/alerts/{code}/ack         → { ok }
//  鉴权:Authorization: Bearer <API_TOKEN>(health 外全部)。
//

import Foundation

// MARK: - 错误类型(结构化 reason,UI 据此弹提示)

enum APIError: Error, LocalizedError, Equatable {
    case unauthorized
    case slotsFull          // 409 满仓
    case duplicateHolding   // 409 同 code 已持
    case notHolding         // 404 已清/不存在
    case validation(String) // 422 字段校验
    case server(Int, String)
    case transport(String)
    case noToken

    var errorDescription: String? {
        switch self {
        case .unauthorized:     return "鉴权失败(检查 API Token)"
        case .slotsFull:        return "已满 3 仓 · 先清一只再开"
        case .duplicateHolding: return "该股已在持仓 · 不可重复开仓"
        case .notHolding:       return "该持仓已清或不存在"
        case .validation(let m): return "字段校验失败:\(m)"
        case .server(let c, let m): return "服务端错误 \(c):\(m)"
        case .transport(let m): return "网络错误:\(m)"
        case .noToken:          return "未配置 API Token · 去设置填入"
        }
    }
}

// MARK: - 请求/响应载荷

struct OpenPositionRequest: Encodable {
    let code: String
    let name: String
    let buy_price: Double
    let qty: Int
    let entry_reason: String
}

struct OpenPositionResponse: Decodable {
    let ok: Bool
    let position_id: Int
    let stop_line: Double
    let take_line: Double
    let buy_date: String
}

struct ClosePositionRequest: Encodable {
    let sell_price: Double
    let sell_time: String?   // ISO8601;缺省服务端用当前时刻
}

struct ClosePositionResponse: Decodable {
    let ok: Bool
    let trade_id: Int
    let pnl: Double
    let kept_stop: Bool
    let kept_take: Bool
    let kept_time: Bool
    let broke_rule: Bool
}

struct DeviceRegisterRequest: Encodable {
    let token: String
    let platform: String   // "ios"
}

// MARK: - 阶段2:候选 / 深判 / 教练(plan §4.3)

/// GET /candidates 响应(plan §4.3:满仓/无缓存 → degraded + 空列表)。
struct CandidatesResult {
    let candidates: [Candidate]
    let freeSlots: Int
    let tradeDate: String
    let degraded: Bool
    let reason: String?
}

/// 列表端点 candidates 形状(camelCase,逐字段对齐 Models.swift Candidate;
/// 列表里 analysis 省略,深判 on-demand,故此处 analysis 解码为占位)。
private struct CandidateListDTO: Decodable {
    let rank: Int
    let name: String
    let code: String
    let sector: String?
    let tag: String?
    let price: Double
    let chg: String
    let volMultiple: String
    let volPct: Int
    let flow: String
    let turnover: String
    let warn: String?
}

private struct CandidatesListResponse: Decodable {
    let candidates: [CandidateListDTO]
    let free_slots: Int
    let trade_date: String
    let degraded: Bool
    let reason: String?
}

/// POST /candidates/{code}/analyze 响应(plan §4.3)。
struct AnalyzeResult {
    let code: String
    let analysis: DeepAnalysis
    let fundAsof: String
}

private struct AnalyzeResponse: Decodable {
    let ok: Bool
    let code: String
    let analysis: DeepAnalysis
    let fund_asof: String
}

/// POST /positions/{id}/coach 请求/响应(plan §4.3;advice 二元 拿/清)。
struct CoachRequestBody: Encodable {
    let question: String?
}

struct CoachResult {
    let advice: String        // "拿" | "清"
    let reason: String
    let analysis: DeepAnalysis
    let fundAsof: String
}

private struct CoachResponse: Decodable {
    let ok: Bool
    let advice: String
    let reason: String
    let analysis: DeepAnalysis
    let fund_asof: String
}

struct AlertAckRequest: Encodable {
    let action: String     // "marked_close" | "dismissed"
}

/// 无请求体 POST 占位({})。
struct EmptyBody: Encodable {}

/// GET /positions 响应(对齐 backend PositionsList + Models.swift Position 形状)。
private struct PositionsListResponse: Decodable {
    let holdings: [PositionDTO]
    let free_slots: Int
}

/// 后端返回的 Position 形状(snake_case);转 Models.swift Position。
private struct PositionDTO: Decodable {
    let id: Int
    let code: String
    let name: String
    let buy_price: Double
    let qty: Int
    let entry_reason: String
    let buy_date: String
    let status: String
    let price: Double
    let flow3d: String
}

// MARK: - APIClient

actor APIClient {
    private let baseURL: URL
    private let token: String
    private let session: URLSession

    init(baseURL: URL, token: String, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.token = token
        self.session = session
    }

    // —— 拉持仓 ——
    func fetchPositions() async throws -> (holdings: [Position], freeSlots: Int) {
        let data = try await get("/api/v1/positions")
        let resp = try JSONDecoder().decode(PositionsListResponse.self, from: data)
        let cal = StaticTradingCalendar.shared
        let positions = resp.holdings.map { dto -> Position in
            var p = Position(
                id: dto.id, code: dto.code, name: dto.name,
                buyPrice: dto.buy_price, qty: dto.qty,
                entryReason: dto.entry_reason, entrySnapshot: nil,
                buyDate: cal.parseDate(dto.buy_date) ?? Date(),
                status: dto.status
            )
            // 后端供 price;为 0(无网络/拉价失败)时按 buy_price 兜底,客户端 pnl=0
            p.price = dto.price > 0 ? dto.price : dto.buy_price
            p.flow3d = dto.flow3d
            return p
        }
        return (positions, resp.free_slots)
    }

    // —— 开仓 ——
    func openPosition(_ req: OpenPositionRequest) async throws -> OpenPositionResponse {
        let data = try await post("/api/v1/positions/open", body: req)
        return try JSONDecoder().decode(OpenPositionResponse.self, from: data)
    }

    // —— 清仓 ——
    func closePosition(id: Int, _ req: ClosePositionRequest) async throws -> ClosePositionResponse {
        let data = try await post("/api/v1/positions/\(id)/close", body: req)
        return try JSONDecoder().decode(ClosePositionResponse.self, from: data)
    }

    // —— 设备注册(iOS APNs token)——
    @discardableResult
    func registerDevice(token deviceToken: String) async throws -> Bool {
        _ = try await post("/api/v1/devices",
                           body: DeviceRegisterRequest(token: deviceToken, platform: "ios"))
        return true
    }

    // —— 硬线 ack(停升级)——
    @discardableResult
    func ackAlert(code: String, action: String) async throws -> Bool {
        _ = try await post("/api/v1/alerts/\(code)/ack",
                           body: AlertAckRequest(action: action))
        return true
    }

    // —— 阶段2:拉候选(GET /candidates;后端已按 5×free_slots 运行时截断)——
    func fetchCandidates() async throws -> CandidatesResult {
        let data = try await get("/api/v1/candidates")
        let resp = try JSONDecoder().decode(CandidatesListResponse.self, from: data)
        // 列表 analysis 省略 → 填占位(深判 on-demand 时由 /analyze 覆盖)。
        let neutral = AnalysisAxis(value: "—", tone: .neutral, text: "")
        let placeholder = DeepAnalysis(form: neutral, fund: neutral, news: neutral,
                                       verdict: .watch, plan: "")
        let list = resp.candidates.map { dto -> Candidate in
            Candidate(rank: dto.rank, name: dto.name, code: dto.code,
                      sector: dto.sector ?? "", tag: dto.tag ?? "",
                      price: dto.price, chg: dto.chg,
                      volMultiple: dto.volMultiple, volPct: dto.volPct,
                      flow: dto.flow, turnover: dto.turnover,
                      warn: (dto.warn?.isEmpty == false) ? dto.warn : nil,
                      analysis: placeholder)
        }
        return CandidatesResult(candidates: list, freeSlots: resp.free_slots,
                                tradeDate: resp.trade_date, degraded: resp.degraded,
                                reason: resp.reason)
    }

    // —— 阶段2:on-demand 深判候选(POST /candidates/{code}/analyze;上游失败仍 200 返占位卡)——
    func analyzeCandidate(code: String) async throws -> AnalyzeResult {
        let data = try await post("/api/v1/candidates/\(code)/analyze", body: EmptyBody())
        let resp = try JSONDecoder().decode(AnalyzeResponse.self, from: data)
        return AnalyzeResult(code: resp.code, analysis: resp.analysis, fundAsof: resp.fund_asof)
    }

    // —— 阶段2:中间地带教练(POST /positions/{id}/coach;非持仓 404)——
    func coachPosition(id: Int, question: String? = nil) async throws -> CoachResult {
        let data = try await post("/api/v1/positions/\(id)/coach",
                                  body: CoachRequestBody(question: question))
        let resp = try JSONDecoder().decode(CoachResponse.self, from: data)
        return CoachResult(advice: resp.advice, reason: resp.reason,
                           analysis: resp.analysis, fundAsof: resp.fund_asof)
    }

    // —— health(免鉴权,联通性自检)——
    func health() async throws -> Bool {
        let url = baseURL.appendingPathComponent("/api/v1/health")
        var req = URLRequest(url: url)
        req.timeoutInterval = 8
        let (data, resp) = try await session.data(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else { return false }
        let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        return (obj?["status"] as? String) == "ok"
    }

    // MARK: - 传输层

    private func get(_ path: String) async throws -> Data {
        try ensureToken()
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = "GET"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.timeoutInterval = 12
        return try await send(req)
    }

    private func post<B: Encodable>(_ path: String, body: B) async throws -> Data {
        try ensureToken()
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(body)
        req.timeoutInterval = 12
        return try await send(req)
    }

    private func ensureToken() throws {
        if token.trimmingCharacters(in: .whitespaces).isEmpty { throw APIError.noToken }
    }

    private func send(_ req: URLRequest) async throws -> Data {
        let data: Data
        let resp: URLResponse
        do {
            (data, resp) = try await session.data(for: req)
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
        guard let http = resp as? HTTPURLResponse else {
            throw APIError.transport("无 HTTP 响应")
        }
        switch http.statusCode {
        case 200...299:
            return data
        case 401:
            throw APIError.unauthorized
        case 409:
            throw mapReason(data, fallback: .server(409, "冲突"))
        case 404:
            throw APIError.notHolding
        case 422:
            throw APIError.validation(reasonString(data) ?? "请检查输入")
        default:
            throw APIError.server(http.statusCode, reasonString(data) ?? "未知错误")
        }
    }

    /// FastAPI 的 HTTPException(detail={ok:false, reason:...})落在 "detail" 里。
    private func mapReason(_ data: Data, fallback: APIError) -> APIError {
        guard let reason = reasonString(data) else { return fallback }
        switch reason {
        case "slots_full":        return .slotsFull
        case "duplicate_holding": return .duplicateHolding
        case "not_holding":       return .notHolding
        default:                  return fallback
        }
    }

    private func reasonString(_ data: Data) -> String? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if let detail = obj["detail"] as? [String: Any] {
            if let r = detail["reason"] as? String { return r }
        }
        if let detailStr = obj["detail"] as? String { return detailStr }
        // 422 的 detail 是数组
        if let arr = obj["detail"] as? [[String: Any]], let first = arr.first,
           let msg = first["msg"] as? String { return msg }
        return nil
    }
}
