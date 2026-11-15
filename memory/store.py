"""跨会话持久记忆库：SQLite 单文件 + 向量检索 + 反思。

移植自 GA-CN associate.py 的检索公式（相似度×新近度×重要度），改为单主角持久化。
embedding 走 OpenAI 兼容 /embeddings；失败时自动降级为字符 n-gram 相似度。
"""
from __future__ import annotations

import json
import re
import sqlite3
import struct
import time
from datetime import date, datetime

from openai import OpenAI

import os as _os
_os.environ["NO_PROXY"] = "127.0.0.1,localhost"
_os.environ["no_proxy"] = "127.0.0.1,localhost"

import config
from memory.forgetting import retention as _retention, blur_text as _blur


# ---------- 相似度 ----------

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (na * nb)


def _ngram_sim(a: str, b: str, n: int = 2) -> float:
    """降级用：字符 bigram Jaccard。"""
    sa = {a[i:i + n] for i in range(max(0, len(a) - n + 1))}
    sb = {b[i:i + n] for i in range(max(0, len(b) - n + 1))}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """中文 bigram BM25：无需分词器，够用。"""
    q_terms = {query[i:i+2] for i in range(max(0, len(query) - 1))} or {query}
    doc_terms = [{d[i:i+2] for i in range(max(0, len(d) - 1))} for d in docs]
    avgdl = sum(len(d) for d in docs) / max(1, len(docs))
    n_docs = len(docs)
    scores = []
    for terms, d in zip(doc_terms, docs):
        score = 0.0
        for qt in q_terms:
            tf = sum(1 for _ in range(len(d)) if d.startswith(qt, _)) // max(1, len(qt))
            if tf == 0:
                continue
            df = sum(1 for t2 in doc_terms if qt in t2)
            idf = ((n_docs - df + 0.5) / (df + 0.5) + 1.0)
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avgdl))
        scores.append(score)
    return scores


def _rrf(vector_ranked: list[int], bm25_ranked: list[int], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion：两路检索结果融合。"""
    fused = {}
    for rank, idx in enumerate(vector_ranked):
        fused[idx] = fused.get(idx, 0) + 1 / (k + rank + 1)
    for rank, idx in enumerate(bm25_ranked):
        fused[idx] = fused.get(idx, 0) + 1 / (k + rank + 1)
    return fused


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


# ---------- 记忆库 ----------

class MemoryStore:
    def __init__(self, db_path=config.DB_PATH, embed_model: str | None = None):
        self.db_path = str(db_path)
        self.embed_model = embed_model or config.EMBED_MODEL or 'default'
        embed_url = getattr(config, "EMBED_BASE_URL", None)
        if not embed_url:
            import json as _json, os as _os
            lp = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "config_local.json")
            if _os.path.exists(lp):
                local = _json.load(open(lp, encoding="utf-8"))
                embed_url = local.get("embed_base_url")
        self._client = OpenAI(base_url=embed_url or "http://127.0.0.1:11434/v1",
                              api_key=config.API_KEY or "none")
        self._embed_ok = True          # 首次失败后置 False，本次会话内不再试
        self._init_db()

    def _init_db(self) -> None:
        con = self._con()
        con.execute("""CREATE TABLE IF NOT EXISTS nodes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,            -- event/thought/chat
            text TEXT NOT NULL,
            ts REAL NOT NULL,              -- unix ts
            importance REAL DEFAULT 3.0,   -- 1-10
            poignancy REAL DEFAULT 0,      -- 0-150
            access_count INTEGER DEFAULT 0,
            last_access REAL DEFAULT 0,
            mem_key INTEGER DEFAULT 0,     -- 关键性 0-3（遗忘曲线分级）
            vec BLOB)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_nodes_ts ON nodes(ts)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_nodes_key ON nodes(mem_key)")
        con.commit()
        con.close()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    # ---- embedding ----

    def _embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self._embed_ok:
            return None
        try:
            resp = self._client.embeddings.create(model=self.embed_model, input=texts)
            return [d.embedding for d in resp.data]
        except Exception:
            self._embed_ok = False
            return None

    # ---- 写 ----

    def add(self, kind: str, text: str, when: datetime | None = None,
            importance: float = 3.0, poignancy: float = 0.0,
            key: int = 0) -> int:
        when = when or datetime.now()
        vecs = self._embed([text])
        con = self._con()
        cur = con.execute(
            "INSERT INTO nodes(kind,text,ts,importance,poignancy,mem_key,vec) VALUES(?,?,?,?,?,?,?)",
            (kind, text, when.timestamp(), importance, poignancy, key,
             _pack(vecs[0]) if vecs else None))
        con.commit()
        nid = cur.lastrowid
        con.close()
        return nid

    # ---- 读 ----

    CANDIDATE_CAP = 400          # 候选集上限：SQL 预过滤后的行数（浮点计算只跑这些）

    def _candidate_sql(self) -> str:
        """候选集查询：热记忆（90 天内）全收 + 关键记忆不限时 + 随机采样冷记忆。
        用 SQL 把全量扫描压到常数规模——浮点运算只跑候选，不跑全库。"""
        return (
            "SELECT id,kind,text,ts,importance,poignancy,access_count,mem_key,vec FROM nodes "
            "WHERE ts >= :hot_cut "                       # 热窗：90 天
            "   OR mem_key >= 2 "                          # 关键记忆（含 L2/L3 蒸馏）永久可检索
            "   OR id IN (SELECT id FROM nodes WHERE mem_key <= 1 AND ts < :hot_cut "
            "             ORDER BY RANDOM() LIMIT :cold_sample) "  # 冷记忆随机抽样 60 条（做梦/旧事偶然想起）
            " LIMIT :cap"
        )

    def retrieve(self, query: str, top_k: int = 8,
                 now_ts: float | None = None) -> list[tuple[dict, float]]:
        """返回 [(node_dict, score)]，score = 相似度 × 新近度 × 重要度。
        性能：SQL 预过滤候选集（热窗+关键+冷抽样），Python 浮点只跑候选。"""
        now_ts = now_ts or time.time()
        hot_cut = now_ts - 90 * 86400
        con = self._con()
        rows = con.execute(self._candidate_sql(), {
            "hot_cut": hot_cut, "cold_sample": 60, "cap": self.CANDIDATE_CAP}).fetchall()
        con.close()
        if not rows:
            return []
        qvec = self._embed([query])
        qvec = qvec[0] if qvec else None

        # 双路检索：向量（语义）+ BM25（关键词），RRF 融合
        vec_scores = []
        bm25_scores = []
        for (nid, kind, text, when, imp, poig, acc, mkey, vec_blob) in rows:
            sim_v = _cosine(qvec, _unpack(vec_blob)) if (qvec and vec_blob) else _ngram_sim(query, text)
            vec_scores.append(sim_v)
        all_texts = [r[2] for r in rows]
        bm25_scores = _bm25_scores(query, all_texts)
        vec_order = sorted(range(len(rows)), key=lambda i: vec_scores[i], reverse=True)
        bm25_order = sorted(range(len(rows)), key=lambda i: bm25_scores[i], reverse=True)
        fused = _rrf(vec_order, bm25_order)
        fused_score = fused  # idx -> rrf 分

        scored = []
        for idx, (nid, kind, text, when, imp, poig, acc, mkey, vec_blob) in enumerate(rows):
            age_days = max(0.0, (now_ts - when) / 86400)
            recency = 0.995 ** age_days
            importance = (imp / 10.0) * (1.0 + 0.05 * acc)
            ret = _retention(age_days, mkey or 0)
            score = fused_score.get(idx, 0) * recency * importance * (0.2 + 0.8 * ret)
            if ret < 0.35 and mkey is not None and mkey <= 1:
                text = _blur(text, max(0.25, ret / 0.7))
            scored.append(({"id": nid, "kind": kind, "text": text,
                            "when": datetime.fromtimestamp(when),
                            "importance": imp, "poignancy": poig,
                            "retention": ret}, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = [(n, sc) for (n, sc) in scored[:top_k] if n["retention"] >= 0.1]

        # 命中即更新访问记录
        con = self._con()
        for node, _ in top:
            con.execute("UPDATE nodes SET access_count=access_count+1, last_access=? WHERE id=?",
                        (now_ts, node["id"]))
        con.commit()
        con.close()
        return top

    def recent(self, days: float = 1.0) -> list[dict]:
        """取最近 N 天的节点（反思与编年史用）。"""
        cutoff = time.time() - days * 86400
        con = self._con()
        rows = con.execute(
            "SELECT id,kind,text,ts,importance,poignancy FROM nodes WHERE ts>=? ORDER BY ts",
            (cutoff,)).fetchall()
        con.close()
        return [{"id": r[0], "kind": r[1], "text": r[2],
                 "when": datetime.fromtimestamp(r[3]), "importance": r[4],
                 "poignancy": r[5]} for r in rows]

    # ---- 反思（GA-CN reflect 的单主角改写） ----

    REFLECT_SYSTEM = """你是小澄。下面是你最近经历的事和想法。请把它们蒸馏成 3-5 条「对自己的新认识」或「对某个人/事的新看法」。
要求：第一人称；是更高一层的概括而不是复述；每条注明它基于哪些源事件（引用编号）。只输出 JSON：
{"thoughts": [{"text": "...", "evidence": [1,3], "importance": 1-10}]}"""

    def reflect(self, llm_chat) -> list[dict]:
        """llm_chat(user, system)->str。产物写回库（kind=thought），返回给调用方展示。"""
        nodes = self.recent(days=1.0)
        if not nodes:
            return []
        listing = "\n".join(f"{n['id']}. [{n['kind']}] {n['text']}" for n in nodes)
        raw = llm_chat(listing, self.REFLECT_SYSTEM)
        data = _parse_json(raw)
        out = []
        for t in data.get("thoughts", []):
            text = (t.get("text") or "").strip()
            # 过滤占位/空转产物：太短或纯标点（4B 模型偶发输出 "..." 混进 thoughts）
            if len(text) < 10 or re.fullmatch(r"[\W_.。…]+", text):
                continue
            nid = self.add("thought", text, importance=float(t.get("importance", 5)))
            out.append({"id": nid, "text": text, "evidence": t.get("evidence", [])})
        return out


def _parse_json(text: str) -> dict:
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return {}
