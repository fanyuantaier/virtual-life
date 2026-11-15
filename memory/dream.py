"""梦境与时段感知：囡囡的夜是有梦的。

设计（阶段：细节化训练）：
- 凌晨 00:00-05:59 是"睡眠时段"——她不产生日常事件，而产生梦；
- 梦的素材来自记忆库：高关键性记忆（key2-3）+ 随机抽的低保留记忆
  （快淡忘的记忆最容易变形入梦——这是遗忘曲线的副产品）；
- LLM 把 2-3 条记忆碎片重组成超现实梦境（时间错乱、人物混搭、情绪放大）；
- 梦以 kind='dream' key=1 入库：醒来会忘——几天后检索不到，符合真实；
- 梦日记独立归档 diary_life/dreams/；
- 时段感知注入：chat 时按当前时刻给 system 加"现在几点、她通常在干什么"。

其他时段以此类推：
- 06:00-08:59 晨间：半醒状态，梦的残影+今天的预期
- 12:00-13:59 午间：饭桌思绪
- 17:00-19:00 黄昏：一天里情绪最容易泛起的时段
- 23:00-00:00 入睡前：白天事件的回放
"""
from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import config

# 时段 → 感知描述（chat/成人模式的 system 注入用）
TIME_AWARENESS = [
    (0, 6,   "现在是凌晨，囡囡在睡觉。如果被叫醒，她声音里会有睡意，可能提到刚做的梦。"),
    (6, 9,   "现在是早晨，囡囡刚醒或正在洗漱。她可能提起昨晚的梦，或者今天的打算。"),
    (9, 12,  "现在是上午，囡囡在忙自己的事。"),
    (12, 14, "现在是午饭时间，囡囡可能在吃饭，顺便想下午的事。"),
    (14, 17, "现在是下午，囡囡在忙，精神头一般。"),
    (17, 19, "现在是黄昏，囡囡一天里最容易情绪泛起的时段——晚饭的油烟味、楼下的人声。"),
    (19, 23, "现在是晚上，囡囡在家，可能在刷手机、看书，或者和妈妈说话。"),
    (23, 24, "快到半夜了，囡囡在床上，白天的事在脑子里过电影，快睡着了。"),
]


def time_awareness(now: datetime | None = None) -> str:
    now = now or datetime.now()
    for lo, hi, desc in TIME_AWARENESS:
        if lo <= now.hour < hi:
            return f"[{now:%H:%M}] {desc}"
    return f"[{now:%H:%M}]"


DREAM_SYSTEM = """你在为囡囡写「昨晚的梦」。她刚满 18 岁，苏州人。

给你三块记忆碎片（有的清楚有的模糊）。把它们织成一个梦：
- 梦不讲逻辑：时间地点可以错乱，人物可以变形（妈妈变成老师、外婆出现在教室），场景可以跳跃
- 但情绪必须连贯：梦的核心情绪要从碎片里来（怕、暖、急、遗憾）
- 用她的视角写，150-250 字，第一人称，醒来回忆的口吻——细节清楚一半、模糊一半
- 结尾往往被什么打断（闹钟、敲门、尿意），或者就这么淡出

只输出梦的正文，不要解释。"""

DREAM_USER = """记忆碎片：
{fragments}

现在是{now:%m月%d日}凌晨。她昨晚做了个梦——写下来。"""


def gather_fragments(store, rng: random.Random) -> list[dict]:
    """抽梦的素材：2 条高关键 + 1 条随机低保留。"""
    import sqlite3
    con = sqlite3.connect(str(store.db_path))
    key_rows = con.execute(
        "SELECT text, ts FROM nodes WHERE mem_key>=2 AND kind IN ('event','thought') "
        "ORDER BY RANDOM() LIMIT 2").fetchall()
    faint_rows = con.execute(
        "SELECT text, ts FROM nodes WHERE mem_key<=1 AND kind='event' "
        "ORDER BY RANDOM() LIMIT 1").fetchall()
    con.close()
    fragments = []
    for text, ts in key_rows + faint_rows:
        when = datetime.fromtimestamp(ts).strftime("%Y-%m")
        fragments.append(f"[{when}] {text[:80]}")
    return fragments


def dream_night(llm_chat, store, now: datetime | None = None) -> str | None:
    """跑一个梦：抽碎片→LLM 织梦→入库（key=1，会淡出）→落盘。
    返回梦的文本，失败返回 None。"""
    rng = random.Random()
    fragments = gather_fragments(store, rng)
    if not fragments:
        return None
    now = now or datetime.now()
    user = DREAM_USER.format(fragments="\n".join("- " + f for f in fragments), now=now)
    try:
        dream = llm_chat(user, DREAM_SYSTEM)
        if not dream or not dream.strip():
            return None
    except Exception:
        return None
    dream = dream.strip()
    # 入库：梦也是记忆，但 key=1——几天后淡出，"醒来就忘"
    store.add("dream", f"做了一个梦：{dream[:120]}",
              when=now, importance=4.0, key=1)
    # 落盘
    dream_dir = config.DATA_DIR / "diary_life" / "dreams"
    dream_dir.mkdir(parents=True, exist_ok=True)
    with (dream_dir / f"{now.date().isoformat()}.md").open("a", encoding="utf-8") as f:
        f.write(f"# 梦 · {now.date().isoformat()}（凌晨 {now:%H:%M}）\n\n{dream}\n\n")
        f.write("---\n素材碎片：\n" + "\n".join(f"- {f}" for f in fragments) + "\n\n")
    return dream


def demo() -> None:
    """跑一个梦看效果。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from life import LifeSim
    from llm import LLMClient
    sim = LifeSim(42)
    c = LLMClient()
    dream = dream_night(c.chat, sim.store())
    print(dream)


if __name__ == "__main__":
    demo()
