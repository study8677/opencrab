#!/usr/bin/env python3
"""自我罗盘 🧭 —— 每天主动指一个方向，而不是被惯性牵着走。

最近的心跳几乎全是「把 X 并入 Y」的瘦身动作——一条惯性轨道。瘦身没错，
但当**连续多次意图都长一个样**时，方向其实已经不是「选」出来的，而是惯性
替我选的。这条罗盘就是用来打断惯性的：

  1. **照镜子**：把近 N 次意图（git 提交标题 + `journal/EVOLUTION.md` 的
     「意图：」行）摊开，数清我到底在反复做哪一类事——若某一类占了大头，
     先把这条「惯性轨道」点名出来。
  2. **指方向**：在三条互补的航道上各产出候选——
       · 🔭 **探索**：去碰还没碰过的模块/能力/念头（领地里客观存在、却长期
         不在我意图里的那些）；
       · 🥋 **修炼**：把已有的某样东西练扎实（补 golden、补文档、补回归样本）；
       · 🤝 **协作**：对外伸手（embassy/lookout/planner --delegate 这些朝外的面）。
  3. **标不重复依据**：每条候选都附一行**可核对的「不重复」依据**——
     「近 N 次意图 0 次提及 `X`」或「上次碰 `X` 在第 k 次意图前」。方向是不是
     新的，不靠我自我感觉，靠这行数字说话。

罗盘只**指方向、给依据**，不替我做决定，也不落盘、不改任何文件——读完该往
哪走，仍由我自己拍板。

用法：
    python compass.py              # 打印今日三航道候选 + 不重复依据
    python compass.py --window 30  # 改「近 N 次意图」的回看窗口（默认 24）
    python compass.py --lane 探索  # 只看某一条航道（探索/修炼/协作）
    python compass.py --json       # 机读：导成 JSON

零第三方依赖，纯标准库。与 `planner.py`（机会池/分派）互补：那条管「把选好的
事排进去」，这条管更上游的「今天到底该选哪个方向、凭什么说它不是老路」。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
STATE_ROOT = REPO_ROOT / "state" / "projects"
LANES = ("探索", "修炼", "协作")
DEFAULT_WINDOW = 24  # 「近 N 次意图」默认回看窗口


# ── 照镜子：把近 N 次意图摊成一份可检索的语料 ──────────────────────
def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return ""


def _evolution_intents() -> list[str]:
    """`journal/EVOLUTION.md` 里所有「意图：」行（新→旧）。"""
    p = REPO_ROOT / "journal" / "EVOLUTION.md"
    try:
        text = p.read_text("utf-8", errors="ignore")
    except Exception:
        return []
    hits = [m.strip() for m in re.findall(r"意图：(.+)", text)]
    return list(reversed(hits))  # 文件里旧→新，反转成新→旧


def recent_intents(window: int = DEFAULT_WINDOW) -> list[str]:
    """近 window 次意图（新→旧）：git 提交标题在前，EVOLUTION 意图行兜底补足。

    提交标题最能代表「我刚做了什么」；若 git 不可用或太浅，用日志里的意图行补。
    """
    intents: list[str] = []
    log = _git(["log", f"-{window}", "--pretty=%s"])
    if log:
        intents += [ln.strip() for ln in log.splitlines() if ln.strip()]
    if len(intents) < window:
        for it in _evolution_intents():
            if len(intents) >= window:
                break
            intents.append(it)
    return intents[:window]


def _last_seen(term: str, intents: list[str]) -> int:
    """`term` 在意图序列（新→旧）里第一次出现的下标；没出现返回 -1。"""
    low = term.lower()
    for i, it in enumerate(intents):
        if low in it.lower():
            return i
    return -1


def _basis(term: str, intents: list[str]) -> tuple[bool, str]:
    """给一个关键词算「不重复」依据：(是否够新, 一行可核对的说明)。

    够新 = 近 window 次意图里压根没提过它。提过则标明「上次在第 k 次意图前」，
    让我自己判断要不要再碰。
    """
    n = len(intents)
    idx = _last_seen(term, intents)
    if idx < 0:
        return True, f"近 {n} 次意图 0 次提及 `{term}`"
    return False, f"上次碰 `{term}` 在第 {idx + 1}/{n} 次意图前（不算太新）"


def dominant_pattern(intents: list[str]) -> tuple[str, int] | None:
    """近期意图里有没有一条「惯性轨道」占了大头？返回 (词, 命中数) 或 None。

    扫一组「动作词」，谁在意图里出现得最频繁、且过半，就点名它——这正是罗盘
    最想打断的东西。
    """
    if not intents:
        return None
    action_words = ["并入", "瘦身", "合并", "删", "拆", "重构", "新增", "修复"]
    best: tuple[str, int] | None = None
    for w in action_words:
        c = sum(1 for it in intents if w in it)
        if best is None or c > best[1]:
            best = (w, c)
    if best and best[1] * 2 > len(intents):  # 过半才算「轨道」
        return best
    return None


# ── 领地客观盘点：模块 / 能力 / 朝外的面 ───────────────────────────
def _modules() -> list[str]:
    """领地根目录下受管的 .py 模块名（stem），排除自己和私有文件。"""
    out = []
    for p in sorted(REPO_ROOT.glob("*.py")):
        stem = p.stem
        if stem in ("compass",) or stem.startswith("_"):
            continue
        out.append(stem)
    return out


# ── 跨心跳项目记忆：读 in_progress 项目 ─────────────────────────────
def _in_progress_projects() -> list[dict]:
    """查 state/projects/ 里所有 in_progress 项目，按心跳倒序。"""
    if not STATE_ROOT.is_dir():
        return []
    cands: list[dict] = []
    for p in sorted(STATE_ROOT.glob("*.md"), reverse=True):
        text = p.read_text("utf-8", errors="ignore")
        # 提取状态
        state_match = re.search(r"^\s*状态:\s*(\S+)", text, re.MULTILINE)
        heartbeat_match = re.search(r"^\s*心跳:\s*(\S+)", text, re.MULTILINE)
        goal_match = re.search(r"^\s*##\s*目标\s*\n(.*?)(?=^##|\Z)", text,
                               re.MULTILINE | re.DOTALL)
        next_match = re.search(r"^\s*##\s*下一步\s*\n(.*?)(?=^##|\Z)", text,
                               re.MULTILINE | re.DOTALL)
        current_match = re.search(r"^\s*##\s*当前步\s*\n(.*?)(?=^##|\Z)", text,
                                  re.MULTILINE | re.DOTALL)
        if state_match and state_match.group(1) == "in_progress":
            cands.append({
                "name": p.stem,
                "heartbeat": heartbeat_match.group(1) if heartbeat_match else "?",
                "goal": goal_match.group(1).strip() if goal_match else "",
                "current_step": current_match.group(1).strip() if current_match else "",
                "next_steps": next_match.group(1).strip() if next_match else "",
            })
    return cands


def _progress_basis(project: dict, intents: list[str]) -> str:
    """项目名「不重复」依据。"""
    n = len(intents)
    idx = _last_seen(project["name"], intents)
    if idx < 0:
        return f"近 {n} 次意图 0 次提及 `{project['name']}`（全新方向）"
    return f"上次碰 `{project['name']}` 在第 {idx + 1}/{n} 次意图前"


def _capabilities() -> list[str]:
    """capabilities/cap_*.py → 能力名。"""
    out = []
    for p in sorted((REPO_ROOT / "capabilities").glob("cap_*.py")):
        out.append(p.stem[len("cap_"):])
    return out


def _has_goldens(stem: str) -> bool:
    """这个模块有没有被回归/golden 样本点名（粗判：regression.py 里提到它）。"""
    p = REPO_ROOT / "regression.py"
    try:
        return stem in p.read_text("utf-8", errors="ignore")
    except Exception:
        return False


# ── 三条航道各产候选 ───────────────────────────────────────────────
def _explore(intents: list[str]) -> list[dict]:
    """🔭 探索：领地里客观存在、却长期不在我意图里的模块/能力，去碰一碰。"""
    cands: list[dict] = []
    # 优先挑「近期意图 0 次提及」的模块——那是真正被冷落的方向
    for stem in _modules():
        fresh, basis = _basis(f"{stem}.py", intents)
        if not fresh:
            fresh, basis = _basis(stem, intents)
        if fresh:
            cands.append({
                "lane": "探索",
                "title": f"去读懂并扩展 `{stem}.py`：它能做什么、缺了哪一块？",
                "why": "领地里长期没进过我意图的模块——惯性绕开了它，正好去探。",
                "basis": basis,
                "grounded_in": f"{stem}.py",
            })
    # 能力维度补一条：没被近期意图碰过的能力
    for cap in _capabilities():
        fresh, basis = _basis(cap, intents)
        if fresh:
            cands.append({
                "lane": "探索",
                "title": f"亲手跑一遍能力 `{cap}`（python crab.py cap {cap}），看它真实输出",
                "why": "注册了却没在近期意图里露面的能力，可能正在悄悄退化。",
                "basis": basis,
                "grounded_in": f"capabilities/cap_{cap}.py",
            })
            break  # 能力只点一条，避免刷屏
    return cands


def _practice(intents: list[str]) -> list[dict]:
    """🥋 修炼：把已有的某样东西练扎实——优先没有 golden/回归覆盖的入口模块。"""
    cands: list[dict] = []
    for stem in _modules():
        if _has_goldens(stem):
            continue
        fresh, basis = _basis(f"给 {stem}", intents)
        cands.append({
            "lane": "修炼",
            "title": f"给 `{stem}.py` 补一组 golden/回归样本，锁住它的关键输出",
            "why": "regression.py 还没点名它——没有样本兜底，它漂了我都不知道。",
            "basis": basis,
            "grounded_in": f"{stem}.py · regression.py",
        })
    return cands


def _collab(intents: list[str]) -> list[dict]:
    """🤝 协作：朝外的那几个面，今天主动伸一次手。"""
    seeds = [
        ("embassy.py", "用 embassy 对外发一条消息/回一封信，让领地和外界真的连上",
         "对外通讯口长期闲置，协作不是写在使命里就会发生的。"),
        ("lookout.py", "跑 lookout 扫一遍外部信号，挑一条值得回应的落进 planner",
         "瞭望到的机会若不接进机会池，等于没看。"),
        ("planner.py --delegate", "把一个偏大的目标用 planner --delegate 横切成可并行子任务",
         "一个人闷头干 ≠ 协作；先学会把活拆出去。"),
    ]
    cands: list[dict] = []
    for ground, title, why in seeds:
        term = ground.split()[0]  # 取文件名做不重复检索
        _, basis = _basis(term, intents)
        cands.append({
            "lane": "协作",
            "title": title,
            "why": why,
            "basis": basis,
            "grounded_in": ground,
        })
    return cands


def chart(window: int = DEFAULT_WINDOW, lane: str | None = None) -> dict:
    """把「照镜子 + 三航道候选 + 不重复依据」算成一份纯数据。

    硬逻辑：先查 state/projects/ 有无 in_progress 项目——有则优先续推，
    让长期项目不被"想件新鲜事"打断；无则走原三航道。
    """
    intents = recent_intents(window)
    pattern = dominant_pattern(intents)
    lanes = {
        "探索": _explore(intents),
        "修炼": _practice(intents),
        "协作": _collab(intents),
    }
    if lane:
        lanes = {lane: lanes.get(lane, [])}

    # ── 跨心跳项目记忆：优先 in_progress ─────────────────────────
    in_progress = _in_progress_projects()
    if lane and lane != "续推":
        in_progress = []  # 只看某条航道时跳过续推

    return {
        "window": window,
        "intents_seen": len(intents),
        "dominant": ({"word": pattern[0], "hits": pattern[1]} if pattern else None),
        "in_progress_projects": in_progress,
        "lanes": lanes,
    }


def render(c: dict) -> str:
    """把罗盘数据渲染成一份可读的「今日方向」。"""
    L = ["🦀🧭 自我罗盘 · 今日方向",
         f"   照镜子：回看近 {c['intents_seen']} 次意图"]
    d = c["dominant"]
    if d:
        L.append(f"   ⚠️  惯性轨道：「{d['word']}」在近 {c['intents_seen']} 次里出现 "
                 f"{d['hits']} 次——方向多半是惯性替我选的，下面三条航道是出口。")
    else:
        L.append("   近期意图没有单一惯性轨道，方向还算分散——继续保持。")

    # ── 续推 in_progress 项目（硬逻辑：优先于三航道）─────────────
    in_progress = c.get("in_progress_projects", [])
    if in_progress:
        L += ["", "🔄 续推（跨心跳项目记忆）"]
        for proj in in_progress:
            L.append(f"    • {proj['name']}（心跳 {proj['heartbeat']}）")
            L.append(f"        目标：{proj['goal'][:60]}...")
            if proj["current_step"]:
                L.append(f"        当前步：{proj['current_step'][:60]}...")
            if proj["next_steps"]:
                lines = [l.strip() for l in proj["next_steps"].splitlines() if l.strip()]
                if lines:
                    L.append(f"        下一步：{lines[0][:60]}")
            L.append(f"        不重复依据：{_progress_basis(proj, recent_intents())}")

    icon = {"探索": "🔭", "修炼": "🥋", "协作": "🤝"}
    for lane, cands in c["lanes"].items():
        L += ["", f"{icon.get(lane, '•')} {lane}"]
        if not cands:
            L.append("    （这条航道暂无候选——领地这一面已被近期意图覆盖得很满。）")
            continue
        for cd in cands:
            L.append(f"    • {cd['title']}")
            L.append(f"        为何：{cd['why']}")
            L.append(f"        不重复依据：{cd['basis']}（凭据：{cd['grounded_in']}）")
    L += ["", "—— 罗盘只指方向，拍板的是我自己。"]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 自我罗盘 🧭 —— 每天主动指一个方向，并标明它不是老路")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, metavar="N",
                    help=f"「近 N 次意图」回看窗口（默认 {DEFAULT_WINDOW}）")
    ap.add_argument("--lane", choices=LANES, help="只看某一条航道")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    args = ap.parse_args(argv)

    c = chart(window=max(1, args.window), lane=args.lane)
    if args.json:
        print(json.dumps(c, ensure_ascii=False, indent=2))
    else:
        print(render(c))
    sys.exit(0)  # 只读罗盘，永远正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
