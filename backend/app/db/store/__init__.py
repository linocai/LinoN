"""SQLite 存储层(plan §4)。

原 `app/db/store.py`(909 行 god-module)按实体拆为本包,**公开 API 与拆包前逐字节等价**
——所有调用点(`from app.db.store import X` / `store.X` / `store_mod.X`)零改动。子模块:

  constants     规则常量单一事实源(-5.0/+15.0/D4/容差带、MAX_HOLDINGS)——只此一处定义
  _common       连接/时间/路径底层工具(get_connection / _now / _db_path)
  schema        建表 DDL + 迁移(_ensure_trades_columns / _ensure_candidates_columns / _ensure_v130_columns)+ init_db
  positions     持仓开/清仓 + 在持查询 + 派生止损止盈 + 机械纪律判定
  trades        trades 只读聚合(复盘打分数据源)
  review        reviews / memory 读写(复盘注记 + 闭环结论沉淀)
  device_tokens APNs device token 注册
  candidates    候选缓存表 upsert/list
  outcomes      回测 candidate_outcomes / analysis_verdicts + 待回填扫描

注:plan DDL 是后端 schema 权威。客户端 Models.swift 的 name/note 展示列由 schema 迁移补充。
"""

from app.db.store._common import _db_path, _now, get_connection
from app.db.store.candidates import (
    _CANDIDATE_KEYS,
    candidate_entry_date_of,
    latest_candidate_date,
    list_candidates,
    upsert_candidates,
)
from app.db.store.constants import (
    FORCE_CLOSE_TRADE_DAY,
    MAX_HOLDINGS,
    STOP_KEPT_HIGH,
    STOP_KEPT_LOW,
    STOP_RATIO,
    STOP_TRIGGER_PCT,
    TAKE_RATIO,
    TAKE_TRIGGER_PCT,
)
from app.db.store.device_tokens import list_device_tokens, upsert_device_token
from app.db.store.outcomes import (
    get_verdict,
    list_outcomes,
    pending_backfill_entries,
    upsert_analysis_verdict,
    upsert_candidate_outcome,
)
from app.db.store.positions import (
    _compute_kept_flags,
    close_position,
    get_holding_by_code,
    get_position,
    holding_count,
    list_holdings,
    open_position,
    stop_line,
    take_line,
)
from app.db.store.review import (
    get_review_note,
    insert_memory,
    insert_review,
    list_memory,
    upsert_review_note,
)
from app.db.store.schema import (
    _SCHEMA,
    _ensure_candidates_columns,
    _ensure_trades_columns,
    _ensure_v130_columns,
    init_db,
)
from app.db.store.trades import list_all_trades, list_closed_trades

__all__ = [
    # 常量(单一事实源)
    "STOP_RATIO", "TAKE_RATIO", "STOP_TRIGGER_PCT", "TAKE_TRIGGER_PCT",
    "STOP_KEPT_LOW", "STOP_KEPT_HIGH", "FORCE_CLOSE_TRADE_DAY", "MAX_HOLDINGS",
    # 连接/建表/迁移
    "get_connection", "init_db",
    # 持仓
    "stop_line", "take_line", "open_position", "list_holdings",
    "get_holding_by_code", "get_position", "holding_count", "close_position",
    # trades / 复盘 / 记忆
    "list_closed_trades", "list_all_trades",
    "insert_review", "insert_memory", "list_memory",
    "upsert_review_note", "get_review_note",
    # 设备 token
    "upsert_device_token", "list_device_tokens",
    # 候选 / 回测
    "upsert_candidates", "list_candidates", "latest_candidate_date",
    "candidate_entry_date_of", "upsert_candidate_outcome", "list_outcomes",
    "pending_backfill_entries", "get_verdict", "upsert_analysis_verdict",
]
