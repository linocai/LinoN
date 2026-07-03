"""FastAPI 应用主体(阶段1 A.1/A.2/A.4 ack + 单 unit 后台监控挂载)。

绑 127.0.0.1:8001(nginx 反代)。/api/v1/health 免鉴权;其余端点过 require_token。
startup:fail-fast 校验 API_TOKEN(len>=16)+ init_db + 起后台监控轮询任务。
shutdown:置位 stop_event,优雅停轮询。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status

from app.api.deps import require_api_token_ready, require_token
from app.api.schemas import (
    AlertAck,
    CandidatesList,
    CandidatesRefreshOut,
    ChatRequest,
    CoachRequest,
    DeviceRegister,
    MemoryOut,
    OutcomesStatsOut,
    PositionClose,
    PositionOpen,
    PositionOut,
    PositionsList,
    ReviewNoteIn,
    ReviewOut,
)
from app.calendar.trading_calendar import (
    count_holding_trade_days,
    next_trading_day,
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
    """开仓 buy_date 'YYYY-MM-DD'(D 计数基准 D1)。

    D5 修 reviewer 🔵#1:今天是交易日 → 今天;周末/节假日录入 → 取**下一**交易日
    (next_trading_day),不再取上一交易日——否则 D 计数会从已收盘的上一交易日提前起算,
    把周末当 D1 之后的时间,导致 D4 强平提前。不破 should_force_close 的 count==4 契约
    (只改 buy_date 落点,计数语义不变)。
    """
    from datetime import date
    today = date.today()
    d = today if is_trading_day(today) else next_trading_day(today)
    return d.strftime("%Y-%m-%d")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # —— startup ——
    require_api_token_ready()           # fail-fast:API_TOKEN len>=16
    store.init_db()
    app.state.escalation = EscalationManager(
        interval_min=settings.ESCALATE_INTERVAL_MIN
    )
    # 审后修复 #2:升级状态仅内存,重启会丢。启动时从 positions 重建
    # count≥4 逾期在持仓的 time 升级,使 D4 后重启/夜间重启不丢"D4 无条件清仓"逼促。
    from datetime import datetime as _dt
    from app.monitor.loop import rebuild_time_escalations
    rebuilt = rebuild_time_escalations(app.state.escalation, now=_dt.now())
    if rebuilt:
        logger.info("启动重建逾期 time 升级 %d 条(D4+ 持仓)", rebuilt)
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

    # 回读该 trade 的机械判定结果 + 净额(v1.3.0 Phase B4)
    flags = _read_trade_flags(trade_id)
    # fee/net_pnl_amount:新清仓总有实值;旧行(迁移前)为 NULL → 原样传 null(不兜 0.0)。
    return {
        "ok": True,
        "trade_id": trade_id,
        "pnl": flags["pnl"],
        "kept_stop": bool(flags["kept_stop"]),
        "kept_take": bool(flags["kept_take"]),
        "kept_time": bool(flags["kept_time"]),
        "broke_rule": bool(flags["broke_rule"]),
        "fee": flags.get("fee"),
        "net_pnl_amount": flags.get("net_pnl_amount"),
    }


# —— A.2 列持仓 ——————————————————————————————————————————————————————

@app.get(f"{API_PREFIX}/positions", dependencies=[Depends(require_token)])
def list_positions() -> PositionsList:
    holdings = store.list_holdings()
    # §4b 联调点:后端供 price(客户端算 pnl)。按需拉一拍实时价填 price;
    # flow3d(主力近 3 日净流入)需 Tushare moneyflow,阶段2 接,本期占位。
    prices = _resolve_prices([h["code"] for h in holdings])
    out = []
    for h in holdings:
        out.append(PositionOut(
            id=h["id"], code=h["code"], name=h["name"],
            buy_price=h["buy_price"], qty=h["qty"],
            entry_reason=h["entry_reason"], buy_date=h["buy_date"],
            status=h["status"],
            price=prices.get(h["code"], 0.0) or 0.0,
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


# —— D2 候选列表(读缓存 + 运行时按 free_slots 截断)——————————————————————

@app.get(f"{API_PREFIX}/candidates", dependencies=[Depends(require_token)])
def list_candidates() -> CandidatesList:
    """读 candidates 缓存表最新 trade_date,按 5×free_slots 运行时再截断。

    满仓(free_slots=0)→ 空列表(闭门);无缓存/无 token → degraded:true 空列表。
    candidates 形状对齐 Models.swift Candidate(analysis 在列表里省略,深判 on-demand)。
    """
    free = max(0, store.MAX_HOLDINGS - store.holding_count())
    td = store.latest_candidate_date()
    if td is None:
        # 无缓存:degraded(可能 token 缺失 EOD 未算,或盘前首日)。HTTP 仍 200。
        reason = "no_cache" if settings.has_tushare_token else "no_tushare_token"
        return CandidatesList(
            candidates=[], free_slots=free, trade_date="", degraded=True, reason=reason,
        )
    all_rows = store.list_candidates(td)
    limit = 5 * free   # 截断公式(满仓 0 闭门)
    shown = all_rows[:limit] if limit > 0 else []
    return CandidatesList(
        candidates=shown, free_slots=free, trade_date=td, degraded=False,
    )


# —— D2 强制重算候选(鉴权)——————————————————————————————————————————

@app.post(f"{API_PREFIX}/candidates/refresh", dependencies=[Depends(require_token)])
def refresh_candidates() -> CandidatesRefreshOut:
    """强制重算当日候选并 upsert。返回 {ok, trade_date, count, degraded}。

    无 token/拉取失败 → degraded:true,count=0,不崩(沿降级契约)。
    """
    count, td, degraded = _recompute_candidates()
    return CandidatesRefreshOut(ok=True, trade_date=td, count=count, degraded=degraded)


# —— 候选重算编排(端点 + EOD tick 共用)————————————————————————————————

def _candidate_basis_date() -> str:
    """候选 EOD 计算基准交易日 'YYYYMMDD'。

    今天是交易日且已过收盘窗口 → 今天;否则取上一交易日(Tushare EOD 数据口径)。
    注:Tushare 2000 积分实际数据可能滞后,_recompute 内 pipeline 会按此基准日拉,
    拉不到该日则 fetch 返回失败 → degraded(不崩)。
    """
    from datetime import date
    today = date.today()
    d = today if is_trading_day(today) else prev_trading_day(today)
    return d.strftime("%Y%m%d")


def _recompute_candidates() -> tuple:
    """拉全市场 → 粗筛排序 → upsert candidates 表。返回 (count, trade_date_disp, degraded)。

    可注入测试替身:模块级 _pipeline_fn(避免单测联网)。
    """
    basis = _candidate_basis_date()
    try:
        rows, degraded, _reason, td = _pipeline_fn(basis)
    except Exception:
        logger.warning("候选重算异常(已吞)", exc_info=True)
        return 0, _disp_date(basis), True
    # td 为展示串 'YYYY-MM-DD'(pipeline 产);degraded 时 rows 为空
    store.upsert_candidates(td, rows)
    return len(rows), td, degraded


def _default_pipeline_fn(basis_yyyymmdd: str):
    from app.screen.pipeline import run_pipeline
    return run_pipeline(basis_yyyymmdd)


# 可注入测试替身(避免单测联网/真拉 Tushare)。
_pipeline_fn = _default_pipeline_fn


def _disp_date(yyyymmdd: str) -> str:
    s = str(yyyymmdd)
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s


# —— D4 on-demand 深判(候选)——————————————————————————————————————

@app.post(f"{API_PREFIX}/candidates/{{code}}/analyze",
          dependencies=[Depends(require_token)])
def analyze_candidate(code: str) -> dict:
    """on-demand 对候选深判,返回 {ok, code, analysis: DeepAnalysis, fund_asof}。

    name/sector 优先从最新候选缓存补,缺则用行业映射/code 兜底。
    上游(Tushare/DeepSeek)失败 → 深判返回降级占位卡(verdict=观望),HTTP 仍 200。

    副作用(阶段2.5 F3,响应体不变):深判成功且 verdict 合法时落 analysis_verdicts,
    供未来回测 join。trade_date 取该 code 所属候选的 entry_date(store.candidate_
    entry_date_of),非 latest_candidate_date——深判 on-demand,用户可能在候选产生
    T+1/T+2 才点深判,那时 latest 已滚到新一天,用 latest 会导致回测 join 恒取不到。
    查不到所属候选日(如直接对非候选票深判)→ 不落(verdict 保持 NULL,不硬塞错日期)。
    """
    bare = _bare_code(code)
    name, sector = _resolve_candidate_meta(bare)
    # candidate 模式也注入中性 history_digest(不改响应结构,历史仅影响 DeepSeek text)。
    history_digest, _ = _coach_brain(bare)
    result = _analyze_fn(bare, name, sector, "candidate", None, None, None, history_digest)
    analysis = result["analysis"]
    _maybe_persist_verdict(bare, analysis)
    return {
        "ok": True,
        "code": bare,
        "analysis": analysis,
        "fund_asof": result["fund_asof"],
    }


def _maybe_persist_verdict(code: str, analysis: dict) -> None:
    """candidate 模式深判成功 → 落 analysis_verdicts(仅供回测 join,不改响应契约)。

    trade_date 取该 code 所属候选的 entry_date;查不到 → 不落。verdict 非法(理论上
    clamp_analysis 已保证合法,这里再兜底)→ 不落。落库异常吞掉,不影响响应。
    """
    from app.llm.deepseek import _VERDICTS

    verdict = analysis.get("verdict") if isinstance(analysis, dict) else None
    if verdict not in _VERDICTS:
        return
    entry_date = store.candidate_entry_date_of(code)
    if not entry_date:
        return
    try:
        store.upsert_analysis_verdict(entry_date, code, verdict)
    except Exception:
        logger.warning("落 analysis_verdicts 失败(已吞,不影响响应)", exc_info=True)


# —— D4 中间地带 B 剂量(在持仓二元建议)————————————————————————————————

@app.post(f"{API_PREFIX}/positions/{{position_id}}/coach",
          dependencies=[Depends(require_token)])
def coach_position(position_id: int, body: CoachRequest) -> dict:
    """对在持仓给中间地带二元建议(拿/清)。非在持仓 → 404 not_holding。

    最看重量能萎缩 + 主力资金还在不在(方法论在 system prompt)。返回
    {ok, advice:"拿"|"清", reason, analysis: DeepAnalysis, fund_asof}。
    上游失败 → 降级占位卡 + advice 由 verdict 派生(观望→拿),HTTP 仍 200。
    """
    from datetime import date
    from app.llm.analyze import coach_advice_from_analysis

    pos = store.get_position(position_id)
    if pos is None or pos.get("status") != "holding":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "reason": "not_holding"},
        )

    code = pos["code"]
    # 当前盈亏%(按需拉一拍实时价;拉不到则 None,深判仍可做)
    pnl_pct = None
    prices = _resolve_prices([code])
    price = prices.get(code)
    if price and pos["buy_price"]:
        pnl_pct = round((price - pos["buy_price"]) / pos["buy_price"] * 100, 2)
    trade_day = count_holding_trade_days(pos["buy_date"], date.today())

    # 教练大脑(G4):两条独立产物,严格分流。
    # · history_digest(中性统计)→ 进 prompt(经 _analyze_fn),供 LLM 引用增说服力。
    # · review_ref(带情绪第二人称)→ 仅回客户端展示,**绝不进 prompt**。
    history_digest, review_ref = _coach_brain(code)

    result = _analyze_fn(
        code, pos.get("name", code), "", "coach", pnl_pct, trade_day, body.question,
        history_digest,
    )
    analysis = result["analysis"]
    advice = coach_advice_from_analysis(analysis)
    reason = analysis.get("plan", "")
    resp = {
        "ok": True,
        "advice": advice,
        "reason": reason,
        "analysis": analysis,
        "fund_asof": result["fund_asof"],
    }
    if review_ref:              # 无历史破线笔 → 省略字段(降级不硬造)
        resp["review_ref"] = review_ref
    return resp


def _coach_brain(code: str) -> tuple:
    """教练大脑两串(history_digest 进 prompt / review_ref 回客户端)。降级不崩。

    返回 (history_digest: str, review_ref: Optional[str])。任何异常 → ('', None)。
    """
    try:
        from app.review.brain import build_history_digest, build_review_ref
        digest = build_history_digest(trades_fn=store.list_all_trades)
        ref = build_review_ref(code, trades_fn=store.list_all_trades)
        return digest or "", ref
    except Exception:
        logger.warning("教练大脑构建异常(降级为空)", exc_info=True)
        return "", None


# —— v1.2.1 Phase A:统一多轮对话端点(候选深析对话化 / 持仓追问)——————————————

@app.post(f"{API_PREFIX}/chat", dependencies=[Depends(require_token)])
def chat(body: ChatRequest) -> dict:
    """对话式深判(plan §4.1)。candidate 模式候选深析对话 / coach 模式持仓追问对话。

    后端无状态:多轮历史由客户端每次全量回传(body.messages),不落库 thread。
    coach 模式 position_id 指向的持仓不存在/已 closed → 404 not_holding;存在则
    **以 pos["code"] 为准**(忽略 body.code,同现 /coach)。candidate 模式 name/sector
    复用现成 _resolve_candidate_meta,客户端不传。

    落库门槛(决定2 硬要求):仅当 is_first(messages 里 assistant 条数==0)且
    mode=="candidate" 且 result 非降级时,才落 analysis_verdicts——降级"观望"绝不
    覆盖真实 verdict 污染回测。上游失败仍 HTTP 200 返降级占位,绝不抛崩。
    """
    from datetime import date

    bare = _bare_code(body.code)
    pnl_pct: Optional[float] = None
    trade_day: Optional[int] = None
    name, sector = "", ""

    if body.mode == "coach":
        if body.position_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "not_holding"},
            )
        pos = store.get_position(body.position_id)
        if pos is None or pos.get("status") != "holding":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "not_holding"},
            )
        bare = pos["code"]   # 以持仓 code 为准,忽略 body.code(同现 /coach)
        name = pos.get("name", bare)
        prices = _resolve_prices([bare])
        price = prices.get(bare)
        if price and pos["buy_price"]:
            pnl_pct = round((price - pos["buy_price"]) / pos["buy_price"] * 100, 2)
        trade_day = count_holding_trade_days(pos["buy_date"], date.today())
    else:
        name, sector = _resolve_candidate_meta(bare)

    # 教练大脑:只取中性 history_digest,丢弃带情绪的 review_ref(守味隔离铁律)。
    history_digest, _ = _coach_brain(bare)

    is_first = sum(1 for m in body.messages if m.role == "assistant") == 0
    messages_payload = [{"role": m.role, "content": m.content} for m in body.messages]

    result = _chat_fn(
        bare, messages_payload, mode=body.mode, name=name, sector=sector,
        pnl_pct=pnl_pct, trade_day=trade_day, history_digest=history_digest,
    )

    if is_first and body.mode == "candidate" and not result["degraded"]:
        _maybe_persist_verdict(bare, {"verdict": result["verdict"]})

    return {
        "ok": True,
        "code": bare,
        "reply": result["reply"],
        "verdict": result["verdict"],
        "fund_asof": result["fund_asof"],
        "is_first": is_first,
        "degraded": result["degraded"],
    }


def _default_chat_fn(code, messages, *, mode, name, sector, pnl_pct, trade_day, history_digest):
    from app.llm.analyze import chat_stock
    return chat_stock(
        code, messages, mode=mode, name=name, sector=sector,
        pnl_pct=pnl_pct, trade_day=trade_day, history_digest=history_digest,
    )


# 可注入测试替身(避免单测联网/真调 DeepSeek+Tushare),同 _analyze_fn 模式。
_chat_fn = _default_chat_fn


# —— F4 回测统计只读端点(阶段2.5,仅供调试/未来前端,本版本不接客户端)—————————

@app.get(f"{API_PREFIX}/candidates/outcomes", dependencies=[Depends(require_token)])
def candidates_outcomes(since: str = "") -> OutcomesStatsOut:
    """回测统计聚合(plan §4.1 三维度:排序分位分层收益 / tag 胜率 / verdict 命中率)。

    读 candidate_outcomes 聚合(不预计算落库)。空表(回填未跑/无候选)→
    sample_total=0、各分组空数组、note 标"暂无回测样本",HTTP 200(不 500)。
    """
    from app.screen.backtest import compute_outcome_stats
    stats = compute_outcome_stats(since=since or None)
    return OutcomesStatsOut(**stats)


# —— 阶段3 G2:复盘 + 记忆端点 ——————————————————————————————————————————

def _current_week() -> str:
    """本 ISO 周 'YYYY-Www'(缺 week 参数时的默认)。"""
    from datetime import date
    from app.review.score import iso_week
    return iso_week(date.today())


@app.get(f"{API_PREFIX}/review", dependencies=[Depends(require_token)])
def get_review(week: str = "") -> ReviewOut:
    """实时聚合某 ISO 周复盘(缺 week → 本周)。返回 Review 形状 + openHoldings + nextWeekNote。

    纯确定性聚合(零 LLM):读全部 trades 聚合该周 discipline_rate/redFlags/每笔/近6周 trend;
    附未平 positions(openHoldings)+ reviews 表已存的用户注(nextWeekNote)。
    空库(无 trades/memory)→ 诚实空态(discipline_rate=0),HTTP 200 不 500。
    """
    from app.review.score import aggregate_week

    wk = week.strip() or _current_week()
    try:
        review = aggregate_week(
            wk,
            trades_fn=store.list_all_trades,
            holdings_fn=store.list_holdings,
        )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"ok": False, "reason": "invalid_week", "week": wk},
        )
    review["nextWeekNote"] = store.get_review_note(wk)
    return ReviewOut(**review)


@app.post(f"{API_PREFIX}/review/{{week}}/note", dependencies=[Depends(require_token)])
def save_review_note(week: str, body: ReviewNoteIn) -> dict:
    """写/覆盖某周 next_week_note(upsert reviews 表,SELECT-then-UPDATE/INSERT)。

    顺手快照当刻 discipline_rate(供历史留痕;GET /review 的 disciplineRate 始终实时算)。
    """
    from app.review.score import aggregate_week

    try:
        review = aggregate_week(
            week,
            trades_fn=store.list_all_trades,
            holdings_fn=store.list_holdings,
        )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"ok": False, "reason": "invalid_week", "week": week},
        )
    store.upsert_review_note(week, body.note, discipline_rate=review["disciplineRate"])
    return {"ok": True, "week": week}


@app.get(f"{API_PREFIX}/memory", dependencies=[Depends(require_token)])
def get_memory() -> MemoryOut:
    """列 memory 表条目(倒序)+ 已平仓 trades 流水(供 MemoryView 历史区)。

    closedTrades 组装:name 为 NULL 兜底回 code(存量历史行可能 name=NULL);
    pnl 展示串带号;守线徽章字段布尔化;date 取 close_time 的日期部分。
    空库 → items/closedTrades 皆空数组,HTTP 200。
    """
    items = []
    for m in store.list_memory(limit=200):
        items.append({
            "kind": m.get("kind", ""),
            "content": m.get("content", ""),
            "date": _date_part(m.get("created_at")),
        })
    closed = []
    for t in store.list_closed_trades():
        pnl = float(t.get("pnl", 0.0) or 0.0)
        closed.append({
            "name": t.get("name") or str(t.get("code", "")),   # NULL 兜底回 code
            "code": str(t.get("code", "")),
            "pnl": f"{pnl:+.1f}%",
            "netPnlAmount": _net_amount_of(t),                 # 元,可空(旧 NULL 行 → null,🟡1)
            "keptStop": bool(int(t.get("kept_stop", 0))),
            "keptTake": bool(int(t.get("kept_take", 0))),
            "keptTime": bool(int(t.get("kept_time", 0))),
            "brokeRule": bool(int(t.get("broke_rule", 0))),
            "note": t.get("note") or "",
            "date": _date_part(t.get("close_time")),
        })
    # 流水按 date 倒序(最近在前),与 memory 一致
    closed.reverse()
    return MemoryOut(items=items, closedTrades=closed)


def _date_part(ts: Optional[str]) -> str:
    """从 'YYYY-MM-DD HH:MM:SS' 或 'YYYY-MM-DD' 取日期部分;None → 空串。"""
    if not ts:
        return ""
    return str(ts).split(" ")[0].split("T")[0]


def _net_amount_of(t: dict) -> Optional[float]:
    """trade 行的净收益金额(元,可空)。v1.3.0 迁移前的旧行 net_pnl_amount 为 NULL → None
    (不兜 0.0,🟡1;区分"没数据"vs"真 0 元")。真 0.0 收益原样返 0.0。"""
    raw = t.get("net_pnl_amount")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# —— 深判编排桥(可注入测试替身)————————————————————————————————————————

def _bare_code(code: str) -> str:
    import re
    return re.sub(r"\D", "", code or "")[:6]


def _resolve_candidate_meta(code: str) -> tuple:
    """从最新候选缓存补 (name, sector);缺则行业映射/code 兜底。"""
    td = store.latest_candidate_date()
    if td:
        for c in store.list_candidates(td):
            if c["code"] == code:
                return c.get("name") or code, c.get("sector") or ""
    # 兜底:行业映射
    try:
        from app.screen.fetch import name_of, industry_of, load_industry_map
        load_industry_map()
        return name_of(code) or code, industry_of(code) or ""
    except Exception:
        return code, ""


def _default_analyze_fn(code, name, sector, mode, pnl_pct, trade_day, question,
                        history_digest=None):
    from app.llm.analyze import analyze_stock
    return analyze_stock(
        code, name, sector, mode=mode,
        pnl_pct=pnl_pct, trade_day=trade_day, question=question,
        history_digest=history_digest,
    )


# 可注入测试替身(避免单测联网/真调 DeepSeek+Tushare)。
_analyze_fn = _default_analyze_fn


# —— 内部工具 ————————————————————————————————————————————————————————

def _resolve_name(code: str) -> str:
    """尝试用实时源补股票名;失败返回空串(不阻塞录入)。"""
    try:
        from app.data.realtime import get_realtime_quote
        q = get_realtime_quote(code)
        return q.name if q is not None else ""
    except Exception:
        return ""


def _resolve_prices(codes: list) -> dict:
    """按需拉一拍实时价(§4b 联调点:后端供 price)。

    任何源失败/无网络都不阻塞列持仓:返回能拿到的子集,缺的 code 由
    客户端按 buy_price 兜底(pnl=0)。可注入测试替身见模块级 _quotes_fn。
    """
    if not codes:
        return {}
    try:
        quotes = _quotes_fn(list(codes))
    except Exception:
        logger.warning("列持仓拉实时价失败,price 缺省 0(客户端兜底)", exc_info=True)
        return {}
    out: dict = {}
    for code, q in (quotes or {}).items():
        price = getattr(q, "price", None)
        if price is None and isinstance(q, dict):
            price = q.get("price")
        if price:
            out[code] = float(price)
    return out


def _default_quotes_fn(codes: list) -> dict:
    from app.data.realtime import get_realtime_quotes
    return get_realtime_quotes(codes)


# 可注入测试替身(避免单测联网)。
_quotes_fn = _default_quotes_fn


def _read_trade_flags(trade_id: int) -> dict:
    conn = store.get_connection()
    try:
        row = conn.execute(
            "SELECT pnl, kept_stop, kept_take, kept_time, broke_rule, fee, net_pnl_amount "
            "FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else {
        "pnl": 0.0, "kept_stop": 0, "kept_take": 0, "kept_time": 0, "broke_rule": 0,
        "fee": None, "net_pnl_amount": None,
    }
