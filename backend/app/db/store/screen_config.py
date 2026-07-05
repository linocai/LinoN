"""选股配置存取(v1.3.1 Phase B1)。

单行表 `screen_config`(id 恒 1),存**用户增量**配置(只存显式提交的键,非全量)。
默认值单一源仍在 `app.screen.rules.DEFAULT_SCREEN_CONFIG`(由常量/WEIGHTS 引用构造);
本模块只做"读一行 JSON / upsert 一行 JSON",不碰默认值、不做校验/归一(那是
`rules.resolve_screen_config`/`validate_screen_config` 的职责,plan §4 Phase B2)。

无行/JSON 损坏 → get 返回空 dict `{}`,由上层(resolve_screen_config)合默认——绝不崩。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.db.store._common import _now, get_connection

log = logging.getLogger(__name__)


def get_screen_config(db_path: Optional[str] = None) -> Dict[str, Any]:
    """读用户增量配置(单行 JSON)。无行 / JSON 损坏 → 返回空 dict(由上层合默认,不崩)。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT config_json FROM screen_config WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {}
    raw = row["config_json"]
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("screen_config.config_json 解析失败(已损坏),降级为空 dict")
        return {}
    if not isinstance(data, dict):
        log.warning("screen_config.config_json 非 dict 形状,降级为空 dict")
        return {}
    return data


def put_screen_config(cfg: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """upsert 用户增量配置(id=1 单行,覆盖式全量替换该行 JSON)。

    cfg 是**调用方已逐键夹紧过**的增量(见 rules.validate_screen_config);本函数只负责
    落库,不再校验。cfg 传空 dict `{}` → 存空增量(= 恢复默认,resolve 时全回默认值,
    plan §4 Phase B2「恢复默认」契约)。
    """
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO screen_config (id, config_json, updated_at)
               VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 config_json = excluded.config_json,
                 updated_at = excluded.updated_at""",
            (json.dumps(cfg, ensure_ascii=False), _now()),
        )
        conn.commit()
    finally:
        conn.close()


def get_screen_config_updated_at(db_path: Optional[str] = None) -> Optional[str]:
    """读用户配置最近一次写入时间(GET 端点 updated_at 字段);无行 → None。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT updated_at FROM screen_config WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    return row["updated_at"] if row else None
