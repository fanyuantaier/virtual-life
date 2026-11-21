"""共享数据契约：三线程（世界引擎/记忆/调度）都 import 这里，不互相 import。"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- 状态（物理层记账用） ----------

class ProtagonistState(BaseModel):
    energy: int = Field(ge=0, le=100)
    mood: int = Field(ge=-100, le=100)
    money: int
    location: str
    mood_tags: list[str] = Field(default_factory=list)


class NpcState(BaseModel):
    name: str
    relationship: int = 0          # -100..100
    facts: list[str] = Field(default_factory=list)   # 事实列表，非数值：\"10/12 帮我修过车\"
    pending_debts: list[str] = Field(default_factory=list)  # 未兑现的人情/承诺
    last_seen: Optional[date] = None


# ---------- 事件（导演输出 → 主角输入） ----------

class Event(BaseModel):
    slot: Literal["morning", "afternoon", "evening", "night"]
    kind: Literal["routine", "incidental", "major", "reality"]
    location: str
    actors: list[str] = Field(default_factory=list)  # NPC 名或 \"你\"
    content: str                    # 发生了什么（一句到三句）
    detail: str = ""                # 细节填槽：具体物/话/天气等
    intensity: int = Field(1, ge=1, le=10)
    decision_point: bool = False    # 是否留决策点给主角
    foreshadow_tags: list[str] = Field(default_factory=list)  # 埋下的伏笔 id


class Decision(BaseModel):
    question: str
    options: list[str] = Field(min_length=2, max_length=4)


class DecisionResult(BaseModel):
    choice: str
    inner_reason: str               # 主角的内心理由，入记忆


class DiaryEntry(BaseModel):
    date: date
    slot: Literal["morning", "afternoon", "evening", "night", "daily"]
    text: str
    emotion_tags: list[str] = Field(default_factory=list)
    poignancy: int = Field(0, ge=0, le=150)


# ---------- 伏笔表（导演的主输入之一） ----------

class Foreshadow(BaseModel):
    id: str
    summary: str                    # \"欠小李一顿饭\"
    opened_on: date
    urgency: int = Field(1, ge=1, le=5)   # 越大越快到期
    expires_hint: Optional[str] = None    # \"两周内不还关系会降\"


# ---------- 调度契约 ----------

class DayPlan(BaseModel):
    date: date
    events: list[Event]
    decisions: list[tuple[str, Decision]] = Field(default_factory=list)  # event_id -> decision


class MemoryHit(BaseModel):
    when: datetime
    text: str
    kind: Literal["event", "thought", "chat", "diary", "fact", "scene", "persona", "dream", "ticket"]
    importance: float
