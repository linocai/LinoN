"""候选缓存表(阶段2 D1/D2:EOD 算一次候选落表,端点读缓存)。

score 列(阶段3.1)由 schema._ensure_candidates_columns 迁移补充;v1.4.1 Phase C 起
score 语义从"池内相对分"改"绝对质量分",0 分是合法最低分——旧行 score=NULL 回读改
省略键(不再兜底 0,避免与绝对口径下合法 0 分撞车,见 plan §4.2 🔵9)。
warn_level 列(v1.3.1 A2.5,第四次真 migration)同一函数补充;旧行 warn_level=NULL 回读省略键
(前向兼容,同 warn 惯例)。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.db.store._common import _now, get_connection

# Candidate dict → candidates 列名映射(rows 用 pipeline 产的 camelCase 键)。
_CANDIDATE_KEYS = (
    ("rank", "rank"),
    ("name", "name"),
    ("code", "code"),
    ("sector", "sector"),
    ("tag", "tag"),
    ("price", "price"),
    ("chg", "chg"),
    ("vol_multiple", "volMultiple"),
    ("vol_pct", "volPct"),
    ("flow", "flow"),
    ("turnover", "turnover"),
    ("warn", "warn"),
    ("warn_level", "warnLevel"),   # v1.3.1 A2.5:高位分级(red/amber),第四次真 migration
)


def upsert_candidates(
    trade_date: str, rows: List[Dict[str, Any]], db_path: Optional[str] = None
) -> int:
    """整体替换某 trade_date 的候选缓存(先删该日旧行,再插入新行)。

    rows = pipeline 产的 Candidate dict 列表(camelCase 键:volMultiple/volPct…)。
    trade_date 'YYYY-MM-DD'。返回写入行数。空 rows → 清掉该日缓存(返回 0)。
    """
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM candidates WHERE trade_date = ?", (trade_date,))
        n = 0
        now = _now()
        for r in rows:
            conn.execute(
                """INSERT INTO candidates
                   (trade_date, rank, code, name, sector, tag, price, chg,
                    vol_multiple, vol_pct, flow, turnover, warn, score, warn_level,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade_date,
                    int(r.get("rank", 0)),
                    str(r.get("code", "")),
                    str(r.get("name", "")),
                    r.get("sector"),
                    r.get("tag"),
                    r.get("price"),
                    r.get("chg"),
                    r.get("volMultiple"),
                    r.get("volPct"),
                    r.get("flow"),
                    r.get("turnover"),
                    r.get("warn"),
                    int(r.get("score", 0)),   # 阶段3.1:pipeline 一定带 score,缺省兜底 0
                    r.get("warnLevel"),        # v1.3.1 A2.5:None → NULL(旧行/无警示票同此)
                    now,
                ),
            )
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def list_candidates(trade_date: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读某 trade_date 的候选缓存,按 rank 升序。返回 Candidate 形状 dict 列表
    (camelCase 键,对齐 Models.swift / plan §4.3;warn/warnLevel 为 None 时省略键)。
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM candidates WHERE trade_date = ? ORDER BY rank",
            (trade_date,),
        ).fetchall()
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        cand = {
            "rank": d["rank"],
            "name": d["name"],
            "code": d["code"],
            "sector": d.get("sector") or "",
            "tag": d.get("tag") or "",
            "price": d.get("price") or 0.0,
            "chg": d.get("chg") or "",
            "volMultiple": d.get("vol_multiple") or "",
            "volPct": d.get("vol_pct") or 0,
            "flow": d.get("flow") or "",
            "turnover": d.get("turnover") or "",
        }
        # v1.4.1 Phase C(🔵9):score 展示分绝对口径下 0 是合法最低分,与旧 NULL 撞车——
        # NULL(迁移前旧行/无候选)→ 省略键(客户端 Candidate.score 是 Int?,nil 不显徽章,
        # 前向兼容现成),不再兜底 0(兜 0 会让旧行显示假的"绝对 0 分")。
        if d.get("score") is not None:
            cand["score"] = d["score"]
        if d.get("warn"):
            cand["warn"] = d["warn"]
        # v1.3.1 A2.5:warn_level(高位分级红/琥珀)。旧行/无警示票 warn_level=NULL → 省略键
        # (前向兼容,客户端解到 nil,同 warn 惯例;致命#1 门禁的关键回读点)。
        if d.get("warn_level"):
            cand["warnLevel"] = d["warn_level"]
        out.append(cand)
    return out


def latest_candidate_date(db_path: Optional[str] = None) -> Optional[str]:
    """最近一次有候选缓存的 trade_date('YYYY-MM-DD');无则 None。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT trade_date FROM candidates ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return row["trade_date"] if row else None


def candidate_entry_date_of(code: str, db_path: Optional[str] = None) -> Optional[str]:
    """查某 code 在 candidates 缓存里【最近一次】所属的 trade_date(= entry_date)。

    供 /analyze 落 analysis_verdicts 用(plan §4.2:trade_date 必须取该 code 所属候选的
    entry_date,不是 latest_candidate_date——深判 on-demand,用户可能在候选产生 T+1/T+2
    才点深判,那时 latest 已滚到新一天,用 latest 会导致回测 join 恒取不到)。
    查不到(该 code 从未出现在任何候选快照里)→ None。
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT trade_date FROM candidates WHERE code = ? ORDER BY trade_date DESC LIMIT 1",
            (code,),
        ).fetchone()
    finally:
        conn.close()
    return row["trade_date"] if row else None
