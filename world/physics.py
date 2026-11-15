"""物理层：纯规则模块，只做校验与记账，不生成任何事件。

输入输出约定：
- build_skeleton(day, ...) -> Skeleton：按工作日/周末生成骨架日程。
- validate_events(events, state, skeleton) -> list[str]：返回不合法原因列表，空列表表示全部合法。
- apply_outcome(state, npc_map, event, outcome) -> ProtagonistState：把事件结果回写到主角与 NPC 状态（原地修改并返回）。
- quota_check(recent_days) -> list[str]：检查事件配额，返回违反项原因列表。

本模块不 import 任何网络/LLM 依赖，只依赖 pydantic 与共享契约 contracts。
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Mapping, Optional

from pydantic import BaseModel, Field

try:  # 作为包的一部分被导入时走相对导入
    from ..contracts import Event, NpcState, ProtagonistState
except ImportError:  # 直接运行 world/ 下模块时，把上级目录（contracts.py 所在）加进 sys.path
    _PARENT = str(Path(__file__).resolve().parent.parent)
    if _PARENT not in sys.path:
        sys.path.insert(0, _PARENT)
    from contracts import Event, NpcState, ProtagonistState

# ---------- 骨架日程 ----------

SlotName = str  # "morning" / "afternoon" / "evening" / "night"
SLOT_ORDER: tuple[SlotName, ...] = ("morning", "afternoon", "evening", "night")


class SlotSpec(BaseModel):
    """单个槽位：fixed 表示固定安排（如上班），free 表示自由槽（可长事件）。"""
    slot: SlotName
    kind: str = "free"            # "fixed" | "free"
    label: str = ""               # 固定槽的安排名，如 "上班"
    location: str = ""            # 固定槽所在地点，自由槽默认留空由事件决定


class Skeleton(BaseModel):
    """一天的骨架：4 个槽位，标注哪些是固定槽。"""
    day: date
    is_weekend: bool
    slots: dict[SlotName, SlotSpec]

    def free_slots(self) -> list[SlotName]:
        return [s.slot for s in self.slots.values() if s.kind == "free"]

    def fixed_slots(self) -> list[SlotName]:
        return [s.slot for s in self.slots.values() if s.kind == "fixed"]


def build_skeleton(day: date, work_location: str = "公司", home_location: str = "家") -> Skeleton:
    """工作日：morning/afternoon 固定上班；evening/night 自由。周末：全部自由。"""
    is_weekend = day.weekday() >= 5
    if is_weekend:
        slots = {name: SlotSpec(slot=name, kind="free") for name in SLOT_ORDER}
    else:
        slots = {
            "morning": SlotSpec(slot="morning", kind="fixed", label="上班", location=work_location),
            "afternoon": SlotSpec(slot="afternoon", kind="fixed", label="上班", location=work_location),
            "evening": SlotSpec(slot="evening", kind="free"),
            "night": SlotSpec(slot="night", kind="free"),
        }
    # 固定槽之外补一个默认地点，供地点存在性校验兜底
    for spec in slots.values():
        if spec.kind == "free" and not spec.location:
            spec.location = home_location
    return Skeleton(day=day, is_weekend=is_weekend, slots=slots)


# ---------- 地点注册表（纯静态，物理层不发明地点） ----------

DEFAULT_LOCATIONS: set[str] = {"家", "公司", "小区", "便利店", "超市", "公园", "医院", "地铁站"}


def known_locations(skeleton: Skeleton, state: ProtagonistState) -> set[str]:
    """地点全集 = 默认注册表 + 骨架槽位地点 + 主角当前所在地。"""
    locs = set(DEFAULT_LOCATIONS)
    locs.update(spec.location for spec in skeleton.slots.values() if spec.location)
    locs.add(state.location)
    return locs


# ---------- 消费与情绪的纯规则启发 ----------

_MONEY_RE = re.compile(r"[¥￥]?\s*(\d{2,6})\s*元")          # detail/content 里的显式金额
_SPEND_RE = re.compile(r"(买|付|请|消费|花了|购物|下单|充值|缴费)")

_JOY_RE = re.compile(r"(大喜|狂喜|惊喜|庆祝|狂欢|中奖|升职|加薪|表白成功|求婚|中了|大赚)")
# "无因"的判定：事件没有挂任何伏笔，也没留决策点，则视为凭空发生
_UNCAUSED = lambda ev: not ev.foreshadow_tags and not ev.decision_point


def estimate_cost(event: Event) -> int:
    """从事件文本里估计花费：有显式金额按金额，只有消费动词按保守默认 100 元，无则 0。"""
    text = f"{event.content} {event.detail}"
    amounts = [int(m) for m in _MONEY_RE.findall(text)]
    if amounts:
        return sum(amounts)
    return 100 if _SPEND_RE.search(text) else 0


# ---------- 约束校验 ----------

def validate_events(
    events: list[Event],
    state: ProtagonistState,
    skeleton: Skeleton,
) -> list[str]:
    """校验一天的事件列表，返回不合法原因（中文，空列表=合法）。

    规则：
    1. 时间塞得进槽：槽位必须存在于骨架；一个槽最多一个事件；固定槽只允许该固定安排本身。
    2. 钱够：事件估计花费之和不允许超过 state.money。
    3. 地点存在：事件地点必须在地点全集里。
    4. 情绪连续性：昨天收尾 mood < -50 时，今天不允许 intensity>=8 的"无因大喜"事件
       （无伏笔、无决策点、文本命中大喜词）。
    """
    reasons: list[str] = []
    known = known_locations(skeleton, state)
    seen_slots: set[SlotName] = set()
    total_cost = 0

    for i, ev in enumerate(events):
        tag = f"事件[{i}]({ev.slot}/{ev.kind})"
        # 1. 槽位
        if ev.slot not in SLOT_ORDER:
            reasons.append(f"{tag}：未知槽位 {ev.slot}")
            continue
        spec = skeleton.slots.get(ev.slot)
        if spec is None:
            reasons.append(f"{tag}：骨架中没有 {ev.slot} 槽")
        elif ev.slot in seen_slots:
            reasons.append(f"{tag}：槽位 {ev.slot} 已被占用，一天一个槽只能塞一个事件")
        else:
            seen_slots.add(ev.slot)
            if spec.kind == "fixed" and spec.label not in ev.content:
                reasons.append(
                    f"{tag}：{ev.slot} 是固定槽（{spec.label}），不接受其他事件"
                )
        # 3. 地点
        if ev.location and ev.location not in known:
            reasons.append(f"{tag}：地点「{ev.location}」不存在（不在地点注册表/骨架/当前所在地）")
        # 2. 钱
        total_cost += estimate_cost(ev)
        # 4. 情绪连续性
        if state.mood < -50 and ev.intensity >= 8 and ev.kind in ("incidental", "major"):
            if _JOY_RE.search(f"{ev.content} {ev.detail}") and _UNCAUSED(ev):
                reasons.append(
                    f"{tag}：昨天 mood={state.mood}，情绪低谷期不允许无因大喜（intensity={ev.intensity}，无伏笔无决策点）"
                )

    if total_cost > state.money:
        reasons.append(f"全天花费约 {total_cost} 元，超出余额 {state.money} 元")

    return reasons


# ---------- 状态回写 ----------

class EventOutcome(BaseModel):
    """一次事件结果的量化描述，由导演/结算方给出，物理层只负责落账。"""
    energy_delta: int = 0
    mood_delta: int = 0
    money_delta: int = 0
    mood_tags: list[str] = Field(default_factory=list)
    npc_facts: dict[str, list[str]] = Field(default_factory=dict)    # npc名 -> 新事实
    npc_debts: dict[str, list[str]] = Field(default_factory=dict)    # npc名 -> 新欠下的人情


def derive_outcome(event: Event, today: Optional[date] = None) -> EventOutcome:
    """无外部结算时的规则化默认结果：按 kind/intensity 给基础 delta，消费按 estimate_cost 扣钱。"""
    base = {"routine": (2, 0), "incidental": (0, 2), "major": (-6, 6), "reality": (-2, 1)}
    e, m = base.get(event.kind, (0, 0))
    scale = (event.intensity - 5) / 5.0  # intensity 高低微调
    outcome = EventOutcome(
        energy_delta=int(e + e * scale),
        mood_delta=int(m + (4 if event.kind != "routine" else 0) * scale),
        money_delta=-estimate_cost(event),
    )
    if today is not None:
        for actor in event.actors:
            if actor and actor != "你":
                outcome.npc_facts.setdefault(actor, []).append(
                    f"{today.month}/{today.day} {event.content}"
                )
    return outcome


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def apply_outcome(
    state: ProtagonistState,
    npc_map: dict[str, NpcState],
    event: Event,
    outcome: EventOutcome | Mapping,
    today: Optional[date] = None,
) -> ProtagonistState:
    """把事件结果回写：改主角 energy/mood/money（越界钳制），涉及 NPC 的写事实与 pending_debts。

    outcome 可以传 EventOutcome，也可以传等价的 dict。event.actors 里的 NPC 若不在 npc_map 中则忽略。
    原地修改并返回 state。
    """
    oc = outcome if isinstance(outcome, EventOutcome) else EventOutcome.model_validate(outcome)

    state.energy = _clamp(state.energy + oc.energy_delta, 0, 100)
    state.mood = _clamp(state.mood + oc.mood_delta, -100, 100)
    # 未显式给钱变化时，按规则估计扣款，保证"花钱必记账"
    money_delta = oc.money_delta if oc.money_delta != 0 else -estimate_cost(event)
    state.money = state.money + money_delta
    for tag in oc.mood_tags:
        if tag not in state.mood_tags:
            state.mood_tags.append(tag)

    for actor in event.actors:
        if not actor or actor == "你":
            continue
        npc = npc_map.get(actor)
        if npc is None:
            continue
        for fact in oc.npc_facts.get(actor, []):
            if fact not in npc.facts:
                npc.facts.append(fact)
        for debt in oc.npc_debts.get(actor, []):
            if debt not in npc.pending_debts:
                npc.pending_debts.append(debt)
        if today is not None:
            npc.last_seen = today

    # 事件自身挂的伏笔：有受惠 NPC 时默认记一笔人情债
    if event.foreshadow_tags and today is not None:
        for actor in event.actors:
            npc = npc_map.get(actor) if actor != "你" else None
            if npc is None:
                continue
            debt = f"{today.month}/{today.day} 因「{event.content}」欠下的人情（{','.join(event.foreshadow_tags)}）"
            if debt not in npc.pending_debts:
                npc.pending_debts.append(debt)

    return state


# ---------- 配额检查 ----------

def quota_check(recent_days: list) -> list[str]:
    """检查近若干天的配额，返回违反原因列表。recent_days 按日期升序，元素为 DayPlan（鸭子类型：
    只要求有 .date 与 .events）。规则：
    1. major 下限（硬性）：任意相邻两个 major 事件间隔不得超过 12 天；若记录跨度已 >= 12 天而
       从未出现 major，同样违规。
    2. 留白：每天必须至少有一个无事件槽（按 4 槽制，即一天事件数 <= 3）。
    """
    reasons: list[str] = []
    if not recent_days:
        return reasons

    # 1. major 节奏
    major_days = sorted(
        plan.date for plan in recent_days if any(ev.kind == "major" for ev in plan.events)
    )
    span_days = (recent_days[-1].date - recent_days[0].date).days
    if not major_days:
        if span_days >= 12:
            reasons.append(
                f"配额违规：近 {span_days} 天没有任何 kind=major 事件（硬性下限：每 7-12 天一次）"
            )
    else:
        for prev, nxt in zip(major_days, major_days[1:]):
            gap = (nxt - prev).days
            if gap > 12:
                reasons.append(f"配额违规：major 事件间隔 {gap} 天（{prev} → {nxt}），超过 12 天上限")
        tail_gap = (recent_days[-1].date - major_days[-1]).days
        if tail_gap > 12:
            reasons.append(
                f"配额违规：最近一次 major 在 {major_days[-1]}，已 {tail_gap} 天没有新的 major"
            )

    # 2. 每天留白
    for plan in recent_days:
        used = {ev.slot for ev in plan.events}
        if len(used) >= len(SLOT_ORDER):
            reasons.append(f"配额违规：{plan.date} 四个槽全被事件占满，没有留白槽")

    return reasons


def days_since_last_major(recent_days: list, today: date) -> int:
    """辅助：距上一次 major 事件过了多少天（从未有过则返回 -1），供导演判断戏剧时机。"""
    last = None
    for plan in recent_days:
        if any(ev.kind == "major" for ev in plan.events):
            last = plan.date
    if last is None:
        return -1
    return (today - last).days


def due_foreshadows(foreshadows: list, today: date, horizon_days: int = 3) -> list:
    """辅助：按 urgency/opened_on 挑出"戏剧时机已到"的伏笔（打开越久/越紧急越靠前）。"""
    def score(fs):
        age = (today - fs.opened_on).days
        return (fs.urgency, age)
    return sorted(
        (fs for fs in foreshadows if (today - fs.opened_on).days >= max(1, 6 - fs.urgency * horizon_days // 5)),
        key=score,
        reverse=True,
    )
