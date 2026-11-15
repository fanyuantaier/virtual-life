"""现实收件箱模块：熟人消息注入点。

用户把想"寄给"虚拟主角的消息写成 .txt 文件放进收件箱目录
（默认 data/inbox），每个文件一条消息；scan_inbox() 扫描后：

1. 解析出 {sender, text, when}（when 为文件 mtime）；
2. 把原文件移动到同目录下 archive/ 子目录完成归档（避免下次重复读取）。

文件名（去 .txt）作为 sender；文件内容整段作为 text。目录不存在或
扫描失败返回 []，不抛异常。
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DIR = Path("data") / "inbox"
ARCHIVE_DIRNAME = "archive"


def scan_inbox(dir_path: str | Path = DEFAULT_DIR) -> list[dict[str, Any]]:
    """扫描收件箱目录，读取并归档所有 .txt 消息文件。

    - dir_path 不存在：返回 []（首次运行属正常状态，不算错误）。
    - 每个非隐藏的 .txt 文件视为一条消息：文件名=sender，内容=text，
      文件 mtime=when。
    - 读到的文件移动到 dir_path/archive/ 下（重名自动加序号），即"归档"。
    - 单个文件读取失败只记 log 并跳过，不影响其余文件。
    """
    inbox = Path(dir_path)
    if not inbox.is_dir():
        return []  # 目录不存在不算错误：用户还没放消息而已

    messages: list[dict[str, Any]] = []
    archive = inbox / ARCHIVE_DIRNAME
    try:
        candidates = sorted(inbox.glob("*.txt"))
    except OSError as exc:
        log.warning("inbox: 扫描 %s 失败: %s", inbox, exc)
        return []

    for path in candidates:
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            stat = path.stat()
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            log.warning("inbox: 读取 %s 失败，跳过: %s", path, exc)
            continue
        if not text:
            log.info("inbox: %s 内容为空，跳过", path.name)
            continue
        messages.append({
            "sender": path.stem,
            "text": text,
            "when": datetime.fromtimestamp(stat.st_mtime),
        })
        # ---- 归档：移入 archive/，重名追加序号 ----
        try:
            archive.mkdir(parents=True, exist_ok=True)
            dest = archive / path.name
            i = 1
            while dest.exists():
                dest = archive / f"{path.stem}_{i}{path.suffix}"
                i += 1
            shutil.move(str(path), str(dest))
        except OSError as exc:
            # 归档失败不致命：消息已读，但下次会重复注入，记 warning
            log.warning("inbox: 归档 %s 失败（下次可能重复读取）: %s", path, exc)

    if messages:
        log.info("inbox: 收到 %d 条熟人消息", len(messages))
    return messages
