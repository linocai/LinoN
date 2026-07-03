"""持仓 positions 表:开/清仓 + 在持查询 + 派生止损止盈 + 机械纪律判定。

止损线/止盈线**读取时派生、不落库**(单一事实源,同持仓天数)。清仓落一条 trades
闭合记录 + 归档 position,破线笔在同一事务内原子沉淀一条 memory 闭环结论。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.trade import costs
from app.db.store._common import _now, get_connection
from app.db.store.constants import (
    FORCE_CLOSE_TRADE_DAY,
    MAX_HOLDINGS,
    STOP_KEPT_HIGH,
    STOP_KEPT_LOW,
    STOP_RATIO,
    TAKE_RATIO,
    TAKE_TRIGGER_PCT,
)


# —— 派生量(读取时算,不落库)————————————————————————————————————

def stop_line(buy_price: float) -> float:
    """止损线 = buy_price × 0.95(读取时派生,四舍五入 0.01)。"""
    return round(buy_price * STOP_RATIO, 2)


def take_line(buy_price: float) -> float:
    """止盈线 = buy_price × 1.15(读取时派生,四舍五入 0.01)。"""
    return round(buy_price * TAKE_RATIO, 2)


# —— CRUD ——————————————————————————————————————————————————————————

def open_position(
    code: str,
    name: str,
    buy_price: float,
    qty: int,
    entry_reason: str,
    buy_date: str,
    entry_snapshot: Optional[Dict[str, Any]] = None,
    industry: str = "",
    db_path: Optional[str] = None,
) -> int:
    """开一仓,写 positions(status='holding')。返回新 position id。

    entry_snapshot 形如 {'formNote': ..., 'fundNote': ...}(系统自动补,存 JSON)。
    持仓上限校验:已 >= 3 holding 时抛 ValueError(同时最多 3 票)。
    industry(v1.3.0 Phase A1,相关性护栏用):调用方只应传"已缓存"的行业口径
    (app.py._resolve_industry 只读 fetch.industry_of,绝不在此触发同步联网拉取);
    查不到/未传 → 空串,不阻塞开仓。
    """
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "SELECT COUNT(*) AS n FROM positions WHERE status = 'holding'"
        )
        if cur.fetchone()["n"] >= MAX_HOLDINGS:
            raise ValueError(f"持仓已满({MAX_HOLDINGS} 票),不能再开仓")
        snap_json = json.dumps(entry_snapshot, ensure_ascii=False) if entry_snapshot else None
        cur = conn.execute(
            """INSERT INTO positions
               (code, name, buy_price, qty, entry_reason, entry_snapshot,
                buy_date, status, created_at, industry)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'holding', ?, ?)""",
            (code, name, buy_price, qty, entry_reason, snap_json, buy_date, _now(),
             industry or ""),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_holdings(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出在持(status='holding')。每行附派生 stop_line / take_line。"""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status = 'holding' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if d.get("entry_snapshot"):
            try:
                d["entry_snapshot"] = json.loads(d["entry_snapshot"])
            except (json.JSONDecodeError, TypeError):
                pass
        d["stop_line"] = stop_line(d["buy_price"])     # 派生
        d["take_line"] = take_line(d["buy_price"])     # 派生
        out.append(d)
    return out


def get_holding_by_code(code: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 code 取在持仓(status='holding')。无则 None。用于 open 重复防护。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM positions WHERE code = ? AND status = 'holding'",
            (code,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    d = dict(row)
    if d.get("entry_snapshot"):
        try:
            d["entry_snapshot"] = json.loads(d["entry_snapshot"])
        except (json.JSONDecodeError, TypeError):
            pass
    d["stop_line"] = stop_line(d["buy_price"])
    d["take_line"] = take_line(d["buy_price"])
    return d


def get_position(position_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 id 取任一持仓行(任何 status)。无则 None。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def holding_count(db_path: Optional[str] = None) -> int:
    """当前在持仓票数。"""
    conn = get_connection(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM positions WHERE status = 'holding'"
            ).fetchone()["n"]
        )
    finally:
        conn.close()


def _compute_kept_flags(
    open_price: float,
    close_price: float,
    pnl_pct: float,
    holding_trade_days: Optional[int],
) -> Dict[str, bool]:
    """机械规则计算 kept_stop / kept_take / kept_time(阶段3 细化)。

    · kept_stop:在止损容差带 [-6%, -4%] 离场 → 守了止损(滑点不误判)。
    · kept_take:pnl >= +15% 止盈线 → 守了止盈。
    · kept_time:在 D4 当天或之前离场(count<=4)→ 守了时间。
      holding_trade_days 为 None(未传日历计数)时,保守置 True(无证据破纪律)。
    · broke_rule:亏损但没守住止损(跌穿 -6% 还没走),或持过 D4 → 破纪律。
    """
    kept_stop = STOP_KEPT_LOW <= pnl_pct <= STOP_KEPT_HIGH
    kept_take = pnl_pct >= TAKE_TRIGGER_PCT
    if holding_trade_days is None:
        kept_time = True
    else:
        kept_time = holding_trade_days <= FORCE_CLOSE_TRADE_DAY

    broke_rule = False
    # 跌穿止损容差下沿仍未守住 → 破止损
    if pnl_pct < STOP_KEPT_LOW:
        broke_rule = True
    # 持过 D4 仍未清 → 破时间
    if holding_trade_days is not None and holding_trade_days > FORCE_CLOSE_TRADE_DAY:
        broke_rule = True
    return {
        "kept_stop": kept_stop,
        "kept_take": kept_take,
        "kept_time": kept_time,
        "broke_rule": broke_rule,
    }


def close_position(
    position_id: int,
    close_price: float,
    close_time: Optional[str] = None,
    holding_trade_days: Optional[int] = None,
    db_path: Optional[str] = None,
) -> int:
    """清一仓:落一条 trades 闭合记录 + 归档对应 position(status='closed')。

    pnl = (close-open)/open*100(百分比)。kept_* / broke_rule 机械规则计算
    (阶段3 细化)。holding_trade_days 可由日历原语 count_holding_trade_days 传入,
    用于 kept_time 判定;不传则保守 True。
    返回新 trade id。position 不存在或非 holding → 抛 ValueError。
    """
    from app.review.score import _mechanical_comment   # 短评单一事实源(与 G1 aggregate 同源)

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"position {position_id} 不存在")
        if row["status"] != "holding":
            raise ValueError(f"position {position_id} 非在持(status={row['status']})")

        open_price = float(row["buy_price"])
        open_time = row["buy_date"]
        ctime = close_time or _now()
        pnl_pct = round((close_price - open_price) / open_price * 100, 4) if open_price else 0.0
        flags = _compute_kept_flags(open_price, close_price, pnl_pct, holding_trade_days)
        name = row["name"]                       # 从 position 取(阶段3 G3 补列)
        note = _mechanical_comment(flags)        # 机械短评(守住铁律/破止损/破时间)

        # v1.3.0 Phase B2:交易成本 + 净收益金额(🔴金额计算,元)。
        # qty 从 position 带出(positions.qty NOT NULL,理论恒有值);算不出/缺失时兜底
        # fee=0、net=毛收益 —— **不阻断清仓**(全自动、不手填、不硬闸,用户明确要求)。
        try:
            qty = int(row["qty"])
        except (KeyError, IndexError, TypeError, ValueError):
            qty = 0
        if qty > 0:
            fee = costs.total_fee(open_price * qty, close_price * qty)
            net_pnl = costs.net_pnl_amount(open_price, close_price, qty)
        else:
            fee = 0.0
            net_pnl = round((close_price - open_price) * qty, 2)  # qty=0 → 0.0(兜底,不硬闸)

        cur = conn.execute(
            """INSERT INTO trades
               (code, open_price, close_price, open_time, close_time,
                kept_stop, kept_take, kept_time, pnl, broke_rule, created_at, name, note,
                qty, fee, net_pnl_amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["code"], open_price, close_price, open_time, ctime,
                int(flags["kept_stop"]), int(flags["kept_take"]),
                int(flags["kept_time"]), pnl_pct, int(flags["broke_rule"]), _now(),
                name, note,
                qty, fee, net_pnl,
            ),
        )
        trade_id = int(cur.lastrowid)
        # 归档持仓
        conn.execute(
            "UPDATE positions SET status = 'closed' WHERE id = ?", (position_id,)
        )
        # 破线笔:同一事务内原子沉淀一条闭环结论(不 commit 后再开新连接)。
        # 若此处抛异常,trades 写 + position 归档一并回滚(原子;G3 验收③)。
        # 经 facade 取 insert_memory(而非模块顶部直接 import 绑定):保持
        # monkeypatch(app.db.store.insert_memory) 可拦截 → 拆包前的原子回滚测试语义不变。
        if flags["broke_rule"]:
            from app.db import store as _store
            _store.insert_memory("闭环结论", f"{name or row['code']}:{note}", conn=conn)
        conn.commit()
        return trade_id
    finally:
        conn.close()
