"""硬线升级/重复至确认状态机(阶段1 A.4)。

行为契约(plan A.4):
  · 同一硬线事件(按 code+kind 聚合)未确认 → 按 ESCALATE_INTERVAL_MIN 重复推、角标递增"第 N 次升级"。
  · 录动作(marked_close / dismissed)→ ack 停升级。
  · D4 时间止损无券商兜底 → 沿用同一升级机制(多次重复)。

设计:纯状态机,时间靠 now 注入(单测可控)。调用方(loop)负责真发推:
  · 每轮拿到 classify 产出的 HardlineEvent,喂 register(event);
  · 调 due_pushes(now) 拿"本轮该推的 (track, badge)" → 逐条真发;
  · 用户 ack → ack(code, kind?, action) 标记停推。

聚合键 = (code, kind)。同一票止损线与 D4 时间线是两条独立可升级事件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from app.monitor.hardline import HardlineEvent


@dataclass
class _Track:
    """单条硬线的升级状态。"""
    event: HardlineEvent
    first_seen: datetime
    last_push: Optional[datetime] = None
    push_count: int = 0          # 已推次数(角标 = push_count;第 1 次=1)
    acked: bool = False
    ack_action: Optional[str] = None


def _key(code: str, kind: str) -> Tuple[str, str]:
    return (code, kind)


class EscalationManager:
    """硬线升级状态机。单实例随 app 生命周期常驻(loop 持有)。"""

    def __init__(self, interval_min: int = 15) -> None:
        self.interval = timedelta(minutes=max(1, interval_min))
        self._tracks: Dict[Tuple[str, str], _Track] = {}

    # —— 录入本轮硬线事件 ——————————————————————————————————————————
    def register(self, event: HardlineEvent, now: Optional[datetime] = None) -> None:
        """登记/刷新一条硬线事件。已存在且未 ack → 仅更新 event 内容(文案随价格变)。

        非硬线(suspect)忽略(不进升级)。已 ack 的同键事件不复活
        (用户已处理;除非清仓后重新建仓——本期 code 唯一持仓,不处理复活)。
        """
        if not event.is_hardline:
            return
        now = now or datetime.now()
        k = _key(event.code, event.kind)
        tr = self._tracks.get(k)
        if tr is None:
            self._tracks[k] = _Track(event=event, first_seen=now)
        elif not tr.acked:
            tr.event = event  # 刷新最新文案/盈亏

    # —— 本轮该推的事件 ——————————————————————————————————————————
    def due_pushes(self, now: Optional[datetime] = None) -> List[Tuple[_Track, int]]:
        """返回本轮应推送的 [(track, badge_escalation)]。

        首次出现立即推(badge=1);此后每满 interval 推一次,badge 递增。
        已 ack 的不推。返回后调用方应对每条调用 mark_pushed 落实推送时间。
        """
        now = now or datetime.now()
        due: List[Tuple[_Track, int]] = []
        for tr in self._tracks.values():
            if tr.acked:
                continue
            if tr.last_push is None:
                due.append((tr, tr.push_count + 1))
            elif now - tr.last_push >= self.interval:
                due.append((tr, tr.push_count + 1))
        return due

    def mark_pushed(self, track: _Track, now: Optional[datetime] = None) -> None:
        """登记一条已真发推送(更新 last_push 与计数)。"""
        now = now or datetime.now()
        track.last_push = now
        track.push_count += 1

    # —— 确认(停升级)————————————————————————————————————————————
    def ack(self, code: str, action: str, kind: Optional[str] = None) -> int:
        """用户 ack:停止该 code(可指定 kind)的升级。

        kind=None → ack 该 code 的所有未确认硬线(客户端按 code 维度 ack,
        一条推送可能聚合该票的止损+时间两线,统一停)。返回被 ack 的条数。
        action ∈ {"marked_close", "dismissed"}。
        """
        n = 0
        for (c, kd), tr in self._tracks.items():
            if c != code:
                continue
            if kind is not None and kd != kind:
                continue
            if not tr.acked:
                tr.acked = True
                tr.ack_action = action
                n += 1
        return n

    # —— 内省 ————————————————————————————————————————————————————
    def active_tracks(self) -> List[_Track]:
        """未 ack 的硬线(供心跳/调试)。"""
        return [t for t in self._tracks.values() if not t.acked]

    def clear(self) -> None:
        self._tracks.clear()
