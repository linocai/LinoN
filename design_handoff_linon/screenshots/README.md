# 设计稿截图 / Screenshots

高保真设计稿的导出截图,作为 SwiftUI 实现的视觉参考。可点击的原版见上层 `LinoN.dc.html`(macOS)与 `LinoN iPhone.dc.html`(iOS)。

> 截图为参考外观;所有精确取值(颜色/字号/间距)以 `DesignTokens.swift` 为准。

## iOS(正式客户端 · 计划锁定 SwiftUI)
`ios/`
| 文件 | 屏 | 要点 |
|---|---|---|
| `01-today.png` | 今日持仓 | 大标题 + KPI Hero + 教练横幅 + 持仓卡(双线轨道 / D 计数)+ 底部玻璃标签栏 |
| `02-candidates.png` | 候选列表 | 机械排序卡 · 放量条 · 第 4 行高位警告降级 · 截断脚注 |
| `03-analysis.png` | 深度分析 | DeepSeek 结构化三面(形态/资金/消息)+「可进」建议 +「全仓买入并录入」|
| `04-coach.png` | 反情绪教练 | 触止损后"想再拿一天" → 调出 5/14 复盘教训怼回 |
| `05-review.png` | 周复盘 | 评分 Hero + 三联小计 + 6 周执行率趋势柱 + 每笔点评 |
| `06-memory.png` | 记忆 | 闭环结论 / 长期记忆卡 + 已平仓历史流水(守线徽章)|
| `07-entry-sheet.png` | 开仓录入 | bottom sheet · 止损线只读派生 ¥45.88 = 48.30 × 0.95 |
| `08-lockscreen-push.png` | 锁屏硬线推送 | 玻璃通知 · 第 2 次升级角标 ·「标记次日清仓」· 盘后摘要 |

## macOS(大屏决策台)
`macos/`
| 文件 | 屏 |
|---|---|
| `01-today.png` | 今日持仓(侧栏 + KPI 横条 + 持仓卡)|
| `02-candidates.png` | 候选列表(表格密排)|
| `03-analysis.png` | 深度分析 / 对话 |
| `04-coach.png` | 反情绪教练介入 |
| `05-review.png` | 周复盘 |
| `06-memory.png` | 记忆 |
| `07-open-entry.png` | 开仓录入弹窗(止损派生只读)|
