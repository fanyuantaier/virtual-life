"""人生模式入口：从 0 岁开始的完整一生。

阶段4：python life.py --seed 42
- 出生参数规则随机（无人设，只有家庭/环境/先天气质）；
- 年龄阶段驱动：流速/语言/记忆策略随阶段切换；
- 幼年期高速折叠（1 现实小时 = 8-24 模拟天），成年后逐渐过渡到实时；
- 每"一年"做一次深度反思（年度人格审计）。

与 daemon.py 的关系：life 模式跑在独立的记忆库（life_seed{N}.db），
不影响 adult 线的 life.db。达到 18 岁后打印总结并停（成年线由 daemon 接管）。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

Path("logs").mkdir(exist_ok=True)


def _local_llm_url() -> str:
    """config_local.json 的 llm_base_url（start.py 引导产物）。"""
    try:
        import json as _j, os as _o
        lp = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "config_local.json")
        if _o.path.exists(lp):
            return _j.load(open(lp, encoding="utf-8")).get("llm_base_url") or ""
    except Exception:
        pass
    return ""

try:
    from world import json_repair as _json_repair
except ImportError:
    import json_repair as _json_repair
from world.life import (BirthParams, generate_birth, stage_for_age,
                        hours_for_stage, style_note, stage_directive)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler("logs/life.log", encoding="utf-8")])
log = logging.getLogger("life")


class LifeSim:
    def __init__(self, seed: int):
        self.seed = seed
        self.birth = generate_birth(seed)
        self.birth_date = self.birth.birth_date
        self.db_path = config.DATA_DIR / f"life_seed{seed}.db"
        self._store = None
        self._persona = None
        self._llm = None

    def age_days_at(self, sim_date: date) -> int:
        return (sim_date - self.birth_date).days

    @property
    def age_days(self) -> int:
        return (date.today() - self.birth_date).days

    @property
    def age_years(self) -> float:
        return self.age_days / 365.25

    def store(self):
        if self._store is None:
            from memory.store import MemoryStore
            self._store = MemoryStore(db_path=self.db_path)
        return self._store

    def persona_text(self) -> str:
        return self.birth.render()

    def sim_days_per_tick(self, stage: str) -> int:
        """每次 tick（1 现实小时）推进多少模拟天。"""
        h = hours_for_stage(stage)
        return max(1, round(h)) if h else 0

    def run_day(self, sim_date: date, age_years: float, stage: str) -> bool:
        """age_years 按 sim_date 计算的年龄（由 run() 传入）"""
        """跑一天。返回是否成功（导演失败且无兜底时 False）。"""
        from world import director as director_mod
        from world.physics import build_skeleton
        from world.fallback import fallback_day
        from contracts import ProtagonistState, NpcState

        state = ProtagonistState(energy=80, mood=10, money=0, location="家")
        npc_map = {
            "爸爸": NpcState(name="爸爸", relationship=50),
            "妈妈": NpcState(name="妈妈", relationship=60),
        }
        if "祖父母" in self.birth.family_type:
            npc_map["奶奶"] = NpcState(name="奶奶", relationship=55)
        if "二胎" in self.birth.family_type:
            npc_map["哥哥或姐姐"] = NpcState(name="哥哥或姐姐", relationship=40)

        skeleton = build_skeleton(sim_date)
        directive = stage_directive(stage, age_years)
        store = self.store()
        recent = store.recent(days=14.0)
        chronicle = "\n".join(f"[{n['when']:%m-%d}] {n['text']}" for n in recent[-20:]) or "（刚出生，世界一片新）"

        try:
            d_llm = director_mod.LLMClient(model=config._think_model(),
                                           base_url=config.LLM_BASE_URL or _local_llm_url(), timeout=480.0)
            director = director_mod.Director(llm=d_llm)
            plan = director.plan_day(
                sim_date, skeleton, state, directive + "\n" + chronicle,
                [], list(npc_map.values()), [], reality_hooks=self.birth.render())
        except RuntimeError as exc:
            log.warning("导演失败用兜底: %s", str(exc)[:100])
            plan = fallback_day(sim_date, state, last_events=[n["text"] for n in recent[:1]])

        # 事件入库：幼年期事件天然高关键性（一切都是第一次）
        for ev in plan.events:
            from memory.forgetting import is_key_memory
            key = is_key_memory(ev.content, ev.intensity, ev.actors,
                                ev.decision_point,
                                attachment_names=set(npc_map))
            if stage in ("infant", "toddler"):
                key = max(key, 3)   # 幼年一切皆初次：全部按关键记忆存
            store.add("event", f"({age_years:.1f}岁) 在{ev.location}，{ev.content}",
                      when=datetime.combine(sim_date, datetime.min.time().replace()),
                      importance=min(10.0, 2.0 + ev.intensity), key=key)
        # 日记落盘（按年归档）
        diary_dir = config.DATA_DIR / "diary_life"
        diary_dir.mkdir(parents=True, exist_ok=True)
        year_dir = diary_dir / f"year_{int(age_years)}"
        year_dir.mkdir(exist_ok=True)
        with (year_dir / f"{sim_date.isoformat()}.md").open("a", encoding="utf-8") as f:
            f.write(f"# {sim_date}（{age_years:.2f} 岁）\n\n")
            for ev in plan.events:
                f.write(f"- [{ev.slot}] {ev.content}\n")
            f.write("\n")
        return True

    def annual_reflection(self, age_years: float) -> str:
        """年度人格审计：这一年的记忆蒸馏成自我认知（幼年期由 LLM 代述）。"""
        store = self.store()
        nodes = store.recent(days=365.0)
        if not nodes:
            return ""
        listing = "\n".join(f"- {n['text']}" for n in nodes[:40])
        from llm import LLMClient
        llm = LLMClient()
        stage = stage_for_age(age_years)
        prompt = (
            f"你替一个 {age_years:.1f} 岁的孩子写这一年的『成长记录』。他经历的事：\n"
            f"{listing}\n\n"
            f"要求：以第三人称总结这一年他学会了什么、怕什么、喜欢谁、性格露出什么苗头。"
            f"300 字以内。语言风格：{style_note(stage)}"
        )
        try:
            summary = llm.chat(prompt, "你是成长记录的执笔人，客观而温柔。")
            if not summary or not summary.strip():
                raise RuntimeError("empty summary")
            store.add("thought", f"【{int(age_years)}岁年度总结】{summary[:300]}",
                      importance=9.0, key=3)
            # 分层蒸馏（借鉴 TencentDB-Agent-Memory：L1 事实→L2 场景→L3 人格画像）
            try:
                from memory.distill import distill
                year_texts = [n["text"] for n in nodes[:60]]
                layers = distill(llm.chat, age_years, year_texts)
                for f in layers["L1"]:
                    store.add("fact", f, importance=7.0, key=2)
                for domain, desc in layers["L2"].items():
                    store.add("scene", f"[{domain}] {desc}", importance=8.0, key=3)
                for trait in layers["L3"]:
                    store.add("persona", trait, importance=9.0, key=3)
                log.info("蒸馏完成 L1=%d L2=%d L3=%d",
                         len(layers["L1"]), len(layers["L2"]), len(layers["L3"]))
            except Exception as exc:
                log.warning("分层蒸馏失败（不影响总结）: %s", str(exc)[:80])
            return summary
        except Exception as exc:
            log.warning("年度反思失败（%s），1 分钟后重试一次", exc)
            import time as _t
            _t.sleep(60)
            try:
                summary = llm.chat(prompt, "你是成长记录的执笔人，客观而温柔。")
                if not summary or not summary.strip():
                    return ""
                store.add("thought", f"【{int(age_years)}岁年度总结】{summary[:300]}",
                          importance=9.0, key=3)
                return summary
            except Exception as exc2:
                log.warning("年度反思重试仍失败: %s", exc2)
                return ""

    def run_month_jump(self, month_start: date, age_years: float, stage: str) -> int:
        """月度跳跃：一次 LLM 调用生成这一个月的 1-3 个关键时刻（低细节快进）。
        返回生成的事件数。这是幼年期的主力模式——人格由关键事件塑造，不由日常流水账。"""
        from world import director as director_mod
        from contracts import ProtagonistState
        from memory.forgetting import is_key_memory
        store = self.store()
        state = ProtagonistState(energy=80, mood=10, money=0, location="家")
        month_end = month_start + timedelta(days=30)
        age_lo = (month_start - self.birth_date).days / 365.25
        age_hi = (month_end - self.birth_date).days / 365.25
        recent = store.recent(days=99999)
        chronicle = chr(10).join(f"- {n['text']}" for n in recent[-15:]) or "（刚出生）"
        # 缓存优化：system 前缀跨 216 个月字节级一致（稳定铁律+家庭卡在前），
        # 易变信息（年龄/月份）全部放 user 尾部——LLM 网关前缀缓存可整段命中
        sys_p = (
            "你在为一个孩子的成长时间线写『关键时刻』。一个月发生 3-5 件重要的事——"
            "正是这些事塑造人格；另外再给 2 件『次要事件』（background 类，一句话日常，用于填充生活质感）。输出 JSON 数组，每个事件："
            '{"date": "MM-DD", "content": "发生了什么（2-3句，具体到人和话）", "why_key": "为什么这件事对他的性格有影响（一句）"}'
            f"{chr(10)}家庭环境：{self.birth.render()}{chr(10)}"
            "规则：事件要有因果（从家庭结构里长出来），可以平凡（第一次自己吃饭）也可以重（亲人生病）；"
            "『次要事件』kind 填 background，intensity 1-2；其余 kind 不填；"
            "禁止随机空降的戏剧（不坐飞机不中彩票）；内容必须符合这个年龄能经历的事。"
        )
        user_p = (
            f"当前阶段：{stage}（{age_lo:.1f} 到 {age_hi:.1f} 岁）。语言风格：{style_note(stage)}{chr(10)}"
            f"近期时间线：{chr(10)}{chronicle}{chr(10)}{chr(10)}请给 {month_start.strftime('%Y-%m')} 这个月的关键时刻。"
        )
        try:
            import json as _json
            raw = director_mod.LLMClient(model=config._think_model(),
                                         base_url=config.LLM_BASE_URL or _local_llm_url(),
                                         timeout=480.0).chat(sys_p, user_p, temperature=1.0, max_tokens=16000)
            raw = director_mod.Director._strip_monologue(raw)
            try:
                with open("data/raw_month.log", "a", encoding="utf-8") as _f:
                    _f.write(chr(10) + "===== " + str(month_start) + " =====" + chr(10) + raw[:2000] + chr(10))
            except OSError:
                pass
            data = _json_repair.robust_parse(raw)
            items = data if isinstance(data, list) else data.get("events", data.get("moments", []))
            if items and isinstance(items, dict):
                items = [items]
            n = 0
            for it in items or []:
                if not isinstance(it, dict) or not it.get("content"):
                    continue
                if it.get("kind") == "background":
                    key = 1   # 次要事件：普通记忆，会随遗忘曲线淡出
                    importance = 4.0
                else:
                    key = 3   # 月度关键时刻 = 人格塑造点，一律 key3
                    importance = 8.0
                try:
                    d = datetime.strptime(f"{month_start.year}-{it.get('date','15')}", "%Y-%m-%d")
                except ValueError:
                    d = month_start + timedelta(days=14)
                store.add("event", f"({age_hi:.1f}岁) {it['content']}",
                          when=datetime.combine(d, datetime.min.time()),
                          importance=importance, key=key)
                # 关键事件也落日记（月度档案）
                diary_dir = config.DATA_DIR / "diary_life" / f"year_{int(age_hi)}"
                diary_dir.mkdir(parents=True, exist_ok=True)
                with (diary_dir / f"{d.date().isoformat()}.md").open("a", encoding="utf-8") as f:
                    f.write(f"# {d.date().isoformat()}（{age_hi:.2f} 岁）关键时刻" + chr(10) + chr(10))
                    f.write(f"- {it['content']}" + chr(10))
                    if it.get("why_key"):
                        f.write(f"- *为什么重要：{it['why_key']}*" + chr(10))
                    f.write(chr(10))
                n += 1
            return n
        except Exception as exc:
            log.warning("月度跳跃失败（%s），跳过这月", str(exc)[:100])
            return 0

    def run(self, max_age: int = 18, fast_mode: bool = True) -> None:
        """主循环。
        fast_mode=True（幼年快进）：月度跳跃，每月 1 次 LLM 调用，0-18 岁 ≈ 216 次调用 ≈ 数小时；
        fast_mode=False：逐日完整导演（ adult 线的 run_day，供到达目标年龄后的精细生活）。"""
        log.info("=== 人生模式启动 seed=%d %s ===", self.seed, self.birth.render())
        if not fast_mode:
            self._run_daily(max_age)
            return
        sim_date = self.birth_date
        total_events = 0
        while True:
            age = (sim_date - self.birth_date).days / 365.25
            if age >= max_age:
                log.info("=== 到达 %d 岁，快进结束（共 %d 个关键时刻）=== ", max_age, total_events)
                break
            stage = stage_for_age(age)
            n = self.run_month_jump(sim_date, age, stage)
            total_events += n
            sim_date = sim_date + timedelta(days=30)
            year_now = int(age)
            log.info("快进到 %s（%.2f 岁，%s），关键时刻累计 %d",
                     sim_date, age, stage, total_events)
            # 年度反思：生日过线
            if int((sim_date - self.birth_date).days / 365.25) != year_now and n is not None:
                self.annual_reflection((sim_date - self.birth_date).days / 365.25)
            time.sleep(1.0)

    def _run_daily(self, max_age: int) -> None:
        """逐日精细模式（原逻辑，供 adult 精细生活）。"""
        sim_date = self.birth_date
        while True:
            age = (sim_date - self.birth_date).days / 365.25
            if age >= max_age:
                break
            stage = stage_for_age(age)
            self.run_day(sim_date, age, stage)
            sim_date = sim_date + timedelta(days=1)
            time.sleep(0.5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--daily", action="store_true", help="逐日精细模式（默认月度跳跃快进）")
    ap.add_argument("--max-age", type=int, default=6)
    ap.add_argument("--batch", type=int, default=30, help="[已废弃，月度跳跃模式不再需要]")
    args = ap.parse_args()
    Path("logs").mkdir(exist_ok=True)
    LifeSim(args.seed).run(max_age=args.max_age, fast_mode=not args.daily)


if __name__ == "__main__":
    main()
