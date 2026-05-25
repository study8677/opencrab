#!/usr/bin/env python3
"""变更影响分析器 🎯 —— 算清「这次 diff 牵动了什么、最少该验哪些」。

`cap_impact` 已能从一次变更摸出直接下游依赖、点名它的文档、受影响能力。
这条标准库模块把它再推一层，专攻进化前最想知道的两个问题：

  1. **传递闭包**：动一个模块，不只看「谁直接 import 它」，而是顺着 import
     图把**间接受牵连**的模块全摊开——漏测往往漏在第二跳之外。
  2. **该验哪些（最小集）**：领地里能「证明自己还活着」的命令是有限的——
     `checkup.py` / `smoke.py` / `goldens.py` / `hands.py` 自测。每条验证
     命令自身也有一棵 import 依赖树；只有当本次变更落进某条命令的依赖树里，
     这条命令才**真的相关**。于是不再「无脑全跑」，而是按相关性排出最小清单，
     并标出哪些是兜底（任何改动都建议跑的领地自检）。

顺带还会标出：受波及的**入口**（带 `__main__`、可 `python X.py` 直接跑的脚本）
和**能力**（`cap_*.py` → `crab.py cap <NAME>`），它们是改完最该亲手点一遍的面。

用法：
    python impact.py                  # 对比 main + 工作区脏改动，打印影响清单
    python impact.py --base HEAD~3    # 换个对比基线
    python impact.py --files a.py b.py # 直接给定变更文件（跳过 git）
    python impact.py --json           # 机读：导成 JSON

零第三方依赖，纯标准库。和 `crab.py cap impact` 互补：那条落盘清单，这条
专做「最小该验集」的推断，可单独跑、可被 CI/钩子接住。
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# 领地里「证明自己还能活」的验证命令：(命令, 它真正运行的入口文件, 一句说明)。
# 只有当本次变更落进某入口的依赖树里，这条命令才被判为「相关」。
_VERIFIERS = [
    ("python checkup.py --quiet", "checkup.py", "领地自检：关键文件/可编译/可导入/结构完整"),
    ("python smoke.py --quiet", "smoke.py", "烟雾测试：README 关键用法还跑得起来"),
    ("python regression.py snapshot", "regression.py", "回归样本：关键命令输出/退出码未漂移"),
    ("python hands.py", "hands.py", "手的自测：这只生命「还能不能活」"),
]
# 兜底：无论变更落在哪，这些都建议先跑——它们扫的是整片领地，不靠依赖树。
_ALWAYS = {"python checkup.py --quiet"}


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return ""


def _py_files() -> list[pathlib.Path]:
    """领地里所有受管 .py（排除 state/ 与 .git/）。"""
    out = []
    for p in REPO_ROOT.rglob("*.py"):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel.startswith(("state/", ".git/")):
            continue
        out.append(p)
    return sorted(out)


def _imports(src: str) -> set[str]:
    """一个源文件 import 进来的所有点分模块名（坏语法返回空集）。"""
    mods: set[str] = set()
    try:
        tree = ast.parse(src)
    except Exception:
        return mods
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def _module_keys(rel: str) -> set[str]:
    """一个文件路径可能被 import 的模块名形态。"""
    parts = rel[:-3].split("/")          # 去掉 .py
    return {parts[-1], ".".join(parts)}  # 裸 stem + 包路径


def _forward_graph() -> dict[str, set[str]]:
    """正向依赖图：文件 -> 它 import 的「本仓库其他文件」集合（posix 相对路径）。"""
    files = _py_files()
    rels = [p.relative_to(REPO_ROOT).as_posix() for p in files]
    # 模块名形态 -> 它对应的仓库文件
    key_to_file: dict[str, str] = {}
    for rel in rels:
        for k in _module_keys(rel):
            key_to_file[k] = rel
    graph: dict[str, set[str]] = {}
    for p, rel in zip(files, rels):
        mods = _imports(p.read_text("utf-8", errors="ignore"))
        deps: set[str] = set()
        for m in mods:
            if m in key_to_file:
                deps.add(key_to_file[m])
            else:  # `import a.b.c` 时尾段也试着匹配（如 capabilities.cap_x）
                tail = m.split(".")[-1]
                if tail in key_to_file:
                    deps.add(key_to_file[tail])
        deps.discard(rel)
        graph[rel] = deps
    return graph


def _reverse(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    """反转依赖图：文件 -> 「直接 import 了它」的文件集合。"""
    rev: dict[str, set[str]] = {f: set() for f in graph}
    for f, deps in graph.items():
        for d in deps:
            rev.setdefault(d, set()).add(f)
    return rev


def _closure(starts: set[str], adj: dict[str, set[str]]) -> set[str]:
    """从 starts 出发在邻接表 adj 上做 BFS，返回可达集（不含 starts 本身）。"""
    seen: set[str] = set(starts)
    stack = list(starts)
    while stack:
        cur = stack.pop()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen - set(starts)


def _changed_files(base: str, given: list[str] | None) -> tuple[list[str], str]:
    """求出本次变更文件（posix 相对路径，去重保序），附一句来源说明。"""
    if given:
        files = [str(f).replace("\\", "/") for f in given]
        return _dedup_existing(files), "由 --files 直接给定"
    changed: list[str] = []
    if _git(["rev-parse", "--verify", "--quiet", base]):
        diff = _git(["diff", "--name-only", f"{base}...HEAD"])
        changed += [ln.strip() for ln in diff.splitlines() if ln.strip()]
        src = f"git diff {base}...HEAD + 工作区脏改动"
    else:
        src = f"(基线 {base!r} 不存在，只看工作区)"
    for ln in _git(["status", "--porcelain"]).splitlines():
        if ln.strip():
            changed.append(ln[3:].strip())
    return _dedup_existing(changed), src


def _dedup_existing(files: list[str]) -> list[str]:
    """去重保序，只留仍存在于工作区的文件。"""
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        if f and f not in seen and (REPO_ROOT / f).exists():
            seen.add(f)
            out.append(f)
    return out


def _doc_mentions(filename: str) -> list[str]:
    """哪些文档（*.md）点名了这个文件——可能要跟着同步更新。"""
    hits: list[str] = []
    for p in sorted(REPO_ROOT.rglob("*.md")):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel.startswith(("state/", ".git/")):
            continue
        try:
            if filename in p.read_text("utf-8", errors="ignore"):
                hits.append(rel)
        except Exception:
            continue
    return hits


def _has_main(rel: str) -> bool:
    """文件是否带 `if __name__ == "__main__"`（可 `python X.py` 直接跑）。"""
    try:
        src = (REPO_ROOT / rel).read_text("utf-8", errors="ignore")
    except Exception:
        return False
    return '__main__' in src and "__name__" in src


def analyze(base: str = "main", files: list[str] | None = None) -> dict:
    """把「变更 -> 传递闭包 -> 入口/能力/文档 -> 最小该验集」算成纯数据。"""
    changed, src = _changed_files(base, files)
    fwd = _forward_graph()
    rev = _reverse(fwd)

    changed_py = {f for f in changed if f.endswith(".py")}
    # 传递下游：顺着「谁 import 谁」一路摊开间接受牵连的模块
    transitive = sorted(_closure(changed_py, rev))

    # 受波及入口：自身或其依赖树里命中了变更的、带 __main__ 的脚本
    entrypoints = []
    for f in sorted(fwd):
        if not _has_main(f):
            continue
        reach = _closure({f}, fwd) | {f}      # 入口能 import 到的全部 + 自己
        if reach & changed_py:
            entrypoints.append(f)

    # 受影响能力：直接动了的 cap_*.py
    caps = sorted(
        f[len("capabilities/cap_"):-len(".py")]
        for f in changed
        if f.startswith("capabilities/cap_") and f.endswith(".py")
    )

    # 文档同步：每个变更文件被哪些 md 点名
    docs: dict[str, list[str]] = {}
    for f in changed:
        hits = _doc_mentions(pathlib.Path(f).name)
        if hits:
            docs[f] = hits

    # 最小该验集：变更落进某验证命令的依赖树 -> 它相关；外加兜底自检
    verify: list[dict] = []
    for cmd, entry, why in _VERIFIERS:
        reach = _closure({entry}, fwd) | {entry}
        relevant = bool(reach & changed_py)
        always = cmd in _ALWAYS
        if relevant or always:
            verify.append({
                "command": cmd, "why": why,
                "reason": "兜底全域自检" if (always and not relevant)
                          else "变更落在它的依赖树里",
            })
    for cap in caps:
        verify.append({"command": f"python crab.py cap {cap}",
                       "why": f"单跑受影响能力 `{cap}`，确认它本身没坏",
                       "reason": "本次直接改了它"})

    return {
        "source": src,
        "changed": changed,
        "transitive": transitive,
        "entrypoints": entrypoints,
        "caps": caps,
        "docs": docs,
        "verify": verify,
    }


def render(a: dict) -> str:
    """把影响数据渲染成一份「牵动了什么 + 最小该验清单」。"""
    L = ["🦀🎯 变更影响分析", f"   来源：{a['source']}"]
    if not a["changed"]:
        L.append("   （没探测到变更文件——工作区干净，或基线选错了。）")
        return "\n".join(L)

    L.append(f"   变更 {len(a['changed'])} · 传递牵连 {len(a['transitive'])} · "
             f"入口 {len(a['entrypoints'])} · 能力 {len(a['caps'])}")
    L += ["", "▸ 变更文件："]
    L += [f"    • {f}" for f in a["changed"]]

    if a["transitive"]:
        L += ["", "▸ 传递下游（间接 import 了变更模块，改了接口要一并检查）："]
        L += [f"    ↘ {f}" for f in a["transitive"]]

    if a["entrypoints"]:
        L += ["", "▸ 受波及入口（改完最该亲手 `python X` 点一遍）："]
        L += [f"    ⮕ python {f}" for f in a["entrypoints"]]

    if a["docs"]:
        L += ["", "▸ 点名变更文件的文档（可能要同步更新）："]
        for f, hits in a["docs"].items():
            L.append(f"    📄 {f} ← {', '.join(hits)}")

    L += ["", "▸ 最小该验集（按顺序跑；只列与本次变更相关的）：", "", "```bash"]
    L += [v["command"] for v in a["verify"]] or ["# （无——本次变更没碰到任何验证路径）"]
    L += ["```", "", "| 命令 | 验什么 | 为何相关 |", "|---|---|---|"]
    for v in a["verify"]:
        L.append(f"| `{v['command']}` | {v['why']} | {v['reason']} |")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 变更影响分析器 🎯 —— 算清这次 diff 牵动了什么、最少该验哪些")
    ap.add_argument("--base", default="main", metavar="REF",
                    help="对比基线（默认 main）")
    ap.add_argument("--files", nargs="+", metavar="PATH",
                    help="直接给定变更文件（跳过 git 探测）")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    args = ap.parse_args(argv)

    a = analyze(base=args.base, files=args.files)
    if args.json:
        print(json.dumps(a, ensure_ascii=False, indent=2))
    else:
        print(render(a))
    # 退出码：有变更=0（正常分析完）；这是只读分析器，不据此拦改动
    sys.exit(0)


if __name__ == "__main__":
    main()
