"""阶段1 A.3:3 硬线判定 + T+1/涨跌停文案 + 多源一致性校验(纯函数,不联网)。

构造行情注入 classify。买入日选交易日 2026-06-22(周一)便于排 D1..D4。
  D1 = 2026-06-22(周一),D2 = 06-23,D3 = 06-24,D4 = 06-25。
"""

from datetime import date

from app.monitor.hardline import (
    KIND_STOP,
    KIND_TAKE,
    KIND_TIME,
    KIND_SUSPECT,
    classify,
    pnl_pct_of,
    quotes_consistent,
)

BUY = date(2026, 6, 22)   # 周一,交易日 → D1


def _classify(*, price, buy_price=100.0, pre_close=99.0, limit_up=109.0,
              limit_down=89.0, today, suspect=False):
    return classify(
        code="600000", name="示例", buy_price=buy_price, price=price,
        pre_close=pre_close, limit_up=limit_up, limit_down=limit_down,
        buy_date=BUY, today=today, quote_suspect=suspect,
    )


# —— 止损线 ——
def test_d1_stop_says_tomorrow_not_must_go():
    """D1 命中止损 → 文案'记录,明日开盘处理',不喊'必走'(T+1)。"""
    evs = _classify(price=94.0, today=date(2026, 6, 22))  # -6% → 触损,D1
    assert len(evs) == 1 and evs[0].kind == KIND_STOP
    assert evs[0].actionable is False
    assert "明日" in evs[0].body and "必走" not in evs[0].body


def test_d2_stop_says_must_go():
    """D2 命中止损(可成交)→ '必走'。"""
    evs = _classify(price=94.0, today=date(2026, 6, 23))  # D2
    assert len(evs) == 1 and evs[0].kind == KIND_STOP
    assert evs[0].actionable is True
    assert "必走" in evs[0].body


def test_limit_down_seal_says_tomorrow():
    """一字跌停封死(现价贴跌停价)→ '封死,明日处理',不喊必走(即便 D2+)。"""
    # 跌停价 89.0,现价 89.0(贴死),且 -11% 触损;D2
    evs = _classify(price=89.0, limit_down=89.0, today=date(2026, 6, 23))
    assert len(evs) == 1 and evs[0].kind == KIND_STOP
    assert evs[0].actionable is False
    assert "封死" in evs[0].body and "明日" in evs[0].body


# —— 止盈线 ——
def test_take_profit_d2():
    # limit_up=130(远高于现价 116)→ 可成交,'可走'
    evs = _classify(price=116.0, limit_up=130.0, today=date(2026, 6, 23))  # +16% → 止盈,D2
    assert len(evs) == 1 and evs[0].kind == KIND_TAKE
    assert evs[0].actionable is True
    assert "可走" in evs[0].body


def test_take_limit_up_seal_says_tomorrow():
    """触止盈线但一字涨停封死无法成交 → '明日处理'。"""
    evs = _classify(price=116.0, limit_up=116.0, today=date(2026, 6, 23))
    assert evs[0].kind == KIND_TAKE and evs[0].actionable is False
    assert "涨停" in evs[0].body and "明日" in evs[0].body


def test_take_d1_says_tomorrow():
    evs = _classify(price=116.0, limit_up=130.0, today=date(2026, 6, 22))  # D1
    assert evs[0].kind == KIND_TAKE and evs[0].actionable is False
    assert "明日" in evs[0].body


# —— D4 时间强平 ——
def test_d4_force_close():
    """D4 出强平(独立于价格线;现价小亏也强平)。"""
    evs = _classify(price=98.0, today=date(2026, 6, 25))  # D4,-2% 未触价格线
    kinds = [e.kind for e in evs]
    assert KIND_TIME in kinds
    time_ev = [e for e in evs if e.kind == KIND_TIME][0]
    assert time_ev.actionable is True and "无条件清仓" in time_ev.body


def test_d4_plus_stop_two_events():
    """D4 当天同时触止损 → 价格线 + 时间线两条事件。"""
    evs = _classify(price=94.0, today=date(2026, 6, 25))  # -6% + D4
    kinds = sorted(e.kind for e in evs)
    assert KIND_STOP in kinds and KIND_TIME in kinds
    assert len(evs) == 2


# —— 多源一致性 ——
def test_quotes_consistent_ok():
    assert quotes_consistent(99.0, 100.0, 99.0, 100.1) is True


def test_quotes_inconsistent_pre_close_divergence():
    # 除权口径差:一源 pre_close 90,一源 99 → >2% → 不一致
    assert quotes_consistent(90.0, 100.0, 99.0, 100.0) is False


def test_suspect_does_not_trigger_hardline():
    """两源不一致 → 只产出 KIND_SUSPECT,不触发硬线(防假报警)。"""
    evs = _classify(price=94.0, today=date(2026, 6, 23), suspect=True)  # 本会触损
    assert len(evs) == 1 and evs[0].kind == KIND_SUSPECT
    assert evs[0].is_hardline is False
    assert "存疑" in evs[0].title and "不据此触发" in evs[0].body


# —— pnl 工具 ——
def test_pnl_pct_of():
    assert pnl_pct_of(100.0, 95.0) == -5.0
    assert pnl_pct_of(100.0, 115.0) == 15.0
    assert pnl_pct_of(0.0, 50.0) == 0.0


def test_no_trigger_in_normal_band():
    """正常区间(-3%)→ 无硬线事件。"""
    evs = _classify(price=97.0, today=date(2026, 6, 23))
    assert evs == []
