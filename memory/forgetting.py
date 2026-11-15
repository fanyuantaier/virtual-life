"""遗忘曲线记忆：Ebbinghaus 衰减 + 关键性分级 + 旧记忆模糊化。

阶段4 第二需求。设计：
- 每条记忆 retention（保留度）随时间衰减：R = exp(-t / (S × K))，
  S=记忆强度（由关键性决定），K=统一时间常数；
- 关键性 key（0-3 级）在写入时判定：
    3 = 首次经历 / 高强度(intensity>=8) / 涉及依恋对象（父母、重要他人）
    2 = 有决策点、有情绪标签高分
    1 = 普通事件
    0 = 纯日常（默认）
- 检索时：key>=2 的记忆永不模糊，只降 recency；
  key<=1 的记忆按 retention 降质改写——细节丢失、只剩轮廓（"好像……"、"记得不太清"）；
  retention < 0.15 的普通记忆从检索池中淡出（不是删除——文件里还在，只是想不起来）；
- 模糊化是"检索时改写"而非"存储时破坏"：库里的原文永远在（可回溯），
  改变的只是"主角想起来了什么"——这才符合人脑：痕迹在，提取失真。

关键性写入接口：add(kind, text, ..., key=N)；不传时按规则自动判。
"""
from __future__ import annotations

import math
import random
import re

# 时间常数：retention 半衰期（天）× 关键性
_K = 3.0          # key=1 的半衰期约 2 天（exp(-t/(K*decay)) 调参见 retention()）
_DECAY_BY_KEY = {0: 6.0, 1: 14.0, 2: 45.0, 3: 180.0}   # 衰减常数（天）：key0 一周剩31%，key3 半年剩66%


_FLOOR_BY_KEY = {0: 0.0, 1: 0.0, 2: 0.05, 3: 0.30}   # 关键记忆的保留度下限（永不完全遗忘）


def retention(days: float, key: int) -> float:
    """保留度 0-1：key 越高衰减越慢；key3 有 0.30 下限（一生难忘的轮廓）。"""
    tau = _DECAY_BY_KEY.get(key, 2.5)
    r = math.exp(-max(0.0, days) / tau)
    return max(r, _FLOOR_BY_KEY.get(key, 0.0))


def is_key_memory(text: str, intensity: float = 1, actors: list[str] | None = None,
                  decision: bool = False, attachment_names: set[str] | None = None) -> int:
    """写入时自动判关键性（0-3）。"""
    key = 0
    if intensity >= 8:
        key = max(key, 3)
    if decision:
        key = max(key, 2)
    if actors and attachment_names:
        if set(actors) & attachment_names:
            key = max(key, 3 if intensity >= 5 else 2)
    # 首次经历：文本含"第一次/第一次见/从来没"
    if re.search(r"第一次|初次|从来没|头一回", text):
        key = max(key, 3)
    if intensity >= 5:
        key = max(key, 1)
    return key


def blur_text(text: str, keep_ratio: float, rng: random.Random | None = None) -> str:
    """把一条记忆按保留度模糊化：细节词随机脱落，句尾加不确定前缀。

    keep_ratio=1.0 原样；0.5 丢一半细节；<0.3 只剩一句轮廓。
    """
    rng = rng or random.Random()
    if keep_ratio >= 0.95:
        return text
    # 分句
    parts = re.split(r"(?<=[。！？，])", text)
    parts = [p for p in parts if p.strip()]
    keep_n = max(1, round(len(parts) * keep_ratio))
    kept = rng.sample(parts, keep_n) if len(parts) > keep_n else parts
    blurred = "".join(kept).strip()
    prefix = ("好像", "记得不太清了，大概", "模糊的印象是", "似乎是")
    if keep_ratio < 0.5:
        blurred = rng.choice(prefix) + blurred
    return blurred
