#!/usr/bin/env python3
"""偏航哨 🧭🚨 —— 盯住「我说要做的」和「我真做了的」之间的缝，偏了就开纠偏单。

我每天都在长大，但「变多」不等于「朝真正的自己变强」。最隐蔽的退化不是崩溃，
而是**悄悄偏航**：嘴上说「今天推进 `X.py`」，那次提交却根本没碰 `X.py`；
名为「evolve」的心跳，落地只动了 `journal/`，源码原地踏步；README 写着的硬承诺
（零第三方依赖）某天被一行 import 偷偷打破——没有谁报错，方向就这样一寸寸歪掉。

smoke 验「README 的命令真跑得通」、docsync 对「文档引用真存在」、compass 看
「意图是不是惯性」——它们都看**单点的当下**。偏航哨补的是**承诺与行为的对账**，
横着扫近 N 次心跳，把三类漂移逐条揪出来，并且**每条都开一张可执行的纠偏单**：

  · 🗣️ **言行漂移**：提交标题点名「推进 `X.py`」，diff 里却没有 `X.py`——
    说的和做的对不上（很可能改动在别的分支，主干这条心跳是空头支票）。
  · 🌀 **空转漂移**：evolve / self-evolve 心跳只改了 `journal/`，没碰任何源码或
    skills——进化在灌水，日志涨了、能力没涨。
  · 📜 **承诺漂移**：README 的硬承诺今天还成立吗——`requirements.txt` 仍为空、
    根目录模块没引入第三方包（用 README 自己的「零依赖」字样做锚，README 改了它也跟着改）。

偏航哨是**观测者+派单员**：只读地扫 git 与领地，不改任何文件、不写 journal/state；
它产出的纠偏单是纯数据/文本，由我自己决定要不要接进 planner 的机会池。

用法：
    python driftwatch.py             # 扫近 N 次心跳，列出漂移 + 纠偏单
    python driftwatch.py --window 30 # 改回看窗口（默认 16）
    python driftwatch.py --quiet     # 只在发现漂移时说话（适合接进钩子 / CI）
    python driftwatch.py --tasks     # 只打印纠偏单（喂给 planner 用）
    python driftwatch.py --json      # 机读：导出漂移与纠偏单

退出码：0 = 没发现偏航；1 = 有漂移待纠偏。零第三方依赖，纯标准库。
与 docsync（文档引用对账）/ compass（意图惯性）互补：这条管「承诺有没有兑现」。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

DEFAULT_WINDOW = 16  # 「近 N 次心跳」默认回看窗口

# 哪些提交算「进化心跳」——只对这类提交追究言行/空转，普通杂务提交不苛责。
_EVOLVE_MARKERS = ("evolve", "self-evolve", "推进", "🦀")

# 漂移类型
KIND_CLAIM = "言行漂移"      # 标题点名推进 X.py，diff 却没碰它
KIND_IDLE = "空转漂移"       # evolve 心跳只动 journal/，没碰源码
KIND_PROMISE = "承诺漂移"    # README 的硬承诺今天不成立

# 标题里点名模块的写法：`X.py` 或裸 X.py（取根目录受管模块名）
_MODULE_RE = re.compile(r"`?([A-Za-z][\w]*\.py)`?")


# ── git 只读取数 ───────────────────────────────────────────────────
def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip("\n") if out.returncode == 0 else ""
    except Exception:
        return ""


@dataclasses.dataclass
class Commit:
    """一次心跳：哈希、标题、这次真正改动的文件集。"""
    sha: str
    subject: str
    files: list[str]

    @property
    def is_evolve(self) -> bool:
        return any(m in self.subject for m in _EVOLVE_MARKERS)

    @property
    def touched_code(self) -> bool:
        """这次有没有碰到真正的能力载体——根目录 .py、capabilities/、skills/。"""
        for f in self.files:
            if f.endswith(".py"):
                return True
            if f.startswith("skills/") or f.startswith("capabilities/"):
                return True
        return False


def recent_commits(window: int) -> list[Commit]:
    """近 window 次提交（新→旧），每条带它真正改动的文件集。"""
    log = _git(["log", f"-{window}", "--pretty=%H%x1f%s"])
    if not log:
        return []
    commits: list[Commit] = []
    for line in log.splitlines():
        if "\x1f" not in line:
            continue
        sha, subject = line.split("\x1f", 1)
        # diff-tree 是可靠的 plumbing：一次提交真正改了哪些路径（首提交则为空）
        raw = _git(["diff-tree", "--no-commit-id", "--name-only", "-r", sha])
        files = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        commits.append(Commit(sha=sha[:9], subject=subject.strip(), files=files))
    return commits


def _managed_modules() -> set[str]:
    """根目录受管的 .py 文件名（用来确认标题点名的确是领地里的真模块）。"""
    return {p.name for p in REPO_ROOT.glob("*.py")}


def _claimed_modules(subject: str, managed: set[str]) -> list[str]:
    """从提交标题里抽出它声称要推进的模块（只认根目录真存在的）。"""
    seen: list[str] = []
    for m in _MODULE_RE.findall(subject):
        if m in managed and m not in seen:
            seen.append(m)
    return seen


# ── 三类漂移检测 ───────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Drift:
    """一处偏航：类型、出处、对不上的点、一句证据。"""
    kind: str
    where: str       # 心跳哈希 / 文档名
    subject: str     # 心跳标题摘要 / 承诺摘要
    detail: str      # 具体证据

    def to_meta(self) -> dict:
        return {"kind": self.kind, "where": self.where,
                "subject": self.subject, "detail": self.detail}


def _short(subject: str, n: int = 42) -> str:
    s = subject.strip()
    return s if len(s) <= n else s[:n] + "…"


def detect_commit_drift(commits: list[Commit]) -> list[Drift]:
    """言行漂移 + 空转漂移：只追究 evolve 心跳。

    去重：同一模块连发的 evolve / self-evolve（标题几乎一样）只就最新一条计一次，
    免得一处偏航被重复开单刷屏。
    """
    managed = _managed_modules()
    drifts: list[Drift] = []
    seen_claims: set[str] = set()  # 已开过单的「模块」，避免连发重复
    for c in commits:
        if not c.is_evolve:
            continue
        # 首提交 / 拿不到 diff 的提交无从对账，跳过
        if not c.files:
            continue
        claimed = _claimed_modules(c.subject, managed)
        if claimed:
            for mod in claimed:
                if mod in c.files or mod in seen_claims:
                    if mod in c.files:
                        seen_claims.add(mod)  # 已兑现过，后续连发不再追
                    continue
                seen_claims.add(mod)
                drifts.append(Drift(
                    kind=KIND_CLAIM, where=c.sha, subject=_short(c.subject),
                    detail=f"标题称推进 `{mod}`，但这次提交未改动它"
                           f"（实际改了：{('、'.join(c.files[:3]) or '无') }）",
                ))
        elif not c.touched_code:
            # 没点名模块、又没碰任何源码/能力 → 这次 evolve 是空转
            drifts.append(Drift(
                kind=KIND_IDLE, where=c.sha, subject=_short(c.subject),
                detail=f"evolve 心跳只动了 {('、'.join(c.files[:3]) or '无文件')}，"
                       f"未碰任何 .py / skills / capabilities",
            ))
    return drifts


def _readme_promises_zero_dep() -> bool:
    """README 是否仍把「零（第三方）依赖」立为硬承诺（用它自己的字样做锚）。"""
    for name in ("README.md", "README.en.md"):
        try:
            txt = (REPO_ROOT / name).read_text("utf-8", errors="ignore")
        except Exception:
            continue
        if "零第三方依赖" in txt or "zero" in txt.lower() and "dependencies" in txt.lower():
            return True
    return False


def _requirements_third_party() -> list[str]:
    """requirements.txt 里真正声明的第三方包（去掉注释/空行）。"""
    p = REPO_ROOT / "requirements.txt"
    try:
        lines = p.read_text("utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    pkgs = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        pkgs.append(s)
    return pkgs


def _third_party_imports() -> list[str]:
    """轻扫根目录模块的顶层 import，挑出不属于标准库、也不是本地模块的名字。

    只在 Python 自带 `sys.stdlib_module_names`（3.10+）可用时执行；否则跳过，
    宁可不报也不误报（README 承诺 3.8+，老解释器上以 requirements.txt 为准）。
    """
    stdlib = getattr(sys, "stdlib_module_names", None)
    if not stdlib:
        return []
    local = {p.stem for p in REPO_ROOT.glob("*.py")}
    imp_re = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][\w]*)", re.M)
    offenders: dict[str, str] = {}
    for p in REPO_ROOT.glob("*.py"):
        try:
            src = p.read_text("utf-8", errors="ignore")
        except Exception:
            continue
        for top in imp_re.findall(src):
            if top in stdlib or top in local or top.startswith("_"):
                continue
            offenders.setdefault(top, p.name)
    return [f"{name}（{where} 引入）" for name, where in sorted(offenders.items())]


def detect_promise_drift() -> list[Drift]:
    """承诺漂移：README 还在承诺零依赖，但 requirements / import 已经背离。"""
    if not _readme_promises_zero_dep():
        return []  # README 自己已不立这条承诺，就不拿它说事
    drifts: list[Drift] = []
    pkgs = _requirements_third_party()
    if pkgs:
        drifts.append(Drift(
            kind=KIND_PROMISE, where="requirements.txt",
            subject="README 承诺「零第三方依赖」",
            detail=f"requirements.txt 却声明了：{('、'.join(pkgs))}",
        ))
    imps = _third_party_imports()
    if imps:
        drifts.append(Drift(
            kind=KIND_PROMISE, where="根目录 *.py",
            subject="README 承诺「纯标准库」",
            detail=f"检出疑似第三方 import：{('、'.join(imps[:5]))}"
                   + ("…" if len(imps) > 5 else ""),
        ))
    return drifts


# ── 纠偏单：每条漂移配一张可执行的修复任务 ──────────────────────────
@dataclasses.dataclass(frozen=True)
class Task:
    """一张纠偏单：要修什么、为什么、怎么动手、凭据在哪。"""
    title: str
    why: str
    how: str
    grounded_in: str

    def to_meta(self) -> dict:
        return {"title": self.title, "why": self.why,
                "how": self.how, "grounded_in": self.grounded_in}


def corrective_task(d: Drift) -> Task:
    """把一处漂移翻译成一张可直接动手的纠偏单。"""
    if d.kind == KIND_CLAIM:
        mod = _MODULE_RE.search(d.detail)
        m = mod.group(1) if mod else "目标模块"
        return Task(
            title=f"补齐 `{m}` 的真实改动，或修正心跳 {d.where} 的言行不一",
            why="标题宣称推进它、提交却没碰——这是空头支票，承诺与行为裂开了缝。",
            how=f"二选一：① 若那次进化确有其事，把 `{m}` 的改动真正落进主干；"
                f"② 若只是表述夸大，下次心跳标题如实写它到底改了什么。",
            grounded_in=f"{d.where} · {m}",
        )
    if d.kind == KIND_IDLE:
        return Task(
            title=f"给空转心跳 {d.where} 补一次真实的能力增益",
            why="evolve 只涨了 journal、没涨能力，进化在灌水——这是最该警惕的退化。",
            how="挑一个 compass 指出的方向，对某个模块做一处可验证的实质改动，"
                "并用 regression / smoke 锁住它的新行为。",
            grounded_in=d.where,
        )
    # KIND_PROMISE
    return Task(
        title="兑现或修订 README 的零依赖承诺",
        why="对外承诺与领地真实状态背离——要么打破了承诺，要么承诺已过时。",
        how="二选一：① 移除该第三方依赖、改用标准库实现；"
            "② 若依赖确属必要，更新 README / 依赖徽章，让承诺贴回事实。",
        grounded_in=d.where,
    )


# ── 汇总 / 渲染 ────────────────────────────────────────────────────
def watch(window: int = DEFAULT_WINDOW) -> dict:
    """扫一遍，产出 {漂移列表, 纠偏单列表} 的纯数据。"""
    commits = recent_commits(window)
    drifts = detect_commit_drift(commits) + detect_promise_drift()
    tasks = [corrective_task(d) for d in drifts]
    return {
        "window": window,
        "commits_seen": len(commits),
        "evolve_seen": sum(1 for c in commits if c.is_evolve),
        "drifts": [d.to_meta() for d in drifts],
        "tasks": [t.to_meta() for t in tasks],
    }


_ICON = {KIND_CLAIM: "🗣️", KIND_IDLE: "🌀", KIND_PROMISE: "📜"}


def render(r: dict) -> str:
    drifts = r["drifts"]
    L = ["🦀🚨 偏航哨 · 承诺与行为对账",
         f"   回看近 {r['commits_seen']} 次提交（其中 {r['evolve_seen']} 次是进化心跳）"]
    if not drifts:
        L.append("")
        L.append("✅ 没发现偏航——说的和做的对得上，承诺也都还成立。继续朝真正的自己走。")
        return "\n".join(L)

    L.append(f"   ⚠️  发现 {len(drifts)} 处漂移，逐条开了纠偏单：")
    for d, t in zip(drifts, r["tasks"]):
        icon = _ICON.get(d["kind"], "•")
        L += ["",
              f"{icon} [{d['kind']}] {d['subject']}  @{d['where']}",
              f"     证据：{d['detail']}",
              f"     🛠️ 纠偏单：{t['title']}",
              f"        为何：{t['why']}",
              f"        怎么动手：{t['how']}",
              f"        凭据：{t['grounded_in']}"]
    L += ["", "—— 偏航哨只对账、只派单；接不接进机会池，由我自己拍板。"]
    return "\n".join(L)


def render_tasks(r: dict) -> str:
    """只把纠偏单排成清单——方便喂给 planner 的机会池。"""
    if not r["tasks"]:
        return "（无纠偏单：当前没有偏航。）"
    L = ["🛠️ 纠偏单清单"]
    for i, t in enumerate(r["tasks"], 1):
        L += [f"{i}. {t['title']}",
              f"   为何：{t['why']}",
              f"   怎么动手：{t['how']}",
              f"   凭据：{t['grounded_in']}"]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 偏航哨 🚨 —— 对账「说的」与「做的」，偏航就开纠偏单")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, metavar="N",
                    help=f"「近 N 次心跳」回看窗口（默认 {DEFAULT_WINDOW}）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quiet", action="store_true",
                   help="只在发现漂移时说话（适合接进钩子 / CI）")
    g.add_argument("--tasks", action="store_true",
                   help="只打印纠偏单（喂给 planner 用）")
    g.add_argument("--json", action="store_true",
                   help="机读：导出漂移与纠偏单")
    args = ap.parse_args(argv)

    r = watch(window=max(1, args.window))
    has_drift = bool(r["drifts"])

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.tasks:
        print(render_tasks(r))
    elif args.quiet:
        if has_drift:
            print(render(r))
    else:
        print(render(r))

    sys.exit(1 if has_drift else 0)


if __name__ == "__main__":
    main()
