"""日循环调度器：把"现实的一天"推进给虚拟人。

run_day(date, ctx) 按 morning → afternoon → evening → night 四段推进，
每段做三件事：
  1. 组装输入：本段事件槽位（由 ctx.director 生成 DayPlan）、记忆检索、
     现实钩子（天气/新闻/收件箱）、昨日摘要；
  2. 调 ctx.director 产出/补全本段事件；
  3. 调 ctx.protagonist 对事件做出反应，DiaryEntry 追加落盘到
     data/diary/YYYY-MM-DD.md（utf-8）。

夜间段结束后调 ctx.memory.reflect() 收尾，并更新"昨日摘要"缓存；
每日结束后把 SQLite（ctx.paths.db）备份到 data/backups/YYYY-MM-DD.db。

断点续跑：每段结束把 {date, slot, ...快照} 写 data/checkpoints/state.json；
进程重启后先调 load_checkpoint()，若断点日期与待跑日期一致则从断点的
下一个槽位继续，已写入的日记不重复生成。

== ctx 契约（集成者提供，本模块只定义 Protocol 并按此调用） ==
ctx 是 SimpleNamespace 风格对象，含五个字段：
  memory       MemoryProtocol      记忆系统
  director     DirectorProtocol    世界导演（产出 DayPlan）
  protagonist  ProtagonistProtocol 虚拟主角
  reality      RealityProtocol     现实钩子（weather/news/inbox 可为 None）
  paths        PathsProtocol       各种落盘路径

各 Protocol 所需方法签名见本文件下方定义；未实现的字段允许为 None，
runner 会在运行时跳过对应能力（优雅降级）。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, Protocol, runtime_checkable

# 共享契约：只 import，不修改（contracts.py 在上级目录，这里把项目根加进 path）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from contracts import DayPlan, DecisionResult, DiaryEntry, Event  # noqa: E402

log = logging.getLogger(__name__)

SLOTS = ("morning", "afternoon", "evening", "night")


# ============================================================
# Protocol 定义：集成者按此实现 ctx 的各字段
# ============================================================

@runtime_checkable
class MemoryProtocol(Protocol):
    def retrieve(self, query: str, k: int = 5) -> list[Any]:
        """按查询文本检索相关记忆，返回 MemoryHit 列表。"""
        ...

    def reflect(self, entries: list[DiaryEntry]) -> str:
        """夜间反思：输入当日日记，返回反思/摘要文本。"""
        ...


@runtime_checkable
class DirectorProtocol(Protocol):
    def make_day_plan(self, d: date, context: dict[str, Any]) -> DayPlan:
        """生成某日的 DayPlan（四段事件）；context 含现实钩子/昨日摘要等。"""
        ...


@runtime_checkable
class ProtagonistProtocol(Protocol):
    def react(
        self,
        dayplan_events: list[Any],      # list[Event]
        memory_hits: list[Any],         # list[MemoryHit]
        persona_text: str,
    ) -> tuple[list[DiaryEntry], list[DecisionResult]]:
        """对本段事件做出反应：返回 (日记条目, 决策结果)。"""
        ...


@runtime_checkable
class RealityProtocol(Protocol):
    def get_weather(self, city: str) -> Optional[dict[str, Any]]: ...
    def get_headlines(self, n: int = 5) -> list[str]: ...
    def scan_inbox(self, dir_path: Any = None) -> list[dict[str, Any]]: ...


@runtime_checkable
class PathsProtocol(Protocol):
    db: str                       # SQLite 数据库路径
    diary_dir: Path               # 日记目录 data/diary
    checkpoint_file: Path         # 断点文件 data/checkpoints/state.json
    backup_dir: Path              # 备份目录 data/backups
    inbox_dir: Path               # 收件箱目录 data/inbox


# ============================================================
# 路径与默认 ctx
# ============================================================

def default_paths(base: str | Path = ".") -> SimpleNamespace:
    """默认路径布局，均相对项目根目录 base。"""
    base = Path(base)
    return SimpleNamespace(
        db=str(base / "data" / "life.db"),
        diary_dir=base / "data" / "diary",
        checkpoint_file=base / "data" / "checkpoints" / "state.json",
        backup_dir=base / "data" / "backups",
        inbox_dir=base / "data" / "inbox",
    )


def default_reality(city: str = "Beijing") -> SimpleNamespace:
    """用 reality/ 下的三个抓取模块 + clock 组装 RealityProtocol 实现。

    网络失败时这三个模块自身返回 None/[]，这里不额外兜底。
    """
    from reality import weather, news, inbox as inbox_mod, clock

    return SimpleNamespace(
        city=city,
        get_weather=weather.get_weather,
        get_headlines=news.get_headlines,
        scan_inbox=inbox_mod.scan_inbox,
        today=clock.today,
        is_holiday=clock.is_holiday,
    )


# ============================================================
# 断点
# ============================================================

def _slot_snapshot(d: date, slot: str, day_plan: Optional[DayPlan]) -> dict[str, Any]:
    """每段结束时写入 checkpoint 的进度快照。

    day_plan 一并序列化存档：续跑时复用同一份 DayPlan，
    避免重新调导演导致跨进程事件不一致。
    """
    snap: dict[str, Any] = {
        "date": d.isoformat(),
        "slot": slot,                      # 刚跑完的槽位
        "next_slot": _next_slot(slot),     # 下次要恢复的槽位
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "status": "slot_done",
    }
    if day_plan is not None:
        snap["day_plan"] = json.loads(day_plan.model_dump_json())  # model_dump_json 能序列化 date
    return snap


def _next_slot(slot: str) -> Optional[str]:
    """当前槽位的下一个槽位；night 之后是 None（该日结束）。"""
    i = SLOTS.index(slot)
    return SLOTS[i + 1] if i + 1 < len(SLOTS) else None


def save_checkpoint(ctx: Any, d: date, slot: str,
                    day_plan: Optional[DayPlan] = None) -> None:
    """把进度写入 ctx.paths.checkpoint_file（data/checkpoints/state.json）。"""
    try:
        p: Path = ctx.paths.checkpoint_file
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(_slot_snapshot(d, slot, day_plan), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("checkpoint: 写入失败（不影响本段运行）: %s", exc)


def load_checkpoint(ctx: Any) -> Optional[dict[str, Any]]:
    """读取断点；文件不存在/损坏返回 None，并由调用方决定从哪继续。"""
    try:
        p: Path = ctx.paths.checkpoint_file
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("checkpoint: 读取失败，忽略旧断点: %s", exc)
        return None


# ============================================================
# 日记落盘
# ============================================================

def _append_diary(ctx: Any, entries: list[DiaryEntry]) -> None:
    """把本段日记条目以 utf-8 追加写入 data/diary/YYYY-MM-DD.md。"""
    if not entries:
        return
    diary_dir = Path(ctx.paths.diary_dir)
    diary_dir.mkdir(parents=True, exist_ok=True)
    d = entries[0].date
    path = diary_dir / f"{d.isoformat()}.md"
    lines: list[str] = []
    if not path.exists():  # 当日第一段：写日期标题
        lines.append(f"# {d.isoformat()}\n")
    for e in entries:
        tags = " ".join(f"#{t}" for t in e.emotion_tags)
        lines.append(
            f"\n## {e.slot} · 感动度 {e.poignancy}\n\n{e.text}\n"
            + (f"\n*{tags}*\n" if tags else "")
        )
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        log.error("diary: 追加 %s 失败: %s", path, exc)


# ============================================================
# 主循环
# ============================================================

def _reality_snapshot(ctx: Any) -> dict[str, Any]:
    """收集现实钩子：天气 / 新闻 / 收件箱消息。全部允许失败降级。"""
    snap: dict[str, Any] = {"weather": None, "headlines": [], "inbox": []}
    r = getattr(ctx, "reality", None)
    if r is None:
        return snap
    try:
        snap["weather"] = r.get_weather(getattr(r, "city", "Beijing"))
    except Exception as exc:  # 第三方实现可能不守约，兜一层
        log.warning("runner: 现实钩子 weather 异常: %s", exc)
    try:
        snap["headlines"] = r.get_headlines(5)
    except Exception as exc:
        log.warning("runner: 现实钩子 news 异常: %s", exc)
    try:
        snap["inbox"] = r.scan_inbox(getattr(ctx.paths, "inbox_dir", None))
    except Exception as exc:
        log.warning("runner: 现实钩子 inbox 异常: %s", exc)
    return snap


def run_day(d: date, ctx: Any, resume: bool = False) -> None:
    """推进一整天；resume=True 时若断点日期与本日一致则从断点后继续。"""
    start_slot = "morning"
    if resume:
        cp = load_checkpoint(ctx)
        if cp and cp.get("date") == d.isoformat():
            nxt = cp.get("next_slot")
            if nxt is None:
                log.info("runner: %s 已跑完（断点状态），跳过", d)
                return
            start_slot = nxt
            log.info("runner: 从断点恢复 %s，自 %s 续跑", d, nxt)
        elif cp:
            log.info("runner: 断点日期(%s)与待跑日期(%s)不一致，整日重跑",
                     cp.get("date"), d)

    # 当日一次性输入：现实快照 + 昨日摘要（来自上次夜间 reflect 的缓存）
    reality = _reality_snapshot(ctx)
    y_summary = _load_yesterday_summary(ctx, d)

    day_plan: Optional[DayPlan] = None
    for slot in SLOTS[SLOTS.index(start_slot):]:
        if day_plan is None:
            # 续跑时优先用 checkpoint 里存档的 DayPlan（保持事件一致）
            day_plan = _restore_day_plan(ctx, d)
            if day_plan is None:
                # 非续跑或存档损坏：现调导演；首段失败则本日直接放弃
                day_plan = _make_day_plan(ctx, d, reality, y_summary)
            if day_plan is None:
                log.error("runner: %s 导演产出 DayPlan 失败，本日中止", d)
                return

        seg_events = [e for e in day_plan.events if e.slot == slot]
        run_slot(d, slot, seg_events, ctx, reality, y_summary)

        if slot == "night":
            # 夜间：先反思收尾，再打"整日完成"的 checkpoint
            _night_reflection(ctx, d)
            _backup_db(ctx, d)
            _mark_day_done(ctx, d)
        else:
            save_checkpoint(ctx, d, slot, day_plan)


def _restore_day_plan(ctx: Any, d: date) -> Optional[DayPlan]:
    """从断点文件恢复 DayPlan（仅当断点日期一致且内容合法）。"""
    cp = load_checkpoint(ctx)
    if not cp or cp.get("date") != d.isoformat() or "day_plan" not in cp:
        return None
    try:
        plan = DayPlan.model_validate(cp["day_plan"])
        if plan.date != d:
            log.warning("runner: 存档 DayPlan 日期不符，弃用")
            return None
        log.info("runner: 已从断点恢复 DayPlan（%d 个事件）", len(plan.events))
        return plan
    except Exception as exc:  # pydantic 校验失败等
        log.warning("runner: 断点中的 DayPlan 损坏，改由导演重新生成: %s", exc)
        return None


def _mark_day_done(ctx: Any, d: date) -> None:
    """整日（含反思）跑完后把断点置为完成态，避免 resume 时重复跑。"""
    try:
        p: Path = ctx.paths.checkpoint_file
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "date": d.isoformat(), "slot": "night", "next_slot": None,
            "status": "day_done",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("checkpoint: 标记整日完成失败: %s", exc)


def run_slot(
    d: date,
    slot: str,
    events: list[Any],
    ctx: Any,
    reality: Optional[dict[str, Any]] = None,
    yesterday_summary: Optional[str] = None,
) -> tuple[list[DiaryEntry], list[DecisionResult]]:
    """推进单个槽位（也可被外部单独调用做细粒度测试）。"""
    reality = reality or {"weather": None, "headlines": [], "inbox": []}

    # ---- 1) 记忆检索：用本段事件文本作为查询 ----
    memory_hits: list[Any] = []
    query = " ".join(e.content for e in events)
    if query and ctx.memory is not None:
        try:
            memory_hits = ctx.memory.retrieve(query, k=5)
        except Exception as exc:
            log.warning("runner: 记忆检索失败，空检索继续: %s", exc)

    # ---- 2) 组装导演上下文并补段内细节（事件已由 DayPlan 提供）----
    director_ctx: dict[str, Any] = {
        "slot": slot,
        "date": d.isoformat(),
        "events": [e.model_dump() for e in events],
        "reality": reality,
        "yesterday": yesterday_summary,
    }
    # 现实事件注入：有熟人消息 → 作为 reality 事件追加给主角
    for msg in reality.get("inbox", []):
        events.append(Event(
            slot=slot, kind="reality", location="现实世界",
            actors=[msg.get("sender", "熟人")],
            content=f"收到熟人来信：{msg.get('text', '')}",
            detail=f"when={msg.get('when')}", intensity=4,
            decision_point=True,
        ))

    # ---- 3) 主角反应 ----
    persona_text = getattr(ctx, "persona_text", "") or ""
    entries: list[DiaryEntry] = []
    decisions: list[DecisionResult] = []
    try:
        entries, decisions = ctx.protagonist.react(events, memory_hits, persona_text, slot_hint=slot)
    except Exception as exc:
        log.error("runner: 主角 react 异常（%s/%s）：本段跳过", d, slot, exc)
        return [], []

    # ---- 4) 日记落盘（utf-8 追加）----
    _append_diary(ctx, entries)

    # ---- 5) 决策写回：选择结算进状态，决策本身入记忆（阶段2-2）----
    if decisions:
        _apply_decisions(ctx, d, decisions)

    log.info("runner: %s %s 完成，日记 %d 条、决策 %d 个",
             d, slot, len(entries), len(decisions))
    return entries, decisions


def _apply_decisions(ctx: Any, d: date, decisions: list[Any]) -> None:
    """把主角的决策写回世界：状态微调（心情按选择性质）+ 决策入记忆库。

    状态持有者在 ctx.state_holder（集成者提供，main.StateHolder）；
    没有该字段时静默跳过，保持 runner 对旧 ctx 的向后兼容。
    """
    holder = getattr(ctx, "state_holder", None)
    if holder is None:
        return
    try:
        for dec in decisions:
            reason = getattr(dec, "inner_reason", "") or ""
            choice = getattr(dec, "choice", "") or ""
            # 心情微调：主动介入的选择通常更有掌控感
            mood_delta = 2 if ("介入" in choice or "主动" in choice or "去" in choice) else 0
            holder.state.mood = max(-100, min(100, holder.state.mood + mood_delta))
            # 决策入记忆：kind=thought，内心理由是人格素材
            ctx.memory.add_event(
                "thought",
                f"我决定：{choice}（关于：{getattr(dec, 'question', '')[:40]}）。因为 {reason[:80]}",
                when=datetime.combine(d, datetime.now().time()),
                importance=5.0 if mood_delta else 4.0,
            )
        log.info("runner: %s 决策写回 %d 条", d, len(decisions))
    except Exception as exc:
        log.warning("runner: 决策写回失败（不影响主流程）: %s", exc)


def _make_day_plan(
    ctx: Any, d: date, reality: dict[str, Any], y_summary: Optional[str]
) -> Optional[DayPlan]:
    """调导演产出 DayPlan；失败返回 None。"""
    try:
        return ctx.director.make_day_plan(
            d, {"reality": reality, "yesterday": y_summary}
        )
    except Exception as exc:
        log.error("runner: director.make_day_plan 异常: %s", exc)
        return None


def _night_reflection(ctx: Any, d: date) -> None:
    """夜间收尾：读取当天日记 → memory.reflect → 缓存为昨日摘要。"""
    try:
        diary_path = Path(ctx.paths.diary_dir) / f"{d.isoformat()}.md"
        day_text = ""
        if diary_path.exists():
            day_text = diary_path.read_text(encoding="utf-8", errors="replace")
        # 反思输入也可以直接用当日 DiaryEntry 列表——但落盘后已有 md，
        # 用文件内容最简单稳妥（集成者也可在 reflect 里自行读库）。
        reflection = ctx.memory.reflect([]) if not day_text else \
            ctx.memory.reflect(_load_entries_from_md(day_text, d))
        _save_yesterday_summary(ctx, d, reflection)
    except Exception as exc:
        log.error("runner: 夜间反思失败（%s）：跳过摘要缓存", exc)


def _load_entries_from_md(md_text: str, d: date) -> list[DiaryEntry]:
    """把当日 markdown 反解为 DiaryEntry 列表（尽力而为，供 reflect 用）。"""
    entries: list[DiaryEntry] = []
    slot = "morning"
    text_parts: list[str] = []
    for line in md_text.splitlines():
        if line.startswith("## "):
            if text_parts:
                entries.append(DiaryEntry(date=d, slot=slot,  # type: ignore[arg-type]
                                          text="\n".join(text_parts).strip()))
                text_parts = []
            head = line[3:].split("·")[0].strip()
            slot = head if head in SLOTS else "morning"
        elif not line.startswith("# ") and line.strip():
            text_parts.append(line)
    if text_parts:
        entries.append(DiaryEntry(date=d, slot=slot,  # type: ignore[arg-type]
                                  text="\n".join(text_parts).strip()))
    return entries


def _summary_file(ctx: Any) -> Path:
    return Path(ctx.paths.checkpoint_file).parent / "yesterday_summary.json"


def _load_yesterday_summary(ctx: Any, d: date) -> Optional[str]:
    """读昨日摘要缓存；仅当缓存日期是 d 的前一天时才有效，否则返回 None。"""
    try:
        f = _summary_file(ctx)
        if not f.is_file():
            return None
        data = json.loads(f.read_text(encoding="utf-8"))
        yesterday = (d - timedelta(days=1)).isoformat()
        return data.get("summary") if data.get("date") == yesterday else None
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("runner: 昨日摘要缓存读取失败: %s", exc)
        return None


def _save_yesterday_summary(ctx: Any, d: date, summary: str) -> None:
    """把 reflect 结果缓存为"昨日摘要"（date=反思日 d），供 d+1 各段输入使用。"""
    try:
        f = _summary_file(ctx)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(
            {"date": d.isoformat(), "summary": summary,
             "saved_at": datetime.now().isoformat(timespec="seconds")},
            ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError as exc:
        log.warning("runner: 昨日摘要缓存写入失败: %s", exc)


def _backup_db(ctx: Any, d: date) -> None:
    """每日反思结束后把 SQLite 备份到 data/backups/YYYY-MM-DD.db。"""
    try:
        src = Path(ctx.paths.db)
        if not src.is_file():
            log.info("runner: 数据库 %s 不存在，跳过备份", src)
            return
        backup_dir = Path(ctx.paths.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest = backup_dir / f"{d.isoformat()}.db"
        # SQLite 在线备份的标准做法（比文件复制更安全，避免拷到半写状态）
        with sqlite3.connect(str(src)) as sconn, \
                sqlite3.connect(str(dest)) as dconn:
            sconn.backup(dconn)
        log.info("runner: 数据库已备份到 %s", dest)
    except (OSError, sqlite3.Error) as exc:
        log.warning("runner: 数据库备份失败: %s", exc)
