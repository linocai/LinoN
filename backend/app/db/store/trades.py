"""trades 只读聚合(阶段3 G1:复盘打分数据源)。

⚠️ trades 表【无 status 列】——每一行本身就是一笔已闭合交易(close_position 落库时写)。
   读 trades 禁止 `WHERE status='closed'`(那是 positions 概念,会抛 no such column)。
   list_closed_trades = 直接读全表,可选按 close_time 的 since/until 过滤。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.db.store._common import get_connection


def list_closed_trades(
    since: Optional[str] = None,
    until: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """列出已闭合 trades(直接读全表,无 status 过滤),按 close_time 升序。

    可选按 close_time 过滤:since <= close_time(<= until)。since/until 为
    'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM:SS' 串(字典序比较即时序,SQLite TEXT 存)。
    """
    conn = get_connection(db_path)
    try:
        clauses: List[str] = []
        params: List[Any] = []
        if since is not None:
            clauses.append("close_time >= ?")
            params.append(since)
        if until is not None:
            clauses.append("close_time <= ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM trades{where} ORDER BY close_time",
            tuple(params),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def list_all_trades(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出所有 trades(供近 6 周趋势跨周聚合),按 close_time 升序。"""
    return list_closed_trades(db_path=db_path)
