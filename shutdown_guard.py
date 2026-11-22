"""配额烧完自动关机守卫：监控双 burnout 进程 + 配额，<3M 时收尾并关机。

启动：python -X utf8 shutdown_guard.py （独立进程，随烧随看）
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def glm_remaining():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11451/v1/balance", timeout=10) as r:
            return json.load(r)["buckets"][0]["remaining"]
    except Exception:
        return None


def burnout_alive() -> int:
    """数还活着的 burnout 进程。"""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "(Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
        "Where-Object {$_.CommandLine -like '*burnout*'}).Count"],
        capture_output=True, text=True)
    try:
        return int(r.stdout.strip() or 0)
    except ValueError:
        return 0


def backup_db() -> str:
    import sqlite3
    src = Path("data/life_seed42.db")
    con = sqlite3.connect(str(src))
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    bdir = Path("data/backups")
    bdir.mkdir(exist_ok=True)
    dst = bdir / f"life_seed42_pre_shutdown_{datetime.now():%Y%m%d_%H%M}.db"
    shutil.copy(src, dst)
    return str(dst)


def main() -> None:
    print("=== 关机守卫启动：配额 <3M 且 burnout 进程退出 → 备份 → 关机 ===", flush=True)
    while True:
        rem = glm_remaining()
        alive = burnout_alive()
        now = datetime.now().strftime("%H:%M:%S")
        if rem is not None:
            print(f"[{now}] GLM={rem/1e6:.1f}M burnout_alive={alive}", flush=True)
        # 达成条件：配额耗尽（<3M）且两个任务都已自行退出
        if rem is not None and rem < 3e6 and alive == 0:
            print("=== 配额用尽 + 任务退出 → 收尾 ===", flush=True)
            bak = backup_db()
            print(f"记忆库已备份: {bak}", flush=True)
            # 停掉常驻自动化（避免关机后任务残留报错）
            for tn in ["vl-adult-loop", "vl-densify-am", "vl-densify-pm", "vl-burn-weekday"]:
                subprocess.run(["schtasks", "/Change", "/TN", tn, "/DISABLE"],
                               capture_output=True)
            print("常驻计划任务已暂停（关机后再开机可手动恢复）", flush=True)
            time.sleep(5)
            subprocess.run(["shutdown", "/s", "/t", "60"], capture_output=True)
            print("=== 60 秒后关机 ===", flush=True)
            return
        time.sleep(120)


if __name__ == "__main__":
    main()
