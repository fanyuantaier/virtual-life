"""囡囡成人实时模式：18 岁后按真实时钟逐日过活。

用法：
    python adult.py                # 跑今天剩余时段
    python adult.py --loop         # 常驻：每 10 分钟检查，到点自动跑对应槽位
    python adult.py --date 2026-11-07

记忆库：life_seed42.db（延续 18 年的记忆与遗忘曲线状态）
人格：18 岁成人礼的 L3 画像 + birth.render() 家庭环境
日记：data/diary_life/adult/YYYY-MM-DD.md（四段式+钟点）
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

Path("logs").mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler("logs/adult.log", encoding="utf-8")])
log = logging.getLogger("adult")

SLOTS = ("morning", "afternoon", "evening", "night")
ADULT_DIARY = config.DATA_DIR / "diary_life" / "adult"


def build_ctx(seed: int = 42):
    """组装成人模式的 ctx：复用 runner 的 Protocol 契约。"""
    from types import SimpleNamespace
    from scheduler import runner
    from life import LifeSim
    from world import director as director_mod
    from world.physics import build_skeleton, validate_events, derive_outcome, apply_outcome, due_foreshadows
    from contracts import ProtagonistState, NpcState, Foreshadow, Event

    sim = LifeSim(seed)
    sim.store()               # 先初始化 store（_store 为 None 时 _embed_ok 会炸）
    sim._store._embed_ok = True
    persona_card = sim.birth.render()
    # L3 画像常驻人格：从库里取 persona 层
    persona_traits = [n["text"] for n in sim.store().recent(days=99999)
                      if n.get("kind") == "persona" or "persona" in str(n)]
    persona_text = persona_card + "\n\n她的性格（由经历沉淀）：\n" + "\n".join(
        f"- {t}" for t in persona_traits[:7])

    state = ProtagonistState(energy=75, mood=15, money=2800, location="家")
    npc_map = {
        "妈妈": NpcState(name="妈妈", relationship=60, facts=["教师", "每周日来电话"]),
        "爸爸": NpcState(name="爸爸", relationship=35, facts=["长途司机", "惊蛰带种子"]),
        "外婆": NpcState(name="外婆", relationship=65, facts=["同住", "种瓜藤", "腰痛过"]),
    }

    from world.world_sim import WorldSim
    from world.needs import Needs, init_from_birth, EVENT_EFFECTS
    world_sim = WorldSim(seed=seed)
    needs = init_from_birth(sim.birth.temperament)

    class AdultDirector:
        def __init__(self):
            self.llm = director_mod.LLMClient(model=config._think_model(),
                                              base_url=config.LLM_BASE_URL or _cfg_local("llm_base_url"),
                                              timeout=480.0)
            from world import physics
            self.physics = physics

        def make_day_plan(self, d: date, context: dict):
            reality = context.get("reality") or {}
            skeleton = build_skeleton(d)
            # 成人日 prompt：L3 画像+家庭+最近记忆
            recent = sim.store().recent(days=30.0)
            chronicle = "\n".join(f"[{n['when']:%m-%d}] {n['text']}" for n in recent[-30:]) or "（新篇章）"
            from world.timetable import format_timetable
            hooks = ""
            w = reality.get("weather")
            if w:
                hooks += f"真实天气：{w.get('desc')} {w.get('temp_c')}°C。"
            headlines = reality.get("headlines") or []
            if headlines:
                hooks += "新闻：" + "；".join(headlines[:2])
            sys_extra = (f"主角囡囡，18 岁，刚高中毕业待业/准备大学。性格：\n"
                         + "\n".join(f"- {t}" for t in persona_traits[:7])
                         + f"\n家庭：{persona_card}\n地点只用：家、公司、小区、便利店、超市、公园、医院、地铁站。")
            # P1 世界自转：世界今日事件（导演可见暗线，用于埋迹象）
            world_events = world_sim.tick(d)
            from world.world_sim import world_block
            hooks += "\n【世界今日】\n" + world_block(world_events, include_hidden=True)
            # P2 需求阈值：状态逼出的事件
            hooks += "\n" + needs.block()
            # 上帝之手：用户干预必须消化（读后清空）
            import json as _jh
            gh = Path(__file__).resolve().parent / "data" / "godhand" / "pending.json"
            if gh.exists():
                try:
                    items = _jh.loads(gh.read_text(encoding="utf-8"))
                    if items:
                        hooks += "\n【上帝之手的干预，今天的计划必须把这些事编进去】"
                        hooks += "\n" + "\n".join(f"- {it['text']}" for it in items)
                        gh.unlink()
                except Exception:
                    pass
            from world.director import PlanContext, Director
            ctx = PlanContext(
                chronicle=chronicle,
                free_slots=list(SLOTS), fixed_slots=[],
                money=state.money, mood=state.mood, energy=state.energy,
                location=state.location,
                reality_hooks=hooks + sys_extra)
            director = Director(llm=self.llm)
            plan = director.plan_day(
                d, skeleton, state, chronicle, [], list(npc_map.values()),
                [], reality_hooks=hooks)
            return plan

    class AdultProtagonist:
        def __init__(self):
            from llm import LLMClient
            self.client = LLMClient()

        def react(self, events, memory_hits, persona_text, slot_hint: str = "morning"):
            from protagonist import react
            return react(self.client, persona_text, events, memory_hits,
                         sim_date=date.today(), slot_hint=slot_hint)

    class AdultMemory:
        def __init__(self):
            self.store = sim.store()

        def retrieve(self, query: str, k: int = 5):
            nodes = self.store.retrieve(query, top_k=k)
            from contracts import MemoryHit
            return [MemoryHit(when=n["when"], text=n["text"], kind=n["kind"],
                              importance=n["importance"]) for n, _ in nodes]

        def reflect(self, entries) -> str:
            from llm import LLMClient
            c = LLMClient()
            thoughts = self.store.reflect(c.chat)
            return "；".join(t["text"] for t in thoughts) or "（今天没什么特别的）"

        def add_event(self, kind, text, when=None, importance=3.0):
            return self.store.add(kind, text, when=when, importance=importance)

    class Paths:
        db = sim.db_path
        diary_dir = ADULT_DIARY
        checkpoint_file = config.DATA_DIR / "checkpoints" / "adult_state.json"
        backup_dir = config.DATA_DIR / "backups"
        inbox_dir = config.DATA_DIR / "inbox"

    class AdultReality:
        def get_weather(self, city): 
            from reality.weather import get_weather
            return get_weather(city)
        def get_headlines(self, n=5):
            from reality.news import get_headlines
            return get_headlines(n)
        def scan_inbox(self, dir_path=None):
            from reality.inbox import scan_inbox
            return scan_inbox(dir_path)

    ctx = SimpleNamespace(
        paths=Paths(), reality=AdultReality(),
        memory=AdultMemory(), director=AdultDirector(),
        protagonist=AdultProtagonist(),
        persona_text=persona_text,
        state_holder=SimpleNamespace(state=state, npc_map=npc_map),
    )
    return ctx, runner


def _llm_chat():
    from llm import LLMClient
    return LLMClient().chat


def _cfg_local(key: str):
    """config_local.json 读取（start.py 引导产物）。"""
    try:
        import json as _j, os as _o
        lp = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), 'config_local.json')
        if _o.path.exists(lp):
            return _j.load(open(lp, encoding='utf-8')).get(key)
    except Exception:
        pass
    return None


def tick() -> None:
    """按时刻表跑今天该跑的槽位（checkpoint 防重跑）。"""
    import json
    from scheduler import runner as runner_mod
    from world.timetable import current_slot

    ctx, runner_mod2 = build_ctx()
    cp_file = ctx.paths.checkpoint_file
    done_slots = set()
    if cp_file.exists():
        try:
            data = json.loads(cp_file.read_text(encoding="utf-8"))
            if data.get("date") == date.today().isoformat():
                done_slots = set(data.get("done_slots", []))
        except (OSError, ValueError):
            pass
    now = datetime.now()
    # 凌晨 0-6 点：睡梦时段，跑一个梦而不是日常槽位
    if now.hour < 6:
        from memory.dream import dream_night
        dream = dream_night(ctx.client.chat if hasattr(ctx, 'client') else _llm_chat(), ctx.memory.store, now)
        if dream:
            log.info("adult: 凌晨梦完成（%d 字）", len(dream))
        else:
            log.info("adult: 凌晨梦失败/跳过")
        return
    label, cur_slot = current_slot(now, now.replace(hour=0, minute=0, second=0, microsecond=0))
    # 已过当前槽的全部待跑槽位（凌晨属昨夜 night，跳过）
    todo = [s for s in SLOTS if s not in done_slots and
            SLOTS.index(s) <= SLOTS.index(cur_slot)]
    if not todo:
        log.info("adult: %s 无待跑槽位（已跑 %s）", date.today(), sorted(done_slots))
        return
    # 一天只调一次导演：当天无 DayPlan 存档则现生成
    plan_file = config.DATA_DIR / "checkpoints" / f"adult_plan_{date.today().isoformat()}.json"
    reality = {"weather": ctx.reality.get_weather(config.CITY),
               "headlines": ctx.reality.get_headlines(3), "inbox": []}
    from contracts import DayPlan
    if plan_file.exists():
        day_plan = DayPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))
        log.info("adult: 复用当日计划（%d 事件）", len(day_plan.events))
    else:
        try:
            day_plan = ctx.director.make_day_plan(date.today(), {"reality": reality})
        except RuntimeError as exc:
            log.warning("adult: 导演失败（%s），今晚到此为止，明早 tick 重试", str(exc)[:80])
            return
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(day_plan.model_dump_json(), encoding="utf-8")
        log.info("adult: 生成当日计划（%d 事件）", len(day_plan.events))
    for slot in todo:
        seg = [e for e in day_plan.events if e.slot == slot]
        runner_mod2.run_slot(date.today(), slot, seg, ctx, reality, None)
        done_slots.add(slot)
        cp_file.parent.mkdir(parents=True, exist_ok=True)
        cp_file.write_text(json.dumps({
            "date": date.today().isoformat(), "done_slots": sorted(done_slots),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("adult: %s 完成（日记 %s）", slot, "有" if seg else "空段占位")
    # 夜槽跑完 → 夜间反思 + 备份
    if "night" in done_slots and len(done_slots) == 4:
        entries = []
        try:
            from scheduler.runner import _load_entries_from_md, _night_reflection
            _night_reflection(ctx, date.today())
            log.info("adult: 夜间反思完成")
        except Exception as exc:
            log.warning("adult: 夜间反思失败 %s", exc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="常驻模式")
    ap.add_argument("--interval", type=int, default=600)
    args = ap.parse_args()
    if args.loop:
        log.info("=== 囡囡成人模式常驻启动 ===")
        while True:
            try:
                tick()
            except Exception as exc:
                log.error("tick 异常: %s", exc)
            time.sleep(args.interval)
    else:
        tick()


if __name__ == "__main__":
    main()
