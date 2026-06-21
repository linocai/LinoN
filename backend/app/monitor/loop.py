"""监控后台轮询任务(阶段1 A.3+A.4+A.5,单 unit 架构)。

单 unit(plan 已定):FastAPI 与监控同机,API 内起后台 asyncio 任务,不另起进程。

轮询循环:
  · 用 trading_window(today) 判交易时段;非交易时段休眠(粗轮询,省 CPU)。
  · 交易时段每 ~60s:拉在持仓票实时价(get_realtime_quotes)→ 两源一致性校验
    → classify 产出硬线事件 → 喂 EscalationManager → due_pushes → 真发 APNs(遍历 device_tokens)。
  · 收盘后(~15:05 过一次)对每持仓推 EOD 摘要(每自然交易日仅一次)。

可注入:push_fn(默认 apns.send_push)、quotes_fn(默认 get_realtime_quotes)、clock,
便于单测在不联网/不真推的前提下驱动一轮。

EscalationManager 单例随 app 生命周期常驻(app.state.escalation 持有)。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time
from typing import Callable, Dict, List, Optional

from app.calendar.trading_calendar import trading_window
from app.config import settings
from app.db import store
from app.monitor.escalation import EscalationManager
from app.monitor.hardline import (
    HardlineEvent,
    classify,
    quotes_consistent,
)
from app.monitor.eod import build_eod_summaries
from app.push import apns

logger = logging.getLogger(__name__)

# 交易时段轮询间隔(秒)
POLL_INTERVAL_SEC = 60
# 非交易时段休眠(秒,粗轮询)
IDLE_SLEEP_SEC = 300
# 收盘判定:15:00 收盘,留 5min 让 EOD 数据稳定
_EOD_AFTER = time(15, 5)


def _is_trading_now(now: datetime) -> bool:
    """当前是否处于交易时段(任一段窗口内)。"""
    win = trading_window(now.date())
    if win is None:
        return False
    t = now.time()
    return any(o <= t <= c for (o, c) in win)


def _is_after_close(now: datetime) -> bool:
    """是否已过收盘(交易日且 >= 15:05)。"""
    return trading_window(now.date()) is not None and now.time() >= _EOD_AFTER


def _build_two_source_quotes(codes: List[str]) -> Dict[str, dict]:
    """拉两源现价用于一致性校验(新浪 + 腾讯各拉一遍)。

    返回 {code: {"sina": Quote|None, "tencent": Quote|None}}。
    复用 realtime 内部 fetch;为简洁直接用 get_realtime_quotes(主源)+ 单独腾讯探测。
    """
    from app.data import realtime
    out: Dict[str, dict] = {c: {"sina": None, "tencent": None} for c in codes}
    syms = {realtime.to_symbol(c): c for c in codes}
    # 新浪
    sina_raw = realtime._fetch_sina(list(syms.keys()))
    for sym, body in sina_raw.items():
        q = realtime._parse_sina(sym, body)
        if q is not None and sym in syms:
            out[syms[sym]]["sina"] = q
    # 腾讯
    tx_raw = realtime._fetch_tencent(list(syms.keys()))
    for sym, body in tx_raw.items():
        q = realtime._parse_tencent(sym, body)
        if q is not None and sym in syms:
            out[syms[sym]]["tencent"] = q
    return out


def run_one_tick(
    *,
    esc: EscalationManager,
    now: datetime,
    quotes_fn: Optional[Callable[[List[str]], Dict[str, object]]] = None,
    two_source_fn: Optional[Callable[[List[str]], Dict[str, dict]]] = None,
    push_fn: Optional[Callable[..., object]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, object]:
    """执行一轮监控(纯过程,可单测):拉价 → 判硬线 → 升级 → 推送。

    返回本轮摘要 {events, pushes}(供测试断言/日志)。不联网时注入 fns。
    """
    quotes_fn = quotes_fn or _default_quotes_fn
    two_source_fn = two_source_fn or _build_two_source_quotes
    push_fn = push_fn or apns.send_push

    holdings = store.list_holdings(db_path)
    if not holdings:
        return {"events": [], "pushes": 0, "holdings": 0}

    codes = [h["code"] for h in holdings]
    quotes = quotes_fn(codes)
    two_src = two_source_fn(codes)

    all_events: List[HardlineEvent] = []
    for h in holdings:
        code = h["code"]
        q = quotes.get(code)
        if q is None:
            continue
        price = q.price if hasattr(q, "price") else q.get("price", 0.0)
        pre_close = q.pre_close if hasattr(q, "pre_close") else q.get("pre_close", 0.0)
        limit_up = q.limit_up if hasattr(q, "limit_up") else q.get("limit_up", 0.0)
        limit_down = q.limit_down if hasattr(q, "limit_down") else q.get("limit_down", 0.0)

        # 两源一致性
        srcs = two_src.get(code, {})
        sa, sb = srcs.get("sina"), srcs.get("tencent")
        suspect = False
        if sa is not None and sb is not None:
            suspect = not quotes_consistent(
                sa.pre_close, sa.price, sb.pre_close, sb.price
            )

        events = classify(
            code=code, name=h["name"], buy_price=h["buy_price"],
            price=price, pre_close=pre_close,
            limit_up=limit_up, limit_down=limit_down,
            buy_date=h["buy_date"], today=now.date(),
            quote_suspect=suspect,
        )
        for ev in events:
            all_events.append(ev)
            esc.register(ev, now=now)

    # 升级器决定本轮该推的
    tokens = store.list_device_tokens(db_path)
    pushes = 0
    for tr, badge in esc.due_pushes(now=now):
        ev = tr.event
        for dt in tokens:
            push_fn(
                dt["token"], ev.title, ev.body,
                category=apns.CATEGORY_HARDLINE,
                thread_id=ev.code,
                badge_escalation=badge,
                custom={"code": ev.code, "kind": ev.kind, "escalation": badge},
            )
            pushes += 1
        esc.mark_pushed(tr, now=now)

    return {"events": all_events, "pushes": pushes, "holdings": len(holdings)}


def run_eod_tick(
    *,
    now: datetime,
    quotes_fn: Optional[Callable[[List[str]], Dict[str, object]]] = None,
    push_fn: Optional[Callable[..., object]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, object]:
    """收盘后对每持仓推一条 EOD 摘要(category 普通)。返回 {summaries, pushes}。"""
    quotes_fn = quotes_fn or _default_quotes_fn
    push_fn = push_fn or apns.send_push

    holdings = store.list_holdings(db_path)
    if not holdings:
        return {"summaries": [], "pushes": 0}

    codes = [h["code"] for h in holdings]
    quotes = quotes_fn(codes)
    summaries = build_eod_summaries(holdings, quotes, today=now.date())

    tokens = store.list_device_tokens(db_path)
    pushes = 0
    for s in summaries:
        for dt in tokens:
            push_fn(
                dt["token"], s.title, s.body,
                category=apns.CATEGORY_EOD,
                thread_id=s.code,
                custom={"code": s.code, "kind": "eod"},
            )
            pushes += 1
    return {"summaries": summaries, "pushes": pushes}


def _default_quotes_fn(codes: List[str]) -> Dict[str, object]:
    from app.data.realtime import get_realtime_quotes
    return get_realtime_quotes(codes)


async def monitor_loop(esc: EscalationManager, stop_event: asyncio.Event) -> None:
    """常驻后台轮询协程。stop_event 置位时优雅退出。

    交易时段每 POLL_INTERVAL_SEC 跑 run_one_tick;非交易时段粗休眠。
    收盘后(每交易日一次)跑 run_eod_tick。
    """
    last_eod_date: Optional[date] = None
    logger.info("监控轮询启动(单 unit;sandbox=%s)", settings.APNS_USE_SANDBOX)
    while not stop_event.is_set():
        now = datetime.now()
        try:
            if _is_trading_now(now):
                await asyncio.to_thread(run_one_tick, esc=esc, now=now)
                sleep_for = POLL_INTERVAL_SEC
            elif _is_after_close(now) and last_eod_date != now.date():
                await asyncio.to_thread(run_eod_tick, now=now)
                last_eod_date = now.date()
                sleep_for = IDLE_SLEEP_SEC
            else:
                sleep_for = IDLE_SLEEP_SEC
        except Exception as e:  # 轮询任何异常不得掀翻常驻协程
            logger.exception("监控轮询单轮异常(已吞,继续): %s", e)
            sleep_for = POLL_INTERVAL_SEC
        # 可中断休眠:stop_event 置位即醒
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=sleep_for)
        except asyncio.TimeoutError:
            pass
    logger.info("监控轮询退出")
