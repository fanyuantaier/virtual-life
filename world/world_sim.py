"""世界自转引擎：世界有独立于主角的一条线。

P1（借鉴优先级第一）：矮人要塞的世界历史 / 太吾的 NPC 生态 / Kenshi 的势力演化。
借鉴的是"世界有独立于主角的一条线"，不是具体系统。

设计：
- 世界时间 = 真实日期，与主角同步，但世界事件不需要主角在场；
- NPC 之间有关系网（A-B 关系独立于他们与主角的关系）；
- NPC 有自己的目标（换工作、相亲、搬家、备考），按日程推进，主角只能看到"迹象"；
- 世界编年史独立记录：世界事件写 world_chronicle（导演读得到、主角"记忆"里没有——
  信息不对称的基础，P3 传闻系统从这里接管"哪些世界事件传到了主角耳朵里"）；
- 季节/节气影响世界事件池（春节=返乡、夏天=台风、双十一=快递爆仓）。

与 npc_sim.py 的分工：npc_sim 管"NPC 主动找主角"，world_sim 管"NPC 自己过日子"。
"""
from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import config

# ---------- NPC 之间关系网（与主角无关的独立关系） ----------

NPC_RELATIONS: dict[tuple[str, str], int] = {
    ("小李", "老周"): 20,      # 同组同事，关系一般（老周批过他交付）
    ("小李", "阿蔓"): 5,       # 点头之交
    ("妈妈", "外婆"): 45,      # 姐妹（若外婆同住则是母女）
    ("老周", "爸爸"): -10,     # 不认识，0 分也无妨
}


def npc_relation(a: str, b: str) -> int:
    """NPC 之间的关系值（与主角无关）。"""
    return NPC_RELATIONS.get((a, b), NPC_RELATIONS.get((b, a), 0))


def bump_npc_relation(a: str, b: str, delta: int) -> None:
    k = (a, b) if (a, b) in NPC_RELATIONS else ((b, a) if (b, a) in NPC_RELATIONS else (a, b))
    NPC_RELATIONS[k] = NPC_RELATIONS.get(k, 0) + delta


# ---------- NPC 长期目标（世界自转的引擎：目标推进产生事件） ----------

NPC_GOALS: dict[str, dict] = {
    # 目标有阶段，每阶段世界 tick 有概率推进；推进到"临近完成"时最容易产生迹象事件
    "小李": {"goal": "跳槽准备", "stage": 0, "max_stage": 3,
             "signs": ["更新了简历", "请了半天假说去办事", "工位上多了快递箱", "和陌生人在咖啡馆见面"]},
    "老周": {"goal": "评职称", "stage": 0, "max_stage": 2,
             "signs": ["抱着一摞材料找领导", "办公室灯亮到很晚"]},
    "阿蔓": {"goal": "接大单插画", "stage": 0, "max_stage": 2,
             "signs": ["连续几天没出门", "网购了数位板笔尖", "客厅堆了打样纸"]},
}

# ---------- 季节事件池（节气驱动，世界级背景事件） ----------

SEASON_EVENTS = [
    (12, 1, "春节前，小区快递架堆成山，代收点老板嗓子都哑了"),
    (12, 15, "开始有人家往门口贴春联，胶带撕拉声此起彼伏"),
    (3, 5, "惊蛰一过，小区绿化带的猫开始成群出现"),
    (6, 20, "梅雨季，全小区的晾衣杆都是满的"),
    (8, 10, "台风外围过境，物业挨家挨户提醒关窗"),
    (11, 11, "双十一快递高峰，物流园堵到马路上"),
]


class WorldSim:
    """世界自转：每次 world_tick 推进一天的世界事件，写世界编年史。"""

    def __init__(self, chronicle_path: Path | None = None, seed: int | None = None):
        self.chronicle_path = chronicle_path or (config.DATA_DIR / "world_chronicle.md")
        self.rng = random.Random(seed)
        self.chronicle_path.parent.mkdir(parents=True, exist_ok=True)

    def _append_chronicle(self, d: date, text: str, visible: bool) -> None:
        """世界编年史：visible=True 表示这是公开事件（P3 传闻系统可传给主角）；
        visible=False 是主角视角看不到的暗线（导演可以拿来埋迹象）。"""
        tag = "公开" if visible else "暗线"
        with self.chronicle_path.open("a", encoding="utf-8") as f:
            f.write(f"[{d.isoformat()}][{tag}] {text}\n")

    def read_chronicle(self, visible_only: bool = True, last_n: int = 20) -> list[str]:
        """读世界编年史。导演读全部（含暗线，用来埋迹象）；
        传闻系统只读公开行（visible_only=True）。"""
        if not self.chronicle_path.exists():
            return []
        lines = self.chronicle_path.read_text(encoding="utf-8").splitlines()
        if visible_only:
            lines = [l for l in lines if "[公开]" in l]
        return lines[-last_n:]

    def tick(self, today: date) -> list[dict]:
        """推进一天的世界。返回今天发生的世界事件列表（供导演输入）。"""
        events: list[dict] = []

        # 1) 季节背景事件（到日子就发生，确定性）
        for month, day, desc in SEASON_EVENTS:
            if today.month == month and today.day == day:
                events.append({"kind": "season", "text": desc, "visible": True})

        # 2) NPC 目标推进（世界自转核心：目标推进到后期 → 泄漏迹象）
        for npc, g in NPC_GOALS.items():
            if g["stage"] >= g["max_stage"]:
                continue
            p = 0.15 if g["stage"] == 0 else (0.30 if g["stage"] == 1 else 0.45)
            if self.rng.random() < p:
                g["stage"] += 1
                if g["stage"] >= g["max_stage"]:
                    # 目标完成：世界级事件（主角可能后来才知道）
                    events.append({"kind": "goal_done", "npc": npc,
                                   "text": f"{npc}的「{g['goal']}」有了结果", "visible": True})
                    self._append_chronicle(today, f"{npc}完成了「{g['goal']}」", visible=True)
                else:
                    # 推进中：泄漏一个迹象（暗线——主角视角看不到，导演可见）
                    sign = self.rng.choice(g["signs"])
                    events.append({"kind": "goal_sign", "npc": npc, "text": f"{npc}{sign}",
                                   "visible": False})
                    self._append_chronicle(today, f"迹象：{npc}{sign}", visible=False)

        # 3) NPC 之间关系漂移（与主角无关的世界线）
        if self.rng.random() < 0.3:
            keys = list(NPC_RELATIONS.keys())
            if keys:
                k = self.rng.choice(keys)
                delta = self.rng.choice([-3, -2, 2, 3])
                NPC_RELATIONS[k] += delta
                if abs(NPC_RELATIONS[k]) > 40:   # 关系剧变：世界级事件
                    a, b = k
                    events.append({"kind": "npc_drift", "text":
                                   f"{a}和{b}的关系{'明显变好' if delta > 0 else '出了些问题'}",
                                   "visible": False})
                    self._append_chronicle(today, f"{a}与{b}关系{'升温' if delta > 0 else '恶化'}",
                                           visible=False)

        # 4) 世界编年史：把今天的公开事件记下来
        for e in events:
            if e["visible"]:
                self._append_chronicle(today, e["text"], visible=True)
        return events


def world_block(events: list[dict], include_hidden: bool = True) -> str:
    """给导演 prompt 的世界事件块。include_hidden=False 时过滤暗线（主角视角）。"""
    lines = []
    for e in events:
        if not include_hidden and not e["visible"]:
            continue
        lines.append(f"- {e['text']}")
    return "\n".join(lines) or "（世界今天风平浪静）"
