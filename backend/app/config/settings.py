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

        # —— 阶段1 track A:API 鉴权(单用户共享密钥)——
        API_TOKEN: Optional[str] = None

        # —— 阶段1 track A:APNs token-based 推送 ——
        APNS_KEY_ID: Optional[str] = None
        APNS_TEAM_ID: Optional[str] = None
        APNS_BUNDLE_ID: Optional[str] = None
        APNS_KEY_PATH: Optional[str] = None        # .p8 私钥文件路径(secret,不入 git)
        APNS_USE_SANDBOX: bool = True              # dev 直装走 sandbox 网关
        ESCALATE_INTERVAL_MIN: int = 15            # 硬线未 ack 的升级重复间隔(分钟)

        # —— v1.3.0 Phase B1:交易成本费率(沪深口径,费用单一源;公式在 app/trade/costs.py)——
        COMMISSION_RATE: float = 0.00028           # 佣金率(万2.8,买卖各一次)
        COMMISSION_MIN: float = 5.0                # 最低佣金(元/笔)
        STAMP_TAX_RATE: float = 0.0005             # 卖出印花税(0.05%,仅卖出)
        TRANSFER_FEE_RATE: float = 0.00001         # 过户费率(0.001%,沪深买卖双边)

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

        @property
        def has_api_token(self) -> bool:
            return bool(self.API_TOKEN and self.API_TOKEN.strip())

        @property
        def has_apns_config(self) -> bool:
            """APNs 凭证齐全(KeyID/TeamID/BundleID/.p8 路径都在)才能真推。"""
            return bool(
                self.APNS_KEY_ID and self.APNS_TEAM_ID
                and self.APNS_BUNDLE_ID and self.APNS_KEY_PATH
            )

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

            def pick_bool(key: str, default: bool) -> bool:
                raw = pick(key, None)
                if raw is None:
                    return default
                return raw.strip().lower() in ("1", "true", "yes", "on")

            def pick_int(key: str, default: int) -> int:
                raw = pick(key, None)
                try:
                    return int(raw) if raw is not None else default
                except (ValueError, TypeError):
                    return default

            def pick_float(key: str, default: float) -> float:
                raw = pick(key, None)
                try:
                    return float(raw) if raw is not None else default
                except (ValueError, TypeError):
                    return default

            self.TUSHARE_TOKEN: Optional[str] = pick("TUSHARE_TOKEN", None)
            self.DEEPSEEK_API_KEY: Optional[str] = pick("DEEPSEEK_API_KEY", None)
            self.DB_PATH: str = pick("DB_PATH", _DEFAULT_DB_PATH) or _DEFAULT_DB_PATH
            self.API_TOKEN: Optional[str] = pick("API_TOKEN", None)
            self.APNS_KEY_ID: Optional[str] = pick("APNS_KEY_ID", None)
            self.APNS_TEAM_ID: Optional[str] = pick("APNS_TEAM_ID", None)
            self.APNS_BUNDLE_ID: Optional[str] = pick("APNS_BUNDLE_ID", None)
            self.APNS_KEY_PATH: Optional[str] = pick("APNS_KEY_PATH", None)
            self.APNS_USE_SANDBOX: bool = pick_bool("APNS_USE_SANDBOX", True)
            self.ESCALATE_INTERVAL_MIN: int = pick_int("ESCALATE_INTERVAL_MIN", 15)
            # —— v1.3.0 Phase B1:交易成本费率(与主路径字段/默认值一致)——
            self.COMMISSION_RATE: float = pick_float("COMMISSION_RATE", 0.00028)
            self.COMMISSION_MIN: float = pick_float("COMMISSION_MIN", 5.0)
            self.STAMP_TAX_RATE: float = pick_float("STAMP_TAX_RATE", 0.0005)
            self.TRANSFER_FEE_RATE: float = pick_float("TRANSFER_FEE_RATE", 0.00001)

        @property
        def has_tushare_token(self) -> bool:
            return bool(self.TUSHARE_TOKEN and self.TUSHARE_TOKEN.strip())

        @property
        def has_deepseek_key(self) -> bool:
            return bool(self.DEEPSEEK_API_KEY and self.DEEPSEEK_API_KEY.strip())

        @property
        def has_api_token(self) -> bool:
            return bool(self.API_TOKEN and self.API_TOKEN.strip())

        @property
        def has_apns_config(self) -> bool:
            return bool(
                self.APNS_KEY_ID and self.APNS_TEAM_ID
                and self.APNS_BUNDLE_ID and self.APNS_KEY_PATH
            )

    _BACKEND = "stdlib-fallback"


# 单例:全后端共用
settings = Settings()
