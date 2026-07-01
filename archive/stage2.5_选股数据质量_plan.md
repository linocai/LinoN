# 阶段2.5 全文归档:选股数据质量 + 信号回测闭环

> 从 PROJECT_PLAN.md 收口移出的完整 Plan(含 Phase 拆分与实施记录指针)。审查报告见 `archive/REVIEW_REPORT_阶段2.5.md`。

## 4. 当前版本 Plan —— 阶段 2.5:选股数据质量 + 信号回测闭环

> **定位**:两项在阶段2/阶段3 之间的**纯后端**维护性小版本。① 修数据正确性缺陷(技术指标未复权);② 补信号有效性回测闭环(选股规则/DeepSeek verdict 事后命中率)。**与阶段3「复盘闭环——纪律打分」是两回事**:阶段3 打分「用户有没有守规则」,阶段2.5 回测「系统选股准不准」。命名取 2.5 而非「阶段3 一部分」,因它不含任何客户端改动、不动纪律语义,是阶段2 选股链路的直接补强。
>
> **本版本不含前端**:F1/F2 修数据、F3 落回测数据只入库不展示。回测统计结果的可视化(展示端点 + 客户端页面)**留待未来版本**(阶段3 ReviewView 或独立小版本),本版本只保证数据在库里可查、有一个只读端点供调试。
>
> **全期铁律(不可触碰)**:① `-5.0/+15.0/D4/容差带` 仍只在 `store.py` 顶部,新逻辑禁止另起一份;② 止损止盈比例、D4 强平语义、持仓交易日计数(D1 起算)**均不触碰**——本版本不涉及这些;③ 降级铁律:所有新增 Tushare 接口调用缺 token/失败必须优雅降级不崩,守住现有「全链路不崩」契约;④ 不落原始全市场数据(内存紧),回测只加「候选 + 事后收益」轻量记录。

### 4.0 技术选型(本阶段定死,不留给施工)

| 维度 | 决定 |
|---|---|
| 复权接口 | Tushare **`adj_factor`**(全市场按 `trade_date` 单次返回,与 `ts_daily_all` 同批量口径);新增 `tushare_client.ts_adj_factor_all(trade_date)`(全市场单日)+ `ts_adj_factor(code, start, end)`(单票区间),沿现有四接口降级模式(无 token/无权限/限频/网络异常 → `ok=False` 不抛) |
| 复权方式 | **前复权(qfq)**,方向钉死见下「复权序列方向契约」。窗口内以**窗口最新交易日的 adj_factor 为基准**做归一。选前复权因窗口末端(当前价)对齐真实盘口价,技术指标(新高/均线/涨幅)以当前价为锚更符合"现在这个价站没站上均线"的语义 |
| **复权序列方向契约(致命,钉死不得反)** | `qfq_closes(raw_closes, adj_factors) -> list`:入参 **raw_closes / adj_factors 均为新→旧排序**(与 `fetch.py`/`analyze.py` 现有序列一致——`closes[0]` = 最新交易日=今天)。基准 = **`adj_factors[0]`**(新→旧的第 0 个 = 最新日)。公式 `qfq_close[i] = raw_close[i] × adj_factors[i] / adj_factors[0]`。**⇒ 最新日(i=0)close 恒不变**(factor 约成 1),更早日按各自因子相对最新日缩放。**禁止用 `[-1]` 当基准**(那是最早日 = 后复权,历史价整体错位、new_high/ma/pct_60d 全线偏且无除权票测不出)。`compute_form` 消费的 closes 亦为新→旧,内部下标与现有一致 |
| 复权范围 | **只复权 close 序列**(new_high/ma20/pct_60d/当日 pct_chg 依赖价格连续性);**vol 不动**(adj_factor 是价格因子,不改成交量;vol_multiple 用原始量在除权日仍可比,"手"口径不受除权影响) |
| **当日 pct_chg 口径(改)** | `compute_form` 内当日涨跌幅**从复权后的 `closes[0]/closes[1]` 派生**(`(closes[0]-closes[1])/closes[1]×100`),**不再用 daily 原始 `pre_close` 字段**——复权后 today_close 变了而 raw pre_close 没变,除权当天会算出假突变。`compute_form` 不再接收 `pre_close` 参数 |
| 缺 adj_factor 降级 | 某票/某日缺 adj_factor → 该处 `factor=1.0`(退化为原始价,即当前行为),**不崩、不阻塞**;全市场 adj_factor 整体拉取失败 → 全体 factor=1.0(整链路退化为复权前的老行为,候选照出) |
| 形态计算去重 | 抽 `app/screen/form.py`(新模块,纯函数)统一 `fetch.py` 与 `analyze.py` 两处重复的近 N 日形态计算;两处改为调用共享函数,复权在**共享函数内部**统一做(一处修,两处生效)。`ma20` 窗口统一引用 `rules.MA_DAYS`(不照抄 analyze.py 硬编的 `closes[:20]`) |
| 回测 N | **N = 3 个交易日**(呼应 D 型:买入 D1、最迟 D4 卖出 = 持有 3 个交易日;回测"候选录入后持有 3 个交易日的实际涨跌")。回填基准:对 `candidates.trade_date` 往后数 3 个交易日 |
| 回测数据落库 | **新表 `candidate_outcomes`**(见 4.2 DDL),不复用 candidates 表加列(候选是当日快照、结果是 T+3 回填,生命周期不同;分表清晰)。**不落原始全市场数据**,每票只存 1 行轻量结果 |
| **回测收益口径(改·数学正确)** | **`ret_3d` = entry_date 后 3 个交易日 `daily.pct_chg` 累乘**:`ret_3d = (∏_{i=1..3}(1 + pct_chg_i/100) − 1) × 100`(百分比)。`daily.pct_chg` 本身即**复权调整后的真实日收益**(Tushare 已在源头处理除权),除权日天然正确,**不需要为回测另拉 adj_factor,也不做「entry/exit 各自 qfq 再比」**(那样两天基准日不同、基准不约分,窗口内除权即算错——这是回测最需算对的场景)。这 3 天 daily 回填本就要读,零额外接口。`entry_close`/`exit_close` 存原始 `daily.close`(仅供人工核对展示,**不参与 ret_3d 计算**),回测统计一律用 `ret_3d` |
| 回测取价 | 回填读 entry_date 后第 1/2/3 个交易日的 `daily`(每日全市场 `ts_daily_all(d)`,3 次;逐票取 `pct_chg` 累乘)。缺某日/某票 → 该票跳过不落(不崩) |
| 回测触发 | EOD tick 内新增回填步骤(收盘后、候选刷新之后)。**防重不靠内存**:每次 tick **扫描 candidates 里存在、`candidate_outcomes` 里缺记录、且 entry_date 距今已过 `min_trade_days=4` 个交易日(含 entry_date 自身,即 D4 当天/之后)**的候选批量补齐,天然靠 `UNIQUE(entry_date,code)` 幂等防重(重启/错过窗口次日自动补,不永久漏);失败吞异常不掀翻轮询。**口径订正(经 reviewer 验算,见变更日志)**:D1=entry_date,回测需等 entry_date 后第 3 个交易日的 daily 收盘出来才能算 3 日累乘收益,该日就是 D4——故正确判定常量是 `min_trade_days=4` 而非字面"≥3 个交易日已过"(3 会在 D3 未收盘时提前触发,读到不完整数据)。代码 `store.pending_backfill_entries(..., min_trade_days=4)` 是**正确实现**,此处文字已订正对齐代码,不改代码 |
| **Tushare 限频评估(重要)** | 现状 `fetch_market_snapshot` 单次 refresh 已 ~68 次全市场调用(daily×65 + moneyflow_dc×3 + daily_basic×1 + stock_basic×1,ECS 实测 39s)。F2 若在近 65 日循环同步拉 `ts_adj_factor_all(d)` → ~133 次,**很可能撞 Tushare 每分钟限频**;触发后 adj_factor 走降级 factor=1.0 → **复权静默失效(测试/冒烟全绿看不出)**。**落地策略**:① 回测侧已改走 `pct_chg` 累乘、**不用 adj_factor**,adj_factor 全市场拉取只服务 F2 选股复权;② F2 拉 `ts_adj_factor_all` **加节流**(沿 daily 逐日循环间隔,复用现有限频降级)并**查证 6000 积分档 adj_factor 每分钟限额是否够 65 连拉**(builder 冒烟时实测,不够则降到"仅拉当日 + 近 20 日"够算 new_high/ma20,pct_60d 复权可接受近似或对少数除权票单独补拉);③ **可观测性硬要求**:refresh 完成 log 出「adj_factor 拉取成功日数/总日数」,静默大面积失败要能从日志看出来 |
| ECS 内存 | adj_factor 全市场单日 ~5400 行(与 daily 同量级),逐日拉完即用即弃、不驻留全序列——增量内存 << 现有峰值 926MB;回测每次只拉 3 个交易日 daily(非近 65 日),增量更小。真正风险在**接口调用次数/限频**(见上行),非内存 |
| 只读调试端点 | `GET /candidates/outcomes`(鉴权,读 `candidate_outcomes` 聚合统计),**仅供调试/未来前端**,本版本不接客户端 |

### 4.1 回测统计维度(定死口径)

回填后基于 `candidate_outcomes` 可算三类统计(端点聚合返回,不预计算落库):

1. **排序分位分层收益**:按 `rank` 分层(rank 1–5 / 6–10 / 11+),各层平均 `ret_3d`、正收益占比。验证"排序靠前是否真的更强"。
2. **tag 分类胜率**:按 `tag`(放量突破 / 站上均线)分组,各组平均 `ret_3d`、胜率(`ret_3d>0` 占比)。验证哪种形态事后更优。
3. **DeepSeek verdict 命中率**:仅统计**当时做过深判**的候选(`verdict` 非空)。按 verdict(可进 / 观望 / 不进)分组算平均 `ret_3d`,验证"可进"组是否真的跑赢"不进"组。**注**:深判是 on-demand,大部分候选无 verdict → 该维度样本天然稀疏,端点返回时标注样本量,少即诚实标"样本不足"。

### 4.2 新表 DDL(权威,builder 严格照建)

```sql
CREATE TABLE IF NOT EXISTS candidate_outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date    TEXT    NOT NULL,   -- 候选产生日(= candidates.trade_date)'YYYY-MM-DD'
    code          TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    rank          INTEGER NOT NULL,   -- 当时机械排序名次(从 candidates 快照带出)
    tag           TEXT,               -- 当时标签(放量突破/站上均线)
    verdict       TEXT,               -- 深判 verdict(可进/观望/不进);未深判 → NULL
    entry_close   REAL    NOT NULL,   -- 候选日原始 daily.close(仅供人工核对,不参与 ret_3d)
    exit_date     TEXT    NOT NULL,   -- entry_date 后第 3 个交易日 'YYYY-MM-DD'
    exit_close    REAL    NOT NULL,   -- exit_date 原始 daily.close(仅供人工核对,不参与 ret_3d)
    ret_3d        REAL    NOT NULL,   -- 3 个交易日 daily.pct_chg 累乘收益 %(复权正确,见 §4.0「回测收益口径」)
    created_at    TEXT    NOT NULL,
    UNIQUE(entry_date, code)          -- 每票每候选日至多一行(回填幂等)
);

CREATE TABLE IF NOT EXISTS analysis_verdicts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date   TEXT    NOT NULL,    -- = 该 code 所属 candidates 快照的 entry_date(非 latest_candidate_date)
    code         TEXT    NOT NULL,
    verdict      TEXT    NOT NULL,    -- 最近一次候选深判 verdict(可进/观望/不进)
    created_at   TEXT    NOT NULL,
    UNIQUE(trade_date, code)          -- ON CONFLICT DO UPDATE 覆盖为最新一次深判(非保留最早)
);
```

- **verdict 来源(修订,堵 join 取不到的缝)**:回测要 join DeepSeek verdict,但 `/analyze` 现在不落库。F3 增 `analysis_verdicts` 表,`/analyze` 成功时落一行。**关键**:
  - **trade_date 取该 code 在 candidates 缓存里实际所属的 entry_date**,**不是** `latest_candidate_date`——深判 on-demand,用户可能在候选产生 T+1/T+2 才点深判,那时 latest 已滚到新一天,用 latest 会导致回测 join 恒取不到。`/analyze` 端点已需解析该候选(拿 name/sector),遍历时顺手带出它所属的 `entry_date`(在 candidates 里查该 code 命中的 trade_date)。查不到所属候选日(极少数,如直接对非候选票深判)→ **不落 analysis_verdicts**(回测该票 verdict 保持 NULL,不硬塞错日期)。
  - **仅 candidate 模式落**:`/analyze`(候选深判,`mode='candidate'`)才落;**`/positions/{id}/coach`(在持仓深判,`mode='coach'`)一律不落 analysis_verdicts**——coach 是对已买入持仓的判断、不是候选,落进去会污染候选回测。
  - `ON CONFLICT(trade_date,code) DO UPDATE`(覆盖为最新一次深判,非 INSERT OR IGNORE 保留最早)。降级占位卡(verdict=观望)也落(它也是一次真实深判结果),不额外标注来源。**此表只为回测,不改 `/analyze` 响应契约**。

### 4.3 Phase 拆分(全部纯后端;依赖:F1 → F2 → F3;F4 依赖 F3)

**Phase F1 · 复权共享形态模块（后端）**
- 新建 `app/data/tushare_client.py` 接口 `ts_adj_factor_all(trade_date)` + `ts_adj_factor(code, start, end)`(沿降级模式,无 token/失败 `ok=False` 不抛)。
- 新建 `app/screen/form.py`:
  - `qfq_closes(raw_closes, adj_factors) -> list`:入参**均为新→旧**,基准 = `adj_factors[0]`(最新日),`qfq_close[i] = raw_close[i] × adj_factors[i] / adj_factors[0]`;缺因子(None/0/长度不齐)→ 该处 factor=1.0(退化原始价)。**方向契约见 §4.0**,禁止用 `[-1]` 当基准。
  - `compute_form(closes_new_to_old, vols_new_to_old) -> FormResult`(vol_multiple/new_high_20d/above_ma20/pct_60d/pct_chg)。**入参 closes 为已 qfq 的新→旧序列**;当日 pct_chg 从 `closes[0]/closes[1]` 派生(**不收 pre_close 参数**);口径逐字对齐现有:前 5 日均量(`vols[1:6]`)、new_high 用 `closes[1:21]` 且 `>=` 含等号、ma 窗口用 `closes[:rules.MA_DAYS]`(**引用常量,不硬编 20**)、60 日基准 `closes[min(60,len-1)]`。
- **验收**:① **方向断言(区分前/后复权,必须有)**——构造「最新日(i=0)factor=1.0、更早日 factor=0.5」的新→旧序列,断言 `qfq_closes` 后**最新日 close 不变**、更早日 close 被**放大 2×**(若实现取成 `[-1]` 基准则此断言失败,能抓出方向反);② `qfq_closes` 对无除权(adj 恒定)序列 = 原序列、缺因子退化 factor=1.0;③ `compute_form` 对无除权序列产出与现有 `_enrich_form`/`_fetch_form` 完全一致(现有测试数据回归);④ 20日/60日边界窗口不足退化正确。新增 `test_form.py`。

**Phase F2 · 两处形态计算切共享 + 复权（后端）**
- `fetch.py`:近 N 日 daily 循环里**同步逐日拉 `ts_adj_factor_all(d)`**(与 daily 同循环、加节流复用限频降级,按日 join adj_factor 到 `daily_by_date`,缺则该日 factor 缺失→退化);`_enrich_form` **保留为薄封装**(签名不变,`test_screen.py` 有测试直接调它断言字段):内部改为「取本票 close/adj 序列 → `qfq_closes` → `compute_form`」,删掉自己那份放量/新高/均线/涨幅计算。
- `analyze.py`:`_fetch_form` **保留为薄封装**(签名不变):改为拉 `ts_adj_factor(code, start, end)` + `ts_daily` → `qfq_closes` → `compute_form`;删重复计算。可注入 `adj_factor_fn`(单测免联网,沿 `daily_fn` 模式)。
- **可观测性(硬要求)**:`fetch_market_snapshot` 完成后 log 出「adj_factor 拉取成功日数/总日数」(如 `adj_factor 62/65 日拿到`),让限频导致的大面积静默失效能从日志看出。
- **验收**:① grep 确认 vol_multiple/new_high/ma20/pct_60d 只在 `form.py` 一处算(两处不再各写一份);② `_enrich_form`/`_fetch_form` 签名未变,`test_screen`/`test_llm` 现有断言不回归;③ adj_factor 缺失(无 token / 全失败)→ 两处均退化为原始价(等价旧行为);④ 新增测试:构造含除权样例 DataFrame(adj_factor 窗口内跳变),验证复权后 pct_60d/new_high 与不复权**不同且正确**(除权日不被误判暴跌、不漏判新高),当日 pct_chg 从复权 closes 派生(除权日不出假突变);⑤ adj_factor 全市场拉取失败 → 候选照出(退化不崩)。**限频冒烟**:builder 真 token 跑一次 refresh,实测 adj_factor 65 连拉是否撞限频 + 记录耗时/内存峰值(对比 39s / 926MB 基线);若撞限频按 §4.0 落地策略降级(仅拉当日+近20日)。

**Phase F3 · 回测回填 + 深判 verdict 落库（后端）**
- `store.py`:加 `candidate_outcomes` + `analysis_verdicts` 两表 DDL(加入 `_SCHEMA`,`init_db` 幂等建);CRUD:`upsert_candidate_outcome(row)`(幂等 `UNIQUE(entry_date,code)`)、`get_verdict(trade_date, code)`、`upsert_analysis_verdict(trade_date, code, verdict)`(`ON CONFLICT DO UPDATE` 覆盖最新)、`list_outcomes(since=None)`(读回测数据)、`candidate_entry_date_of(code)`(查某 code 在 candidates 里所属的 trade_date,供 `/analyze` 落 verdict 用)、`pending_backfill_entries(today, min_trade_days=3, db_path)`(扫描:candidates 里存在、candidate_outcomes 里缺、且 entry_date 距 today ≥3 交易日的 (entry_date,code) 批)。
- `/analyze` 端点(`app.py`):**仅 candidate 模式**深判成功且 `verdict` 合法时落 `analysis_verdicts`——`trade_date` 取 `store.candidate_entry_date_of(code)`(该 code 所属候选日,**非 latest_candidate_date**);查不到所属候选日 → 不落(verdict 保持 NULL)。**`/coach`(mode=coach)一律不落**。**不改 `/analyze` 响应结构**。
- 新建 `app/screen/backtest.py`:`run_backfill(now, *, daily_all_fn, db_path)`——调 `store.pending_backfill_entries(today)` 拿待回填批(**扫描式,不靠内存 last_backfill_date**);对每个 entry_date,拉其后第 1/2/3 个交易日的 `ts_daily_all(d)`,逐票取 `daily.pct_chg` **累乘**算 `ret_3d`(见 §4.0 收益口径),entry/exit close 存原始 daily.close 供核对,join `analysis_verdicts` 取 verdict,`upsert_candidate_outcome`。缺某日/某票 → 该票跳过不落(不崩)。
- `loop.py`:EOD tick 内候选刷新之后调 `run_backfill(now=now)`;失败吞异常不掀翻轮询。可注入 `_backfill_fn` 免单测联网。**无需 `last_backfill_date` 变量**(扫描式天然幂等 + 补漏)。
- **验收**:① 造 candidates 有 3 交易日前候选 + 造其后 3 日 daily(带 pct_chg)样例 → `run_backfill` 用 pct_chg 累乘算出正确 `ret_3d`、幂等(重跑不重复行,`UNIQUE` 生效);② `pending_backfill_entries` 只返回「≥3 交易日已过 + 未回填」的 entry_date(跨周末用交易日历数,单测冻结 today);③ 重启/错过窗口场景:上次漏回填的 entry_date 次日 tick 自动补齐(不永久漏);④ 缺某日 daily → 该票跳过、其余照落,不崩;⑤ 无 token → daily_all 全失败 → 回填 0 行不崩;⑥ `/analyze` 落 verdict 用所属候选日(造 latest 已滚动的场景验 join 取得到);coach 模式不落 analysis_verdicts;`ON CONFLICT DO UPDATE` 覆盖最新;新增 `test_backtest.py`。

**Phase F4 · 回测统计只读端点（后端）**
- `app.py`:`GET {API_PREFIX}/candidates/outcomes`(鉴权 `require_token`),读 `candidate_outcomes` 聚合返回 4.1 三维度统计 + 样本量。**只读、不接客户端**(本版本仅供调试/未来前端)。响应形状:
  ```
  { "sample_total": int, "since": "YYYY-MM-DD",
    "by_rank_tier":  [{ "tier": "1-5", "n": int, "avg_ret_3d": float, "win_rate": float }, ...],
    "by_tag":        [{ "tag": "放量突破", "n": int, "avg_ret_3d": float, "win_rate": float }, ...],
    "by_verdict":    [{ "verdict": "可进", "n": int, "avg_ret_3d": float, "win_rate": float }, ...],
    "note": "样本量小于阈值时标注仅供参考" }
  ```
- 空数据(回填未跑/无候选)→ `sample_total=0`、各分组空数组、`note` 标"暂无回测样本",HTTP 200(不 500)。
- **验收**:造若干 `candidate_outcomes` 行 → 端点返回分层/分 tag/分 verdict 统计数值正确;空表返回 sample_total=0 不崩;缺 token 401;新增端点测试入 `test_candidates_api.py`。

### 4.4 接口契约小结（本版本对外）

| 端点 | 方法 | 鉴权 | 说明 | 客户端 |
|---|---|---|---|---|
| `/candidates/outcomes` | GET | Bearer | 回测统计聚合(4.1 三维度 + 样本量) | **本版本不接**(留未来前端) |

- 现有 4 端点(`/candidates`、`/candidates/refresh`、`/candidates/{code}/analyze`、`/positions/{id}/coach`)**响应契约不变**;`/analyze` 内部新增 verdict 落库副作用,**响应结构零改动**。
- **不新增/不修改任何客户端代码**;`Candidate`/`DeepAnalysis` schema 不动。

**本阶段归档指针**:阶段2 全文已归档 `archive/stage2_候选决策_plan.md`,审查报告 `archive/REVIEW_REPORT_阶段2.md`。阶段3(复盘闭环——纪律打分)仍待规划,开工时 @planner 填充。

