"""传闻系统：信息不对称与失真。

P3（借鉴优先级第三）：CK3 的秘密与阴谋 / 太吾的立场差异 / Smallville 的信息传播。
借鉴"信息不对称和失真"——主角做的事经 NPC 的嘴传播，会延迟、会变样。

设计：
- 每个世界事件/NPC 事件带 visibility（公开/暗线）——world_sim 已打标；
- 传闻引擎：公开事件按概率逐日传播（NPC→NPC→可能传到主角耳朵里）；
- 失真：每传一手，文本按规则变异（数字夸大、细节丢失、人物替换）；
- 主角的"知道"状态：主角记忆里有的=知道；传闻到主角耳边的事件
  以 kind='rumor' 入库（标记 source=谁说的）——她能分清"亲历"和"听说"；
- 与世界编年史的关系：编年史是"真相记录"，传闻是"被传播污染的版本"。

失真规则（规则化，不用 LLM——传闻本来就是量大的事）：
- 第 1 手：原样（亲见者）；
- 第 2 手：丢失 20% 细节（后半句变模糊）；
- 第 3 手：数字 ±30%、"听说"前缀；
- 第 4+ 手：只剩一句话轮廓 + "不知道真假"。
"""
from __future__ import annotations

import random
import re
from datetime import date, timedelta

import config


def distort(text: str, hops: int, rng: random.Random) -> str:
    """按传播手数失真文本。"""
    if hops <= 1:
        return text
    if hops == 2:
        # 丢尾部细节
        parts = re.split(r"(?<=[。！？])", text)
        return "".join(parts[:max(1, len(parts) - 1)]).strip() or text
    if hops == 3:
        # 数字夸张 + 听说前缀
        numbers = re.findall(r"\d+", text)
        for n in numbers:
            new = max(1, int(int(n) * rng.uniform(1.2, 1.6)))
            text = text.replace(n, str(new))
        return "听说" + text
    # 4+ 手：只剩轮廓
    core = re.split(r"[，。！？]", text)[0]
    return f"不知道真假，据说{core}……"


class RumorEngine:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        # 传播状态：rumor_id -> (hops, last_npc, next_spread_day)
        self.spreads: dict[str, dict] = {}

    def seed_rumor(self, rumor_id: str, world_text: str, origin_npc: str,
                   today: date, npc_peers: list[str]) -> bool:
        """一个公开世界事件从知情 NPC 开始传播。"""
        if rumor_id in self.spreads:
            return False
        self.spreads[rumor_id] = {
            "text": world_text, "hops": 1, "holder": origin_npc,
            "next": today + timedelta(days=self.rng.randint(1, 3)),
            "peers": [p for p in npc_peers if p != origin_npc],
        }
        return True

    def tick(self, today: date, npc_names: list[str]) -> list[dict]:
        """推进传播：到期的传闻跳一手，可能落到主角耳朵（概率 40%）。
        返回今天传到主角耳朵的传闻列表。"""
        reached = []
        for rid, sp in list(self.spreads.items()):
            if today < sp["next"]:
                continue
            sp["hops"] += 1
            sp["next"] = today + timedelta(days=self.rng.randint(1, 3))
            # 换个持有者（在 NPC 网里传）
            others = [n for n in npc_names if n != sp["holder"]]
            if others:
                sp["holder"] = self.rng.choice(others)
            # 传到主角耳朵？
            if self.rng.random() < 0.40:
                distorted = distort(sp["text"], sp["hops"], self.rng)
                reached.append({"rumor_id": rid, "text": distorted,
                                "via": sp["holder"], "hops": sp["hops"]})
                # 传到主角后这事对她不再是秘密——从传播网移除（她知道了就完了）
                del self.spreads[rid]
            elif sp["hops"] >= 5:   # 传了五手还没到主角，凉了
                del self.spreads[rid]
        return reached

    def active_count(self) -> int:
        return len(self.spreads)
