//
//  HoldingDayPips.swift
//  LinoN — 签名组件②:D1–D4 持仓交易日计数器
//
//  四态(§4b / README):
//    · 已过的日(i < day):实心黑
//    · 当前日(i == day):蓝色描边环;触止损时红环
//    · 第 4 日(i == 4 且未到):红色虚边(强平日)
//    · 未到(其余):灰
//  契约:should_force_close == (count == 4)。
//

import SwiftUI

struct HoldingDayPips: View {
    let day: Int        // 当前持仓交易日(1…4+)
    var hitStop: Bool = false

    var body: some View {
        HStack(spacing: 6) {
            ForEach(1...4, id: \.self) { i in
                pip(for: i)
            }
        }
    }

    @ViewBuilder
    private func pip(for i: Int) -> some View {
        if i < day {
            // 已过:实心黑
            Circle()
                .fill(LN.textPrimary)
                .frame(width: 8, height: 8)
        } else if i == day {
            // 当前:蓝环(触损红环)
            Circle()
                .fill((hitStop ? LN.down : LN.accent).opacity(0.15))
                .frame(width: 10, height: 10)
                .overlay(Circle().stroke(hitStop ? LN.down : LN.accent, lineWidth: 2))
        } else if i == 4 {
            // 第 4 日未到:红虚边(强平日)
            Circle()
                .fill(Color.white)
                .frame(width: 8, height: 8)
                .overlay(Circle().stroke(LN.down.opacity(0.5), lineWidth: 1.5))
        } else {
            // 未到:灰
            Circle()
                .fill(Color(hex: 0xDCDEE3))
                .frame(width: 8, height: 8)
        }
    }
}

#if DEBUG
#Preview("HoldingDayPips") {
    VStack(alignment: .leading, spacing: 18) {
        HStack { Text("D1").frame(width: 30); HoldingDayPips(day: 1) }
        HStack { Text("D2").frame(width: 30); HoldingDayPips(day: 2) }
        HStack { Text("D3").frame(width: 30); HoldingDayPips(day: 3) }
        HStack { Text("D3 触损").frame(width: 60); HoldingDayPips(day: 3, hitStop: true) }
        HStack { Text("D4").frame(width: 30); HoldingDayPips(day: 4) }
    }
    .padding(40)
}
#endif
