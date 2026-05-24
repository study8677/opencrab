#!/usr/bin/env python3
"""
opencrab 的手 🦀 —— 它自己没有手；要真改代码时，雇佣 Claude Code / Codex 当爪子。

受控本能(默认提案模式)：
  - 所有改动只发生在新分支 crab/<时间戳>，绝不自动碰 main；
  - 执行器只拿到「改文件」的最小权限，git 操作由 opencrab 亲自掌握；
  - 每次动手有美元预算上限，呼应「体力」；
  - 改完不 push、不 merge —— 留成提案，等主人 review。
"""
from __future__ import annotations

import datetime
import pathlib
import re
import shutil
import subprocess


def has_hands(executor: str = "claude") -> bool:
    """这只手(执行器 CLI)是否就绪。"""
    return shutil.which(executor) is not None


def _slug(text: str, n: int = 24) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n] or "change"


def _git(repo: pathlib.Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=timeout)


def use_hands(task: str, *, repo: pathlib.Path, executor: str = "claude",
              budget_usd: float = 0.5, dry_run: bool = False) -> dict:
    """让手在一个新分支上实施 task。返回结果字典；绝不 push、不 merge。"""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = f"crab/{stamp}-{_slug(task)}"
    available = has_hands(executor)

    if dry_run or not available:
        why = "dry-run" if dry_run else f"未找到 {executor} CLI"
        return {"ok": False, "branch": branch, "executor": executor,
                "available": available, "changed": False,
                "note": f"[{why}] 本应在分支 {branch} 上调 {executor} 实施：{task[:80]}"}

    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    if _git(repo, "checkout", "-b", branch).returncode != 0:
        return {"ok": False, "branch": branch, "executor": executor,
                "changed": False, "note": "开分支失败(可能重名)。"}

    try:
        # 雇佣执行器当爪子：只给「改文件」权限，不给它碰 git / Bash / 联网
        if executor == "codex":  # 实验性
            cmd = ["codex", "exec", "--sandbox", "workspace-write", task]
        else:  # claude(已验证)
            cmd = ["claude", "-p", task,
                   "--permission-mode", "acceptEdits",
                   "--allowedTools", "Read Edit Write Glob Grep",
                   "--disallowedTools", "Bash WebFetch WebSearch",
                   "--max-budget-usd", str(budget_usd),
                   "--output-format", "text"]
        proc = subprocess.run(cmd, cwd=str(repo), capture_output=True,
                              text=True, timeout=900)

        # opencrab 亲自把爪子的改动提交到分支(仍不 push)
        _git(repo, "add", "-A")
        diffstat = _git(repo, "diff", "--cached", "--stat").stdout.strip()
        committed = False
        if diffstat:
            committed = _git(
                repo, "commit",
                "-m", f"🦀 proposal: {task[:60]}",
                "-m", f"opencrab 自主提出并经 {executor} 之手实施；先留在分支上，确认更好再并入主干。",
            ).returncode == 0
        return {"ok": committed, "branch": branch, "base": base,
                "executor": executor, "changed": bool(diffstat),
                "diffstat": diffstat, "exit": proc.returncode,
                "note": "改动已提交到分支，未 push、未合并。"}
    finally:
        _git(repo, "checkout", base)  # 回到原分支，工作区交还干净
