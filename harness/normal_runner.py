"""正常时间线续跑：补缺的日子（不带·补标签）+ max 档强化任务。

用法：python -X utf8 harness/normal_runner.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.profile import get_profile
from harness.tasks import normal_day, self_chat, weekly_reflection


def main() -> None:
    prof = get_profile("max")
    from life import LifeSim
    from llm import LLMClient
    sim = LifeSim(42)
    llm = LLMClient()
    store = sim.store()
    report = {"profile": "normal-max", "started": datetime.now().isoformat(timespec="seconds"), "tasks": {}}

    def record(task, result, t0):
        report["tasks"][task] = {"result": result, "seconds": round(time.time() - t0, 1)}
        print(f"  [{task}] {result} ({report['tasks'][task]['seconds']}s)", flush=True)

    days = [date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)]
    t0 = time.time()
    done = 0
    for i, d in enumerate(days):
        n = normal_day(sim, d, prof)
        done += n
        print(f"  day {i+1}/3 {d}: +{n} 事件", flush=True)
    record("normal_day", f"{len(days)} 天、{done} 事件", t0)

    t0 = time.time()
    from harness.tasks import dream_burst
    done = dream_burst(sim, llm.chat, prof.dreams_per_night)
    record("dream_burst", f"{done}/{prof.dreams_per_night}", t0)

    t0 = time.time()
    done = self_chat(sim, llm, prof.self_chat_rounds)
    record("self_chat", f"{done}/{prof.self_chat_rounds}", t0)

    t0 = time.time()
    summary = weekly_reflection(sim, llm.chat)
    if summary:
        store.add("thought", f"【周度观察】{summary[:250]}", importance=8.0, key=2)
    record("weekly_reflection", f"{len(summary)} 字" if summary else "空", t0)

    report["ended"] = datetime.now().isoformat(timespec="seconds")
    out = Path("logs") / f"harness_normal_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"=== 正常时间线续跑完成，报告 {out} ===", flush=True)


if __name__ == "__main__":
    main()
