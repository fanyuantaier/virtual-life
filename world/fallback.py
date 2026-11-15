"""规则化兜底日：LLM 不可用时，世界照常转动。

设计（阶段3 时间同步的兜底）：
- 现实时钟不会因为 LLM 网关抽风而停下——导演连续失败时，用骨架+状态+伏笔
  规则化生成"平淡但真实"的一天（通勤、吃饭、天气、昨天事件的余波）；
- 不调任何 LLM，永不失败；
- 事件结构完全合规（过物理校验），细节从现实钩子和最近记忆里取。

这符合"千篇一律"的底色：生活大部分日子本来就该平淡无奇。
"""
from __future__ import annotations

from datetime import date

from contracts import DayPlan, Event, ProtagonistState


_ROUTINE = {
    "workday": [
        ("morning", "公司", "routine", "07:20 出门上班，路上买了早餐，地铁比平时挤一些。", 1),
        ("afternoon", "公司", "routine", "15:40 上班的活有点赶，眼睛盯屏幕发酸。", 1),
        ("evening", "小区", "routine", "18:40 下班路过小区门口，闻到人家炒菜的油烟味。", 1),
        ("night", "家", "routine", "22:50 洗完澡躺在床上，刷了会儿手机就困了。", 1),
    ],
    "weekend": [
        ("morning", "家", "routine", "09:30 醒来，被楼下小孩的吵闹声叫醒的。", 1),
        ("afternoon", "超市", "routine", "15:00 去超市补了点吃的，排队的工夫把购物清单又看了一遍。", 1),
        ("evening", "家", "routine", "19:30 晚饭随便对付了一口，饭后在小区里走了两圈。", 1),
        ("night", "家", "routine", "23:10 夜里安静，只有冰箱的嗡嗡声。", 1),
    ],
}

_WEATHER_INSERTS = {
    "rain": ("evening", "家", "routine", "傍晚下雨了，窗玻璃上的水痕一道叠着一道。", 2),
    "clear": ("afternoon", "小区", "routine", "下午阳光很好，晾在阳台的衣服干得很快。", 1),
}


def fallback_day(today: date, state: ProtagonistState,
                 weather: dict | None = None,
                 last_events: list[str] | None = None) -> DayPlan:
    """规则化生成一天：骨架例程 + 天气插事件 + 昨日余波一条。"""
    template = _ROUTINE["weekend" if today.weekday() >= 5 else "workday"]
    events = []
    for slot, loc, kind, content, inten in template:
        events.append(Event(slot=slot, kind=kind, location=loc, actors=[],
                            content=content, detail="", intensity=inten,
                            decision_point=False, foreshadow_tags=[]))
    used = {e.slot for e in events}
    if weather:
        key = "rain" if weather.get("is_rain") else "clear"
        slot, loc, kind, content, inten = _WEATHER_INSERTS[key]
        if slot not in used:               # 槽位冲突时放弃插入，不硬塞
            events.append(Event(slot=slot, kind=kind, location=loc, actors=[],
                                content=content, detail="", intensity=inten,
                                decision_point=False, foreshadow_tags=[]))
            used.add(slot)
    for prev in (last_events or [])[:1]:
        slot = "night" if "night" not in used else ("evening" if "evening" not in used else None)
        if slot is None:
            break
        events.append(Event(slot=slot, kind="routine",
                            location="家", actors=[],
                            content=f"想起昨天的事：{prev[:40]}，心里有点感触。",
                            detail="", intensity=2, decision_point=False,
                            foreshadow_tags=[]))
        used.add(slot)
    return DayPlan(date=today, events=events)
