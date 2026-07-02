"""回测(阶段2.5 F3):candidate_outcomes + analysis_verdicts 读写 + 待回填扫描。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.db.store._common import _now, get_connection


def upsert_candidate_outcome(row: Dict[str, Any], db_path: Optional[str] = None) -> int:
    """写一行回测结果(幂等 UNIQUE(entry_date, code))。

    row 需含:entry_date, code, name, rank, tag, verdict(可 None), entry_close,
    exit_date, exit_close, ret_3d。重复 (entry_date, code) → 覆盖(保持最新一次回填)。
    返回该行 id。
    """
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO candidate_outcomes
               (entry_date, code, name, rank, tag, verdict, entry_close,
                exit_date, exit_close, ret_3d, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(entry_date, code) DO UPDATE SET
                   name=excluded.name, rank=excluded.rank, tag=excluded.tag,
                   verdict=excluded.verdict, entry_close=excluded.entry_close,
                   exit_date=excluded.exit_date, exit_close=excluded.exit_close,
                   ret_3d=excluded.ret_3d, created_at=excluded.created_at""",
            (
                row["entry_date"], row["code"], row.get("name", row["code"]),
                int(row.get("rank", 0)), row.get("tag"), row.get("verdict"),
                float(row["entry_close"]), row["exit_date"], float(row["exit_close"]),
                float(row["ret_3d"]), _now(),
            ),
        )
        conn.commit()
        r = conn.execute(
            "SELECT id FROM candidate_outcomes WHERE entry_date = ? AND code = ?",
            (row["entry_date"], row["code"]),
        ).fetchone()
        return int(r["id"]) if r else int(cur.lastrowid)
    finally:
        conn.close()


def list_outcomes(since: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读回测结果(可选 entry_date >= since 过滤,'YYYY-MM-DD')。按 entry_date 升序。"""
    conn = get_connection(db_path)
    try:
        if since:
            rows = conn.execute(
                "SELECT * FROM candidate_outcomes WHERE entry_date >= ? ORDER BY entry_date",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM candidate_outcomes ORDER BY entry_date"
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def pending_backfill_entries(
    today, min_trade_days: int = 4, db_path: Optional[str] = None
) -> List[Dict[str, str]]:
    """扫描待回填的 (entry_date, code) 批:candidates 有、candidate_outcomes 缺、

    且 entry_date 距 today 已过 >= min_trade_days 个交易日(含 entry_date 自身,
    D 计数口径——entry_date=D1,min_trade_days=4 即 entry_date 后已过 3 个交易日,
    exit 数据〔第 3 个交易日〕必然已收盘可拉)。

    扫描式防重(不靠内存变量):天然靠 UNIQUE(entry_date,code) 幂等,重启/错过窗口
    次日 tick 会自动补齐已过去但未回填的候选,不永久漏。today 为 date/datetime。
    返回 [{'entry_date':..., 'code':..., 'name':..., 'rank':..., 'tag':...}, ...]。
    """
    from app.calendar.trading_calendar import count_holding_trade_days

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT c.trade_date AS entry_date, c.code AS code, c.name AS name,
                      c.rank AS rank, c.tag AS tag
               FROM candidates c
               LEFT JOIN candidate_outcomes o
                 ON o.entry_date = c.trade_date AND o.code = c.code
               WHERE o.id IS NULL
               ORDER BY c.trade_date, c.rank"""
        ).fetchall()
    finally:
        conn.close()
    out: List[Dict[str, str]] = []
    for r in rows:
        d = dict(r)
        if count_holding_trade_days(d["entry_date"], today) >= min_trade_days:
            out.append(d)
    return out


def get_verdict(trade_date: str, code: str, db_path: Optional[str] = None) -> Optional[str]:
    """查某 (trade_date, code) 的深判 verdict;无则 None。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT verdict FROM analysis_verdicts WHERE trade_date = ? AND code = ?",
            (trade_date, code),
        ).fetchone()
    finally:
        conn.close()
    return row["verdict"] if row else None


def upsert_analysis_verdict(
    trade_date: str, code: str, verdict: str, db_path: Optional[str] = None
) -> int:
    """落一次深判 verdict(ON CONFLICT DO UPDATE 覆盖为最新一次,非保留最早)。

    trade_date 必须是该 code 所属候选的 entry_date(调用方用 candidate_entry_date_of
    解析),不是 latest_candidate_date。返回该行 id。
    """
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO analysis_verdicts (trade_date, code, verdict, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(trade_date, code) DO UPDATE SET
                   verdict=excluded.verdict, created_at=excluded.created_at""",
            (trade_date, code, verdict, _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM analysis_verdicts WHERE trade_date = ? AND code = ?",
            (trade_date, code),
        ).fetchone()
        return int(row["id"]) if row else int(cur.lastrowid)
    finally:
        conn.close()
