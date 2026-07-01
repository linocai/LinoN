"""阶段2.5 F3:回测回填(run_backfill)+ verdict 落库单测。

不联网:daily_all_fn 注入假 TushareResult;DB 用 tmp_path。验证:
  · ret_3d 用 pct_chg 累乘算对(致命2 收益口径);
  · pending_backfill_entries 只返回 >=3 交易日已过 + 未回填的候选;
  · 幂等(UNIQUE 生效,重跑不重复行);
  · 重启/错过窗口场景次日 tick 自动补齐(扫描式,不靠内存);
  · 缺某日/某票 daily → 该票跳过、其余照落,不崩;
  · 无 token(daily_all 全失败)→ 回填 0 行不崩;
  · analysis_verdicts:trade_date 取所属候选日(非 latest)、coach 模式不落、
    ON CONFLICT DO UPDATE 覆盖最新。
"""

import pytest
import pandas as pd

from app.db import store
from app.data.tushare_client import TushareResult
from app.screen import backtest


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "backtest.db")
    store.init_db(path)
    return path


def _seed_candidates(db, entry_date="2026-06-23"):
    rows = [
        {"rank": 1, "name": "票A", "code": "600001", "sector": "半导体", "tag": "放量突破",
         "price": 10.0, "chg": "+3.00%", "volMultiple": "2.8x", "volPct": 90,
         "flow": "+1.20亿", "turnover": "4.6%", "warn": None},
        {"rank": 2, "name": "票B", "code": "600002", "sector": "医药", "tag": "站上均线",
         "price": 20.0, "chg": "+1.00%", "volMultiple": "1.8x", "volPct": 60,
         "flow": "+0.50亿", "turnover": "3.0%", "warn": None},
    ]
    store.upsert_candidates(entry_date, rows, db_path=db)
    return rows


def _daily_fn_factory(by_date):
    """by_date: {'YYYYMMDD': [{'ts_code':..,'pct_chg':..,'close':..}, ...]} 或 None(失败)。"""
    def _fn(td):
        recs = by_date.get(td)
        if recs is None:
            return TushareResult.fail("daily 拉取失败")
        return TushareResult.success(pd.DataFrame(recs))
    return _fn


# —— ret_3d 收益口径(致命2):pct_chg 累乘 ——————————————————————————————

def test_run_backfill_with_frozen_today(db, monkeypatch):
    """冻结 today 到 entry_date 之后第 3 个交易日,确保 pending 命中候选。"""
    entry_date = "2026-06-23"
    _seed_candidates(db, entry_date)
    by_date = {
        "20260623": [
            {"ts_code": "600001.SH", "close": 10.0, "pct_chg": 0.0},
            {"ts_code": "600002.SH", "close": 20.0, "pct_chg": 0.0},
        ],
        "20260624": [
            {"ts_code": "600001.SH", "close": 11.0, "pct_chg": 10.0},
            {"ts_code": "600002.SH", "close": 19.0, "pct_chg": -5.0},
        ],
        "20260625": [
            {"ts_code": "600001.SH", "close": 12.1, "pct_chg": 10.0},
            {"ts_code": "600002.SH", "close": 19.0, "pct_chg": 0.0},
        ],
        "20260626": [
            {"ts_code": "600001.SH", "close": 12.1, "pct_chg": 0.0},
            {"ts_code": "600002.SH", "close": 17.1, "pct_chg": -10.0},
        ],
    }
    from datetime import date as _date

    today = _date(2026, 6, 26)   # entry_date 后第 3 个交易日(D4,已收盘)
    out = backtest.run_backfill(
        now=today, daily_all_fn=_daily_fn_factory(by_date), db_path=db,
    )
    assert out["entries_scanned"] == 2
    assert out["filled"] == 2

    outcomes = {o["code"]: o for o in store.list_outcomes(db_path=db)}
    # 600001: (1.10)(1.10)(1.00)-1 = 0.21 → 21%
    assert outcomes["600001"]["ret_3d"] == pytest.approx(21.0, abs=0.01)
    assert outcomes["600001"]["entry_close"] == pytest.approx(10.0)
    assert outcomes["600001"]["exit_close"] == pytest.approx(12.1)
    assert outcomes["600001"]["exit_date"] == "2026-06-26"
    # 600002: (0.95)(1.00)(0.90)-1 = -0.145 → -14.5%
    assert outcomes["600002"]["ret_3d"] == pytest.approx(-14.5, abs=0.01)


# —— 幂等(重跑不重复行)——————————————————————————————————————————————

def test_run_backfill_idempotent_rerun(db, monkeypatch):
    entry_date = "2026-06-23"
    _seed_candidates(db, entry_date)
    by_date = {
        "20260623": [{"ts_code": "600001.SH", "close": 10.0, "pct_chg": 0.0},
                     {"ts_code": "600002.SH", "close": 20.0, "pct_chg": 0.0}],
        "20260624": [{"ts_code": "600001.SH", "close": 11.0, "pct_chg": 10.0},
                     {"ts_code": "600002.SH", "close": 19.0, "pct_chg": -5.0}],
        "20260625": [{"ts_code": "600001.SH", "close": 12.1, "pct_chg": 10.0},
                     {"ts_code": "600002.SH", "close": 19.0, "pct_chg": 0.0}],
        "20260626": [{"ts_code": "600001.SH", "close": 12.1, "pct_chg": 0.0},
                     {"ts_code": "600002.SH", "close": 17.1, "pct_chg": -10.0}],
    }
    from datetime import date as _date
    today = _date(2026, 6, 26)
    fn = _daily_fn_factory(by_date)

    out1 = backtest.run_backfill(now=today, daily_all_fn=fn, db_path=db)
    assert out1["filled"] == 2
    # 第二次 pending 应为空(candidate_outcomes 已有 → LEFT JOIN 排除)
    out2 = backtest.run_backfill(now=today, daily_all_fn=fn, db_path=db)
    assert out2["entries_scanned"] == 0
    assert out2["filled"] == 0

    outcomes = store.list_outcomes(db_path=db)
    assert len(outcomes) == 2   # 未重复行(UNIQUE(entry_date,code) 生效)


# —— pending_backfill_entries:只返回 >=3 交易日已过的候选 ——————————————————

def test_pending_backfill_entries_excludes_too_recent(db):
    # entry_date=2026-06-25(周四)→ 交易日序列:06-25(D1)/06-26(D2,周五)/
    # 06-29(D3,周一)/06-30(D4,周二)。
    entry_date = "2026-06-25"
    _seed_candidates(db, entry_date)
    from datetime import date as _date
    # today = entry_date 当天(D1)→ 未满 4 → 不应出现
    pending_d1 = store.pending_backfill_entries(_date(2026, 6, 25), min_trade_days=4, db_path=db)
    assert pending_d1 == []
    # today = D3(06-29)→ 仍不足 4 → 不应出现
    pending_d3 = store.pending_backfill_entries(_date(2026, 6, 29), min_trade_days=4, db_path=db)
    assert pending_d3 == []
    # today = D4(06-30)→ 满足 >=4 → 应出现
    pending_d4 = store.pending_backfill_entries(_date(2026, 6, 30), min_trade_days=4, db_path=db)
    assert len(pending_d4) == 2


# —— 重启/错过窗口场景:次日 tick 自动补齐 ——————————————————————————————

def test_pending_backfill_catches_up_after_missed_window(db):
    """模拟'昨天该回填但服务重启漏了',今天 tick 应仍能扫到并补齐(扫描式天然补漏)。"""
    entry_date = "2026-06-23"
    _seed_candidates(db, entry_date)
    from datetime import date as _date
    # 假设服务在 06-26(D4)该回填时重启漏了,直到 06-30(周二)才又跑起来
    pending_late = store.pending_backfill_entries(_date(2026, 6, 30), min_trade_days=4, db_path=db)
    assert len(pending_late) == 2   # 仍能扫到(未回填、已过 >=4 交易日)


# —— 缺某日/某票 daily → 该票跳过、其余照落,不崩 ——————————————————————————

def test_run_backfill_missing_data_for_one_code_skips_only_that(db):
    entry_date = "2026-06-23"
    _seed_candidates(db, entry_date)
    by_date = {
        "20260623": [{"ts_code": "600001.SH", "close": 10.0, "pct_chg": 0.0},
                     {"ts_code": "600002.SH", "close": 20.0, "pct_chg": 0.0}],
        "20260624": [{"ts_code": "600001.SH", "close": 11.0, "pct_chg": 10.0}],  # 600002 缺
        "20260625": [{"ts_code": "600001.SH", "close": 12.1, "pct_chg": 10.0},
                     {"ts_code": "600002.SH", "close": 19.0, "pct_chg": 0.0}],
        "20260626": [{"ts_code": "600001.SH", "close": 12.1, "pct_chg": 0.0},
                     {"ts_code": "600002.SH", "close": 17.1, "pct_chg": -10.0}],
    }
    from datetime import date as _date
    today = _date(2026, 6, 26)
    out = backtest.run_backfill(now=today, daily_all_fn=_daily_fn_factory(by_date), db_path=db)
    assert out["filled"] == 1     # 只有 600001 落
    assert out["skipped"] == 1    # 600002 缺一天数据,跳过不崩

    outcomes = store.list_outcomes(db_path=db)
    codes = [o["code"] for o in outcomes]
    assert codes == ["600001"]


def test_run_backfill_daily_all_fail_returns_zero_not_crash(db):
    """无 token(daily_all 全失败)→ 回填 0 行不崩。"""
    entry_date = "2026-06-23"
    _seed_candidates(db, entry_date)

    def _all_fail(td):
        return TushareResult.fail("token 缺失")

    from datetime import date as _date
    today = _date(2026, 6, 26)
    out = backtest.run_backfill(now=today, daily_all_fn=_all_fail, db_path=db)
    assert out["filled"] == 0
    assert store.list_outcomes(db_path=db) == []


# —— analysis_verdicts:trade_date 取所属候选日 / ON CONFLICT DO UPDATE ——————————

def test_upsert_analysis_verdict_overwrites_latest(db):
    store.upsert_analysis_verdict("2026-06-23", "600001", "可进", db_path=db)
    assert store.get_verdict("2026-06-23", "600001", db_path=db) == "可进"
    # 覆盖为最新一次深判(非保留最早)
    store.upsert_analysis_verdict("2026-06-23", "600001", "不进", db_path=db)
    assert store.get_verdict("2026-06-23", "600001", db_path=db) == "不进"


def test_candidate_entry_date_of_finds_owning_candidate_date(db):
    """深判 T+1/T+2 才点时 latest_candidate_date 已滚动;candidate_entry_date_of 仍应
    取该 code 实际所属的候选日,不是 latest。"""
    _seed_candidates(db, "2026-06-23")
    # 模拟第二天(06-24)又刷新了一批新候选(不含 600001),latest 滚到 06-24
    store.upsert_candidates("2026-06-24", [
        {"rank": 1, "name": "票C", "code": "600099", "sector": "—", "tag": "站上均线",
         "price": 5.0, "chg": "+1.00%", "volMultiple": "1.6x", "volPct": 50,
         "flow": "+0.10亿", "turnover": "2.0%", "warn": None},
    ], db_path=db)
    assert store.latest_candidate_date(db_path=db) == "2026-06-24"
    # 600001 仍应能查到它真正所属的候选日 06-23(非 latest 的 06-24)
    assert store.candidate_entry_date_of("600001", db_path=db) == "2026-06-23"
    # 从未出现过的 code → None
    assert store.candidate_entry_date_of("999999", db_path=db) is None


def test_backfill_joins_verdict_when_present(db):
    """回填时 join analysis_verdicts,verdict 非空正确带出;未深判 → None。"""
    entry_date = "2026-06-23"
    _seed_candidates(db, entry_date)
    store.upsert_analysis_verdict(entry_date, "600001", "可进", db_path=db)
    by_date = {
        "20260623": [{"ts_code": "600001.SH", "close": 10.0, "pct_chg": 0.0},
                     {"ts_code": "600002.SH", "close": 20.0, "pct_chg": 0.0}],
        "20260624": [{"ts_code": "600001.SH", "close": 11.0, "pct_chg": 10.0},
                     {"ts_code": "600002.SH", "close": 19.0, "pct_chg": -5.0}],
        "20260625": [{"ts_code": "600001.SH", "close": 12.1, "pct_chg": 10.0},
                     {"ts_code": "600002.SH", "close": 19.0, "pct_chg": 0.0}],
        "20260626": [{"ts_code": "600001.SH", "close": 12.1, "pct_chg": 0.0},
                     {"ts_code": "600002.SH", "close": 17.1, "pct_chg": -10.0}],
    }
    from datetime import date as _date
    today = _date(2026, 6, 26)
    backtest.run_backfill(now=today, daily_all_fn=_daily_fn_factory(by_date), db_path=db)

    outcomes = {o["code"]: o for o in store.list_outcomes(db_path=db)}
    assert outcomes["600001"]["verdict"] == "可进"
    assert outcomes["600002"]["verdict"] is None   # 未深判
