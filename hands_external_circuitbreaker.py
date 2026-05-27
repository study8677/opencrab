"""Runtime circuit breaker for accidental Claude external-aid calls.

The breaker is intentionally small and dependency-free so it can be loaded very
early.  It fails closed for ``claude`` executable invocations unless an explicit
operator override is present:

    CRAB_ALLOW_EXTERNAL_CLAUDE=1

Every blocked touch is appended to ``.crab_external_breaker_audit.jsonl``.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable


_ALLOW_ENV = "CRAB_ALLOW_EXTERNAL_CLAUDE"
_AUDIT_PATH_ENV = "CRAB_EXTERNAL_BREAKER_AUDIT"
_DEFAULT_AUDIT_PATH = ".crab_external_breaker_audit.jsonl"


class ClaudeCircuitBreakerError(RuntimeError):
    """Raised when the runtime breaker blocks an external Claude invocation."""


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _token_basename(token: Any) -> str:
    try:
        text = os.fspath(token)
    except TypeError:
        text = str(token)
    text = text.strip().strip("\"'")
    if not text:
        return ""
    return os.path.basename(text).lower()


def _iter_command_tokens(command: Any) -> Iterable[str]:
    if command is None:
        return ()
    if isinstance(command, (str, bytes, os.PathLike)):
        text = os.fsdecode(command)
        try:
            return shlex.split(text)
        except ValueError:
            return text.split()
    try:
        return list(command)
    except TypeError:
        return (str(command),)


def is_claude_command(command: Any) -> bool:
    """Return True when *command* attempts to execute the ``claude`` binary."""

    for token in _iter_command_tokens(command):
        base = _token_basename(token)
        if base == "claude" or base == "claude.exe":
            return True
    return False


def breaker_enabled() -> bool:
    """Return True when the external-aid breaker should fail closed."""

    return not _truthy(os.environ.get(_ALLOW_ENV))


def should_block(command: Any) -> bool:
    """Return True when a command must be blocked and audited."""

    return breaker_enabled() and is_claude_command(command)


def audit_block(command: Any, api: str) -> None:
    """Append one audit record for a blocked accidental external-aid call."""

    path = Path(os.environ.get(_AUDIT_PATH_ENV, _DEFAULT_AUDIT_PATH))
    record = {
        "ts": time.time(),
        "event": "external_claude_blocked",
        "api": api,
        "command": repr(command),
        "reason": "brain-only runtime circuit breaker",
        "override_env": _ALLOW_ENV,
    }
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        # Blocking is the safety property; audit failure must not let Claude run.
        pass


def assert_not_blocked(command: Any, api: str = "unknown") -> None:
    """Raise after auditing if *command* would invoke external Claude."""

    if should_block(command):
        audit_block(command, api)
        raise ClaudeCircuitBreakerError(
            "blocked external claude invocation by brain-only runtime circuit breaker "
            f"(set {_ALLOW_ENV}=1 only for an explicitly approved non-brain-only run)"
        )


_ORIGINAL_POPEN = subprocess.Popen
_INSTALLED = False


def install() -> bool:
    """Install subprocess-level protection once.

    Returns True when this call installed the hook, False when it was already
    active.
    """

    global _INSTALLED
    if _INSTALLED:
        return False

    def guarded_popen(*popenargs: Any, **kwargs: Any) -> Any:
        command = popenargs[0] if popenargs else kwargs.get("args")
        assert_not_blocked(command, "subprocess.Popen")
        return _ORIGINAL_POPEN(*popenargs, **kwargs)

    subprocess.Popen = guarded_popen  # type: ignore[assignment]
    _INSTALLED = True
    return True


__all__ = [
    "ClaudeCircuitBreakerError",
    "assert_not_blocked",
    "audit_block",
    "breaker_enabled",
    "install",
    "is_claude_command",
    "should_block",
]
