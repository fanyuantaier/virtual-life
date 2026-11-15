"""内在需求衰减与心理阈值：状态逼出事件。

P2（借鉴优先级第二）：RimWorld 的心理阈值 / Sims 的需求衰减 / CK3 的性格驱动决策。
借鉴"事件由状态耦合触发"——状态不是被动记录，而是会主动"造"事件的引擎。

设计：
- 四项需求持续衰减（每天 tick 一次）：社交 / 独处 / 成就 / 安全；
- 需求由事件改变：和人吃饭→社交+30；一个人待一天→社交-10；被表扬→成就+20……
- 需求跌破阈值 → 生成"状态逼出的事件"注入导演输入（孤独累积→今天特别想找人说话；
  钱少+成就低→晚上睡不着琢磨兼职）；
- 性格修正系数：先天气质改衰减速度和阈值（倔的人更不肯求助，安全需求阈值更高）；
- 与导演的耦合：需求块进 prompt，导演必须让今天的天气/事件与状态匹配
  （情绪锁的升级版：从"昨天丧今天不许大喜"升级为"需求状态决定今天的色彩"）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config

# ---------- 需求模型 ----------

# 衰减/日（负值=自然流失；社交这类每天必须补充，独处则相反）
DECAY = {"social": -8, "solitude": -4, "achievement": -5, "safety": -2}

# 阈值：跌破触发状态事件
THRESHOLDS = {"social": 25, "solitude": 20, "achievement": 25, "safety": 30}

# 事件 → 需求变化（导演/物理层结算用）
EVENT_EFFECTS = {
    "和人吃饭": {"social": +25},
    "一个人待一天": {"solitude": +20, "social": -10},
    "被表扬": {"achievement": +20},
    "被批评": {"achievement": -15, "mood": -10},
    "考试/交付": {"achievement": +10, "safety": -5},
    "和妈妈通话": {"social": +15, "safety": +10},
    "见爸爸": {"safety": +5, "social": +10},
    "加班": {"solitude": +5, "achievement": +5, "social": -10},
    "独处爱好(书/游戏)": {"solitude": +15},
}

# 性格修正：先天气质 → 衰减速度倍率与阈值偏移
TEMPERAMENT_MODS = {
    "活泼": {"social": {"decay": 1.3, "threshold": +5}},      # 活泼的人更怕孤独
    "好动": {"achievement": {"decay": 1.2}},
    "安静": {"solitude": {"decay": 0.6, "threshold": -10}},   # 安静的人独处需求恢复慢、更耐独处
    "专注": {"achievement": {"threshold": -5}},
    "敏感": {"safety": {"decay": 1.4, "threshold": +10}},     # 敏感的人安全感流失快、要求高
    "观察型": {"solitude": {"threshold": -5}},
    "胆小": {"safety": {"threshold": +15}},
    "恋物": {"safety": {"threshold": +5}},
    "倔强": {"achievement": {"threshold": +10}},
    "好奇心强": {"achievement": {"decay": 1.3}},
    "黏人": {"social": {"decay": 1.5, "threshold": +15}},
    "爱笑": {"social": {"threshold": -5}},
}

# 阈值触发 → 状态逼出的事件描述（导演必须编进今天）
TRIGGER_EVENTS = {
    "social": "孤独累积到顶了——今天会特别想找人说话，哪怕只是闲聊；谁先出现就会拉着谁多说几句",
    "solitude": "被人消耗太久了——今天会找借口推掉一切邀约，一个人待着才回血",
    "achievement": "成就感见底了——今天会特别想做成一件哪怕很小的事，做不成就睡不好",
    "safety": "安全感在流失——今天会对钱、对工作、对家人的健康格外敏感，一点风吹草动就多想",
}


@dataclass
class Needs:
    social: float = 60
    solitude: float = 60
    achievement: float = 50
    safety: float = 60
    temperament: list[str] = field(default_factory=list)

    def decay_today(self) -> dict[str, float]:
        """每日衰减（性格修正），返回实际变化量。"""
        deltas = {}
        for k, base in DECAY.items():
            mult = 1.0
            for t in self.temperament:
                mod = TEMPERAMENT_MODS.get(t, {}).get(k, {})
                mult *= mod.get("decay", 1.0)
            d = base * mult
            cur = getattr(self, k)
            new = max(0, min(100, cur + d))
            setattr(self, k, new)
            deltas[k] = new - cur
        return deltas

    def triggered(self) -> list[str]:
        """跌破阈值的需求 → 状态逼出的事件（导演输入）。"""
        out = []
        for k, th in THRESHOLDS.items():
            th_adj = th
            for t in self.temperament:
                th_adj += TEMPERAMENT_MODS.get(t, {}).get(k, {}).get("threshold", 0)
            if getattr(self, k) < th_adj:
                out.append(TRIGGER_EVENTS[k])
        return out

    def apply_event(self, effects: dict[str, float]) -> None:
        """事件结算：按 EVENT_EFFECTS 改需求。"""
        for k, v in effects.items():
            if hasattr(self, k):
                setattr(self, k, max(0, min(100, getattr(self, k) + v)))

    def block(self) -> str:
        """给导演 prompt 的需求块。"""
        t = self.triggered()
        lines = [f"内在需求：社交{self.social:.0f}/100 独处{self.solitude:.0f}/100 "
                 f"成就{self.achievement:.0f}/100 安全{self.safety:.0f}/100"]
        if t:
            lines.append("【状态逼出的事件，必须体现进今天】")
            lines += [f"- {x}" for x in t]
        else:
            lines.append("需求都在阈值之上，今天状态平稳。")
        return "\n".join(lines)


def init_from_birth(temperament: list[str]) -> Needs:
    return Needs(temperament=temperament)
