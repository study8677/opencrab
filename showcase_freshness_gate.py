"""Freshness gate for the public showcase page.

The gate compares the numbers advertised by ``docs/index.html`` with the
current repository state.  When the page looks stale it writes a refresh ticket
and invokes ``showcase_refresh_gate`` when that module exposes a callable entry
point.

This module is intentionally dependency-free and import-safe.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


DEFAULT_INDEX = Path("docs/index.html")
DEFAULT_TICKET = Path("docs/showcase_refresh_ticket.json")
DEFAULT_MAX_AGE_DAYS = 7


@dataclass(frozen=True)
class ShowcaseCounts:
    modules: int
    commits: int
    skills: int

    def as_dict(self) -> Dict[str, int]:
        return {
            "modules": self.modules,
            "commits": self.commits,
            "skills": self.skills,
        }


@dataclass(frozen=True)
class FreshnessResult:
    stale: bool
    reasons: List[str]
    documented: Dict[str, Optional[int]]
    current: ShowcaseCounts
    ticket_path: Optional[str]
    refresh_gate_ran: bool
    refresh_gate_error: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "stale": self.stale,
            "reasons": list(self.reasons),
            "documented": dict(self.documented),
            "current": self.current.as_dict(),
            "ticket_path": self.ticket_path,
            "refresh_gate_ran": self.refresh_gate_ran,
            "refresh_gate_error": self.refresh_gate_error,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _repo_root(start: Optional[Path] = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "crab.py").exists() or (candidate / ".git").exists():
            return candidate
    return here


def _iter_python_modules(root: Path) -> Iterable[Path]:
    ignored = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "venv", ".venv"}
    for path in root.rglob("*.py"):
        if any(part in ignored for part in path.parts):
            continue
        yield path


def _count_skills(root: Path) -> int:
    """Count public top-level functions/classes as a stable skill proxy."""

    total = 0
    for path in _iter_python_modules(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    total += 1
    return total


def _read_git_head(root: Path) -> str:
    head = root / ".git" / "HEAD"
    try:
        raw = head.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if raw.startswith("ref:"):
        ref = raw.split(":", 1)[1].strip()
        try:
            return (root / ".git" / ref).read_text(encoding="utf-8").strip()
        except OSError:
            return raw
    return raw


def _count_commits(root: Path) -> int:
    """Return a lightweight commit-count estimate without shelling out to git."""

    logs_head = root / ".git" / "logs" / "HEAD"
    try:
        lines = [line for line in logs_head.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return 1 if _read_git_head(root) else 0
    return len(lines)


def current_counts(root: Optional[Path] = None) -> ShowcaseCounts:
    base = _repo_root(root)
    return ShowcaseCounts(
        modules=sum(1 for _ in _iter_python_modules(base)),
        commits=_count_commits(base),
        skills=_count_skills(base),
    )


def _number_near(text: str, words: Iterable[str]) -> Optional[int]:
    joined = "|".join(re.escape(word) for word in words)
    patterns = (
        rf"(?:{joined})[^0-9]{{0,80}}([0-9][0-9,]*)",
        rf"([0-9][0-9,]*)[^<\n]{{0,80}}(?:{joined})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def documented_counts(index_path: Path = DEFAULT_INDEX) -> Dict[str, Optional[int]]:
    try:
        html = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"modules": None, "commits": None, "skills": None}

    meta_values: Dict[str, Optional[int]] = {}
    for key in ("modules", "commits", "skills"):
        meta = re.search(
            rf'<meta\s+[^>]*(?:name|property)=["\']crab-{key}["\'][^>]*content=["\']([0-9][0-9,]*)["\']',
            html,
            flags=re.IGNORECASE,
        )
        meta_values[key] = int(meta.group(1).replace(",", "")) if meta else None

    return {
        "modules": meta_values["modules"] if meta_values["modules"] is not None else _number_near(html, ("module", "modules", "模块")),
        "commits": meta_values["commits"] if meta_values["commits"] is not None else _number_near(html, ("commit", "commits", "提交")),
        "skills": meta_values["skills"] if meta_values["skills"] is not None else _number_near(html, ("skill", "skills", "技能")),
    }


def _file_age_days(path: Path) -> Optional[float]:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None
    return (_utc_now() - modified).total_seconds() / 86400.0


def _staleness_reasons(
    documented: Mapping[str, Optional[int]],
    current: ShowcaseCounts,
    index_path: Path,
    max_age_days: int,
) -> List[str]:
    reasons: List[str] = []
    current_map = current.as_dict()

    if not index_path.exists():
        reasons.append(f"{index_path.as_posix()} is missing")

    for key, value in documented.items():
        if value is None:
            reasons.append(f"documented {key} count is missing")
        elif value != current_map[key]:
            reasons.append(f"{key} count differs: documented={value}, current={current_map[key]}")

    age = _file_age_days(index_path)
    if age is not None and age > max_age_days:
        reasons.append(f"{index_path.as_posix()} is {age:.1f} days old; limit={max_age_days}")

    return reasons


def _write_ticket(path: Path, reasons: List[str], documented: Mapping[str, Optional[int]], current: ShowcaseCounts) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": _utc_now().isoformat(),
        "kind": "showcase_refresh_request",
        "source": "showcase_freshness_gate",
        "reasons": reasons,
        "documented": dict(documented),
        "current": current.as_dict(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path.as_posix()


def _call_entrypoint(func: Any) -> None:
    signature = inspect.signature(func)
    required = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]
    if not required:
        func()
    elif len(required) == 1:
        func([])
    else:
        raise TypeError(f"unsupported showcase_refresh_gate entrypoint signature: {signature}")


def run_showcase_refresh_gate() -> Optional[str]:
    """运行展示刷新网关，优先使用已存在的 showcase_refresh_gate 模块。"""
    # 先尝试导入 showcase_refresh_gate
    try:
        module = importlib.import_module("showcase_refresh_gate")
        # 找可调用的入口点
        for name in ("main", "run", "check", "showcase_refresh_gate"):
            func = getattr(module, name, None)
            if callable(func):
                try:
                    _call_entrypoint(func)
                except Exception as exc:
                    return f"{name} failed: {exc}"
                return None
        return "no callable entrypoint in showcase_refresh_gate"
    except ImportError:
        pass  # 没有 showcase_refresh_gate，直接执行刷新
    
    # 直接执行刷新命令
    import subprocess
    import sys
    root = Path(__file__).parent
    
    # 运行 showcase_refresher.py 更新 JSON
    refresher = root / "showcase_refresher.py"
    if refresher.exists():
        subprocess.run([sys.executable, str(refresher)], cwd=root, check=True)
    
    # 运行 showcase.py 更新 HTML
    showcase = root / "showcase.py"
    if showcase.exists():
        subprocess.run([sys.executable, str(showcase)], cwd=root, check=True)
    
    return None  # 成功


def check_docs_index(
    index_path: Path = DEFAULT_INDEX,
    ticket_path: Path = DEFAULT_TICKET,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    run_refresh_gate: bool = True,
) -> FreshnessResult:
    base = _repo_root(index_path.parent if index_path.parent != Path("") else None)
    index = index_path if index_path.is_absolute() else base / index_path
    ticket = ticket_path if ticket_path.is_absolute() else base / ticket_path

    current = current_counts(base)
    documented = documented_counts(index)
    reasons = _staleness_reasons(documented, current, index, max_age_days)
    stale = bool(reasons)

    written_ticket: Optional[str] = None
    refresh_error: Optional[str] = None
    refresh_ran = False

    if stale:
        written_ticket = _write_ticket(ticket, reasons, documented, current)
        if run_refresh_gate:
            refresh_ran = True
            refresh_error = run_showcase_refresh_gate()
            # 刷新后重新检查是否仍然过期
            if refresh_error is None:
                # 重新读取 index.html 的统计值
                documented_after = documented_counts(index)
                reasons_after = _staleness_reasons(documented_after, current, index, max_age_days)
                if not reasons_after:
                    # 刷新成功，清除过期状态
                    stale = False
                    reasons.clear()

    return FreshnessResult(
        stale=stale,
        reasons=reasons,
        documented=dict(documented),
        current=current,
        ticket_path=written_ticket,
        refresh_gate_ran=refresh_ran,
        refresh_gate_error=refresh_error,
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = list(argv or [])
    index = Path(args[0]) if args else DEFAULT_INDEX
    max_age = int(os.environ.get("SHOWCASE_MAX_AGE_DAYS", str(DEFAULT_MAX_AGE_DAYS)))
    result = check_docs_index(index_path=index, max_age_days=max_age)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result.stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
