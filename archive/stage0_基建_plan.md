# archive: 阶段 0 — 基建(数据能稳定拉) · 全文 + 完工记录

> 此文件为 LinoN 阶段 0 当前版本 Plan 的归档全文(原 PROJECT_PLAN.md §4 + §3 阶段0 验收实施记录),版本收口于 2026-06-21。主文件该节已清回阶段1。跨阶段的客户端契约(§4b)仍留在主文件,不在此归档。

## 阶段 0 验收实施记录(原主文件 §3 摘录)

- **阶段 0 验收 = "数据能稳定拉"** ✅(冒烟脚本一次性可见:实时价拉到 / 日历正确 / 库已建 / Tushare 按 token 降级)。
- **已真跑过**(本地):config 无 .env 不崩 / 实时价真源拉到非空 Quote(新浪实测 + 降级编排单测)/ Tushare 无 token 四接口优雅降级 / SQLite 四表 + 开仓→清仓闭合 / 日历 D1–D4 与跨周末·跨国庆 / `setup.sh` 幂等建 venv+库 / `sync.sh` 未配 host 优雅退出 / `smoke.py` 全段可见。**pytest 40 条全绿**(realtime14 / calendar10 / db10 / tushare6)。
- **待联调**(token/SSH/真机就绪后):Tushare 有 token 真拉 daily/moneyflow;实时价**联网+盘中**复测(本期用收盘快照+样例报文);`sync.sh` 真 rsync 到 ECS + 远端 setup;`linon.service` 阶段1 接 FastAPI 后才 enable。
- **落地目录**:`backend/`(`app/{config,data,db,calendar,smoke}` + `scripts/{setup.sh,sync.sh,smoke.py}` + `deploy/linon.service` + `tests/`(4 文件)+ `requirements.txt` + `.env.example`)、`client/`(`DesignTokens.swift`+`Models.swift` 契约拷贝)、`archive/`、根 `.gitignore` + `CLAUDE.md`。

---

## 当前版本 Plan 全文(原 §4)—— 阶段 0:基建(数据能稳定拉)

边界:**只建"日历原语"不让调度器跑起来;只建"持仓交易日数计算函数"不接第 4 日触发推送。** FastAPI 接口本体、轮询守护进程、调度器、APNs、报警判定、开/清仓录入、选股、复盘 → 全部 OUT,推后到阶段 1+。

### Phase 0.1 项目骨架与配置(后端 · monorepo)

- **monorepo 重组**:后端收进 `backend/`(`app/`(config / data / db / calendar / smoke 子模块)、`scripts/`、`data/`(SQLite 落盘)、`requirements.txt`、`.env.example` 均在 `backend/` 下);客户端占位 `client/`(SwiftUI 多平台 Xcode 工程,本期可只放 `DesignTokens.swift`+`Models.swift` 占位、工程骨架可选);根 `.gitignore`。
- 配置模块:**pydantic-settings** `Settings` 读 `.env`,字段含 `TUSHARE_TOKEN`(占位可空)、`DEEPSEEK_API_KEY`(留空)、`DB_PATH`;`.env` 与 `data/*.db` 入 `.gitignore`。
- 依赖钉死版本写入 `requirements.txt`;`git init`(builder 执行)。
- **验收**:在 `backend/` 下 `python -c "from app.config import settings"`,无 `.env`(仅 `.env.example`)时不崩,缺失 token 字段为 None/空串。

### Phase 0.2 实时价(免费多源,后端)

- 接口契约:
  ```
  get_realtime_quote(code: str) -> Quote | None    # 单票;全失败返回 None,不抛崩
  get_realtime_quotes(codes: list[str]) -> dict[str, Quote]
  Quote = {
    code, name, price(现价,float),
    pre_close, open, high, low,
    limit_up, limit_down(涨跌停价;主板±10%、ST±5%;以 pre_close 算或源带均可),
    volume(手), amount(成交额,元),
    bid1..bid5/ask1..ask5(可选), ts(数据时间,str),
    source("sina"|"tencent")
  }
  ```
- **新浪主源 → 腾讯降级**,GBK 解码,归一为统一 `Quote` 结构;源全挂时逐票返回 None / 跳过,整体不崩。
- **涨跌停价**:阶段0 只需让 `Quote` 携带或可推算 `limit_up`/`limit_down`(300/688 已黑名单不做,不涉 ±20%);**用途是阶段1 识别一字板"必走但物理不可执行"**。
- **验收**:对一只真实在交易票拉到非空 `Quote`;主源人为不可用时自动走腾讯。

### Phase 0.3 Tushare 封装(后端)

- 四接口薄封装,**统一带状态返回,token 缺失优雅降级不抛崩**:
  ```
  TushareResult = { ok: bool, data: DataFrame | None, reason: str }   # ok=False 时 reason 说明"token 缺失/限频/网络"
  ts_moneyflow(code, start, end) -> TushareResult      # 主力/小单净额
  ts_daily_basic(code, trade_date) -> TushareResult    # 换手率/涨跌幅/PE-PB
  ts_daily(code, start, end) -> TushareResult          # 日线·形态
  ts_trade_cal(start, end) -> TushareResult            # 交易日历
  ```
- token 缺失/初始化失败时,所有调用返回 `ok=False` 且 `data=None`,**不抛异常**。
- **验收**:无 token 时四接口均返回 `ok=False, reason` 可读;有 token 时 `ts_daily` / `ts_moneyflow` 各拉到一条真实数据。

### Phase 0.4 SQLite 四表(后端)

- 建表 + 初始化 + 基础 CRUD。DDL 摘要(对齐 v2 §11;**持仓为"全有全无",无部分仓位字段;持仓天数不落库**):
  ```
  positions(id, code, name, buy_price, qty, entry_reason,
            entry_snapshot(JSON:形态+资金快照), buy_date(交易日历基准),
            status('holding'), created_at)            -- 最多 3 行
            -- 止损线 = buy_price×0.95,读取时派生、不落库(单一事实源,同持仓天数)
            -- 开仓录入(用户): 代码/买入价/数量/进场理由
            -- 开仓自动补(系统): 形态资金快照(entry_snapshot)/买入日(止损线读取时派生,不存列)
  trades(id, code, open_price, close_price, open_time, close_time,
         kept_stop(bool), kept_take(bool), kept_time(bool),
         pnl, broke_rule(bool), created_at)            -- 每笔一买一卖闭合
  reviews(id, week, score, red_flags(JSON), discipline_rate,
          lessons, next_week_note, created_at)
  memory(id, kind, content, created_at)                -- 闭环结论/长期记忆
  ```
- CRUD 最小集:`open_position`(写 `positions`)、`close_position`(落 `trades` + 归档对应 `positions`)、`list_holdings`、`insert_review`、`insert_memory`。
- **验收**:初始化建四表;开一仓→清一仓,`positions` 归档且 `trades` 落一条闭合记录。

### Phase 0.5 交易日历原语(后端 · 含锁定约束 1+2)

- `trade_cal` 驱动 + **静态 2025–2026 兜底**;**缺 token 用静态表,不崩**;有 token 时拉 `trade_cal` 并与静态表校验对齐(不一致告警)。
- 接口契约:
  ```
  is_trading_day(date) -> bool
  next_trading_day(date) -> date
  prev_trading_day(date) -> date
  trading_window(date) -> [(am_open,am_close),(pm_open,pm_close)] | None
      # 两段(A股有午休): 上午 09:30–11:30 + 下午 13:00–15:00;非交易日 None
      # 注: 集合竞价(9:15–9:25、14:57–15:00)价格行为不同,阶段0 不实现竞价逻辑,仅留注释
  count_holding_trade_days(buy_date, today) -> int       # 闭区间[buy_date,today]内交易日个数;买入日=1
  should_force_close(buy_date, today) -> bool            # == True 当且仅当 count==4(D4 强平)
  ```
- **锁定语义(钉死,builder 不得改)**:`count_holding_trade_days` 数闭区间 `[buy_date, today]` 的交易日个数,**买入日计为 1**;计数 == 4(买入日之后第 3 个交易日)即 `should_force_close` 为真。可卖日 = D2/D3,D4 强平。
- **验收**:用静态表跑一组用例:连续交易日的 D1/D2/D3/D4 计数为 1/2/3/4,`should_force_close` 仅在 D4 为真;跨周末/节假日时按交易日(非自然日)计数正确。
- **已知限制(阶段1 处理)**:① **个股停牌盲区**——`trade_cal` 是市场级,个股停牌时实时价拿不到、硬线无法算、D4 撞停牌卖不掉,日历原语照不到;② **D4 时间止损无独立兜底**——价格线(-5%/+15%)有券商到价提醒人工兜底,**时间触发的 D4 没有**,D4 当天用户无暇则无第二重保险,阶段1 设计应对(如多次升级提醒)。

### Phase 0.6 部署脚手架(运维 · 含锁定约束 3+4)

- `scripts/setup.sh`:**幂等**——建 venv、装 `requirements.txt`、建库(调 0.4 初始化)。可重复执行不报错。
- `scripts/sync.sh`:rsync over SSH,**只同步 `backend/`(显式排除 `client/` 和 `data/`)**,参数化 `host/user/path`,**SSH 连接方式留占位**(读环境变量或 `.env`,未配置时打印提示并退出,不误同步)。
- `deploy/linon.service`:systemd unit **草稿**,留给阶段 1,**本期不启用**(不写 enable/start)。
- **验收**:`setup.sh` 在干净目录跑通建出可用 venv 与库;再跑一次不破坏现状;`sync.sh` 未配 host 时优雅提示退出。

### Phase 0.7 冒烟脚本(可见验收)

- `scripts/smoke.py`:① 拉一只票实时价并打印 `Quote`;② 有 token 时拉一条 `daily` + 一条 `moneyflow` 打印(无 token 打印"已降级:token 缺失");③ 打印 today 附近交易日历(prev/today/next + 是否交易日);④ 建库(调 0.4)。
- **验收(阶段 0 总验收)**:运行 `smoke.py` 一次性可见——实时价拉到、日历原语正确、库已建、Tushare 按 token 有无给出对应结果。即 **"数据能稳定拉"**。

---

## 完工记录(2026-06-21)

数据层四件套 + 部署脚手架 + 冒烟脚本全部落地并本地验收;git init + 干净首提交。目录 = `backend/app/{config,data,db,calendar,smoke}` + `scripts/{setup,sync}.sh` + `smoke.py` + `deploy/linon.service`(草稿态)+ `tests/`(pytest 40 条全绿)+ `client/` 两 .swift 契约。

**关键决策/偏离**:
1. 后端 schema 严格照 plan §4 DDL(`positions` 无 stop_line 列、止损线读取时 ×0.95 派生);**偏离记**:`trades` 表照 plan DDL 建,**未加** Models.swift 上展示用的 `name`/`note` 列(plan DDL 为后端权威,客户端那两列留阶段3 复盘细化时评估,已记 CLAUDE.md)。
2. `kept_stop/kept_take/kept_time/broke_rule` 用机械规则(止损容差带 [-6%,-4%]、止盈 +15%、D4),**注明阶段3 细化**。
3. config 加标准库 fallback(仅 pydantic-settings 未装时启用,不掩盖正式安装)。
4. 静态日历表查证官方 2025/2026 休市+调休补班日硬编码,`verify_against_trade_cal` 留作 token 到位后比对。

**待联调**:Tushare 真 token 拉数 / 实时价联网+盘中复测 / ECS rsync+远端 setup / systemd enable(均列入 §5 用户侧收尾)。项目专属坑沉淀入根 `CLAUDE.md`(新浪 Referer、两源 bid/ask 顺序相反、calendar 包名撞标准库、pydantic v2 不可 setattr 等)。
