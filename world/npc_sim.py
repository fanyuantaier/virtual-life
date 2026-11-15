"""NPC 离屏演化：主角看不见的时间里，NPC 们也在过日子。

设计（阶段2-3）：
- 纯规则 + random，不用 LLM——NPC 不是导演，是背景物理；
- pending_debts 老化：挂账超 3 天 urgency 升，超 7 天关系缓降（被遗忘的人情会凉）；
- relationship 回归均值：没有互动就向 0 缓慢漂移；
- 主动事件：小概率触发（受关系/欠账状态调制），产出"次日事件建议"交给导演消化，
  导演必须把它编进当天（作为 reality/incidental 事件），不许无视。

用法：
    sim = NpcSim(npc_map)
    initiatives = sim.advance(today)   # 每天调用一次，返回 list[dict]
"""
from __future__ import annotations

import random
from datetime import date
from typing import Any

# 主动事件模板：按触发条件挑，填 NPC 名即成事件建议
_TEMPLATES = [
    {"trigger": "debt",   "weight": 3.0,
     "text": "{npc}突然来电，语气随意但话里带话，像是想起了什么没结的事"},
    {"trigger": "debt",   "weight": 2.0,
     "text": "{npc}发来消息：「最近怎么样？」——你们上次的约定还悬着"},
    {"trigger": "high_rel", "weight": 2.0,
     "text": "{npc}主动约你，说最近发现了个好玩的地方"},
    {"trigger": "high_rel", "weight": 1.5,
     "text": "{npc}碰巧路过你家附近，问要不要一起吃个饭"},
    {"trigger": "low_rel", "weight": 2.0,
     "text": "听说{npc}最近不太顺，熟人之间传开了"},
    {"trigger": "always", "weight": 0.8,
     "text": "{npc}在小区群里发了个奇怪的表情包，没头没尾"},
]


def _weighted_pick(options: list[dict]) -> dict:
    total = sum(t["weight"] for t in options)
    r = random.uniform(0, total)
    acc = 0.0
    for t in options:
        acc += t["weight"]
        if r <= acc:
            return t
    return options[-1]


class NpcSim:
    def __init__(self, npc_map: dict[str, Any], seed: int | None = None):
        self.npcs = npc_map
        self.rng = random.Random(seed)   # 可复现；不传则真随机

    def advance(self, today: date) -> list[dict]:
        """推进一天：老化+漂移+主动事件。返回事件建议列表。"""
        initiatives: list[dict] = []
        for npc in self.npcs.values():
            # 1) 欠账老化：>3 天紧迫度涨、>7 天关系缓降
            for i, debt in enumerate(list(npc.pending_debts)):
                age = self._debt_age(npc, debt, today)
                if age > 7 and self.rng.random() < 0.3:
                    npc.relationship = max(-100, npc.relationship - 1)
                    npc.pending_debts[i] = f"{debt}（晾了{age}天，对方有点介意）"
            # 2) 关系回归均值（无互动时向 0 漂 1 点，10% 概率）
            if self.rng.random() < 0.10:
                step = -1 if npc.relationship > 0 else (1 if npc.relationship < 0 else 0)
                npc.relationship += step
            npc.last_seen = npc.last_seen or today

            # 3) 主动事件：基础 8%，被状态调制
            p = 0.08
            if npc.pending_debts:
                p += 0.12                     # 有人情悬着，更可能来找我
            if npc.relationship > 40:
                p += 0.06                     # 关系好，爱约你
            if npc.relationship < -20:
                p -= 0.04                     # 关系僵，躲着你
            if self.rng.random() >= p:
                continue

            options = [t for t in _TEMPLATES if self._trigger_ok(t["trigger"], npc)]
            if not options:
                continue
            tpl = _weighted_pick(options)
            initiatives.append({
                "npc": npc.name,
                "relationship": npc.relationship,
                "text": tpl["text"].format(npc=npc.name),
                "kind": "npc_initiative",
            })
        return initiatives

    def _trigger_ok(self, trigger: str, npc: Any) -> bool:
        if trigger == "always":
            return True
        if trigger == "debt":
            return bool(npc.pending_debts)
        if trigger == "high_rel":
            return npc.relationship >= 30
        if trigger == "low_rel":
            return npc.relationship <= -10
        return False

    @staticmethod
    def _debt_age(npc: Any, debt: str, today: date) -> int:
        """从 debt 文本里的（晾了N天）标记或 NPC.last_seen 估算挂账天数。"""
        import re
        m = re.search(r"晾了(\d+)天", debt)
        if m:
            return int(m.group(1))
        if npc.last_seen:
            return max(0, (today - npc.last_seen).days)
        return 1
