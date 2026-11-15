"""虚拟人生成器 · 一键启动脚本。

首次运行自动引导配置模型端点；之后按菜单操作。
用法：python start.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CFG_FILE = Path("config_local.json")   # 用户配置（不入库，优先于 config.py）


def load_local() -> dict:
    if CFG_FILE.exists():
        return json.loads(CFG_FILE.read_text(encoding="utf-8"))
    return {}


def save_local(cfg: dict) -> None:
    CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def first_time_setup() -> dict:
    """首次运行：引导填写模型端点。"""
    local = load_local()
    if local.get("llm_base_url") and local.get("llm_model"):
        return local
    print("=" * 60)
    print("首次运行 · 模型配置引导")
    print("=" * 60)
    print("本系统需要一个 OpenAI 兼容的 chat 端点（导演+主角+反思共用）。")
    print("常见选择：")
    print("  1. Ollama 本地        http://127.0.0.1:11434/v1")
    print("  2. llama.cpp 本地     http://127.0.0.1:8080/v1")
    print("  3. 云 API             如 https://api.deepseek.com/v1")
    print("  4. 自行输入")
    choice = input("选择 [1-4]: ").strip()
    presets = {
        "1": "http://127.0.0.1:11434/v1",
        "2": "http://127.0.0.1:8080/v1",
        "3": "",
    }
    base_url = presets.get(choice) or input("base_url: ").strip()
    if not base_url:
        base_url = input("base_url: ").strip()
    model = input("模型名（如 qwen3:8b / GLM-5.3-Flash / deepseek-chat）: ").strip()
    api_key = input("api_key（本地服务直接回车）: ").strip()
    if not base_url or not model:
        print("base_url 和模型名不能为空。")
        sys.exit(1)
    local.update({"llm_base_url": base_url, "llm_model": model, "api_key": api_key})

    # embedding 可选
    print("\nEmbedding 端点（可选：没有就回车，记忆检索降级为字符相似度，仍可用）")
    embed_url = input("embedding base_url（如 http://127.0.0.1:11434/v1）: ").strip()
    embed_model = input("embedding 模型名（如 nomic-embed-text）: ").strip()
    local.update({"embed_base_url": embed_url, "embed_model": embed_model})

    # 相识方式
    print("\n你和主角怎么认识的？（回车=默认 打王者认识的）")
    print("可选：打王者认识的 / 网友 / 笔友 / 同学的同学 / 邻居")
    way = input("相识方式: ").strip() or "打王者认识的"
    local.update({"meet_way": way})

    save_local(local)
    print("\n配置已保存到", CFG_FILE)
    return local


def apply_config(local: dict) -> None:
    """把用户配置注入运行时（config 模块）。"""
    import config
    if local.get("llm_base_url"):
        config.LLM_BASE_URL = local["llm_base_url"]
    if local.get("llm_model"):
        config.LLM_MODEL = local["llm_model"]
    if local.get("api_key"):
        config.API_KEY = local["api_key"]
    if local.get("embed_base_url"):
        config.EMBED_BASE_URL = local["embed_base_url"]
    if local.get("embed_model"):
        config.EMBED_MODEL = local["embed_model"]


def ensure_relation(meet_way: str | None) -> None:
    import relation as rel_mod
    if meet_way:
        rel_mod.set_meet_way(meet_way)


def cmd_new(args) -> None:
    """创建一个新的人生（随机出生参数）。"""
    apply_config(load_local())
    ensure_relation(load_local().get("meet_way"))
    import random
    seed = args.seed if args.seed else random.randint(1, 99999)
    from life import LifeSim
    sim = LifeSim(seed)
    print(f"出生参数已生成（seed={seed}）：\n{sim.birth.render()}")
    print("开始快进到 18 岁（月度跳跃，约 3 分钟/月 × 216 月）。Ctrl+C 可中断，")
    print("重跑 python start.py new --seed", seed, "会从头开始；用 continue 恢复。")
    sim.run(max_age=args.max_age, fast_mode=True)


def cmd_continue(args) -> None:
    """从记忆库断点续跑快进。"""
    apply_config(load_local())
    ensure_relation(load_local().get("meet_way"))
    from life import LifeSim
    import sqlite3, datetime, time
    sim = LifeSim(42)
    con = sqlite3.connect(str(sim.db_path))
    try:
        last_ts, = con.execute("SELECT MAX(ts) FROM nodes WHERE kind='event'").fetchone()
    finally:
        con.close()
    last_date = datetime.fromtimestamp(last_ts).date() if last_ts else sim.birth_date
    sim_date = last_date + timedelta(days=30)
    from world.life import stage_for_age
    while True:
        age = (sim_date - sim.birth_date).days / 365.25
        if age >= args.max_age:
            print(f"=== 到达 {args.max_age} 岁 ===")
            sim.annual_reflection(age)
            break
        stage = stage_for_age(age)
        n = sim.run_month_jump(sim_date, age, stage)
        print(f"快进到 {sim_date}（{age:.2f} 岁），新增 {n}")
        if int((sim_date - sim.birth_date).days / 365.25) != int(age):
            sim.annual_reflection(age)
        sim_date = sim_date + timedelta(days=30)
        time.sleep(1.0)


def cmd_chat(args) -> None:
    """和主角聊天。"""
    apply_config(load_local())
    ensure_relation(load_local().get("meet_way"))
    import chat
    chat.main()


def cmd_live(args) -> None:
    """成人实时模式（18 岁后）：按真实时钟过日常+凌晨梦境。"""
    apply_config(load_local())
    import adult
    adult.main()


def cmd_daemon(args) -> None:
    """默认演示线（小澄）的实时守护。"""
    apply_config(load_local())
    import daemon
    daemon.tick() if not args.loop else None
    if args.loop:
        while True:
            try:
                daemon.tick()
            except Exception as exc:
                print("tick 异常:", exc)
            time.sleep(600)


def cmd_stats(args) -> None:
    """查看当前人生状态。"""
    apply_config(load_local())
    import config
    from life import LifeSim
    import sqlite3
    from datetime import datetime
    sim = LifeSim(42)
    con = sqlite3.connect(str(sim.db_path))
    n, = con.execute("SELECT COUNT(*) FROM nodes").fetchone()
    last_ts, = con.execute("SELECT MAX(ts) FROM nodes WHERE kind='event'").fetchone()
    con.close()
    birth = datetime.combine(sim.birth_date, datetime.min.time())
    last_age = ((datetime.fromtimestamp(last_ts) if last_ts else datetime.now()) - birth).days / 365.25
    diary = len(list((config.DATA_DIR / "diary_life").rglob("*.md")))
    print(f"主角：seed42 囡囡（{sim.birth.render()}）")
    print(f"年龄：{last_age:.2f} 岁 | 记忆节点：{n} | 日记：{diary} 篇")
    dreams = len(list((config.DATA_DIR / "diary_life" / "dreams").glob("*.md")))
    print(f"梦境：{dreams} 个")
    import relation as rel_mod
    rel = rel_mod.load_relation()
    print(f"与你的关系：{rel['way']}，聊了 {rel['rounds']} 轮（{rel_mod.intimacy_label(rel['rounds'])}）")


import time
from datetime import timedelta


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="虚拟人生成器")
    sub = ap.add_subparsers(dest="cmd")

    p_new = sub.add_parser("new", help="创建新人生（快进到 18 岁）")
    p_new.add_argument("--seed", type=int, default=None)
    p_new.add_argument("--max-age", type=int, default=18)

    p_cont = sub.add_parser("continue", help="断点续跑快进")
    p_cont.add_argument("--max-age", type=int, default=18)

    sub.add_parser("chat", help="和主角聊天")
    sub.add_parser("live", help="成人实时模式（按真实时钟过日常+凌晨梦境）")

    p_daemon = sub.add_parser("daemon", help="演示线实时守护")
    p_daemon.add_argument("--loop", action="store_true")

    sub.add_parser("stats", help="查看当前人生状态")

    args = ap.parse_args()
    if not args.cmd:
        # 无参数：显示菜单
        print("""
虚拟人生成器
============
  python start.py new [--seed N]   创建新人生（无人设随机出生→快进到 18 岁）
  python start.py continue         断点续跑快进
  python start.py chat             和 18 岁的主角聊天
  python start.py live             成人实时模式（常驻：按真实时钟过日常+凌晨做梦）
  python start.py stats            查看当前状态
""")
        return
    fn = {"new": cmd_new, "continue": cmd_continue, "chat": cmd_chat,
          "live": cmd_live, "daemon": cmd_daemon, "stats": cmd_stats}.get(args.cmd)
    if fn:
        fn(args)


if __name__ == "__main__":
    main()
