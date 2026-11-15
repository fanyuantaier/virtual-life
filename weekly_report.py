"""观察者周报：把"看"变成有产出的乐趣。

P4：观察者游戏的核心是"我能看到因果，但我算不出结果"。
周报 = 主角视角 vs 世界真相 的对照呈现：
- 主角知道的（她的日记、她的记忆检索命中）
- 主角不知道的（世界编年史的暗线、传闻的原始版本）
- 因果链标注（哪条暗线在她生活里留下了迹象）

用法：python weekly_report.py [--weeks 1]
产出：data/weekly/YYYY-Www.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config


def _week_range(weeks_back: int = 1) -> tuple[date, date, str]:
    today = date.today()
    end = today - timedelta(days=7 * (weeks_back - 1))
    start = end - timedelta(days=7)
    iso_year, iso_week, _ = end.isocalendar()
    return start, end, f"{iso_year}-W{iso_week:02d}"


def gather(start: date, end: date) -> dict:
    from life import LifeSim
    sim = LifeSim(42)
    con = __import__("sqlite3").connect(str(sim.db_path))
    lo = datetime.combine(start, datetime.min.time()).timestamp()
    hi = datetime.combine(end, datetime.max.time()).timestamp()

    her_events = [r[0] for r in con.execute(
        "SELECT text FROM nodes WHERE kind='event' AND ts BETWEEN ? AND ? ORDER BY ts", (lo, hi))]
    her_diary = []
    d_dir = Path(config.DATA_DIR) / "diary_life"
    cur = start
    while cur <= end:
        for f in d_dir.rglob(f"{cur.isoformat()}.md"):
            her_diary.append(f)
        cur += timedelta(days=1)

    wc = Path(config.DATA_DIR) / "world_chronicle.md"
    world_lines = []
    if wc.exists():
        for l in wc.read_text(encoding="utf-8").splitlines():
            m = l[:11]
            try:
                d = date.fromisoformat(l[1:11])
                if start <= d <= end:
                    world_lines.append(l)
            except ValueError:
                continue
    con.close()
    return {"her_events": her_events, "her_diary": her_diary, "world": world_lines}


def render(start: date, end: date, week_label: str) -> str:
    g = gather(start, end)
    out = [f"# 世界周报 {week_label}（{start} ~ {end}）\n"]

    out.append("## 她知道的部分\n")
    if g["her_diary"]:
        for f in g["her_diary"]:
            out.append(f"### {f.stem}\n")
            out.append(f.read_text(encoding="utf-8"))
            out.append("")
    else:
        out.append("（本周她的日记空缺）\n")

    out.append("## 她不知道的部分（世界真相）\n")
    hidden = [l for l in g["world"] if "暗线" in l]
    public = [l for l in g["world"] if "公开" in l]
    if public:
        out.append("**已公开的世界事件**（这些迟早会以传闻形式到达她）：")
        out += [f"- {l}" for l in public]
    if hidden:
        out.append("\n**暗线**（只有导演和你知道）：")
        out += [f"- {l}" for l in hidden]
    if not g["world"]:
        out.append("（本周世界风平浪静）")

    out.append("\n## 因果链提示\n")
    out.append("对照上面两栏：世界暗线的迹象，有没有变成她日记里的情绪波动？")
    out.append("这就是「我能看到因果，但我算不出结果」——下周她会怎么反应，写出来才算数。")

    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=1, help="往前生成几周（默认 1=上周）")
    args = ap.parse_args()
    out_dir = Path(config.DATA_DIR) / "weekly"
    out_dir.mkdir(parents=True, exist_ok=True)
    for w in range(1, args.weeks + 1):
        start, end, label = _week_range(w)
        report = render(start, end, label)
        p = out_dir / f"{label}.md"
        p.write_text(report, encoding="utf-8")
        print("生成:", p)


if __name__ == "__main__":
    main()
