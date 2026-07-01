"""阶段3 G3:清仓沉淀记忆 + trades 补列(高危迁移)单测。

覆盖 plan §4.4 G3 验收:
  ① 幂等硬断言:连跑 init_db 两次/三次不抛 duplicate column、不丢已有 trades 行、不改列值;
  ② 旧库(无 name/note 列)跑 init_db 自动补列、数据无损;
  ③ 破线笔 → trades.name/note 落库 + memory 新增闭环结论,二者同一事务(强制抛异常验回滚);
  ④ 守线笔 → 不沉淀 memory;
  ⑤ close_position 返回值/契约不变;
  ⑥ _mechanical_comment 只定义一处(G1/G3 import 同一函数)。
"""

import sqlite3

import pytest

from app.db import store


def _cols(db_path, table="trades"):
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    conn.close()
    return cols


# —— ①:幂等 ——————————————————————————————————————————————————————

def test_init_db_idempotent_no_duplicate_column(tmp_path):
    db = str(tmp_path / "idem.db")
    store.init_db(db)
    assert "name" in _cols(db) and "note" in _cols(db)
    # 种一行 trades(经 open→close)
    pid = store.open_position("603986", "兆易创新", 100.0, 100, "x", "2026-06-22", db_path=db)
    store.close_position(pid, 116.0, holding_trade_days=2, db_path=db)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    before = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY id")]
    conn.close()

    # 再跑 init_db 两次(模拟服务反复重启)——不抛 duplicate column
    store.init_db(db)
    store.init_db(db)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    after = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY id")]
    conn.close()
    # 行数不变、列值不变
    assert len(after) == len(before) == 1
    assert after[0] == before[0]
    # 列仍只一份 name/note(无重复列)
    assert _cols(db).count("name") == 1 and _cols(db).count("note") == 1


# —— ②:旧库(无 name/note)自动补列、数据无损 ————————————————————————

def test_old_db_without_columns_gets_migrated(tmp_path):
    db = str(tmp_path / "old.db")
    # 手工建一个"旧版" trades 表(无 name/note 列)+ 种一行历史数据
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
            open_price REAL NOT NULL, close_price REAL NOT NULL,
            open_time TEXT NOT NULL, close_time TEXT NOT NULL,
            kept_stop INTEGER NOT NULL, kept_take INTEGER NOT NULL,
            kept_time INTEGER NOT NULL, pnl REAL NOT NULL,
            broke_rule INTEGER NOT NULL, created_at TEXT NOT NULL)
    """)
    conn.execute(
        """INSERT INTO trades
           (code, open_price, close_price, open_time, close_time,
            kept_stop, kept_take, kept_time, pnl, broke_rule, created_at)
           VALUES ('600519', 100.0, 120.0, '2026-06-22', '2026-06-30 10:00:00',
                   1, 1, 1, 20.0, 0, '2026-06-30 10:00:00')"""
    )
    conn.commit(); conn.close()
    assert "name" not in _cols(db)

    # init_db 自动补列
    store.init_db(db)
    assert "name" in _cols(db) and "note" in _cols(db)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM trades WHERE code='600519'").fetchone()
    conn.close()
    # 历史数据无损;新列为 NULL
    assert row["code"] == "600519" and row["pnl"] == 20.0
    assert row["name"] is None and row["note"] is None


# —— ③:破线笔 → trades.name/note + memory,同一事务(原子)——————————————

def test_broke_trade_sinks_memory_and_writes_name_note(tmp_path):
    db = str(tmp_path / "broke.db")
    store.init_db(db)
    pid = store.open_position("002463", "沪电股份", 100.0, 100, "追高", "2026-06-22", db_path=db)
    # -10% 离场(跌穿容差下沿)→ 破止损
    store.close_position(pid, 90.0, holding_trade_days=2, db_path=db)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    mems = conn.execute("SELECT * FROM memory ORDER BY id").fetchall()
    conn.close()
    assert t["broke_rule"] == 1
    assert t["name"] == "沪电股份"
    assert t["note"] == "破止损:跌穿 -5% 未走"
    assert len(mems) == 1
    assert mems[0]["kind"] == "闭环结论"
    assert "沪电股份" in mems[0]["content"] and "破止损" in mems[0]["content"]


def test_broke_trade_memory_atomic_rollback(tmp_path, monkeypatch):
    """insert_memory 前强制抛异常 → trades 写 + position 归档一并回滚(证明原子)。"""
    db = str(tmp_path / "atomic.db")
    store.init_db(db)
    pid = store.open_position("002463", "沪电股份", 100.0, 100, "x", "2026-06-22", db_path=db)

    # 让 insert_memory 抛异常(打断同事务的 memory 写)
    import app.db.store as store_mod
    orig = store_mod.insert_memory

    def _boom(*a, **k):
        raise RuntimeError("memory sink boom")

    monkeypatch.setattr(store_mod, "insert_memory", _boom)

    with pytest.raises(RuntimeError):
        store.close_position(pid, 90.0, holding_trade_days=2, db_path=db)

    # 回滚验证:trades 无新行、position 仍 holding、memory 无行
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    n_trades = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
    pos = conn.execute("SELECT status FROM positions WHERE id=?", (pid,)).fetchone()
    n_mem = conn.execute("SELECT COUNT(*) AS n FROM memory").fetchone()["n"]
    conn.close()
    assert n_trades == 0            # trades 一并回滚
    assert pos["status"] == "holding"   # position 未归档(回滚)
    assert n_mem == 0

    monkeypatch.setattr(store_mod, "insert_memory", orig)


# —— ④:守线笔 → 不沉淀 memory ————————————————————————————————————

def test_kept_trade_does_not_sink_memory(tmp_path):
    db = str(tmp_path / "kept.db")
    store.init_db(db)
    pid = store.open_position("603986", "兆易创新", 100.0, 100, "x", "2026-06-22", db_path=db)
    store.close_position(pid, 116.0, holding_trade_days=2, db_path=db)   # +16% 守
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    n_mem = conn.execute("SELECT COUNT(*) AS n FROM memory").fetchone()["n"]
    conn.close()
    assert t["broke_rule"] == 0 and t["note"] == "守住铁律"
    assert n_mem == 0   # 守线不沉淀(避免噪声)


# —— ⑤:close_position 返回值/契约不变 ————————————————————————————————

def test_close_position_returns_trade_id_unchanged(tmp_path):
    db = str(tmp_path / "ret.db")
    store.init_db(db)
    pid = store.open_position("603986", "兆易创新", 100.0, 100, "x", "2026-06-22", db_path=db)
    tid = store.close_position(pid, 116.0, holding_trade_days=2, db_path=db)
    assert isinstance(tid, int) and tid >= 1


# —— ⑥:_mechanical_comment 单一事实源 ————————————————————————————————

def test_mechanical_comment_single_source():
    """G1 aggregate(score.py)与 G3 close_position(store.py)import 同一 _mechanical_comment。"""
    from app.review.score import _mechanical_comment as from_score
    import inspect

    # store.close_position 源码里 import 的正是 app.review.score._mechanical_comment
    src = inspect.getsource(store.close_position)
    assert "from app.review.score import _mechanical_comment" in src
    # 全库只有 score.py 定义 def _mechanical_comment(不在 store.py 另写一份)
    store_src = inspect.getsource(store)
    assert "def _mechanical_comment" not in store_src


def test_insert_memory_conn_reuse_no_double_commit(tmp_path):
    """insert_memory(conn=) 复用连接不自 commit(供 close_position 原子)。"""
    db = str(tmp_path / "conn.db")
    store.init_db(db)
    conn = store.get_connection(db)
    try:
        mid = store.insert_memory("长期记忆", "x", conn=conn)
        assert mid >= 1
        # 未 commit:另开连接读不到(隔离)
        conn2 = sqlite3.connect(db)
        n_before = conn2.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        conn2.close()
        assert n_before == 0
        conn.commit()
        conn3 = sqlite3.connect(db)
        n_after = conn3.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        conn3.close()
        assert n_after == 1
    finally:
        conn.close()
