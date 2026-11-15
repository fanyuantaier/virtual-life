"""训练执行器：按档位跑一批加压任务。

用法：
    python -m harness.runner --profile burst            # 加密一夜
    python -m harness.runner --profile max --days 7     # 灌满：含 7 天历史精补
    python -m harness.runner --profile normal           # 日常维持

统一记账：每个任务产出计数 + 耗时 + 异常，结束时打印训练报告。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from harness.profile import get_profile


def run(profile_name: str, backfill_days: int = 0) -> dict:
    prof = get_profile(profile_name)
    from life import LifeSim
    from llm import LLMClient
    sim = LifeSim(42)
    llm = LLMClient()
    store = sim.store()

    report = {"profile": prof.name, "started": datetime.now().isoformat(timespec="seconds"),
              "tasks": {}}

    def record(task: str, result, t0: float):
        report["tasks"][task] = {"result": result,
                                 "seconds": round(time.time() - t0, 1)}
        print(f"  [{task}] {result} ({report['tasks'][task]['seconds']}s)")

    # 1) 历史日子精补（backfill_days>0 时）
    if backfill_days > 0:
        t0 = time.time()
        from harness.tasks import deep_day
        done = 0
        base = date.today() - timedelta(days=30 * 18)   # 从出生年起补
        # 补"最缺"的日子：挑 diary 文件少的年份
        for i in range(backfill_days):
            d = base + timedelta(days=i * 3)            # 每 3 天取 1 天精补
            done += deep_day(sim, d, prof)
        record("deep_day", f"{backfill_days} 天精补、{done} 事件入库", t0)

    # 2) 梦境连做
    t0 = time.time()
    from harness.tasks import dream_burst
    done = dream_burst(sim, llm.chat, prof.dreams_per_night)
    record("dream_burst", f"{done}/{prof.dreams_per_night} 个梦", t0)

    # 3) 对话自演
    if prof.self_chat_rounds > 0:
        t0 = time.time()
        from harness.tasks import self_chat
        done = self_chat(sim, llm, prof.self_chat_rounds)
        record("self_chat", f"{done}/{prof.self_chat_rounds} 轮", t0)

    # 4) 历史月度重蒸馏
    if prof.monthly_jump_extra > 0:
        t0 = time.time()
        from harness.tasks import monthly_redistill
        done = monthly_redistill(sim, llm.chat, prof.monthly_jump_extra)
        record("monthly_redistill", f"{done} 个月补蒸馏", t0)

    # 5) 反思（按深度）
    t0 = time.time()
    from harness.tasks import weekly_reflection
    summary = weekly_reflection(sim, llm.chat)
    if summary:
        store.add("thought", f"【周度观察】{summary[:250]}", importance=8.0, key=2)
    record("weekly_reflection", f"{len(summary)} 字" if summary else "空", t0)

    report["ended"] = datetime.now().isoformat(timespec="seconds")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["normal", "burst", "max"], default="normal")
    ap.add_argument("--days", type=int, default=0, help="历史日子精补天数（max 档建议 30+）")
    args = ap.parse_args()
    Path("logs").mkdir(exist_ok=True)
    print(f"=== harness 训练启动 profile={args.profile} days={args.days} ===")
    report = run(args.profile, args.days)
    import json
    out = Path("logs") / f"harness_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"=== 训练报告已写 {out} ===")


if __name__ == "__main__":
    main()
