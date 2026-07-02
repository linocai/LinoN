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
  device_tokens(id, token UNIQUE, platform, created_at)   -- 阶段1 A.1 设备注册
  candidates(...)                                          -- 阶段2 D1/D2 候选缓存
  candidate_outcomes(...) / analysis_verdicts(...)          -- 阶段2.5 F3 回测 + verdict 落库

CRUD 最小集:open_position / close_position(落 trades + 归档 position) /
            list_holdings / get_holding / insert_review / insert_memory /
            upsert_device_token / list_device_tokens(阶段1 A.1 推送遍历) /
            upsert_candidate_outcome / list_outcomes / candidate_entry_date_of /
            pending_backfill_entries(扫描式回填防重)/ get_verdict / upsert_analysis_verdict
            (ON CONFLICT DO UPDATE 覆盖最新,阶段2.5 F3)。

注:plan DDL 是后端 schema 权威。客户端 Models.swift 上 TradeRecord 多了 name/note 字段
   (展示用),不在后端 0.4 DDL 内——本期严格照 plan DDL 建表,name/note 留待阶段3 复盘细化时
   再评估是否加列(写入变更日志/CLAUDE.md 备忘)。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings

log = logging.getLogger(__name__)

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
    -- name/note 两列由 _ensure_trades_columns() 迁移补充(阶段3,ALTER ADD COLUMN,不在此 DDL)
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

CREATE TABLE IF NOT EXISTS device_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT    NOT NULL UNIQUE,       -- APNs device token(客户端上报)
    platform   TEXT    NOT NULL DEFAULT 'ios',
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date   TEXT    NOT NULL,            -- EOD 计算基准 'YYYY-MM-DD'
    rank         INTEGER NOT NULL,            -- 机械排序名次(1 起)
    code         TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    sector       TEXT,                        -- 板块(免费板块归类/占位)
    tag          TEXT,                        -- 标签
    price        REAL,                        -- EOD 收盘价
    chg          TEXT,                        -- 涨跌幅展示串
    vol_multiple TEXT,                        -- 放量倍数 "2.8x"
    vol_pct      INTEGER,                     -- 放量进度 0-100
    flow         TEXT,                        -- 主力净流入展示串
    turnover     TEXT,                        -- 换手展示串
    warn         TEXT,                        -- 高位警告降级(≥50% 时非空)
    created_at   TEXT    NOT NULL,
    UNIQUE(trade_date, code)
    -- score 列由 _ensure_candidates_columns() 迁移补充(阶段3.1,ALTER ADD COLUMN,不在此 DDL)
);

CREATE TABLE IF NOT EXISTS candidate_outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date    TEXT    NOT NULL,   -- 候选产生日(= candidates.trade_date)'YYYY-MM-DD'
    code          TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    rank          INTEGER NOT NULL,   -- 当时机械排序名次(从 candidates 快照带出)
    tag           TEXT,               -- 当时标签(放量突破/站上均线)
    verdict       TEXT,               -- 深判 verdict(可进/观望/不进);未深判 → NULL
    entry_close   REAL    NOT NULL,   -- 候选日原始 daily.close(仅供人工核对,不参与 ret_3d)
    exit_date     TEXT    NOT NULL,   -- entry_date 后第 3 个交易日 'YYYY-MM-DD'
    exit_close    REAL    NOT NULL,   -- exit_date 原始 daily.close(仅供人工核对,不参与 ret_3d)
    ret_3d        REAL    NOT NULL,   -- 3 个交易日 daily.pct_chg 累乘收益 %(复权正确,见 plan §4.0)
    created_at    TEXT    NOT NULL,
    UNIQUE(entry_date, code)          -- 每票每候选日至多一行(回填幂等)
);

CREATE TABLE IF NOT EXISTS analysis_verdicts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date   TEXT    NOT NULL,    -- = 该 code 所属 candidates 快照的 entry_date(非 latest_candidate_date)
    code         TEXT    NOT NULL,
    verdict      TEXT    NOT NULL,    -- 最近一次候选深判 verdict(可进/观望/不进)
    created_at   TEXT    NOT NULL,
    UNIQUE(trade_date, code)          -- ON CONFLICT DO UPDATE 覆盖为最新一次深判(非保留最早)
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


def _ensure_trades_columns(conn: sqlite3.Connection) -> None:
    """给 trades 表补 name/note 列(阶段3 G3,项目首次真 migration,高危区)。

    SQLite 无 `ADD COLUMN IF NOT EXISTS`,故靠 PRAGMA table_info 探测(硬编精确集合)。
    整段 try/except:ALTER 意外失败**只 log.error,不 re-raise**——init_db 跑在 app.py
    lifespan 启动路径、每次 ECS 重启都执行,一个展示列的迁移绝不能拖垮整个交易监控服务的
    startup(name/note 缺了打分照跑,打分只读 kept_*/broke_rule/pnl/close_time)。
    """
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}  # row[1] = 列名
        for col in ("name", "note"):
            if col not in existing:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {col} TEXT")
    except Exception:
        log.error("trades 补列(name/note)迁移异常(已吞,不拖垮 startup)", exc_info=True)


def _ensure_candidates_columns(conn: sqlite3.Connection) -> None:
    """给 candidates 表补 score 列(阶段3.1,项目第二次真 migration,高危区)。

    与 _ensure_trades_columns 完全同套姿势:PRAGMA table_info 精确集合探测缺 score 则
    ALTER TABLE ADD COLUMN;整段 try/except **只 log.error,不 re-raise**——init_db 跑在
    app.py lifespan 启动路径、每次 ECS 重启都执行,一个展示列的迁移绝不能拖垮整个交易
    监控服务的 startup(score 缺了候选照跑,只是不显示分数)。

    **为何 ALTER 不 DROP**(plan §4.1 否决方案②):pending_backfill_entries 的回填扫描
    FROM candidates LEFT JOIN candidate_outcomes 读 candidates 表**历史行**找未回填样本,
    DROP 重建会丢掉"已产候选但回测未回填(entry_date 距今不足 4 交易日)"的历史行,导致
    这批候选的回测样本永久丢失。故 candidates 表历史行不可 DROP,必须走 ALTER 保留历史。
    """
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(candidates)")}  # row[1] = 列名
        if "score" not in existing:
            conn.execute("ALTER TABLE candidates ADD COLUMN score INTEGER")
    except Exception:
        log.error("candidates 补列(score)迁移异常(已吞,不拖垮 startup)", exc_info=True)


def init_db(db_path: Optional[str] = None) -> str:
    """建表(幂等)+ trades/candidates 补列迁移。返回落库路径。"""
    path = _db_path(db_path)
    conn = get_connection(path)
    try:
        conn.executescript(_SCHEMA)
        _ensure_trades_columns(conn)        # 阶段3 G3:trades 补 name/note(幂等,失败不拖垮)
        _ensure_candidates_columns(conn)    # 阶段3.1:candidates 补 score(幂等,失败不拖垮)
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


def get_holding_by_code(code: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 code 取在持仓(status='holding')。无则 None。用于 open 重复防护。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM positions WHERE code = ? AND status = 'holding'",
            (code,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    d = dict(row)
    if d.get("entry_snapshot"):
        try:
            d["entry_snapshot"] = json.loads(d["entry_snapshot"])
        except (json.JSONDecodeError, TypeError):
            pass
    d["stop_line"] = stop_line(d["buy_price"])
    d["take_line"] = take_line(d["buy_price"])
    return d


def get_position(position_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 id 取任一持仓行(任何 status)。无则 None。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def holding_count(db_path: Optional[str] = None) -> int:
    """当前在持仓票数。"""
    conn = get_connection(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM positions WHERE status = 'holding'"
            ).fetchone()["n"]
        )
    finally:
        conn.close()


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
    from app.review.score import _mechanical_comment   # 短评单一事实源(与 G1 aggregate 同源)

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
        name = row["name"]                       # 从 position 取(阶段3 G3 补列)
        note = _mechanical_comment(flags)        # 机械短评(守住铁律/破止损/破时间)

        cur = conn.execute(
            """INSERT INTO trades
               (code, open_price, close_price, open_time, close_time,
                kept_stop, kept_take, kept_time, pnl, broke_rule, created_at, name, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["code"], open_price, close_price, open_time, ctime,
                int(flags["kept_stop"]), int(flags["kept_take"]),
                int(flags["kept_time"]), pnl_pct, int(flags["broke_rule"]), _now(),
                name, note,
            ),
        )
        trade_id = int(cur.lastrowid)
        # 归档持仓
        conn.execute(
            "UPDATE positions SET status = 'closed' WHERE id = ?", (position_id,)
        )
        # 破线笔:同一事务内原子沉淀一条闭环结论(不 commit 后再开新连接)。
        # 若此处抛异常,trades 写 + position 归档一并回滚(原子;G3 验收③)。
        if flags["broke_rule"]:
            insert_memory("闭环结论", f"{name or row['code']}:{note}", conn=conn)
        conn.commit()
        return trade_id
    finally:
        conn.close()


# —— trades 只读聚合(阶段3 G1:复盘打分数据源)——————————————————————————
#
# ⚠️ trades 表【无 status 列】——每一行本身就是一笔已闭合交易(close_position 落库时写)。
#    读 trades 禁止 `WHERE status='closed'`(那是 positions 概念,会抛 no such column)。
#    list_closed_trades = 直接读全表,可选按 close_time 的 since/until 过滤。

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


# —— 周复盘注记(阶段3 G2:reviews 首次写入)——————————————————————————————
#
# ⚠️ reviews 表【无 UNIQUE(week) 约束】——禁用 ON CONFLICT(week)(无冲突目标会报错)。
#    upsert 用 SELECT id WHERE week=? → 有则 UPDATE、无则 INSERT(单用户无并发,可接受非原子)。
#    不给 reviews 另加约束(SQLite 加约束要建新表搬数据,风险更大不值得)。

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


# —— 设备 token(阶段1 A.1:APNs device token 注册;推送时遍历)——————————

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


# —— 候选缓存表(阶段2 D1/D2:EOD 算一次候选落表,端点读缓存)——————————

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
                    vol_multiple, vol_pct, flow, turnover, warn, score, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
    (camelCase 键,对齐 Models.swift / plan §4.3;warn 为 None 时省略键)。
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
            # 阶段3.1:score 展示分。旧行(迁移前写入)score=NULL → 回读兜底 0 不崩
            # (客户端旧行显示 0 分属预期,这些是待回填的历史缓存、不在当前推荐列表)。
            "score": d.get("score") if d.get("score") is not None else 0,
        }
        if d.get("warn"):
            cand["warn"] = d["warn"]
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


# —— 回测(阶段2.5 F3):candidate_outcomes + analysis_verdicts ————————————

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
