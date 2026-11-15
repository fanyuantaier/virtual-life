"""追加式人格文件：人设头部固定，自我认知只增不删、带日期与自增编号。

膨胀治理（11-08）：正文条目超过 ARCHIVE_KEEP 时，最旧的自动移入
self_archived.md（不丢数据，但不占 render 的上下文）——
防止"只增不删"导致人格文件无限膨胀、稀释 L3 画像的信号。
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import config

_HEADER_END = "<!-- 自我认知（以下只增不删） -->"


class Persona:
    ARCHIVE_KEEP = 60           # self.md 内保留最近 60 条；更早的移入归档

    def __init__(self, path=config.PERSONA_PATH):
        self.path = str(path)
        self._ensure()

    def _ensure(self) -> None:
        if not Path(self.path).exists():
            Path(self.path).write_text("（人格头部待填）\n\n" + _HEADER_END + "\n", encoding="utf-8")

    def _read(self) -> tuple[str, list[tuple[int, str, str]]]:
        content = Path(self.path).read_text(encoding="utf-8")
        if _HEADER_END in content:
            head, tail = content.split(_HEADER_END, 1)
        else:
            head, tail = content, ""
        entries: list[tuple[int, str, str]] = []
        for m in re.finditer(r"^#(\d+) \(([\d-]+)\) (.+)$", tail, re.M):
            entries.append((int(m.group(1)), m.group(2), m.group(3).strip()))
        return head.strip(), entries

    def update(self, entries: list[str], on: date | None = None) -> list[int]:
        """追加自我认知条目，返回分配的编号。超量旧条目自动归档。"""
        if not entries:
            return []
        on = on or date.today()
        _, existing = self._read()
        next_id = (existing[-1][0] + 1) if existing else 1
        with open(self.path, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(f"#{next_id} ({on:%Y-%m-%d}) {e.strip()}\n")
                next_id += 1
        self._archive_overflow()
        return list(range(next_id - len(entries), next_id))

    def _archive_overflow(self) -> int:
        """把超出 ARCHIVE_KEEP 的旧条目移进 self_archived.md。返回移动条数。"""
        content = Path(self.path).read_text(encoding="utf-8")
        if _HEADER_END not in content:
            return 0
        head, tail = content.split(_HEADER_END, 1)
        lines = [l for l in tail.splitlines() if l.strip()]
        if len(lines) <= self.ARCHIVE_KEEP:
            return 0
        overflow, keep = lines[:-self.ARCHIVE_KEEP], lines[-self.ARCHIVE_KEEP:]
        arch_path = Path(self.path).parent / "self_archived.md"
        with arch_path.open("a", encoding="utf-8") as af:
            af.write(f"\n<!-- 归档于 {date.today().isoformat()} -->\n")
            for l in overflow:
                af.write(l + "\n")
        Path(self.path).write_text(head + _HEADER_END + "\n" + "\n".join(keep) + "\n",
                                   encoding="utf-8")
        return len(overflow)

    def render(self, last_n: int = 30) -> str:
        """系统提示用：头部 + 最近 N 条自我认知。"""
        head, entries = self._read()
        tail = entries[-last_n:]
        lines = [head, "", "自我认知（随经历增长）："]
        lines += [f"#{i} ({d}) {t}" for i, d, t in tail]
        return "\n".join(lines)

    # ---- 用户自定义人设卡（优先级高于一切生成内容）----

    USER_CARD = Path(config.DATA_DIR) / "user_card.json"

    def user_card(self) -> dict:
        """读用户手写的人设卡；没有则返回空。字段均可选：
        name/nickname/personality/opening/relationship/backstory"""
        if self.USER_CARD.exists():
            try:
                return json.loads(self.USER_CARD.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}
