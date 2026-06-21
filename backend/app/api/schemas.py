"""API 请求/响应模型(阶段1 A.1/A.2/A.4)。

字段校验错误由 pydantic 抛 422(plan A.2 要求)。
Position 响应形状对齐 client/Models.swift:含 code/name/buy_price/qty/entry_reason/
buy_date(+ 实时态 price/flow3d);【不含 stop_line】(客户端派生)。
"""

from __future__ import annotations

from typing import List, Literal, Optional

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
