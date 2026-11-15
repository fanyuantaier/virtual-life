"""多实例管理：profiles/<name>/ 目录 = 一个独立人格。

用法：
    from engine.profiles import list_profiles, load_profile
    list_profiles()            # ['nana', 'my-shadow', ...]
    p = load_profile('nana')   # 返回 Person 实例
"""
from __future__ import annotations

import json
from pathlib import Path

import config

PROFILES_DIR = Path(config.BASE_DIR) / "profiles"


def list_profiles() -> list[str]:
    if not PROFILES_DIR.exists():
        return []
    return sorted([d.name for d in PROFILES_DIR.iterdir()
                   if d.is_dir() and (d / "birth.json").exists()])


def load_profile(name: str):
    from engine.person import Person
    return Person.load(name)


def profile_info(name: str) -> dict | None:
    p = PROFILES_DIR / name
    if not (p / "birth.json").exists():
        return None
    b = json.loads((p / "birth.json").read_text(encoding="utf-8"))
    import sqlite3
    con = sqlite3.connect(str(p / "memory.db"))
    n, = con.execute("SELECT COUNT(*) FROM nodes").fetchone()
    con.close()
    return {"name": b.get("name"), "nickname": b.get("nickname"),
            "city": b.get("city"), "memory_total": n}
