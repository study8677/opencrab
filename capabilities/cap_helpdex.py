"""能力 · 命令自述与帮助索引 📖 —— 扫描脚本/入口/README，自动生成统一的能力目录。

它把领地里散落的「能力」串成一份可读索引，三块结构：
  1. 能力目录   —— 每个根级 *.py 的用途(模块 docstring 首行) + 可插拔能力清单(按归类)。
  2. 用法速查   —— 从各脚本 docstring 里捞出 `python …` 命令行，一处看全怎么调。
  3. 典型失败入口 —— 各脚本里所有「非零退出 / 回滚保命」的出口，故障时按图索骥。

默认把渲染结果写到仓库根的 `COMMANDS.md`(自动生成、可重跑覆盖)，方便人和工具发现；
传 ctx={"write": False} 则只渲染不落盘。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import ast
import pathlib
import re

from . import Result, all_capabilities, capability, enabled_capabilities

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT = _REPO_ROOT / "COMMANDS.md"

# docstring 里像「能跑的命令」的行(python …)。
_CMD_RE = re.compile(r"^\s*(python[ \t]+\S+\.py[^\n#]*?)\s*(?:#.*)?$")
# 非零退出出口：sys.exit(<非零>)。零退出是正常收场，不算失败入口。
_EXIT_RE = re.compile(r"sys\.exit\(\s*([^)]*?)\s*\)")


def _root_scripts() -> list[pathlib.Path]:
    return sorted(_REPO_ROOT.glob("*.py"))


def _docstring(src: str) -> str:
    try:
        return ast.get_docstring(ast.parse(src)) or ""
    except Exception:
        return ""


def _purpose(doc: str) -> str:
    """模块 docstring 首行作为「这个脚本是干什么的」。"""
    for line in doc.splitlines():
        if line.strip():
            return line.strip()
    return "(无说明)"


def _usage_cmds(doc: str) -> list[str]:
    """从 docstring 里捞出形如 `python x.py …` 的用法命令行(去重保序)。"""
    seen: set[str] = set()
    out: list[str] = []
    for line in doc.splitlines():
        m = _CMD_RE.match(line)
        if m:
            cmd = m.group(1).strip()
            if cmd not in seen:
                seen.add(cmd)
                out.append(cmd)
    return out


def _nonzero_exits(src: str) -> list[tuple[int, str]]:
    """找出所有非零退出出口，返回 (行号, 退出表达式)。"""
    lines = src.splitlines()
    out: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        for m in _EXIT_RE.finditer(line):
            expr = m.group(1).strip()
            if expr in ("", "0"):          # 正常收场，不是失败入口
                continue
            out.append((i, expr))
    return out


def _scan_scripts() -> list[dict]:
    """逐个根级脚本：用途、用法命令、非零退出出口。"""
    scripts: list[dict] = []
    for p in _root_scripts():
        src = p.read_text("utf-8", errors="ignore")
        doc = _docstring(src)
        scripts.append({
            "file": p.name,
            "purpose": _purpose(doc),
            "usages": _usage_cmds(doc),
            "exits": _nonzero_exits(src),
        })
    return scripts


def _render(scripts: list[dict]) -> str:
    """把扫描结果渲染成统一格式的 markdown 索引。"""
    enabled = {c.name for c in enabled_capabilities()}
    caps = all_capabilities()
    by_cat: dict[str, list] = {}
    for c in caps:
        by_cat.setdefault(c.category, []).append(c)

    L: list[str] = []
    L.append("# 🦀 opencrab 命令索引")
    L.append("")
    L.append("> 自动生成，请勿手改——重跑 `python crab.py cap helpdex` 即可刷新。")
    L.append("> 把领地里散落的能力串成一份索引：能力目录 + 用法速查 + 典型失败入口。")
    L.append("")

    # 1) 能力目录
    L.append("## 🧩 能力目录")
    L.append("")
    L.append("### 脚本入口")
    L.append("")
    L.append("| 脚本 | 用途 |")
    L.append("|---|---|")
    for s in scripts:
        L.append(f"| `{s['file']}` | {s['purpose']} |")
    L.append("")
    L.append(f"### 可插拔能力（{len(enabled)}/{len(caps)} 已启用）")
    L.append("")
    for cat in sorted(by_cat):
        L.append(f"**{cat}**")
        L.append("")
        for c in by_cat[cat]:
            mark = "🟢" if c.name in enabled else "⚪"
            tags = f" · _{', '.join(c.tags)}_" if c.tags else ""
            L.append(f"- {mark} `{c.name}` — {c.summary}{tags}")
        L.append("")

    # 2) 用法速查
    L.append("## ⚡ 用法速查")
    L.append("")
    any_usage = False
    for s in scripts:
        if not s["usages"]:
            continue
        any_usage = True
        L.append(f"### `{s['file']}`")
        L.append("")
        L.append("```bash")
        L.extend(s["usages"])
        L.append("```")
        L.append("")
    L.append("运行某个可插拔能力：")
    L.append("")
    L.append("```bash")
    L.append("python crab.py caps          # 列出全部能力及启用状态")
    L.append("python crab.py cap <NAME>    # 单独跑一种能力")
    L.append("```")
    L.append("")
    if not any_usage:
        L.append("> 暂未在脚本 docstring 里发现 `python …` 用法样例。")
        L.append("")

    # 3) 典型失败入口
    L.append("## 🚨 典型失败入口")
    L.append("")
    L.append("> 各脚本里所有「非零退出」出口——程序判失败、回滚保命的地方，故障时按图索骥。")
    L.append("")
    any_exit = False
    for s in scripts:
        if not s["exits"]:
            continue
        any_exit = True
        L.append(f"- `{s['file']}`：" +
                 "、".join(f"L{ln}(`sys.exit({expr})`)" for ln, expr in s["exits"]))
    if not any_exit:
        L.append("- （未发现非零退出出口）")
    L.append("")
    return "\n".join(L).rstrip() + "\n"


@capability("helpdex", "命令自述与帮助索引：扫脚本/入口/能力，生成统一目录+用法速查+失败入口",
            category="自述", tags=("docs", "discovery", "manifest", "help"))
def run(ctx: dict) -> Result:
    scripts = _scan_scripts()
    doc = _render(scripts)

    write = (ctx or {}).get("write", True)
    n_cmds = sum(len(s["usages"]) for s in scripts)
    n_exits = sum(len(s["exits"]) for s in scripts)
    n_caps = len(all_capabilities())

    written = None
    if write:
        try:
            _OUT.write_text(doc, "utf-8")
            written = _OUT.relative_to(_REPO_ROOT).as_posix()
        except Exception as e:
            return Result(ok=False, summary=f"索引已生成但落盘失败：{e}", detail=doc)

    summary = (f"索引覆盖 {len(scripts)} 个脚本 · {n_caps} 种能力 · "
               f"{n_cmds} 条用法 · {n_exits} 处失败入口"
               + (f" → 已写入 {written}" if written else "（未落盘）"))
    return Result(ok=True, summary=summary, detail=doc,
                  data={"scripts": len(scripts), "capabilities": n_caps,
                        "usages": n_cmds, "exits": n_exits, "written": written})
