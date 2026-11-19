"""每日记忆加厚：把指定日期的密度拉到 max（事件 8-16 条/天）。

早 07:30：补昨天（完整一天）+ 今天上午
夜 22:30：补今天（白天+夜）

用法：python -X utf8 harness/daily_densify.py [--date 2026-11-19]
不带 --date 时自动判断：现在 <20 点 → 补昨天+今天上午；>=20 点 → 补今天全天。
单发简版 prompt（深夜/凌晨导演失败率高，此路成功率 ~100%）。
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


def _cfg_url() -> str:
    lp = Path(__file__).resolve().parent.parent / "config_local.json"
    if lp.exists():
        return json.loads(lp.read_text(encoding="utf-8")).get("llm_base_url") or ""
    return ""


from life import LifeSim          # 必须先于 world.* 导入，否则 world/life.py 遮蔽 life
from world.director import LLMClient
from world.json_repair import robust_parse


def densify_day(sim, d: date, llm: LLMClient, part: str) -> int:
    """单发简版生成一天的加密片段并入库。part: 'day'（全天）/'morning'。"""
    store = sim.store()
    recent = store.recent(days=5.0)
    chronicle = chr(10).join(f"[{n['when']:%m-%d %H:%M}] {n['text']}" for n in recent[-8:])
    scope = "这一天从早到晚" if part == "day" else "这一天的上午到中午"
    n_have = 0
    lo = datetime(d.year, d.month, d.day).timestamp()
    for (ts,) in store._con().execute(
            "SELECT ts FROM nodes WHERE kind='event' AND ts BETWEEN ? AND ?", (lo, lo + 86400)).fetchall():
        n_have += 1
    store._con().close()
    prompt = (
        f"你是人生记录员。给 18 岁女孩沈青蔓（苏州，爸妈离异随母，外婆同住，爸爸长途司机，"
        f"爱记账、把好东西分一半，毕业刚工作）写 {d.isoformat()} {scope} 的 5 条新片段。\n"
        f"近期她的生活：\n{chronicle}\n"
        f"该日期已有 {n_have} 条记录，你写的必须是【没写过的新角度】：换地点、换人物、换感官细节。\n"
        f"要求：口语、每条 1-2 句、带具体物件或人、与近期事件有因果。"
        f'只输出 JSON 数组：[{{"content":"...", "intensity":2}}]'
    )
    raw = llm.chat(prompt, "只输出 JSON 数组。", max_tokens=8000)
    data = robust_parse(raw.split("</think>")[-1])
    items = data if isinstance(data, list) else []
    n = 0
    age = (d - date(2008, 11, 4)).days / 365.25
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not it.get("content"):
            continue
        store.add("event", f"({age:.1f}岁) {it['content']}",
                  when=datetime(d.year, d.month, d.day, 12 + i * 2, 0),
                  importance=4.0, key=1)
        n += 1
    return n


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=str, default=None)
    args = ap.parse_args()
    sim = LifeSim(42)
    llm = LLMClient(model=config._think_model(),
                    base_url=config.LLM_BASE_URL or _cfg_url(), timeout=480.0)
    today = date.today()
    if args.date:
        d = date.fromisoformat(args.date)
        n = densify_day(sim, d, llm, "day")
        print(f"{d}: +{n}", flush=True)
        return
    now = datetime.now()
    results = []
    if now.hour < 20:
        # 早间档：补昨天全天 + 今天上午
        y = today - timedelta(days=1)
        results.append((y, densify_day(sim, y, llm, "day")))
        results.append((today, densify_day(sim, today, llm, "morning")))
    else:
        # 夜间档：补今天全天
        results.append((today, densify_day(sim, today, llm, "day")))
    for d, n in results:
        print(f"{d}: +{n} 事件", flush=True)


if __name__ == "__main__":
    main()
