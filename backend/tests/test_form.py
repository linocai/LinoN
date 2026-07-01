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
