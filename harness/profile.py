"""消耗力度档位：控制 token 消耗强度。

三档（配额 500M/日，夜间窗口充裕时可开 max）：
- normal：日常维持——每天 4 槽+1 梦+1 反思，约 20-40M/日
- burst： 加密——每槽事件 2-3 → 4-6，梦境 1 → 3，反思加深（月度+周度），约 80-150M/日
- max：  灌满——额外跑历史月度重蒸馏、NPC 视角补写、对话自演 20 轮，约 200-400M/日

选择建议：白天 normal，夜里（23:00-09:00 窗口）burst/max。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IntensityProfile:
    name: str
    events_per_slot: tuple[int, int]      # 每槽事件数区间
    director_candidates: int              # 导演一次生成候选数
    dreams_per_night: int                 # 每晚梦境数
    monthly_jump_extra: int               # 月度跳跃额外重蒸馏月数（历史加密）
    self_chat_rounds: int                 # 对话自演轮数（NPC 视角补写）
    reflection_depth: str                 # daily / weekly / monthly
    parallel: int                         # 并发 LLM 调用数


PROFILES = {
    "normal": IntensityProfile(
        name="normal", events_per_slot=(1, 2), director_candidates=3,
        dreams_per_night=1, monthly_jump_extra=0, self_chat_rounds=0,
        reflection_depth="daily", parallel=1),
    "burst": IntensityProfile(
        name="burst", events_per_slot=(3, 5), director_candidates=3,
        dreams_per_night=3, monthly_jump_extra=0, self_chat_rounds=0,
        reflection_depth="weekly", parallel=2),
    "max": IntensityProfile(
        name="max", events_per_slot=(5, 8), director_candidates=5,
        dreams_per_night=5, monthly_jump_extra=6, self_chat_rounds=20,
        reflection_depth="monthly", parallel=3),
}


def get_profile(name: str) -> IntensityProfile:
    return PROFILES.get(name, PROFILES["normal"])
