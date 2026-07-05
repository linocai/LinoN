"""建表 DDL(plan §4)+ 迁移(阶段3/3.1 真 migration,高危区)+ init_db。

DDL 是后端 schema 权威。客户端 Models.swift 上 TradeRecord 多 name/note 展示字段,
由 `_ensure_trades_columns` 迁移补充(阶段3);candidates.score 由 `_ensure_candidates_columns`
补充(阶段3.1)。两处迁移整段 try/except 只 log 不 re-raise——init_db 跑在 app.py lifespan
启动路径、每次 ECS 重启都执行,展示列迁移绝不能拖垮整个交易监控服务的 startup。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from app.db.store._common import _db_path, get_connection

log = logging.getLogger(__name__)

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
    -- industry 列由 _ensure_v130_columns() 迁移补充(v1.3.0,ALTER ADD COLUMN,不在此 DDL)
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
    -- qty/fee/net_pnl_amount 三列由 _ensure_v130_columns() 迁移补充(v1.3.0,不在此 DDL)
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
    -- warn_level 列由 _ensure_candidates_columns() 迁移补充(v1.3.1 A2.5,ALTER ADD COLUMN,不在此 DDL)
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
    """给 candidates 表补 score/warn_level 列(阶段3.1 + v1.3.1 A2.5,项目第二/第四次
    真 migration,高危区)。

    与 _ensure_trades_columns 完全同套姿势:PRAGMA table_info 精确集合探测缺列则
    ALTER TABLE ADD COLUMN;整段 try/except **只 log.error,不 re-raise**——init_db 跑在
    app.py lifespan 启动路径、每次 ECS 重启都执行,一个展示列的迁移绝不能拖垮整个交易
    监控服务的 startup(score/warn_level 缺了候选照跑,只是不显示分数/红标)。

    **为何 ALTER 不 DROP**(plan §4.1 否决方案②):pending_backfill_entries 的回填扫描
    FROM candidates LEFT JOIN candidate_outcomes 读 candidates 表**历史行**找未回填样本,
    DROP 重建会丢掉"已产候选但回测未回填(entry_date 距今不足 4 交易日)"的历史行,导致
    这批候选的回测样本永久丢失。故 candidates 表历史行不可 DROP,必须走 ALTER 保留历史。

    **v1.3.1 A2.5 新增 warn_level TEXT**(第四次真 migration):候选高位分级(红/琥珀)
    经 candidates 缓存表往返展示,不做此列会导致 warnLevel 字段在 upsert 时被逐列白名单
    INSERT 静默丢弃、GET /candidates 读不回,红标功能生产静默失效(致命#1)。
    """
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(candidates)")}  # row[1] = 列名
        if "score" not in existing:
            conn.execute("ALTER TABLE candidates ADD COLUMN score INTEGER")
        if "warn_level" not in existing:
            conn.execute("ALTER TABLE candidates ADD COLUMN warn_level TEXT")
    except Exception:
        log.error("candidates 补列(score/warn_level)迁移异常(已吞,不拖垮 startup)", exc_info=True)


def _ensure_v130_columns(conn: sqlite3.Connection) -> None:
    """v1.3.0 合并 migration(项目第三次真 migration,🔴高危区)。

    一次补 positions.industry(②相关性护栏,开仓落库,本 Phase 只建列不写值)+
    trades.qty/fee/net_pnl_amount(④净额复盘,清仓落库)。与 _ensure_trades_columns /
    _ensure_candidates_columns 完全同套姿势:PRAGMA table_info 精确集合探测 → 缺列则
    ALTER TABLE ADD COLUMN;整段 try/except **只 log.error,不 re-raise**——init_db 跑在
    app.py lifespan 启动路径、每次 ECS 重启都执行,迁移绝不能拖垮整个交易监控服务的 startup。

    **positions/trades 有真实持仓/成交数据,故 ALTER 不 DROP 重建**(存量已闭合 trades
    的三新列为 NULL,净额契约 nullable,读旧行原样传 null;存量 holding 的 industry
    为 NULL,相关性护栏对 NULL 行业跳过、降级不误报)。三新列均 nullable(无 NOT NULL /
    无默认值),存量行不受影响。

    **🔵4 迁移失败后果差异**:新列 INSERT 硬编落在开仓 + 清仓两条关键录入路径,迁移
    静默失败 = 录不了仓(比阶段3"少个展示列"重);仍用只 log 不 re-raise 的既有姿势
    (不为此改 fail-fast——录入路径本就有 try/except → 409/404 兜底),Plan §4 已接受。
    """
    try:
        pos_cols = {row[1] for row in conn.execute("PRAGMA table_info(positions)")}  # row[1] = 列名
        if "industry" not in pos_cols:
            conn.execute("ALTER TABLE positions ADD COLUMN industry TEXT")
        trade_cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
        for col, coltype in (("qty", "INTEGER"), ("fee", "REAL"), ("net_pnl_amount", "REAL")):
            if col not in trade_cols:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {coltype}")
    except Exception:
        log.error(
            "v1.3.0 补列(positions.industry + trades.qty/fee/net_pnl_amount)迁移异常"
            "(已吞,不拖垮 startup)",
            exc_info=True,
        )


def init_db(db_path: Optional[str] = None) -> str:
    """建表(幂等)+ trades/candidates 补列迁移。返回落库路径。"""
    path = _db_path(db_path)
    conn = get_connection(path)
    try:
        conn.executescript(_SCHEMA)
        _ensure_trades_columns(conn)        # 阶段3 G3:trades 补 name/note(幂等,失败不拖垮)
        _ensure_candidates_columns(conn)    # 阶段3.1:candidates 补 score(幂等,失败不拖垮)
        _ensure_v130_columns(conn)          # v1.3.0:positions.industry + trades.qty/fee/net_pnl_amount
        conn.commit()
    finally:
        conn.close()
    return path
