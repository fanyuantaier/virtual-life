"""多用户应用层：从单人实验到多人可用。

设计原则（对应"适应更多人的需求"）：
1. 本地优先：所有记忆/日记/对话存本机，无云端依赖（隐私默认安全）
2. 三分钟上手：向导式创建（自己/亲人/逝者纪念/虚拟角色 四种模板）
3. 数据主权：一键导出（JSON+Markdown）/ 一键删除（真正删除，不留备份）
4. 隔离：每个 profile 独立目录/记忆库/关系档案，互不可见

使用方式（网页）：
    python web/server.py → 浏览器打开 → 无 profile 时自动进创建向导
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path

import config

PROFILES_DIR = Path(config.BASE_DIR) / "profiles"

# 四种创建模板：决定初始记忆种子和需求基线
TEMPLATES = {
    "self": {
        "label": "我自己的数字分身",
        "desc": "导入你的微信记录/日记/照片，AI 用你的记忆长成你的样子",
        "seed_memories": [],
        "needs_bias": {},
    },
    "family": {
        "label": "亲人的数字分身",
        "desc": "为父母/祖辈创建——导入他们的记录，留一份会说话的记忆",
        "seed_memories": [],
        "needs_bias": {"social": {"decay": 0.8}},
    },
    "memorial": {
        "label": "逝者纪念",
        "desc": "以逝者的记录为基础创建。语气更温和，避免敏感话题",
        "seed_memories": [],
        "needs_bias": {"social": {"decay": 0.5}, "achievement": {"threshold": -10}},
        "guard": "memorial",
    },
    "fiction": {
        "label": "虚拟角色",
        "desc": "小说角色/游戏 NPC/品牌 IP——完全虚构但人格连贯",
        "seed_memories": [],
        "needs_bias": {},
    },
}


def list_all() -> list[dict]:
    """所有 profile 的概览（供网页选择）。"""
    out = []
    if not PROFILES_DIR.exists():
        return out
    for d in sorted(PROFILES_DIR.iterdir()):
        bf = d / "birth.json"
        if not bf.exists():
            continue
        b = json.loads(bf.read_text(encoding="utf-8"))
        db = d / "memory.db"
        n = 0
        if db.exists():
            import sqlite3
            try:
                con = sqlite3.connect(str(db))
                n, = con.execute("SELECT COUNT(*) FROM nodes").fetchone()
                con.close()
            except Exception:
                pass
        out.append({"profile_id": d.name, "name": b.get("name"),
                    "nickname": b.get("nickname"), "memories": n,
                    "template": b.get("template", "fiction")})
    return out


def create_from_template(profile_id: str, template: str, name: str,
                         nickname: str = "", **kwargs) -> Path:
    """按模板创建 profile。返回目录。"""
    if template not in TEMPLATES:
        raise ValueError(f"未知模板: {template}")
    t = TEMPLATES[template]
    root = PROFILES_DIR / profile_id
    if root.exists():
        raise FileExistsError(f"profile 已存在: {profile_id}")
    root.mkdir(parents=True, exist_ok=True)

    birth = {
        "name": name, "nickname": nickname or name, "template": template,
        "city": kwargs.get("city", ""),
        "family_type": kwargs.get("family_type", ""),
        "parent_jobs": kwargs.get("parent_jobs", []),
        "economy": kwargs.get("economy", ""),
        "temperament": kwargs.get("temperament", []),
        "birth_date": kwargs.get("birth_date", date.today().isoformat()),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "guard": t.get("guard", ""),
    }
    (root / "birth.json").write_text(
        json.dumps(birth, ensure_ascii=False, indent=1), encoding="utf-8")
    # 初始记忆种子
    from engine.person import Person
    p = Person.load(profile_id)
    for m in t["seed_memories"]:
        p.store.add("event", m, importance=5.0, key=3)
    return root


def export_profile(profile_id: str, out_path: Path | None = None) -> Path:
    """一键导出：记忆库 + 日记 + 关系档案 → 单个 JSON + Markdown 包。"""
    root = PROFILES_DIR / profile_id
    if not root.exists():
        raise FileNotFoundError(profile_id)
    out_path = out_path or (config.DATA_DIR / "exports" / f"{profile_id}_{datetime.now():%Y%m%d}.zip")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # JSON：结构化记忆
    import sqlite3
    data = []
    db = root / "memory.db"
    if db.exists():
        con = sqlite3.connect(str(db))
        try:
            rows = con.execute("SELECT kind, text, ts, importance, mem_key FROM nodes ORDER BY ts").fetchall()
            data = [{"kind": k, "text": t,
                     "when": datetime.fromtimestamp(ts).isoformat(),
                     "importance": i, "key": mk} for k, t, ts, i, mk in rows]
        except sqlite3.OperationalError:
            pass
        con.close()
    tmp_json = root / "export.json"
    tmp_json.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    # Markdown：人可读版
    md_lines = [f"# {profile_id} 记忆导出（{datetime.now():%Y-%m-%d}）\n"]
    for item in data:
        md_lines.append(f"- [{item['when'][:10]}][{item['kind']}] {item['text']}")
    tmp_md = root / "export.md"
    tmp_md.write_text("\n".join(md_lines), encoding="utf-8")

    # 打包
    import zipfile
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_json, "memories.json")
        z.write(tmp_md, "memories.md")
        diary = root / "diary"
        if diary.exists():
            for f in diary.rglob("*.md"):
                z.write(f, f"diary/{f.relative_to(diary)}")
        if (root / "birth.json").exists():
            z.write(root / "birth.json", "birth.json")
    tmp_json.unlink()
    tmp_md.unlink()
    return out_path


def delete_profile(profile_id: str, keep_backup: bool = False) -> int:
    """真正删除一个 profile（含记忆库/日记/关系）。返回删除的记忆数。
    keep_backup=True 时先导出一份 zip 到 exports/ 再删。"""
    root = PROFILES_DIR / profile_id
    if not root.exists():
        raise FileNotFoundError(profile_id)
    import sqlite3
    n = 0
    if (root / "memory.db").exists():
        con = sqlite3.connect(str(root / "memory.db"))
        try:
            n, = con.execute("SELECT COUNT(*) FROM nodes").fetchone()
        except sqlite3.OperationalError:
            n = 0
        con.close()
    if keep_backup:
        export_profile(profile_id)
    shutil.rmtree(root)
    return n


import shutil  # noqa: E402  (delete_profile 用)
