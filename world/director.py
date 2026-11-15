"""导演层：调用 LLM 生成一天的事件（无骰子、无概率抽取），并对产出做禁用过滤与物理校验。

输入输出约定：
- Director.plan_day(...) -> DayPlan：主入口。给定当天日期、骨架、主角状态、近 30 天编年史摘要、
  伏笔表、NPC 列表、禁用清单（近 14 天已用桥段要素）与可选现实钩子，返回通过物理层校验的一天计划。
- Director.maybe_update_hidden(today) -> bool：每 7 天一次，让 LLM 推进世界隐变量（dict[str, str]）。
- 隐变量只允许以"迹象"形式泄漏进事件 content（prompt 立规矩 + 代码扫描双保险），不允许直接明说。

生成策略：一次让 LLM 交 3 个候选方案（每个都是完整 Event[]），代码侧用字符 3-gram 重叠度
挑与近期历史最不相似的一个；命中禁用清单打回重生成；物理校验失败重试，最多 2 次。
温度默认 1.0（高温要创意）。LLM 走 OpenAI 兼容 /chat/completions，base_url 默认
http://127.0.0.1:11434/v1（本地 ollama），仅用标准库 urllib，不引入第三方 HTTP 依赖。
"""
from __future__ import annotations

import json

try:
    from world import json_repair as _json_repair
except ImportError:
    import json_repair as _json_repair
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

try:  # 作为包的一部分被导入时走相对导入
    from ..contracts import DayPlan, Decision, Event, Foreshadow, NpcState, ProtagonistState
    from . import physics
except ImportError:  # 直接运行 world/ 下模块时，把所需目录加进 sys.path
    _HERE = str(Path(__file__).resolve().parent)
    _PARENT = str(Path(_HERE).parent)
    for _p in (_PARENT, _HERE):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    from contracts import DayPlan, Decision, Event, Foreshadow, NpcState, ProtagonistState
    import physics


# ---------- 薄 LLM 封装（OpenAI 兼容接口） ----------

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "qwen3:32b"


class LLMClient:
    """OpenAI 兼容 /chat/completions 的薄封装，只用标准库。"""

    def __init__(self, base_url: str = "", model: str = "", api_key: str = "", timeout: float = 180.0):
        self.base_url = (base_url or os.environ.get("VIRTUALLIFE_LLM_BASE_URL", "")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("VIRTUALLIFE_LLM_MODEL", "") or DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("VIRTUALLIFE_LLM_API_KEY", "") or "ollama"
        self.timeout = timeout

    def chat(self, system: str, user: str, temperature: float = 1.0,
             max_tokens: int = 4096, retries: int = 3) -> str:
        """返回助手回复文本；网络/响应异常时重试 retries 次，最终失败抛 RuntimeError。"""
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
            method="POST",
        )
        last_err: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"].get("content") or ""
                if not content.strip():
                    # 网关偶发返回空 content（GLM reasoning 吃满预算/网关抽风）→ 视为失败重试
                    raise RuntimeError("empty content")
                return content
            except urllib.error.HTTPError as err:
                last_err = err
                # 429 限流：退避后重试（外层 plan_day 还有自己的重试循环）
                if err.code == 429 and attempt < retries:
                    time.sleep(20.0 * (attempt + 1))
                    continue
                if attempt < retries:
                    time.sleep(1.5)
            except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, OSError) as err:
                last_err = err
                if attempt < retries:
                    time.sleep(1.5)
        raise RuntimeError(
            "LLM 调用失败（base_url=%s model=%s）: %s" % (self.base_url, self.model, last_err)
        )


# ---------- LLM 输出的 JSON 提取 ----------

def _extract_json_array(text: str) -> list | dict:
    """从回复里抠出第一个完整 JSON 数组或对象（兼容 ```json 围栏与前后闲话）。"""
    fence = re.search(r"```(?:json)?\s*(\[.*\]|\{.*\})\s*```", text, re.S)
    src = fence.group(1) if fence else text
    # 优先找数组起点；找不到再找对象起点（兼容 {"candidates": ...} 包装）
    start = src.find("[")
    obj_start = src.find("{")
    if obj_start != -1 and (start == -1 or obj_start < start):
        start = obj_start
        opener, closer, dict_mode = "{", "}", True
    else:
        if start == -1:
            raise ValueError("LLM 回复中找不到 JSON 数组")
        opener, closer, dict_mode = "[", "]", False
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
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return json.loads(src[start:i + 1])
    raise ValueError("LLM 回复中 JSON 未闭合")


# ---------- 候选去重：字符 n-gram 重叠度（不依赖向量库） ----------

def _ngrams(text: str, n: int = 3) -> set:
    text = re.sub(r"\s+", "", text)
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def _similarity(candidate_text: str, history_text: str) -> float:
    """Jaccard：候选与历史的 3-gram 集合交并比。"""
    a, b = _ngrams(candidate_text), _ngrams(history_text)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def pick_most_novel(candidates: list, history_text: str) -> int:
    """返回与近 30 天编年史重叠度最低的候选下标。候选内取与历史最相似的单事件作为该候选分数
    （最坏情况匹配，避免一个候选里夹带一段高度复读的旧桥段）。"""
    best_i, best_s = 0, float("inf")
    for i, cand in enumerate(candidates):
        try:
            cand_texts = [json.dumps(ev, ensure_ascii=False) for ev in cand]
        except (TypeError, ValueError):
            cand_texts = [str(cand)]
        s = max((_similarity(t, history_text) for t in cand_texts), default=0.0)
        if s < best_s:
            best_i, best_s = i, s
    return best_i


# ---------- 禁用清单扫描 ----------

def hit_banned(plan_events: list, banned: list[str]) -> list[str]:
    """返回候选命中的禁用要素列表（空=通过）。子串匹配 content+detail+actors。"""
    hits: list[str] = []
    for item in banned:
        if not item:
            continue
        for ev in plan_events:
            hay = "%s %s %s" % (ev.get("content", ""), ev.get("detail", ""),
                                " ".join(ev.get("actors", []) or []))
            if item in hay:
                hits.append(item)
                break
    return hits


# 隐变量键名的同义词组：LLM 擅长换皮改写（跳槽→离职/换工作/找下家），
# 精确匹配必被击穿。这里维护常见暗线主题的同义词簇，任一同义词出现在事件里即判泄密。
_LEAK_SYNONYMS: dict[str, tuple[str, ...]] = {
    "跳槽": ("离职", "换工作", "找下家", "新公司", "面试", "辞职", "Offer", "offer", "简历"),
    "离婚": ("分开", "搬出去", "离婚", "感情破裂", "冷战中"),
    "暗恋": ("喜欢", "心动", "表白", "情书"),
    "怀孕": ("有喜", "怀孕", "宝宝", "产检"),
    "生病": ("确诊", "住院", "化疗", "复查", "病历"),
    "失业": ("被裁", "裁员", "下岗", "n+1", "N+1"),
    "搬家": ("搬家", "退租", "新房东", "搬走"),
}


def leaked_hidden_terms(events: list, hidden_state: dict,
                        synonym_map: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """泄密扫描 v2：键名精确匹配 + 同义词簇检测。

    同义词簇支持两层扩展：
    1. 内置 _LEAK_SYNONYMS（常见暗线主题）；
    2. hidden_state 值本身含括号补充词（如 "跳槽（ synonym: 离职,换工作 "）——不支持；
       而是由 maybe_update_hidden 在推进隐变量时调 LLM 生成 synonyms 存入
       hidden_synonyms.json，与本表合并。"""
    syn_map = dict(_LEAK_SYNONYMS)
    if synonym_map:
        syn_map.update(synonym_map)
    hits: list[str] = []
    for key in hidden_state:
        # 该键名的检测词集：键名自身 + 已知同义词簇 + 值里的关键词
        terms = {key}
        for theme, words in syn_map.items():
            if theme in key or key in theme or any(w and w in key for w in words):
                terms.update(words)
        val = str(hidden_state.get(key, ""))
        terms.update(w for w in val.replace("，", ",").split(",") if len(w) >= 2 and w != key)
        def _fuzzy_hit(term: str, content: str) -> bool:
            """容错子串匹配：LLM 会插量词（换工作→换个工作）。
            策略：检测词的 2-gram 窗口 ≥60% 出现且语义核（末 2-gram）命中。"""
            if term in content:
                return True
            if len(term) < 3:
                return False
            wins = [term[i:i + 2] for i in range(len(term) - 1)]
            hits_n = sum(1 for w in wins if w in content)
            return hits_n / len(wins) >= 0.5 and (wins[-1] in content or wins[0] in content)

        for ev in events:
            content = ev.get("content", "") + ev.get("detail", "")
            if any(t and _fuzzy_hit(t, content) for t in terms):
                hits.append(key)
                break
    return hits


# ---------- 拼进 prompt 的上下文 ----------

class PlanContext(BaseModel):
    chronicle: str = ""                        # 近 30 天编年史摘要（调用方拼好传入）
    foreshadows: list[Foreshadow] = Field(default_factory=list)
    npcs: list[NpcState] = Field(default_factory=list)
    reality_hooks: str = ""                    # 天气/新闻，可为空
    banned_elements: list[str] = Field(default_factory=list)  # 近 14 天已用桥段要素
    free_slots: list[str] = Field(default_factory=list)       # 当天空槽
    fixed_slots: list[str] = Field(default_factory=list)      # 当天固定槽
    money: int = 0
    mood: int = 0
    energy: int = 0
    location: str = ""
    low_mood_lock: bool = False                # 昨天 mood<-50 的情绪锁

# ---------- 导演主体 ----------

class Director:
    """导演：维护世界隐变量，产出经物理层校验的 DayPlan。

    温度固定 1.0；一次要 3 个候选挑最不相似的；命中禁用清单打回重生成一次（下一轮 attempt）；
    物理校验失败把原因喂回给 LLM 重试，最多 2 次重试（共 3 次尝试）。全部失败抛 RuntimeError，
    不静默降级、不伪造事件。
    """

    def __init__(self, llm: Optional[LLMClient] = None,
                 hidden_state: Optional[dict] = None):
        self.llm = llm or LLMClient()
        self.hidden_state: dict[str, str] = dict(hidden_state or {})

    # ----- 世界隐变量 -----

    def maybe_update_hidden(self, today: date) -> bool:
        """每 7 天允许推进一次隐变量（用天序数对 7 取模判定）。返回是否真的更新了。
        推进失败不阻塞当天规划，只返回 False。"""
        if self.hidden_state and today.toordinal() % 7 != 0:
            return False
        sys_p = (
            "你在维护一个模拟世界的隐藏设定（读者不可直接看见的暗线）。\n"
            "每条隐变量是一句话，例如：\"小李在偷偷准备跳槽\"。\n"
            "规则：\n"
            "1. 已有隐变量只能缓慢演化或保持，不能一夜反转；也可以新增一条。\n"
            "2. 输出 JSON：{\"hidden\": {\"短名\": \"一句话描述\"}}，输出完整表。\n"
            "3. 只输出 JSON，不要任何多余文字。\n"
        )
        user_p = (
            "当前隐变量：" +
            (json.dumps(self.hidden_state, ensure_ascii=False) if self.hidden_state else "（空，请新增一条）") +
            "\n今天：" + today.isoformat() + "。请推进或新增。"
        )
        try:
            raw = self.llm.chat(sys_p, user_p, temperature=0.9, max_tokens=512)
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                return False
            data = json.loads(match.group(0))
            hidden = data.get("hidden")
            if not isinstance(hidden, dict) or not hidden:
                return False
            self.hidden_state = {str(k): str(v) for k, v in hidden.items() if k and v}
            return True
        except (RuntimeError, ValueError, json.JSONDecodeError):
            return False

    def _hidden_prompt_block(self) -> str:
        if not self.hidden_state:
            return "世界暗线：（当前无）"
        lines = "\n".join("- %s：%s" % (k, v) for k, v in self.hidden_state.items())
        return (
            "世界暗线（只有你知道；绝不允许在事件 content 里直接明说，"
            "只允许以迹象/侧面细节泄漏。例如不能写\"小李在偷偷跳槽\"，"
            "只能写\"小李午休躲在天台打电话，看见你来立刻挂断\"）：\n" + lines
        )

    # ----- prompt 构造 -----

    def _system_prompt(self, ctx: PlanContext, ban_feedback: str) -> str:
        return (
            "你是一部单机养成模拟世界的导演。主角是一个由经历沉淀出人格的普通人。\n"
            "你的职责：为今天编出 3 个候选的\"一天事件方案\"，每个方案都是完整的事件列表。\n\n"
            "铁律（违反任何一条即作废）：\n"
            "1.【伏笔优先】事件主来源是伏笔表：先判断哪些伏笔到了\"戏剧时机\"（紧急度高、打开久、"
            "到期提示临近、与编年史里的旧事有呼应），让事件从它们身上长出来；"
            "只有伏笔表确实无事可做时，才允许现编日常事件。兑现伏笔时把对应 id 写进 "
            "foreshadow_tags。\n"
            "2.【无骰子】禁止随机数、概率、掷骰设定；事件要有因果与余波，与编年史衔接。\n"
            "3.【3 个候选】一次输出 3 个彼此明显不同的完整方案。"
            "输出格式是 JSON 数组套 JSON 数组：[[事件,...],[事件,...],[事件,...]]。\n"
            "4.【禁用清单】近 14 天已用桥段要素：" +
            ("、".join(ctx.banned_elements) if ctx.banned_elements else "（无）") +
            "。任何候选的内容/细节/人物命中这些词即算重复，禁止使用。\n"
            "5.【暗线保密】" + self._hidden_prompt_block() + "\n"
            "6.【只输出 JSON】不要解释性文字。\n"
        )

    def _user_prompt(self, ctx: PlanContext, ban_feedback: str) -> str:
        fs_table = "\n".join(
            "- [%s] %s（打开于 %s，紧急度 %d/5%s）" % (
                fs.id, fs.summary, fs.opened_on, fs.urgency,
                ("，到期提示：" + fs.expires_hint) if fs.expires_hint else "",
            )
            for fs in ctx.foreshadows
        ) or "（空：伏笔表确实无事可做，才允许现编日常事件）"
        npc_table = "\n".join(
            "- %s：关系值 %d；已知事实：%s；未兑现人情/承诺：%s；最近见面：%s" % (
                n.name, n.relationship,
                "；".join(n.facts) or "无",
                "；".join(n.pending_debts) or "无",
                n.last_seen or "很久",
            )
            for n in ctx.npcs
        ) or "（无 NPC）"
        mood_lock = (
            "【情绪锁】主角正处情绪低谷（mood<-50）：今天禁止任何无伏笔、无决策点的 "
            "intensity>=8 大喜事件；可以有温暖的小事，不允许凭空狂喜。"
            if ctx.low_mood_lock else ""
        )
        ban_fb = (
            "\n【上一稿被驳回，必须改】" + ban_feedback + "\n请彻底避开上述问题重写。"
            if ban_feedback else ""
        )
        reality = ctx.reality_hooks.strip() or "（无）"
        # 阶段3：时刻表注入 + 细节档位
        import config as _cfg
        from world.timetable import format_timetable
        lo, hi = _cfg.EVENTS_PER_SLOT.get(_cfg.DETAIL_LEVEL, (1, 2))
        return (
            "今天骨架：\n"
            "固定槽（已被上班等固定安排占用，不要往里塞事件）：%s\n"
            "自由空槽（只允许在这些槽里放事件）：%s\n"
            "当天时刻表：%s。事件发生在钟点之间，detail 开头注明钟点（如\"07:30 \"），让一天有流水账的时间感。\n"
            "事件数量：每个自由槽 %d-%d 个事件（含微事件：路上看到什么、午饭吃了什么、同事随口一句话），总计全天 %d 个左右。\n"
            "主角当前：money=%d 元，mood=%d，energy=%d，所在地=%s。\n"
            "%s\n\n"
            "近 30 天编年史摘要：\n%s\n\n"
            "伏笔表（事件主来源，优先从这里的戏剧时机长出事件）：\n%s\n\n"
            "NPC 状态：\n%s\n\n"
            "现实钩子（天气/新闻，可选用作 reality 类事件）：\n%s\n"
            "%s\n"
            "每个事件对象的字段：\n"
            '- "slot"："morning"|"afternoon"|"evening"|"night" 之一，只能用上面的自由空槽；\n'
            '- "detail"：细节填槽（具体物/话/天气/金额），涉及花钱要写明"X元"；开头写钟点（如"07:30 "）对应当天时刻表；\n'
            '- "kind"："routine"|"incidental"|"major"|"reality" 之一；\n'
            '- "location"：必须从下面这份合法地点清单中选："家"、"公司"、"小区"、"便利店"、"超市"、"公园"、"医院"、"地铁站"（清单之外的地点会被驳回）；\n'
            '- "actors"：NPC 名列表（可含"你"），没有则空数组；\n'
            '- "content"：发生了什么，1-3 句；与暗线有关时只能用迹象暗示；\n'
            '- "intensity"：1-10 整数；major 建议 7+，routine 建议 1-3；\n'
            '- "decision_point"：布尔，是否留决策点给主角；\n'
            '- "foreshadow_tags"：本事件兑现或推进的伏笔 id 数组，没有则空数组。\n'
            % (
                "、".join(ctx.fixed_slots) or "无",
                "、".join(ctx.free_slots) or "无",
                format_timetable(),
                lo, hi, (hi - lo + 1) * max(1, len(ctx.free_slots)),
                ctx.money, ctx.mood, ctx.energy, ctx.location,
                mood_lock,
                ctx.chronicle or "（空白开局，无历史）",
                fs_table,
                npc_table,
                reality,
                ban_fb,
            )
        )

    # ----- 主流程 -----

    @staticmethod
    def _strip_monologue(raw: str) -> str:
        """剥掉模型混在 JSON 前后的思考独白，只留含 JSON 的部分。

        常见形态：先一大段"我来分析/要避开/先生成。"再跟正文（或压根没有正文）。
        策略：有代码围栏直接取围栏；否则从 JSON 起始符截取；
        没有任何 JSON 踪迹则原样返回（让上层报"找不到 JSON"触发重试）。
        """
        fence = re.search(r"```(?:json)?\s*(\[.*\]|\{.*\})\s*```", raw, re.S)
        if fence:
            return fence.group(0)
        starts = [i for i in (raw.find("["), raw.find("{")) if i != -1]
        if not starts:
            return raw
        start = min(starts)
        return raw if start < 60 else raw[start:]

    def plan_day(
        self,
        today: date,
        skeleton,                       # physics.Skeleton
        state: ProtagonistState,
        chronicle: str,
        foreshadows: list[Foreshadow],
        npcs: list[NpcState],
        banned_elements: list[str],
        reality_hooks: str = "",
    ) -> DayPlan:
        """生成今天的 DayPlan。流程：LLM 交 3 候选 → 挑与编年史最不相似的 →
        禁用清单过滤（命中打回重生成）→ 泄密扫描 → 物理层校验（失败带原因重试，最多 2 次）。
        全部尝试失败抛 RuntimeError。"""
        ctx = PlanContext(
            chronicle=chronicle,
            foreshadows=foreshadows,
            npcs=npcs,
            reality_hooks=reality_hooks,
            banned_elements=list(banned_elements),
            free_slots=skeleton.free_slots(),
            fixed_slots=skeleton.fixed_slots(),
            money=state.money,
            mood=state.mood,
            energy=state.energy,
            location=state.location,
            low_mood_lock=state.mood < -50,
        )

        ban_feedback = ""
        last_reason = ""
        for attempt in range(4):  # 初次 + 最多 3 次重试（4B 高温下独白/字段错率不低）
            raw = self.llm.chat(
                self._system_prompt(ctx, ban_feedback),
                self._user_prompt(ctx, ban_feedback),
                temperature=1.0,
                max_tokens=16000,   # GLM 系 reasoning 先吃几千 token，正文空间必须留足
            )
            # 4B 模型偶发把思考独白当输出（"先生成。"结尾）——剥掉 JSON 之外的独白
            raw = self._strip_monologue(raw)
            try:   # raw 留痕常开（排障命脉）；超 500KB 轮转
                _log_p = "data/raw_replies.log"
                if os.path.exists(_log_p) and os.path.getsize(_log_p) > 500_000:
                    os.replace(_log_p, _log_p + ".old")
                with open(_log_p, "a", encoding="utf-8") as _f:
                    _f.write("\n===== %s attempt %d =====\n%s\n" % (today, attempt, raw))
            except OSError:
                pass
            try:
                candidates = _json_repair.robust_parse(raw)
            except (ValueError, json.JSONDecodeError) as err:
                ban_feedback = last_reason = "输出不是合法 JSON：" + str(err)
                continue
            # 兼容 {"candidates": [[...],...]} / {"candidates": [...]} 等包装形态
            if candidates and isinstance(candidates, dict):
                for key in ("candidates", "plans", "方案", "data"):
                    if isinstance(candidates.get(key), list):
                        candidates = candidates[key]
                        break
            if candidates and all(isinstance(c, dict) for c in candidates):
                candidates = [candidates]          # 单对象 → 单候选方案
            # 4B 常见误读：把"3个候选"理解成"3个单事件方案"——每个候选只有 1 个事件。
            # 兜底：全部为单事件候选时合并成一个方案（比打回重试省一轮 LLM 调用）。
            if (candidates and len(candidates) > 1
                    and all(isinstance(c, list) and len(c) == 1 for c in candidates)):
                candidates = [sum(candidates, [])]
            # 同槽冲突兜底：候选内同一 slot 出现多次时只保留第一个（物理层会拒绝，先自愈）
            for ci, cand in enumerate(candidates):
                if isinstance(cand, list) and len(cand) > 1:
                    seen: set = set()
                    dedup = []
                    for ev in cand:
                        slot = ev.get("slot") if isinstance(ev, dict) else None
                        if slot and slot in seen:
                            continue
                        if slot:
                            seen.add(slot)
                        dedup.append(ev)
                    candidates[ci] = dedup
            if not candidates or not all(isinstance(c, list) for c in candidates):
                ban_feedback = last_reason = "候选方案结构不对：应为 [[事件...],[事件...],[事件...]]"
                continue

            # 挑与近 30 天历史最不相似的候选
            chosen = candidates[pick_most_novel(candidates, chronicle)]
            try:
                events = [Event.model_validate(ev) for ev in chosen]
            except ValidationError as err:
                ban_feedback = last_reason = "事件字段不合法：" + str(err)
                continue

            # 禁用清单：命中打回重生成一次（初次尝试命中时打回；重试稿仍命中则按物理校验继续走）
            hits = hit_banned([ev.model_dump() for ev in events], ctx.banned_elements)
            if hits and attempt == 0:
                ban_feedback = last_reason = "命中近 14 天已用桥段要素：" + "、".join(hits)
                continue

            # 隐变量泄密扫描：键名不允许原样出现
            leaks = leaked_hidden_terms(
                [ev.model_dump() for ev in events], self.hidden_state
            )
            if leaks:
                ban_feedback = last_reason = (
                    "暗线泄密：以下词不允许直接出现在事件里，只能用迹象暗示：" + "、".join(leaks)
                )
                continue

            # 物理层校验
            reasons = physics.validate_events(events, state, skeleton)
            if reasons:
                last_reason = "；".join(reasons)
                ban_feedback = "物理规则不合法：" + last_reason
                continue

            plan = DayPlan(date=today, events=events)
            plan.decisions = [
                (
                    "ev-%d" % i,
                    Decision(
                        question="关于「%s」你打算怎么做？" % ev.content[:30],
                        options=["顺其自然", "主动介入"],
                    ),
                )
                for i, ev in enumerate(events) if ev.decision_point
            ]
            return plan

        raise RuntimeError(
            "导演连续 3 次未能生成合法 DayPlan，最后一次原因：" + (last_reason or ban_feedback or "未知")
        )
