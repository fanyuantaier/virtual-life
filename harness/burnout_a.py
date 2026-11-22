"""配额清空任务 A：max 全套餐（梦5+自演20+蒸馏12+周反思）循环到配额耗尽。

用法：python -X utf8 harness/burnout_a.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.profile import get_profile
from harness.tasks import dream_burst, self_chat, monthly_redistill, weekly_reflection


def glm_remaining():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11451/v1/balance", timeout=10) as r:
            return json.load(r)["buckets"][0]["remaining"]
    except Exception:
        return None


def main() -> None:
    prof = get_profile("max")
    from life import LifeSim
    from llm import LLMClient
    sim = LifeSim(42)
    llm = LLMClient()
    store = sim.store()
    lap = 0
    while True:
        rem = glm_remaining()
        if rem is not None and rem < 3e6:
            print(f"=== 配额 <3M，A 任务收工（lap {lap}）===", flush=True)
            break
        lap += 1
        print(f"--- A lap {lap}（剩 {rem/1e6 if rem else '?'}M）---", flush=True)
        try:
            d = dream_burst(sim, llm.chat, prof.dreams_per_night)
            print(f"  梦 {d}/5", flush=True)
            s = self_chat(sim, llm, prof.self_chat_rounds)
            print(f"  自演 {s}/20", flush=True)
            m = monthly_redistill(sim, llm.chat, 12)
            print(f"  重蒸馏 {m} 月", flush=True)
            summary = weekly_reflection(sim, llm.chat)
            if summary:
                store.add("thought", f"【周度观察】{summary[:250]}", importance=8.0, key=2)
        except Exception as exc:
            print(f"  lap 异常（继续）: {str(exc)[:80]}", flush=True)
            time.sleep(30)
    out = Path("logs") / f"burnout_a_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps({"laps": lap}, ensure_ascii=False), encoding="utf-8")
    print(f"=== A 报告 {out} ===", flush=True)


if __name__ == "__main__":
    main()
