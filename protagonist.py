"""主角层：收事件脚本 → 反应/决策 → 日记。人格的声音，独立于导演。

接口（供 scheduler.runner 调用）：
    react(dayplan_events, memory_hits, persona_text) -> (list[DiaryEntry], list[DecisionResult])
"""
from __future__ import annotations

import json
from datetime import date
from typing import Protocol

from openai import OpenAI
from pydantic import ValidationError

from contracts import DecisionResult, DiaryEntry, Event, MemoryHit
import config


class _Client(Protocol):
    def chat(self, prompt: str, system: str) -> str: ...


SYSTEM_TMPL = """你是一个生活在模拟世界里的普通人，名字叫「小澄」。下面是你的人格与自我认知：

{persona}

规则：
- 你收到的是「今天这一段发生在你身上的事」。它们是世界对你的安排，你只能反应，不能改写事实本身。
- 但你怎么感受、怎么想、做什么，完全由你决定。
- 对每个事件：写一段第一人称日记（2-4 句，口语化，允许琐碎和无聊——生活大部分是无聊的），打 1-3 个情绪标签，按内心触动程度打分 0-150。
- 如果事件带 decision=true：先给出你的选择和真实理由（不要讨好任何人，按你的人格来）。
- 只输出 JSON：{{"entries": [{{"slot": "...", "text": "...", "emotion_tags": ["..."], "poignancy": 0}}], "decisions": [{{"question": "...", "choice": "...", "inner_reason": "..."}}]}}"""


def react(client: _Client, persona_text: str, events: list[Event],
          memory_hits: list[MemoryHit],
          sim_date: date | None = None,
          slot_hint: str = "morning") -> tuple[list[DiaryEntry], list[DecisionResult]]:
    """主角对一段事件脚本做反应。memory_hits 已由调用方检索好。
    sim_date=模拟世界日期（用于日记文件名），不传则用真实日期。
    slot_hint=当前段名（events 为空时占位日记用）。"""
    _sim_date = sim_date or date.today()
    memory_block = "\n".join(
        f"- [{h.when:%m-%d}] {h.text}" for h in memory_hits
    ) or "（没有想起什么特别的事）"

    events_block = "\n".join(
        f"[{e.slot}|{e.kind}|强度{e.intensity}] 在{e.location}，{('和' + '、'.join(e.actors) + '一起，') if e.actors else ''}{e.content}"
        + (f"（细节：{e.detail}）" if e.detail else "")
        + ("【需要你做决定】" if e.decision_point else "")
        for e in events
    )

    system = SYSTEM_TMPL.format(persona=persona_text)
    user = f"""你想起的一些往事：
{memory_block}

今天这一段发生的事：
{events_block}"""

    resp = client.chat(user, system)
    data = _parse_json(resp)
    entries: list[DiaryEntry] = []
    decisions: list[DecisionResult] = []
    for raw in data.get("entries", []):
        try:
            raw.setdefault("date", _sim_date)
            entries.append(DiaryEntry(**raw))
        except (ValidationError, TypeError):
            continue
    for raw in data.get("decisions", []):
        try:
            decisions.append(DecisionResult(**raw))
        except ValidationError:
            continue
    # 兜底：模型偶发返回空 entries（尤其段内事件少时）——用事件本身生成最小日记，
    # 保证日记流不断档（宁可平淡，不可断流）
    if not events:
        # 空时段兜底：这一天这个时段本来就无事——生成"平静的一段"日记，日记流不断档
        return ([(DiaryEntry(date=_sim_date, slot=slot_hint,
                             text="（这一段没什么特别的事，平平静静地过去了。）",
                             emotion_tags=["平静"], poignancy=1))], [])
    if not entries and events:
        for e in events:
            entries.append(DiaryEntry(
                date=_sim_date, slot=e.slot,
                text=f"（{e.location}）{e.content}",
                emotion_tags=["平淡"], poignancy=max(1, e.intensity * 3)))
    return entries, decisions


def _parse_json(text: str) -> dict:
    """容忍 ```json 围栏与 <think> 块。"""
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
