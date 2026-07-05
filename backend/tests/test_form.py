"""阶段2.5 F1:复权(qfq_closes)+ 共享形态计算(compute_form)单测。

铁律(plan §4.0 复权序列方向契约,致命1修订):qfq_closes 入参新→旧、基准 = adj_factors[0]
(最新日)。本文件的方向断言是**唯一能测出方向反了**的测试——若实现误用 adj_factors[-1]
当基准(那是后复权),断言会失败。
"""

import pytest

from app.screen.form import FormResult, compute_form, qfq_closes


# —— qfq_closes:方向契约(致命1,必须能区分前/后复权)——————————————————————

def test_qfq_direction_latest_unchanged_older_scaled():
    """最新日(i=0)factor=1.0、更早日 factor=0.5 → 最新日 close 不变,更早日放大 2x。

    若实现误用 [-1](最早日)当基准,该断言必然失败(能抓出方向反)。
    """
    raw_closes = [100.0, 90.0, 80.0]       # 新→旧
    adj_factors = [1.0, 0.5, 0.5]          # 新→旧;最新日基准=1.0
    out = qfq_closes(raw_closes, adj_factors)
    assert out[0] == pytest.approx(100.0)   # 最新日不变
    assert out[1] == pytest.approx(90.0 * 0.5 / 1.0)   # 45.0
    assert out[2] == pytest.approx(80.0 * 0.5 / 1.0)   # 40.0


def test_qfq_direction_older_day_scaled_up_when_factor_larger():
    """更严格的方向断言:更早日 factor 相对基准更大 → 更早日价格被【放大】。

    构造:最新日 factor=1.0(基准),更早日 factor=2.0(表示该日发生过除权,原始价
    需要放大才能与最新日价格连续可比)。qfq_close[更早] = raw × 2.0 / 1.0 = raw×2。
    """
    raw_closes = [50.0, 40.0]     # 新→旧
    adj_factors = [1.0, 2.0]      # 新→旧;更早日 factor 是基准的 2 倍
    out = qfq_closes(raw_closes, adj_factors)
    assert out[0] == pytest.approx(50.0)          # 最新日不变
    assert out[1] == pytest.approx(80.0)           # 40 × 2.0 / 1.0 = 80(放大 2x)


# —— qfq_closes:无除权 / 缺因子退化 ——————————————————————————————————

def test_qfq_no_adjustment_when_factors_constant():
    """adj 恒定(无除权)→ 复权后序列 = 原序列(等比缩放,因子相同则不变)。"""
    raw_closes = [10.0, 10.5, 9.8, 10.2]
    adj_factors = [1.3, 1.3, 1.3, 1.3]
    out = qfq_closes(raw_closes, adj_factors)
    for a, b in zip(out, raw_closes):
        assert a == pytest.approx(b)


def test_qfq_missing_base_factor_degrades_to_raw():
    """基准(adj_factors[0])缺失(None/0)→ 整体退化为原始价,不崩。"""
    raw_closes = [10.0, 11.0, 12.0]
    assert qfq_closes(raw_closes, [None, 1.0, 1.0]) == raw_closes
    assert qfq_closes(raw_closes, [0, 1.0, 1.0]) == raw_closes
    assert qfq_closes(raw_closes, []) == raw_closes


def test_qfq_missing_single_day_factor_degrades_that_day():
    """某一日缺因子(None/0)→ 该日退化为不缩放(用基准值本身,等同该日 factor=base)。"""
    raw_closes = [100.0, 90.0, 80.0]
    adj_factors = [2.0, None, 2.0]   # 中间日缺
    out = qfq_closes(raw_closes, adj_factors)
    assert out[0] == pytest.approx(100.0)
    assert out[1] == pytest.approx(90.0)   # 缺因子退化:90 × 2.0/2.0 = 90(不缩放)
    assert out[2] == pytest.approx(80.0)   # 2.0/2.0=1 不缩放


def test_qfq_empty_input():
    assert qfq_closes([], []) == []


# —— compute_form:回归现有 _enrich_form/_fetch_form 口径(无除权序列)——————————

def test_compute_form_matches_existing_enrich_semantics():
    """无除权样例(照 test_screen.py test_enrich_vol_multiple_and_new_high 的数据)。"""
    closes = [20.0] + [10.0] * 20   # 今日 20 远高于前 20 日 10 → 新高
    vols = [3000.0] + [1000.0] * 20
    # 当日涨跌幅从 closes[0]/closes[1] 派生(20 vs 10)
    result = compute_form(closes, vols)
    assert result.vol_multiple == 3.0
    assert result.new_high_20d is True
    assert result.above_ma20 is True
    assert result.pct_60d == pytest.approx(100.0)   # (20-10)/10*100
    assert result.pct_chg == pytest.approx(100.0)   # (20-10)/10*100(从 closes 派生非 pre_close)


def test_compute_form_empty_safe():
    result = compute_form([], [])
    assert result.vol_multiple == 0.0
    assert result.new_high_20d is False
    assert result.above_ma20 is False
    assert result.pct_60d is None
    assert result.pct_chg == 0.0


def test_compute_form_single_day_safe():
    """只有一天数据(无历史)→ 各字段保守退化,不崩。"""
    result = compute_form([10.0], [1000.0])
    assert result.pct_chg == 0.0
    assert result.vol_multiple == 0.0
    assert result.new_high_20d is False
    assert result.pct_60d is None


# —— compute_form:20/60 日边界窗口不足退化正确 ——————————————————————————

def test_compute_form_window_insufficient_20d():
    """不足 20 日历史 → new_high 用现有全部(prev20 取现有),不崩不越界。"""
    closes = [15.0, 12.0, 13.0, 11.0]   # 只有 4 天
    vols = [500.0, 400.0, 300.0, 200.0]
    result = compute_form(closes, vols)
    assert result.new_high_20d is True   # 15 >= max(12,13,11)
    assert result.pct_60d is not None    # base_idx = min(60, len-1) = 3


def test_compute_form_ma_window_uses_rules_constant(monkeypatch):
    """ma20 窗口引用 rules.MA_DAYS(不硬编 20)——改常量后行为应跟随。"""
    from app.screen import rules

    closes = [10.0, 20.0, 20.0, 20.0, 5.0, 5.0]
    vols = [100.0] * 6
    # MA_DAYS=3 时 ma_window=[10,20,20],avg=16.67,today(10)<avg → above_ma20=False
    monkeypatch.setattr(rules, "MA_DAYS", 3, raising=False)
    result = compute_form(closes, vols)
    assert result.above_ma20 is False

    # MA_DAYS=6(全窗口)时 avg=(10+20+20+20+5+5)/6=13.33,today(10)<avg → 仍 False
    # 换一个能翻转结果的场景验证常量确实被使用
    monkeypatch.setattr(rules, "MA_DAYS", 1, raising=False)
    result2 = compute_form(closes, vols)
    assert result2.above_ma20 is True   # ma_window=[10],today(10)>=10 → True


# —— 阶段3.1 信号1:收盘站 VWAP(compute_form 新增 amounts 入参)——————————————

def test_vwap_ok_default_false_without_amounts():
    """不传 amounts(旧调用点向后兼容)→ vwap_ok 恒 False,不崩。"""
    closes = [10.0, 9.0, 9.5]
    vols = [1000.0, 900.0, 950.0]
    result = compute_form(closes, vols)             # 不传 amounts
    assert result.vwap_ok is False


def test_vwap_ok_close_above_vwap():
    """收在 VWAP 上 → vwap_ok True。

    今日 amount=1000 千元 = 100 万元, vol=100 手 = 10000 股 → vwap = 1e6/1e4 = 100.0。
    今日 close=105 >= 100 → 站上 VWAP。
    """
    closes = [105.0, 100.0]
    vols = [100.0, 100.0]           # 手
    amounts = [1000.0, 1000.0]      # 千元
    result = compute_form(closes, vols, amounts)
    assert result.vwap_ok is True


def test_vwap_ok_close_below_vwap():
    """收在 VWAP 下 → vwap_ok False(vwap=100,close=95<100)。"""
    closes = [95.0, 100.0]
    vols = [100.0, 100.0]
    amounts = [1000.0, 1000.0]
    result = compute_form(closes, vols, amounts)
    assert result.vwap_ok is False


def test_vwap_ok_zero_volume_guard():
    """停牌/异常行 vols[0]==0 → 除零守卫,vwap_ok False 不报错。"""
    closes = [95.0, 100.0]
    vols = [0.0, 100.0]             # 当日停牌 vol=0
    amounts = [1000.0, 1000.0]
    result = compute_form(closes, vols, amounts)    # 不抛 ZeroDivisionError
    assert result.vwap_ok is False


# —— 阶段3.1 信号5:近期活跃(had_limit_up,排除今日,从复权 closes 派生)——————————

def test_had_limit_up_historical_day():
    """近 N 日历史某日(下标 >=1)涨停 ≈9.9% → had_limit_up True。

    构造:closes 新→旧 = [今日, 昨日, 前日, ...];让昨日相对前日涨 ~9.9%
    (pct[1] = (closes[1]-closes[2])/closes[2])。今日温和(不参与,已排除)。
    """
    # closes[2]=100(前日), closes[1]=109.9(昨日,涨9.9%), closes[0]=110(今日温和涨0.09%)
    closes = [110.0, 109.9, 100.0] + [100.0] * 8
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols)
    assert result.had_limit_up is True


def test_had_limit_up_excludes_today():
    """仅今日(下标0)暴涨、历史全温和 → had_limit_up False(验排除今日 🟡#1)。

    今日相对昨日涨停(pct[0]≈9.9%),但历史各日温和 → 不算近期活跃(今日交给信号6)。
    """
    # closes[0]=109.9(今日暴涨), closes[1]=100(昨日), 之后全 100 温和
    closes = [109.9, 100.0] + [100.0] * 9
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols)
    assert result.had_limit_up is False


def test_had_limit_up_from_qfq_no_false_positive_on_dividend():
    """含除权跳变因子的样例:复权后不产生假涨停(验从复权 closes 派生 🟡#2)。

    原始价在除权日会跳变(如 10→5),若用原始 pct 会误判涨停/暴跌;compute_form 收到的
    是【已复权】closes,除权日跳变已被消除。这里传【复权后】平缓序列 → 无假涨停。
    """
    # 复权后序列平缓(每日 ~1% 内波动),即使原始价除权跳变,复权后不产生涨停
    closes = [100.0, 100.5, 100.2, 99.8, 100.1, 99.9, 100.3, 99.7, 100.0, 100.4, 100.1, 99.6]
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols)
    assert result.had_limit_up is False


def test_had_limit_up_data_insufficient_false():
    """数据不足(仅 1-2 天,无法派生历史 pct)→ had_limit_up False,不崩。"""
    assert compute_form([10.0], [1000.0]).had_limit_up is False
    assert compute_form([10.0, 9.0], [1000.0, 900.0]).had_limit_up is False


def test_had_limit_up_respects_lookback_window(monkeypatch):
    """涨停发生在回看窗口外(第 N+1 日更早)→ 不算(验窗口边界引用 ACTIVE_LOOKBACK_DAYS)。"""
    from app.screen import rules
    monkeypatch.setattr(rules, "ACTIVE_LOOKBACK_DAYS", 3, raising=False)
    # 涨停在 pct[5](窗口 [1:4] 之外)→ False
    # closes: idx 0..6;pct[5]=(closes[5]-closes[6])/closes[6]
    closes = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0, 100.0]   # 昨日窗口内全温和
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols)
    assert result.had_limit_up is False   # 涨停在窗口外(index5 > 窗口上界3)


# —— v1.3.1 A1 信号:pos_health(位置健康,距60日高点)————————————————————

def test_pos_health_near_high():
    """今日收盘贴近60日最高收盘 → pos_health 接近 1。"""
    closes = [99.0] + [100.0] * 25   # 60日最高=100,今日99 → 0.99
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols)
    assert result.pos_health == pytest.approx(0.99)


def test_pos_health_far_from_high():
    """今日收盘远离60日最高收盘 → pos_health 偏小。"""
    closes = [30.0] + [100.0] * 25   # 60日最高=100,今日30 → 0.30
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols)
    assert result.pos_health == pytest.approx(0.30)


def test_pos_health_data_insufficient_under_20_days_zero():
    """数据不足(len<20)→ pos_health=0.0(建议#9:防次新股贴短命高点白拿满权)。"""
    closes = [99.0] + [100.0] * 18   # 共 19 天 < 20
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols)
    assert result.pos_health == 0.0


def test_pos_health_exactly_20_days_computes():
    """恰好 20 天(边界含)→ 正常计算,不退化 0。"""
    closes = [99.0] + [100.0] * 19   # 共 20 天
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols)
    assert result.pos_health == pytest.approx(0.99)


# —— v1.3.1 A1 信号:breakout_ok(横盘突破,信号7)——————————————————————————

def test_breakout_ok_narrow_range_then_today_breaks_out_with_volume():
    """窄横盘 + 今日大阳线突破24日上沿 + 量比达标 → True(重要#5 门禁用例)。

    按错误公式(振幅窗口含今日)这条会 False:今日=110 会被纳入 max,振幅变成
    (110-98)/98≈12.2%<15%仍窄、但"今日突破区间上沿"的上沿本身被今日污染,
    今日不会 > 含自己的 max → False。正确实现(振幅在 closes[1:25],不含今日)
    应判 True:closes[1:25] 全在 [98,100] 窄幅内,今日 110 突破该区间上沿。
    """
    # closes[1:25] 24 天窄幅 [98,100.5],今日(closes[0])放量大阳线 110 突破上沿
    window = [99.0, 100.5, 98.0, 100.0] * 6   # 24 个数,窄幅
    closes = [110.0] + window
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols, volume_ratio=2.0)   # 量比达标(>=1.5)
    assert result.breakout_ok is True


def test_breakout_ok_false_when_range_not_narrow():
    """近24日振幅过宽(≥15%)→ False(即使今日突破 + 量比达标)。"""
    window = [80.0, 100.0, 85.0, 95.0] * 6   # 振幅 (100-80)/80=25% 远超 15%
    closes = [110.0] + window
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols, volume_ratio=2.0)
    assert result.breakout_ok is False


def test_breakout_ok_false_when_today_does_not_break_out():
    """今日未突破24日区间上沿 → False(即使窄幅 + 量比达标)。"""
    window = [99.0, 100.5, 98.0, 100.0] * 6   # 窄幅,上沿 100.5
    closes = [100.0] + window   # 今日 100 未突破 100.5
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols, volume_ratio=2.0)
    assert result.breakout_ok is False


def test_breakout_ok_false_when_volume_ratio_missing():
    """缺 volume_ratio(None,默认)→ False(向后兼容旧调用点)。"""
    window = [99.0, 100.5, 98.0, 100.0] * 6
    closes = [110.0] + window
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols)   # 不传 volume_ratio
    assert result.breakout_ok is False


def test_breakout_ok_false_when_volume_ratio_below_min():
    """量比不达标(<BREAKOUT_VOL_RATIO_MIN)→ False。"""
    window = [99.0, 100.5, 98.0, 100.0] * 6
    closes = [110.0] + window
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols, volume_ratio=1.0)   # <1.5
    assert result.breakout_ok is False


def test_breakout_ok_false_when_data_insufficient_under_25_days():
    """数据不足 25 日(closes[1:25] 拿不满)→ False,不崩。"""
    closes = [110.0] + [100.0] * 20   # 总共 21 天,closes[1:25] 只有 20 个
    vols = [1000.0] * len(closes)
    result = compute_form(closes, vols, volume_ratio=2.0)
    assert result.breakout_ok is False
