"""导演 LLM 回复的多层容错解析。

四层防线（按序）：
1. 双通道：原文 → 全局反转义（模型把 \" 写成 \\" 的混用）；
2. 深度扫描：找第一个完整 JSON，括号失衡时补齐重试；
3. 逐字符暴力回退（截断修复）：输出被 max_tokens 切断时，从右向左在每个
   结构字符（}/]）处尝试截断+补齐——保证 JSON 前缀有解必达；
4. 全部失败抛 ValueError，由导演层喂回重试。
"""
from __future__ import annotations

import json


def robust_parse(raw: str):
    last_err = None
    for src in (raw, raw.replace('\\"', '"')):
        start = src.find("[")
        if start == -1:
            continue
        # A. 正常深度扫描
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(src)):
            ch = src[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    frag = src[start:i + 1]
                    opens = frag.count("[") + frag.count("{") - frag.count("]") - frag.count("}")
                    for pad in ("", "]" * max(0, opens)):
                        try:
                            return json.loads(frag + pad)
                        except json.JSONDecodeError as e:
                            last_err = e
                    break
        # B. 截断修复：从右向左在每个 } 或 ] 后截断+补齐
        i = len(src) - 1
        while i > start + 5:
            if src[i] in ("}", "]"):
                frag = src[start:i + 1]
                opens = frag.count("[") + frag.count("{") - frag.count("]") - frag.count("}")
                for pad in ("]" * max(0, opens), "]" * max(0, opens - 1)):
                    try:
                        return json.loads(frag + pad)
                    except json.JSONDecodeError as e:
                        last_err = e
            i -= 1
    raise ValueError("无法解析（截断回退失败）：" + str(last_err))
