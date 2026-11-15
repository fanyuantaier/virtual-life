"""实时调度守护：按现实时钟自动推进虚拟生活。

阶段3：时间线同步。
- USE_REAL_CLOCK=True 时：虚拟日期=真实日期，每个时刻表锚点过后自动跑对应槽位
  （如 18:00 过后跑 evening）；重复启动不重跑（checkpoint day_done/slot_done 挡住）；
- TIME_SCALE>1：加速模式，把现实时钟按倍速折叠成虚拟时刻（2.0 = 现实过 12h = 虚拟一天）；
- 一次性 `python daemon.py` 把当前时点之前的槽位补齐，适合配 Windows 计划任务
  每 30 分钟调一次（守护进程模式后加 --loop 挂着跑）。

用法：
    python daemon.py            # 补齐当前时点的所有待跑槽位后退出
    python daemon.py --loop     # 常驻循环，每 10 分钟检查一次
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

Path("logs").mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("daemon")


def _scaled_now() -> datetime:
    """现实时刻按 TIME_SCALE 折叠成虚拟时刻。

    折叠规则：以当天 00:00 为锚，虚拟已过分钟 = 现实已过分钟 × TIME_SCALE。
    1.0 时虚拟=现实；2.0 时中午 12:00 就走完一整天。
    """
    now = datetime.now()
    if config.TIME_SCALE == 1.0:
        return now
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    passed = (now - midnight).total_seconds() / 60.0 * config.TIME_SCALE
    return midnight + timedelta(minutes=passed)


def tick(once: bool = True) -> None:
    """检查当前虚拟时刻该跑哪些槽位，逐个补齐。"""
    from scheduler import runner
    import main as app

    vnow = _scaled_now()
    d = vnow.date()
    ctx, runner_mod = app.build_ctx()
    ctx.protagonist._sim_date = d

    cp = runner.load_checkpoint(ctx)
    if cp and cp.get("status") == "day_done" and cp.get("date") == d.isoformat():
        return                      # 今天已经过完

    from world.timetable import current_slot
    label, cur_slot = current_slot(vnow, vnow.replace(hour=0, minute=0, second=0, microsecond=0))
    # 找到 cur_slot 在槽序里的位置：从断点槽位（或第一个槽）跑到当前槽为止
    slots = list(config.SLOTS)
    start_idx = 0
    if cp and cp.get("date") == d.isoformat() and cp.get("next_slot"):
        start_idx = slots.index(cp["next_slot"])
    end_idx = slots.index(cur_slot)
    if start_idx > end_idx:
        return                      # 当前槽已跑过
    for slot in slots[start_idx:end_idx + 1]:
        log.info("daemon: %s 推进 %s（虚拟时刻 %s）", d, slot, label)
        # 单槽推进：复用 runner 的断点+DayPlan 复用逻辑
        runner.run_day(d, ctx, resume=True)
        break                       # run_day(resume) 自带断点续跑，一次推一段
    _ = once


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="常驻循环模式")
    ap.add_argument("--interval", type=int, default=600, help="循环间隔秒数")
    args = ap.parse_args()
    if not args.loop:
        tick()
        return
    log.info("daemon: 常驻启动（TIME_SCALE=%s, DETAIL=%s）", config.TIME_SCALE, config.DETAIL_LEVEL)
    while True:
        try:
            tick()
        except Exception as exc:
            log.error("daemon: tick 异常: %s", exc)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
