"""SQLite 四表 + CRUD 最小集(plan §4 Phase 0.4)。

严格按 plan DDL:
  positions(id, code, name, buy_price, qty, entry_reason, entry_snapshot(JSON),
            buy_date, status, created_at)            -- 最多 3 行;【不含 stop_line 列】
            -- 止损线 = buy_price×0.95 读取时派生(本表不存),单一事实源同持仓天数。
  trades(id, code, open_price, close_price, open_time, close_time,
         kept_stop, kept_take, kept_time, pnl, broke_rule, created_at)
  reviews(id, week, score, red_flags(JSON), discipline_rate, lessons,
          next_week_note, created_at)
  memory(id, kind, content, created_at)

CRUD 最小集:open_position / close_position(落 trades + 归档 position) /
            list_holdings / insert_review / insert_memory。

注:plan DDL 是后端 schema 权威。客户端 Models.swift 上 TradeRecord 多了 name/note 字段
   (展示用),不在后端 0.4 DDL 内——本期严格照 plan DDL 建表,name/note 留待阶段3 复盘细化时
   再评估是否加列(写入变更日志/CLAUDE.md 备忘)。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings

# —— 止损/止盈/容差常量(规则单一事实源,与客户端 Models.swift / plan §4b 对齐)——
STOP_RATIO = 0.95           # 止损线 = buy_price × 0.95(-5%)
TAKE_RATIO = 1.15           # 止盈线 = buy_price × 1.15(+15%)
# 触发线口径定死 -5.0(plan §4b);展示侧 -4.9 仅显示阈,触发判定引用 -5.0。
STOP_TRIGGER_PCT = -5.0
TAKE_TRIGGER_PCT = 15.0
# 止损容差带(约束5):在 -6%~-4% 离场都算"守了止损",不因正常滑点误标破纪律。
STOP_KEPT_LOW = -6.0
STOP_KEPT_HIGH = -4.0
FORCE_CLOSE_TRADE_DAY = 4   # D4 强平

MAX_HOLDINGS = 3            # 同时最多 3 票

_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT    NOT NULL,
    name           TEXT    NOT NULL,
    buy_price      REAL    NOT NULL,
    qty            INTEGER NOT NULL,
    entry_reason   TEXT    NOT NULL,          -- 用户录入:进场理由
    entry_snapshot TEXT,                      -- 系统自动:JSON {formNote, fundNote}
    buy_date       TEXT    NOT NULL,          -- 交易日历基准(D1 起算),'YYYY-MM-DD'
    status         TEXT    NOT NULL DEFAULT 'holding',
    created_at     TEXT    NOT NULL
    -- 止损线不落库:= buy_price × 0.95 读取时派生(单一事实源)
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL,
    open_price  REAL    NOT NULL,
    close_price REAL    NOT NULL,
    open_time   TEXT    NOT NULL,
    close_time  TEXT    NOT NULL,
    kept_stop   INTEGER NOT NULL,             -- bool(守住止损,带 -6%~-4% 容差)
    kept_take   INTEGER NOT NULL,             -- bool(守住止盈)
    kept_time   INTEGER NOT NULL,             -- bool(守住时间 D4)
    pnl         REAL    NOT NULL,             -- 百分比收益(close-open)/open*100
    broke_rule  INTEGER NOT NULL,             -- bool(标红依据)
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    week            TEXT    NOT NULL,
    score           INTEGER NOT NULL,
    red_flags       TEXT,                     -- JSON 数组
    discipline_rate INTEGER NOT NULL,
    lessons         TEXT,
    next_week_note  TEXT,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT    NOT NULL,              -- 闭环结论/长期记忆/纪律里程碑
    content    TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _db_path(db_path: Optional[str] = None) -> str:
    return db_path or settings.DB_PATH


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """打开连接(自动建父目录)。row_factory = Row(列名访问)。"""
    path = _db_path(db_path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Optional[str] = None) -> str:
    """建四表(幂等)。返回落库路径。"""
    path = _db_path(db_path)
    conn = get_connection(path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return path


# —— 派生量(读取时算,不落库)————————————————————————————————————

def stop_line(buy_price: float) -> float:
    """止损线 = buy_price × 0.95(读取时派生,四舍五入 0.01)。"""
    return round(buy_price * STOP_RATIO, 2)


def take_line(buy_price: float) -> float:
    """止盈线 = buy_price × 1.15(读取时派生,四舍五入 0.01)。"""
    return round(buy_price * TAKE_RATIO, 2)


# —— CRUD ——————————————————————————————————————————————————————————

def open_position(
    code: str,
    name: str,
    buy_price: float,
    qty: int,
    entry_reason: str,
    buy_date: str,
    entry_snapshot: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> int:
    """开一仓,写 positions(status='holding')。返回新 position id。

    entry_snapshot 形如 {'formNote': ..., 'fundNote': ...}(系统自动补,存 JSON)。
    持仓上限校验:已 >= 3 holding 时抛 ValueError(同时最多 3 票)。
    """
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "SELECT COUNT(*) AS n FROM positions WHERE status = 'holding'"
        )
        if cur.fetchone()["n"] >= MAX_HOLDINGS:
            raise ValueError(f"持仓已满({MAX_HOLDINGS} 票),不能再开仓")
        snap_json = json.dumps(entry_snapshot, ensure_ascii=False) if entry_snapshot else None
        cur = conn.execute(
            """INSERT INTO positions
               (code, name, buy_price, qty, entry_reason, entry_snapshot,
                buy_date, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'holding', ?)""",
            (code, name, buy_price, qty, entry_reason, snap_json, buy_date, _now()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_holdings(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出在持(status='holding')。每行附派生 stop_line / take_line。"""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status = 'holding' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if d.get("entry_snapshot"):
            try:
                d["entry_snapshot"] = json.loads(d["entry_snapshot"])
            except (json.JSONDecodeError, TypeError):
                pass
        d["stop_line"] = stop_line(d["buy_price"])     # 派生
        d["take_line"] = take_line(d["buy_price"])     # 派生
        out.append(d)
    return out


def _compute_kept_flags(
    open_price: float,
    close_price: float,
    pnl_pct: float,
    holding_trade_days: Optional[int],
) -> Dict[str, bool]:
    """机械规则计算 kept_stop / kept_take / kept_time(阶段3 细化)。

    · kept_stop:在止损容差带 [-6%, -4%] 离场 → 守了止损(滑点不误判)。
    · kept_take:pnl >= +15% 止盈线 → 守了止盈。
    · kept_time:在 D4 当天或之前离场(count<=4)→ 守了时间。
      holding_trade_days 为 None(未传日历计数)时,保守置 True(无证据破纪律)。
    · broke_rule:亏损但没守住止损(跌穿 -6% 还没走),或持过 D4 → 破纪律。
    """
    kept_stop = STOP_KEPT_LOW <= pnl_pct <= STOP_KEPT_HIGH
    kept_take = pnl_pct >= TAKE_TRIGGER_PCT
    if holding_trade_days is None:
        kept_time = True
    else:
        kept_time = holding_trade_days <= FORCE_CLOSE_TRADE_DAY

    broke_rule = False
    # 跌穿止损容差下沿仍未守住 → 破止损
    if pnl_pct < STOP_KEPT_LOW:
        broke_rule = True
    # 持过 D4 仍未清 → 破时间
    if holding_trade_days is not None and holding_trade_days > FORCE_CLOSE_TRADE_DAY:
        broke_rule = True
    return {
        "kept_stop": kept_stop,
        "kept_take": kept_take,
        "kept_time": kept_time,
        "broke_rule": broke_rule,
    }


def close_position(
    position_id: int,
    close_price: float,
    close_time: Optional[str] = None,
    holding_trade_days: Optional[int] = None,
    db_path: Optional[str] = None,
) -> int:
    """清一仓:落一条 trades 闭合记录 + 归档对应 position(status='closed')。

    pnl = (close-open)/open*100(百分比)。kept_* / broke_rule 机械规则计算
    (阶段3 细化)。holding_trade_days 可由日历原语 count_holding_trade_days 传入,
    用于 kept_time 判定;不传则保守 True。
    返回新 trade id。position 不存在或非 holding → 抛 ValueError。
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"position {position_id} 不存在")
        if row["status"] != "holding":
            raise ValueError(f"position {position_id} 非在持(status={row['status']})")

        open_price = float(row["buy_price"])
        open_time = row["buy_date"]
        ctime = close_time or _now()
        pnl_pct = round((close_price - open_price) / open_price * 100, 4) if open_price else 0.0
        flags = _compute_kept_flags(open_price, close_price, pnl_pct, holding_trade_days)

        cur = conn.execute(
            """INSERT INTO trades
               (code, open_price, close_price, open_time, close_time,
                kept_stop, kept_take, kept_time, pnl, broke_rule, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["code"], open_price, close_price, open_time, ctime,
                int(flags["kept_stop"]), int(flags["kept_take"]),
                int(flags["kept_time"]), pnl_pct, int(flags["broke_rule"]), _now(),
            ),
        )
        trade_id = int(cur.lastrowid)
        # 归档持仓
        conn.execute(
            "UPDATE positions SET status = 'closed' WHERE id = ?", (position_id,)
        )
        conn.commit()
        return trade_id
    finally:
        conn.close()


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


def insert_memory(kind: str, content: str, db_path: Optional[str] = None) -> int:
    """写一条长期记忆/闭环结论/里程碑。返回 memory id。"""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO memory (kind, content, created_at) VALUES (?, ?, ?)",
            (kind, content, _now()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()
