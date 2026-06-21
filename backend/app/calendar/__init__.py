"""交易日历原语(静态 2025–2026 沪市兜底 + trade_cal 驱动)。

注意:本包名为 `calendar`,与标准库同名。包内一律用【绝对导入】
(`from app.calendar.trading_calendar import ...`),不要 `import calendar`
期望拿到标准库——会拿到本包。需要标准库日历时显式 `import calendar as _stdcal`
亦有歧义,故本包内不依赖标准库 calendar。
"""

from app.calendar.trading_calendar import (
    count_holding_trade_days,
    is_trading_day,
    next_trading_day,
    prev_trading_day,
    should_force_close,
    trading_window,
)

__all__ = [
    "is_trading_day",
    "next_trading_day",
    "prev_trading_day",
    "trading_window",
    "count_holding_trade_days",
    "should_force_close",
]
