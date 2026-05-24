#!/usr/bin/env python3
"""
opencrab 的手 🦀 —— 雇佣 Claude Code / Codex 当爪子，并安全地自我进化。

自我进化的 integrate 模式（由 OPENCRAB_AUTONOMY 决定）：
  branch  : 改动只留在新分支(最稳)
  merge   : 自测通过才合并到本地主干(不 push)
  publish : 自测通过才合并并 push 到公开仓(完全自主，"公开大海")

关键的免疫系统：它改完自己后，先自测「还能不能正常启动」——
通过才合并；不通过就自动回滚、丢弃这次改动，保住自己(断肢再生)。
git 始终攥在 opencrab 手里；爪子只拿到「改文件」的最小权限。
"""
from __future__ import annotations

import datetime
import pathlib
import re
import shutil
import subprocess
import sys


def has_hands(executor: str = "claude") -> bool:
    """这只手(执行器 CLI)是否就绪。"""
    return shutil.which(executor) is not None


def _slug(text: str, n: int = 24) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n] or "change"


def _git(repo: pathlib.Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=timeout)


def _self_test(repo: pathlib.Path) -> tuple[bool, str]:
    """它改完自己后，验证「还能不能启动」：语法编译 + 导入主模块。"""
    pys = [p.name for p in repo.glob("*.py")]
    if pys:
        r = subprocess.run([sys.executable, "-m", "py_compile", *pys],
                           cwd=str(repo), capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return False, "语法错误：" + (r.stderr.strip()[:200] or "?")
    r2 = subprocess.run([sys.executable, "-c", "import crab"],
                        cwd=str(repo), capture_output=True, text=True, timeout=60)
    if r2.returncode != 0:
        return False, "导入失败：" + (r2.stderr.strip()[:200] or "?")
    return True, "自测通过：改完还能正常启动"


def use_hands(task: str, *, repo: pathlib.Path, executor: str = "claude",
              budget_usd: float = 0.5, dry_run: bool = False,
              integrate: str = "branch") -> dict:
    """让手在新分支上实施 task，再按 integrate 模式安全地并入。"""
    repo = pathlib.Path(repo)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = f"crab/{stamp}-{_slug(task)}"
    available = has_hands(executor)

    if dry_run or not available:
        why = "dry-run" if dry_run else f"未找到 {executor} CLI"
        return {"ok": False, "branch": branch, "executor": executor,
                "available": available, "changed": False, "integrate": integrate,
                "note": f"[{why}] 本应在分支 {branch} 上调 {executor}（{integrate} 模式）实施：{task[:70]}"}

    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    if _git(repo, "checkout", "-b", branch).returncode != 0:
        return {"ok": False, "branch": branch, "changed": False,
                "integrate": integrate, "note": "开分支失败(可能重名)。"}

    result = {"branch": branch, "base": base, "executor": executor,
              "integrate": integrate, "changed": False, "ok": False}
    try:
        # 1) 雇佣爪子改文件：只给「改文件」最小权限，不碰 git / Bash / 联网
        if executor == "codex":  # 实验性
            cmd = ["codex", "exec", "--sandbox", "workspace-write", task]
        else:  # claude(已验证)
            cmd = ["claude", "-p", task, "--permission-mode", "acceptEdits",
                   "--allowedTools", "Read Edit Write Glob Grep",
                   "--disallowedTools", "Bash WebFetch WebSearch",
                   "--max-budget-usd", str(budget_usd), "--output-format", "text"]
        proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=900)
        result["exit"] = proc.returncode

        # 2) opencrab 亲自把改动提交到分支
        _git(repo, "add", "-A")
        diffstat = _git(repo, "diff", "--cached", "--stat").stdout.strip()
        result["diffstat"] = diffstat
        if not diffstat:
            result["note"] = "爪子没做出任何改动。"
            return result
        result["changed"] = True
        _git(repo, "commit", "-m", f"🦀 self-evolve: {task[:60]}",
             "-m", "opencrab 自主提出并实施。")

        if integrate == "branch":
            result["ok"] = True
            result["note"] = f"改动在分支 {branch}，先养着，未合并。"
            return result

        # 3) 免疫系统：改完自己，先自测「还能不能活」
        ok, why = _self_test(repo)
        result["self_test"] = why
        if not ok:
            _git(repo, "checkout", base)          # 断肢再生：回滚保命
            _git(repo, "branch", "-D", branch)
            result["healed"] = True
            result["note"] = f"自测没过（{why}）→ 已回滚丢弃，保住了自己。"
            return result

        # 4) 自测通过 → 合并到主干
        _git(repo, "checkout", base)
        if _git(repo, "merge", "--no-ff", branch,
                "-m", f"🦀 evolve: {task[:50]}").returncode != 0:
            _git(repo, "merge", "--abort")
            result["note"] = "合并冲突 → 已放弃，改动留在分支。"
            return result
        _git(repo, "branch", "-D", branch)

        if integrate == "publish":              # 公开大海：推向全世界
            push = _git(repo, "push", "origin", base, timeout=120)
            result["ok"] = push.returncode == 0
            result["note"] = ("自测通过 → 已合并并 push 到公开仓 🌊" if result["ok"]
                              else "已合并到本地，但 push 失败：" + push.stderr.strip()[:120])
        else:                                   # merge：只到本地主干
            result["ok"] = True
            result["note"] = "自测通过 → 已合并到本地主干(未 push)。"
        return result
    finally:
        cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if cur and cur != base:                 # 兜底：确保回到主干
            _git(repo, "checkout", base)
