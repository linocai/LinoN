//
//  StaticTradingCalendar.swift
//  LinoN — 客户端交易日历(实现 Models.swift 的 TradingCalendar 协议)
//
//  与后端 app/calendar/static_holidays.py【同源镜像】2025–2026 沪市休市日。
//  关键契约(单一事实源):
//    · 买入日 = D1(闭区间 [buyDate, today] 内的交易日个数)。
//    · shouldForceClose == (count == 4)  —— D4 无条件强平。
//  普通周六/周日按周末判非交易日;表内 = 法定休市 + 调休补班周末(股市仍休)。
//

import Foundation

final class StaticTradingCalendar: TradingCalendar {
    static let shared = StaticTradingCalendar()

    /// 与后端 static_holidays.py 逐字镜像(2025-12 复核口径)。
    private let closed: Set<String> = [
        // —— CLOSED_2025 ——
        "2025-01-01",
        "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
        "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
        "2025-04-04", "2025-04-05", "2025-04-06",
        "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
        "2025-05-31", "2025-06-01", "2025-06-02",
        "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
        "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
        "2025-01-26", "2025-02-08", "2025-04-27", "2025-09-28", "2025-10-11",
        // —— CLOSED_2026 ——
        "2026-01-01", "2026-01-02", "2026-01-03",
        "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
        "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
        "2026-04-04", "2026-04-05", "2026-04-06",
        "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
        "2026-06-19", "2026-06-20", "2026-06-21",
        "2026-09-25", "2026-09-26", "2026-09-27",
        "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
        "2026-10-05", "2026-10-06", "2026-10-07",
        "2026-01-04", "2026-02-14", "2026-02-28", "2026-05-09", "2026-09-20", "2026-10-10",
    ]

    /// 上海时区固定日历(A 股交易日在 Asia/Shanghai 判定)。
    private let cal: Calendar
    private let fmt: DateFormatter

    private init() {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Asia/Shanghai") ?? .current
        self.cal = c
        let f = DateFormatter()
        f.calendar = c
        f.timeZone = c.timeZone
        f.dateFormat = "yyyy-MM-dd"
        self.fmt = f
    }

    func key(_ date: Date) -> String { fmt.string(from: date) }

    func parseDate(_ s: String) -> Date? {
        // 接受 "yyyy-MM-dd" 或带时间前缀
        if let d = fmt.date(from: String(s.prefix(10))) { return d }
        return nil
    }

    // MARK: - TradingCalendar

    func isTradingDay(_ date: Date) -> Bool {
        let weekday = cal.component(.weekday, from: date)   // 1=Sun … 7=Sat
        if weekday == 1 || weekday == 7 { return false }
        return !closed.contains(key(date))
    }

    func nextTradingDay(_ date: Date) -> Date {
        var d = cal.date(byAdding: .day, value: 1, to: date) ?? date
        var guardN = 0
        while !isTradingDay(d) && guardN < 30 {
            d = cal.date(byAdding: .day, value: 1, to: d) ?? d
            guardN += 1
        }
        return d
    }

    func prevTradingDay(_ date: Date) -> Date {
        var d = cal.date(byAdding: .day, value: -1, to: date) ?? date
        var guardN = 0
        while !isTradingDay(d) && guardN < 30 {
            d = cal.date(byAdding: .day, value: -1, to: d) ?? d
            guardN += 1
        }
        return d
    }

    /// 闭区间 [buyDate, today] 内交易日个数,买入日 = 1。
    func countHoldingTradeDays(buyDate: Date, today: Date) -> Int {
        let start = cal.startOfDay(for: buyDate)
        let end = cal.startOfDay(for: today)
        if end < start { return 0 }
        var count = 0
        var d = start
        var guardN = 0
        while d <= end && guardN < 400 {
            if isTradingDay(d) { count += 1 }
            d = cal.date(byAdding: .day, value: 1, to: d) ?? d
            guardN += 1
        }
        return count
    }

    /// D4 强平:当且仅当 count == 4。
    func shouldForceClose(buyDate: Date, today: Date) -> Bool {
        countHoldingTradeDays(buyDate: buyDate, today: today) == 4
    }
}
