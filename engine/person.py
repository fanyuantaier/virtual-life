"""Person：一个数字人格。整合记忆/需求/关系/反思，与具体 seed 解耦。

用法：
    from engine.person import Person
    p = Person.create(name="某人", birth_params={...}, seed=7)
    p.remember("今天发生了什么", importance=5, key=1)
    p.reflect()

数据存储：profiles/<name>/（独立记忆库、日记、关系档案）。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import config


@dataclass
class BirthParams:
    name: str                     # 大名
    nickname: str                 # 小名
    city: str
    family_type: str
    parent_jobs: list[str]
    economy: str
    temperament: list[str]
    birth_date: date

    def render(self) -> str:
        return (f"大名：{self.name}，小名：{self.nickname}。出生地：{self.city}。"
                f"家庭：{self.family_type}，父亲是{self.parent_jobs[0]}，"
                f"母亲是{self.parent_jobs[1]}。家境{self.economy}。"
                f"先天气质：{'、'.join(self.temperament)}。")


class Person:
    """一个可持续生活、记忆、遗忘、做梦的数字人格。"""

    def __init__(self, name: str, root: Path | None = None):
        self.name = name
        self.root = root or (Path(config.BASE_DIR) / "profiles" / name)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "memory.db"
        self.diary_dir = self.root / "diary"
        self.dream_dir = self.root / "dreams"
        self.relation_file = self.root / "relation.json"
        self.birth_file = self.root / "birth.json"
        self._store = None

    # ---- 创建 ----

    @classmethod
    def create(cls, name: str, nickname: str, seed: int = 42,
               city: str = "苏州", family_type: str = "三口之家",
               parent_jobs: list[str] | None = None,
               economy: str = "普通", temperament: list[str] | None = None,
               birth_date: date | None = None) -> "Person":
        import random
        rng = random.Random(seed)
        p = cls(name)
        p.birth_file.write_text(json.dumps({
            "name": name, "nickname": nickname, "seed": seed,
            "city": city, "family_type": family_type,
            "parent_jobs": parent_jobs or ["教师", "司机"],
            "economy": economy,
            "temperament": temperament or ["活泼", "好动"],
            "birth_date": (birth_date or date.today()).isoformat(),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        # 初始记忆锚点：出生
        store = p.store
        store.add("event", f"({nickname}出生) {city}，{family_type}。第一声哭很响。", key=3)
        return p

    @classmethod
    def load(cls, name: str) -> "Person":
        return cls(name)

    # ---- 属性 ----

    @property
    def store(self):
        if self._store is None:
            from memory.store import MemoryStore
            self._store = MemoryStore(db_path=self.db_path)
        return self._store

    @property
    def birth(self) -> dict:
        return json.loads(self.birth_file.read_text(encoding="utf-8"))

    def age_years(self, on: date | None = None) -> float:
        b = date.fromisoformat(self.birth["birth_date"])
        return max(0.0, ((on or date.today()) - b).days / 365.25)

    def persona_text(self) -> str:
        import sqlite3
        con = sqlite3.connect(str(self.db_path))
        rows = con.execute("SELECT text FROM nodes WHERE kind='persona' "
                           "ORDER BY ts DESC LIMIT 7").fetchall()
        con.close()
        b = self.birth
        return (f"大名：{b['name']}，小名：{b['nickname']}。{b['city']}人。\n"
                "性格（经历沉淀）：\n" + "\n".join(f"- {t}" for t, in rows))

    # ---- 记忆操作（遗忘曲线自动生效） ----

    def remember(self, text: str, importance: float = 5.0,
                 key: int = 1, when: datetime | None = None) -> int:
        return self.store.add("event", text, when=when, importance=importance, key=key)

    def remember_chat(self, with_whom: str, user_msg: str, reply: str) -> None:
        p = self.root / "user_memories.json"
        mems = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        mems.append({"when": datetime.now().isoformat(timespec="seconds"),
                     "with": with_whom, "user": user_msg, "reply": reply})
        p.write_text(json.dumps(mems[-500:], ensure_ascii=False, indent=1), encoding="utf-8")

    def recall(self, query: str, k: int = 6) -> list[dict]:
        nodes = self.store.retrieve(query, top_k=k)
        return [{"text": n["text"], "when": n["when"],
                 "retention": n.get("retention", 1.0)} for n, _ in nodes]

    # ---- 生活 ----

    def dream(self, llm_chat) -> str | None:
        from memory.dream import dream_night
        return dream_night(llm_chat, self.store)

    def reflect(self, llm_chat) -> str:
        from memory.forgetting import is_key_memory  # noqa
        thoughts = self.store.reflect(llm_chat)
        return "；".join(t["text"] for t in thoughts)

    # ---- 导出 ----

    def export_summary(self) -> dict:
        import sqlite3
        con = sqlite3.connect(str(self.db_path))
        n, = con.execute("SELECT COUNT(*) FROM nodes").fetchone()
        kinds = dict(con.execute("SELECT kind, COUNT(*) FROM nodes GROUP BY kind").fetchall())
        con.close()
        return {"name": self.name, "age_years": round(self.age_years(), 2),
                "memory_total": n, "kinds": kinds}
