"""训练任务定义：harness 可跑的"加压训练"项目。

每个任务 = 一类 token 密集型生成，产出都入记忆库/日记/编年史：
- deep_day(days)      逐日精细补写历史日子（把月度跳跃的粗粒度换成 full 模式）
- dream_burst(n)      一晚连做 n 个梦（不同记忆碎片组合）
- self_chat(n)        对话自演：囡囡和自己记忆里的 NPC 群像对话 n 轮（社交记忆加密）
- monthly_redistill(m) 重蒸馏历史 m 个月：给旧月份补 L1/L2 分层（当年只跑了粗粒度）
- weekly_reflection   周度深度反思（比日常反思更深：跨 7 天找模式）
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import config


def deep_day(sim, d: date, profile) -> int:
    """单日精细补写：完整导演流程（逐日模式），事件密度按档位。"""
    import life as life_mod
    from world.physics import build_skeleton
    from world import director as director_mod
    from contracts import ProtagonistState, NpcState
    from world.fallback import fallback_day
    store = sim.store()
    state = ProtagonistState(energy=75, mood=10, money=2800, location="家")
    npc_map = {"妈妈": NpcState(name="妈妈", relationship=60),
               "爸爸": NpcState(name="爸爸", relationship=35),
               "外婆": NpcState(name="外婆", relationship=65)}
    skeleton = build_skeleton(d)
    recent = store.recent(days=30.0)
    chronicle = "\n".join(f"[{n['when']:%m-%d}] {n['text']}" for n in recent[-30:])
    try:
        llm = director_mod.LLMClient(model=config._think_model(),
                                     base_url=config.LLM_BASE_URL or life_mod._local_llm_url(),
                                     timeout=480.0)
        director = director_mod.Director(llm=llm)
        plan = director.plan_day(d, skeleton, state, chronicle,
                                 [], list(npc_map.values()), [], reality_hooks="")
        count = 0
        for ev in plan.events:
            from memory.forgetting import is_key_memory
            key = is_key_memory(ev.content, ev.intensity, ev.actors,
                                ev.decision_point, {"妈妈", "爸爸", "外婆"})
            store.add("event", f"({(d - sim.birth_date).days / 365.25:.1f}岁·补) {ev.content}",
                      when=datetime(d.year, d.month, d.day, 12, 0),
                      importance=min(10.0, 2.0 + ev.intensity), key=key)
            count += 1
        return count
    except Exception:
        plan = fallback_day(d, state, last_events=[n["text"] for n in recent[:1]])
        return len(plan.events)


def dream_burst(sim, llm_chat, n: int) -> int:
    """一晚 n 个梦：不同碎片组合。"""
    from memory.dream import dream_night
    done = 0
    for i in range(n):
        if dream_night(llm_chat, sim.store()):
            done += 1
    return done


def self_chat(sim, llm_client, n: int) -> int:
    """对话自演：囡囡与记忆中 NPC 群像的假想对话 n 轮（社交记忆加密）。
    每轮 = 随机抽一个 NPC + 随机话题（从最近记忆），囡囡以她的口吻应答，
    应答入 chat 记忆。"""
    import random
    from datetime import datetime
    store = sim.store()
    npcs = ["妈妈", "爸爸", "外婆", "小李", "阿蔓", "老周"]
    topics_pool = [n["text"] for n in store.recent(days=14.0)] or ["最近的生活"]
    done = 0
    for i in range(n):
        npc = random.choice(npcs)
        topic = random.choice(topics_pool)[:60]
        prompt = (f"你正在心里和{npc}对话（想象中的，或电话里的）。刚才你想起：{topic}\n"
                  f"写你们这段对话里你说的部分（2-4 句，你的口吻）。")
        try:
            reply = llm_client.chat(prompt, "你是囡囡。口语化，句子短。")
            if reply and reply.strip():
                store.add("chat", f"和{npc}（心里/电话）说：{reply.strip()[:80]}",
                          when=datetime.now(), importance=4.0, key=1)
                done += 1
        except Exception:
            continue
    return done


def monthly_redistill(sim, llm_chat, months: int) -> int:
    """历史月度重蒸馏：给过去 months 个月各补一次 L1/L2 蒸馏。"""
    from memory.distill import distill
    done = 0
    today = date.today()
    for m in range(months):
        end = today - timedelta(days=30 * m)
        start = end - timedelta(days=30)
        lo = datetime(start.year, start.month, start.day).timestamp()
        hi = datetime(end.year, end.month, end.day).timestamp()
        import sqlite3
        con = sqlite3.connect(str(sim.db_path))
        rows = [r[0] for r in con.execute(
            "SELECT text FROM nodes WHERE ts BETWEEN ? AND ? AND kind='event' LIMIT 40",
            (lo, hi)).fetchall()]
        con.close()
        if not rows:
            continue
        layers = distill(llm_chat, (today - start).days / 365.25, rows)
        for f in layers["L1"]:
            sim.store().add("fact", f, importance=6.0, key=2)
        for domain, desc in layers["L2"].items():
            sim.store().add("scene", f"[补:{domain}] {desc}", importance=7.0, key=3)
        done += 1
    return done


def weekly_reflection(sim, llm_chat) -> str:
    """周度深度反思：跨 7 天找模式（比日常反思深）。"""
    nodes = sim.store().recent(days=7.0)
    if not nodes:
        return ""
    listing = "\n".join(f"- {n['text']}" for n in nodes[:50])
    return llm_chat(
        f"下面是囡囡这一周的经历。找「重复出现的模式」（同一情绪/同一件事反复）和「变化」"
        f"（和之前相比她有什么不一样），写 200 字以内的周度观察，第一人称。\n{listing}",
        "你是囡囡自己的声音。")
