"""用户关系记忆：囡囡与用户的相识、对话史、关系演化。

设计：
- 相识档案 relation.json：怎么认识的（默认网友）、相识日期、称呼；
- 对话史入记忆库（kind=chat, key=2——和用户的对话是重要记忆）；
- 关系状态演化：聊天次数累计，亲密度分级（陌生→认识→熟→朋友→好朋友），
  由对话轮数+情感词粗判，规则驱动不用 LLM；
- 每次聊天开场：retrieve 相似的历史对话片段（她记得你们聊过什么）。

存储：
- data/relation.json —— 相识档案（可手工编辑）
- life_seed42.db nodes 表 kind='chat' —— 对话记忆
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import config

RELATION_FILE = config.DATA_DIR / "relation.json"

# 亲密度分级：按累计对话轮数（网友身份升温要慢——现实里网友两年也就到"熟"）
_INTIMACY_STEPS = [(0, "陌生"), (3, "点头之交"), (15, "聊得来的网友"), (40, "熟"), (80, "朋友"), (150, "好朋友")]

# 相识方式选项
MEET_WAYS = {
    "打王者认识的": "打《王者荣耀》认识的，组过几次队",
    "网友": "在一个网站上认识的，聊得来",
    "笔友": "不知道怎么就通上信了，像老式的笔友",
    "同学的同学": "经人介绍认识的，说是同龄人",
    "游戏里认识的": "打游戏组队认识的，后来加了好友",
    "邻居": "搬到附近的新邻居，打过几次照面",
}


def load_relation() -> dict:
    """读相识档案；没有则按默认（网友）初始化。"""
    if RELATION_FILE.exists():
        try:
            return json.loads(RELATION_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    rel = {
        "way": "打王者认识的",
        "way_desc": MEET_WAYS["打王者认识的"],
        "since": date.today().isoformat(),
        "calls_user": "你",           # 她怎么称呼用户（可改）
        "rounds": 0,
    }
    RELATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    RELATION_FILE.write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    return rel


def save_relation(rel: dict) -> None:
    RELATION_FILE.write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")


def set_meet_way(way: str) -> dict:
    """设置相识方式（首次对话前调用）。"""
    rel = load_relation()
    rel["way"] = way
    rel["way_desc"] = MEET_WAYS.get(way, way)
    save_relation(rel)
    return rel


def intimacy_label(rounds: int) -> str:
    label = _INTIMACY_STEPS[0][1]
    for threshold, name in _INTIMACY_STEPS:
        if rounds >= threshold:
            label = name
    return label


def relation_block() -> str:
    """给系统提示的关系块：她怎么认识你的、聊过几轮、现在什么关系。"""
    rel = load_relation()
    days_known = (date.today() - date.fromisoformat(rel["since"])).days
    label = intimacy_label(rel["rounds"])
    return (
        f"你和一个网友聊过天：你们是{rel['way_desc']}（{rel['since']} 认识，{days_known} 天了）。"
        f"你叫对方「{rel['calls_user']}」。到现在聊了 {rel['rounds']} 轮，"
        f"你觉得你们算「{label}」。"
    )


def bump_round() -> dict:
    """每次对话后调用：轮数 +1，写回。"""
    rel = load_relation()
    rel["rounds"] = rel.get("rounds", 0) + 1
    save_relation(rel)
    return rel


MEM_FILE = config.DATA_DIR / "user_memories.json"


def _load_mems() -> list[dict]:
    """用户对话记忆独立文件：list[{when, user, reply}]。可手工编辑/清空。"""
    if MEM_FILE.exists():
        try:
            return json.loads(MEM_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    return []


def _save_mems(mems: list[dict]) -> None:
    MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEM_FILE.write_text(json.dumps(mems, ensure_ascii=False, indent=1), encoding="utf-8")


def remember_exchange(user_msg: str, reply: str) -> None:
    """把一轮对话追加进独立用户记忆文件（不进遗忘曲线——与用户的记忆她一直记得，
    除非你手动清空）。"""
    mems = _load_mems()
    mems.append({
        "when": datetime.now().isoformat(timespec="seconds"),
        "user": user_msg,
        "reply": reply,
    })
    _save_mems(mems[-500:])   # 上限 500 条防爆文件


def recall_chats_about(query: str, k: int = 3) -> list[str]:
    """检索和用户的历史对话：先关键词匹配最新 100 条，不足补最近几条。"""
    mems = _load_mems()
    recent = mems[-100:]
    scored = []
    q_terms = {query[i:i+2] for i in range(max(0, len(query) - 1))} | {query}
    for i, m in enumerate(recent):
        text = m["user"] + " " + m["reply"]
        overlap = len(q_terms & {text[j:j+2] for j in range(max(0, len(text) - 1))})
        if overlap > 0:
            scored.append((overlap, i, m))
    scored.sort(reverse=True)
    out = [f"{m['user'][:40]} → {m['reply'][:40]}" for _, _, m in scored[:k]]
    if not out:   # 没有相关命中 → 给最近 k 条
        out = [f"{m['user'][:40]} → {m['reply'][:40]}" for m in recent[-k:]]
    return out


def clear_user_memories() -> int:
    """清空用户对话记忆（手动操作）。返回清除条数。"""
    mems = _load_mems()
    _save_mems([])
    return len(mems)


def edit_user_memories() -> Path:
    """返回记忆文件路径（直接编辑 JSON 即可）。"""
    MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MEM_FILE.exists():
        _save_mems([])
    return MEM_FILE


def first_meet_message() -> str | None:
    """如果是第一次聊天，生成她的开场白（相识方式驱动）。"""
    rel = load_relation()
    if rel.get("rounds", 0) > 0:
        return None
    from llm import LLMClient
    c = LLMClient()
    try:
        return c.chat(
            f"你叫囡囡，18 岁，苏州人。你们是{rel['way_desc']}，今天第一次聊天。"
            "写她的开场白：2-3 句，口语化，带点拘谨但友好，符合她的性格（倔、心软、怕吵）。"
            "不要自我介绍太长。",
            "你是囡囡。")
    except Exception:
        return "你好呀……我们是不是在哪儿聊过？算了，重新认识下，我叫囡囡。"
