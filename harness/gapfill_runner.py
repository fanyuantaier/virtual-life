"""时间轴空洞补全：读 logs/gapfill_days.txt 逐日精补，完成后接重蒸馏+周反思。

启动：0 点由外部触发（Task Scheduler / 手动 python -X utf8 harness/gapfill_runner.py）
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.profile import get_profile
from harness.tasks import deep_day, monthly_redistill, weekly_reflection


def main() -> None:
    prof = get_profile("max")
    from life import LifeSim
    from llm import LLMClient
    sim = LifeSim(42)
    llm = LLMClient()
    store = sim.store()
    report = {"profile": "gapfill", "started": datetime.now().isoformat(timespec="seconds"), "tasks": {}}

    def record(task, result, t0):
        report["tasks"][task] = {"result": result, "seconds": round(time.time() - t0, 1)}
        print(f"  [{task}] {result} ({report['tasks'][task]['seconds']}s)", flush=True)

    days = [date.fromisoformat(s.strip())
            for s in (Path("logs") / "gapfill_days.txt").read_text().strip().splitlines() if s.strip()]
    t0 = time.time()
    done = 0
    for i, d in enumerate(days):
        n = deep_day(sim, d, prof)
        done += n
        print(f"  day {i+1}/{len(days)} {d}: +{n} 事件 ({time.time()-t0:.0f}s)", flush=True)
    record("deep_day", f"{len(days)} 天精补、{done} 事件", t0)

    t0 = time.time()
    n = monthly_redistill(sim, llm.chat, 12)
    record("monthly_redistill", f"{n} 个月", t0)

    t0 = time.time()
    summary = weekly_reflection(sim, llm.chat)
    if summary:
        store.add("thought", f"【周度观察】{summary[:250]}", importance=8.0, key=2)
    record("weekly_reflection", f"{len(summary)} 字" if summary else "空", t0)

    # max 加压：梦境连做 + 对话自演（用户指定最高档）
    t0 = time.time()
    from harness.tasks import dream_burst, self_chat
    done = dream_burst(sim, llm.chat, prof.dreams_per_night)
    record("dream_burst", f"{done}/{prof.dreams_per_night}", t0)
    t0 = time.time()
    done = self_chat(sim, llm, prof.self_chat_rounds)
    record("self_chat", f"{done}/{prof.self_chat_rounds}", t0)

    report["ended"] = datetime.now().isoformat(timespec="seconds")
    out = Path("logs") / f"harness_gapfill_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"=== 空洞补全完成，报告 {out} ===", flush=True)


if __name__ == "__main__":
    main()
