"""FastAPI 应用主体(阶段1 A.1/A.2/A.4 ack + 单 unit 后台监控挂载)。

绑 127.0.0.1:8001(nginx 反代)。/api/v1/health 免鉴权;其余端点过 require_token。
startup:fail-fast 校验 API_TOKEN(len>=16)+ init_db + 起后台监控轮询任务。
shutdown:置位 stop_event,优雅停轮询。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status

from app.api.deps import require_api_token_ready, require_token
from app.api.schemas import (
    AlertAck,
    DeviceRegister,
    PositionClose,
    PositionOpen,
    PositionOut,
    PositionsList,
)
from app.calendar.trading_calendar import (
    count_holding_trade_days,
    prev_trading_day,
    is_trading_day,
)
from app.config import settings
from app.db import store
from app.monitor.escalation import EscalationManager

logger = logging.getLogger(__name__)

VERSION = "1.0.0-stage1A"
API_PREFIX = "/api/v1"

# 是否在 startup 起后台监控轮询(测试时可置 False,避免后台任务干扰)。
ENABLE_MONITOR = True


def _current_trade_date() -> str:
    """当前交易日 'YYYY-MM-DD':今天是交易日用今天,否则用上一交易日。"""
    from datetime import date
    today = date.today()
    d = today if is_trading_day(today) else prev_trading_day(today)
    return d.strftime("%Y-%m-%d")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # —— startup ——
    require_api_token_ready()           # fail-fast:API_TOKEN len>=16
    store.init_db()
    app.state.escalation = EscalationManager(
        interval_min=settings.ESCALATE_INTERVAL_MIN
    )
    app.state._stop_event = asyncio.Event()
    app.state._monitor_task = None
    if ENABLE_MONITOR:
        from app.monitor.loop import monitor_loop
        app.state._monitor_task = asyncio.create_task(
            monitor_loop(app.state.escalation, app.state._stop_event)
        )
        logger.info("后台监控轮询已挂载(单 unit)")
    yield
    # —— shutdown ——
    app.state._stop_event.set()
    task = app.state._monitor_task
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()


app = FastAPI(title="LinoN", version=VERSION, lifespan=lifespan)


# —— health(免鉴权)————————————————————————————————————————————————

@app.get(f"{API_PREFIX}/health")
def health() -> dict:
    return {"status": "ok", "version": VERSION}


# —— A.1 设备注册 ————————————————————————————————————————————————————

@app.post(f"{API_PREFIX}/devices", dependencies=[Depends(require_token)])
def register_device(body: DeviceRegister) -> dict:
    store.upsert_device_token(body.token, body.platform)
    return {"ok": True}


# —— A.2 开仓 ————————————————————————————————————————————————————————

@app.post(f"{API_PREFIX}/positions/open", dependencies=[Depends(require_token)])
def open_position(body: PositionOpen):
    # 重复 code 防护(漏录/幽灵持仓)
    if store.get_holding_by_code(body.code) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"ok": False, "reason": "duplicate_holding"},
        )
    # 满仓防护
    if store.holding_count() >= store.MAX_HOLDINGS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"ok": False, "reason": "slots_full"},
        )

    buy_date = _current_trade_date()
    # name 缺省时尝试实时源补,补不到留 code(不阻塞录入)
    name = (body.name or "").strip()
    if not name:
        name = _resolve_name(body.code) or body.code

    # entry_snapshot 系统自动补(开仓瞬间形态/资金快照占位串)
    entry_snapshot = {
        "formNote": f"开仓@{buy_date} 买入价 {body.buy_price}",
        "fundNote": "资金快照:阶段2 接 Tushare 补",
    }

    try:
        pid = store.open_position(
            code=body.code, name=name, buy_price=body.buy_price, qty=body.qty,
            entry_reason=body.entry_reason, buy_date=buy_date,
            entry_snapshot=entry_snapshot,
        )
    except ValueError:
        # 并发兜底:open_position 内部满仓 ValueError
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"ok": False, "reason": "slots_full"},
        )

    return {
        "ok": True,
        "position_id": pid,
        "stop_line": store.stop_line(body.buy_price),
        "take_line": store.take_line(body.buy_price),
        "buy_date": buy_date,
    }


# —— A.2 清仓 ————————————————————————————————————————————————————————

@app.post(f"{API_PREFIX}/positions/{{position_id}}/close",
          dependencies=[Depends(require_token)])
def close_position(position_id: int, body: PositionClose):
    pos = store.get_position(position_id)
    if pos is None or pos["status"] != "holding":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "reason": "not_holding"},
        )

    # 持仓交易日计数(用于 kept_time 机械判定)
    from datetime import date
    htd = count_holding_trade_days(pos["buy_date"], date.today())

    try:
        trade_id = store.close_position(
            position_id=position_id,
            close_price=body.sell_price,
            close_time=body.sell_time,
            holding_trade_days=htd,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "reason": "not_holding"},
        )

    # 回读该 trade 的机械判定结果
    flags = _read_trade_flags(trade_id)
    return {
        "ok": True,
        "trade_id": trade_id,
        "pnl": flags["pnl"],
        "kept_stop": bool(flags["kept_stop"]),
        "kept_take": bool(flags["kept_take"]),
        "kept_time": bool(flags["kept_time"]),
        "broke_rule": bool(flags["broke_rule"]),
    }


# —— A.2 列持仓 ——————————————————————————————————————————————————————

@app.get(f"{API_PREFIX}/positions", dependencies=[Depends(require_token)])
def list_positions() -> PositionsList:
    holdings = store.list_holdings()
    out = []
    for h in holdings:
        out.append(PositionOut(
            id=h["id"], code=h["code"], name=h["name"],
            buy_price=h["buy_price"], qty=h["qty"],
            entry_reason=h["entry_reason"], buy_date=h["buy_date"],
            status=h["status"],
            price=h.get("price", 0.0) or 0.0,
            flow3d=h.get("flow3d", "—") or "—",
        ))
    free = max(0, store.MAX_HOLDINGS - len(out))
    return PositionsList(holdings=out, free_slots=free)


# —— A.4 硬线 ack ————————————————————————————————————————————————————

@app.post(f"{API_PREFIX}/alerts/{{code}}/ack", dependencies=[Depends(require_token)])
def ack_alert(code: str, body: AlertAck) -> dict:
    esc: EscalationManager = app.state.escalation
    n = esc.ack(code, body.action)
    return {"ok": True, "stopped": n}


# —— 内部工具 ————————————————————————————————————————————————————————

def _resolve_name(code: str) -> str:
    """尝试用实时源补股票名;失败返回空串(不阻塞录入)。"""
    try:
        from app.data.realtime import get_realtime_quote
        q = get_realtime_quote(code)
        return q.name if q is not None else ""
    except Exception:
        return ""


def _read_trade_flags(trade_id: int) -> dict:
    conn = store.get_connection()
    try:
        row = conn.execute(
            "SELECT pnl, kept_stop, kept_take, kept_time, broke_rule "
            "FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else {
        "pnl": 0.0, "kept_stop": 0, "kept_take": 0, "kept_time": 0, "broke_rule": 0
    }
