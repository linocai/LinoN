"""阶段3 G1:打分聚合核心(纯确定性)单测。

覆盖 plan §4.4 G1 验收:
  ① 多周 trades 样例 → 正确 discipline_rate/score/redFlags/每笔 tag/comment;
  ② 空周 → discipline_rate=0/score=0/空数组/sampleNote,不返满分;
  ③ rateTrend 用上一 ISO 周:prev_week("2026-W01")=="2025-W52" + prev_week("2026-W27")=="2026-W26";
  ④ trend 近6周无交易的周补 0;
  ⑤ openHoldings 读未平 positions、tradeDay 用 count_holding_trade_days、不计入 discipline_rate;
  ⑥ list_closed_trades 直读全表(无 status 过滤),SQL 不含 status(grep 断言防回归)。
"""

import inspect
from datetime import date

import pytest

from app.db import store
from app.review import score
from app.review.score import (
    _mechanical_comment,
    aggregate_week,
    iso_week,
    prev_week,
    week_bounds,
)


# —— ISO 周原语 ————————————————————————————————————————————————————

def test_iso_week():
    assert iso_week("2026-06-30") == "2026-W27"          # 周二
    assert iso_week("2026-06-30 15:05:00") == "2026-W27"  # 带时刻
    assert iso_week(date(2026, 6, 29)) == "2026-W27"      # 周一


def test_prev_week_crosses_year_boundary():
    # 致命断言(plan-critic 实跑验算):2025 ISO 共 52 周
    assert prev_week("2026-W01") == "2025-W52"


def test_prev_week_same_year():
    assert prev_week("2026-W27") == "2026-W26"


def test_prev_week_no_arithmetic_on_number():
    # 若对周号算术减一,W53 边界会算错;这里验证走日期回溯口径
    assert prev_week("2021-W01") == "2020-W53"   # 2020 ISO 有 53 周


def test_week_bounds():
    mon, sun = week_bounds("2026-W27")
    assert mon == date(2026, 6, 29) and sun == date(2026, 7, 5)
    assert mon.isoweekday() == 1 and sun.isoweekday() == 7


# —— 机械短评单一事实源 ——————————————————————————————————————————————

def test_mechanical_comment_kept():
    flags = {"kept_stop": True, "kept_take": True, "kept_time": True, "broke_rule": False}
    assert _mechanical_comment(flags) == "守住铁律"


def test_mechanical_comment_broke_stop():
    flags = {"kept_stop": False, "kept_take": False, "kept_time": True, "broke_rule": True}
    assert _mechanical_comment(flags) == "破止损:跌穿 -5% 未走"


def test_mechanical_comment_broke_time():
    flags = {"kept_stop": True, "kept_take": False, "kept_time": False, "broke_rule": True}
    assert _mechanical_comment(flags) == "破时间:持过 D4 未清"


# —— 造多周 trades 样例的辅助 ————————————————————————————————————————

def _trade(close_time, pnl, kept_stop, kept_take, kept_time, broke_rule, name="示例", code="600000"):
    return {
        "code": code, "name": name, "pnl": pnl,
        "kept_stop": int(kept_stop), "kept_take": int(kept_take),
        "kept_time": int(kept_time), "broke_rule": int(broke_rule),
        "close_time": close_time,
    }


# —— ①:多周样例 → 正确聚合 ——————————————————————————————————————————

def test_aggregate_week_mixed():
    # W27(2026-06-29 ~ 07-05):3 笔 = 2 守 + 1 破止损
    trades = [
        _trade("2026-06-30 10:00:00", 6.4, True, False, True, False, name="兆易创新", code="603986"),
        _trade("2026-07-01 14:00:00", 16.2, True, True, True, False, name="工业富联", code="601138"),
        _trade("2026-07-02 09:40:00", -8.2, False, False, True, True, name="沪电股份", code="002463"),
    ]
    r = aggregate_week("2026-W27", trades_fn=lambda: trades, holdings_fn=lambda: [], today=date(2026, 7, 3))
    assert r["week"] == "2026-W27"
    assert r["disciplineRate"] == 67    # round(2/3*100)
    assert r["score"] == 67
    assert len(r["trades"]) == 3
    # redFlags 只 1 条(破止损那笔),带股票名 + 具体跌幅
    assert r["redFlags"] == ["沪电股份 破止损:-8.2% 未在 -5% 走"]
    tags = {t["code"]: t["tag"] for t in r["trades"]}
    assert tags["603986"] == "good" and tags["601138"] == "good" and tags["002463"] == "red"
    comments = {t["code"]: t["comment"] for t in r["trades"]}
    assert comments["002463"] == "破止损:跌穿 -5% 未走"
    assert comments["603986"] == "守住铁律"
    assert r["sampleNote"] == "本周 3 笔闭合"
    assert r["lessons"] == "" and r["nextWeekNote"] == ""


def test_aggregate_week_broke_time_red_flag():
    trades = [
        _trade("2026-06-30 10:00:00", 1.2, True, False, False, True, name="某票", code="600111"),
    ]
    r = aggregate_week("2026-W27", trades_fn=lambda: trades, holdings_fn=lambda: [], today=date(2026, 7, 3))
    assert r["disciplineRate"] == 0
    assert r["redFlags"] == ["某票 破时间:持过 D4 未清"]
    assert r["trades"][0]["comment"] == "破时间:持过 D4 未清"


# —— ②:空周 → 诚实空态,不返满分 ————————————————————————————————————

def test_aggregate_week_empty_is_honest_zero():
    r = aggregate_week("2026-W27", trades_fn=lambda: [], holdings_fn=lambda: [], today=date(2026, 7, 3))
    assert r["disciplineRate"] == 0 and r["score"] == 0
    assert r["redFlags"] == [] and r["trades"] == []
    assert r["sampleNote"] == "本周 0 笔闭合"
    # trend 仍是 6 个点(全 0)
    assert len(r["trend"]) == 6
    assert all(p["value"] == 0 for p in r["trend"])


# —— ③:rateTrend 用上一 ISO 周 ————————————————————————————————————

def test_rate_trend_uses_prev_iso_week():
    # 上周 W26 全守(rate=100),本周 W27 2/3 守(67)→ trend = 67-100 = -33
    trades = [
        _trade("2026-06-24 10:00:00", 5.0, True, False, True, False),   # W26
        _trade("2026-06-30 10:00:00", 6.4, True, False, True, False),   # W27
        _trade("2026-07-01 10:00:00", 16.2, True, True, True, False),   # W27
        _trade("2026-07-02 10:00:00", -8.2, False, False, True, True),  # W27 破
    ]
    r = aggregate_week("2026-W27", trades_fn=lambda: trades, holdings_fn=lambda: [], today=date(2026, 7, 3))
    assert r["disciplineRate"] == 67
    assert r["rateTrend"] == 67 - 100   # -33


def test_rate_trend_zero_when_no_prev_week():
    trades = [_trade("2026-06-30 10:00:00", 6.4, True, False, True, False)]
    r = aggregate_week("2026-W27", trades_fn=lambda: trades, holdings_fn=lambda: [], today=date(2026, 7, 3))
    assert r["rateTrend"] == 0   # 上周无数据 → 0(不是负满分)


# —— ④:trend 近6周,无交易补 0 ————————————————————————————————————

def test_trend_six_weeks_fills_zero():
    # 只有 W27 有交易(全守 100),前 5 周补 0
    trades = [_trade("2026-06-30 10:00:00", 6.4, True, False, True, False)]
    r = aggregate_week("2026-W27", trades_fn=lambda: trades, holdings_fn=lambda: [], today=date(2026, 7, 3))
    assert len(r["trend"]) == 6
    labels = [p["label"] for p in r["trend"]]
    assert labels == ["W22", "W23", "W24", "W25", "W26", "W27"]
    values = [p["value"] for p in r["trend"]]
    assert values == [0, 0, 0, 0, 0, 100]


# —— ⑤:openHoldings 读未平 positions、tradeDay 用日历、不计入 rate ————————

def test_open_holdings_not_counted_in_rate():
    trades = [
        _trade("2026-06-30 10:00:00", -8.2, False, False, True, True),  # 唯一闭合,破
    ]
    holdings = [
        {"code": "601138", "name": "工业富联", "buy_price": 18.3, "buy_date": "2026-06-29"},
    ]
    r = aggregate_week("2026-W27", trades_fn=lambda: trades, holdings_fn=lambda: holdings, today=date(2026, 7, 1))
    # discipline_rate 只按闭合笔(1 笔破)= 0;未平持仓不参与
    assert r["disciplineRate"] == 0
    assert len(r["openHoldings"]) == 1
    oh = r["openHoldings"][0]
    assert oh["name"] == "工业富联" and oh["code"] == "601138"
    assert oh["buyPrice"] == 18.3
    # tradeDay 用 count_holding_trade_days([2026-06-29, 2026-07-01]) = 3 交易日(周一/二/三)
    from app.calendar.trading_calendar import count_holding_trade_days
    assert oh["tradeDay"] == count_holding_trade_days("2026-06-29", date(2026, 7, 1))
    assert oh["tradeDay"] == 3


def test_open_holdings_name_fallback_to_code():
    holdings = [{"code": "600519", "name": None, "buy_price": 10.0, "buy_date": "2026-06-29"}]
    r = aggregate_week("2026-W27", trades_fn=lambda: [], holdings_fn=lambda: holdings, today=date(2026, 7, 1))
    assert r["openHoldings"][0]["name"] == "600519"


# —— ⑥:list_closed_trades 直读全表(无 status 过滤)————————————————————

def test_list_closed_trades_no_status_filter_in_sql():
    """源码 grep:list_closed_trades 的 SQL 绝不按 status 过滤(防回归)。

    trades 无 status 列,`WHERE status='closed'` 会抛 no such column。
    只检真 SQL 危险模式(注释里的解释性 "status" 词不算)。
    """
    src = inspect.getsource(store.list_closed_trades).lower()
    for bad in ("where status", "status=", "status =", "status='closed'", "and status"):
        assert bad not in src, f"list_closed_trades SQL 不应含 {bad!r}"


def test_list_closed_trades_reads_full_table(tmp_path):
    db = str(tmp_path / "t.db")
    store.init_db(db)
    pid = store.open_position("603986", "兆易创新", 100.0, 100, "x", "2026-06-22", db_path=db)
    store.close_position(pid, 116.0, close_time="2026-06-30 10:00:00", holding_trade_days=2, db_path=db)
    pid2 = store.open_position("601138", "工业富联", 50.0, 100, "x", "2026-06-22", db_path=db)
    store.close_position(pid2, 40.0, close_time="2026-07-02 10:00:00", holding_trade_days=2, db_path=db)

    rows = store.list_closed_trades(db_path=db)
    assert len(rows) == 2
    # 升序 by close_time
    assert rows[0]["close_time"] < rows[1]["close_time"]
    # since/until 过滤
    only_first = store.list_closed_trades(until="2026-07-01", db_path=db)
    assert len(only_first) == 1 and only_first[0]["code"] == "603986"
    only_second = store.list_closed_trades(since="2026-07-01", db_path=db)
    assert len(only_second) == 1 and only_second[0]["code"] == "601138"


def test_list_all_trades_alias(tmp_path):
    db = str(tmp_path / "t2.db")
    store.init_db(db)
    pid = store.open_position("603986", "兆易创新", 100.0, 100, "x", "2026-06-22", db_path=db)
    store.close_position(pid, 116.0, holding_trade_days=2, db_path=db)
    assert len(store.list_all_trades(db_path=db)) == 1
