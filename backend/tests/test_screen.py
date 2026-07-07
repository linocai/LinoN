"""阶段2 D1:选股数据层(rules/fetch/pipeline + candidates CRUD)单测。

铁律:不联网。fetch 用注入的假 snapshot;pipeline 喂样例 StockRow;
Tushare/网络一律不真连。验证黑名单/高位线/截断/排序/放量/新高/60日涨幅。
"""

import pytest

from app.screen import rules
from app.screen import fetch as fetch_mod
from app.screen.fetch import MarketSnapshot, StockRow, _enrich_form, fetch_market_snapshot
from app.screen import pipeline
from app.db import store
from app.data.tushare_client import TushareResult


# —— rules:黑名单(二元)————————————————————————————————————————————

@pytest.mark.parametrize("code,name,industry,expected", [
    ("600519", "贵州茅台", "白酒", True),       # 白酒行业
    ("000858", "五粮液", "白酒", True),
    ("300750", "宁德时代", "电池", True),        # 创业板 300*
    ("301051", "信濠光电", "光学光电子", True),  # 创业板 301*(旧 `300` 正则漏挡)
    ("302132", "中航成飞", "国防军工", True),    # 创业板 302*(板块整段覆盖)
    ("688981", "中芯国际", "半导体", True),      # 科创 688*
    ("689009", "九号公司", "汽车", True),        # 科创 689*(CDR,旧正则漏挡)
    ("830799", "艾融软件", "软件", True),        # 北交所 8*
    ("920363", "莱赛激光", "激光", True),        # 北交所 920* 新代码段(旧正则漏挡)
    ("430139", "华岭股份", "半导体", True),      # 4* 段
    ("600000", "*ST浦发", "银行", True),         # ST
    ("600000", "ST银行", "银行", True),          # ST
    ("600036", "招商银行", "银行", False),       # 干净
    ("603986", "兆易创新", "半导体", False),     # 干净主板
    ("600600", "青岛啤酒", "啤酒", True),        # 啤酒命中
    ("600132", "重庆啤酒", "啤酒", True),
    ("000001", "餐饮股", "酒店餐饮", False),     # 酒店餐饮 NOT 排除(只含'酒'不含白酒等)
])
def test_blacklist(code, name, industry, expected):
    assert rules.is_blacklisted(code, name, industry) is expected


def test_baijiu_industry_none_safe():
    assert rules.is_baijiu_industry(None) is False
    assert rules.is_baijiu_industry("") is False
    assert rules.is_baijiu_industry("红黄酒") is True   # 黄酒 子串命中


# —— rules:高位线(v1.3.1 A1 改:不再 exclude,只分级 warn)——————————————

def test_high_position_verdict():
    """v1.3.1 起 ≥100% 不再 'exclude',改归 'warn'(plan §4.1 A1 验收)。"""
    assert rules.high_position_verdict(200.0) == "warn"   # 门禁用例:pct_60d=200 → warn 非 exclude
    assert rules.high_position_verdict(120.0) == "warn"
    assert rules.high_position_verdict(100.0) == "warn"
    assert rules.high_position_verdict(80.0) == "warn"
    assert rules.high_position_verdict(50.0) == "warn"
    assert rules.high_position_verdict(49.9) == "ok"
    assert rules.high_position_verdict(0.0) == "ok"
    assert rules.high_position_verdict(None) == "ok"


def test_high_position_verdict_no_exclude_branch():
    """rules 模块不再产 'exclude' 判定(硬排除已删,plan §4.1)。"""
    for pct in (0.0, 49.9, 50.0, 80.0, 100.0, 120.0, 500.0):
        assert rules.high_position_verdict(pct) != "exclude"


def test_high_warn_level():
    assert rules.high_warn_level(200.0) == "high"
    assert rules.high_warn_level(100.0) == "high"
    assert rules.high_warn_level(80.0) == "amber"
    assert rules.high_warn_level(50.0) == "amber"
    assert rules.high_warn_level(49.9) is None
    assert rules.high_warn_level(None) is None


def test_high_warn_text():
    assert rules.high_warn_text(60.0) is not None
    # v1.3.1 重要#6:≥100% 不再 None(旧 exclude 轮不到产文案;现在仍会出现在候选池,
    # 必须有红级文案配套 warnLevel=high)。
    assert rules.high_warn_text(200.0) is not None
    assert "极高位" in rules.high_warn_text(200.0)
    assert rules.high_warn_text(120.0) is not None
    assert rules.high_warn_text(10.0) is None
    assert rules.high_warn_text(None) is None


# —— rules:候选条数上限(v1.3.0 C1/C4:固定 20,不再随 free_slots/满仓变化)———————

def test_candidate_limit_is_fixed_20():
    """CANDIDATE_LIMIT 单一源 = 20,不随持仓状态变化(旧 5×free_slots 截断公式已删)。"""
    assert rules.CANDIDATE_LIMIT == 20


def test_rules_has_no_stale_truncation_helpers():
    """旧满仓闭门辅助(free_slots/truncation_limit/SLOTS_PER_CANDIDATE)已删净,不留死码。"""
    assert not hasattr(rules, "free_slots")
    assert not hasattr(rules, "truncation_limit")
    assert not hasattr(rules, "SLOTS_PER_CANDIDATE")


def test_rules_max_holdings_not_redefined():
    """rules 模块不再重复定义 MAX_HOLDINGS(单一源收敛到 app.db.store.constants)。"""
    assert not hasattr(rules, "MAX_HOLDINGS")


# —— rules:排序加权(v1.3.1 A1 换新九因子集,量比权重最大)——————————————————

def _rank_score(vol_ratio, fund, turn, pos_health, *, vwap=None, breakout=None,
                mv=None, active=None, day=None):
    """v1.3.1 九参 rank_score 的测试辅助:新因子缺省给中性(不影响相对比较)。

    vwap/breakout/active 缺省 False(0 分,等值不影响相对次序);mv 缺省 0
    (<=0 → 中性 0.5,全相等不影响);day 缺省 0(无罚)。等长同序。
    """
    n = len(vol_ratio)
    return rules.rank_score(
        vol_ratios=vol_ratio, fund_3d=fund, turnovers=turn, pos_healths=pos_health,
        vwap_oks=vwap if vwap is not None else [False] * n,
        breakout_oks=breakout if breakout is not None else [False] * n,
        total_mv_yis=mv if mv is not None else [0.0] * n,
        actives=active if active is not None else [False] * n,
        day_pcts=day if day is not None else [0.0] * n,
    )


def test_rank_score_vol_ratio_is_single_largest_factor():
    # 量比是单一最大权因子(0.30):其余因子等值、仅量比不同 → 量比高者得分高。
    scores = _rank_score([5.0, 1.5], [100.0, 100.0], [10.0, 10.0], [0.9, 0.9])
    assert scores[0] > scores[1]


def test_rank_score_vol_ratio_outweighs_any_single_other():
    # 量比权(0.30)大于任意单个其他正权因子:A 仅量比满分,B 仅资金满分 → A 胜。
    scores = _rank_score(
        [5.0, 1.5],       # A 量比满分,B 最低
        [100.0, 999.0],   # B 资金满分,A 最低
        [10.0, 10.0],
        [0.9, 0.9],
    )
    assert scores[0] > scores[1]    # 0.30(vol_ratio) > 0.06(fund)


def test_rank_score_empty():
    assert rules.rank_score([], [], [], [], [], [], [], [], []) == []


def test_rank_score_all_equal_neutral():
    # 全相等输入 → 每票同分(v1.4.1 Phase C2:vol_ratio/fund 改绝对曲线后,等值输入
    # 仍产等值分——绝对曲线对等值输入天然给出相同因子分,"每票同分"结论仍成立)。
    scores = _rank_score([2.0, 2.0], [50.0, 50.0], [10.0, 10.0], [0.8, 0.8],
                         vwap=[True, True], breakout=[False, False], mv=[100.0, 100.0],
                         active=[False, False], day=[3.0, 3.0])
    assert scores[0] == scores[1]


def test_rank_score_new_factors_shift_ranking():
    # 两票量比/资金/换手/位置健康全相等,A 站 VWAP + 近期涨停,B 否 → A 分更高(信号1/5 生效)。
    scores = _rank_score([2.0, 2.0], [50.0, 50.0], [10.0, 10.0], [0.8, 0.8],
                         vwap=[True, False], active=[True, False])
    assert scores[0] > scores[1]


def test_rank_score_pos_health_not_min_maxed():
    """pos_health 直接进分不走 min-max:两票 0.99 vs 0.30,其余全等 → 0.99 得高分(plan §4.1 A1)。"""
    scores = _rank_score([2.0, 2.0], [50.0, 50.0], [10.0, 10.0], [0.99, 0.30])
    assert scores[0] > scores[1]


def test_rank_score_breakout_shifts_ranking():
    """两票其余全等,A breakout_ok=True、B False → A 分更高(信号7 生效)。"""
    scores = _rank_score([2.0, 2.0], [50.0, 50.0], [10.0, 10.0], [0.8, 0.8],
                         breakout=[True, False])
    assert scores[0] > scores[1]


def test_rank_score_day_surge_is_penalty():
    # 两票其余全等,A 今日暴涨(涨停)、B 温和 → A 被罚,分更低(信号6 负权)。
    scores = _rank_score([2.0, 2.0], [50.0, 50.0], [10.0, 10.0], [0.8, 0.8],
                         day=[9.8, 3.0])
    assert scores[0] < scores[1]


def test_weights_positive_sum_to_one():
    # 正权之和 = 1.00(day_surge 是罚项 -0.06,不计入正权和;v1.3.1 A1 九键新向量)。
    pos = sum(w for w in rules.WEIGHTS.values() if w > 0)
    assert abs(pos - 1.0) < 1e-9
    assert rules.WEIGHTS["day_surge"] < 0   # 罚项为负
    assert set(rules.WEIGHTS.keys()) == {
        "vol_ratio", "pos_health", "turnover", "vwap", "breakout",
        "mv_elastic", "active", "fund", "day_surge",
    }
    assert rules.WEIGHTS["vol_ratio"] == 0.30   # 权重最大


# —— rules:阶段3.1/v1.3.1 评分函数边界(信号3/4/6)————————————————————————

def test_turnover_health_score_boundaries():
    # v1.3.1 改带 [7,15]:5% < 下沿7% → 衰减(<1);10% 落健康带 → 满分 1.0;
    # 20% > 上沿15% → 衰减(<1)。
    assert rules.turnover_health_score(10.0) == 1.0       # 健康带满分
    assert rules.turnover_health_score(7.0) == 1.0        # 下沿含端点
    assert rules.turnover_health_score(15.0) == 1.0       # 上沿含端点
    assert 0.0 < rules.turnover_health_score(5.0) < 1.0   # 过低衰减
    assert 0.0 < rules.turnover_health_score(20.0) < 1.0  # 过高衰减
    assert rules.turnover_health_score(0.0) == 0.0        # 无成交无共识
    assert rules.turnover_health_score(-1.0) == 0.0       # 负值兜底
    assert rules.turnover_health_score(30.0) == 0.0       # 2×上沿及以上 → 0
    # 单调性:健康带外距离越远分越低
    assert rules.turnover_health_score(16.0) > rules.turnover_health_score(20.0)


def test_mv_elastic_score_boundaries():
    # v1.3.1 改带 [50,500]/floor 30:20 亿(微盘<30)→ 0;100 亿(中小盘带)→ 满分。
    # 审后修复:MV_MEGA_CEIL 500→1500(原与 mv_hi=500 重合、衰减带 span=0 退化成硬
    # 台阶,现拉开成真正的线性衰减带 [500,1500])。
    assert rules.mv_elastic_score(100.0) == 1.0           # 中小盘满分带
    assert rules.mv_elastic_score(50.0) == 1.0            # 下沿含端点
    assert rules.mv_elastic_score(500.0) == 1.0           # 上沿含端点
    assert rules.mv_elastic_score(20.0) == 0.0            # 微盘 <30 → 0
    assert rules.mv_elastic_score(1500.0) == 0.0          # 衰减终点 → 0
    assert rules.mv_elastic_score(2000.0) == 0.0          # 超过衰减终点恒 0
    # 500亿(mv_hi)=1.0,1000亿(衰减带中点)≈0.5,1500亿(mv_mega_ceil)=0,
    # >1500 恒 0(审后修复用户新增验收点)。
    assert rules.mv_elastic_score(1000.0) == pytest.approx(0.5)
    assert 0.0 < rules.mv_elastic_score(40.0) < 1.0       # 下行衰减带(30~50)
    assert 0.0 < rules.mv_elastic_score(800.0) < 1.0      # 上行衰减带(500~1500)内部
    # 缺失/未知市值 → 中性 0.5(不当微盘惩罚,plan §4.1 🔵)
    assert rules.mv_elastic_score(0.0) == 0.5


def test_mv_elastic_score_respects_cfg_mv_mega_ceil():
    """cfg 传入的 mv_mega_ceil 真实改变上行衰减终点(证穿参生效)。"""
    cfg = dict(rules.DEFAULT_SCREEN_CONFIG)
    cfg["mv_mega_ceil"] = 1000.0   # 收窄衰减带(默认 1500 → 1000)
    assert rules.mv_elastic_score(1000.0, cfg) == 0.0
    assert rules.mv_elastic_score(1500.0, cfg) == 0.0     # 已过收窄后的终点,仍 0
    assert 0.0 < rules.mv_elastic_score(750.0, cfg) < 1.0
    assert rules.mv_elastic_score(-5.0) == 0.5


def test_day_surge_penalty_monotonic():
    # 3% < 软闸阈9% → 0(不罚);9.5% 罚项 >0 且单调升;涨停线以上封顶 1.0。
    assert rules.day_surge_penalty_norm(3.0) == 0.0       # 软闸阈下不罚
    assert rules.day_surge_penalty_norm(8.99) == 0.0
    assert rules.day_surge_penalty_norm(9.0) == 0.0       # 阈值起点仍 0(=阈值不罚)
    assert 0.0 < rules.day_surge_penalty_norm(9.5) <= 1.0
    assert rules.day_surge_penalty_norm(9.8) == 1.0       # 涨停线封顶
    assert rules.day_surge_penalty_norm(12.0) == 1.0      # 更高恒 1
    # 单调不减
    assert rules.day_surge_penalty_norm(9.2) < rules.day_surge_penalty_norm(9.6)


def test_day_surge_warn_text():
    assert rules.day_surge_warn_text(3.0) is None         # 温和无 warn
    assert rules.day_surge_warn_text(8.9) is None
    assert rules.day_surge_warn_text(9.0) is not None     # 阈值起点触发
    assert "单日强弩之末" in rules.day_surge_warn_text(9.5)
    assert rules.day_surge_warn_text(None) is None


# —— v1.4.1 Phase C2:两因子绝对曲线边界(plan §4.2)——————————————————————

def test_vol_ratio_score_boundaries():
    assert rules.vol_ratio_score(0.5) == 0.0         # 缩量,无意义
    assert rules.vol_ratio_score(-1.0) == 0.0        # 负值兜底
    assert rules.vol_ratio_score(1.0) == 0.0          # 拐点起点(含端点)→ 0
    assert rules.vol_ratio_score(2.0) == pytest.approx(0.5)   # 中点线性
    assert rules.vol_ratio_score(3.0) == 1.0          # 拐点终点(含端点)→ 1
    assert rules.vol_ratio_score(5.0) == 1.0          # 超过封顶恒 1
    # 单调不减
    assert rules.vol_ratio_score(1.5) < rules.vol_ratio_score(2.5)


def test_fund_rate_score_boundaries():
    assert rules.fund_rate_score(0.0) == 0.0          # 持平不加分(含端点)
    assert rules.fund_rate_score(-5.0) == 0.0         # 净流出不加分
    assert rules.fund_rate_score(7.5) == pytest.approx(0.5)   # 中点线性
    assert rules.fund_rate_score(15.0) == 1.0         # 拐点终点(含端点)→ 1
    assert rules.fund_rate_score(30.0) == 1.0         # 超过封顶恒 1
    # 单调不减
    assert rules.fund_rate_score(3.0) < rules.fund_rate_score(10.0)


def test_vol_ratio_score_and_fund_rate_score_equal_input_equal_output():
    """等值输入产等值分(替代旧 _normalize 全 0.5 中性的等值不变式)。"""
    assert rules.vol_ratio_score(2.0) == rules.vol_ratio_score(2.0)
    assert rules.fund_rate_score(8.0) == rules.fund_rate_score(8.0)


def test_rank_score_vol_ratio_absolute_curve_monotonic_relation_holds():
    """绝对曲线下,vol_ratio 单调递增区间内的相对关系仍成立(量比越大排序分越高,
    plan §4 施工盯防:若不成立说明接线错,不是曲线设计问题)。"""
    scores = _rank_score([1.5, 2.5], [50.0, 50.0], [10.0, 10.0], [0.8, 0.8])
    assert scores[1] > scores[0]


def test_rank_score_fund_rate_absolute_curve_monotonic_relation_holds():
    """绝对曲线下,fund_rate 正区间内的相对关系仍成立(资金占比越高排序分越高)。"""
    scores = _rank_score([2.0, 2.0], [5.0, 12.0], [10.0, 10.0], [0.8, 0.8])
    assert scores[1] > scores[0]


# —— fetch:_enrich_form 内存算放量/新高/60日涨幅/均线 ————————————————

def _daily_seq(closes, vols, pre_closes=None):
    """造 daily_by_date(新→旧 dates 对齐 closes/vols)。"""
    n = len(closes)
    dates = [f"2026050{i}" if i < 10 else f"202605{i}" for i in range(n)]  # 占位日期串
    daily_by_date = {}
    pre_closes = pre_closes or [c for c in closes]
    for i, d in enumerate(dates):
        daily_by_date[d] = {"600000": {
            "close": closes[i], "vol": vols[i], "pre_close": pre_closes[i],
        }}
    return dates, daily_by_date


def test_enrich_vol_multiple_and_new_high():
    # 今日(新)收 20、量 3000;前 5 日量均 1000 → 放量 3.0x
    closes = [20.0] + [10.0] * 20   # 今日 20 远高于前 20 日 10 → 新高
    vols = [3000.0] + [1000.0] * 20
    pre = [19.0] + [10.0] * 20
    dates, dbd = _daily_seq(closes, vols, pre)
    sr = StockRow(code="600000", name="x", industry="")
    # 未传 adj_by_date(6 参默认 None)→ 无复权数据,退化为原始价(等价旧行为)
    _enrich_form(sr, "600000", dates, dbd, dates[0])
    assert sr.vol_multiple == 3.0
    assert sr.new_high_20d is True
    assert sr.above_ma20 is True
    # 60 日涨幅:closes 只有 21 个 → base 取最旧(10),(20-10)/10=100%
    assert sr.pct_60d == pytest.approx(100.0)
    # 当日涨跌幅(阶段2.5 F2 改:从复权后 closes[0]/closes[1] 派生,不再用原始 pre_close)
    # closes[0]=20, closes[1]=10 → (20-10)/10*100=100%(与 pre=19 算出的旧 5.26% 不同,
    # 这正是 plan 铁律要修的口径——除权后 pre_close 字段不可信,改用复权后价序列派生)。
    assert sr.pct_chg == pytest.approx(100.0)


def test_enrich_no_data_safe():
    sr = StockRow(code="600000", name="x", industry="")
    _enrich_form(sr, "600000", [], {}, "20260506")
    assert sr.vol_multiple == 0.0 and sr.new_high_20d is False and sr.pct_60d is None


def test_enrich_old_daily_without_amount_key_no_crash():
    """旧 daily record 无 amount 键(_daily_seq)→ _enrich_form 退化 vwap_ok False,不崩(向后兼容)。"""
    closes = [20.0] + [10.0] * 20
    vols = [3000.0] + [1000.0] * 20
    dates, dbd = _daily_seq(closes, vols)   # 无 amount 键
    sr = StockRow(code="600000", name="x", industry="")
    _enrich_form(sr, "600000", dates, dbd, dates[0])   # 5 参旧签名,无 adj/amount
    assert sr.vwap_ok is False              # 缺 amount → 保守 False
    assert sr.vol_multiple == 3.0           # 其余字段照常


def test_enrich_writes_vwap_ok_and_had_limit_up():
    """daily record 带 amount + 历史涨停 → _enrich_form 写回 vwap_ok/had_limit_up(信号1/5)。"""
    # 今日 close=105,amount=1000 千元,vol=100 手 → vwap=100 → close>vwap → vwap_ok True
    # 昨日相对前日涨停 ~9.9%(pct[1])→ had_limit_up True
    n = 12
    closes = [105.0, 109.9, 100.0] + [100.0] * (n - 3)
    vols = [100.0] * n
    amounts = [1000.0] * n
    dates = [f"2026{'%04d' % (600 + i)}"[:8] for i in range(n)]  # 占位新→旧
    daily_by_date = {}
    for i, d in enumerate(dates):
        daily_by_date[d] = {"600000": {
            "close": closes[i], "vol": vols[i], "pre_close": closes[i], "amount": amounts[i],
        }}
    sr = StockRow(code="600000", name="x", industry="")
    _enrich_form(sr, "600000", dates, daily_by_date, dates[0])
    assert sr.vwap_ok is True
    assert sr.had_limit_up is True


# —— fetch_market_snapshot:东财 moneyflow_dc 字段映射/单位/近3日合计/降级 ——————
# 资金源切到东财 moneyflow_dc 后,fetch 读 net_amount(万元)填 net_mf_amount/net_mf_3d。
# 用造的样例 DataFrame 驱动(不联网),验证字段映射 + 近 3 日合计 + 无权限降级。

def _df(records):
    import pandas as pd
    return pd.DataFrame(records)


def _patch_fetch(monkeypatch, *, basic, dc_by_date, daily_by_date, stock_basic=None,
                  adj_by_date=None):
    """注入假 Tushare 接口(全市场 daily_basic / 东财 moneyflow_dc / daily / adj_factor / stock_basic)。

    dc_by_date / daily_by_date / adj_by_date: {'YYYYMMDD': [records]};缺日 → ok=False 降级。
    stock_basic: 行业映射记录列表(None → 不提供,行业退化为空)。
    adj_by_date 缺省(None)→ 全部降级(ok=False),等价旧行为(不复权)。
    """
    fetch_mod.reset_industry_cache()
    adj_by_date = adj_by_date or {}

    def _basic_all(td):
        return TushareResult.success(_df(basic)) if basic is not None \
            else TushareResult.fail("daily_basic 失败")

    def _dc_all(td):
        recs = dc_by_date.get(td)
        return TushareResult.success(_df(recs)) if recs is not None \
            else TushareResult.fail("moneyflow_dc 无权限")

    def _daily_all(td):
        recs = daily_by_date.get(td)
        return TushareResult.success(_df(recs)) if recs is not None \
            else TushareResult.fail("daily 失败")

    def _adj_all(td):
        recs = adj_by_date.get(td)
        return TushareResult.success(_df(recs)) if recs is not None \
            else TushareResult.fail("adj_factor 无数据")

    def _stock_basic():
        return TushareResult.success(_df(stock_basic)) if stock_basic is not None \
            else TushareResult.fail("stock_basic 失败")

    monkeypatch.setattr(fetch_mod.tc, "ts_daily_basic_all", _basic_all)
    monkeypatch.setattr(fetch_mod.tc, "ts_moneyflow_dc_all", _dc_all)
    monkeypatch.setattr(fetch_mod.tc, "ts_daily_all", _daily_all)
    monkeypatch.setattr(fetch_mod.tc, "ts_adj_factor_all", _adj_all)
    monkeypatch.setattr(fetch_mod.tc, "ts_stock_basic", _stock_basic)


def test_fetch_snapshot_maps_moneyflow_dc_net_amount(monkeypatch):
    """东财 moneyflow_dc.net_amount(万元)→ net_mf_amount;近 3 日合计 → net_mf_3d。"""
    td = "20260626"
    # 茅台 net_amount 当日 +12000 万、前两日 +5000/+3000 → 近 3 日 20000 万(=2 亿)
    dc = {
        "20260626": [{"ts_code": "600519.SH", "net_amount": 12000.0}],
        "20260625": [{"ts_code": "600519.SH", "net_amount": 5000.0}],
        "20260624": [{"ts_code": "600519.SH", "net_amount": 3000.0}],
    }
    basic = [{"ts_code": "600519.SH", "close": 1600.0,
              "turnover_rate": 1.2, "total_mv": 2_000_000.0}]
    # daily 只给当日一行(形态指标会保守退化,不影响资金字段验证)
    daily = {"20260626": [{"ts_code": "600519.SH", "close": 1600.0,
                           "vol": 30000.0, "pre_close": 1580.0}]}
    _patch_fetch(monkeypatch, basic=basic, dc_by_date=dc, daily_by_date=daily)

    snap = fetch_market_snapshot(td)
    assert snap.ok is True
    row = next(r for r in snap.rows if r.code == "600519")
    assert row.net_mf_amount == 12000.0           # 当日东财主力净额(万元)
    assert row.net_mf_3d == pytest.approx(20000.0)  # 近 3 日合计(万元)= 2 亿


# —— fetch_market_snapshot:volume_ratio(官方量比)读取 + NaN 安全守卫(v1.3.1 A2 重要#4)——

def test_fetch_snapshot_reads_volume_ratio():
    """daily_basic.volume_ratio 正常读取,写入 StockRow.volume_ratio。"""
    from app.screen.fetch import _safe_float
    assert _safe_float(2.5) == 2.5
    assert _safe_float(None) == 0.0
    assert _safe_float(None, 1.0) == 1.0


def test_safe_float_guards_nan():
    """pd.isna 的 NaN 值 → 安全返回 default(重要#4:`x or 0.0` 拦不住 NaN,这里必须真守住)。"""
    import math
    from app.screen.fetch import _safe_float
    nan = float("nan")
    assert math.isnan(nan)                 # 前提:nan 确实是 float nan
    assert _safe_float(nan, 0.0) == 0.0     # 必须守住,不能透出 nan
    assert _safe_float(nan) != nan          # 绝不能是 nan(nan != nan 恒 True,只为强调语义)
    import pandas as pd
    assert _safe_float(pd.NA, 0.0) == 0.0   # pandas 专属 NA 同样守住


def test_fetch_snapshot_volume_ratio_nan_defaults_zero_and_gets_coarse_filtered(monkeypatch):
    """volume_ratio=NaN(模拟 Tushare 缺值)→ 读入 0.0,该票粗筛按 <VOL_RATIO_MIN 淘汰
    (不会放行进 rank_score 毒化 min-max;重要#4 门禁用例)。
    """
    import math
    td = "20260626"
    basic = [{"ts_code": "600000.SH", "close": 10.0, "turnover_rate": 3.0,
              "total_mv": 500_000.0, "volume_ratio": math.nan}]
    daily = {"20260626": [{"ts_code": "600000.SH", "close": 10.0,
                           "vol": 1000.0, "pre_close": 9.8}]}
    _patch_fetch(monkeypatch, basic=basic, dc_by_date={}, daily_by_date=daily)

    snap = fetch_market_snapshot(td)
    assert snap.ok is True
    row = next(r for r in snap.rows if r.code == "600000")
    assert row.volume_ratio == 0.0   # NaN 安全兜底为 0(非 nan),粗筛按 0<VOL_RATIO_MIN 会淘汰


def test_fetch_snapshot_volume_ratio_present_maps_correctly(monkeypatch):
    """volume_ratio 正常有值 → 如实写入 StockRow.volume_ratio。"""
    td = "20260626"
    basic = [{"ts_code": "600000.SH", "close": 10.0, "turnover_rate": 3.0,
              "total_mv": 500_000.0, "volume_ratio": 2.3}]
    daily = {"20260626": [{"ts_code": "600000.SH", "close": 10.0,
                           "vol": 1000.0, "pre_close": 9.8}]}
    _patch_fetch(monkeypatch, basic=basic, dc_by_date={}, daily_by_date=daily)

    snap = fetch_market_snapshot(td)
    row = next(r for r in snap.rows if r.code == "600000")
    assert row.volume_ratio == pytest.approx(2.3)


def test_fetch_snapshot_moneyflow_dc_no_permission_degrades(monkeypatch):
    """moneyflow_dc 无权限(2000 积分)→ 资金面退化为 0,daily_basic 在则快照仍 ok 不崩。"""
    td = "20260626"
    basic = [{"ts_code": "600000.SH", "close": 10.0,
              "turnover_rate": 3.0, "total_mv": 500_000.0}]
    daily = {"20260626": [{"ts_code": "600000.SH", "close": 10.0,
                           "vol": 1000.0, "pre_close": 9.8}]}
    # dc_by_date 全缺 → ts_moneyflow_dc_all 一律 fail(模拟无权限)
    _patch_fetch(monkeypatch, basic=basic, dc_by_date={}, daily_by_date=daily)

    snap = fetch_market_snapshot(td)
    assert snap.ok is True   # 核心 daily_basic 在 → 快照不 degraded
    row = next(r for r in snap.rows if r.code == "600000")
    assert row.net_mf_amount == 0.0 and row.net_mf_3d == 0.0   # 资金面退化为 0


def test_fetch_snapshot_daily_basic_fail_degrades(monkeypatch):
    """核心 daily_basic 失败 → MarketSnapshot.fail(pipeline 据此 degraded 空列表)。"""
    _patch_fetch(monkeypatch, basic=None, dc_by_date={}, daily_by_date={})
    snap = fetch_market_snapshot("20260626")
    assert snap.ok is False and snap.rows == []


# —— fetch_market_snapshot:复权(阶段2.5 F2)——除权样例验 pct_60d/new_high 正确 ————

def test_fetch_snapshot_qfq_ex_dividend_corrects_pct_60d(monkeypatch):
    """窗口内除权跳变(adj_factor 中途减半)→ 复权后 pct_60d/new_high 与不复权不同且正确。

    构造:某票原始 close 恒为 10(除权前后价格连续无变化——典型除权特征,除权日
    原始 close 会有断层但这里简化用"因子跳变、原始价不变"来隔离验证复权逻辑本身),
    adj_factor 在窗口中段(20260610 之前)从 2.0(除权前)变为 1.0(除权后,最新)。
    复权后:除权前的原始价应被【放大】(乘以 2.0/1.0),不复权则看不出这个差异。
    """
    td = "20260626"
    dates = fetch_mod._recent_trade_dates(td, 5)   # 新→旧 5 天:26,25,24,23,22(近似,含跳周末)
    # 最新 3 天 factor=1.0(除权后),更早 2 天 factor=2.0(除权前)
    daily_by_date = {}
    adj_by_date = {}
    for i, d in enumerate(dates):
        close = 10.0
        daily_by_date[d] = [{"ts_code": "600000.SH", "close": close,
                              "vol": 1000.0, "pre_close": close}]
        factor = 1.0 if i < 3 else 2.0
        adj_by_date[d] = [{"ts_code": "600000.SH", "adj_factor": factor}]

    basic = [{"ts_code": "600000.SH", "close": 10.0,
              "turnover_rate": 3.0, "total_mv": 500_000.0}]
    _patch_fetch(monkeypatch, basic=basic, dc_by_date={}, daily_by_date=daily_by_date,
                 adj_by_date=adj_by_date)

    snap = fetch_market_snapshot(td)
    assert snap.ok is True
    row = next(r for r in snap.rows if r.code == "600000")
    # 不复权时 pct_60d 应为 0(原始价恒 10,无变化);复权后更早日被放大 2x(=20),
    # 故 today(10) vs base(qfq 后的最早日 close=20)→ (10-20)/20*100 = -50%,
    # 与"不复权 0%"不同且方向正确(复权后能看出相对更早时点其实是缩水,因为那时
    # 除权前的可比价其实更高)。
    assert row.pct_60d == pytest.approx(-50.0)


def test_fetch_snapshot_missing_adj_factor_degrades_to_raw(monkeypatch):
    """adj_factor 全市场拉取失败(整日缺)→ 该日退化 factor=None,不崩,近似不复权。"""
    td = "20260626"
    basic = [{"ts_code": "600000.SH", "close": 10.0,
              "turnover_rate": 3.0, "total_mv": 500_000.0}]
    daily = {"20260626": [{"ts_code": "600000.SH", "close": 10.0,
                           "vol": 1000.0, "pre_close": 9.8}]}
    # adj_by_date 缺省 → 全部降级(_adj_all 一律 fail)
    _patch_fetch(monkeypatch, basic=basic, dc_by_date={}, daily_by_date=daily)
    snap = fetch_market_snapshot(td)
    assert snap.ok is True   # 不崩


def test_fetch_snapshot_pct_chg_no_false_jump_on_ex_dividend_day(monkeypatch):
    """当日 pct_chg 从复权后 closes[0]/closes[1] 派生,除权日不出假突变。

    构造:原始 close 今日=5.0(除权后价,除以2),昨日=10.0(除权前价);若用原始
    pre_close(=10.0 假设未调整)算会得到 -50% 假暴跌。复权后:今日 factor=1.0,
    昨日 factor=2.0(除权发生在两天之间)→ qfq(昨日)=10.0×2.0/1.0=20.0,
    今日(5.0)vs 复权后昨日(20.0)... 这里改用更直观场景验证不假突变:
    今日 close=5.0(factor=1.0,基准),昨日 close=10.0 但除权因子相同(factor=1.0,
    表示两天间无除权)→ 复权后昨日仍 10.0,pct_chg=(5-10)/10*100=-50%(真实下跌,
    非除权误判)。
    """
    td = "20260626"
    dates = fetch_mod._recent_trade_dates(td, 3)
    daily_by_date = {
        dates[0]: [{"ts_code": "600000.SH", "close": 5.0, "vol": 1000.0, "pre_close": 10.0}],
        dates[1]: [{"ts_code": "600000.SH", "close": 10.0, "vol": 1000.0, "pre_close": 10.0}],
        dates[2]: [{"ts_code": "600000.SH", "close": 10.0, "vol": 1000.0, "pre_close": 10.0}],
    }
    adj_by_date = {d: [{"ts_code": "600000.SH", "adj_factor": 1.0}] for d in dates}
    basic = [{"ts_code": "600000.SH", "close": 5.0, "turnover_rate": 3.0, "total_mv": 500_000.0}]
    _patch_fetch(monkeypatch, basic=basic, dc_by_date={}, daily_by_date=daily_by_date,
                 adj_by_date=adj_by_date)
    snap = fetch_market_snapshot(td)
    row = next(r for r in snap.rows if r.code == "600000")
    assert row.pct_chg == pytest.approx(-50.0)   # 真实下跌,非除权假突变


# —— pipeline:黑名单/高位/粗筛/排序/截断(喂样例,免联网)——————————————

def _sr(code, name, industry, vol_mult=2.0, mf3=100.0, mf_today=10.0,
        new_high=True, above_ma=True, pct60=10.0, close=10.0, turnover=5.0, pct_chg=3.0,
        vol_ratio=None, pos_health=0.8, breakout=False):
    """测试用 StockRow 工厂。v1.3.1 A2:粗筛/排序改用 volume_ratio(官方量比),
    vol_ratio 缺省时镜像 vol_mult(沿用旧调用点"vol_mult 控制放量强弱"的测试意图,
    免逐个调用点改写);vol_multiple 仍保留(展示口径解耦,建议#10)。
    pos_health 缺省 0.8(中性偏高,不为 0 免打偏排序);breakout 缺省 False。
    """
    return StockRow(
        code=code, name=name, industry=industry, close=close, pct_chg=pct_chg,
        turnover=turnover, net_mf_amount=mf_today, net_mf_3d=mf3,
        vol_multiple=vol_mult,
        volume_ratio=vol_ratio if vol_ratio is not None else vol_mult,
        pct_60d=pct60, new_high_20d=new_high, above_ma20=above_ma,
        pos_health=pos_health, breakout_ok=breakout,
    )


def test_pipeline_blacklist_kept_high_position_no_longer_excluded():
    """黑名单仍硬排除;v1.3.1 起高位线 ≥100% 不再排除,只标 warnLevel=high(plan §4.1)。"""
    rows = [
        _sr("600000", "干净A", "银行"),                       # 合格
        _sr("300001", "创业板", "电池"),                      # 黑名单代码,仍排除
        _sr("600519", "贵州茅台", "白酒"),                    # 白酒黑名单,仍排除
        _sr("600002", "高位B", "钢铁", pct60=150.0),          # 高位 ≥100:v1.3.1 不再排除
        _sr("600003", "warnC", "有色", pct60=70.0),           # ≥50 warn 不排除
    ]
    snap = MarketSnapshot(trade_date="2026-05-06", rows=rows)
    out = pipeline.build_candidates(snap)
    codes = [c["code"] for c in out]
    assert "600000" in codes and "600003" in codes
    assert "300001" not in codes and "600519" not in codes   # 黑名单仍排除
    assert "600002" in codes   # 高位不再排除(关键回归断言)

    # warn 降级:600003(70%)warn 非空,warnLevel=amber
    warnc = next(c for c in out if c["code"] == "600003")
    assert warnc.get("warn")
    assert warnc.get("warnLevel") == "amber"

    # 600002(150%)warn 非空且 warnLevel=high(红级,重要#6)
    high = next(c for c in out if c["code"] == "600002")
    assert high.get("warn")
    assert "极高位" in high["warn"]
    assert high.get("warnLevel") == "high"

    # 干净 A 无 warn、无 warnLevel(省略键)
    cleana = next(c for c in out if c["code"] == "600000")
    assert cleana.get("warn") is None
    assert "warnLevel" not in cleana


def test_pipeline_coarse_filters():
    rows = [
        _sr("600000", "合格", "银行", vol_mult=2.0, mf3=100.0, new_high=True),
        _sr("600001", "量不够", "银行", vol_mult=1.2),               # < 1.5 淘汰
        _sr("600002", "资金流出", "银行", mf3=-50.0),                # 近3日<=0 淘汰
        _sr("600003", "形态差", "银行", new_high=False, above_ma=False),  # 形态俱否 淘汰
        _sr("600004", "大幅出货", "银行", mf_today=-99999.0),        # 当日大幅净流出 淘汰
    ]
    snap = MarketSnapshot(trade_date="2026-05-06", rows=rows)
    out = pipeline.build_candidates(snap)
    assert [c["code"] for c in out] == ["600000"]


def test_pipeline_ranking_and_rank_field():
    # 放量越强排越前(放量权最大)
    rows = [
        _sr("600001", "弱量", "银行", vol_mult=1.6),
        _sr("600002", "强量", "银行", vol_mult=5.0),
        _sr("600003", "中量", "银行", vol_mult=3.0),
    ]
    snap = MarketSnapshot(trade_date="2026-05-06", rows=rows)
    out = pipeline.build_candidates(snap)
    assert [c["code"] for c in out] == ["600002", "600003", "600001"]
    assert [c["rank"] for c in out] == [1, 2, 3]


def test_pipeline_candidate_shape():
    rows = [_sr("600000", "兆易创新", "半导体", vol_mult=2.8, mf3=12000.0, turnover=4.6)]
    snap = MarketSnapshot(trade_date="2026-05-06", rows=rows)
    out = pipeline.build_candidates(snap)
    c = out[0]
    # 逐字段对齐 Candidate(Models.swift)+ 阶段3.1 新增 score
    for k in ("rank", "name", "code", "sector", "tag", "price", "chg",
              "volMultiple", "volPct", "turnover", "flow", "score"):
        assert k in c
    assert c["volMultiple"] == "2.8x"
    assert isinstance(c["volPct"], int) and 0 <= c["volPct"] <= 100
    assert c["flow"] == "+1.20亿"   # 12000 万 → 1.20 亿
    # v1.4.1 Phase C1 绝对口径:单票不再强制中性满分 100,score 按其自身原始加权分算,
    # 落 [0,100] 区间即可(不再依赖池内 min-max)。
    assert isinstance(c["score"], int) and 0 <= c["score"] <= 100


# —— 阶段3.1 pipeline:新因子改排序 + warn 合并 + score 打分展示 ——————————————

def test_pipeline_new_factor_shifts_ranking():
    """两票放量相同,A 站 VWAP+近期涨停,B 否 → A 排在前(信号1/5 生效,plan Phase C 验收1)。"""
    a = _sr("600000", "站VWAP有涨停A", "银行", vol_mult=3.0)
    a.vwap_ok = True
    a.had_limit_up = True
    b = _sr("600001", "普通B", "银行", vol_mult=3.0)
    b.vwap_ok = False
    b.had_limit_up = False
    snap = MarketSnapshot(trade_date="2026-05-06", rows=[b, a])   # 故意 B 在前
    out = pipeline.build_candidates(snap)
    assert [c["code"] for c in out] == ["600000", "600001"]   # A 靠新因子排到前


def test_pipeline_day_surge_warn():
    """单日暴涨票(今日 pct_chg≥9%)候选 warn 非空且含单日软闸文案(plan Phase C 验收2)。"""
    rows = [_sr("600000", "单日暴涨", "银行", pct_chg=9.8, pct60=10.0)]  # 今日 9.8%,60日不高
    snap = MarketSnapshot(trade_date="2026-05-06", rows=rows)
    out = pipeline.build_candidates(snap)
    assert out[0].get("warn") and "单日强弩之末" in out[0]["warn"]


def test_pipeline_warn_merges_high_and_surge():
    """今日暴涨 + 60 日高位(50-100%)→ 两条 warn 合并展示(仍单一字符串)。"""
    rows = [_sr("600000", "双雷", "银行", pct_chg=9.5, pct60=70.0)]
    snap = MarketSnapshot(trade_date="2026-05-06", rows=rows)
    out = pipeline.build_candidates(snap)
    w = out[0].get("warn")
    assert w and "60日累涨" in w and "单日强弩之末" in w   # 两条合并
    assert isinstance(w, str)   # 仍单一 Optional[str]


def test_pipeline_score_range_and_same_order_as_rank():
    """v1.4.1 Phase C1 绝对口径:score ∈ [0,100] 整数,不改 rank 次序(与 rank 同序降序)。

    末位不再恒为旧 SCORE_FLOOR——绝对口径下按各自原始加权分独立算,允许任意低值
    (甚至 0),这正是"弱势票诚实显低分"的设计目标(plan §4.2)。
    """
    rows = [
        _sr("600001", "弱", "银行", vol_mult=1.6),
        _sr("600002", "强", "银行", vol_mult=5.0),
        _sr("600003", "中", "银行", vol_mult=3.0),
    ]
    snap = MarketSnapshot(trade_date="2026-05-06", rows=rows)
    out = pipeline.build_candidates(snap)
    scores = [c["score"] for c in out]
    ranks = [c["rank"] for c in out]
    # rank 严格升序(排序不变)
    assert ranks == [1, 2, 3]
    # score 整数、值域 [0,100]、与 rank 同序(降序)
    for s in scores:
        assert isinstance(s, int) and 0 <= s <= 100
    assert scores == sorted(scores, reverse=True)   # 与 rank 同序


def test_pipeline_two_stock_pool_score_matches_absolute_formula():
    """两票池展示分逐票独立按 clamp(raw*100,0,100) 算(v1.4.1 Phase C1,plan §4.2)——
    用 rank_score 反推期望值锁定,证明展示分不再依赖池内 min-max(而是 raw*100 clamp)。
    两票 vol_ratio(2.001/2.000)在 Phase C2 绝对曲线下几乎同分,展示分差应极小。"""
    rows = [
        _sr("600001", "略强", "银行", vol_mult=2.001),
        _sr("600002", "略弱", "银行", vol_mult=2.000),
    ]
    snap = MarketSnapshot(trade_date="2026-05-06", rows=rows)
    out = pipeline.build_candidates(snap)

    # 用同样入参重放 rank_score 算原始分,验证展示分 = clamp(raw*100, 0, 100)(逐票独立)。
    raws = rules.rank_score(
        vol_ratios=[2.001, 2.000], fund_3d=[0.0, 0.0], turnovers=[5.0, 5.0],
        pos_healths=[0.8, 0.8], vwap_oks=[False, False], breakout_oks=[False, False],
        total_mv_yis=[0.0, 0.0], actives=[False, False], day_pcts=[3.0, 3.0],
    )
    expected = sorted(
        [int(round(max(0.0, min(100.0, r * 100)))) for r in raws], reverse=True
    )
    scores = sorted([c["score"] for c in out], reverse=True)
    assert scores == expected
    # 两票几乎全同因子(vol_ratio 绝对曲线下 2.001/2.000 几乎同分)→ 分差应极小
    # (不再被强行拉开到 100 vs 旧 SCORE_FLOOR)。
    assert abs(scores[0] - scores[1]) <= 1


def test_pipeline_single_and_all_equal_score_equal_not_necessarily_100():
    """v1.4.1 Phase C1 绝对口径:单票 / 全相等 survivors 不再强制中性满分 100——
    绝对曲线对等值输入产等值分(仍相等,原"全相等→同分"结论成立),但具体值由各自
    原始加权分决定,不由池内 min-max 兜底为 100(plan §4.2)。
    """
    # 单票:落 [0,100] 区间,不断言恒为 100
    single = pipeline.build_candidates(
        MarketSnapshot(trade_date="2026-05-06", rows=[_sr("600000", "唯一", "银行")]))
    assert isinstance(single[0]["score"], int) and 0 <= single[0]["score"] <= 100
    # 两票全因子相等 → 等值输入产等值分(仍相等,但不再断言为 100)
    rows = [_sr("600001", "A", "银行"), _sr("600002", "B", "银行")]  # 完全相同参数
    out = pipeline.build_candidates(MarketSnapshot(trade_date="2026-05-06", rows=rows))
    scores = [c["score"] for c in out]
    assert scores[0] == scores[1]


def test_run_pipeline_degraded_on_failed_snapshot():
    def _fail(td):
        return MarketSnapshot.fail("2026-05-06", "token 缺失")
    rows, degraded, reason, td = pipeline.run_pipeline("20260506", snapshot_fn=_fail)
    assert rows == [] and degraded is True and "token" in reason


# —— v1.4.1 Phase C1:_normalize_scores 绝对口径单测(plan §4 Phase C 验收2)————————

def test_normalize_scores_negative_raw_clamped_to_zero():
    assert pipeline._normalize_scores([-0.5]) == [0]


def test_normalize_scores_over_one_raw_clamped_to_100():
    assert pipeline._normalize_scores([1.5]) == [100]


def test_normalize_scores_normal_values():
    assert pipeline._normalize_scores([0.4]) == [40]
    assert pipeline._normalize_scores([0.8586]) == [86]


def test_normalize_scores_empty():
    assert pipeline._normalize_scores([]) == []


def test_normalize_scores_multiple_independent_of_pool():
    """逐票独立 clamp,不依赖池内其余值(与旧 min-max 的关键区别)。"""
    assert pipeline._normalize_scores([0.1, 0.9]) == [10, 90]


# —— v1.4.1 Phase C1:展示分跨天可比性(plan §4 Phase C 验收4)——————————————————

def test_display_score_comparable_across_different_pools():
    """两批不同池、含相同原始分的票 → 展示分相同(证明脱离池内相对,跨天可比)。"""
    pool_a = [
        _sr("600001", "A强", "银行", vol_mult=5.0),
        _sr("600002", "A中", "银行", vol_mult=2.0),
    ]
    pool_b = [
        _sr("600003", "B强", "银行", vol_mult=5.0),   # 与 pool_a 首票原始分理论相同
        _sr("600004", "B弱", "银行", vol_mult=1.6),
        _sr("600005", "B更弱", "银行", vol_mult=1.55),
    ]
    out_a = pipeline.build_candidates(MarketSnapshot(trade_date="2026-05-06", rows=pool_a))
    out_b = pipeline.build_candidates(MarketSnapshot(trade_date="2026-05-06", rows=pool_b))
    score_a_strong = next(c for c in out_a if c["code"] == "600001")["score"]
    score_b_strong = next(c for c in out_b if c["code"] == "600003")["score"]
    # 两票除池组成不同外因子完全一致 → 展示分应相同(跨池/跨"天"可比)
    assert score_a_strong == score_b_strong


# —— v1.4.1 Phase C:回测不受影响(plan §4.2 查证结论,锁定断言)——————————————————

def test_backtest_does_not_consume_score_field():
    """backtest.py 分位统计只吃 rank/tag/verdict,不读 score——score 改绝对口径
    不影响回测链路(plan §4.2 查证结论锁定)。"""
    import inspect

    from app.screen import backtest

    src = inspect.getsource(backtest)
    assert '["score"]' not in src and ".get(\"score\"" not in src


def test_run_pipeline_no_candidates():
    def _empty(td):
        return MarketSnapshot(trade_date="2026-05-06", rows=[])
    rows, degraded, reason, td = pipeline.run_pipeline("20260506", snapshot_fn=_empty)
    assert rows == [] and degraded is False and reason == "no_candidates"


def test_run_pipeline_exception_safe():
    def _boom(td):
        raise RuntimeError("network down")
    rows, degraded, reason, td = pipeline.run_pipeline("20260506", snapshot_fn=_boom)
    assert rows == [] and degraded is True and "异常" in reason


# —— store:candidates CRUD ————————————————————————————————————————

@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "cand.db")
    store.init_db(p)
    return p


def _cand(rank, code, warn=None, score=100):
    return {
        "rank": rank, "name": f"票{code}", "code": code, "sector": "半导体",
        "tag": "放量突破", "price": 10.0 + rank, "chg": "+3.00%",
        "volMultiple": "2.8x", "volPct": 90, "flow": "+1.20亿",
        "turnover": "4.6%", "warn": warn, "score": score,
    }


def test_upsert_and_list_candidates(db):
    rows = [_cand(1, "600000", score=100), _cand(2, "600001", warn="60日累涨 70%", score=42)]
    n = store.upsert_candidates("2026-05-06", rows, db_path=db)
    assert n == 2
    got = store.list_candidates("2026-05-06", db_path=db)
    assert [c["code"] for c in got] == ["600000", "600001"]
    assert got[0]["volMultiple"] == "2.8x" and got[0]["volPct"] == 90
    assert "warn" not in got[0]          # warn=None → 省略键
    assert got[1]["warn"] == "60日累涨 70%"
    # 阶段3.1:score round-trip 带回读
    assert got[0]["score"] == 100 and got[1]["score"] == 42


def test_upsert_replaces_same_date(db):
    store.upsert_candidates("2026-05-06", [_cand(1, "600000")], db_path=db)
    store.upsert_candidates("2026-05-06", [_cand(1, "600999")], db_path=db)
    got = store.list_candidates("2026-05-06", db_path=db)
    assert [c["code"] for c in got] == ["600999"]   # 整体替换


def test_latest_candidate_date(db):
    assert store.latest_candidate_date(db_path=db) is None
    store.upsert_candidates("2026-05-05", [_cand(1, "600000")], db_path=db)
    store.upsert_candidates("2026-05-06", [_cand(1, "600001")], db_path=db)
    assert store.latest_candidate_date(db_path=db) == "2026-05-06"


def test_upsert_empty_clears(db):
    store.upsert_candidates("2026-05-06", [_cand(1, "600000")], db_path=db)
    n = store.upsert_candidates("2026-05-06", [], db_path=db)
    assert n == 0
    assert store.list_candidates("2026-05-06", db_path=db) == []
