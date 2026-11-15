"""数据导入器：把用户的真实记忆转成 Person 的记忆节点。

支持来源：
- wechat(txt)  ：微信聊天记录导出文本（一行一条，"发送者: 内容"格式）
- diary(txt)   ：日记文件（按日期分隔或纯文本流）
- photos(dir)  ：照片目录（按文件日期生成 EXIF 时刻记忆）

所有导入默认 key=2（重要但非终身锚点），用户可在导入后手工调级。
"""
from __future__ import annotations

import random
import re
from datetime import datetime
from pathlib import Path


def import_wechat_txt(person, txt_path: Path, peer_name: str,
                      max_lines: int = 2000) -> int:
    """导入微信聊天导出文本。格式：'2024-01-01 12:00:00 名字\\n内容' 或 '名字: 内容'。
    每条以 key=2 入库（和某人的真实交流是重要记忆）。"""
    count = 0
    text = Path(txt_path).read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}.*?[:：]\s*(.+)$")
    for line in text.splitlines()[:max_lines]:
        line = line.strip()
        if not line or line.startswith("========"):
            continue
        m = pattern.match(line)
        content = m.group(1) if m else line
        if len(content) < 4:
            continue
        person.store.add("chat", f"和{peer_name}的聊天：{content[:100]}",
                         importance=4.0, key=2)
        count += 1
        if count >= max_lines:
            break
    return count


def import_diary_txt(person, txt_path: Path, max_entries: int = 500) -> int:
    """导入日记文本。支持日期行（2024-01-01 / 2024年1月1日 / 1月1日）分段。"""
    count = 0
    text = Path(txt_path).read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*(?=\d{4}[-年]|\d{1,2}月\d{1,2}日)", text)
    for block in blocks[:max_entries]:
        block = block.strip()
        if len(block) < 20:
            continue
        # 尝试提取日期
        m = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})", block[:40])
        when = None
        if m:
            try:
                when = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        summary = block[:150].replace("\n", " ")
        person.store.add("event", f"(日记) {summary}",
                         when=when, importance=6.0, key=2)
        count += 1
    return count


def import_photo_dir(person, photo_dir: Path, max_photos: int = 200) -> int:
    """导入照片目录：按文件修改时间生成时刻记忆（照片本身不入库，只留时刻线索）。"""
    count = 0
    exts = {".jpg", ".jpeg", ".png", ".heic"}
    photos = sorted([f for f in Path(photo_dir).iterdir()
                     if f.suffix.lower() in exts], key=lambda f: f.stat().st_mtime)
    for f in photos[:max_photos]:
        when = datetime.fromtimestamp(f.stat().st_mtime)
        person.store.add("event", f"(照片时刻) {f.stem}——那天拍了一张照片",
                         when=when, importance=4.0, key=1)
        count += 1
    return count


def import_mixed(person, source_dir: Path) -> dict:
    """混合导入：扫描目录，txt 尝试日记/微信，图片走照片。返回统计。"""
    stats = {"wechat": 0, "diary": 0, "photos": 0}
    for f in Path(source_dir).rglob("*"):
        if f.suffix.lower() == ".txt":
            content = f.read_text(encoding="utf-8", errors="replace")[:500]
            if re.search(r"^\d{4}-\d{2}-\d{2}.*[:：]", content, re.M):
                stats["wechat"] += import_wechat_txt(person, f)
            else:
                stats["diary"] += import_diary_txt(person, f)
        elif f.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic"}:
            stats["photos"] += import_photo_dir(person, f.parent)
    return stats
