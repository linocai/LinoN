//
//  CandidatesAnalysisTests.swift
//  LinoN — 阶段2 前端 E1/E2 单测 + v1.3.0 Phase C3 候选放开
//
//  覆盖:候选固定 Top 20(shownCandidates,v1.3.0 起满仓不再闭门)、
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

    /// v1.3.0 Phase C3:满仓不再闭门候选,固定展示 Top 20(不因持仓数变化)。
    func testShownCandidatesFixedTop20RegardlessOfHoldings() {
        let m = AppModel()
        m.candidates = (1...25).map { makeCandidate(rank: $0, code: "c\($0)") }
        XCTAssertEqual(m.shownCandidates.count, 20)   // 空仓 → 仍是 Top 20(非 5×3=15)
        m.holdings = [makePos("h1"), makePos("h2"), makePos("h3")]
        XCTAssertEqual(m.shownCandidates.count, 20)   // 满仓 → 不闭门,仍 Top 20
    }

    func testShownCandidatesShorterThanLimit() {
        let m = AppModel()
        m.candidates = (1...4).map { makeCandidate(rank: $0, code: "c\($0)") }
        // 候选少于 20 取全部
        XCTAssertEqual(m.shownCandidates.count, 4)
    }

    func testHeadlineAndFootnoteCopyNoLongerMentionsClosedDoor() {
        let m = AppModel()
        m.candidates = (1...20).map { makeCandidate(rank: $0, code: "c\($0)") }
        m.holdings = [makePos("h1"), makePos("h2"), makePos("h3")]   // 满仓
        // 满仓不再提"闭门",文案不含旧措辞。
        XCTAssertFalse(CandidatesCopy.headline(m).contains("闭门"))
        XCTAssertFalse(CandidatesCopy.footnote(m).contains("闭门"))
        XCTAssertTrue(CandidatesCopy.headline(m).contains("20"))
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

// MARK: - v1.3.0 Phase D2:三仓相关性护栏(checkCorrelation 触发/静默契约)

@MainActor
final class CorrelationGuardrailTests: XCTestCase {

    /// 无 clientProvider(未配置后端)→ 静默清空,不崩、不弹错。
    func testCheckCorrelationSilentWhenNoClient() async {
        let m = AppModel()
        m.correlationConflict = CorrelationResult(ok: true, conflict: true, industry: "白酒",
                                                   conflictWith: [CorrelationHolding(code: "x", name: "y", industry: "白酒")])
        await m.checkCorrelation(code: "600519")
        XCTAssertNil(m.correlationConflict)   // 无 client → 静默清空,不保留旧值误导
    }

    /// 代码不满 6 位 → 不触发查询(不逐字符打请求),状态清空。
    func testCheckCorrelationSkipsWhenCodeUnder6Digits() async {
        let m = AppModel()
        await m.checkCorrelation(code: "6005")
        XCTAssertNil(m.correlationConflict)
    }

    /// openEntry / dismissModal 打开或关闭表单时清空上一次的相关性状态(不残留旧警示条)。
    func testOpenEntryAndDismissModalClearCorrelationConflict() {
        let m = AppModel()
        m.correlationConflict = CorrelationResult(ok: true, conflict: true, industry: "白酒", conflictWith: [])
        m.openEntry()
        XCTAssertNil(m.correlationConflict)

        m.correlationConflict = CorrelationResult(ok: true, conflict: true, industry: "白酒", conflictWith: [])
        m.dismissModal()
        XCTAssertNil(m.correlationConflict)
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

// MARK: - v1.3.1 Phase A3:Candidate.warnLevel 可选解码(前向兼容 + 红/琥珀分级派生)

final class CandidateWarnLevelDecodeTests: XCTestCase {

    private func candidateJSON(warnLevel: String?) -> Data {
        let warnLevelLine = warnLevel.map { "\"warnLevel\": \"\($0)\",\n" } ?? ""
        return """
        {
          "id": "00000000-0000-0000-0000-000000000002",
          "rank": 1, "name": "东方电缆", "code": "603606",
          "sector": "海缆", "tag": "低位平台突破",
          "price": 42.1, "chg": "+3.20%",
          "volMultiple": "2.8x", "volPct": 90,
          "flow": "+1.20亿", "turnover": "4.6%",
          "warn": "60日累涨120%,极高位,追高高危",
          \(warnLevelLine)"analysis": {
            "form": {"value": "—", "tone": "neutral", "text": ""},
            "fund": {"value": "—", "tone": "neutral", "text": ""},
            "news": {"value": "—", "tone": "neutral", "text": ""},
            "verdict": "观望", "plan": ""
          }
        }
        """.data(using: .utf8)!
    }

    func testDecodesHighWarnLevel() throws {
        let c = try JSONDecoder().decode(Candidate.self, from: candidateJSON(warnLevel: "high"))
        XCTAssertEqual(c.warnLevel, "high")
    }

    func testDecodesAmberWarnLevel() throws {
        let c = try JSONDecoder().decode(Candidate.self, from: candidateJSON(warnLevel: "amber"))
        XCTAssertEqual(c.warnLevel, "amber")
    }

    func testDecodesOldResponseWithoutWarnLevelDoesNotFail() throws {
        // 前向兼容:旧后端无 warnLevel 字段 → 解码不失败、warnLevel=nil(不因新字段挡住整列表解码)。
        let c = try JSONDecoder().decode(Candidate.self, from: candidateJSON(warnLevel: nil))
        XCTAssertNil(c.warnLevel)
        XCTAssertEqual(c.code, "603606")
    }
}

/// v1.3.1 Phase A3:红/琥珀分级派生契约——镜像 CandidateRow.warnOrSector/rowBackground 的
/// switch 逻辑,断言分级严格走 `warnLevel` 字段而非解析 `warn` 文案(CLAUDE.md 红线)。
private enum WarnLevelDerivation {
    static func pillIsRed(_ c: Candidate) -> Bool { c.warn != nil && c.warnLevel == "high" }
    static func pillIsAmber(_ c: Candidate) -> Bool { c.warn != nil && c.warnLevel != "high" }
}

final class WarnLevelDerivationTests: XCTestCase {

    private func makeCandidate(warn: String?, warnLevel: String?) -> Candidate {
        let neutral = AnalysisAxis(value: "—", tone: .neutral, text: "")
        let a = DeepAnalysis(form: neutral, fund: neutral, news: neutral, verdict: .watch, plan: "")
        return Candidate(rank: 1, name: "票", code: "600000", sector: "行业", tag: "",
                         price: 10, chg: "+1.00%", volMultiple: "1.0x", volPct: 50,
                         flow: "+0.1亿", turnover: "1.0%", warn: warn, warnLevel: warnLevel, analysis: a)
    }

    func testHighLevelDerivesRedPill() {
        let c = makeCandidate(warn: "60日累涨120%,极高位,追高高危", warnLevel: "high")
        XCTAssertTrue(WarnLevelDerivation.pillIsRed(c))
        XCTAssertFalse(WarnLevelDerivation.pillIsAmber(c))
    }

    func testAmberLevelDerivesAmberPill() {
        let c = makeCandidate(warn: "60日累涨65%,较高位,注意风险", warnLevel: "amber")
        XCTAssertFalse(WarnLevelDerivation.pillIsRed(c))
        XCTAssertTrue(WarnLevelDerivation.pillIsAmber(c))
    }

    /// 旧后端无 warnLevel(nil)但仍带 warn 文案 → 兜底走琥珀(现状行为),不因缺字段崩成红。
    func testNilLevelWithWarnTextFallsBackToAmberNotRed() {
        let c = makeCandidate(warn: "60日累涨65%,较高位,注意风险", warnLevel: nil)
        XCTAssertFalse(WarnLevelDerivation.pillIsRed(c))
        XCTAssertTrue(WarnLevelDerivation.pillIsAmber(c))
    }

    func testNoWarnShowsNeitherPill() {
        let c = makeCandidate(warn: nil, warnLevel: nil)
        XCTAssertFalse(WarnLevelDerivation.pillIsRed(c))
        XCTAssertFalse(WarnLevelDerivation.pillIsAmber(c))
    }
}

// MARK: - v1.3.0 Phase E:导出同花顺 TXT —— thsMarketSuffix 最长前缀优先判定

final class ThsMarketSuffixTests: XCTestCase {

    func testShanghaiMainBoard60() {
        XCTAssertEqual(thsMarketSuffix("600519"), ".SH")   // 贵州茅台
        XCTAssertEqual(thsMarketSuffix("603986"), ".SH")   // 兆易创新
    }

    func testShanghaiSTAR688And689() {
        XCTAssertEqual(thsMarketSuffix("688981"), ".SH")   // 科创板
        XCTAssertEqual(thsMarketSuffix("689009"), ".SH")   // 九号(CDR)
    }

    func testShanghaiPrefix9() {
        XCTAssertEqual(thsMarketSuffix("900901"), ".SH")   // 沪 B 股等 9 前缀(非 920)
    }

    func testShenzhenMainAndChinext() {
        XCTAssertEqual(thsMarketSuffix("000858"), ".SZ")   // 五粮液(主板 000)
        XCTAssertEqual(thsMarketSuffix("300750"), ".SZ")   // 创业板 300
        XCTAssertEqual(thsMarketSuffix("301051"), ".SZ")   // 创业板 301(非 300 也在 30 段)
    }

    /// 🟡3 核心验收:920xxx 必须判 .BJ,绝不能被 "9" 前缀先命中误判成 .SH
    /// (若判定顺序颠倒 —— 先判 9 再判 920 —— 这条会失败,是防回归的关键锚点)。
    func testBeijingExchange920MustNotBeMisclassifiedAsShanghai() {
        XCTAssertEqual(thsMarketSuffix("920363"), ".BJ")   // 莱赛激光(北交所新段)
        XCTAssertNotEqual(thsMarketSuffix("920363"), ".SH")
    }

    func testBeijingExchangePrefix8And4() {
        XCTAssertEqual(thsMarketSuffix("830799"), ".BJ")   // 8 开头老北交所
        XCTAssertEqual(thsMarketSuffix("430047"), ".BJ")   // 4 开头老三板转北交所
    }

    func testUnknownPrefixReturnsNil() {
        // 构造一个不匹配任何已知前缀段的代码(1 开头目前无对应市场)。
        XCTAssertNil(thsMarketSuffix("100000"))
        XCTAssertNil(thsMarketSuffix(""))
        XCTAssertNil(thsMarketSuffix("12345"))     // 非 6 位
    }

    func testExportTextSkipsUnknownPrefixLines() {
        let neutral = AnalysisAxis(value: "—", tone: .neutral, text: "")
        let a = DeepAnalysis(form: neutral, fund: neutral, news: neutral, verdict: .watch, plan: "")
        func c(_ code: String) -> Candidate {
            Candidate(rank: 1, name: code, code: code, sector: "", tag: "",
                     price: 10, chg: "+1.00%", volMultiple: "1.0x", volPct: 50,
                     flow: "+0.1亿", turnover: "1.0%", warn: nil, analysis: a)
        }
        let list = [c("600519"), c("100000"), c("920363"), c("300750")]
        let text = thsExportText(list)
        let lines = text.split(separator: "\n").map(String.init)
        XCTAssertEqual(lines.count, 3)                 // 100000 未知前缀被跳过
        XCTAssertTrue(lines.contains("600519.SH"))
        XCTAssertTrue(lines.contains("920363.BJ"))
        XCTAssertTrue(lines.contains("300750.SZ"))
        XCTAssertFalse(text.contains("100000"))
    }

    func testExportTextEmptyCandidatesProducesEmptyString() {
        XCTAssertEqual(thsExportText([]), "")
    }
}
