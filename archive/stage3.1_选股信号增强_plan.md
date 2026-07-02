# 阶段3.1 全文归档:选股信号增强(杨永兴"一夜持股法"信号借鉴 + 候选打分展示)

> 从 PROJECT_PLAN.md 收口移出的完整 Plan(含 Phase 拆分与 plan-critic 两轮修订记录)。审查报告见 `archive/REVIEW_REPORT_阶段3.1.md`。

## 4. 当前版本 Plan —— 阶段 3.1:选股信号增强(杨永兴"一夜持股法"信号借鉴)

> **后端为主 + 客户端小改**。把 6 类选股信号借鉴进现有粗筛/排序/深判,**全部软信号**(排序权重 / LLM 深判输入 / warn 软闸),**不新增硬排除**(守铁律:技术面交 LLM 判);并把排序综合分暴露为候选卡上的**当日相对分 `score`**(展示分,归一到 `[SCORE_FLOOR,100]`,见 §4.0)供用户直接看。系统/打法完全不变(2–3 天 D 型 EOD 节奏、止损 -5%/止盈 +15%/D4 强平离场铁律不碰),只碰进场端(选股)。信号来源为源自 Backlog §5"选股增强候选"那节,用户已逐条拍板范围;打分展示为用户 review 后追加需求(2026-07-02)。

### 版本定位与命名

- **阶段 3.1**(不是阶段4,也不合并进阶段4):这批全是选股数据层/排序/深判层的改动,与阶段4(K线图/舆情展示/真机 E2E,均前端打磨)技术面无交集、内聚在选股链路,单独收口更清晰。阶段 3.1 完工后阶段4 仍待规划。
- **打分展示随本版本一起做**:用户 review 后追加"想在候选卡上直接看到分数、不只是排名"。因这个分数(`rank_score` 已在算的加权综合分)只有客户端能展示给用户看,**本版本从"纯后端"扩为"后端 + 客户端小改"**(候选 dict 加 `score` 字段 + `CandidateRow` 双端加展示元素 + 解释条加"当日相对分"文案)。不含其他前端改动。
- **打分口径 = 当日候选池内相对分,不跨天可比**:直接复用 `rank_score` 现有的 min-max 相对归一机制(值域已在 [0,1]),不重新设计跨天可比的固定标尺。排序/截断逻辑完全不动(本就按这个综合加权分取前 `5×free_slots` 名),只是把已在用的中间分数值**暴露**出来展示。
- **效果验证复用阶段2.5 已建回测闭环**:这 6 类信号**目前均未经复盘验证、是经验值定位**,不在本版本重新发明验证机制;上线后靠 `candidate_outcomes`/`analysis_verdicts` 表 + `GET /candidates/outcomes` 端点做事后统计(排序分位分层收益 / tag 胜率 / verdict 命中率),后续复盘迭代调权重/阈值。**本版本只落信号,不做效果分析**。

### 4.0 技术选型定死(6 类信号各自落点、公式、阈值来源)

> **降级铁律**:6 条全部复用现有已拉数据(`daily` 的 close/vol/amount/pct_chg、`daily_basic` 的 total_mv/turnover_rate),**零新增 Tushare 接口调用**(无一条需新拉字段),不触碰阶段2.5 已冒烟的限频边界。
> **常量单一事实源**:本版本新增的经验阈值(换手区间 5%/10%、单日涨幅软闸阈、市值分档、活跃回看 N 日、涨停判定阈)一律放 `app/screen/rules.py` 顶部,仿现有 `VOL_MULTIPLE_MIN`/`WEIGHTS` 写法,**每条标注"经验默认值,可复盘迭代,不卡生死"**;`-5.0/+15.0/D4/容差带` 仍只在 `store.py` 顶部,本版本不碰。

| # | 信号 | 落点 | 计算/公式(数据来源) | 阈值来源 |
|---|---|---|---|---|
| 1 | **收盘站当日 VWAP** | 排序加分 + 深判 prompt | `vwap = amount / vol`(`daily.amount` 千元×1000→元 ÷ `daily.vol` 手×100→股);`vwap_ok = close ≥ vwap`(布尔)。**当日 EOD 即可算** | 无阈值(纯布尔比较) |
| 2 | **量价形态(吸筹 vs 出货)** | **交 LLM 深判**(prompt 新增上下文,非死阈) | 不新增数值计算;把已有 `vol_multiple`(放量倍数)+ 当日 `pct_chg`(单日涨幅,由 `compute_form` 从复权后 `closes[0]/closes[1]` 派生,现已如此)+ `vwap_ok` 一并喂 DeepSeek,prompt 明确要求"区分温和放量缓涨(吸筹,健康)vs 爆量暴拉/放巨量滞涨(出货,危险)" | LLM 判,无死阈 |
| 3 | **换手健康区间** | 排序因子**细化**(改 `WEIGHTS["turnover"]` 的算法) | 把 turnover 从"越高越好 min-max 归一"改为**区间偏好评分函数** `turnover_health_score(t)`:落 `[TURNOVER_HEALTHY_LO, TURNOVER_HEALTHY_HI]` 得满分 1.0;过低(无共识)/过高(筹码松动)按距离线性衰减到 0 | 经验:健康带 `5%–10%`(rules.py 顶部) |
| 4 | **市值弹性偏好** | 排序**新增因子**(消化 dead 字段 `total_mv_yi`) | `mv_score(total_mv_yi)`:中小盘(如 `20–200 亿`)满分,超大盘(`>500 亿`)衰减、微盘(`<15 亿`)衰减(流动性/操纵风险) | 经验:中小盘带 + 微盘/超大盘阈(rules.py 顶部) |
| 5 | **近期活跃(有涨停)** | 排序**新增因子**(不做粗筛软条件,避免误挡) | `had_limit_up`:扫**排除今日**的近 N 日(下标 `[1:1+ACTIVE_LOOKBACK_DAYS]`)`pct_chg`,任一日 `≥ LIMIT_UP_PCT`(主板宽阈,涵盖 9.8%+)即 True;True 加分。**排除今日是刻意的**——"近期弹性"本意是**历史**接力表现,今日暴涨交给信号6单独定性,避免与 #6 在"今天涨停"样本上打架(见 §4.0 下方"信号5/6 不打架"说明)。pct_chg 序列由 `compute_form` 内部从**已复权** `closes` 逐日派生(见 🟡#2 定死) | 经验:回看 `10` 日、涨停阈 `9.8%`(rules.py 顶部) |
| 6 | **单日强弩之末软闸** | 排序**罚分** + warn 软闸(**不新增硬排除**) | **今日** `pct_chg ≥ DAY_SURGE_WARN_PCT`(接近涨停/暴涨)→ 排序扣分 + 追加一条 warn 文案(与 60 日高位 warn 并列,不互斥);**单日维度,区别于已有 60 日累计高位闸**(§4.1 `HIGH_EXCLUDE/WARN`) | 经验:单日软闸阈 `9.0%`(rules.py 顶部) |

**排序权重重构(信号 1/3/4/5/6 汇入 `rank_score`)**:现有 4 因子(`vol 0.40 / fund 0.25 / turnover 0.20 / low_position 0.15`)权重之和 = 1.0。本版本把 turnover 因子改为区间健康评分(#3)、新增 vwap 布尔加分(#1)、市值弹性(#4)、近期活跃(#5)、单日软闸罚分(#6)。**权重方案(经验首版,rules.py 顶部,可迭代)**:
```
vol           0.28   # 放量强度(权重仍最大,略降为新因子腾空间)
fund          0.20   # 资金面(相对口径 net_mf_rate_3d,不变)
turnover      0.14   # 换手【健康区间评分】(#3,不再 min-max)
low_position  0.10   # 低位程度(pct_60d 越低越好,不变)
vwap          0.10   # 收盘站 VWAP(#1,布尔 0/1)
mv_elastic    0.10   # 市值弹性(#4)
active        0.08   # 近期活跃(#5,布尔 0/1)
day_surge     -0.06  # 单日强弩之末罚分(#6,罚项,越暴涨扣越多)
```
和为正权 1.0 + 罚项 -0.06。`rank_score` 入参与返回同序契约不变,仅内部因子扩充;`day_surge` 是罚项(从总分里减)。**具体数值是经验首版、必迭代**,施工按此落地,复盘后调。

**信号5/6 不打架(plan-critic 🟡#1 修订)**:信号5(active)回看窗口**排除今日**(`pct_chg[1:1+N]`),信号6(day_surge)只看**今日** `pct_chg[0]`——两者时间窗互斥。若含今日,则"今日涨停"的票会同时拿 active +0.08 与 day_surge -0.06、净 +0.02 加分,而 warn 却在喊危险(排序奖励 vs warn 警告自相矛盾,且把 #6 想罚的票罚没了)。排除今日后:今日暴涨的票只被 #6 罚 + warn,不被 #5 奖励;历史有过涨停(近期活跃)且今日温和的票才被 #5 奖励——语义各归其位。

**涨停判定数据源定死(plan-critic 🟡#2 修订)**:涨停判定用的 `pct_chg` 序列一律**由 `compute_form` 内部从已复权 `closes` 逐日派生**(`pct[i] = (closes[i]-closes[i+1])/closes[i+1]`),**不传原始 `daily.pct_chg`、不在 fetch.py 补存 pct_chg 字段**。理由:① 复权序列本身已消除除权跳变,除权日不会产生假涨停;② 零新增入参/零新增存储字段;③ 与交易所官方 pct_chg 的舍入级口径差被 9.8% 阈值的 0.2% 容差吸收。**删除原设计里的 `raw_pcts_new_to_old` 入参**(见 §4.1 form.py)。

**候选打分展示(用户追加需求,当日相对分)**:`rank_score` 已在算加权综合分(用于排序取前 N),此前算完即丢、只输出 rank。本版本把这个分数暴露为候选 dict 的 `score`(int):
- **口径 = 当日候选池内相对分,不跨天可比**。`rank_score` 加权和因含 day_surge 负权,理论范围约 `[-0.06, 1.0]`;为得到稳定的展示分,`build_candidates` 在拿到全部 survivors 的原始加权分后,**对这批分数 min-max 归一到 `[SCORE_FLOOR, 100]` 取整**(与 rank 排序用的原始分同源,归一只为展示、不改排序次序)。
- **归一区间用 `[SCORE_FLOOR, 100]`(取 `SCORE_FLOOR=10`,rules.py 顶部经验常量)而非 `[0,100]`(plan-critic 🟡#4 修订)**:避免"末位恒 0 分""两票池必然 100 vs 0"的观感矛盾(系统推荐的票却打 0 分、或两票原始分只差 0.0001 也被拉成 100/0)。floor 抬到 10 是纯展示映射、单调递增变换,**与 rank 严格同序、不影响排序保序性**。
- **归一口径钉死:对【全部 survivors】归一(截断前),展示的是截断后子集**。rank 本就在全量 survivors 上打,score 要与 rank 同源同序就必须在同一全集上归一;端点 `5×free_slots` 截断只是取子集展示,不改各票已算好的 score。**不是**"对截断后子集再归一"(那会让同一票的 score 随当日截断数量漂移)。
- **退化处理**:survivors 为空 → 无候选(无 score);全相等 / 单票 → min==max,统一给中性满分 `100`(即"当日唯一/并列最优",避免除零)。
- **`score` 只服务展示,不参与排序/截断**:排序仍按 `rank_score` 原始加权分降序、截断仍 `5×free_slots`(逻辑零改动)。`score` 与 `rank` 同源同序(rank=1 的 score 恒为当日最高 100)。
- **不跨天比较的护栏**:候选页解释条(`CandidatesExplainBar`)加一句"分数为当日候选池内相对评分,不同日期不可横向比较",防用户误解为绝对质量分。

### 4.1 数据流改动点(逐文件)

- **`app/screen/rules.py`**(常量单一源 + 评分函数):
  - 顶部新增经验常量:`TURNOVER_HEALTHY_LO=5.0`/`TURNOVER_HEALTHY_HI=10.0`、`MV_SMALL_CAP_LO=20.0`/`MV_SMALL_CAP_HI=200.0`/`MV_MICRO_FLOOR=15.0`/`MV_MEGA_CEIL=500.0`(单位亿)、`ACTIVE_LOOKBACK_DAYS=10`/`LIMIT_UP_PCT=9.8`、`DAY_SURGE_WARN_PCT=9.0`、`SCORE_FLOOR=10`(展示分归一下限,见 §4.0 打分展示),每条标注"经验默认值,可复盘迭代,不卡生死"。
  - 更新 `WEIGHTS` 为 4.0 的 8 键方案。
  - 新增纯函数(全部无副作用、可单测):`turnover_health_score(t)→[0,1]`、`mv_elastic_score(mv_yi)→[0,1]`(**`mv_yi<=0`(缺失/默认 0.0)→ 返回中性 0.5,不当微盘惩罚**,与 `_normalize` 全相等中性逻辑一致,plan-critic 🔵)、`day_surge_penalty_norm(pct_chg)→[0,1]`(越暴涨越接近 1,乘以负权)。
  - 重写 `rank_score(...)`:入参新增 `vwap_oks: List[bool]`、`total_mv_yis: List[float]`、`actives: List[bool]`、`day_pcts: List[float]`(与现有 4 个列表等长同序);vol/fund/low_position 沿用 min-max 归一,turnover 改调 `turnover_health_score`(不归一,函数已产 [0,1]),vwap/active 布尔转 0/1,mv 调 `mv_elastic_score`,day_surge 调 `day_surge_penalty_norm` 后乘负权。
  - 新增 `day_surge_warn_text(pct_chg)→Optional[str]`(单日暴涨软闸文案,对齐 `high_warn_text` 写法,非空触发琥珀降级)。
- **`app/screen/form.py`**(复用共享形态计算,新增派生):
  - `FormResult` 加两字段:`vwap_ok: bool = False`、`had_limit_up: bool = False`。
  - `compute_form(closes, vols, ...)` 签名扩展:**只新增一个**可选入参 `amounts_new_to_old: Optional[List[float]] = None`(当日 amount 千元序列,算 VWAP)。**涨停判定不新增入参**——`had_limit_up` 由 `compute_form` **内部从已复权 `closes` 逐日派生 pct 序列**判定(见 🟡#2 定死,删除原 `raw_pcts_new_to_old` 设计)。**缺省 `amounts=None` → `vwap_ok` 保守退化 False;`had_limit_up` 数据不足时 False,不崩、向后兼容现有调用**。
    - VWAP:仅当 `vols[0]>0` 才计算(**除零守卫,plan-critic 🔵**:停牌/异常行 `vol==0` → `vwap_ok=False`,不除零报错);`vwap = amounts[0]×1000 / (vols[0]×100)`(千元→元、手→股),`vwap_ok = closes[0] ≥ vwap`(用复权后 close;amount/vol 是当日绝对量,不受复权影响)。
    - 涨停:内部从已复权 `closes` 逐日派生 `pct[i]=(closes[i]-closes[i+1])/closes[i+1]×100`,扫**排除今日**的 `pct[1 : 1+ACTIVE_LOOKBACK_DAYS]`(🟡#1),任一 `≥ LIMIT_UP_PCT` → `had_limit_up=True`。
- **`app/screen/fetch.py`**(全市场路径,填新字段):
  - `StockRow` 加 `vwap_ok: bool = False`、`had_limit_up: bool = False`(`total_mv_yi` 已有,不再新增);
  - `fetch_market_snapshot` 拉 daily 时在 `daily_by_date` 每日 record 里**补存 `amount`**(当前只取 close/vol/pre_close);`_enrich_form` 给 `compute_form` 传 amount 序列(**不传 pct 序列**——涨停判定已改为 compute_form 内部派生,fetch.py 不补存 pct_chg),把 `result.vwap_ok`/`result.had_limit_up` 写回 `sr`。
- **`app/screen/pipeline.py`**(排序传参 + warn 合并 + score 输出):
  - `build_candidates` 调 `rank_score` 时补传 `vwap_oks`/`total_mv_yis`/`actives`/`day_pcts` 四个列表(从 survivors 派生);
  - 候选 dict 的 `warn` 字段:现有仅 60 日高位 warn;本版本改为**高位 warn 与单日暴涨 warn 择一或合并**(两条都命中时拼接展示),`warn` 仍是单一可选字符串。
  - **候选 dict 新增 `score` 键**(int):**对全部 survivors 的 `rank_score` 原始加权分** min-max 归一到 `[SCORE_FLOOR, 100]` 取整(截断前归一、与 rank 同源同序、只为展示不改次序),全相等/单票退化给中性满分 100(见 §4.0 打分展示口径钉死);`score` 与 `rank` 同序(rank=1→score=100)。**排序/截断逻辑不动**。⚠ **候选 dict 输出形状变更**(新增 `score` 键),但该 dict 要**经 `store.upsert_candidates`/`list_candidates` 才到端点**——见下方 store.py 改动点(不改 store 则 score 在写库被丢弃)。
- **`app/db/store.py`**(候选缓存表 + CRUD,**致命修复:score 契约链路必经此层 + schema migration**):
  - **现状**:`GET /candidates` 不是 pipeline 直吐,而是 pipeline → `upsert_candidates`(固定 13 列 INSERT,`store.py:658`)→ `list_candidates`(逐列显式重建 dict,`store.py:700`)→ 端点透传。两处都**硬编列/键、无 `score`**,不改则 score 在写库这步被静默丢弃。
  - **`candidates` 表加 `score` 列**——**这是货真价实的 schema migration**(ECS 生产库该表阶段2 已上线,`CREATE TABLE IF NOT EXISTS` 不会给已存在表加列)。**迁移姿势拍板:复用阶段3 `_ensure_trades_columns` 那套 `PRAGMA table_info` 探测 + `ALTER TABLE ADD COLUMN`**(项目已有先例、幂等、不丢历史行):新增 `_ensure_candidates_columns(conn)`,`PRAGMA table_info(candidates)` 精确集合探测缺 `score` 则 `ALTER TABLE candidates ADD COLUMN score INTEGER`,**try/except 只 log 不 re-raise**(init_db 跑在 lifespan、每次 ECS 重启执行,展示列迁移绝不能拖垮 startup),在 `init_db` 里 candidates 建表后调用。
  - **为何不 DROP 重建(否决 plan-critic 方案②)**:已确认 `pending_backfill_entries`(`store.py:825`)的回填扫描 **`FROM candidates c LEFT JOIN candidate_outcomes` 读 candidates 表历史行**——DROP 会清掉"已产生候选但回测未回填(entry_date 距今不足 4 交易日)"的历史行,导致这批候选的回测样本永久丢失。故 candidates 表历史行**不可 DROP**,必须走 ALTER 保留历史。
  - `upsert_candidates`:INSERT 列加 `score`,值取 `int(r.get("score", 0))`(pipeline 一定带 score,但给缺省兜底)。
  - `list_candidates`:重建 dict 加 `"score": d.get("score") if d.get("score") is not None else 0`(**旧行 `score=NULL` 回读兜底 0**——ALTER 加列后既有历史行该列为 NULL,回读给 0 不崩;客户端旧行显示 0 分属预期,这些是待回填的历史缓存、不在当前推荐列表)。
- **`app/llm/analyze.py` + `app/llm/prompt.py`**(深判层,信号 1/2 喂 LLM):
  - `analyze.py` 的 `_fetch_form` 返回 dict 补 `vwap_ok`(单票路径 daily 已拉 amount/vol,可算);
  - `prompt.py` 的 `build_user_prompt`【形态】行追加 `收盘站VWAP={form.get('vwap_ok')}`,并在 candidate 模式 system/user 提示里新增一句要求 LLM"结合放量倍数 + 单日涨幅 + 是否站 VWAP 判断量价形态属吸筹(温和放量缓涨、收在均价上)还是出货(爆量暴拉/放巨量收在均价下),形态危险则降 form 轴 tone 或转 verdict 观望"。**深判判定口径不硬编,只加上下文**。
- **`client/Models.swift`**(候选契约,加 score 字段,**前向兼容**):
  - `Candidate` 结构体新增 `var score: Int?`(**可选**);`CandidateListDTO`(列表端点省略 `analysis` 的解码 DTO)也同步加 `score: Int?`。
  - **必须可选,不能非可选(plan-critic 🟡#3 致命窗口期)**:`CandidateListDTO` 现有除 sector/tag/warn 外的字段全非可选;若 `score` 设非可选,"新客户端连旧后端"(响应无 `score` 字段)会导致**整个候选列表解码失败、候选页全空**。而 ECS 现跑阶段2 代码、阶段2.5/3 均"代码完工待部署"——"新客户端 + 旧后端"窗口期几乎必然出现。设 `Int?` 后缺省解码为 nil,`CandidateRow` 缺 score 时**不显示分数徽章**(优雅降级)。
- **`client/LinoN/Views/CandidatesView.swift`**(候选行 + 解释条):
  - `CandidateRow` **双端各自加 score 展示元素**(iOS 竖排行 / macOS 横向多列各补一处):形式贴近现有数值展示元素——建议做成小徽章/数字(可参考 `volPct` 0–100 或 `volMultiple` 数字的展示密度),不做复杂设计;iOS 放在 rank chip 或右侧列附近,macOS 加一窄列或并入现有列。**由 builder 按验收标准落地具体位置**,风格与现有候选卡数值一致(monospacedDigit、贴近 `LN` token 配色)。
  - `CandidatesExplainBar` 加一句"当日相对分,不同日期不可比较"类文案(位置贴近现有解释条 headline;注意阶段2 已修的 iOS 窄屏 pill 换行坑,新增文案走可换行文本、勿塞定宽 pill)。

### 4.2 客户端边界(本版本客户端小改,仅为打分展示)

- **判断结论:客户端只为"打分展示"改,6 条信号本身仍纯后端。**
  - **6 类信号本身零客户端改动**:信号 1/3/4/5 只改**排序位次**(客户端照 `rank` 渲染)、信号 2 只改 **DeepSeek 深析卡内容**(照现有 `DeepAnalysis` schema 渲染)、信号 6 复用**现有 `warn` 可选字符串字段**(`CandidateRow` 已有琥珀降级逻辑)——这三类都无需客户端改。
  - **唯一客户端改动 = 打分展示**:候选 dict 新增 `score`(展示分,归一到 `[SCORE_FLOOR,100]`),需 `Candidate`(+`CandidateListDTO`)加**可选** `score: Int?` 字段(前向兼容,见 §4.1)、`CandidateRow` 双端加展示元素(缺 score 不显示)、解释条加文案。见 §4.1 客户端改动点 + §4.3 Phase D。
- **不新增"近期活跃"等信号标签**:活跃/VWAP/市值弹性只进排序打分(汇入 score),不在候选卡单独立信号标签(避免为经验未验证的信号过早占 UI)。候选卡现有 `tag`("放量突破"/"站上均线")保持不变。
- **契约变更范围(仅 candidates 列表端点 + score)**:`GET /candidates` 候选 dict 新增 `score` 键(camelCase,int);链路 pipeline→`upsert_candidates`→`candidates` 表(加列,ALTER 迁移)→`list_candidates`→端点全程带 score(见 §4.1 store.py)。`DeepAnalysis` schema 零改动、`warn` 仍是 `Optional[str]`、`GET /candidates/outcomes` 回测端点响应零改动、其余端点契约零改动。`entry_snapshot`/持仓/复盘/记忆等所有其他形状不受影响。

### 4.3 Phase 拆分(A/B/C 后端,D 前端;B 依赖 A,C 依赖 A/B,D 依赖 C)

**Phase 拆分判断**:score 的**后端全链路**(pipeline 算分 → `store` 迁移加列 + upsert/list 带 score → 端点)都在同一后端候选缓存链路上,与 Phase C(排序传参 + warn 合并,同在候选 dict 输出这层)天然内聚,**全部并入 Phase C**(含 store.py 的 schema migration——它是 score 到达端点的必经环节,不可拆出);score 的**客户端展示**(Models 加可选字段 + CandidateRow 双端 UI + 解释条文案)是独立技术栈(Swift/xcodegen)、可独立验收的交付单元,**单独拆 Phase D(前端·打分展示)**,依赖 Phase C 的 score 输出就位。

**Phase A（后端·规则层）—— rules.py 常量 + 评分函数 + rank_score 重构**
- 交付:§4.0 全部经验常量入 `rules.py` 顶部(标注"可迭代不卡生死");新增 `turnover_health_score`/`mv_elastic_score`/`day_surge_penalty_norm`/`day_surge_warn_text` 纯函数;`WEIGHTS` 改 8 键方案;`rank_score` 扩入参(4 新列表)并接入新因子(含 day_surge 负权)。
- 验收:
  1. 单测覆盖每个新评分函数的边界（换手 3%/7%/15% 分档、市值 10 亿/50 亿/800 亿 分档、单日涨幅 3%/9.5% 罚分单调性）。
  2. `rank_score` 新入参等长同序、返回同序;全相等输入退化中性（复用 `_normalize` 全 0.5 逻辑）。
  3. 现有旧测试若直接调 `rank_score`（4 参）需同步更新为新签名（施工负责改，不 skip）。
  4. `grep` 断言：所有新经验阈值只在 `rules.py` 顶部出现一份，不在 fetch/pipeline/form 里另写。

**Phase B（后端·数据层）—— form.py + fetch.py 派生 vwap_ok / had_limit_up + amount 序列**
- 依赖 Phase A（常量就位）。
- 交付:`FormResult`/`StockRow` 加 `vwap_ok`/`had_limit_up`;`compute_form` 加**一个**可选入参 `amounts_new_to_old`(涨停判定不新增入参、内部从复权 closes 派生),向后兼容;`fetch_market_snapshot` 拉 daily 时补存 `amount`,`_enrich_form` 传 amount 序列给 `compute_form` 并写回 StockRow。
- 验收:
  1. `compute_form` 不传 `amounts` 时 `vwap_ok` 恒 False；数据不足时 `had_limit_up` False（向后兼容，现有 `_enrich_form`/`_fetch_form` 旧签名调用不崩）。
  2. 单测：造 close 收在 VWAP 上/下两样例验 `vwap_ok`；**`vols[0]==0`（停牌/异常行）→ `vwap_ok=False` 不除零报错（除零守卫）**。
  3. 涨停单测：造近 N 日**历史某日**(下标 ≥1)`pct≈9.9%` 的复权 close 序列 → `had_limit_up=True`；**仅今日(下标 0)暴涨、历史全温和 → `had_limit_up=False`(验排除今日 🟡#1)**；含除权跳变因子的样例复权后不产生假涨停(验从复权 closes 派生 🟡#2)。
  4. VWAP 用当日绝对 amount/vol（不复权，单位换算千元→元、手→股正确），复权只作用于 close。
  5. `_enrich_form` 5 参旧签名（无 adj/amount）仍可调、退化不崩（阶段2.5 已有旧测试直调）。

**Phase C（后端·流水线 + 存储层 + 深判层）—— pipeline 排序传参 + warn 合并 + score 输出 + store 迁移 + prompt/analyze 喂信号 1/2**
- 依赖 Phase A/B。
- 交付:`build_candidates` 给 `rank_score` 补传 4 新列表;候选 `warn` 合并 60 日高位 + 单日暴涨软闸(仍单一字符串);**候选 dict 新增 `score`**(对全部 survivors 原始加权分 min-max 归一到 `[SCORE_FLOOR,100]` 取整、截断前归一、只展示不改排序、全相等/单票给中性 100);**`store.py` 迁移(致命修复)**:新增 `_ensure_candidates_columns`(PRAGMA 探测 + `ALTER ADD COLUMN score`,try/except 只 log,init_db 调用),`upsert_candidates` INSERT 加 `score` 列,`list_candidates` 重建 dict 加 `score`(NULL→0 兜底);`analyze._fetch_form` 返回补 `vwap_ok`;`prompt.build_user_prompt`【形态】行加 `收盘站VWAP` + candidate 模式加量价形态吸筹/出货判定提示。
- 验收:
  1. `build_candidates` 端到端造样例快照，验新因子改变排序位次（如两票放量相同、A 站 VWAP+近期涨停、B 否，A 排在前）。
  2. 单日暴涨票（今日 `pct_chg≥9%`）候选 `warn` 非空且含单日软闸文案；同时 60 日高位则两条合并展示。
  3. `warn` 仍是 `Optional[str]`；`GET /candidates` 响应键集合 = 阶段2 键集合 **+ 新增 `score` 一键**（单测断言键集合精确）。
  4. **`score` 值域校验**：`score` ∈ `[SCORE_FLOOR,100]` 整数；rank=1 的候选 score 恒为 100；单票/全相等 survivors → score 全为 100；`score` 变化不改变 rank 排序次序（同源同序断言）。**两票池断言**：两票原始分极小差距（如 0.5001 vs 0.5000）归一后 = `[100, SCORE_FLOOR]`（不再是 100/0）；末位票 score = `SCORE_FLOOR`（非 0）。
  5. **store 迁移验收（复用阶段3 迁移契约姿势）**：① 对**已存在旧 candidates 表（无 score 列）**跑 `init_db` → `_ensure_candidates_columns` 加列成功；② **连跑 init_db 两/三次不抛 duplicate column、不丢历史行、不改既有值**；③ 旧行 `score=NULL` 经 `list_candidates` 回读为 0 不崩；④ `upsert_candidates`→`list_candidates` round-trip 带 score 一致;⑤ `test_screen.py`/`test_db.py` 里现有候选 upsert/list 回读断言**同步更新为含 score 键**（施工负责改，不 skip）。⑥ grep 断言 `pending_backfill_entries` 回填逻辑未受影响（仍读 candidates 历史行、未 DROP）。
  6. `prompt` 单测：candidate 模式 user prompt 含 `收盘站VWAP=` 与量价形态提示句；coach 模式不受影响（不加吸筹/出货提示，仍二元拿/清）。
  7. 深判降级链不破：`_fetch_form` degraded 时 `vwap_ok` 缺省 `—`，prompt 优雅显示，全链路不崩。
  8. 全后端 pytest 全绿（现有 276 基线 + 本版本新增，无回归）；真 Tushare/DeepSeek 冒烟：refresh 产候选排序体现新因子、候选 dict 经写读库后带合法 `score`、`/analyze` 真 DeepSeek 返回体现量价形态判定。

**Phase D（前端·打分展示）—— Models 加可选 score + CandidateRow 双端展示 + 解释条文案**
- 依赖 Phase C（后端 `score` 输出就位）。
- 交付:`client/Models.swift` 的 `Candidate`(及列表解码用的 `CandidateListDTO`)加 **`var score: Int?`(可选,前向兼容)**;`CandidatesView.swift` 的 `CandidateRow` **iOS + macOS 各加一处 score 展示元素**(小徽章/数字，贴近现有数值展示风格，不做复杂设计;**score 为 nil 时不显示徽章**);`CandidatesExplainBar` 加"当日相对分,不同日期不可比较"类文案(走可换行文本，避开阶段2 已修的 iOS 窄屏 pill 换行坑);**改 .swift 后必 `xcodegen generate`**(项目坑,CLAUDE.md track B)。
- 验收:
  1. `Candidate`/`CandidateListDTO` 解码后端真响应(带 `score`)成功、`score` 正确填入;**解码"无 score 字段的旧后端响应"不失败、`score=nil`(前向兼容窗口期,plan-critic 🟡#3)——单测明确覆盖此场景**。
  2. 双端 build:`xcodebuild -scheme LinoN -destination 'platform=iOS Simulator,...' build` + `-destination 'platform=macOS' build` 各 `BUILD SUCCEEDED`(改 View 必跑 App target,全局经验)。
  3. iOS + macOS `CandidateRow` 都渲染出 score(computer-use 点击受本机 Dock 守卫,退路 `ImageRenderer` 离屏组件快照逐端目检 score 元素在位——注意 `ImageRenderer` 不渲 ScrollView,须单独渲染 CandidateRow 本体,见 CLAUDE.md track E);`score=nil` 时不显示徽章、行布局不塌。
  4. 解释条文案渲染正常、iOS 窄屏不竖排换行(回归阶段2 已修的 pill 换行坑)。
  5. client XCTest 全绿(现有 40 基线,含新增 score 可选解码单测,无回归)。

### 4.4 本版本明确不做（OUT，防蔓延）

- **不做盘中选股**:现有 Tushare daily/daily_basic/moneyflow_dc/adj_factor 全是收盘后 EOD 数据,当日 K 线要等 15:00 收盘才成型(接口产品形态限制,非 token 权限)。维持现有"每天 15:35 EOD 选股、次日开盘决策买入、拿 1–2 天"节奏不变。
- **不改离场规则**:止损 -5%/止盈 +15%/D4 强平/±1% 容差带这套离场铁律完全不动,本版本只碰进场端(选股)。杨的"次日隔夜跳空就卖"框架**完全不借**,所有信号已重新校准服务"2–3 天续强不破位"。
- **不新增硬排除规则**:守铁律"技术面交 LLM 判"——现有黑名单(板块/ST/白酒)、60 日高位线(≥100% 排除)不加新的二元硬排除,6 条全是软信号(排序权重/LLM 输入/warn 软闸)。信号 6 单日软闸只 warn+罚分,**不排除**。
- **不看大盘/板块/题材**:与现有"炒个股不炒大盘"一致,天然不改。
- **不新增 Tushare 接口调用**:6 条全复用现有已拉数据,零新增接口(不触碰阶段2.5 冒烟的限频边界)。
- **客户端只做打分展示这一件事**:`client/` 改动严格限于 `Candidate`(+`CandidateListDTO`)加**可选** `score: Int?` 字段 + `CandidateRow` 双端加 score 展示(nil 不显示)+ 解释条加文案;**不新增信号标签、不改深析卡、不动其他任何 View / 契约**。`DeepAnalysis` schema、`warn` 字段类型、其余端点契约全部零改动。
- **candidates 表不 DROP 重建、不重构现有列**:score 走 ALTER 加列(保留历史行供回测回填,见 §4.1 store.py);现有 13 列、`UNIQUE(trade_date,code)`、`upsert_candidates` 的"整体替换该日缓存"语义、`pending_backfill_entries` 回填扫描逻辑全部不动。
- **不做信号效果分析/可视化**:效果验证复用阶段2.5 已建 `GET /candidates/outcomes` 回测闭环,本版本只落信号入库、不做统计分析视图(那是未来事,信号需先跑一段积累样本)。**打分展示 ≠ 效果分析**:score 只是当日相对排序分的可视化,不含跨天统计/胜率/收益回看。
- **不动阶段2.5/阶段3 已完工代码**:回测表、复盘打分、教练大脑等均不碰;仅在 `analyze.py` 只读地补一个 `vwap_ok` 字段进 prompt。

### 4.5 部署前置(candidates 表 score 列迁移,与阶段3 trades 迁移同类)

- 本版本给 `candidates` 表 ALTER 加 `score` 列(项目第二次真 schema migration)。部署阶段3.1 前,ECS 上先 `cp linon.db linon.db.bak-YYYYMMDD` **备份一次**再让服务重启触发 `_ensure_candidates_columns` 的 ALTER(与阶段3 trades 迁移相同的高危区姿势,已列 §5)。`candidates` 是每日全量替换的缓存,即使迁移异常最坏影响是当日候选,但备份零成本、照旧做。
- 迁移是幂等的(PRAGMA 探测 + try/except 只 log),ECS 每次重启执行不重复加列、不拖垮 startup。

