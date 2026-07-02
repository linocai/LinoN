"""设备 token(阶段1 A.1:APNs device token 注册;推送时遍历)。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.db.store._common import _now, get_connection


def upsert_device_token(
    token: str, platform: str = "ios", db_path: Optional[str] = None
) -> int:
    """登记一个 APNs device token。token UNIQUE,重复上报 upsert 不增行、不报错。

    返回该 token 行的 id。
    """
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO device_tokens (token, platform, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(token) DO UPDATE SET platform = excluded.platform""",
            (token, platform, _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM device_tokens WHERE token = ?", (token,)
        ).fetchone()
        return int(row["id"]) if row else int(cur.lastrowid)
    finally:
        conn.close()


def list_device_tokens(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出所有已注册设备 token(推送时遍历)。"""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, token, platform, created_at FROM device_tokens ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
