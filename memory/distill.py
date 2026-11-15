"""分层记忆蒸馏：借鉴 TencentDB-Agent-Memory 的 L0→L3 管线。

层次（适配单主角人生模拟）：
- L0 原始层：月度关键时刻/日常事件（现有 nodes 表，kind=event）——不动
- L1 事实层：从 L0 提取的原子事实（"怕吵"、"母亲每周日来电"、"不吃香菜"）
- L2 场景层：按生活域归纳的知识块（家庭关系、学校、习惯、恐惧、愿望）
- L3 画像层：稳定人格特质（相当于不断修正的"我是谁"）

蒸馏时机：年度反思时顺带做一次三层蒸馏（一年 96 个月 → 一次调用）；
检索时：L3 常驻 prompt，L2 按查询相关命中，L1/L0 按现有遗忘曲线检索。

存储：nodes 表加 distill 层字段（layer TEXT: L1/L2/L3），同一张表统一检索。
"""
from __future__ import annotations

import json

LAYER_PROMPTS = {
    "L1": """从下面的成长记录里提取「原子事实」：关于这个孩子的具体、可验证的小事实。
要求：每条一句话，主谓宾清楚；只写记录里有依据的；5-15 条。只输出 JSON：{"facts": ["...", "..."]}""",
    "L2": """把下面的事实归纳成「生活场景块」：家庭、学校/日常、习惯、恐惧、愿望五个域。
每域一段 50 字以内的白描。只输出 JSON：{"家庭": "...", "学校日常": "...", "习惯": "...", "恐惧": "...", "愿望": "..."}""",
    "L3": """基于下面的场景描述，写出这个孩子当前的稳定人格画像（5-8 条「他是……的人」句式）。
只写有行为证据支撑的特质，不要贴标签式的空话。只输出 JSON：{"traits": ["...", "..."]}""",
}


def distill(llm_chat, age_years: float, year_texts: list[str]) -> dict:
    """对一年的记忆做 L1→L2→L3 三层蒸馏。llm_chat(user, system)->str。
    返回 {"L1": [...], "L2": {...}, "L3": [...]}，任一层失败则该层为空。"""
    out = {"L1": [], "L2": {}, "L3": []}
    listing = "\n".join(f"- {t}" for t in year_texts[:60])

    # L1：原子事实
    try:
        raw = llm_chat(listing, LAYER_PROMPTS["L1"])
        data = _parse(raw)
        out["L1"] = [str(x) for x in data.get("facts", [])][:15]
    except Exception:
        pass
    if not out["L1"]:
        return out

    # L2：场景归纳
    try:
        raw = llm_chat("\n".join(f"- {f}" for f in out["L1"]), LAYER_PROMPTS["L2"])
        data = _parse(raw)
        out["L2"] = {k: str(v) for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}
    except Exception:
        pass

    # L3：人格画像
    try:
        l2_text = "\n".join(f"[{k}] {v}" for k, v in out["L2"].items()) or listing
        raw = llm_chat(l2_text, LAYER_PROMPTS["L3"])
        data = _parse(raw)
        out["L3"] = [str(x) for x in data.get("traits", [])][:8]
    except Exception:
        pass
    return out


def _parse(text: str) -> dict:
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return {}
