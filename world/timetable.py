"""细颗粒时段表：把一天切成带钟点的时段，替代粗粒度四槽。

阶段3：时间线同步。设计：
- HOURLY_SLOTS（config）定义一天的时刻表：每个时刻有槽名与钟点；
- Event 契约不变（slot 字段仍用 morning/...），新增 time_label（"07:30"）放 detail 前；
- build_skeleton 不变（槽位逻辑复用），导演 prompt 额外拿到时刻表；
- 调度器实时模式：按 TIME_SCALE 换算现实钟点 → 决定当前该跑哪个时段。

时刻表即"生活的骨架"：07:00 起床、09:00 到岗、12:00 午饭……
导演在此骨架上填肉，事件自然带钟点，日记像真的流水账。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import config


def time_slots_for_day(day) -> list[tuple[str, str]]:
    """返回当天时刻表 [(钟点"HH:MM", 槽名)]，过滤掉非工作日的上班时刻。"""
    slots = list(config.HOURLY_SLOTS)
    if day.weekday() >= 5:                     # 周末：09:00 视为起床，无 09:00 到岗语义
        return slots
    return slots


def current_slot(now: datetime, sim_midnight: datetime) -> tuple[str, str]:
    """按现实时钟返回 (钟点标签, 槽名)。实时模式下每个时刻表条目是锚点，
    落在两个锚点之间时归前一个锚点（07:15 属于 07:00 槽）。"""
    minutes = (now - sim_midnight).total_seconds() / 60.0
    label, slot = config.HOURLY_SLOTS[0][1], config.HOURLY_SLOTS[0][1]
    label = config.HOURLY_SLOTS[0][0]
    slot = config.HOURLY_SLOTS[0][1]
    for hhmm, name in config.HOURLY_SLOTS:
        h, m = map(int, hhmm.split(":"))
        if minutes >= h * 60 + m:
            label, slot = hhmm, name
    return label, slot


def slot_time_window(hhmm: str, span_minutes: int = 150) -> tuple[datetime, datetime]:
    """锚点时刻 → (开始, 结束) 时间窗，供调度器判断该不该跑这一段。"""
    h, m = map(int, hhmm.split(":"))
    start = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    return start, start + timedelta(minutes=span_minutes)


def format_timetable() -> str:
    """给导演 prompt 用的时刻表文本。"""
    lines = []
    for hhmm, name in config.HOURLY_SLOTS:
        lines.append(f"{hhmm}（{name}）")
    return "、".join(lines)
