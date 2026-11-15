"""现实新闻模块：抓取 RSS 头条，供世界引擎的"现实钩子"使用。

- 无 API key，xml.etree.ElementTree 解析 RSS 2.0 / Atom。
- 缓存 6 小时；超时或解析失败一律返回 [] 并记 log，不抛异常。

默认源选 BBC 中文 + 路透中文等无 key 的公开 RSS；调用方可通过
get_headlines(feeds=[...]) 覆盖。网络优先 httpx，回退 urllib。
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

log = logging.getLogger(__name__)

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

import urllib.request

_CACHE_TTL = 6 * 3600.0  # 6 小时
_TIMEOUT = 10.0

# 默认 RSS 源（无 key、公开）。元素标题即可当头条。
DEFAULT_FEEDS: tuple[str, ...] = (
    "http://www.people.com.cn/rss/politics.xml",   # 人民网·时政（2026-11-01 实测可用）
    "https://sspai.com/feed",                      # 少数派
    "https://www.douban.com/feed/review/book",     # 豆瓣书评
)

# RSS/Atom 里常见的命名空间，strip 后统一按 item/title 走
_TAG_RE = re.compile(r"\{[^}]+\}")

_cache: dict[str, tuple[float, list[str]]] = {}  # feed_url -> (抓取时刻, 标题列表)


def _fetch_text(url: str) -> Optional[str]:
    """拉取 RSS 原文；任何失败返回 None。"""
    try:
        if httpx is not None:
            resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (rss-reader)"})
            resp.raise_for_status()
            return resp.text
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (rss-reader)"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:
        log.warning("news: 抓取 RSS 失败 (%s): %s", url, exc)
        return None


def _parse_headlines(xml_text: str, limit: int) -> list[str]:
    """从 RSS/Atom XML 里抽标题；解析失败返回 []。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("news: RSS XML 解析失败: %s", exc)
        return []
    titles: list[str] = []
    # RSS 2.0: channel/item/title；Atom: feed/entry/title
    for item in list(root.iter("item")) + list(root.iter("entry")):
        t = item.findtext("title")
        if t:
            t = _TAG_RE.sub("", t).strip()  # 保险：万一 findtext 未去 ns（不会，但防御）
            t = re.sub(r"\s+", " ", t)
            if t:
                titles.append(t)
        if len(titles) >= limit:
            break
    return titles


def get_headlines(n: int = 5, feeds: Optional[list[str]] = None) -> list[str]:
    """获取前 n 条头条标题；失败返回 []。

    feeds 不传则用 DEFAULT_FEEDS；缓存 6 小时（按源列表整体缓存）。
    """
    if n <= 0:
        return []
    sources = tuple(feeds) if feeds else DEFAULT_FEEDS
    key = "|".join(sources)
    now_ts = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and now_ts - hit[0] < _CACHE_TTL and hit[1]:
        return hit[1][:n]

    headlines: list[str] = []
    for url in sources:
        text = _fetch_text(url)
        if text:
            headlines.extend(_parse_headlines(text, n))
        if len(headlines) >= n:
            break
    headlines = headlines[:n]
    if not headlines:
        log.warning("news: 所有 RSS 源均不可用，返回空列表")
        return []
    _cache[key] = (now_ts, list(headlines))
    return headlines
