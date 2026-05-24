"""能力 · 状态快照与差异诊断 🩺 —— 记录此刻工作区的运行状态，并对比上次快照。

和 `cap_snapshot`(量代码规模、供演化日志用)不同，这里关心的是「运行态」：
我现在在哪条分支、有没有未提交的脏改动、配置摘要、最近的审计尾部。
每次运行都把这张「运行态快照」存到 state/diag/last.json，并和上次对比，
输出「我变了什么、问题可能从哪来」——给故障排查与自我感知用。

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import datetime
import json
import pathlib
import subprocess

from . import Result, capability

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DIAG_DIR = _REPO_ROOT / "state" / "diag"      # 落在被 .gitignore 的 state/ 里
_LAST = _DIAG_DIR / "last.json"


def _git(args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(_REPO_ROOT), *args.split()],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return ""


def _audit_tail(n: int = 5) -> list[str]:
    """读今天审计的尾部 n 条，归成 `event` 名列表，定位最近发生了什么。"""
    try:
        import sys
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        import audit
        recs = audit.read_records(limit=n)
        return [f"{r.get('seq', '?')}:{r.get('event', '?')}" for r in recs]
    except Exception:
        return []


def capture() -> dict:
    """给「此刻运行态的我」拍一张快照(纯数据)。"""
    import os
    porcelain = _git("status --porcelain")
    dirty = [ln for ln in porcelain.splitlines() if ln.strip()]
    return {
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
        "branch": _git("rev-parse --abbrev-ref HEAD") or "?",
        "head": _git("rev-parse --short HEAD") or "?",
        "dirty_count": len(dirty),
        "dirty_files": sorted(ln[3:] for ln in dirty)[:20],
        "env": {
            "autonomy": os.environ.get("OPENCRAB_AUTONOMY", "journal"),
            "executor": os.environ.get("OPENCRAB_EXECUTOR", "claude"),
            "model": os.environ.get("OPENCRAB_MODEL", "gpt-5.4-mini"),
            "dreaming": not os.environ.get("OPENCRAB_API_KEY"),
        },
        "audit_tail": _audit_tail(),
    }


def _load_last() -> dict | None:
    if not _LAST.exists():
        return None
    try:
        return json.loads(_LAST.read_text("utf-8"))
    except Exception:
        return None


def _save(snap: dict) -> None:
    try:
        _DIAG_DIR.mkdir(parents=True, exist_ok=True)
        _LAST.write_text(json.dumps(snap, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass   # 诊断是观测者，存不下也绝不弄死生命


def diff(before: dict, after: dict) -> list[str]:
    """量出两张运行态快照之间「我变了什么」，只列真正发生变化的关键差异。"""
    diffs: list[str] = []
    if before.get("branch") != after.get("branch"):
        diffs.append(f"分支 {before.get('branch')}→{after.get('branch')}")
    if before.get("head") != after.get("head"):
        diffs.append(f"HEAD {before.get('head')}→{after.get('head')}")
    db, da = before.get("dirty_count", 0), after.get("dirty_count", 0)
    if db != da:
        diffs.append(f"未提交改动 {db}→{da}（{da - db:+d}）")
    for key, label in (("autonomy", "自治"), ("executor", "手"),
                       ("model", "大脑"), ("dreaming", "梦境")):
        bv = (before.get("env") or {}).get(key)
        av = (after.get("env") or {}).get(key)
        if bv != av:
            diffs.append(f"{label} {bv}→{av}")
    return diffs


@capability("diag", "运行态诊断：分支/脏改动/配置/审计尾部，并对比上次快照",
            category="感知", tags=("diagnostics", "runtime", "git"))
def run(ctx: dict) -> Result:
    now = capture()
    last = _load_last()
    _save(now)   # 这次成为下次的对比基线

    head_line = (f"@{now['branch']} {now['head']} · "
                 f"{now['dirty_count']} 处未提交 · "
                 f"{'梦境' if now['env']['dreaming'] else now['env']['model']}")
    if last is None:
        return Result(ok=True, summary=f"{head_line}（首张运行态快照，暂无可对比基线）",
                      data={"snapshot": now, "diffs": []})

    diffs = diff(last, now)
    if diffs:
        summary = f"{head_line} · 较上次：" + "；".join(diffs)
    else:
        summary = f"{head_line} · 较上次无关键变化"

    detail_lines = [f"上次快照 @ {last.get('at', '?')}"]
    detail_lines += ["  " + d for d in diffs] or ["  （运行态稳定）"]
    if now["dirty_files"]:
        detail_lines.append("当前未提交文件：")
        detail_lines += ["  " + f for f in now["dirty_files"]]
    if now["audit_tail"]:
        detail_lines.append("最近审计：" + " ".join(now["audit_tail"]))
    return Result(ok=True, summary=summary, detail="\n".join(detail_lines),
                  data={"snapshot": now, "diffs": diffs})
