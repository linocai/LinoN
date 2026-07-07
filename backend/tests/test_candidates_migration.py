"""阶段3.1:candidates 表加 score 列(项目第二次真 migration,高危区)单测。
v1.3.1 A2.5:candidates 表再加 warn_level 列(项目第四次真 migration,高危区)单测。

覆盖 plan §4.3 Phase C 验收5(复用阶段3 迁移契约姿势 test_review_migration.py):
  ① 对已存在旧 candidates 表(无 score 列)跑 init_db → _ensure_candidates_columns 加列成功;
  ② 连跑 init_db 两/三次不抛 duplicate column、不丢历史行、不改既有值(模拟 ECS 反复重启);
  ③ 旧行 score=NULL 经 list_candidates 回读省略键,不崩(v1.4.1 Phase C 起改省略键,
     不再兜底 0,见 tests 内注释与 plan §4.2 🔵9);
  ④ upsert_candidates → list_candidates round-trip 带 score 一致;
  ⑤ (见 test_screen.py)现有候选 upsert/list 回读断言同步更新为含 score 键;
  ⑥ pending_backfill_entries 回填逻辑未受影响(仍读 candidates 历史行、未 DROP)。

v1.3.1 A2.5 新增覆盖(plan §4.1 A2.5 验收,致命#1 门禁):
  ⑦ 对已存在旧 candidates 表(无 warn_level 列,含旧 score 列)跑 init_db 自动补列;
  ⑧ 旧行 warn_level=NULL 经 list_candidates 回读省略键(前向兼容,同 warn 惯例);
  ⑨ **穿透缓存回环测试**:pipeline 产 warnLevel="high"/"amber"/None →
     upsert_candidates 落库 → list_candidates 读回仍带 warnLevel(必须过缓存表往返,
     不是内存直测)——封死"候选缓存表断层"盲区,致命#1 的门禁。
"""

import sqlite3

import pytest

from app.db import store


def _cols(db_path, table="candidates"):
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    conn.close()
    return cols


def _cand(rank, code, warn=None, score=None, warn_level=None):
    d = {
        "rank": rank, "name": f"票{code}", "code": code, "sector": "半导体",
        "tag": "放量突破", "price": 10.0 + rank, "chg": "+3.00%",
        "volMultiple": "2.8x", "volPct": 90, "flow": "+1.20亿",
        "turnover": "4.6%", "warn": warn,
    }
    if score is not None:
        d["score"] = score
    if warn_level is not None:
        d["warnLevel"] = warn_level
    return d


# —— ①:旧库(无 score 列)自动补列 ————————————————————————————————————

def test_old_candidates_table_without_score_gets_migrated(tmp_path):
    db = str(tmp_path / "old_cand.db")
    # 手工建一个"旧版" candidates 表(阶段2 的 13 列,无 score)+ 种一行历史候选
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE candidates (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date   TEXT    NOT NULL,
            rank         INTEGER NOT NULL,
            code         TEXT    NOT NULL,
            name         TEXT    NOT NULL,
            sector       TEXT, tag TEXT, price REAL, chg TEXT,
            vol_multiple TEXT, vol_pct INTEGER, flow TEXT, turnover TEXT, warn TEXT,
            created_at   TEXT    NOT NULL,
            UNIQUE(trade_date, code)
        )
    """)
    conn.execute(
        """INSERT INTO candidates
           (trade_date, rank, code, name, sector, tag, price, chg,
            vol_multiple, vol_pct, flow, turnover, warn, created_at)
           VALUES ('2026-06-24', 1, '600000', '历史候选', '银行', '放量突破',
                   10.0, '+3.00%', '2.8x', 90, '+1.20亿', '4.6%', NULL,
                   '2026-06-24 15:35:00')"""
    )
    conn.commit(); conn.close()
    assert "score" not in _cols(db)

    # init_db 自动补列
    store.init_db(db)
    assert "score" in _cols(db)

    # 历史行无损;新列为 NULL
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM candidates WHERE code='600000'").fetchone()
    conn.close()
    assert row["code"] == "600000" and row["name"] == "历史候选"
    assert row["score"] is None


# —— ②:幂等(连跑 init_db 多次不抛 duplicate column、不丢行、不改值)——————————

def test_init_db_idempotent_no_duplicate_score(tmp_path):
    db = str(tmp_path / "idem_cand.db")
    store.init_db(db)
    assert "score" in _cols(db)
    # 种候选(经 upsert)
    store.upsert_candidates("2026-06-24", [_cand(1, "600000", score=100),
                                           _cand(2, "600001", score=42)], db_path=db)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    before = [dict(r) for r in conn.execute("SELECT * FROM candidates ORDER BY id")]
    conn.close()

    # 再跑 init_db 两次(模拟服务反复重启)——不抛 duplicate column
    store.init_db(db)
    store.init_db(db)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    after = [dict(r) for r in conn.execute("SELECT * FROM candidates ORDER BY id")]
    conn.close()
    # 行数不变、列值不变
    assert len(after) == len(before) == 2
    assert after == before
    # 列仍只一份 score(无重复列)
    assert _cols(db).count("score") == 1


# —— ③:旧行 score=NULL 经 list_candidates 回读省略键(v1.4.1 Phase C 🔵9)——————————

def test_null_score_reads_back_omits_key(tmp_path):
    """v1.4.1 Phase C 起 score 语义变绝对质量分,0 是合法最低分——NULL(迁移前旧行)
    回读改省略键,不再兜底 0(兜 0 会与合法 0 分撞车,plan §4.2 🔵9)。"""
    db = str(tmp_path / "null_score.db")
    store.init_db(db)
    # 直接底层插一行 score=NULL(模拟迁移前写入的旧行)
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT INTO candidates
           (trade_date, rank, code, name, sector, tag, price, chg,
            vol_multiple, vol_pct, flow, turnover, warn, score, created_at)
           VALUES ('2026-06-24', 1, '600000', '旧行', '银行', '放量突破',
                   10.0, '+3.00%', '2.8x', 90, '+1.20亿', '4.6%', NULL, NULL,
                   '2026-06-24 15:35:00')"""
    )
    conn.commit(); conn.close()

    got = store.list_candidates("2026-06-24", db_path=db)
    assert len(got) == 1
    assert "score" not in got[0]   # NULL → 省略键,不兜底 0(与合法 0 分区分)


# —— ④:round-trip 带 score 一致 ————————————————————————————————————

def test_upsert_list_roundtrip_with_score(tmp_path):
    db = str(tmp_path / "rt.db")
    store.init_db(db)
    store.upsert_candidates("2026-06-24", [_cand(1, "600000", score=100),
                                           _cand(2, "600001", score=55)], db_path=db)
    got = store.list_candidates("2026-06-24", db_path=db)
    assert [c["code"] for c in got] == ["600000", "600001"]
    assert got[0]["score"] == 100 and got[1]["score"] == 55
    # 缺省 score(pipeline 兜底)→ upsert 兜底 0
    store.upsert_candidates("2026-06-25", [_cand(1, "600002")], db_path=db)  # 无 score 键
    got2 = store.list_candidates("2026-06-25", db_path=db)
    assert got2[0]["score"] == 0


# —— ⑥:pending_backfill_entries 未受迁移影响(仍读 candidates 历史行,未 DROP)————

def test_pending_backfill_reads_historical_candidates_after_migration(tmp_path):
    """迁移(ALTER 加列)后 candidates 历史行仍在,回填扫描照常命中(证明未 DROP)。"""
    from datetime import date

    db = str(tmp_path / "backfill.db")
    store.init_db(db)
    # 种一批历史候选(entry_date 距 today 已过 >=4 交易日)
    store.upsert_candidates("2026-06-01", [_cand(1, "600000", score=100),
                                           _cand(2, "600001", score=50)], db_path=db)
    # 未回填(candidate_outcomes 无对应行)→ 应全部待回填
    pending = store.pending_backfill_entries(date(2026, 6, 30), db_path=db)
    codes = {p["code"] for p in pending}
    assert {"600000", "600001"} <= codes   # 历史行仍在,被扫描到


def test_pending_backfill_grep_guard_reads_candidates_not_drop():
    """grep 守卫:回填 SQL 仍是 LEFT JOIN candidates 历史行、init_db 未 DROP candidates。"""
    import inspect
    from app.db import store as store_mod

    src = inspect.getsource(store_mod.pending_backfill_entries)
    assert "FROM candidates c" in src            # 仍读 candidates 历史行
    assert "LEFT JOIN candidate_outcomes" in src
    # init_db / 迁移函数不执行 DROP TABLE(ALTER 保留历史,plan §4.1 否决方案②)。
    # 匹配 `DROP TABLE` SQL 语句(非注释里解释性的 "DROP" 字样)。
    import re
    init_src = inspect.getsource(store_mod.init_db)
    migrate_src = inspect.getsource(store_mod._ensure_candidates_columns)
    drop_stmt = re.compile(r"DROP\s+TABLE", re.IGNORECASE)
    assert not drop_stmt.search(init_src)         # init_db 不执行 DROP TABLE
    assert not drop_stmt.search(migrate_src)      # 迁移不 DROP TABLE,走 ALTER
    assert "ADD COLUMN score" in migrate_src      # 迁移方式 = ALTER ADD COLUMN
    assert "ADD COLUMN warn_level" in migrate_src  # v1.3.1 A2.5:第四次真 migration 同函数补


# ———————————————————————————————————————————————————————————————————
# v1.3.1 A2.5:candidates 表加 warn_level 列(项目第四次真 migration,致命#1)
# ———————————————————————————————————————————————————————————————————

# —— ⑦:旧库(有 score 列但无 warn_level 列)自动补列 ——————————————————————

def test_old_candidates_table_without_warn_level_gets_migrated(tmp_path):
    db = str(tmp_path / "old_cand_wl.db")
    # 手工建一个"阶段3.1 版" candidates 表(14 列,有 score 但无 warn_level)+ 种一行历史候选
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE candidates (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date   TEXT    NOT NULL,
            rank         INTEGER NOT NULL,
            code         TEXT    NOT NULL,
            name         TEXT    NOT NULL,
            sector       TEXT, tag TEXT, price REAL, chg TEXT,
            vol_multiple TEXT, vol_pct INTEGER, flow TEXT, turnover TEXT, warn TEXT,
            score        INTEGER,
            created_at   TEXT    NOT NULL,
            UNIQUE(trade_date, code)
        )
    """)
    conn.execute(
        """INSERT INTO candidates
           (trade_date, rank, code, name, sector, tag, price, chg,
            vol_multiple, vol_pct, flow, turnover, warn, score, created_at)
           VALUES ('2026-06-24', 1, '600000', '历史候选', '银行', '放量突破',
                   10.0, '+3.00%', '2.8x', 90, '+1.20亿', '4.6%', NULL, 100,
                   '2026-06-24 15:35:00')"""
    )
    conn.commit(); conn.close()
    assert "warn_level" not in _cols(db)

    # init_db 自动补列
    store.init_db(db)
    assert "warn_level" in _cols(db)
    assert "score" in _cols(db)   # 旧列仍在,未被 DROP 重建丢掉

    # 历史行无损;新列为 NULL
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM candidates WHERE code='600000'").fetchone()
    conn.close()
    assert row["code"] == "600000" and row["name"] == "历史候选"
    assert row["score"] == 100          # 旧值未被改动
    assert row["warn_level"] is None


# —— 幂等(连跑 init_db 多次不抛 duplicate column、不丢行、不改值)—————————————

def test_init_db_idempotent_no_duplicate_warn_level(tmp_path):
    db = str(tmp_path / "idem_wl.db")
    store.init_db(db)
    assert "warn_level" in _cols(db)
    store.upsert_candidates("2026-06-24", [
        _cand(1, "600000", score=100, warn_level="high"),
        _cand(2, "600001", score=42, warn_level="amber"),
    ], db_path=db)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    before = [dict(r) for r in conn.execute("SELECT * FROM candidates ORDER BY id")]
    conn.close()

    store.init_db(db)
    store.init_db(db)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    after = [dict(r) for r in conn.execute("SELECT * FROM candidates ORDER BY id")]
    conn.close()
    assert len(after) == len(before) == 2
    assert after == before
    assert _cols(db).count("warn_level") == 1


# —— ⑧:旧行 warn_level=NULL 经 list_candidates 回读省略键(前向兼容)—————————————

def test_null_warn_level_omitted_on_read(tmp_path):
    db = str(tmp_path / "null_wl.db")
    store.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT INTO candidates
           (trade_date, rank, code, name, sector, tag, price, chg,
            vol_multiple, vol_pct, flow, turnover, warn, score, warn_level, created_at)
           VALUES ('2026-06-24', 1, '600000', '旧行', '银行', '放量突破',
                   10.0, '+3.00%', '2.8x', 90, '+1.20亿', '4.6%', NULL, NULL, NULL,
                   '2026-06-24 15:35:00')"""
    )
    conn.commit(); conn.close()

    got = store.list_candidates("2026-06-24", db_path=db)
    assert len(got) == 1
    assert "warnLevel" not in got[0]   # NULL → 省略键,不崩、前向兼容


# —— ⑨:穿透缓存回环测试(致命#1 门禁,必须过 upsert→list 缓存表往返)——————————

def test_warn_level_high_survives_upsert_list_roundtrip(tmp_path):
    """pipeline 产 warnLevel='high' → upsert_candidates 落库 → list_candidates 读回
    仍带 warnLevel='high'(封死"逐列白名单 INSERT 静默丢弃 warnLevel"断层,致命#1)。
    """
    db = str(tmp_path / "wl_high.db")
    store.init_db(db)
    store.upsert_candidates("2026-06-24", [
        _cand(1, "600000", warn="60日累涨 200%,极高位,追高高危", warn_level="high"),
    ], db_path=db)
    got = store.list_candidates("2026-06-24", db_path=db)
    assert len(got) == 1
    assert got[0]["warnLevel"] == "high"


def test_warn_level_amber_survives_upsert_list_roundtrip(tmp_path):
    """pipeline 产 warnLevel='amber' → upsert → list 读回仍带 'amber'(致命#1 门禁)。"""
    db = str(tmp_path / "wl_amber.db")
    store.init_db(db)
    store.upsert_candidates("2026-06-24", [
        _cand(1, "600001", warn="60日累涨 70%,偏高位,谨慎", warn_level="amber"),
    ], db_path=db)
    got = store.list_candidates("2026-06-24", db_path=db)
    assert len(got) == 1
    assert got[0]["warnLevel"] == "amber"


def test_warn_level_nil_omitted_after_roundtrip(tmp_path):
    """pipeline 未产 warnLevel(无警示票)→ upsert → list 读回省略 warnLevel 键(致命#1 门禁)。"""
    db = str(tmp_path / "wl_nil.db")
    store.init_db(db)
    store.upsert_candidates("2026-06-24", [
        _cand(1, "600002"),   # 不传 warn_level → dict 无 warnLevel 键
    ], db_path=db)
    got = store.list_candidates("2026-06-24", db_path=db)
    assert len(got) == 1
    assert "warnLevel" not in got[0]


def test_warn_level_mixed_pool_roundtrip_via_end_to_end_pipeline(tmp_path):
    """端到端:pipeline.build_candidates 真产 warnLevel → upsert → list 三态齐验
    (high/amber/None 一次性过缓存表往返,最贴近生产真链路的门禁)。
    """
    from app.screen import pipeline
    from app.screen.fetch import MarketSnapshot, StockRow

    rows = [
        StockRow(code="600000", name="极高位", industry="银行", close=10.0,
                 pct_chg=2.0, turnover=8.0, net_mf_amount=10.0, net_mf_3d=100.0,
                 volume_ratio=2.0, pct_60d=200.0, new_high_20d=True, above_ma20=True,
                 pos_health=0.9),
        StockRow(code="600001", name="偏高位", industry="银行", close=10.0,
                 pct_chg=2.0, turnover=8.0, net_mf_amount=10.0, net_mf_3d=100.0,
                 volume_ratio=2.0, pct_60d=70.0, new_high_20d=True, above_ma20=True,
                 pos_health=0.9),
        StockRow(code="600002", name="干净", industry="银行", close=10.0,
                 pct_chg=2.0, turnover=8.0, net_mf_amount=10.0, net_mf_3d=100.0,
                 volume_ratio=2.0, pct_60d=10.0, new_high_20d=True, above_ma20=True,
                 pos_health=0.9),
    ]
    snap = MarketSnapshot(trade_date="2026-06-24", rows=rows)
    candidates = pipeline.build_candidates(snap)
    assert len(candidates) == 3

    db = str(tmp_path / "wl_e2e.db")
    store.init_db(db)
    store.upsert_candidates("2026-06-24", candidates, db_path=db)
    got = {c["code"]: c for c in store.list_candidates("2026-06-24", db_path=db)}

    assert got["600000"]["warnLevel"] == "high"
    assert got["600001"]["warnLevel"] == "amber"
    assert "warnLevel" not in got["600002"]
