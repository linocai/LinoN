"""v1.4.1 Phase A:今日盈亏纯函数单测(today_realized_amount/today_float_pnl)+
GET /positions 端点接线(冻结 today,不联网)。"""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.api.today_pnl import today_float_pnl, today_realized_amount
from app.config import settings as settings_singleton

TEST_TOKEN = "t" * 64
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


# —— 纯函数:today_realized_amount ——————————————————————————————————

def test_today_realized_amount_sums_matching_date():
    trades = [
        {"close_time": "2026-07-07 10:00:00", "net_pnl_amount": -370.0},
        {"close_time": "2026-07-07 11:30:00", "net_pnl_amount": 50.0},
        {"close_time": "2026-07-06 15:00:00", "net_pnl_amount": 999.0},   # 非今日,不计
    ]
    assert today_realized_amount(trades, "2026-07-07") == pytest.approx(-320.0)


def test_today_realized_amount_no_match_returns_zero():
    trades = [{"close_time": "2026-07-01 10:00:00", "net_pnl_amount": 100.0}]
    assert today_realized_amount(trades, "2026-07-07") == 0.0


def test_today_realized_amount_empty_list():
    assert today_realized_amount([], "2026-07-07") == 0.0


def test_today_realized_amount_skips_null_net_pnl():
    """net_pnl_amount=NULL 的旧行(v1.3.0 迁移前)跳过不计入。"""
    trades = [
        {"close_time": "2026-07-07 10:00:00", "net_pnl_amount": None},
        {"close_time": "2026-07-07 11:00:00", "net_pnl_amount": 200.0},
    ]
    assert today_realized_amount(trades, "2026-07-07") == pytest.approx(200.0)


def test_today_realized_amount_iso8601_date_matches():
    """close_time 为 ISO8601(带 T)也能按日期前缀匹配。"""
    trades = [{"close_time": "2026-07-07T09:31:00", "net_pnl_amount": 88.0}]
    assert today_realized_amount(trades, "2026-07-07") == pytest.approx(88.0)


# —— 纯函数:today_float_pnl ——————————————————————————————————————————

def _holding(code, buy_date, buy_price, qty):
    return {"code": code, "buy_date": buy_date, "buy_price": buy_price, "qty": qty}


def test_today_float_pnl_uses_pre_close_for_old_holding():
    holdings = [_holding("600000", "2026-07-01", 10.0, 100)]
    prices = {"600000": 12.0}
    pre_closes = {"600000": 11.0}
    total, partial = today_float_pnl(holdings, prices, pre_closes, "2026-07-07")
    assert total == pytest.approx((12.0 - 11.0) * 100)
    assert partial is False


def test_today_float_pnl_uses_buy_price_for_new_buy_today():
    """今日新买(buy_date==today)用 buy_price 作 base,不受 pre_close 缺失影响。"""
    holdings = [_holding("600001", "2026-07-07", 20.0, 200)]
    prices = {"600001": 22.0}
    pre_closes = {}   # 缺失也无妨:今日新买用 buy_price
    total, partial = today_float_pnl(holdings, prices, pre_closes, "2026-07-07")
    assert total == pytest.approx((22.0 - 20.0) * 200)
    assert partial is False


def test_today_float_pnl_pre_close_missing_marks_partial():
    """非今日新买且 pre_close 缺失/<=0 → 该仓浮动 0 + partial=True。"""
    holdings = [_holding("600002", "2026-07-01", 10.0, 100)]
    prices = {"600002": 12.0}
    pre_closes = {"600002": 0.0}   # <=0 视为缺失
    total, partial = today_float_pnl(holdings, prices, pre_closes, "2026-07-07")
    assert total == 0.0
    assert partial is True


def test_today_float_pnl_price_missing_marks_partial_even_new_buy():
    """price 缺失/<=0(停牌)→ 无论今日新买与否记 0 + partial(先判 price 再判 base)。"""
    holdings = [_holding("600003", "2026-07-07", 15.0, 100)]   # 今日新买
    prices = {}   # 该 code 无价(停牌/拉价失败)
    pre_closes = {}
    total, partial = today_float_pnl(holdings, prices, pre_closes, "2026-07-07")
    assert total == 0.0
    assert partial is True


def test_today_float_pnl_multiple_holdings_partial_does_not_block_others():
    """一仓降级不阻塞其余持仓正常求和。"""
    holdings = [
        _holding("600004", "2026-07-01", 10.0, 100),   # 正常
        _holding("600005", "2026-07-01", 20.0, 100),   # pre_close 缺失,降级
    ]
    prices = {"600004": 11.0, "600005": 25.0}
    pre_closes = {"600004": 10.5}
    total, partial = today_float_pnl(holdings, prices, pre_closes, "2026-07-07")
    assert total == pytest.approx((11.0 - 10.5) * 100)
    assert partial is True


def test_today_float_pnl_empty_holdings():
    total, partial = today_float_pnl([], {}, {}, "2026-07-07")
    assert total == 0.0
    assert partial is False


def test_today_float_pnl_new_buy_zero_price_marks_partial():
    """今日新买但 buy_price<=0(理论不可达,API 层 Field(gt=0) 已挡死;此处防御性兜底)
    → 记 0 + partial,不让 base=0 把浮动虚增为 price*qty(🔵3)。"""
    holdings = [_holding("600006", "2026-07-07", 0.0, 100)]   # 今日新买,buy_price=0
    prices = {"600006": 12.0}
    pre_closes = {}
    total, partial = today_float_pnl(holdings, prices, pre_closes, "2026-07-07")
    assert total == 0.0
    assert partial is True


# —— 端点接线:GET /positions 今日盈亏字段 ——————————————————————————————

def _freeze_today(monkeypatch, iso: str) -> None:
    from datetime import date as _date

    y, m, d = (int(x) for x in iso.split("-"))
    frozen = _date(y, m, d)

    class _FixedDate(_date):
        @classmethod
        def today(cls):
            return frozen

    monkeypatch.setattr("datetime.date", _FixedDate)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_singleton, "DB_PATH", str(tmp_path / "today_pnl_api.db"), raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: {}, raising=False)
    with TestClient(app_mod.app) as c:
        yield c, app_mod


class _Q:
    def __init__(self, price, pre_close):
        self.price = price
        self.pre_close = pre_close


def test_positions_today_pnl_end_to_end(client, monkeypatch):
    """3 持仓 + 1 条今日已平 trade → today_pnl == realized + float,数值精确。"""
    c, app_mod = client
    _freeze_today(monkeypatch, "2026-07-07")   # 周二,交易日

    # 先开一仓并平仓,产生今日已实现(net_pnl_amount 由 close 端点算出落库)
    op = c.post("/api/v1/positions/open", json={
        "code": "600100", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    pid = op.json()["position_id"]
    close = c.post(f"/api/v1/positions/{pid}/close", json={
        "sell_price": 9.5, "sell_time": "2026-07-07 10:00:00",
    }, headers=AUTH)
    assert close.status_code == 200
    realized_expected = close.json()["net_pnl_amount"]
    assert realized_expected is not None

    # 3 持仓(2 老仓 + 1 今日新买),注入带 pre_close 的 Quote
    c.post("/api/v1/positions/open", json={
        "code": "600001", "buy_price": 20.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    c.post("/api/v1/positions/open", json={
        "code": "600002", "buy_price": 30.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)

    quotes = {
        "600001": _Q(price=22.0, pre_close=19.0),   # 老仓:(22-19)*100 = 300
        "600002": _Q(price=28.0, pre_close=31.0),   # 老仓:(28-31)*100 = -300
    }
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: quotes, raising=False)

    r = c.get("/api/v1/positions", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    expected_float = (22.0 - 19.0) * 100 + (28.0 - 31.0) * 100
    assert b["today_float"] == pytest.approx(expected_float)
    assert b["today_realized"] == pytest.approx(realized_expected)
    assert b["today_pnl"] == pytest.approx(realized_expected + expected_float)
    assert b["today_pnl_partial"] is False


def test_positions_today_pnl_pre_close_zero_marks_partial(client, monkeypatch):
    """pre_close=0 的持仓(非今日新买)→ 该仓浮动 0 + today_pnl_partial==True。"""
    c, app_mod = client
    _freeze_today(monkeypatch, "2026-07-06")   # 先在前一交易日开仓(非今日新买)
    c.post("/api/v1/positions/open", json={
        "code": "600010", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)

    _freeze_today(monkeypatch, "2026-07-07")   # 推进到今日
    monkeypatch.setattr(
        app_mod, "_quotes_fn",
        lambda codes: {"600010": _Q(price=12.0, pre_close=0.0)}, raising=False,
    )
    r = c.get("/api/v1/positions", headers=AUTH)
    b = r.json()
    assert b["today_float"] == 0.0
    assert b["today_pnl_partial"] is True


def test_positions_today_pnl_price_missing_marks_partial(client, monkeypatch):
    """prices 缺该 code(price=0/停牌,_quotes_fn 不返回该票)→ 该仓浮动 0 + partial,
    不抛 TypeError(🟡1 关键回归点)。"""
    c, app_mod = client
    _freeze_today(monkeypatch, "2026-07-07")

    c.post("/api/v1/positions/open", json={
        "code": "600011", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    # _quotes_fn 返回空(停牌/拉价失败,该 code 不在返回里)
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: {}, raising=False)
    r = c.get("/api/v1/positions", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["today_float"] == 0.0
    assert b["today_pnl_partial"] is True


def test_positions_today_pnl_new_buy_uses_buy_price_base(client, monkeypatch):
    """今日新买持仓(buy_date==today)base 用 buy_price,即使 pre_close 缺失也不降级。"""
    c, app_mod = client
    _freeze_today(monkeypatch, "2026-07-07")

    c.post("/api/v1/positions/open", json={
        "code": "600012", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    # 只给 price,不给 pre_close(getattr 缺省 None)
    class _QNoPreClose:
        def __init__(self, price):
            self.price = price

    monkeypatch.setattr(
        app_mod, "_quotes_fn",
        lambda codes: {"600012": _QNoPreClose(price=11.0)}, raising=False,
    )
    r = c.get("/api/v1/positions", headers=AUTH)
    b = r.json()
    assert b["today_float"] == pytest.approx((11.0 - 10.0) * 100)
    assert b["today_pnl_partial"] is False


def test_positions_today_pnl_no_realized_when_no_trades_today(client, monkeypatch):
    """无今日平仓 → today_realized==0。"""
    c, app_mod = client
    _freeze_today(monkeypatch, "2026-07-07")
    r = c.get("/api/v1/positions", headers=AUTH)
    assert r.json()["today_realized"] == 0.0


def test_positions_today_pnl_source_failure_degrades_not_500(client, monkeypatch):
    """拉价整体失败 → price/pre_close 全空,今日浮动 0、partial True、不 500。"""
    c, app_mod = client
    _freeze_today(monkeypatch, "2026-07-07")

    c.post("/api/v1/positions/open", json={
        "code": "600013", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)

    def _boom(codes):
        raise RuntimeError("network down")

    monkeypatch.setattr(app_mod, "_quotes_fn", _boom, raising=False)
    r = c.get("/api/v1/positions", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["today_float"] == 0.0
    assert b["today_pnl_partial"] is True


def test_positions_today_pnl_frozen_to_saturday_shows_prior_day_swing(client, monkeypatch):
    """冻结到周六(非交易日)+ buy_date=下一交易日(未来周一)→ buy_date[:10]==today 为
    false,走 pre_close 分支;今日浮动如实显示上一交易日全天变动、不为 0(顺带锁 D5 坑)。"""
    c, app_mod = client
    _freeze_today(monkeypatch, "2026-06-27")   # 周六,非交易日;buy_date 会取下一交易日 06-29(周一)

    op = c.post("/api/v1/positions/open", json={
        "code": "600014", "buy_price": 10.0, "qty": 100, "entry_reason": "x",
    }, headers=AUTH)
    assert op.json()["buy_date"] == "2026-06-29"   # 确认 D5 坑:buy_date 非今日(周六)

    # 周五全天变动:price=周五收盘 12.0,pre_close=周四收盘 11.0
    monkeypatch.setattr(
        app_mod, "_quotes_fn",
        lambda codes: {"600014": _Q(price=12.0, pre_close=11.0)}, raising=False,
    )
    r = c.get("/api/v1/positions", headers=AUTH)
    b = r.json()
    # buy_date(06-29) != today(06-27) → 非今日新买,走 pre_close 分支
    assert b["today_float"] == pytest.approx((12.0 - 11.0) * 100)
    assert b["today_float"] != 0.0
    assert b["today_pnl_partial"] is False
