"""全局配置：模型端点、路径、节奏参数。

模型端口留空——启动时由 start.py 引导填写，或直接改这里。
支持任何 OpenAI 兼容端点：Ollama / llama.cpp server / vLLM / 云 API。
"""
from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# ---------- 模型端点（必填，启动脚本会引导） ----------
# OpenAI 兼容 base_url，例如：
#   Ollama:      http://127.0.0.1:11434/v1
#   llama.cpp:   http://127.0.0.1:8080/v1
#   云 API:      https://api.deepseek.com/v1 等
LLM_BASE_URL = ""          # ← 留空：start.py 会引导填写
LLM_MODEL = ""             # ← 留空：start.py 会引导填写
API_KEY = ""               # 本地服务留空；云 API 填 key

# Embedding 端点（可留空 → 自动降级为字符 n-gram 相似度，功能完整但语义检索变弱）
EMBED_BASE_URL = ""        # 例如 http://127.0.0.1:11434/v1（Ollama）
EMBED_MODEL = ""           # 例如 nomic-embed-text / bge-m3

TEMPERATURE_DIRECTOR = 1.0        # 导演高温要创意
TEMPERATURE_PROTAGONIST = 0.7     # 主角低温保稳定

CITY = "Hangzhou"                 # 主角所在城市（决定现实天气锚定）
NEWS_FEEDS = [                    # RSS 源（无 key，可自行增删）
    "http://www.people.com.cn/rss/politics.xml",
    "https://sspai.com/feed",
    "https://www.douban.com/feed/review/book",
]

# ---------- 节奏参数 ----------
TIME_SCALE = 1.0                  # 1.0=实时；2.0=一天快 2 倍；仅 daemon.py 用
DETAIL_LEVEL = "rich"             # sparse / normal / rich（成人逐日模式的事件密度）
SLOTS = ("morning", "afternoon", "evening", "night")
EVENTS_PER_SLOT = {"sparse": (0, 1), "normal": (1, 2), "rich": (2, 3)}  # 每槽事件数区间
MAJOR_EVENT_MIN_GAP = 7
MAJOR_EVENT_MAX_GAP = 12
HOURLY_SLOTS = (
    ("07:00", "morning"), ("09:00", "morning"), ("12:00", "afternoon"),
    ("15:00", "afternoon"), ("18:00", "evening"), ("21:00", "evening"),
    ("23:00", "night"),
)

# ---------- 路径 ----------
DB_PATH = DATA_DIR / "life.db"          # 默认演示线（小澄）；囡囡线是 life_seed42.db
CHECKPOINT_PATH = DATA_DIR / "checkpoints" / "state.json"
DIARY_DIR = DATA_DIR / "diary"
BACKUP_DIR = DATA_DIR / "backups"
INBOX_DIR = DATA_DIR / "inbox"
PERSONA_PATH = BASE_DIR / "memory" / "self.md"

def _think_model() -> str:
    """当前主力模型名：LLM_MODEL → config_local.json → 兜底。"""
    import config as _c
    if getattr(_c, "LLM_MODEL", None):
        return _c.LLM_MODEL
    try:
        import json as _j2, os as _o2
        lp2 = _o2.path.join(_o2.path.dirname(_o2.path.abspath(__file__)), 'config_local.json')
        if _o2.path.exists(lp2):
            m = _j2.load(open(lp2, encoding='utf-8')).get('llm_model')
            if m:
                return m
    except Exception:
        pass
    try:
        import json as _j, os as _o
        lp = _o.path.join(_o.path.dirname(_o.path.abspath('config.py')), "config_local.json")
        if _o.path.exists(lp):
            return _j.load(open(lp, encoding="utf-8")).get("llm_model") or "default"
    except Exception:
        pass
    return "default"
