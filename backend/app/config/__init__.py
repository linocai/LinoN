"""配置模块。对外只暴露单例 `settings`。

用法:
    from app.config import settings
    settings.TUSHARE_TOKEN   # 可空(占位)
    settings.DB_PATH         # SQLite 落盘路径(默认 backend/data/linon.db)

.env 缺失或字段缺失一律不崩(见 Phase 0.1 验收)。
"""

from app.config.settings import Settings, settings

__all__ = ["Settings", "settings"]
