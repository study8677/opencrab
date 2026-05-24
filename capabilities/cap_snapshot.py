"""能力 · 快照 📸 —— 用几个关键指标量化「此刻领地」的状态。"""
from __future__ import annotations

import datetime
import pathlib
import subprocess

from . import Result, capability

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _git(args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(_REPO_ROOT), *args.split()],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return ""


def take() -> dict:
    """给「此刻的我」拍一张快照(纯数据，供 crab 的演化日志复用)。"""
    py_files = sorted(_REPO_ROOT.glob("*.py"))
    loc = 0
    for p in py_files:
        try:
            loc += len(p.read_text("utf-8", errors="ignore").splitlines())
        except Exception:
            pass
    skills = _REPO_ROOT / "skills"
    journal = _REPO_ROOT / "journal"
    return {
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
        "head": _git("rev-parse --short HEAD") or "?",
        "py_files": len(py_files),
        "loc": loc,
        "skills": len(list(skills.glob("*.md"))) if skills.exists() else 0,
        "journals": len(list(journal.glob("*.md"))) if journal.exists() else 0,
    }


@capability("snapshot", "拍快照：Python 文件数、代码行数、已学技能、航海日志")
def run(ctx: dict) -> Result:
    snap = take()
    summary = (f"{snap['py_files']} 个 .py · {snap['loc']} 行 · "
               f"{snap['skills']} 技能 · {snap['journals']} 日志 @ {snap['head']}")
    return Result(ok=True, summary=summary, data=snap)
