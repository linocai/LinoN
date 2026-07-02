"""复盘 reviews + 记忆 memory 表读写(阶段3 G2:reviews/memory 首次真读写)。

⚠️ reviews 表【无 UNIQUE(week) 约束】——禁用 ON CONFLICT(week)(无冲突目标会报错)。
   upsert 用 SELECT id WHERE week=? → 有则 UPDATE、无则 INSERT(单用户无并发,可接受非原子)。
   不给 reviews 另加约束(SQLite 加约束要建新表搬数据,风险更大不值得)。

insert_memory 支持传入现有 conn 复用连接(不自开、不 commit),供 close_position 在同一
事务内原子沉淀 memory(trades 写 + memory 写要么都成要么都不成)。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from app.db.store._common import _now, get_connection


def insert_review(
    week: str,
    score: int,
    discipline_rate: int,
    red_flags: Optional[List[str]] = None,
    lessons: str = "",
    next_week_note: str = "",
    db_path: Optional[str] = None,
) -> int:
    """写一条周复盘。red_flags 存 JSON 数组。返回 review id。"""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO reviews
               (week, score, red_flags, discipline_rate, lessons, next_week_note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                week, score,
                json.dumps(red_flags or [], ensure_ascii=False),
                discipline_rate, lessons, next_week_note, _now(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def insert_memory(
    kind: str,
    content: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """写一条长期记忆/闭环结论/里程碑。返回 memory id。

    conn 传入时复用现有连接(不自开、不 commit)——供 close_position 在同一事务内
    原子沉淀 memory(阶段3 G3:trades 写 + memory 写要么都成要么都不成)。
    conn 为 None 时自开连接并 commit(独立调用)。
    """
    if conn is not None:
        cur = conn.execute(
            "INSERT INTO memory (kind, content, created_at) VALUES (?, ?, ?)",
            (kind, content, _now()),
        )
        return int(cur.lastrowid)
    conn2 = get_connection(db_path)
    try:
        cur = conn2.execute(
            "INSERT INTO memory (kind, content, created_at) VALUES (?, ?, ?)",
            (kind, content, _now()),
        )
        conn2.commit()
        return int(cur.lastrowid)
    finally:
        conn2.close()


def list_memory(limit: int = 200, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """列 memory 表条目(倒序,最近 limit 条,防未来极端累积)。"""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, kind, content, created_at FROM memory ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def upsert_review_note(
    week: str, note: str, discipline_rate: int = 0, db_path: Optional[str] = None
) -> int:
    """写/覆盖某周 next_week_note(SELECT-then-UPDATE/INSERT,不用 ON CONFLICT)。

    存 note + 当刻 discipline_rate 快照(供历史留痕;端点返回的 disciplineRate 始终实时算)。
    同 week 二次调用覆盖同一行、不新增。返回该行 id。
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM reviews WHERE week = ? ORDER BY id LIMIT 1", (week,)
        ).fetchone()
        if row is not None:
            rid = int(row["id"])
            conn.execute(
                "UPDATE reviews SET next_week_note = ?, discipline_rate = ? WHERE id = ?",
                (note, discipline_rate, rid),
            )
        else:
            cur = conn.execute(
                """INSERT INTO reviews
                   (week, score, red_flags, discipline_rate, lessons, next_week_note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (week, discipline_rate, json.dumps([], ensure_ascii=False),
                 discipline_rate, "", note, _now()),
            )
            rid = int(cur.lastrowid)
        conn.commit()
        return rid
    finally:
        conn.close()


def get_review_note(week: str, db_path: Optional[str] = None) -> str:
    """读某周已存的 next_week_note;无则空串。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT next_week_note FROM reviews WHERE week = ? ORDER BY id LIMIT 1", (week,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return ""
    return row["next_week_note"] or ""
