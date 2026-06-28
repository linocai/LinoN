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


# —— rules:高位线(二元 + warn 降级)————————————————————————————————

def test_high_position_verdict():
    assert rules.high_position_verdict(120.0) == "exclude"
    assert rules.high_position_verdict(100.0) == "exclude"
    assert rules.high_position_verdict(80.0) == "warn"
    assert rules.high_position_verdict(50.0) == "warn"
    assert rules.high_position_verdict(49.9) == "ok"
    assert rules.high_position_verdict(0.0) == "ok"
    assert rules.high_position_verdict(None) == "ok"


def test_high_warn_text():
    assert rules.high_warn_text(60.0) is not None
    assert rules.high_warn_text(120.0) is None   # ≥100 已排除,不出 warn
    assert rules.high_warn_text(10.0) is None
    assert rules.high_warn_text(None) is None


# —— rules:截断公式(随 free_slots:3→15、1→5、0→0)——————————————————

def test_truncation_limit():
    assert rules.free_slots(0) == 3 and rules.truncation_limit(0) == 15
    assert rules.free_slots(2) == 1 and rules.truncation_limit(2) == 5
    assert rules.free_slots(3) == 0 and rules.truncation_limit(3) == 0   # 满仓闭门
    assert rules.free_slots(5) == 0 and rules.truncation_limit(5) == 0   # 兜底不越界


# —— rules:排序加权(放量权重最大)————————————————————————————————

def test_rank_score_vol_is_single_largest_factor():
    # 放量是单一最大权因子(0.4):其余三项相等、仅放量不同 → 放量高者得分高。
    scores = rules.rank_score(
        vol_multiples=[5.0, 1.5],
        fund_3d=[100.0, 100.0],
        turnovers=[3.0, 3.0],
        pct_60ds=[10.0, 10.0],
    )
    assert scores[0] > scores[1]


def test_rank_score_vol_outweighs_any_single_other():
    # 放量权(0.4)大于任意单个其他因子权:A 仅放量满分,B 仅资金满分 → A 胜。
    scores = rules.rank_score(
        vol_multiples=[5.0, 1.5],   # A 放量满分,B 最低
        fund_3d=[100.0, 999.0],     # B 资金满分,A 最低
        turnovers=[3.0, 3.0],
        pct_60ds=[10.0, 10.0],
    )
    assert scores[0] > scores[1]    # 0.4(vol) > 0.25(fund)


def test_rank_score_empty():
    assert rules.rank_score([], [], [], []) == []


def test_weights_sum_to_one():
    assert abs(sum(rules.WEIGHTS.values()) - 1.0) < 1e-9


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
    _enrich_form(sr, "600000", dates, dbd, dates[0])
    assert sr.vol_multiple == 3.0
    assert sr.new_high_20d is True
    assert sr.above_ma20 is True
    # 60 日涨幅:closes 只有 21 个 → base 取最旧(10),(20-10)/10=100%
    assert sr.pct_60d == pytest.approx(100.0)
    # 当日涨跌幅 (20-19)/19*100
    assert sr.pct_chg == pytest.approx(5.26, abs=0.05)


def test_enrich_no_data_safe():
    sr = StockRow(code="600000", name="x", industry="")
    _enrich_form(sr, "600000", [], {}, "20260506")
    assert sr.vol_multiple == 0.0 and sr.new_high_20d is False and sr.pct_60d is None


# —— fetch_market_snapshot:东财 moneyflow_dc 字段映射/单位/近3日合计/降级 ——————
# 资金源切到东财 moneyflow_dc 后,fetch 读 net_amount(万元)填 net_mf_amount/net_mf_3d。
# 用造的样例 DataFrame 驱动(不联网),验证字段映射 + 近 3 日合计 + 无权限降级。

def _df(records):
    import pandas as pd
    return pd.DataFrame(records)


def _patch_fetch(monkeypatch, *, basic, dc_by_date, daily_by_date, stock_basic=None):
    """注入假 Tushare 接口(全市场 daily_basic / 东财 moneyflow_dc / daily / stock_basic)。

    dc_by_date / daily_by_date: {'YYYYMMDD': [records]};缺日 → ok=False 降级。
    stock_basic: 行业映射记录列表(None → 不提供,行业退化为空)。
    """
    fetch_mod.reset_industry_cache()

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

    def _stock_basic():
        return TushareResult.success(_df(stock_basic)) if stock_basic is not None \
            else TushareResult.fail("stock_basic 失败")

    monkeypatch.setattr(fetch_mod.tc, "ts_daily_basic_all", _basic_all)
    monkeypatch.setattr(fetch_mod.tc, "ts_moneyflow_dc_all", _dc_all)
    monkeypatch.setattr(fetch_mod.tc, "ts_daily_all", _daily_all)
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


# —— pipeline:黑名单/高位/粗筛/排序/截断(喂样例,免联网)——————————————

def _sr(code, name, industry, vol_mult=2.0, mf3=100.0, mf_today=10.0,
        new_high=True, above_ma=True, pct60=10.0, close=10.0, turnover=5.0, pct_chg=3.0):
    return StockRow(
        code=code, name=name, industry=industry, close=close, pct_chg=pct_chg,
        turnover=turnover, net_mf_amount=mf_today, net_mf_3d=mf3,
        vol_multiple=vol_mult, pct_60d=pct60, new_high_20d=new_high, above_ma20=above_ma,
    )


def test_pipeline_blacklist_and_high_excluded():
    rows = [
        _sr("600000", "干净A", "银行"),                       # 合格
        _sr("300001", "创业板", "电池"),                      # 黑名单代码
        _sr("600519", "贵州茅台", "白酒"),                    # 白酒黑名单
        _sr("600002", "高位B", "钢铁", pct60=150.0),          # 高位 ≥100 排除
        _sr("600003", "warnC", "有色", pct60=70.0),           # ≥50 warn 不排除
    ]
    snap = MarketSnapshot(trade_date="2026-05-06", rows=rows)
    out = pipeline.build_candidates(snap)
    codes = [c["code"] for c in out]
    assert "600000" in codes and "600003" in codes
    assert "300001" not in codes and "600519" not in codes and "600002" not in codes
    # warn 降级:600003 warn 非空
    warnc = next(c for c in out if c["code"] == "600003")
    assert warnc.get("warn")
    # 干净 A 无 warn
    cleana = next(c for c in out if c["code"] == "600000")
    assert cleana.get("warn") is None


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
    # 逐字段对齐 Candidate(Models.swift)
    for k in ("rank", "name", "code", "sector", "tag", "price", "chg",
              "volMultiple", "volPct", "turnover", "flow"):
        assert k in c
    assert c["volMultiple"] == "2.8x"
    assert isinstance(c["volPct"], int) and 0 <= c["volPct"] <= 100
    assert c["flow"] == "+1.20亿"   # 12000 万 → 1.20 亿


def test_run_pipeline_degraded_on_failed_snapshot():
    def _fail(td):
        return MarketSnapshot.fail("2026-05-06", "token 缺失")
    rows, degraded, reason, td = pipeline.run_pipeline("20260506", snapshot_fn=_fail)
    assert rows == [] and degraded is True and "token" in reason


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


def _cand(rank, code, warn=None):
    return {
        "rank": rank, "name": f"票{code}", "code": code, "sector": "半导体",
        "tag": "放量突破", "price": 10.0 + rank, "chg": "+3.00%",
        "volMultiple": "2.8x", "volPct": 90, "flow": "+1.20亿",
        "turnover": "4.6%", "warn": warn,
    }


def test_upsert_and_list_candidates(db):
    rows = [_cand(1, "600000"), _cand(2, "600001", warn="60日累涨 70%")]
    n = store.upsert_candidates("2026-05-06", rows, db_path=db)
    assert n == 2
    got = store.list_candidates("2026-05-06", db_path=db)
    assert [c["code"] for c in got] == ["600000", "600001"]
    assert got[0]["volMultiple"] == "2.8x" and got[0]["volPct"] == 90
    assert "warn" not in got[0]          # warn=None → 省略键
    assert got[1]["warn"] == "60日累涨 70%"


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
