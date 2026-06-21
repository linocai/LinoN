#!/usr/bin/env python3
"""冒烟脚本(plan §4 Phase 0.7)—— 阶段0 总验收的可见出口。

一次性可见:
  ① 拉一只票实时价并打印 Quote(新浪主/腾讯降级)
  ② 有 token 时拉一条 daily + 一条 moneyflow 打印;无 token 打印「已降级:token 缺失」
  ③ 打印 today 附近交易日历(prev / today / next + 是否交易日)
  ④ 建库(调 0.4 init_db)

验收即「数据能稳定拉」。运行:
  source .venv/bin/activate && python scripts/smoke.py
  或指定测试票:python scripts/smoke.py 600519
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# 允许从 backend/ 任意位置运行:把 backend/ 加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.calendar import (  # noqa: E402
    is_trading_day,
    next_trading_day,
    prev_trading_day,
    trading_window,
)
from app.config import settings  # noqa: E402
from app.data import (  # noqa: E402
    get_realtime_quote,
    ts_daily,
    ts_moneyflow,
)
from app.db import init_db  # noqa: E402


def _hr(title: str) -> None:
    print("\n" + "=" * 56)
    print(f"  {title}")
    print("=" * 56)


def smoke_realtime(code: str) -> None:
    _hr(f"① 实时价(新浪主→腾讯降级) code={code}")
    q = get_realtime_quote(code)
    if q is None:
        print("  ⚠ 未拉到(可能非交易时段且源无快照 / 无网 / 代码非法)。")
        print("    待联调:联网且交易时段对真实在交易票复测。")
        return
    print(f"  source     : {q.source}")
    print(f"  name/code  : {q.name} / {q.code}")
    print(f"  price      : {q.price}   pre_close: {q.pre_close}")
    print(f"  open/hi/lo : {q.open} / {q.high} / {q.low}")
    print(f"  limit_up   : {q.limit_up}   limit_down: {q.limit_down}")
    print(f"  volume(手) : {q.volume}   amount(元): {q.amount}")
    print(f"  bid1/ask1  : {q.bid[0] if q.bid else '—'} / {q.ask[0] if q.ask else '—'}")
    print(f"  ts         : {q.ts}")


def smoke_tushare(code: str) -> None:
    _hr("② Tushare(按 token 有无给出对应结果)")
    if not settings.has_tushare_token:
        print("  已降级:token 缺失 —— ts_daily / ts_moneyflow 返回 ok=False。")
        d = ts_daily(code, "20260601", "20260618")
        m = ts_moneyflow(code, "20260601", "20260618")
        print(f"    ts_daily    : ok={d.ok} reason={d.reason!r}")
        print(f"    ts_moneyflow: ok={m.ok} reason={m.reason!r}")
        print("    待联调:用户购入 2000 积分 token 录入 .env 后真拉一条 daily/moneyflow。")
        return
    print("  token 已配置,真拉一条 daily + 一条 moneyflow:")
    d = ts_daily(code, "20260601", "20260618")
    if d.ok and d.data is not None and len(d.data):
        print(f"    daily      : ok=True 行数={len(d.data)} 首行:")
        print(d.data.head(1).to_string(index=False))
    else:
        print(f"    daily      : ok={d.ok} reason={d.reason!r}")
    m = ts_moneyflow(code, "20260601", "20260618")
    if m.ok and m.data is not None and len(m.data):
        print(f"    moneyflow  : ok=True 行数={len(m.data)} 首行:")
        print(m.data.head(1).to_string(index=False))
    else:
        print(f"    moneyflow  : ok={m.ok} reason={m.reason!r}")


def smoke_calendar() -> None:
    _hr("③ 交易日历(today 附近)")
    today = date.today()
    prev_d = prev_trading_day(today)
    next_d = next_trading_day(today)
    print(f"  today      : {today}  交易日={is_trading_day(today)}")
    print(f"  prev_trade : {prev_d}")
    print(f"  next_trade : {next_d}")
    win = trading_window(today)
    if win is None:
        print("  trading_window(today): None(今日非交易日)")
    else:
        am, pm = win
        print(f"  trading_window(today): 上午 {am[0]}–{am[1]}  下午 {pm[0]}–{pm[1]}")


def smoke_db() -> None:
    _hr("④ 建库(SQLite 四表)")
    path = init_db()
    print(f"  DB ready   : {path}")


def main() -> int:
    code = sys.argv[1] if len(sys.argv) > 1 else "603986"
    print("LinoN 冒烟脚本 —— 阶段0 总验收:数据能稳定拉")
    print(f"  config backend: {__import__('app.config.settings', fromlist=['_BACKEND'])._BACKEND}")
    smoke_realtime(code)
    smoke_tushare(code)
    smoke_calendar()
    smoke_db()
    print("\n冒烟完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
