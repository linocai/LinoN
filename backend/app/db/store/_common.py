"""连接/时间/路径底层工具(store 包内共享,不对外)。"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings

log = logging.getLogger(__name__)


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
