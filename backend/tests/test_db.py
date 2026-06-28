"""Phase 0.4 SQLite:四表建表、open→close 闭合、止损线派生不落库、reviews/memory。"""

import json
import sqlite3

import pytest

from app.db import store
from app.db.store import (
    close_position,
    init_db,
    insert_memory,
    insert_review,
    list_holdings,
    open_position,
    stop_line,
    take_line,
)


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "test.db")
    init_db(p)
    return p


def _tables(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    conn.close()
    return sorted(r[0] for r in rows)


def test_init_creates_tables(db):
    # 阶段0 四表 + 阶段1 A.1 device_tokens + 阶段2 D1 candidates
    assert _tables(db) == [
        "candidates", "device_tokens", "memory", "positions", "reviews", "trades"
    ]


def test_positions_has_no_stop_line_column(db):
    """plan 锁定:positions 不含 stop_line 列(止损线读取时派生)。"""
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()]
    conn.close()
    assert "stop_line" not in cols
    assert "buy_price" in cols and "buy_date" in cols


def test_stop_take_line_derived():
    assert stop_line(100.0) == 95.0     # ×0.95
    assert take_line(100.0) == 115.0    # ×1.15
    assert stop_line(33.33) == round(33.33 * 0.95, 2)


def test_open_then_list_holdings(db):
    pid = open_position(
        "603986", "兆易创新", 100.0, 200, "放量突破平台", "2026-06-22",
        entry_snapshot={"formNote": "平台突破", "fundNote": "主力净流入"},
        db_path=db,
    )
    assert pid >= 1
    h = list_holdings(db)
    assert len(h) == 1
    row = h[0]
    assert row["code"] == "603986" and row["status"] == "holding"
    assert row["stop_line"] == 95.0       # 派生附加
    assert row["take_line"] == 115.0
    assert row["entry_snapshot"] == {"formNote": "平台突破", "fundNote": "主力净流入"}


def test_open_close_closed_loop(db):
    """开一仓 → 清一仓:positions 归档 + trades 落一条闭合记录。"""
    pid = open_position("603986", "兆易创新", 100.0, 200, "突破", "2026-06-22", db_path=db)
    assert len(list_holdings(db)) == 1

    tid = close_position(pid, 116.0, holding_trade_days=2, db_path=db)
    assert tid >= 1
    # positions 归档(不再在 holdings 列表)
    assert len(list_holdings(db)) == 0

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM trades").fetchone()
    p = conn.execute("SELECT status FROM positions WHERE id=?", (pid,)).fetchone()
    conn.close()
    assert p["status"] == "closed"
    assert t["open_price"] == 100.0 and t["close_price"] == 116.0
    assert abs(t["pnl"] - 16.0) < 1e-6           # +16% 百分比
    assert t["kept_take"] == 1                    # >= +15%
    assert t["kept_time"] == 1                    # D2 <= D4
    assert t["broke_rule"] == 0


def test_kept_stop_tolerance_band(db):
    """止损容差带:在 -6%~-4% 离场算守了止损(滑点不误判破纪律)。"""
    # -5% 离场 → kept_stop
    pid = open_position("600000", "示例", 100.0, 100, "x", "2026-06-22", db_path=db)
    close_position(pid, 95.0, holding_trade_days=2, db_path=db)
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert t["kept_stop"] == 1 and t["broke_rule"] == 0

    # -8% 离场(跌穿容差下沿)→ 破止损
    pid2 = open_position("600001", "示例2", 100.0, 100, "x", "2026-06-22", db_path=db)
    close_position(pid2, 92.0, holding_trade_days=2, db_path=db)
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    t2 = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert t2["kept_stop"] == 0 and t2["broke_rule"] == 1


def test_kept_time_broken_past_d4(db):
    """持过 D4(count>4)→ kept_time False, broke_rule True。"""
    pid = open_position("600002", "示例", 100.0, 100, "x", "2026-06-22", db_path=db)
    close_position(pid, 101.0, holding_trade_days=5, db_path=db)
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert t["kept_time"] == 0 and t["broke_rule"] == 1


def test_max_three_holdings(db):
    for i in range(3):
        open_position(f"60000{i}", f"票{i}", 10.0, 100, "x", "2026-06-22", db_path=db)
    with pytest.raises(ValueError):
        open_position("600009", "第四票", 10.0, 100, "x", "2026-06-22", db_path=db)


def test_close_nonexistent_raises(db):
    with pytest.raises(ValueError):
        close_position(999, 10.0, db_path=db)


def test_insert_review_and_memory(db):
    rid = insert_review(
        "2026-W26", 82, 75, red_flags=["追高", "扛单"],
        lessons="别接刀", next_week_note="只做 D 型", db_path=db,
    )
    mid = insert_memory("长期记忆", "两笔大亏死法相同", db_path=db)
    assert rid >= 1 and mid >= 1
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone()
    m = conn.execute("SELECT * FROM memory WHERE id=?", (mid,)).fetchone()
    conn.close()
    assert json.loads(r["red_flags"]) == ["追高", "扛单"]
    assert r["score"] == 82 and r["discipline_rate"] == 75
    assert m["kind"] == "长期记忆" and m["content"] == "两笔大亏死法相同"
