"""按配额策略控烧：工作日（周一~周四）烧到剩余 <200M 以下不再烧；周五~周日不控烧也不加压。

策略（用户 2026-11-19 定）：
- 周一二三四：每天烧 200M/天 —— 启动时记录起点余额，跑到 (起点-200M) 即停
- 周五六日：不跑控烧任务（常规自动化照旧，自然消耗 10-15M/天）
- 每日 00:05 由计划任务触发，主力任务 = monthly_redistill（纯 GLM，产出 L1/L2 有价值）

用法：python -X utf8 burn_weekday.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TARGET_PER_DAY = 200e6        # 工作日每天烧 200M


def glm_remaining() -> float | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11451/v1/balance", timeout=10) as r:
            d = json.load(r)
        return d["buckets"][0]["remaining"]
    except Exception:
        return None


def main() -> None:
    weekday = datetime.now().weekday()   # 0=周一 ... 4=周五 5=周六 6=周日
    if weekday >= 4:
        print(f"=== 今天{['周一','周二','周三','周四','周五','周六','周日'][weekday]}，周末不控烧，退出 ===")
        return
    rem = glm_remaining()
    if rem is None:
        print("=== 配额探测失败，退出 ===")
        return
    stop_at = rem - TARGET_PER_DAY
    if stop_at < 50e6:
        stop_at = 50e6   # 安全底线：剩余不低于 50M
    print(f"=== 工作日控烧启动：起点 {rem/1e6:.1f}M → 烧到 {stop_at/1e6:.1f}M（~200M）===")
    from life import LifeSim
    from llm import LLMClient
    from harness.tasks import monthly_redistill, dream_burst, self_chat, weekly_reflection
    sim = LifeSim(42)
    llm = LLMClient()
    rounds = 0
    log = []
    while True:
        rem = glm_remaining()
        if rem is None:
            print("配额探测失败，10 分钟后重试", flush=True)
            time.sleep(600)
            continue
        if rem <= stop_at:
            print(f"=== 达标：剩余 {rem/1e6:.1f}M ≤ {stop_at/1e6:.1f}M，停 ===", flush=True)
            break
        rounds += 1
        t0 = time.time()
        n = monthly_redistill(sim, llm.chat, 3)
        cost = 0
        rem2 = glm_remaining()
        if rem2:
            cost = rem - rem2
        log.append({"round": rounds, "months": n, "burned_M": round(cost/1e6, 1)})
        print(f"  round {rounds}: 重蒸馏 {n} 个月，烧 {cost/1e6:.1f}M，剩 {rem2/1e6 if rem2 else '?'}M", flush=True)
        time.sleep(30)
    out = Path("logs") / f"burn_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps({"rounds": rounds, "log": log}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"=== 报告 {out} ===")


if __name__ == "__main__":
    main()
