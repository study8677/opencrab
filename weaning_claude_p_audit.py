"""Audit and guard the highest-risk weaning backdoor: ``claude -p``.

This module is intentionally standalone and import-safe.  It gives the codebase
a brain-only way to trace remaining shell-outs to ``claude -p`` and, when
installed by a caller, blocks the most common runtime entry point:
``subprocess`` invocation of ``claude -p``.

The guard is opt-in to avoid surprising unrelated imports, but the detection
logic is pure Python and suitable for low-risk self-modification audits.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple


_CLAUDE_P_RE = re.compile(r"(?<![\w.-])claude\s+-p(?![\w.-])")
_PATCHED = False
_ORIGINALS: Dict[str, Any] = {}


def _now() -> float:
    return time.time()


def _stringify_command(command: Any) -> str:
    if isinstance(command, (list, tuple)):
        return " ".join(str(part) for part in command)
    return str(command)


def command_uses_claude_p(command: Any) -> bool:
    """Return True when a subprocess command clearly invokes ``claude -p``."""

    if isinstance(command, (list, tuple)):
        parts = [str(part) for part in command]
        for index, part in enumerate(parts):
            if os.path.basename(part) == "claude" and "-p" in parts[index + 1 :]:
                return True
        return _CLAUDE_P_RE.search(" ".join(parts)) is not None
    return _CLAUDE_P_RE.search(str(command)) is not None


def audit_python_files(root: str | os.PathLike[str] = ".") -> List[Dict[str, Any]]:
    """Scan Python files below *root* for textual ``claude -p`` call sites."""

    root_path = Path(root)
    findings: List[Dict[str, Any]] = []
    for path in sorted(root_path.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".venv", "venv"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if _CLAUDE_P_RE.search(line):
                findings.append(
                    {
                        "path": str(path),
                        "line": line_no,
                        "kind": "literal-claude-p",
                        "snippet": line.strip()[:240],
                    }
                )
    return findings


def summarize_findings(findings: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Summarize audit findings and identify the highest-frequency file."""

    by_path: MutableMapping[str, int] = {}
    total = 0
    for finding in findings:
        total += 1
        path = str(finding.get("path", ""))
        by_path[path] = by_path.get(path, 0) + 1
    hottest = None
    if by_path:
        hottest = max(by_path.items(), key=lambda item: (item[1], item[0]))
    return {
        "total": total,
        "by_path": dict(sorted(by_path.items())),
        "highest_frequency": {"path": hottest[0], "count": hottest[1]} if hottest else None,
    }


def write_audit_trail(
    findings: Sequence[Mapping[str, Any]],
    trail_path: str | os.PathLike[str] = "weaning_claude_p_audit.jsonl",
) -> Dict[str, Any]:
    """Write a JSONL audit trail for one full static self-route scan."""

    summary = summarize_findings(findings)
    event = {
        "ts": _now(),
        "event": "weaning_claude_p_static_audit",
        "summary": summary,
        "findings": list(findings),
    }
    path = Path(trail_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return summary


def _blocked(command: Any) -> RuntimeError:
    rendered = _stringify_command(command)
    return RuntimeError(
        "weaning guard blocked external fallback to `claude -p`: "
        f"{rendered!r}. Use the local Python self-modification path instead."
    )


def _wrap_call(original: Any) -> Any:
    def guarded(command: Any, *args: Any, **kwargs: Any) -> Any:
        if command_uses_claude_p(command):
            raise _blocked(command)
        return original(command, *args, **kwargs)

    return guarded


def install_subprocess_guard() -> bool:
    """Block the highest-frequency runtime entrance: subprocess claude -p calls.

    Returns True when this call installed the guard, False when it was already
    installed.  The wrapper covers ``run``, ``call``, ``check_call``,
    ``check_output`` and ``Popen``.
    """

    global _PATCHED
    if _PATCHED:
        return False

    for name in ("run", "call", "check_call", "check_output", "Popen"):
        _ORIGINALS[name] = getattr(subprocess, name)
        setattr(subprocess, name, _wrap_call(_ORIGINALS[name]))
    _PATCHED = True
    return True


def uninstall_subprocess_guard() -> bool:
    """Restore subprocess functions patched by :func:`install_subprocess_guard`."""

    global _PATCHED
    if not _PATCHED:
        return False

    for name, original in _ORIGINALS.items():
        setattr(subprocess, name, original)
    _ORIGINALS.clear()
    _PATCHED = False
    return True


def audit_and_seal(
    root: str | os.PathLike[str] = ".",
    trail_path: str | os.PathLike[str] = "weaning_claude_p_audit.jsonl",
    install_guard: bool = True,
) -> Dict[str, Any]:
    """Run one audit pass and optionally seal subprocess ``claude -p`` fallback."""

    findings = audit_python_files(root)
    summary = write_audit_trail(findings, trail_path)
    summary["guard_installed"] = install_subprocess_guard() if install_guard else False
    summary["sealed_entry"] = "subprocess: claude -p"
    return summary


if __name__ == "__main__":
    result = audit_and_seal()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
