"""夜间控烧训练：烧 GLM(11451) 直到剩余 <100M 自动停。

用户要求：明早 09:00 前剩余 <1 亿。当前剩余 ~266M → 今夜烧 ~167M。
主力任务：monthly_redistill（历史重蒸馏，纯 GLM 消耗，产出 L1/L2 有价值）。
每轮 ~15-25M，跑 ~8-10 轮达标即停。
"""
import sys, time, json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import urllib.request


def glm_remaining() -> float | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11451/v1/balance", timeout=10) as r:
            d = json.load(r)
        return d["buckets"][0]["remaining"]
    except Exception:
        return None


def main() -> None:
    target = 100e6   # 剩余低于 1 亿即停
    rounds = 0
    log = []
    print(f"=== 夜间控烧启动（目标：GLM 剩余 < {target/1e6:.0f}M）===")
    while True:
        remaining = glm_remaining()
        if remaining is None:
            print("balance 读取失败，60s 后重试")
            time.sleep(60)
            continue
        if remaining < target:
            print(f"=== 达标：剩余 {remaining/1e6:.1f}M < 100M，共 {rounds} 轮，停 ===")
            break
        rounds += 1
        print(f"--- 第 {rounds} 轮（剩余 {remaining/1e6:.1f}M）---")
        from harness.runner import run
        rep = run("max", backfill_days=0)   # max 档；deep_day 是 deepseek 的活不在其中
        log.append({"round": rounds, "remaining_before": remaining,
                    "tasks": rep["tasks"]})
        time.sleep(5)
    Path("logs/burn_report.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("报告已写 logs/burn_report.json")


if __name__ == "__main__":
    main()
