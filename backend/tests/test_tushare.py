"""Phase 0.3 Tushare:无 token 优雅降级(不抛),ts_code 归一,异常收敛。"""

import app.data.tushare_client as tc
from app.data.tushare_client import (
    TushareResult,
    reset_client_cache,
    to_ts_code,
    ts_daily,
    ts_daily_basic,
    ts_moneyflow,
    ts_trade_cal,
)


class _NoTokenSettings:
    """无 token 的 settings 替身(pydantic BaseSettings 不允许直接改属性,故用替身)。"""

    TUSHARE_TOKEN = None


def _force_no_token(monkeypatch):
    # _get_pro 读的是 tushare_client 模块内 import 进来的 settings 名字
    monkeypatch.setattr(tc, "settings", _NoTokenSettings())
    reset_client_cache()


def test_to_ts_code():
    assert to_ts_code("603986") == "603986.SH"
    assert to_ts_code("000001") == "000001.SZ"
    assert to_ts_code("300750") == "300750.SZ"
    assert to_ts_code("688981") == "688981.SH"
    assert to_ts_code("600000.SH") == "600000.SH"   # 已是 ts_code 原样


def test_all_four_degrade_without_token(monkeypatch):
    """无 token → 四接口 ok=False, data=None, reason 可读,不抛。"""
    _force_no_token(monkeypatch)
    results = {
        "moneyflow": ts_moneyflow("603986", "20260601", "20260618"),
        "daily_basic": ts_daily_basic("603986", "20260618"),
        "daily": ts_daily("603986", "20260601", "20260618"),
        "trade_cal": ts_trade_cal("20260601", "20260630"),
    }
    for name, r in results.items():
        assert isinstance(r, TushareResult), name
        assert r.ok is False, name
        assert r.data is None, name
        assert r.reason and isinstance(r.reason, str), name
        assert "token" in r.reason  # "token 缺失"
    reset_client_cache()


def test_result_helpers():
    f = TushareResult.fail("x")
    assert f.ok is False and f.data is None and f.reason == "x"
    s = TushareResult.success([1, 2])
    assert s.ok is True and s.data == [1, 2] and s.reason == "ok"


def test_api_exception_is_caught(monkeypatch):
    """pro 初始化成功但调用抛异常 → 收敛为 ok=False,不外泄异常。"""

    class _FakePro:
        def daily(self, **kw):
            raise RuntimeError("抱歉,您每分钟最多访问该接口500次")

    monkeypatch.setattr(tc, "_get_pro", lambda: (_FakePro(), "ok"))
    r = ts_daily("603986", "20260601", "20260618")
    assert r.ok is False and r.data is None
    assert "限频" in r.reason


def test_network_exception_is_caught(monkeypatch):
    class _FakePro:
        def moneyflow(self, **kw):
            raise ConnectionError("connection reset")

    monkeypatch.setattr(tc, "_get_pro", lambda: (_FakePro(), "ok"))
    r = ts_moneyflow("603986", "20260601", "20260618")
    assert r.ok is False and "网络/接口异常" in r.reason


def test_success_path(monkeypatch):
    """模拟有 token + 成功返回 DataFrame-like → ok=True 透传 data。"""

    class _FakePro:
        def daily(self, **kw):
            return [{"trade_date": "20260618", "close": 629.0}]

    monkeypatch.setattr(tc, "_get_pro", lambda: (_FakePro(), "ok"))
    r = ts_daily("603986", "20260601", "20260618")
    assert r.ok is True and r.data == [{"trade_date": "20260618", "close": 629.0}]
