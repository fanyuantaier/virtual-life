"""集成入口：把物理层/导演/记忆/主角/调度接成完整一天。

用法：
    python main.py                # 跑今天（实时模式）
    python main.py --resume       # 断点续跑
    python main.py --date 2026-11-01
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

from contracts import Foreshadow, MemoryHit  # noqa: E402

# ---------- 主角模型客户端（复用 llm.py 的 OpenAI 兼容封装） ----------

from llm import LLMClient as _OAClient  # noqa: E402


class ProtagonistAdapter:
    """适配 runner.ProtagonistProtocol：react(events, memory_hits, persona_text)。"""

    def __init__(self, client: _OAClient, temperature: float | None = None):
        import protagonist
        self._p = protagonist
        self._client = client
        self.temperature = temperature
        self._sim_date = None    # 由 build_ctx 在运行时设置

    def react(self, dayplan_events, memory_hits, persona_text, slot_hint: str = "morning"):
        events = [Event(**e) if isinstance(e, dict) else e for e in dayplan_events]
        hits = [MemoryHit(**h) if isinstance(h, dict) else h for h in memory_hits]
        return self._p.react(self._client, persona_text, events, hits,
                             sim_date=getattr(self, "_sim_date", None),
                             slot_hint=slot_hint)


# ---------- 记忆适配（MemoryStore → runner.MemoryProtocol） ----------

class MemoryAdapter:
    def __init__(self, store, persona, llm_chat):
        self.store = store
        self.persona = persona
        self._llm_chat = llm_chat

    def retrieve(self, query: str, k: int = 5):
        nodes = self.store.retrieve(query, top_k=k)
        return [MemoryHit(
            when=n["when"], text=n["text"], kind=n["kind"],
            importance=n["importance"]) for n, _ in nodes]

    def reflect(self, entries) -> str:
        """夜间反思：入库 thought + 追加人格文件，返回摘要文本。"""
        thoughts = self.store.reflect(self._llm_chat)
        if thoughts:
            self.persona.update([t["text"] for t in thoughts])
        return "；".join(t["text"] for t in thoughts) or "（今天没什么特别的）"

    def add_event(self, kind: str, text: str, when=None, importance=3.0):
        return self.store.add(kind, text, when=when, importance=importance)


# ---------- 导演适配（Director → runner.DirectorProtocol） ----------

class DirectorAdapter:
    """runner 调 make_day_plan(d, {reality, yesterday})；这里组装导演真实输入。"""

    def __init__(self, director, physics, state_holder, memory: MemoryAdapter,
                 banned_window_days: int = 14):
        self.d = director
        self.physics = physics
        self.state_holder = state_holder        # 引用共享的 ProtagonistState
        self.memory = memory
        self.banned_window_days = banned_window_days
        self._foreshadows: list = []            # 从事件里沉淀，见 _harvest

    def make_day_plan(self, d: date, context: dict):
        reality = context.get("reality") or {}
        yesterday = context.get("yesterday")
        skeleton = self.physics.build_skeleton(d)
        chronicle = self._chronicle()
        self._harvest()
        hooks = self._hooks(reality)
        # 到期伏笔的紧迫提示：给导演"戏剧时机已到"的显式信号
        due = self.physics.due_foreshadows(self._foreshadows, d)
        if due:
            hooks += " 【伏笔到期提示，优先考虑让它们成熟】" + "；".join(
                f"{f.summary}（已挂{(d - f.opened_on).days}天，紧迫度{f.urgency}）" for f in due[:5])
        # NPC 离屏演化：让 NPC 主动事件进入当天输入，导演必须消化
        try:
            from world.npc_sim import NpcSim
            if not hasattr(self.state_holder, "npc_sim"):
                self.state_holder.npc_sim = NpcSim(self.state_holder.npc_map)
            inits = self.state_holder.npc_sim.advance(d)
            for it in inits:
                hooks += f" 【NPC主动事件，必须编进今天】{it['text']}"
            if inits:
                for it in inits:   # 主动事件本身也进记忆，可追溯
                    self.memory.add_event("event", f"[离屏] {it['text']}",
                                          when=datetime.combine(d, datetime.min.time()),
                                          importance=4.0)
        except Exception:
            pass
        banned = self._banned_elements()
        try:
            plan = self.d.plan_day(
                d, skeleton, self.state_holder.state, chronicle,
                self._foreshadows, self.state_holder.npcs, banned, reality_hooks=hooks)
        except RuntimeError as exc:
            # 导演三轮失败（网关抽风/限流）→ 规则化兜底日，世界照常转动
            import logging
            logging.getLogger("main").warning("导演失败，启用兜底日: %s", str(exc)[:120])
            from world.fallback import fallback_day
            recent = [n["text"] for n in self.memory.store.recent(days=1.0)]
            plan = fallback_day(d, self.state_holder.state,
                                weather=reality.get("weather"), last_events=recent)
        self._record(plan, d)
        return plan

    # -- 输入组装 --

    def _chronicle(self) -> str:
        nodes = self.memory.store.recent(days=30.0)
        return "\n".join(f"[{n['when']:%m-%d}] {n['text']}" for n in nodes[-40:]) or "（刚开始生活，没有历史）"

    def _hooks(self, reality: dict) -> str:
        parts = []
        w = reality.get("weather")
        if w:
            parts.append(f"真实天气：{w.get('desc')}，{w.get('temp_c')}°C" + ("，在下雨" if w.get("is_rain") else ""))
        headlines = reality.get("headlines") or []
        if headlines:
            parts.append("今天的新闻：" + "；".join(headlines[:3]))
        return " ".join(parts)

    def _banned_elements(self) -> list[str]:
        nodes = self.memory.store.recent(days=float(self.banned_window_days))
        banned = set()
        for n in nodes:
            for m in re.finditer(r"[\u4e00-\u9fff]{2,4}", n["text"]):
                banned.add(m.group(0))
        return sorted(banned)[:60]          # 上限防爆 prompt

    def _harvest(self) -> None:
        """从记忆里的伏笔标记沉淀未兑现伏笔（导演兑现后从表中移除）。"""
        known = {f.id for f in self._foreshadows}
        for n in self.memory.store.recent(days=30.0):
            # [FS:id summary] 形式（_record 写入）；summary 可能含空格
            m = re.search(r"\[FS:(\S+) (.+?)\]", n["text"])
            if m and m.group(1) not in known:
                age = max(0, (datetime.now().date() - n["when"].date()).days)
                self._foreshadows.append(Foreshadow(
                    id=m.group(1), summary=m.group(2), opened_on=n["when"].date(),
                    urgency=min(5, 1 + age // 3)))

    def _record(self, plan, d: date) -> None:
        """事件入库（主角记忆）+ 伏笔登记/兑现结算。"""
        for ev in plan.events:
            text = f"在{ev.location}，{ev.content}"
            if ev.foreshadow_tags:
                for tag in ev.foreshadow_tags:
                    text += f" [FS:{tag} {ev.content[:30]}]"
            self.memory.add_event("event", text, when=datetime.combine(d, datetime.min.time()),
                                  importance=min(10.0, 2.0 + ev.intensity))
            # 伏笔结算：事件带 tag = 导演兑现了它，从活跃表移除；
            # 未带 tag 的 decision_point/major 事件 = 可能埋新伏笔，登记为待兑现
            for tag in ev.foreshadow_tags:
                self._foreshadows = [f for f in self._foreshadows if f.id != tag]
            if not ev.foreshadow_tags and ev.kind in ("major", "incidental") and ev.decision_point:
                fid = f"fs-{d.isoformat()}-{abs(hash(ev.content)) % 10000}"
                if fid not in {f.id for f in self._foreshadows}:
                    self._foreshadows.append(Foreshadow(
                        id=fid, summary=ev.content[:60], opened_on=d,
                        urgency=min(5, max(1, ev.intensity // 2))))
            for actor in ev.actors:
                if actor in self.state_holder.npc_map:
                    outcome = self.physics.derive_outcome(ev, today=d)
                    self.physics.apply_outcome(self.state_holder.state,
                                               self.state_holder.npc_map, ev, outcome, today=d)


# ---------- 主角状态容器 ----------

class StateHolder:
    def __init__(self):
        from contracts import NpcState, ProtagonistState
        self.state = ProtagonistState(energy=70, mood=10, money=3000, location="家")
        self.npc_map = {
            "老周": NpcState(name="老周", relationship=5),
            "小李": NpcState(name="小李", relationship=20),
            "阿蔓": NpcState(name="阿蔓", relationship=30),
            "王阿姨": NpcState(name="王阿姨", relationship=15),
            "赵一鸣": NpcState(name="赵一鸣", relationship=40),
            "母亲": NpcState(name="母亲", relationship=60),
        }
    @property
    def npcs(self):
        return list(self.npc_map.values())


# ---------- 组装 ----------

def build_ctx(resume: bool = False):
    from memory.persona import Persona
    from memory.store import MemoryStore
    from scheduler import runner
    from world import director as director_mod
    from world import physics

    paths = runner.default_paths(base=Path(__file__).resolve().parent)
    reality = runner.default_reality(city=config.CITY)

    store = MemoryStore(db_path=paths.db)
    persona = Persona(config.PERSONA_PATH)
    oa = _OAClient(temperature=config.TEMPERATURE_PROTAGONIST)

    state_holder = StateHolder()

    protagonist = ProtagonistAdapter(oa)
    memory = MemoryAdapter(store, persona, oa.chat)
    d_llm = director_mod.LLMClient(model=config._think_model(),
                                   base_url=config.LLM_BASE_URL or _cfg_local("llm_base_url"),
                                   timeout=180.0)  # 网关挂起不回包时 3 分钟必须放弃  # 导演客户端：端点/模型全对齐 config
    director = director_mod.Director(llm=d_llm)
    director_adapter = DirectorAdapter(director, physics, state_holder, memory)

    ctx = SimpleNamespace(
        paths=paths, reality=reality,
        memory=memory, director=director_adapter, protagonist=protagonist,
        persona_text=persona.render(),
        state_holder=state_holder,
    )
    return ctx, runner


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=str, default=None)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    ctx, runner = build_ctx()
    d = date.fromisoformat(args.date) if args.date else date.today()
    ctx.protagonist._sim_date = d    # 让日记文件名用模拟日期而非真实日期
    runner.run_day(d, ctx, resume=args.resume)
    print(f"完成 {d}，日记见 {config.DIARY_DIR}")


if __name__ == "__main__":
    main()
