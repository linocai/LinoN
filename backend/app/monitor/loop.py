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

from app.calendar.trading_calendar import (
    count_holding_trade_days,
    trading_window,
)
from app.config import settings
from app.db import store
from app.monitor.escalation import EscalationManager
from app.monitor.hardline import (
    KIND_TIME,
    HardlineEvent,
    _time_event,
    classify,
    pnl_pct_of,
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
    """拉两源现价(新浪 + 腾讯各拉【一次】)。监控一 tick 的唯一拉价口。

    返回 {code: {"sina": Quote|None, "tencent": Quote|None}}。
    每个源对全量 code 只发一次请求;price 与一致性校验都复用这同一对结果
    (审后修复 #1:不再额外调 get_realtime_quotes,免免费源限频/封 IP 翻倍)。
    """
    from app.data import realtime
    out: Dict[str, dict] = {c: {"sina": None, "tencent": None} for c in codes}
    syms = {realtime.to_symbol(c): c for c in codes}
    # 新浪(一次)
    sina_raw = realtime._fetch_sina(list(syms.keys()))
    for sym, body in sina_raw.items():
        q = realtime._parse_sina(sym, body)
        if q is not None and sym in syms:
            out[syms[sym]]["sina"] = q
    # 腾讯(一次)
    tx_raw = realtime._fetch_tencent(list(syms.keys()))
    for sym, body in tx_raw.items():
        q = realtime._parse_tencent(sym, body)
        if q is not None and sym in syms:
            out[syms[sym]]["tencent"] = q
    return out


def _merge_price_quote(srcs: dict):
    """从两源结果派生本票"现价"用 Quote(优先 sina、缺则 tencent;均缺则 None)。

    与 get_realtime_quotes 的降级口径一致(新浪主、腾讯补),但不另发请求。
    """
    if not srcs:
        return None
    return srcs.get("sina") or srcs.get("tencent")


def _ensure_time_escalation(esc: EscalationManager, holding: dict, now: datetime) -> bool:
    """审后修复 #2:逾期在持仓(count≥4)缺 time 升级时补一条(幂等)。

    classify 只在 count==4 产 time 事件;过了 D4(count≥5)不再产,若服务在
    D4 收盘后/夜间重启,内存升级丢失后 D5 不会重建 → D4 无条件清仓逼促永久漏。
    这里对任一 status='holding' 且 count_holding_trade_days≥4 的持仓,保证始终有
    一条 active 未 ack 的 time 升级,直到被 ack 或清仓。

    关键幂等:已存在该 (code, KIND_TIME) 升级时【不动】badge/计数,只在缺失时新建。
    返回 True 表示本次新建,False 表示已存在(未动)。
    """
    code = holding["code"]
    td = count_holding_trade_days(holding["buy_date"], now.date())
    if td < 4:
        return False
    if esc.has_track(code, KIND_TIME):
        return False  # 幂等:已存在(含已 ack)不重建、不重置 badge
    pnl = pnl_pct_of(holding["buy_price"], holding["buy_price"])  # 无价时按 0
    ev = _time_event(holding["name"], code, pnl, td)
    esc.register(ev, now=now)
    return True


def rebuild_time_escalations(esc: EscalationManager, now: datetime, db_path: Optional[str] = None) -> int:
    """启动时从 positions 重建逾期(count≥4)在持仓的 time 升级(审后修复 #2)。

    保证服务重启后,D4+ 在持仓立即重获 active time 升级,不必等下一价格线触发。
    幂等:复用 _ensure_time_escalation(已存在不动)。返回新建条数。
    """
    n = 0
    for h in store.list_holdings(db_path):
        if _ensure_time_escalation(esc, h, now=now):
            n += 1
    return n


def _qattr(q, name: str, default: float = 0.0) -> float:
    """从 Quote(对象)或 dict 取数值字段。"""
    if q is None:
        return default
    if hasattr(q, name):
        return getattr(q, name)
    if isinstance(q, dict):
        return q.get(name, default)
    return default


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

    审后修复 #1:每个源每 tick 只拉一次。price 与一致性校验复用同一对两源结果
      (两源各拉一次 → 派生 merged price:优先 sina、缺则 tencent;一致性校验
       也用这同一对结果,不额外再调 get_realtime_quotes)。
      quotes_fn 仅为向后兼容/测试覆盖保留:显式传入时仍用它供 price,否则
      price 直接从 two_source_fn 结果派生(默认不再二次拉价)。
    审后修复 #2:每 tick 对 count≥4 的逾期在持仓 ensure 一条 active time 升级
      (幂等:已存在则不动 badge/计数),保证 D4 后重启不丢 D4 无条件清仓逼促。
    """
    two_source_fn = two_source_fn or _build_two_source_quotes
    push_fn = push_fn or apns.send_push

    holdings = store.list_holdings(db_path)
    if not holdings:
        # 无持仓也无需 ensure;直接返回
        return {"events": [], "pushes": 0, "holdings": 0}

    codes = [h["code"] for h in holdings]
    two_src = two_source_fn(codes)
    # price 默认从两源结果派生(不二次拉价);仅当显式注入 quotes_fn 时才用它。
    quotes = quotes_fn(codes) if quotes_fn is not None else None

    all_events: List[HardlineEvent] = []
    for h in holdings:
        code = h["code"]
        srcs = two_src.get(code, {}) or {}
        # price 用 Quote:注入了 quotes_fn 取之,否则从两源派生(优先 sina)
        if quotes is not None:
            q = quotes.get(code)
        else:
            q = _merge_price_quote(srcs)

        # 审后修复 #2:逾期在持仓(count≥4)无条件 ensure 一条 time 升级(幂等)
        _ensure_time_escalation(esc, h, now=now)

        if q is None:
            continue
        price = _qattr(q, "price")
        pre_close = _qattr(q, "pre_close")
        limit_up = _qattr(q, "limit_up")
        limit_down = _qattr(q, "limit_down")

        # 两源一致性(复用同一对结果,不额外再拉)
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
