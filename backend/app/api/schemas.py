"""API 请求/响应模型(阶段1 A.1/A.2/A.4)。

字段校验错误由 pydantic 抛 422(plan A.2 要求)。
Position 响应形状对齐 client/Models.swift:含 code/name/buy_price/qty/entry_reason/
buy_date(+ 实时态 price/flow3d);【不含 stop_line】(客户端派生)。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# —— A.1 设备注册 ——————————————————————————————————————————————————

class DeviceRegister(BaseModel):
    token: str = Field(..., min_length=1)
    platform: Literal["ios"] = "ios"


# —— A.2 开/清仓录入 ————————————————————————————————————————————————

class PositionOpen(BaseModel):
    code: str = Field(..., min_length=1)
    buy_price: float = Field(..., gt=0)
    qty: int = Field(..., gt=0)
    entry_reason: str = Field(..., min_length=1)
    # name 客户端可带(Models.swift 有 name);缺省时服务端用实时源补,补不到留 code。
    name: Optional[str] = Field(default=None)


class PositionClose(BaseModel):
    sell_price: float = Field(..., gt=0)
    sell_time: Optional[str] = Field(default=None)   # ISO8601;缺省服务端用当前时刻


# —— A.4 ack ————————————————————————————————————————————————————

class AlertAck(BaseModel):
    action: Literal["marked_close", "dismissed"]


# —— 响应模型(对齐 Models.swift)————————————————————————————————————

class PositionOut(BaseModel):
    id: int
    code: str
    name: str
    buy_price: float
    qty: int
    entry_reason: str
    buy_date: str
    status: str = "holding"
    # 实时态(监控带;无则占位,客户端可本地补)
    price: float = 0.0
    flow3d: str = "—"


class PositionsList(BaseModel):
    holdings: List[PositionOut]
    free_slots: int


# —— 阶段2 D2/D4:候选 + 深判 —————————————————————————————————————————

class CandidatesList(BaseModel):
    """GET /candidates 响应(plan §4.3)。candidates 为 Candidate 形状 dict 列表
    (analysis 在列表里省略,深判 on-demand);camelCase 键直接透传客户端。"""
    candidates: List[Dict[str, Any]]
    free_slots: int
    trade_date: str
    degraded: bool = False
    reason: Optional[str] = None


class CandidatesRefreshOut(BaseModel):
    ok: bool
    trade_date: str
    count: int
    degraded: bool = False


class CoachRequest(BaseModel):
    """POST /positions/{id}/coach 请求体(question 可选)。"""
    question: Optional[str] = Field(default=None)


# —— 阶段2.5 F4:回测统计只读端点 ————————————————————————————————————

class OutcomeTierStat(BaseModel):
    """按维度分组的回测统计一行(排序分位分层 / tag / verdict 共用形状)。"""
    n: int
    avg_ret_3d: float
    win_rate: float


class OutcomesStatsOut(BaseModel):
    """GET /candidates/outcomes 响应(plan §4.4)。仅供调试/未来前端,本版本不接客户端。"""
    sample_total: int
    since: str = ""
    by_rank_tier: List[Dict[str, Any]]
    by_tag: List[Dict[str, Any]]
    by_verdict: List[Dict[str, Any]]
    note: str = ""


# —— 阶段3 G2:复盘 + 记忆端点 ——————————————————————————————————————————

class ReviewOut(BaseModel):
    """GET /review 响应(plan §4.3,camelCase 逐字段对齐 Models.swift Review + openHoldings)。"""
    week: str
    score: int
    disciplineRate: int
    rateTrend: int
    redFlags: List[str]
    lessons: str = ""
    nextWeekNote: str = ""
    trend: List[Dict[str, Any]]           # [{label, value}]
    trades: List[Dict[str, Any]]          # [{name, code, pnl, tag, comment}]
    openHoldings: List[Dict[str, Any]]    # [{name, code, buyPrice, tradeDay}]
    sampleNote: str = ""


class ReviewNoteIn(BaseModel):
    """POST /review/{week}/note 请求体。"""
    note: str = Field(default="")


class MemoryOut(BaseModel):
    """GET /memory 响应(plan §4.3)。items = memory 条目;closedTrades = 已平仓 trades 流水。"""
    items: List[Dict[str, Any]]           # [{kind, content, date}]
    closedTrades: List[Dict[str, Any]]    # [{name, code, pnl, keptStop, keptTake, keptTime, brokeRule, note, date}]
