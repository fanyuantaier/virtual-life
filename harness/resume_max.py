"""续跑 deep_day 剩余日期 + max 档后续任务（dream/self_chat/redistill/weekly）。

用法：python -X utf8 harness/resume_max.py
从 logs/deep_day_remaining.txt 读剩余日期，逐日精补后接 max 档其余任务。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.profile import get_profile
from harness.tasks import deep_day, dream_burst, self_chat, monthly_redistill, weekly_reflection


def main() -> None:
    prof = get_profile("max")
    from life import LifeSim
    from llm import LLMClient
    sim = LifeSim(42)
    llm = LLMClient()
    store = sim.store()
    report = {"profile": "max-resume", "started": datetime.now().isoformat(timespec="seconds"), "tasks": {}}

    def record(task, result, t0):
        report["tasks"][task] = {"result": result, "seconds": round(time.time() - t0, 1)}
        print(f"  [{task}] {result} ({report['tasks'][task]['seconds']}s)", flush=True)

    # 1) deep_day 剩余日期
    dates_txt = (Path("logs") / "deep_day_remaining.txt").read_text().strip().splitlines()
    t0 = time.time()
    done = 0
    for i, ds in enumerate(dates_txt):
        d = date.fromisoformat(ds.strip())
        n = deep_day(sim, d, prof)
        done += n
        print(f"    day {i+1}/{len(dates_txt)} {d}: +{n} 事件", flush=True)
    record("deep_day", f"{len(dates_txt)} 天精补、{done} 事件入库", t0)

    # 2) 梦
    t0 = time.time()
    done = dream_burst(sim, llm.chat, prof.dreams_per_night)
    record("dream_burst", f"{done}/{prof.dreams_per_night}", t0)

    # 3) 自演
    t0 = time.time()
    done = self_chat(sim, llm, prof.self_chat_rounds)
    record("self_chat", f"{done}/{prof.self_chat_rounds}", t0)

    # 4) 月度重蒸馏
    t0 = time.time()
    done = monthly_redistill(sim, llm.chat, prof.monthly_jump_extra)
    record("monthly_redistill", f"{done} 个月", t0)

    # 5) 周反思
    t0 = time.time()
    summary = weekly_reflection(sim, llm.chat)
    if summary:
        store.add("thought", f"【周度观察】{summary[:250]}", importance=8.0, key=2)
    record("weekly_reflection", f"{len(summary)} 字" if summary else "空", t0)

    report["ended"] = datetime.now().isoformat(timespec="seconds")
    out = Path("logs") / f"harness_resume_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"=== 续跑完成，报告 {out} ===")


if __name__ == "__main__":
    main()
