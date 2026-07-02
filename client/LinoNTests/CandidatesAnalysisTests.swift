//
//  CandidatesAnalysisTests.swift
//  LinoN — 阶段2 前端 E1/E2 单测
//
//  覆盖:满仓闭门联动(shownCandidates/openSlots/candidatesClosed)、
//  深析卡 DeepAnalysis JSON 解码(对齐后端 dict 形状 + 枚举映射)、
//  buyFromAnalysis 预填开仓 sheet、sendComposer / backFromAnalysis 状态机。
//

import XCTest
@testable import LinoN

@MainActor
final class CandidatesGatingTests: XCTestCase {

    private func makeCandidate(rank: Int, code: String, volPct: Int = 50,
                              warn: String? = nil) -> Candidate {
        let neutral = AnalysisAxis(value: "—", tone: .neutral, text: "")
        let a = DeepAnalysis(form: neutral, fund: neutral, news: neutral, verdict: .watch, plan: "")
        return Candidate(rank: rank, name: "票\(rank)", code: code, sector: "半导体", tag: "平台突破",
                         price: 10, chg: "+2.00%", volMultiple: "2.0x", volPct: volPct,
                         flow: "+0.5亿", turnover: "3.0%", warn: warn, analysis: a)
    }

    private func makePos(_ code: String) -> Position {
        Position(id: Int.random(in: 1...9999), code: code, name: code, buyPrice: 10, qty: 100,
                 entryReason: "x", entrySnapshot: nil, buyDate: Date())
    }

    func testOpenSlotsAndClosed() {
        let m = AppModel()
        XCTAssertEqual(m.openSlots, 3)            // 空仓
        XCTAssertFalse(m.candidatesClosed)
        m.holdings = [makePos("a"), makePos("b"), makePos("c")]
        XCTAssertEqual(m.openSlots, 0)            // 满仓
        XCTAssertTrue(m.candidatesClosed)
    }

    func testShownCandidatesTruncatesByFreeSlots() {
        let m = AppModel()
        m.candidates = (1...20).map { makeCandidate(rank: $0, code: "c\($0)") }
        // 空 3 仓 → 5×3 = 15
        XCTAssertEqual(m.shownCandidates.count, 15)
        // 持 1 → 空 2 → 5×2 = 10
        m.holdings = [makePos("h1")]
        XCTAssertEqual(m.shownCandidates.count, 10)
        // 满仓 → 闭门 → 0
        m.holdings = [makePos("h1"), makePos("h2"), makePos("h3")]
        XCTAssertEqual(m.shownCandidates.count, 0)
    }

    func testShownCandidatesShorterThanLimit() {
        let m = AppModel()
        m.candidates = (1...4).map { makeCandidate(rank: $0, code: "c\($0)") }
        // 候选少于 5×freeSlots 取全部
        XCTAssertEqual(m.shownCandidates.count, 4)
    }

    func testHeadlineAndFootnoteCopy() {
        let m = AppModel()
        m.candidates = (1...20).map { makeCandidate(rank: $0, code: "c\($0)") }
        XCTAssertTrue(CandidatesCopy.headline(m).contains("空 3 仓位"))
        XCTAssertTrue(CandidatesCopy.headline(m).contains("15"))
        m.holdings = [makePos("h1"), makePos("h2"), makePos("h3")]
        XCTAssertTrue(CandidatesCopy.headline(m).contains("闭门"))
    }
}

@MainActor
final class AnalysisStateTests: XCTestCase {

    private func makeCandidate(code: String) -> Candidate {
        let g = AnalysisAxis(value: "强", tone: .good, text: "放量突破")
        let a = DeepAnalysis(form: g, fund: g, news: g, verdict: .enter, plan: "不追高")
        return Candidate(rank: 1, name: "东方电缆", code: code, sector: "海缆", tag: "低位平台突破",
                         price: 48.30, chg: "+4.20%", volMultiple: "2.8x", volPct: 90,
                         flow: "+0.9亿", turnover: "6.2%", warn: nil, analysis: a)
    }

    func testBuyFromAnalysisPrefillsOpenForm() async throws {
        let m = AppModel()
        let c = makeCandidate(code: "603606")
        m.candidates = [c]
        m.selectedCode = "603606"
        m.inAnalysis = true
        m.buyFromAnalysis()
        // 全屏即时关闭;modal 在 iOS 上推到下一 tick(避 cover↔sheet 同帧交接)。
        XCTAssertFalse(m.inAnalysis)
        #if os(iOS)
        try await Task.sleep(nanoseconds: 600_000_000)   // 等过 350ms 推迟窗口
        #endif
        XCTAssertEqual(m.modal, .open)
        XCTAssertEqual(m.form.code, "603606")
        XCTAssertEqual(m.form.name, "东方电缆")
        XCTAssertEqual(m.form.price, "48.30")
        XCTAssertEqual(m.form.reason, "低位平台突破")   // tag 非空 → 用 tag
    }

    func testSendComposerAppendsUserThenAssistant() async {
        // v1.2.1 C3:sendComposer 改 async 真接 /chat;无 clientProvider → runChat 走
        // "未配置后端连接" 降级路径,仍应追加 user + assistant 两条(验证状态机不变,不验证真回复内容)。
        let m = AppModel()
        m.selectedCode = "603606"
        m.composer = "这只能进吗"
        await m.sendComposer()
        XCTAssertEqual(m.thread.count, 2)
        XCTAssertEqual(m.thread[0].role, .user)
        XCTAssertEqual(m.thread[0].text, "这只能进吗")
        XCTAssertEqual(m.thread[1].role, .assistant)
        XCTAssertEqual(m.composer, "")           // 发送后清空
    }

    func testSendComposerIgnoresBlank() async {
        let m = AppModel()
        m.selectedCode = "603606"
        m.composer = "   "
        await m.sendComposer()
        XCTAssertTrue(m.thread.isEmpty)
    }

    func testSendComposerIgnoresWhenNoSelectedCode() async {
        let m = AppModel()
        m.composer = "这只能进吗"
        await m.sendComposer()
        XCTAssertTrue(m.thread.isEmpty)   // 无 selectedCode → 不发送(mode 判定需要 code)
    }

    func testBackFromAnalysisResets() {
        let m = AppModel()
        m.inAnalysis = true
        m.thread = [ChatMessage(role: .user, text: "hi")]
        m.composer = "draft"
        m.analysisContext = AnalysisContext(name: "x", code: "1", price: 1, chg: "+1%",
                                            chgIsUp: true, meta: "", hint: "")
        m.firstVerdict = .enter
        m.firstAssistantMsgId = UUID()
        m.backFromAnalysis()
        XCTAssertFalse(m.inAnalysis)
        XCTAssertTrue(m.thread.isEmpty)
        XCTAssertNil(m.analysisContext)
        XCTAssertEqual(m.composer, "")
        XCTAssertNil(m.firstVerdict)
        XCTAssertNil(m.firstAssistantMsgId)
    }
}

// MARK: - v1.2.1 Phase C:chatTurns(from:) 序列化 + 截断契约(plan §4.2 C3/C3-C4)

@MainActor
final class ChatTurnsSerializationTests: XCTestCase {

    func testMapsFourRolesCorrectly() {
        let m = AppModel()
        let g = AnalysisAxis(value: "—", tone: .neutral, text: "")
        let a = DeepAnalysis(form: g, fund: g, news: g, verdict: .watch, plan: "")
        let thread: [ChatMessage] = [
            ChatMessage(role: .user, text: "u1"),
            ChatMessage(role: .assistant, text: "a1"),
            ChatMessage(role: .coach, text: "c1", analysis: a),
            ChatMessage(role: .analysis, analysis: a),   // 结构卡:跳过不序列化
            ChatMessage(role: .user, text: "u2"),
        ]
        let turns = m.chatTurns(from: thread)
        // .analysis 被跳过,其余四条收敛到 user/assistant 两值。
        XCTAssertEqual(turns.count, 4)
        XCTAssertEqual(turns[0].role, "user");      XCTAssertEqual(turns[0].content, "u1")
        XCTAssertEqual(turns[1].role, "assistant"); XCTAssertEqual(turns[1].content, "a1")
        XCTAssertEqual(turns[2].role, "assistant"); XCTAssertEqual(turns[2].content, "c1")  // .coach → assistant,content=text
        XCTAssertEqual(turns[3].role, "user");      XCTAssertEqual(turns[3].content, "u2")
        // 非法角色收敛:后端 Literal["user","assistant"],映射后不应出现其他值。
        XCTAssertTrue(turns.allSatisfy { $0.role == "user" || $0.role == "assistant" })
    }

    func testTruncatesToLast16FromUserBoundary() {
        let m = AppModel()
        // 构造 20 条交替 user/assistant(10 轮),截断应保留最近 16 条且首条是 user。
        var thread: [ChatMessage] = []
        for i in 1...10 {
            thread.append(ChatMessage(role: .user, text: "u\(i)"))
            thread.append(ChatMessage(role: .assistant, text: "a\(i)"))
        }
        let turns = m.chatTurns(from: thread)
        XCTAssertLessThanOrEqual(turns.count, 16)
        XCTAssertEqual(turns.first?.role, "user")
        // 必须保留最近一条 assistant(保证追问轮后端 is_first 恒 false)。
        XCTAssertEqual(turns.last?.content, "a10")
        // 20 条(u1..a10)取尾 16 条 = 从 u3 起(u1/a1/u2/a2 四条被砍),首条恰为 user 无需再修剪。
        XCTAssertEqual(turns.first?.content, "u3")
    }

    func testTruncationTrimsLeadingAssistantToUserBoundary() {
        let m = AppModel()
        // 构造首条深析(user+assistant)+ 9 轮追问,共 20 条;suffix(16) 落点若非 user 需继续前修。
        var thread: [ChatMessage] = [
            ChatMessage(role: .user, text: "open"),
            ChatMessage(role: .assistant, text: "open-reply"),
        ]
        for i in 1...9 {
            thread.append(ChatMessage(role: .user, text: "u\(i)"))
            thread.append(ChatMessage(role: .assistant, text: "a\(i)"))
        }
        // 共 20 条,尾 16 条从 index 4 开始 = u2(第二轮追问的 user),已是 user 边界,无需再修。
        let turns = m.chatTurns(from: thread)
        XCTAssertEqual(turns.count, 16)
        XCTAssertEqual(turns.first?.role, "user")
        XCTAssertEqual(turns.last?.role, "assistant")
        XCTAssertEqual(turns.last?.content, "a9")
    }

    func testNoTruncationWhenUnder16() {
        let m = AppModel()
        let thread: [ChatMessage] = [
            ChatMessage(role: .user, text: "hi"),
        ]
        let turns = m.chatTurns(from: thread)
        XCTAssertEqual(turns.count, 1)
        XCTAssertEqual(turns[0].role, "user")
    }
}

// MARK: - DeepAnalysis JSON 解码(对齐后端 analyze/coach 返回的 analysis dict 形状)

final class DeepAnalysisDecodeTests: XCTestCase {

    func testDecodesBackendAnalysisShape() throws {
        // 形状 = backend app/llm:form/fund/news 各 {value,tone,text} + verdict + plan
        let json = """
        {
          "form": {"value": "平台突破", "tone": "good", "text": "放量站上 20 日均线。"},
          "fund": {"value": "确认", "tone": "warn", "text": "主力净流入,当日小单流出。"},
          "news": {"value": "无雷", "tone": "neutral", "text": "未见监管警告。"},
          "verdict": "可进",
          "plan": "不追高:回踩平台更稳。"
        }
        """.data(using: .utf8)!
        let a = try JSONDecoder().decode(DeepAnalysis.self, from: json)
        XCTAssertEqual(a.form.value, "平台突破")
        XCTAssertEqual(a.form.tone, .good)
        XCTAssertEqual(a.fund.tone, .warn)
        XCTAssertEqual(a.news.tone, .neutral)
        XCTAssertEqual(a.verdict, .enter)
        XCTAssertEqual(a.plan, "不追高:回踩平台更稳。")
    }

    func testDecodesDegradedPlaceholder() throws {
        // 降级占位卡:verdict=观望、三轴 neutral(后端上游失败仍 200 返此)
        let json = """
        {
          "form": {"value": "暂无", "tone": "neutral", "text": "深判降级。"},
          "fund": {"value": "暂无", "tone": "neutral", "text": ""},
          "news": {"value": "暂无", "tone": "neutral", "text": ""},
          "verdict": "观望",
          "plan": "数据不足,观望。"
        }
        """.data(using: .utf8)!
        let a = try JSONDecoder().decode(DeepAnalysis.self, from: json)
        XCTAssertEqual(a.verdict, .watch)
        XCTAssertEqual(a.form.tone, .neutral)
    }

    func testDecodesAvoidVerdict() throws {
        let json = """
        {
          "form": {"value": "弱", "tone": "bad", "text": "高位。"},
          "fund": {"value": "流出", "tone": "bad", "text": "主力净流出。"},
          "news": {"value": "存疑", "tone": "warn", "text": "舆情转冷。"},
          "verdict": "不进",
          "plan": "不进,等回踩。"
        }
        """.data(using: .utf8)!
        let a = try JSONDecoder().decode(DeepAnalysis.self, from: json)
        XCTAssertEqual(a.verdict, .avoid)
        XCTAssertEqual(a.form.tone, .bad)
    }
}

// MARK: - 阶段3.1:Candidate.score 可选解码(前向兼容窗口期,plan §4.1 🟡#3)

final class CandidateScoreDecodeTests: XCTestCase {

    /// Candidate Codable body(含 analysis 结构,score 位置可选填)。
    /// 注:Candidate 有 `var id = UUID()`,synthesized Codable 解码时该键必需 → JSON 带 id。
    /// 本测试聚焦 score 可选性:score 键缺失时不抛(前向兼容),而非 id。
    private func candidateJSON(withScore: Bool) -> Data {
        let scoreLine = withScore ? "\"score\": 87,\n" : ""
        return """
        {
          "id": "00000000-0000-0000-0000-000000000001",
          "rank": 1, "name": "东方电缆", "code": "603606",
          "sector": "海缆", "tag": "低位平台突破",
          "price": 42.1, "chg": "+3.20%",
          "volMultiple": "2.8x", "volPct": 90,
          "flow": "+1.20亿", "turnover": "4.6%",
          \(scoreLine)"analysis": {
            "form": {"value": "—", "tone": "neutral", "text": ""},
            "fund": {"value": "—", "tone": "neutral", "text": ""},
            "news": {"value": "—", "tone": "neutral", "text": ""},
            "verdict": "观望", "plan": ""
          }
        }
        """.data(using: .utf8)!
    }

    func testDecodesCandidateWithScore() throws {
        let c = try JSONDecoder().decode(Candidate.self, from: candidateJSON(withScore: true))
        XCTAssertEqual(c.score, 87)          // 新后端带 score → 正确填入
        XCTAssertEqual(c.code, "603606")
    }

    func testDecodesOldResponseWithoutScoreDoesNotFail() throws {
        // 前向兼容:新客户端连旧后端(响应无 score 字段)→ 解码不失败、score=nil。
        // 若 score 是非可选,这里会抛 keyNotFound → 整个候选列表解码失败、候选页全空。
        let c = try JSONDecoder().decode(Candidate.self, from: candidateJSON(withScore: false))
        XCTAssertNil(c.score)                // 缺字段 → nil,不抛
        XCTAssertEqual(c.rank, 1)            // 其余字段照常解码
        XCTAssertEqual(c.name, "东方电缆")
    }
}
