"""重跑兜底日：6 个导演失败的日子，逐日单独跑，产出入日志。

用法：python -X utf8 harness/rerun_fallback_days.py
"""
from __future__ import annotations

import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.profile import get_profile
from harness.tasks import deep_day


def main() -> None:
    prof = get_profile("max")
    from life import LifeSim
    sim = LifeSim(42)
    days = ["2025-07-10", "2025-07-19", "2025-07-28", "2025-07-31",
            "2025-08-03", "2025-08-09"]
    total = 0
    for ds in days:
        d = date.fromisoformat(ds)
        t0 = time.time()
        n = deep_day(sim, d, prof)
        total += n
        print(f"{ds}: +{n} 事件 ({time.time()-t0:.0f}s)", flush=True)
    print(f"=== 兜底日重跑完成，共 {total} 事件 ===")


if __name__ == "__main__":
    main()
