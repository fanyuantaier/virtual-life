"""Flask 服务器：网页聊天 + 状态查看。

路由：
    GET  /          聊天页面
    POST /api/chat  发消息给囡囡
    GET  /api/stats  当前人生状态
    GET  /api/diary  最近日记

用法：python web/server.py  →  http://127.0.0.1:5000
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json as _json
from flask import Flask, jsonify, request, send_from_directory

import config

app = Flask(__name__, static_folder="static", static_url_path="/static")


def _chat_once(user_msg: str, history: list[dict]) -> str:
    from chat import chat_once
    return chat_once(user_msg, history)


@app.route("/dashboard")
def dashboard_page():
    return send_from_directory(str(Path(__file__).resolve().parent), "dashboard.html")


@app.route("/")
def index():
    return send_from_directory(str(Path(__file__).resolve().parent), "chat.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True)
    msg = (data.get("message") or "").strip()
    history = data.get("history") or []
    if not msg:
        return jsonify({"error": "empty"}), 400
    try:
        reply = _chat_once(msg, history)
        return jsonify({"reply": reply})
    except Exception as exc:
        return jsonify({"error": str(exc)[:120]}), 500


@app.route("/api/stats")
def api_stats():
    import sqlite3
    from life import LifeSim
    sim = LifeSim(42)
    con = sqlite3.connect(str(sim.db_path))
    n, = con.execute("SELECT COUNT(*) FROM nodes").fetchone()
    kinds = dict(con.execute("SELECT kind, COUNT(*) FROM nodes GROUP BY kind").fetchall())
    last_ts, = con.execute("SELECT MAX(ts) FROM nodes").fetchone()
    con.close()
    import pathlib
    diary_days = len(list((config.DATA_DIR / "diary_life" / "adult").glob("*.md")))
    dreams = len(list((config.DATA_DIR / "diary_life" / "dreams").glob("*.md")))
    last_when = datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M") if last_ts else "-"
    # 年龄按重映射锚点（出生 2008-11-04）对真实时钟计算
    age_years = round((datetime.now().date() - date(2008, 11, 4)).days / 365.25, 1)
    return jsonify({
        "name": "沈青蔓（囡囡）",
        "age_years": age_years,
        "memory_total": n,
        "memory_kinds": kinds,
        "diary_days": diary_days,
        "dreams": dreams,
        "last_memory_at": last_when,
    })


@app.route("/timeline")
def timeline_page():
    return send_from_directory(str(Path(__file__).resolve().parent), "timeline.html")


@app.route("/api/timeline")
def api_timeline():
    """按年龄分组的人生时间轴：事件/梦/人格画像。"""
    import sqlite3
    from life import LifeSim
    sim = LifeSim(42)
    con = sqlite3.connect(str(sim.db_path))
    # 出生锚定 2008-11-04（时间轴重映射后的真实锚点），不用 generate_birth 的 today()
    from datetime import date as _date
    b = _date(2008, 11, 4)
    rows = con.execute(
        "SELECT text, ts, kind FROM nodes WHERE kind IN ('event','dream','persona','scene') "
        "ORDER BY ts").fetchall()
    con.close()
    timeline = {}
    for text, ts, kind in rows:
        dt = datetime.fromtimestamp(ts)
        age = max(0, round((dt.date() - b).days / 365.25, 1))
        yk = f"age{int(age)}"
        # 显示"X岁M月"而非日历日期——模拟时间线的日历日期（2039-2044）对用户无意义
        total_days = max(0, (dt.date() - b).days)
        years = int(age)
        months = int((total_days - years * 365.25) / 30.4)
        when_label = f"{years}岁{months}个月" if months else f"{years}岁整"
        timeline.setdefault(yk, []).append({
            "age": age, "when": when_label, "kind": kind, "text": text[:160]
        })
    # 排序输出
    out = [{"age": int(k[3:]), "items": v} for k, v in sorted(timeline.items(), key=lambda x: int(x[0][3:]))]
    return jsonify(out)


@app.route("/api/godhand", methods=["POST"])
def api_godhand():
    """上帝之手：写入干预，下次导演生成时必须消化。"""
    data = request.get_json(force=True)
    text = (data.get("intervention") or "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400
    gd = Path(config.DATA_DIR) / "godhand"
    gd.mkdir(parents=True, exist_ok=True)
    # 追加到待处理干预队列（文件制，adult.py 生成计划时读取并清空）
    queue = gd / "pending.json"
    items = []
    if queue.exists():
        try:
            items = _json.loads(queue.read_text(encoding="utf-8"))
        except Exception:
            items = []
    items.append({"text": text, "at": datetime.now().isoformat(timespec="seconds")})
    queue.write_text(_json.dumps(items[-20:], ensure_ascii=False, indent=1), encoding="utf-8")
    return jsonify({"ok": True, "queued": len(items)})


@app.route("/api/godhand/list")
def api_godhand_list():
    gd = Path(config.DATA_DIR) / "godhand"
    queue = gd / "pending.json"
    items = []
    if queue.exists():
        try:
            items = _json.loads(queue.read_text(encoding="utf-8"))
        except Exception:
            items = []
    return jsonify(items)


@app.route("/api/harness/run", methods=["POST"])
def api_harness_run():
    """触发一轮 harness 训练（同步执行，max 档一次约 2.5 小时）。"""
    from harness.runner import run as harness_run
    d = request.get_json(force=True) if request.data else {}
    profile = d.get("profile", "burst")
    days = int(d.get("days", 0))
    import threading
    result_holder = {}

    def _run():
        try:
            result_holder["report"] = harness_run(profile, backfill_days=days)
        except Exception as exc:
            result_holder["error"] = str(exc)[:200]

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": f"{profile} 训练已在后台启动",
                    "note": "训练完成查看 logs/harness_*.json"})


@app.route("/api/memory/search")
def api_memory_search():
    """记忆全文检索（混合检索）。"""
    from life import LifeSim
    q = request.args.get("q", "")
    k = int(request.args.get("k", 10))
    if not q:
        return jsonify([])
    try:
        sim = LifeSim(42)
        hits = sim.store().retrieve(q, top_k=k)
        return jsonify([{"text": n["text"], "kind": n["kind"],
                         "when": n["when"].strftime("%Y-%m-%d"),
                         "retention": round(n.get("retention", 1.0), 2)} for n, _ in hits])
    except Exception as exc:
        return jsonify({"error": str(exc)[:150]}), 500


@app.route("/api/config")
def api_config_get():
    """当前配置（mask api_key）。"""
    from llm import _local_cfg
    cfg = _local_cfg()
    if "api_key" in cfg and cfg["api_key"]:
        cfg["api_key"] = "***"
    import config as _c
    cfg["embed_url"] = cfg.get("embed_base_url") or getattr(_c, "EMBED_BASE_URL", "")
    cfg["embed_model"] = cfg.get("embed_model") or getattr(_c, "EMBED_MODEL", "")
    return jsonify(cfg)


@app.route("/api/config", methods=["POST"])
def api_config_set():
    """保存配置到 config_local.json（重启 web/loop 生效）。"""
    from llm import _local_cfg
    d = request.get_json(force=True)
    cfg = _local_cfg()
    for k in ["llm_base_url", "llm_model", "api_key", "embed_base_url", "embed_model"]:
        if k in d:
            cfg[k] = d[k].strip() if isinstance(d[k], str) else d[k]
    Path(__file__).resolve().parent.joinpath("config_local.json").write_text(_json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return jsonify({"ok": True, "note": "已保存。重启 adult loop / web server 后生效。"})


@app.route("/api/process")
def api_process():
    """引擎进程状态。"""
    import subprocess
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*adult.py*' "
        "-or $_.CommandLine -like '*harness*' -or $_.CommandLine -like '*burn*'} | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json"],
        capture_output=True, text=True)
    procs = []
    try:
        raw = json.loads(r.stdout) if r.stdout.strip() else []
        if isinstance(raw, dict):
            raw = [raw]
        for x in raw:
            cl = x.get("CommandLine", "")
            kind = "adult-loop" if "adult.py" in cl else ("harness" if "harness" in cl else "burn")
            procs.append({"pid": x["ProcessId"], "kind": kind})
    except Exception:
        pass
    return jsonify({"processes": procs})


@app.route("/api/profiles")
def api_profiles():
    from engine.multiuser import list_all
    return jsonify(list_all())


@app.route("/api/profiles/create", methods=["POST"])
def api_profiles_create():
    from engine.multiuser import create_from_template
    d = request.get_json(force=True)
    try:
        root = create_from_template(
            d.get("profile_id"), d.get("template", "fiction"),
            d.get("name"), d.get("nickname", ""),
            city=d.get("city", ""), family_type=d.get("family_type", ""),
            temperament=d.get("temperament", []))
        return jsonify({"ok": True, "profile_id": root.name})
    except FileExistsError:
        return jsonify({"error": "exists"}), 409


@app.route("/api/profiles/export/<pid>")
def api_profiles_export(pid):
    from engine.multiuser import export_profile
    from flask import send_file
    zp = export_profile(pid)
    return send_file(str(zp), as_attachment=True)


@app.route("/api/profiles/delete/<pid>", methods=["POST"])
def api_profiles_delete(pid):
    from engine.multiuser import delete_profile
    data = request.get_json(force=True) if request.data else {}
    n = delete_profile(pid, keep_backup=data.get("keep_backup", True))
    return jsonify({"deleted_memories": n})


@app.route("/moments")
def moments_page():
    return send_from_directory(str(Path(__file__).resolve().parent), "moments.html")


@app.route("/api/intimacy")
def api_intimacy():
    import relation as rel_mod
    rel = rel_mod.load_relation()
    days = (date.today() - date.fromisoformat(rel["since"])).days
    return jsonify({"label": rel_mod.intimacy_label(rel["rounds"]),
                    "days": days, "rounds": rel["rounds"], "way": rel["way"]})


@app.route("/api/moments")
def api_moments():
    """她的朋友圈：从最近事件里挑可分享的（感动度≥10，非隐私）。"""
    import sqlite3
    from life import LifeSim
    sim = LifeSim(42)
    con = sqlite3.connect(str(sim.db_path))
    rows = con.execute(
        "SELECT text, ts, importance FROM nodes WHERE kind='event' "
        "AND importance >= 5 ORDER BY ts DESC LIMIT 20").fetchall()
    con.close()
    out = [{"when": datetime.fromtimestamp(ts).strftime("%m-%d %H:%M"),
            "text": t.split("，", 1)[-1][:100],
            "mood": p} for t, ts, p in rows]
    return jsonify(out[:10])


@app.route("/api/diary")
def api_diary():
    """最近 7 天日记标题+正文摘要。"""
    import json as _json
    out = []
    d_dir = Path(config.DATA_DIR) / "diary_life" / "adult"
    files = sorted(d_dir.glob("*.md"), reverse=True)[:7]
    for f in files:
        out.append({"date": f.stem, "text": f.read_text(encoding="utf-8")})
    return jsonify(out)


def main() -> None:
    port = 5100
    print(f"=== 囡囡对话网页启动: http://127.0.0.1:{port} ===")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
