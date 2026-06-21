"""Phase 0.2 实时价:解析 / 降级 / 涨跌停 / 代码归一(样例报文,离线)。

样例报文取自真源实测(2026-06-18 收盘快照),保证解析与真实格式对齐;
ST 报文为合成(改名加 ST,验证 ±5% 路径)。真源联网/盘中实测见报告。
"""

import app.data.realtime as rt
from app.data.realtime import (
    Quote,
    compute_limits,
    get_realtime_quote,
    get_realtime_quotes,
    to_symbol,
)

# —— 真源样例(逗号分隔的引号内 body)——
SINA_BODY = (
    "兆易创新,594.000,586.040,629.000,644.640,586.600,628.980,629.000,"
    "59157318,37016387910.000,500,628.980,2700,628.900,200,628.890,1100,"
    "628.880,200,628.860,146318,629.000,200,629.310,400,629.470,700,629.900,"
    "1000,629.910,2026-06-18,15:00:00,00,"
)
TENC_BODY = (
    "1~兆易创新~603986~629.00~586.04~594.00~591573~323172~268402~628.98~5~"
    "628.90~27~628.89~2~628.88~11~628.86~2~629.00~1463~629.31~2~629.47~4~"
    "629.90~7~629.91~10~~20260618161400~42.96~7.33~644.64~586.60~"
    "629.00/591573/37016387910~591573~3701639~8.86~153.41~~644.64~586.60~"
    "9.90~4200.74~4409.93~17.82~644.64~527.44~1.36~-1439~625.73~75.45~267.59"
)
# 合成 ST 报文(基于 sina 格式,改名 *ST,pre_close=10.00)
SINA_ST_BODY = (
    "*ST示例,10.000,10.000,9.500,10.500,9.500,9.490,9.500,"
    "1000000,9500000.000,500,9.490,0,0,0,0,0,0,0,0,1000,9.500,0,0,0,0,0,0,0,0,"
    "2026-06-18,15:00:00,00,"
)


# —— 代码→市场前缀 ——

def test_to_symbol():
    assert to_symbol("603986") == "sh603986"
    assert to_symbol("600519") == "sh600519"
    assert to_symbol("000001") == "sz000001"
    assert to_symbol("300750") == "sz300750"
    assert to_symbol("688981") == "sh688981"
    assert to_symbol("sh603986") == "sh603986"   # 已带前缀原样


# —— 新浪解析 ——

def test_parse_sina_normal():
    q = rt._parse_sina("sh603986", SINA_BODY)
    assert q is not None
    assert q.source == "sina"
    assert q.code == "603986"
    assert q.name == "兆易创新"
    assert q.price == 629.0
    assert q.pre_close == 586.04
    assert q.open == 594.0
    assert q.high == 644.64
    assert q.low == 586.6
    # 主板 ±10%(由 pre_close 算,四舍五入 0.01)
    assert q.limit_up == round(586.04 * 1.10, 2)   # 644.64
    assert q.limit_down == round(586.04 * 0.90, 2)  # 527.44
    # 单位归一:sina volume 股 → 手(÷100);amount 元原样
    assert q.volume == round(59157318 / 100, 2)
    assert q.amount == 37016387910.0
    assert q.bid[0] == 628.98
    assert q.ask[0] == 629.0
    assert q.ts == "2026-06-18 15:00:00"


def test_parse_sina_st_limit_5pct():
    """名称含 *ST → 涨跌停 ±5%。"""
    q = rt._parse_sina("sh600000", SINA_ST_BODY)
    assert q is not None
    assert "ST" in q.name.upper()
    assert q.limit_up == round(10.0 * 1.05, 2)    # 10.50
    assert q.limit_down == round(10.0 * 0.95, 2)  # 9.50


def test_parse_sina_empty_returns_none():
    """停牌/非法(空 body 或字段不足)→ None,不抛。"""
    assert rt._parse_sina("sh603986", "") is None
    assert rt._parse_sina("sh603986", "兆易创新,594") is None


# —— 腾讯解析(降级源)——

def test_parse_tencent_normal():
    q = rt._parse_tencent("sh603986", TENC_BODY)
    assert q is not None
    assert q.source == "tencent"
    assert q.code == "603986"
    assert q.name == "兆易创新"
    assert q.price == 629.0
    assert q.pre_close == 586.04
    assert q.open == 594.0
    assert q.high == 644.64
    assert q.low == 586.6
    # tencent volume 手原样;amount 万元 → 元(×1e4)
    assert q.volume == 591573.0
    assert q.amount == round(3701639 * 10000, 2)
    # bid/ask 价先量后:bid1 价在 index9
    assert q.bid[0] == 628.98
    assert q.ask[0] == 629.0
    assert q.ts == "2026-06-18 16:14:00"
    assert q.limit_up == round(586.04 * 1.10, 2)


def test_parse_tencent_short_returns_none():
    assert rt._parse_tencent("sh603986", "1~~~") is None


# —— 涨跌停纯函数 ——

def test_compute_limits_mainboard():
    up, down = compute_limits(10.0, "603986", "兆易创新")
    assert up == 11.0 and down == 9.0


def test_compute_limits_st():
    up, down = compute_limits(10.0, "600000", "ST示例")
    assert up == 10.5 and down == 9.5


def test_compute_limits_zero_preclose():
    assert compute_limits(0.0, "603986", "x") == (0.0, 0.0)


# —— 降级编排:新浪挂 → 腾讯补 ——

def test_failover_sina_down_tencent_up(monkeypatch):
    """新浪整源失败(空),腾讯补上 → 结果来自 tencent。"""
    monkeypatch.setattr(rt, "_fetch_sina", lambda syms: {})
    monkeypatch.setattr(
        rt, "_fetch_tencent", lambda syms: {"sh603986": TENC_BODY}
    )
    q = get_realtime_quote("603986")
    assert q is not None and q.source == "tencent" and q.price == 629.0


def test_sina_primary_wins(monkeypatch):
    """新浪有数据 → 不降级,结果来自 sina;腾讯不应被查。"""
    monkeypatch.setattr(rt, "_fetch_sina", lambda syms: {"sh603986": SINA_BODY})

    def _should_not_call(syms):
        raise AssertionError("主源成功时不应调腾讯")

    monkeypatch.setattr(rt, "_fetch_tencent", _should_not_call)
    q = get_realtime_quote("603986")
    assert q is not None and q.source == "sina"


def test_all_sources_down_returns_none(monkeypatch):
    """两源全挂 → None,整体不崩。"""
    monkeypatch.setattr(rt, "_fetch_sina", lambda syms: {})
    monkeypatch.setattr(rt, "_fetch_tencent", lambda syms: {})
    assert get_realtime_quote("603986") is None
    assert get_realtime_quotes(["603986", "000001"]) == {}


def test_batch_mixed_sources(monkeypatch):
    """一票走新浪、一票主源缺走腾讯补。"""
    monkeypatch.setattr(rt, "_fetch_sina", lambda syms: {"sh603986": SINA_BODY})
    monkeypatch.setattr(
        rt, "_fetch_tencent",
        lambda syms: {"sz000001": TENC_BODY.replace("603986", "000001")},
    )
    out = get_realtime_quotes(["603986", "000001"])
    assert set(out.keys()) == {"603986", "000001"}
    assert out["603986"].source == "sina"
    assert out["000001"].source == "tencent"


def test_quote_to_dict():
    q = rt._parse_sina("sh603986", SINA_BODY)
    d = q.to_dict()
    assert d["code"] == "603986" and d["source"] == "sina"
    assert isinstance(d["bid"], list)
