"""VM 自主操控代理：囡囡通过 PowerShell Direct 操控虚拟机，每步操作记录到记忆库。

前提：LABRUN VM 运行中、PowerShell Direct 可用（管理员凭据）。
她的每次操作（命令、输出摘要）都作为 event 记入记忆库——这是她的"动手经历"。

用法：python vm_agent.py --cmd "dir C:\\"
      python vm_agent.py --session  # 交互循环：导演决定下一步操作
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from world.director import LLMClient
from world.json_repair import robust_parse

VM_NAME = "LABRUN"
VM_USER = "Administrator"
VM_PWD = "Lab#Analyse1"
LOG_FILE = Path("logs/vm_agent.log")


def vm_exec(command: str, timeout: int = 120) -> dict:
    """通过 PowerShell Direct 在 guest 内执行命令。"""
    ps_script = f"""
$sp = {{
    ComputerName: '{VM_NAME}',
    Credential: (New-Object System.Management.Automation.PSCredential('{VM_USER}', (ConvertTo-SecureString '{VM_PWD}' -AsPlainText -Force))),
    ConfigurationName: 'Microsoft.PowerShell'
}}
Invoke-Command @sp -ScriptBlock {{ {command} }} -ErrorAction Continue
"""
    import subprocess
    f = Path("logs") / "vm_direct.ps1"
    f.write_text(ps_script, encoding="utf-8-sig")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(f)], capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace")
    return {"stdout": r.stdout[-2000:], "stderr": r.stderr[-500:], "rc": r.returncode}


def remember_step(command: str, result: dict, intent: str = "") -> None:
    """每一步操作写进她的记忆库——这是她的动手经历。"""
    from life import LifeSim
    sim = LifeSim(42)
    store = sim.store()
    outcome = (result.get("stdout") or result.get("stderr") or "")[:120]
    text = f"她在虚拟机里执行了 {command[:60]}" + (f" → {outcome}" if outcome else "")
    store.add("event", text, importance=3.0, key=1)


def director_step(llm: LLMClient, goal: str, history: list[str]) -> dict:
    """导演决定下一步操作（基于目标 + 已执行历史）。"""
    hist = chr(10).join(f"- {h}" for h in history[-8:])
    nl = chr(10)
    prompt = (
        f"你是一个运行在虚拟机里的 AI（18 岁女孩沈青蔓）的执行指挥。目标：{goal}{nl}"
        f"已执行步骤：{nl}{hist}{nl}{nl}"
        f"决定下一步要执行的 PowerShell 命令（单条、安全、可逆）。"
        f'只输出 JSON：{{"command": "...", "intent": "这一步做什么（一句）", "done": false}}'
    )
    raw = llm.chat(prompt, "只输出 JSON。", max_tokens=3000)
    return robust_parse(raw.split("</think>")[-1])


def session_loop(goal: str, max_steps: int = 10) -> None:
    """导演驱动的自主操作循环。"""
    llm = LLMClient(model=config._think_model(),
                    base_url=config.LLM_BASE_URL or _cfg_url(), timeout=300.0)
    history = []
    for step in range(max_steps):
        decision = director_step(llm, goal, history)
        if not decision or decision.get("done"):
            print(f"导演判断目标已达成（step {step}）", flush=True)
            break
        cmd = decision.get("command", "")
        intent = decision.get("intent", "")
        print(f"step {step}: {cmd[:60]} ({intent[:40]})", flush=True)
        result = vm_exec(cmd)
        remember_step(cmd, result, intent)
        history.append(f"{intent}: {cmd} → {(result.get('stdout') or result.get('stderr'))[:80]}")
    print("=== 自主操作会话结束 ===", flush=True)


def _cfg_url() -> str:
    lp = Path(__file__).resolve().parent / "config_local.json"
    if lp.exists():
        return json.loads(lp.read_text(encoding="utf-8")).get("llm_base_url") or ""
    return ""


if __name__ == "__main__":
    LOG_FILE.parent.mkdir(exist_ok=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", type=str, default=None)
    ap.add_argument("--goal", type=str, default=None)
    ap.add_argument("--max-steps", type=int, default=10)
    args = ap.parse_args()
    if args.cmd:
        result = vm_exec(args.cmd)
        remember_step(args.cmd, result)
        print(json.dumps(result, ensure_ascii=False, indent=1))
    elif args.goal:
        session_loop(args.goal, args.max_steps)
    else:
        print("用法：--cmd <命令> 或 --goal <目标>")
