# LinoN 阶段2.5(选股数据质量 + 信号回测闭环)审查报告

> reviewer:外部审计员视角从零审查,对照 `PROJECT_PLAN.md` §4(4.0–4.4,F1–F4)。审查日期 2026-07-01。
> 门禁亲自跑通(非信 builder 自述);复权方向做了"手动翻转基准验证测试有效性"的破坏性实验;
> 活 token 下用网络哨兵扫过泄漏;`/candidates/outcomes` 端点做了真 HTTP 活体冒烟;
> daily/adj_factor 的 trade_date join 用真 Tushare 拉数验证对齐。

## 整体评估

- **实现完成度:约 98%**。F1–F4 四个 Phase 全部落地,验收标准逐项命中。plan-critic 两轮抓出的
  2 致命(复权方向、回测收益口径)+ 4 重要(限频/verdict join/DDL/防重)在实现里全部正确落实。
  无遗漏 Phase、无 plan 之外的多余功能(改动范围严格收敛在 plan 列举模块内)。剩余 2% 为下文
  几条文档/测试盲区打磨项,均不影响收口。
- **整体代码质量:高**。复权/回测抽成纯函数(form.py / backtest.py 可注入),降级处处兜底且有
  单测;新表 DDL 逐字对齐 plan §4.2;`_maybe_persist_verdict` 严格只在 candidate 模式落库;
  钉死常量(-5.0/+15.0/D4/容差带)零触碰。注释把"为什么"写清(方向契约/收益口径/防重语义)。
- **主要亮点**:
  1. **复权方向契约真被测试守住**:`test_form.py` 的方向断言不是摆设——reviewer 把 `form.py`
     基准临时改成 `[-1]`(后复权)后,两条方向断言【真的失败】(期望最新日 50.0、后复权算出
     25.0),恢复 `[0]` 后全绿。证明方向对 + 测试有效(能抓出方向反),这是 plan-critic 致命1 的
     核心防线。
  2. **回测收益口径数学正确且不碰复权**:`backtest.py` 全文零 adj_factor/qfq 引用,`ret_3d` 就是
     `∏(1+pct_chg_i/100)-1`(pct_chg 本身即复权后真实日收益)。避开了"entry/exit 各自 qfq 两天
     基准不约分"的致命2 陷阱。
  3. **活 token 下零网络泄漏**:测试环境 `.env` 的 TUSHARE_TOKEN/DEEPSEEK_API_KEY 是活的(若有
     测试裸调真接口会真连)。reviewer 用 autouse 哨兵把所有 ts_*/realtime 真实入口打成"一调就
     炸"跑全套,零炸点;并 grep 确认所有 deepseek.analyze(带 MockTransport)/fetch_sentiment
     (带 fetch_fn)/analyze_stock(带 adj_factor_fn)调用点都注入了替身。builder 自述修的
     `test_analyze_stock_full_chain` 泄漏确已堵住,无其它遗漏。
  4. **coach 不污染候选回测**:`/positions/{id}/coach` 端点确认【没有】落 analysis_verdicts 副作用
     (`test_coach_does_not_persist_verdict` 验证:即便该 code 有 entry_date 可查,coach 也不落)。

### 门禁亲验结果(全部真实跑通)

| 门禁 | 结果 |
|---|---|
| 后端 `python -m pytest` | **227 passed**, 1 warning(urllib3 LibreSSL 无害)。= 基线 193 + 新增 34。新增文件 test_form.py 11 / test_backtest.py 9;其余 14 分布在 test_screen(→44)/test_llm(→20)/test_candidates_api(→24)/test_monitor_loop/test_db 增量。 |
| 网络泄漏哨兵(活 token,全套) | **零 NETGUARD 炸点**。所有 Tushare/realtime 真实入口打成炸弹后全套仍 227 绿 → 无测试真连外网。 |
| 复权方向破坏性验证 | 基准改 `[-1]` → 方向断言【FAILED】(测试有效);恢复 `[0]` → 全绿。 |
| `/candidates/outcomes` 活体冒烟(真 uvicorn+真 token) | 缺 token→**401**;带 token 有数据→三维度聚合数值正确(tier 1-5 avg=5.0 win=0.5 / 6-10 avg=10.0 win=1.0;by_tag/by_verdict 均对;note="样本量小于阈值,仅供参考");since=未来→sample_total=0 各组空数组 note="暂无回测样本" **HTTP 200 不 500**。 |
| daily/adj_factor join 对齐(真 Tushare) | 603986 拉 6 月:daily 与 adj_factor 的 trade_date 均 'YYYYMMDD' object 格式,**join 命中 19/19**;adj_factor=5.6561(该票有除权,复权真在起作用)。 |

## 逐项核对(用户列的 10 个审查重点)

1. **复权方向** ✅ `qfq_closes` 入参新→旧、基准 `adj_factors[0]`(最新日)、`raw×adj[i]/adj[0]`、
   无 `[-1]`(form.py:50,58)。最新日恒不变、更早日按因子缩放。破坏性验证证明方向断言真能抓反。
2. **回测收益** ✅ `run_backfill` 用 `daily.pct_chg` 累乘(backtest.py:129-132),全文零 adj_factor。
3. **verdict 落库对齐** ✅ `/analyze` 经 `_maybe_persist_verdict` 取 `store.candidate_entry_date_of(code)`
   (app.py:362),非 latest;`/coach` 端点未调该函数(app.py:373-413)——无落库副作用。
4. **限频与可观测性** ✅ `fetch.py:224-225` `logger.info("adj_factor 拉取 %d/%d 日成功...")`。
5. **回填防重** ✅ 扫描式(`pending_backfill_entries` LEFT JOIN + `UNIQUE(entry_date,code)`);
   全 app/ 无 `last_backfill_date` 内存变量。
6. **薄封装契约** ✅ `_enrich_form` 新增第 6 个【可选】参数 `adj_by_date=None`(向后兼容,
   test_screen 旧 5 参调用仍有效);`_fetch_form` 新增可选 `adj_factor_fn=None`。签名未破坏。
7. **当日 pct_chg 口径** ✅ `compute_form` 从 `closes[0]/closes[1]` 派生(form.py:84-87),
   不收 pre_close;test_screen 断言已从旧 5.26% 改为 100.0(诚实标注是 plan 要修的口径)。
8. **DDL 细节** ✅ `analysis_verdicts` 有 `id INTEGER PRIMARY KEY AUTOINCREMENT`(store.py:142)+
   `ON CONFLICT(trade_date,code) DO UPDATE`(store.py:716,非 INSERT OR IGNORE)。
9. **降级铁律** ✅ `ts_adj_factor_all/ts_adj_factor` 沿降级模式;缺因子→factor=1.0 退化不复权;
   adj 全市场失败→候选照出(test_fetch_snapshot_missing_adj_factor_degrades_to_raw);
   回填 daily 全失败→0 行不崩(test_run_backfill_daily_all_fail_returns_zero_not_crash)。
10. **契约不变** ✅ `-5.0/+15.0/D4/容差带` 只在 store.py 顶部未碰;4 现有端点响应体零改动
    (`/analyze` 仅加落库副作用、响应结构不变);client/ 目录 git log 零改动、工作区无 client 变更。

---

## 🔴 致命问题(必须修复)

**无。** 无契约漂移、无鉴权缺口、无崩溃路径、无密钥泄漏、无网络泄漏、复权方向正确、回测收益数学正确。

---

## 🟡 重要问题(应该修复)

**无达到"重要"级别的问题。** 两轮 plan-critic 抓出的 2 致命 + 4 重要点在实现里全部正确落实并有测试背书。

---

## 🔵 建议改进(可以考虑)

1. **[文档-代码不一致:`backtest.py:69` / `store.py:655` `min_trade_days=4` vs plan §4.0/§4.3 白纸黑字
   `min_trade_days=3`]** 代码用 4,plan 反复写 3("≥3 个交易日已过")。reviewer 用真实交易日历
   验算:`_next_n_trading_dates(entry,3)` 数的是 entry【之后】的后 3 个交易日(不含 entry),第 3 个
   = D4(count 闭区间含 entry=4);要拉到 D4 数据须 `count(entry,today)>=4`。**代码的 4 是对的**,
   plan 的 3 用了"entry 之后过去的交易日数"另一套口径,语义等价。但常量数字不符 + 变更日志无
   偏离说明,未来维护者可能按 plan 的 3 去"修正"代码反而引入 off-by-one(把回填提前一天、拉到
   未收盘的 D3 数据)。**建议:订正 plan §4.0/§4.3 的常量为 4(或补一句口径换算说明),并在变更
   日志补偏离记录**。test_pending_backfill_entries_excludes_too_recent 已锁 D4 才出的正确行为。

2. **[验收证据缺失:plan §4.2 Phase F2「限频冒烟」未见记录]** plan F2 硬性要求 builder"真 token 跑
   一次 refresh,实测 adj_factor 65 连拉是否撞 Tushare 每分钟限频 + 记录耗时/内存峰值(对比 39s/
   926MB 基线);若撞限频按落地策略降到当日+近20日"。变更日志【无阶段2.5 完工条目】,无法确认这个
   限频实测是否做过。F2 把 refresh 的全市场接口调用从 ~68 次翻到 ~133 次,plan-critic 明确预警这
   "很可能撞限频致复权静默失效(测试全绿看不出)"。可观测性 log 已就位(能事后从日志看 X/65),
   但**上线前应补做这次限频冒烟**(或在收口日志注明"已实测 N/65、耗时 Xs、未撞限频");当前
   fetch.py 也【无主动节流 sleep】,注释"节流复用限频降级"实际只是撞限频后退化 factor=1.0,并非
   主动限速。若真撞限频,复权会在生产静默失效(降级不崩,但复权白做)。

3. **[测试盲区:`analyze.py` 单票深判路径缺除权样例覆盖]** 含除权跳变的复权正确性验证只在 fetch.py
   路径(test_screen 的 test_fetch_snapshot_qfq_ex_dividend_corrects_pct_60d);analyze.py 单票路径的
   adj_factor 只测了恒定因子(`_ok_adj_factor_flat` 全 1.0,等价无除权),【抓不到】该路径特有的
   "按 trade_date 字符串 join adj_factor 到 daily 序列"(analyze.py:74-84)若 key 不匹配导致的静默
   不复权。reviewer 已用真 Tushare 验证 join 命中 19/19(当前格式对齐、无实际隐患),但测试仍缺这
   条覆盖。**建议:给 analyze._fetch_form 补一条含除权跳变因子的样例测试**(验 pct_60d 复权后与
   不复权不同 + join 命中),与 fetch 路径对称。

4. **[轻微偏离:`backtest.py:90-92` 回填额外拉 entry 当天 daily(4 次而非 plan 说的 3 次)]** plan §4.0
   "回测取价"只描述拉 entry 后第 1/2/3 个交易日 daily(3 次);实现为填 `entry_close`(DDL NOT NULL、
   仅供人工核对)额外拉了 entry 当天全市场 daily。有合理理由(DDL NOT NULL 约束),但比 plan 描述
   多一次全市场拉取。回填每次只处理少量待回填 entry_date,影响小。**可接受**;若在意可把 entry_close
   改从 candidates 缓存的 `price` 带出(candidates 已存 EOD close),省这次拉取。

5. **[死代码:`schemas.py:91` `OutcomeTierStat` 定义但未使用]** `OutcomesStatsOut` 的三个维度字段用的是
   `List[Dict[str, Any]]`,`OutcomeTierStat` 模型没被任何地方引用。可删以减噪,或把三维度字段类型
   收紧为 `List[OutcomeTierStat]` 让 schema 更严(但那样 tier/tag/verdict 的 label 字段名不同,需三个
   子模型)。**可忽略/清理项**。

6. **[收口未做:阶段2.5 变更日志无「完工」条目 + 全部改动未提交]** 变更日志只有立项 + plan-critic 修订
   两条,无完工记录;git 工作区阶段2.5 全部改动(+ 资金因子相对口径快修)均未 commit。按项目文件
   规范,收尾应在变更日志记一行(完工摘要 + 关键决策/偏离,尤其上文 #1 的 min_trade_days 偏离)。
   **属 cleaner/收口阶段的事,非施工缺陷**,列此提示收口时补。注:builder 自述的"改动文件清单"漏了
   `pipeline.py`/`rules.py`——经核实那两处是 [2026-07-01] 资金因子相对口径快修(net_mf_3d→
   net_mf_rate_3d),非阶段2.5 内容、也非 plan 之外的顺手优化,与阶段2.5 同处未提交工作区而已。

---

## 收口判断

**阶段2.5 达到可收口标准。** 实现与 plan §4 高度一致(完成度 ~98%),**零致命、零重要问题**;门禁
227 passed 亲验全绿(193+34,数量对得上),活 token 下网络零泄漏,复权方向经破坏性验证确认正确且
测试有效,回测收益口径数学正确不碰复权,verdict 落库/coach 不落均对齐 plan,新表 DDL 逐字合规,
钉死常量与 client/ 零触碰,`/candidates/outcomes` 端点活体冒烟通过。上列 6 条建议中:#1(min_trade_days
文档订正)+#2(限频冒烟证据)+#6(收口日志)应在收口时处理,#3(单票除权测试)+#4(entry 当天拉取)
+#5(死代码)可推后打磨。**无一阻断收口**。建议收口时:① 补做/注明 adj_factor 限频冒烟(#2);
② 订正 plan 的 min_trade_days 常量或补口径说明 + 写完工变更日志(#1/#6);③ #3/#4/#5 入 §5 Backlog
留下个选股迭代版本消化。
