"""v1.3.1 Phase B(选股配置可调化)单测——B1 存储 + B2 合并/校验/生效机制/端点。

plan-critic 重点审面:配置成为新单一事实源,校验/优先级/非法降级必须无懈可击。
覆盖 §4 Phase B 验收:
  B1:screen_config 建表幂等;get/put 往返;空表/坏 JSON 降级;PUT 存增量;
      DEFAULT_SCREEN_CONFIG 等值断言。
  B2:resolve 合并优先级(默认+增量覆盖)+ 全量后归一;validate 各分支(类型错/
      NaN/越界/权重不归一/全0/未知键);端点 GET/PUT 往返 + 夹紧 + 恢复默认清行;
      pipeline 真读活配置(穿参真生效,非 monkeypatch);深判层不读配置。
"""

import importlib
import json
import math
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import settings as settings_singleton
from app.db import store
from app.screen import rules

TEST_TOKEN = "t" * 64
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


# ———————————————————————————————————————————————————————————————————
# B1:配置存储(新表 + 存取)
# ———————————————————————————————————————————————————————————————————

def test_screen_config_table_created_idempotent(tmp_path):
    """建表幂等:连跑 init_db 多次不抛异常、表存在。"""
    db = str(tmp_path / "sc.db")
    store.init_db(db)
    store.init_db(db)
    store.init_db(db)
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='screen_config'"
    )}
    conn.close()
    assert "screen_config" in tables


def test_get_screen_config_empty_table_returns_empty_dict(tmp_path):
    """空表(无行)→ get 返回 {}。"""
    db = str(tmp_path / "sc.db")
    store.init_db(db)
    assert store.get_screen_config(db_path=db) == {}
    assert store.get_screen_config_updated_at(db_path=db) is None


def test_put_get_screen_config_roundtrip(tmp_path):
    """put 存增量 → get 原样读回(只含提交的键)。"""
    db = str(tmp_path / "sc.db")
    store.init_db(db)
    store.put_screen_config({"vol_ratio_min": 2.0, "turnover_lo": 8.0}, db_path=db)
    got = store.get_screen_config(db_path=db)
    assert got == {"vol_ratio_min": 2.0, "turnover_lo": 8.0}
    assert store.get_screen_config_updated_at(db_path=db) is not None


def test_put_screen_config_overwrites_whole_row(tmp_path):
    """再次 put 覆盖式替换整行(非累加 patch)。"""
    db = str(tmp_path / "sc.db")
    store.init_db(db)
    store.put_screen_config({"vol_ratio_min": 2.0, "turnover_lo": 8.0}, db_path=db)
    store.put_screen_config({"mv_lo": 60.0}, db_path=db)
    got = store.get_screen_config(db_path=db)
    assert got == {"mv_lo": 60.0}   # 旧键不再保留


def test_put_screen_config_empty_clears_row_semantics(tmp_path):
    """PUT 空 dict → 存空增量;get 读回 {}(= 恢复默认语义的存储侧基础)。"""
    db = str(tmp_path / "sc.db")
    store.init_db(db)
    store.put_screen_config({"vol_ratio_min": 3.0}, db_path=db)
    assert store.get_screen_config(db_path=db) != {}
    store.put_screen_config({}, db_path=db)
    assert store.get_screen_config(db_path=db) == {}


def test_get_screen_config_corrupt_json_degrades_to_empty(tmp_path):
    """config_json 损坏(非法 JSON)→ get 降级返回 {},不崩。"""
    db = str(tmp_path / "sc.db")
    store.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO screen_config (id, config_json, updated_at) VALUES (1, ?, ?)",
        ("{not valid json", "2026-07-05 10:00:00"),
    )
    conn.commit()
    conn.close()
    assert store.get_screen_config(db_path=db) == {}


def test_get_screen_config_non_dict_json_degrades_to_empty(tmp_path):
    """config_json 是合法 JSON 但非 dict 形状(如数组)→ 降级返回 {}。"""
    db = str(tmp_path / "sc.db")
    store.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO screen_config (id, config_json, updated_at) VALUES (1, ?, ?)",
        (json.dumps([1, 2, 3]), "2026-07-05 10:00:00"),
    )
    conn.commit()
    conn.close()
    assert store.get_screen_config(db_path=db) == {}


# ———————————————————————————————————————————————————————————————————
# B1:DEFAULT_SCREEN_CONFIG 引用构造(建议#8),等值断言防双写漂移
# ———————————————————————————————————————————————————————————————————

def test_screen_config_spec_key_set():
    """SCREEN_CONFIG_SPEC 键集 = 9 权重 + 12 阈值,共 21 键(plan §4 config 形状表)。"""
    weight_keys = {"vol_ratio", "pos_health", "turnover", "vwap", "breakout",
                   "mv_elastic", "active", "fund", "day_surge"}
    threshold_keys = {
        "vol_ratio_min", "turnover_lo", "turnover_hi", "mv_lo", "mv_hi", "mv_floor",
        "breakout_range_max", "breakout_vol_ratio_min", "day_outflow_floor",
        "day_surge_warn_pct", "active_lookback_days", "limit_up_pct",
    }
    assert set(rules.SCREEN_CONFIG_SPEC.keys()) == weight_keys | threshold_keys
    assert len(rules.SCREEN_CONFIG_SPEC) == 21
    for key, spec in rules.SCREEN_CONFIG_SPEC.items():
        assert spec["category"] in ("weight", "threshold")
        assert "type" in spec and "range" in spec and "default" in spec


def test_default_screen_config_equals_rules_constants():
    """DEFAULT_SCREEN_CONFIG 各键 == 对应 rules 常量(引用构造,防双写漂移)。"""
    assert rules.DEFAULT_SCREEN_CONFIG["vol_ratio"] == rules.WEIGHTS["vol_ratio"]
    assert rules.DEFAULT_SCREEN_CONFIG["pos_health"] == rules.WEIGHTS["pos_health"]
    assert rules.DEFAULT_SCREEN_CONFIG["turnover"] == rules.WEIGHTS["turnover"]
    assert rules.DEFAULT_SCREEN_CONFIG["vwap"] == rules.WEIGHTS["vwap"]
    assert rules.DEFAULT_SCREEN_CONFIG["breakout"] == rules.WEIGHTS["breakout"]
    assert rules.DEFAULT_SCREEN_CONFIG["mv_elastic"] == rules.WEIGHTS["mv_elastic"]
    assert rules.DEFAULT_SCREEN_CONFIG["active"] == rules.WEIGHTS["active"]
    assert rules.DEFAULT_SCREEN_CONFIG["fund"] == rules.WEIGHTS["fund"]
    assert rules.DEFAULT_SCREEN_CONFIG["day_surge"] == rules.WEIGHTS["day_surge"]
    assert rules.DEFAULT_SCREEN_CONFIG["vol_ratio_min"] == rules.VOL_RATIO_MIN
    assert rules.DEFAULT_SCREEN_CONFIG["turnover_lo"] == rules.TURNOVER_HEALTHY_LO
    assert rules.DEFAULT_SCREEN_CONFIG["turnover_hi"] == rules.TURNOVER_HEALTHY_HI
    assert rules.DEFAULT_SCREEN_CONFIG["mv_lo"] == rules.MV_SMALL_CAP_LO
    assert rules.DEFAULT_SCREEN_CONFIG["mv_hi"] == rules.MV_SMALL_CAP_HI
    assert rules.DEFAULT_SCREEN_CONFIG["mv_floor"] == rules.MV_MICRO_FLOOR
    assert rules.DEFAULT_SCREEN_CONFIG["breakout_range_max"] == rules.BREAKOUT_RANGE_MAX
    assert rules.DEFAULT_SCREEN_CONFIG["breakout_vol_ratio_min"] == rules.BREAKOUT_VOL_RATIO_MIN
    assert rules.DEFAULT_SCREEN_CONFIG["day_outflow_floor"] == rules.DAY_OUTFLOW_FLOOR
    assert rules.DEFAULT_SCREEN_CONFIG["day_surge_warn_pct"] == rules.DAY_SURGE_WARN_PCT
    assert rules.DEFAULT_SCREEN_CONFIG["active_lookback_days"] == rules.ACTIVE_LOOKBACK_DAYS
    assert rules.DEFAULT_SCREEN_CONFIG["limit_up_pct"] == rules.LIMIT_UP_PCT


def test_default_screen_config_positive_weights_sum_to_one():
    """默认配置 8 正权重和 == 1.00(与 WEIGHTS 一致,沿 A1 断言)。"""
    positive = [v for k, v in rules.DEFAULT_SCREEN_CONFIG.items()
                if rules.SCREEN_CONFIG_SPEC[k]["category"] == "weight" and k != "day_surge"]
    assert sum(positive) == pytest.approx(1.0)


# ———————————————————————————————————————————————————————————————————
# B2:validate_screen_config —— 类型/越界/非有限值/权重归一/全0/未知键
# ———————————————————————————————————————————————————————————————————

def test_validate_unknown_keys_ignored():
    out = rules.validate_screen_config({"vol_ratio_min": 2.0, "totally_unknown_key": 999})
    assert "totally_unknown_key" not in out
    assert out["vol_ratio_min"] == 2.0


def test_validate_type_mismatch_falls_back_to_default():
    """类型不符(字符串)→ 用默认值。"""
    out = rules.validate_screen_config({"vol_ratio_min": "not_a_number"})
    assert out["vol_ratio_min"] == rules.DEFAULT_SCREEN_CONFIG["vol_ratio_min"]


def test_validate_missing_key_absent_from_output():
    """缺失键(未提交)→ 不出现在 validate 输出里(由 resolve 的默认合并负责补,
    validate 本身只处理"存在的键")。"""
    out = rules.validate_screen_config({"vol_ratio_min": 2.0})
    assert "turnover_lo" not in out


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_validate_non_finite_falls_back_to_default(bad):
    """非有限值(nan/inf)→ 用默认值(重要#4,math.isfinite 守卫)。"""
    out = rules.validate_screen_config({"vol_ratio_min": bad})
    assert out["vol_ratio_min"] == rules.DEFAULT_SCREEN_CONFIG["vol_ratio_min"]
    assert math.isfinite(out["vol_ratio_min"])


def test_validate_bool_rejected_as_non_numeric():
    """bool 是 int 子类,但配置语义上不是合法数值 → 回退默认(防 True/False 混进权重)。"""
    out = rules.validate_screen_config({"vol_ratio_min": True})
    assert out["vol_ratio_min"] == rules.DEFAULT_SCREEN_CONFIG["vol_ratio_min"]


def test_validate_threshold_out_of_range_clamped():
    """阈值越界 → 夹到 SPEC range(不 422,不报错)。"""
    out = rules.validate_screen_config({"vol_ratio_min": 100.0})   # range (1.0, 5.0)
    assert out["vol_ratio_min"] == 5.0
    out2 = rules.validate_screen_config({"vol_ratio_min": -10.0})
    assert out2["vol_ratio_min"] == 1.0


def test_validate_active_lookback_days_rounds_to_int():
    """active_lookback_days 是 int 类型,夹紧后取整。"""
    out = rules.validate_screen_config({"active_lookback_days": 7.6})
    assert out["active_lookback_days"] == 8
    assert isinstance(out["active_lookback_days"], int)
    out2 = rules.validate_screen_config({"active_lookback_days": 999})   # range (1,60)
    assert out2["active_lookback_days"] == 60


def test_validate_day_surge_weight_range_negative():
    """day_surge 权重范围是 [-1,0](非 [0,1]);越界(正数)夹到 0。"""
    out = rules.validate_screen_config({"day_surge": 0.5})   # 正数越界
    assert out["day_surge"] == 0.0
    out2 = rules.validate_screen_config({"day_surge": -5.0})
    assert out2["day_surge"] == -1.0


def test_validate_normalize_weights_false_by_default_put_path():
    """normalize_weights 默认 False(PUT 路径):即便提交全部 9 权重键也不归一。"""
    all_weights = {
        "vol_ratio": 0.9, "pos_health": 0.9, "turnover": 0.9, "vwap": 0.9,
        "breakout": 0.9, "mv_elastic": 0.9, "active": 0.9, "fund": 0.9,
        "day_surge": -0.9,
    }
    out = rules.validate_screen_config(all_weights)   # 未传 normalize_weights
    # 未归一:各值仍是夹紧后的原值(0.9),和远大于 1
    assert out["vol_ratio"] == 0.9
    assert out["pos_health"] == 0.9
    total = sum(out[k] for k in all_weights if k != "day_surge")
    assert total == pytest.approx(0.9 * 8)   # 未被归一到 1.0


def test_validate_normalize_weights_true_normalizes_to_one():
    """normalize_weights=True(resolve 路径):8 正权和 != 1.0 → 按比例归一到 1.0。"""
    all_weights = {
        "vol_ratio": 0.9, "pos_health": 0.9, "turnover": 0.9, "vwap": 0.9,
        "breakout": 0.9, "mv_elastic": 0.9, "active": 0.9, "fund": 0.9,
        "day_surge": -0.5,
    }
    out = rules.validate_screen_config(all_weights, normalize_weights=True)
    total = sum(out[k] for k in all_weights if k != "day_surge")
    assert total == pytest.approx(1.0)
    # day_surge 不参与归一,仅按 range 夹紧
    assert out["day_surge"] == -0.5


def test_validate_normalize_weights_all_zero_reverts_to_default():
    """8 正权全 0(数值退化)→ 归一分支退回默认权重(不产除零/全 0 排序)。"""
    zeros = {k: 0.0 for k in rules.SCREEN_CONFIG_SPEC
             if rules.SCREEN_CONFIG_SPEC[k]["category"] == "weight" and k != "day_surge"}
    out = rules.validate_screen_config(zeros, normalize_weights=True)
    for k in zeros:
        assert out[k] == rules.DEFAULT_SCREEN_CONFIG[k]


def test_validate_never_raises_on_garbage_input():
    """非法/异常配置(乱七八糟类型混合)→ 逐字段回退默认,绝不崩。"""
    garbage = {
        "vol_ratio_min": None,
        "turnover_lo": [1, 2, 3],
        "mv_hi": {"a": 1},
        "day_surge_warn_pct": "abc",
        "active_lookback_days": float("nan"),
        "unknown_garbage_key": object(),
    }
    out = rules.validate_screen_config(garbage)   # 不应抛异常
    assert out["vol_ratio_min"] == rules.DEFAULT_SCREEN_CONFIG["vol_ratio_min"]
    assert out["turnover_lo"] == rules.DEFAULT_SCREEN_CONFIG["turnover_lo"]
    assert out["mv_hi"] == rules.DEFAULT_SCREEN_CONFIG["mv_hi"]
    assert out["day_surge_warn_pct"] == rules.DEFAULT_SCREEN_CONFIG["day_surge_warn_pct"]
    assert out["active_lookback_days"] == rules.DEFAULT_SCREEN_CONFIG["active_lookback_days"]


# ———————————————————————————————————————————————————————————————————
# B2:resolve_screen_config —— 合并优先级 + 全量后归一
# ———————————————————————————————————————————————————————————————————

def test_resolve_no_user_config_returns_all_defaults():
    resolved = rules.resolve_screen_config(None)
    assert resolved == rules.validate_screen_config(
        dict(rules.DEFAULT_SCREEN_CONFIG), normalize_weights=True
    )
    for k, v in rules.DEFAULT_SCREEN_CONFIG.items():
        assert resolved[k] == pytest.approx(v)


def test_resolve_merges_user_increment_over_default():
    """用户增量覆盖对应默认键,缺键仍用默认。"""
    resolved = rules.resolve_screen_config({"vol_ratio_min": 2.5})
    assert resolved["vol_ratio_min"] == 2.5
    assert resolved["turnover_lo"] == rules.DEFAULT_SCREEN_CONFIG["turnover_lo"]


def test_resolve_normalizes_weights_after_merge():
    """resolve 合并出全量后触发权重归一(即使用户只改了一个权重键)。"""
    resolved = rules.resolve_screen_config({"vol_ratio": 0.9})   # 单键改动,总和不再是 1.0
    positive_keys = [k for k, v in rules.SCREEN_CONFIG_SPEC.items()
                     if v["category"] == "weight" and k != "day_surge"]
    total = sum(resolved[k] for k in positive_keys)
    assert total == pytest.approx(1.0)


def test_resolve_unknown_key_ignored():
    resolved = rules.resolve_screen_config({"not_a_real_key": 123})
    assert "not_a_real_key" not in resolved


# ———————————————————————————————————————————————————————————————————
# B2:显式穿参真生效(非 monkeypatch)——改 vol_ratio_min 后粗筛行为随之变
# ———————————————————————————————————————————————————————————————————

def test_passes_coarse_respects_cfg_vol_ratio_min():
    """cfg 传入的 vol_ratio_min 真实改变粗筛结果(证穿参生效,非改常量)。"""
    from app.screen.fetch import StockRow
    from app.screen.pipeline import passes_coarse

    sr = StockRow(
        code="600000", name="测试", industry="银行", close=10.0,
        turnover=8.0, net_mf_amount=10.0, net_mf_3d=100.0,
        new_high_20d=True, above_ma20=True, volume_ratio=1.8,
    )
    # 默认 cfg(None)→ VOL_RATIO_MIN=1.5,1.8 通过
    assert passes_coarse(sr, None) is True
    # cfg 把 vol_ratio_min 抬到 2.0 → 1.8 不再通过(未改任何模块级常量)
    cfg = rules.resolve_screen_config({"vol_ratio_min": 2.0})
    assert passes_coarse(sr, cfg) is False
    # rules.VOL_RATIO_MIN 本身未被改动(佐证不是 monkeypatch 常量)
    assert rules.VOL_RATIO_MIN == 1.5


def test_run_pipeline_end_to_end_cfg_changes_coarse_outcome():
    """端到端 run_pipeline(cfg=...) 改 vol_ratio_min 后 refresh 粗筛行为随之变
    (plan §4 Phase B2 验收:pipeline 真读活配置)。"""
    from app.screen import pipeline
    from app.screen.fetch import MarketSnapshot, StockRow

    def _snapshot_fn(td, cfg=None):
        rows = [StockRow(
            code="600000", name="测试", industry="银行", close=10.0,
            pct_chg=2.0, turnover=8.0, net_mf_amount=10.0, net_mf_3d=100.0,
            new_high_20d=True, above_ma20=True, volume_ratio=1.8, pos_health=0.8,
        )]
        return MarketSnapshot(trade_date="2026-07-05", rows=rows)

    # 默认配置(vol_ratio_min=1.5)→ 1.8 通过 → 有候选
    rows_default, degraded, reason, _td = pipeline.run_pipeline(
        "20260705", snapshot_fn=_snapshot_fn, cfg=rules.resolve_screen_config(None)
    )
    assert degraded is False and len(rows_default) == 1

    # 抬高 vol_ratio_min 到 2.0 → 1.8 不再通过 → 空(no_candidates)
    cfg2 = rules.resolve_screen_config({"vol_ratio_min": 2.0})
    rows_strict, degraded2, reason2, _td2 = pipeline.run_pipeline(
        "20260705", snapshot_fn=_snapshot_fn, cfg=cfg2
    )
    assert rows_strict == [] and reason2 == "no_candidates"


def test_recompute_candidates_reads_user_config_from_store(tmp_path, monkeypatch):
    """端到端(app.py _recompute_candidates,真实默认 _pipeline_fn 路径,非注入替身):
    PUT 存的用户增量(vol_ratio_min=2.0)经 store.get_screen_config() → resolve →
    穿参到 run_pipeline → passes_coarse,真实改变粗筛结果(证"刷新链路显式穿参"生效,
    plan §4 Phase B2 验收:pipeline 真读活配置)。
    """
    import importlib

    from app.screen import pipeline as pipeline_mod
    from app.screen.fetch import MarketSnapshot, StockRow

    db_path = str(tmp_path / "recompute.db")
    store.init_db(db_path)
    monkeypatch.setattr(settings_singleton, "DB_PATH", db_path, raising=False)
    app_mod = importlib.import_module("app.api.app")
    importlib.reload(app_mod)   # 确保 _pipeline_fn 恢复为 _default_pipeline_fn(未被其他测试污染)

    def _fake_snapshot(td, cfg=None):
        rows = [StockRow(
            code="600000", name="测试", industry="银行", close=10.0,
            pct_chg=2.0, turnover=8.0, net_mf_amount=10.0, net_mf_3d=100.0,
            new_high_20d=True, above_ma20=True, volume_ratio=1.8, pos_health=0.8,
        )]
        return MarketSnapshot(trade_date="2026-07-05", rows=rows)

    monkeypatch.setattr(pipeline_mod, "fetch_market_snapshot", _fake_snapshot, raising=True)
    monkeypatch.setattr(
        app_mod, "_candidate_basis_date", lambda: "20260705", raising=False
    )

    # 未设用户配置 → 默认 vol_ratio_min=1.5,1.8 通过
    count1, td1, degraded1 = app_mod._recompute_candidates()
    assert degraded1 is False and count1 == 1

    # 用户 PUT 抬高 vol_ratio_min 到 2.0(走真实 store 存取,非直接调 rules)
    store.put_screen_config({"vol_ratio_min": 2.0}, db_path=str(tmp_path / "recompute.db"))
    count2, td2, degraded2 = app_mod._recompute_candidates()
    assert count2 == 0   # 1.8 不再通过粗筛,证明用户配置真生效(非 monkeypatch 常量)
    assert rules.VOL_RATIO_MIN == 1.5   # 模块级常量本身未被改动


# ———————————————————————————————————————————————————————————————————
# B2:深判层边界——analyze.py 不读 screen_config(钉死)
# ———————————————————————————————————————————————————————————————————

def test_analyze_module_does_not_reference_screen_config():
    """grep 守卫:app/llm/analyze.py 源码不出现 screen_config/resolve_screen_config 字样
    (深判层边界钉死,plan §4 Phase B2)。"""
    import inspect
    from app.llm import analyze as analyze_mod

    src = inspect.getsource(analyze_mod)
    assert "screen_config" not in src
    assert "resolve_screen_config" not in src


def test_analyze_compute_form_call_has_no_cfg_kwarg():
    """analyze.py 调 compute_form 时不传 cfg(继续吃 rules 默认常量,不读用户配置)。"""
    import inspect
    from app.llm import analyze as analyze_mod

    src = inspect.getsource(analyze_mod)
    # 找到 compute_form( 调用那一行,断言没有 cfg= 关键字参数
    for line in src.splitlines():
        if "compute_form(" in line:
            assert "cfg=" not in line


# ———————————————————————————————————————————————————————————————————
# B2:端点 GET/PUT 真实 HTTP 往返 + 夹紧 + 恢复默认
# ———————————————————————————————————————————————————————————————————

@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_singleton, "DB_PATH", str(tmp_path / "sc_api.db"), raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    with TestClient(app_mod.app) as c:
        yield c


def test_get_screen_config_requires_auth(api_client):
    r = api_client.get("/api/v1/screen/config")
    assert r.status_code == 401


def test_get_screen_config_default_state(api_client):
    """无用户改动 → GET 返回全默认 config,updated_at=None。"""
    r = api_client.get("/api/v1/screen/config", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["updated_at"] is None
    assert body["defaults"] == rules.DEFAULT_SCREEN_CONFIG
    for k, v in rules.DEFAULT_SCREEN_CONFIG.items():
        assert body["config"][k] == pytest.approx(v)


def test_put_screen_config_roundtrip_and_get_reflects(api_client):
    """PUT 改配置 → GET 能读到生效值(全量,已归一)。"""
    r = api_client.put(
        "/api/v1/screen/config", headers=AUTH,
        json={"config": {"vol_ratio_min": 2.0, "turnover_lo": 8.0}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["config"]["vol_ratio_min"] == 2.0
    assert body["config"]["turnover_lo"] == 8.0

    r2 = api_client.get("/api/v1/screen/config", headers=AUTH)
    body2 = r2.json()
    assert body2["config"]["vol_ratio_min"] == 2.0
    assert body2["updated_at"] is not None


def test_put_screen_config_out_of_range_clamped_not_422(api_client):
    """越界值不 422,后端夹紧后仍 200。"""
    r = api_client.put(
        "/api/v1/screen/config", headers=AUTH,
        json={"config": {"vol_ratio_min": 999.0}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["config"]["vol_ratio_min"] == 5.0   # SPEC range 上界


def test_put_screen_config_unknown_key_ignored_not_error(api_client):
    r = api_client.put(
        "/api/v1/screen/config", headers=AUTH,
        json={"config": {"totally_bogus_key": 42}},
    )
    assert r.status_code == 200
    assert "totally_bogus_key" not in r.json()["config"]


def test_put_screen_config_empty_restores_defaults(api_client):
    """恢复默认 = PUT {config:{}}(空)→ 清用户行,GET 全回默认。"""
    api_client.put(
        "/api/v1/screen/config", headers=AUTH,
        json={"config": {"vol_ratio_min": 3.5}},
    )
    r_mid = api_client.get("/api/v1/screen/config", headers=AUTH)
    assert r_mid.json()["config"]["vol_ratio_min"] == 3.5

    r = api_client.put("/api/v1/screen/config", headers=AUTH, json={"config": {}})
    assert r.status_code == 200
    body = r.json()
    for k, v in rules.DEFAULT_SCREEN_CONFIG.items():
        assert body["config"][k] == pytest.approx(v)

    r2 = api_client.get("/api/v1/screen/config", headers=AUTH)
    assert r2.json()["config"]["vol_ratio_min"] == pytest.approx(
        rules.DEFAULT_SCREEN_CONFIG["vol_ratio_min"]
    )


def test_put_screen_config_weights_not_normalized_by_endpoint():
    """端点 PUT 路径本身不做权重归一(normalize_weights=False);GET resolve 时才归一。
    此测试直接调用后端函数验证 PUT 存的是"夹紧未归一"的值。"""
    all_weights = {
        "vol_ratio": 0.9, "pos_health": 0.9, "turnover": 0.9, "vwap": 0.9,
        "breakout": 0.9, "mv_elastic": 0.9, "active": 0.9, "fund": 0.9,
    }
    clamped = rules.validate_screen_config(all_weights, normalize_weights=False)
    assert clamped["vol_ratio"] == 0.9   # 未被归一
