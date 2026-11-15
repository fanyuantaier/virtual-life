"""薄 LLM 封装：OpenAI 兼容 chat + embeddings，本地 Ollama / 远程 API 通吃。"""
from __future__ import annotations

import json

from openai import OpenAI

import json as _json
import os as _os


def _local_cfg() -> dict:
    """config_local.json（start.py 引导产物）。"""
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "config_local.json")
    if _os.path.exists(p):
        try:
            return _json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


import os as _os
# 本地网关必须绕过系统代理（NO_PROXY 里的 [::1] 会让 httpx 解析崩）
_os.environ["NO_PROXY"] = "127.0.0.1,localhost"
_os.environ["no_proxy"] = "127.0.0.1,localhost"

import config


class LLMClient:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, temperature: float = 0.7):
        self.model = model or config.LLM_MODEL or _local_cfg().get("llm_model") or "default"
        if base_url is None:
            base_url = config.LLM_BASE_URL or _local_cfg().get("llm_base_url")
        if base_url is None and not base_url:
            raise SystemExit("模型端点未配置。运行 python start.py 完成初始化，或编辑 config.py 填 LLM_BASE_URL / LLM_MODEL。")
        self.temperature = temperature
        self.client = OpenAI(
            base_url=base_url or config.LLM_BASE_URL,
            api_key=api_key or config.API_KEY or "none",
            timeout=180.0,        # 网关挂起时 3 分钟必须放弃
            max_retries=1,        # openai 库自带重试也要封顶
        )

    def chat(self, prompt: str, system: str = "", temperature: float | None = None) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature if temperature is None else temperature,
        )
        return resp.choices[0].message.content or ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=config.EMBED_MODEL, input=texts)
        return [d.embedding for d in resp.data]


def demo() -> None:
    """冒烟测试：python llm.py"""
    c = LLMClient()
    print(c.chat("用一句话回答：1+1=?"))
    print(len(c.embed(["测试"])[0]))


if __name__ == "__main__":
    demo()
