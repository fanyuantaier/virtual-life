"""现实天气模块：从 wttr.in 抓取天气，供世界引擎的"现实钩子"使用。

- 无 API key，直接 GET https://wttr.in/<city>?format=j1 解析 JSON。
- 缓存 1 小时（按城市名缓存）；超时或解析失败一律返回 None 并记 log，
  绝不向上抛异常——天气只是风味，不能打断主循环。

优先用 httpx（若已安装），否则回退标准库 urllib，两者行为一致。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

try:  # httpx 是可选的：装了就用它（超时控制更干净），没装走 urllib
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

import urllib.request

_CACHE_TTL = 3600.0  # 1 小时
_TIMEOUT = 10.0      # 单次请求超时（秒）
_cache: dict[str, tuple[float, dict[str, Any]]] = {}  # city -> (抓取时刻, 结果)


def _fetch_json(city: str) -> Optional[dict[str, Any]]:
    """请求 wttr.in 并返回解析后的 dict；任何失败返回 None。"""
    url = f"https://wttr.in/{city}?format=j1"
    try:
        if httpx is not None:
            resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True,
                             headers={"User-Agent": "curl/8.0"})
            resp.raise_for_status()
            return resp.json()
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # 网络/超时/JSON 全部吞掉
        log.warning("weather: 抓取 wttr.in 失败 (%s): %s", city, exc)
        return None


def get_weather(city: str) -> Optional[dict[str, Any]]:
    """查询某城市当前天气。

    返回 {"desc": str, "temp_c": float, "is_rain": bool}；失败或超时返回 None。
    结果按城市缓存 1 小时。
    """
    if not city:
        return None
    key = city.strip().lower()
    now_ts = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and now_ts - hit[0] < _CACHE_TTL:
        return dict(hit[1])

    data = _fetch_json(city)
    if not data:
        return None
    try:
        cur = data["current_condition"][0]
        desc = cur.get("lang_zh", [{}])[0].get("value") or \
            (cur.get("weatherDesc") or [{}])[0].get("value", "")
        temp_c = float(cur["temp_C"])
        # is_rain：当前天气码含雨字样，或近 3 小时降水量 > 0
        weather_code = (cur.get("weatherDesc") or [{}])[0].get("value", "").lower()
        precip = float(cur.get("precipMM", 0) or 0)
        is_rain = any(w in weather_code for w in ("rain", "drizzle", "shower", "雨")) \
            or precip > 0.0
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning("weather: wttr.in 返回结构异常 (%s): %s", city, exc)
        return None

    result = {"desc": str(desc), "temp_c": temp_c, "is_rain": bool(is_rain)}
    _cache[key] = (now_ts, dict(result))
    return result
