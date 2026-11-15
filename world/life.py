"""人生起点：无人设出生参数 + 年龄阶段引擎。

阶段4 核心变化：
- 不再有人设文件（self.md 头部清空为出生参数）——人格 100% 由经历沉淀；
- 家庭/环境由规则随机生成（种子可复现），主角不选择自己的出身；
- 年龄阶段决定：时间流速、语言能力、日记形态、记忆策略。

与 adult 线的关系：adult 模式保留（stage_for_age(>=18) 走原逻辑），
新生效的是 life 模式：python life.py --seed 42 从 0 岁开始。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# ---------- 年龄阶段表 ----------

LIFE_STAGES: dict[str, dict] = {
    # 流速: 1 现实小时 = N 模拟天
    "infant":  {"age": (0, 3),   "hours_per_day": 1 / 24, "style": "fragment",
                "note": "感官碎片：只有感觉、声音、温度、谁在身边，没有因果叙述"},
    "toddler": {"age": (3, 6),   "hours_per_day": 1 / 8,  "style": "simple",
                "note": "简单句：3-10 个字的短句，关注点单一（吃、玩、怕、想要）"},
    "child":   {"age": (6, 12),  "hours_per_day": 1 / 2,  "style": "full",
                "note": "完整口语：有因果叙述，会评价人和事，开始有秘密"},
    "teen":    {"age": (12, 18), "hours_per_day": 2,      "style": "full",
                "note": "少年口吻：自我意识强，在意别人怎么看，情绪波动大"},
    "adult":   {"age": (18, None), "hours_per_day": None,  "style": "full",
                "note": "成人：完整第一人称叙述"},
}


def stage_for_age(age: float) -> str:
    for name, spec in LIFE_STAGES.items():
        lo, hi = spec["age"]
        if hi is None:
            if age >= lo:
                return name
        elif lo <= age < hi:
            return name
    return "adult"


def hours_for_stage(stage: str) -> Optional[float]:
    """1 现实小时 = N 模拟天；None = 实时。"""
    return LIFE_STAGES[stage]["hours_per_day"]


def style_note(stage: str) -> str:
    return LIFE_STAGES[stage]["note"]


INFANT_DIRECTIVE = {
    "infant": (
        "主角是{age:.1f}岁的婴儿。这一天的『事件』不是他做的事，而是发生在他身上的：\n"
        "- 吃奶/辅食、睡觉、哭闹、被抱、换尿布、洗澡、有人逗他、听到声音、看到颜色移动的东西\n"
        "- 他不能说话，日记只能是感官碎片：暖、响、亮、软、怕、困——没有因果，没有时间概念\n"
        "- 家人（依恋对象）的脸和声音是世界的全部坐标\n"
    ),
    "toddler": (
        "主角是{age:.1f}岁的幼儿。能走路、说短句、表达想要/不要：\n"
        "- 事件：玩玩具、摔倒、第一次见到某样东西、被批评、看动画片、跟大人去菜市场/公园\n"
        "- 日记是 3-10 字的短句拼接，关注点单一：想吃、想玩、怕、开心\n"
    ),
    "child": (
        "主角是{age:.1f}岁的孩子。上学了，有自己的朋友和秘密：\n"
        "- 事件：上课、写作业、和同学玩、被表扬/批评、看电视、第一次零花钱\n"
        "- 日记完整口语但有孩子气的因果（『因为他先动手所以我打了他』）\n"
    ),
    "teen": (
        "主角是{age:.1f}岁的少年。中学，自我意识爆发：\n"
        "- 事件：考试、和朋友的关系起伏、暗恋/在乎别人看法、和家长冲突、网络世界\n"
        "- 日记少年口吻：情绪浓度高，在意『别人怎么看我』\n"
    ),
}


def stage_directive(stage: str, age: float) -> str:
    tpl = INFANT_DIRECTIVE.get(stage)
    if not tpl:
        return ""
    return tpl.format(age=age)


# ---------- 出生参数（规则随机，无人设） ----------

@dataclass
class BirthParams:
    seed: int
    city: str                     # 城市（决定天气/新闻的现实锚定）
    family_type: str              # 家庭结构
    parent_jobs: list[str]        # 父母职业
    economy: str                  # 经济水平
    temperament: list[str]        # 先天气质（唯一保留的"内生"设定：不是人格，是禀赋）
    birth_date: date = field(default=None)

    def render(self) -> str:
        """给导演/主角 prompt 用的家庭环境卡（无人设，只有事实）。"""
        return (
            f"出生地：{self.city}。家庭：{self.family_type}，"
            f"父亲是{self.parent_jobs[0]}，母亲是{self.parent_jobs[1]}。"
            f"家境{self.economy}。先天气质：{ '、'.join(self.temperament) }。"
        )


_CITIES = ["杭州", "成都", "长沙", "青岛", "西安", "苏州"]
_FAMILY = ["三口之家", "与祖父母同住的大家庭", "父母离异随母亲", "父母离异随父亲", "二胎家庭"]
_JOBS = ["教师", "司机", "护士", "程序员", "个体户", "工人", "公务员", "销售", "厨师", "会计"]
_ECONOMY = ["拮据", "普通", "普通", "小康", "小康", "宽裕"]
_TEMPERAMENT = [
    ["敏感", "观察型"], ["活泼", "好动"], ["安静", "专注"],
    ["胆小", "恋物"], ["倔强", "好奇心强"], ["黏人", "爱笑"],
]


def generate_birth(seed: int, birth_date: Optional[date] = None) -> BirthParams:
    rng = random.Random(seed)
    jobs = rng.sample(_JOBS, 2)
    return BirthParams(
        seed=seed,
        city=rng.choice(_CITIES),
        family_type=rng.choice(_FAMILY),
        parent_jobs=jobs,
        economy=rng.choice(_ECONOMY),
        temperament=rng.choice(_TEMPERAMENT),
        birth_date=birth_date or date.today(),
    )
