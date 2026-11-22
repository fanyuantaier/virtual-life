"""配额清空任务 B：deep_day 密集精补历史日子，循环到配额耗尽。

用法：python -X utf8 harness/burnout_b.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.profile import get_profile
from harness.tasks import deep_day


def glm_remaining():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11451/v1/balance", timeout=10) as r:
            return json.load(r)["buckets"][0]["remaining"]
    except Exception:
        return None


def main() -> None:
    prof = get_profile("max")
    from life import LifeSim
    sim = LifeSim(42)
    # 补历史：从 2025-08-24 起（上次补到 08-21），每 2 天取 1 天，一直排到今天
    start = date(2025, 8, 24)
    end = date.today()
    days = []
    d = start
    while d < end:
        days.append(d)
        d += timedelta(days=2)
    print(f"B 任务：{len(days)} 天待精补（{start} → {end}）", flush=True)
    i = 0
    while i < len(days):
        rem = glm_remaining()
        if rem is not None and rem < 3e6:
            print(f"=== 配额 <3M，B 任务收工（补到 {days[i]}）===", flush=True)
            break
        d = days[i]
        try:
            n = deep_day(sim, d, prof)
            print(f"  day {i+1}/{len(days)} {d}: +{n} 事件", flush=True)
        except Exception as exc:
            print(f"  {d} 异常: {str(exc)[:60]}", flush=True)
        i += 1
        time.sleep(5)
    out = Path("logs") / f"burnout_b_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps({"completed": i, "total": len(days)}, ensure_ascii=False), encoding="utf-8")
    print(f"=== B 报告 {out} ===", flush=True)


if __name__ == "__main__":
    main()
