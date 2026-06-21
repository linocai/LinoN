"""pydantic-settings 驱动的配置。

锁定(plan §2 / Phase 0.1):
  · 用 pydantic-settings 读 .env;.env 进 gitignore。
  · 字段:TUSHARE_TOKEN(占位可空)、DEEPSEEK_API_KEY(留空)、DB_PATH(默认落盘路径)。
  · .env 缺失 / 字段缺失【不许崩】,缺失 token 字段为 None/空串。

实现说明:
  主路径用 pydantic-settings(BaseSettings)。为了让 Phase 0.1 验收
  (`python -c "from app.config import settings"`)在依赖尚未 pip install 时也能跑通,
  这里保留一个极简标准库 fallback —— 仅当 pydantic-settings 未安装时启用,
  行为(字段名/默认值/.env 读取)与主路径一致,绝不掩盖 ECS 上的正式安装。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# backend/ 目录(本文件在 backend/app/config/settings.py,上溯 3 层)
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = str(_BACKEND_DIR / "data" / "linon.db")
_ENV_FILE = _BACKEND_DIR / ".env"

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        """从 .env 读取的运行配置(pydantic-settings 主路径)。"""

        TUSHARE_TOKEN: Optional[str] = None
        DEEPSEEK_API_KEY: Optional[str] = None
        DB_PATH: str = _DEFAULT_DB_PATH

        model_config = SettingsConfigDict(
            env_file=str(_ENV_FILE),
            env_file_encoding="utf-8",
            extra="ignore",          # .env 里多余字段忽略,不崩
            case_sensitive=False,
        )

        @property
        def has_tushare_token(self) -> bool:
            return bool(self.TUSHARE_TOKEN and self.TUSHARE_TOKEN.strip())

        @property
        def has_deepseek_key(self) -> bool:
            return bool(self.DEEPSEEK_API_KEY and self.DEEPSEEK_API_KEY.strip())

    _BACKEND = "pydantic-settings"

except ImportError:  # pragma: no cover - 仅在依赖未装时走到
    # —— 极简 fallback:仅供「依赖未 pip install」时让 import 不崩 ——
    def _load_env_file(path: Path) -> dict:
        out: dict = {}
        if not path.is_file():
            return out
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                out[key.strip().upper()] = val.strip().strip('"').strip("'")
        except OSError:
            pass
        return out

    class Settings:  # type: ignore[no-redef]
        """标准库 fallback,字段/默认值与主路径一致。"""

        def __init__(self) -> None:
            file_vals = _load_env_file(_ENV_FILE)

            def pick(key: str, default: Optional[str]) -> Optional[str]:
                if key in os.environ:
                    return os.environ[key]
                if key in file_vals:
                    return file_vals[key]
                return default

            self.TUSHARE_TOKEN: Optional[str] = pick("TUSHARE_TOKEN", None)
            self.DEEPSEEK_API_KEY: Optional[str] = pick("DEEPSEEK_API_KEY", None)
            self.DB_PATH: str = pick("DB_PATH", _DEFAULT_DB_PATH) or _DEFAULT_DB_PATH

        @property
        def has_tushare_token(self) -> bool:
            return bool(self.TUSHARE_TOKEN and self.TUSHARE_TOKEN.strip())

        @property
        def has_deepseek_key(self) -> bool:
            return bool(self.DEEPSEEK_API_KEY and self.DEEPSEEK_API_KEY.strip())

    _BACKEND = "stdlib-fallback"


# 单例:全后端共用
settings = Settings()
