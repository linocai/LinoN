# LinoN 阶段1（脊椎 + 今日台）审查报告

> 审查人：reviewer（外部审计员视角，从零独立审查）
> 日期：2026-06-22
> 对象：track A 后端脊椎 + track B 客户端 + track C ECS 部署
> 方法：通读全部源码 / pytest 98 + XCTest 17 实跑 / 双端 xcodebuild / ECS 只读核验 / 手工边界推演

## 一、整体评估

- **实现完成度：约 97%**（阶段1 主线三项全达成；缺口集中在阶段3 才消费的数据保真 + 升级状态持久化）。
- **代码质量：高。** 分层清晰（api/monitor/push/data/db/calendar 各司其职），纯函数可注入可单测（hardline/eod/escalation/apns 不联网不真推），常量单一事实源严格执行，注释把"坑"写在代码旁。客户端平台分叉克制、契约对齐、token 不入源码。
- **主要亮点：**
  1. 规则常量（-5.0/+15.0/D4/容差带）真·单一事实源，监控/EOD/客户端三处引用同一份，零漂移。
  2. 升级状态机设计正确：ack 按 code 停所有 kind，D4 时间线在内存常驻、跨收盘/夜间持续 nag 至 ack（due_pushes 不依赖再注册）。
  3. 漏录防护完备（满仓/重复/非持仓三道闸 + 结构化 reason），客户端/Shortcuts 据此弹精准提示。
  4. 安全到位：hmac.compare_digest + startup fail-fast(len≥16)；ECS 上 .env/.p8 均 600；systemd 全套 hardening；无任何密钥入 git。
  5. 数据源归一坑（新浪 Referer、两源 bid/ask 顺序相反、volume/amount 单位）全部正确处理并有样例单测。

## 二、验收逐项核对（对照 plan §4）

| Phase | 验收要点 | 结论 |
|---|---|---|
| A.1 | health 免鉴权 / 业务端点 401 / devices upsert 不增行 | ✅ 实跑 + 单测 + ECS 验 |
| A.2 | open 返 stop_line=buy×0.95 / 满仓 409 / 重复 409 / close 落 trades 归档 / 重复 404 / 形状对齐(含 name 不含 stop_line) | ✅ 全路径 |
| A.3 | D1"明日处理"/D2+"必走"/一字封死/D4 强平/两源存疑不触发/非交易时段不跑 | ✅ 手工推演 + 单测 |
| A.4 | ES256 JWT(kid/iss/iat/≤1h) / category+thread-id+custom / sandbox 网关 / 未 ack 15min 升级角标递增 / ack 停 | ✅ 单测验签 + ECS 真机 200 |
| A.5 | 盘后每持仓推 盈亏%/D几/明日 D4 预警 / 无 token 资金段降级照推 | ✅ 单测 |
| B.1 | 多平台单 target / iOS+macOS 各 build 通过 | ✅ 双端 BUILD SUCCEEDED |
| B.2 | AppModel 派生 + 导航壳分叉 + 两签名组件公式 | ✅ 公式单测逐点核 |
| B.3 | TodayView 双端 + 开/清仓 sheet(止损只读派生) + toast/reason | ✅ |
| B.4 | 拉持仓+本地算 pnl / device token 上报 / 锁屏 category 动作 / 点动作 ack | ✅（真机投递 track C 验） |
| C.1 | /opt/linon + linon 用户 + secret 600 + 权限复原 | ✅ ECS 实查 |
| C.2 | nginx 反代 :8001 + certbot + 邻居无恙 | ✅ 公网 health ok |
| C.3 | systemd active + 公网 health + ECS→APNs sandbox→真机 200 + --failed 为 0 | ✅ ECS 实查 |

**OUT 项干净占位确认**：候选/复盘/记忆 = PlaceholderView（非半成品）；教练横幅 = 占位文案；Tushare 资金校验 = 无 token 降级注明。均干净。

## 三、问题清单

### 🔴 致命：无

### 🟡 重要
1. **monitor loop 每 tick 拉价 3 次**（`backend/app/monitor/loop.py:97-107`）——合并源 + 单独 sina + 单独 tencent，免费源限频/封 IP 风险翻倍。建议 `_build_two_source_quotes` 复用首拉结果，或一致性校验只在两源都齐时做、不额外再拉。
2. **升级状态仅内存，重启丢失**（`backend/app/api/app.py` lifespan，`app.state.escalation`）——价格线自愈（每 tick 重新 register，badge 归 1）；但若 **D4 当天收盘后/夜间重启**，次日 D5 `classify` 不再产出 time 事件（count==5≠4），**D4 强平 nag 永久丢失**（直到下次价格线触发）。直接关系主线①"铁律逼我走"。建议：启动时对 count≥4 的未平持仓从 `positions`（买入日+日历）重建未 ack 时间升级，或把 escalation 关键状态落 SQLite；至少在 plan 标"重启丢升级"为已知限制。
3. **trades.open_time 仅日期粒度**（`backend/app/db/store.py:316`）——存 `buy_date`（'YYYY-MM-DD'）非开仓时刻；Models.swift `TradeRecord.openTime` 是 `Date`，阶段3 ReviewView 要真实时刻算持仓时长。本期无消费方不爆雷，但阶段3 复盘"垃圾进垃圾出"。建议补真时刻或在 plan 阶段3 条目显式标注。

### 🔵 建议
1. 周末/节假日录入 → `buy_date` 落上一交易日 → D 计数提前一天、D4 强平早一交易日（`app.py:43 _current_trade_date`）。已在 CLAUDE.md 标"预期",但对纪律有实影响。建议非交易日录入取**下一**交易日，或开仓回包提示 buy_date 供确认。
2. 客户端 `hitStop ≤ -4.9` vs 后端 `-5.0`（`Models.swift:40`）：pnl ∈ (-5.0,-4.9] 窗口客户端已显示红卡+横幅"已触止损线"但后端未推。设计如此（展示阈 vs 触发阈），唯横幅文案在 0.1% 窗口偏早，可改"逼近止损线"。
3. EOD 推送窗口/"当日已推"依赖内存 `last_eod_date`（`loop.py:211`），重启或错过窗口可能漏/重推。低频非主线，建议落库或加注释。
4. `deploy/linon.service` 仓库仍是阶段0 草稿（`ExecStart=/usr/bin/true`，uvicorn 行注释态），与 ECS 真 unit 脱节。建议把 ECS 真 unit 回写仓库作权威模板。
5. `_resolve_name`（`app.py:222`）开仓同步拉名，盘后/停牌/无网失败 → 落 code 当 name（持仓卡显示纯数字）。建议引导必填 name 或回包带回解析名确认。
6. `Info.plist:25` 对 `127.0.0.1` 设 `NSIncludesSubdomains` 无意义（IP 无子域），可删。

## 四、亲自验过正确的项

- 后端 pytest **98/98 绿**、客户端 XCTest **17/17 绿**、iOS Simulator + macOS 双端 build **成功**（无 body 超时）。
- 线上 `linon.service` active（uvicorn :8001，~40MB RAM），systemd hardening 齐（ProtectSystem=strict/NoNewPrivileges/ReadWritePaths/User=linon），`systemctl --failed` 空；公网 health ok、无 token 401；`.env`/`.p8` 均 600 `linon:linon`。
- 规则常量单一事实源（store.py 定义、hardline/eod import、客户端镜像），零漂移。
- D 计数 off-by-one（买入日=D1）跨连续日/周末/春节/国庆手工推演正确。
- 升级状态机：ack 按 code 停所有 kind、badge 按间隔递增、suspect 不升级、D4 时间线常驻至 ack（**注意 🟡#2 的重启例外**）。
- 硬线 T+1/涨跌停文案、APNs ES256 JWT 可验签、category `HARDLINE` 与客户端一致、漏录三道闸、secrets 卫生、新浪/腾讯解析、客户端公式——全部核对正确。

## 五、结论

**阶段1 可以收口。** 无 must-fix 阻塞项；三项主线（铁律逼走 / 状态闭环 / 今日台真机可用）均已达成并经实跑/ECS/真机验证。🟡 三项建议在阶段2/3 启动前消化（尤其 #2"升级状态重启丢失"关纪律执行、#3"open_time 粒度"关复盘保真）。建议把这两条写进 PROJECT_PLAN §5 Backlog 作阶段2/3 前置项。
