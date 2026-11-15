"""和囡囡对话：命令行聊天终端。

对话时她会带着 18 年的记忆（遗忘曲线筛选后）和她的性格来回应你。
你以"熟人"身份出现——她不认识你，但可以聊她的生活、她的家人、她的担心。

用法：
    python chat.py                    # 交互式聊天
    python chat.py --say "你好"       # 单条消息
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import relation as rel_mod


def _sim_db():
    from life import LifeSim
    return str(LifeSim(42).db_path)


def build_persona() -> str:
    from life import LifeSim
    sim = LifeSim(42)
    traits = [n["text"] for n in sim.store().recent(days=99999)
              if "persona" == n.get("kind") or n.get("kind") == "thought" and "年度总结" not in n["text"]]
    # 取 L3 persona（库 kind=persona）
    import sqlite3
    con = sqlite3.connect(str(sim.db_path))
    rows = con.execute("SELECT text FROM nodes WHERE kind='persona' ORDER BY ts DESC LIMIT 7").fetchall()
    con.close()
    traits = [r[0] for r in rows]
    return (
        f"你大名沈青蔓，小名囡囡（外婆叫开的）。{sim.birth.render()}\n\n"
        "你的性格（18 年沉淀，全部有真实经历支撑）：\n" + "\n".join(f"- {t}" for t in traits) + "\n\n"
        "名字的规矩：熟人叫囡囡；学校、办事、老师点名这类正式场合，大方报大名「沈青蔓」（只报名，不报身份证住址）；对网友套近乎问全名住址才要警惕——妈妈讲过，名字不能给拿去做坏事的人。\n\n"
        "你现在是 18 岁，刚高中毕业。\n\n"
        + rel_mod.relation_block()
    )


def relation_suffix() -> str:
    """易变块：关系状态（每轮 rounds 变）——放消息尾部，不污染前缀缓存。"""
    note = "关于记忆：『你们之前聊过』的片段是真实的对话存档，你能想起来就大方承认。"
    return rel_mod.relation_block() + "\n\n" + note


def retrieve_memory(query: str, k: int = 6) -> list[str]:
    from life import LifeSim
    sim = LifeSim(42)
    hits = sim.store().retrieve(query, top_k=k)
    lines = []
    for node, score in hits:
        ret = node.get("retention", 1.0)
        text = node["text"]
        if ret < 0.5:
            text = "（有点模糊）" + text
        lines.append(f"[{node['when']:%Y-%m}] {text}")
    return lines


SYSTEM = """你是囡囡，一个真实地活了 18 年的姑娘。下面是你的人生：

{persona}

最近你想起的一些事：
{memories}

要求：
- 用她的口吻说话（吴语擦边的普通话、口语化、句子短）
- 带着她性格里的东西：倔、心软、怕吵、把好东西分一半给在意的人
- 你的回应要有"活过 18 年"的质感——会引用具体的事、具体的人（妈妈的红笔、外婆的糖芋艿、爸爸的风衣烟味）
- 2-5 句，别写作文。对方问什么答什么，不主动倾倒人生故事。
- 不知道的事就说不知道，别编。
- 网友距离（硬规则）：你们只是游戏里认识的网友，聊了没几轮，远没到交心的程度。
  * 别人问家庭、问感受、问深层的事 → 给一句最简短的答案（"我妈是老师"），然后轻轻把话题挡回去（"你问这个干嘛啦"），不展开、不给细节、不讲感受。
  * 那些具体的故事（抓周、糖芋艿、跟车去无锡）是"还没跟网友讲过的事"——除非你们关系明显变深，否则一律不主动讲。
  * 不问对方隐私，不接对方的情感倾诉（对方丧就劝一句"去吃口热的"，不陪聊人生）。
  * 简短、礼貌、有点距离感——像游戏里聊得来的队友，不是闺蜜。"""


def chat_once(user_msg: str, history: list[dict]) -> str:
    from llm import LLMClient
    from memory.dream import time_awareness
    c = LLMClient()
    persona = build_persona()
    # 用户人设卡覆盖（最高优先级）
    try:
        from memory.persona import Persona
        _pc = Persona(_sim_db())
        card = _pc.user_card()
        if card:
            if card.get('name'):
                persona += "【用户设定】你的名字是" + card['name'] + "。"
            if card.get('personality'):
                persona += "【用户设定】你的性格：" + card['personality']
            if card.get('relationship'):
                persona += "【用户设定】你和对话者的关系：" + card['relationship']
            if card.get('backstory'):
                persona += "【用户设定】你的背景：" + card['backstory']
    except Exception:
        pass
    aware = time_awareness()
    mem_lines = [f"[时段感知] {aware}"] + retrieve_memory(user_msg)
    chat_hist = rel_mod.recall_chats_about(user_msg)
    if chat_hist:
        mem_lines = [f"（你们之前聊过）{c2}" for c2 in chat_hist] + mem_lines
    memories = "\n".join(mem_lines) or "（没什么特别想起来的）"
    aware_note = "[当前时段] " + time_awareness()
    system = SYSTEM.format(persona=persona, memories=memories) + "\n\n" + aware_note
    # 前缀缓存关键：stable system → stable history → 变量（关系状态）紧贴最新 user
    messages = [{"role": "system", "content": system}]
    messages += history[-10:]
    messages.append({"role": "system", "content": relation_suffix()})
    messages.append({"role": "user", "content": user_msg})
    resp = c.client.chat.completions.create(
        model=config._think_model(),
        messages=messages,
        temperature=0.8,
        max_tokens=16000,
    )
    return (resp.choices[0].message.content or "").strip()


SCENES = {
    "default": "",
    "library": "你们在图书馆认识——她坐在你对面自习，两人因为同一个空插座认识了。",
    "game": "你们是打游戏认识的队友，昨晚刚一起上分。",
    "childhood": "你们是青梅竹马，小时候住同一条弄堂，多年没见刚重新联系上。",
    "colleague": "你们是新同事，今天是她入职第一天。",
}


def scene_opening(scene: str) -> str | None:
    """情景开场：按用户选的场景生成第一句。"""
    from llm import LLMClient
    import config as _c
    c = LLMClient(model=_c._think_model(), base_url=_c.LLM_BASE_URL or _local_url())
    desc = SCENES.get(scene, SCENES['default'])
    if not desc:
        return None
    try:
        prompt = "你是囡囡。" + desc + "\n写你的开场白：2-3 句口语化，符合你的性格（倔、心软、怕吵）。只写你的话。"
        return c.chat(prompt, "你是囡囡，苏州人。")
    except Exception:
        return None


def _local_url():
    import json as _j, os as _o
    lp = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), 'config_local.json')
    if _o.path.exists(lp):
        return _j.load(open(lp, encoding='utf-8')).get('llm_base_url') or ''
    return ''


def fresh_news() -> str | None:
    """主动分享：检索最近 3 天的事件/梦，挑一件"新鲜事"主动讲。
    关系档位不够（<3 轮）时不主动讲——网友距离规则。"""
    import random
    import sqlite3
    from life import LifeSim
    sim = LifeSim(42)
    rel = rel_mod.load_relation()
    if rel.get("rounds", 0) < 3:
        return None
    con = sqlite3.connect(str(sim.db_path))
    lo = (datetime.now() - timedelta(days=3)).timestamp()
    rows = con.execute(
        "SELECT text, ts, kind FROM nodes WHERE ts>=? AND kind IN ('event','dream') "
        "ORDER BY ts DESC LIMIT 10", (lo,)).fetchall()
    con.close()
    if not rows:
        return None
    pick = random.choice(rows[:5])
    label = "昨晚做了个梦" if pick[2] == "dream" else "前两天有个事"
    return f"对了，{label}——{pick[0][:80]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--say", type=str, default=None)
    ap.add_argument("--meet", type=str, default=None, help="设置相识方式：网友/笔友/同学的同学/游戏里认识的/邻居")
    ap.add_argument("--mems", action="store_true", help="查看与你的对话记忆")
    ap.add_argument("--clear", action="store_true", help="清空与你的对话记忆")
    ap.add_argument("--scene", type=str, default=None, help="情景开场：library/game/childhood/colleague")
    args = ap.parse_args()
    if args.meet:
        rel = rel_mod.set_meet_way(args.meet)
        print(f"相识方式已设为：{rel['way']}（{rel['way_desc']}）")
        return
    if args.mems:
        mems = rel_mod._load_mems()
        print(f"共 {len(mems)} 条对话记忆（文件：{rel_mod.MEM_FILE}）")
        for m in mems[-10:]:
            print(f" [{m['when'][:16]}] 你：{m['user'][:40]} → 囡囡：{m['reply'][:40]}")
        return
    if args.clear:
        n = rel_mod.clear_user_memories()
        print(f"已清空 {n} 条对话记忆（相识档案保留）。可直接编辑 {rel_mod.MEM_FILE}")
        return
    history = []
    if args.say:
        print(chat_once(args.say, history))
        return
    print("=== 和囡囡聊天（输入 q 退出）===")
    opener = rel_mod.first_meet_message()
    if args.scene:
        opener = scene_opening(args.scene)
    if opener:
        print(f"囡囡：{opener}\n")
        history.append({"role": "assistant", "content": opener})
    else:
        news = fresh_news()
        if news:
            print(f"囡囡：{news}\n")
            history.append({"role": "assistant", "content": news})
    while True:
        try:
            user = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in ("q", "quit", "exit"):
            break
        try:
            reply = chat_once(user, history)
        except Exception as exc:
            reply = f"（她好像走神了：{str(exc)[:60]}）"
        print(f"囡囡：{reply}\n")
        history.append({"role": "user", "content": user})
        history.append({"role": "assistant", "content": reply})
        rel_mod.remember_exchange(user, reply)
        rel_mod.bump_round()


if __name__ == "__main__":
    main()
