"""Process-local safeguards loaded automatically by Python.

This module keeps residual ``claude -p`` subprocess entry points from becoming
silent hard dependencies.  Any code path that still shells out through the
standard ``subprocess`` helpers now gets a brain-only default response first;
the original external call is used only if the local route itself fails.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Any, Iterable


_ORIGINAL_RUN = subprocess.run
_ORIGINAL_CHECK_OUTPUT = subprocess.check_output
_ORIGINAL_CHECK_CALL = subprocess.check_call


def _is_claude_p_command(cmd: Any) -> bool:
    """Return True when *cmd* is a real ``claude -p`` invocation."""

    if isinstance(cmd, (list, tuple)):
        parts = [str(part) for part in cmd]
    elif isinstance(cmd, str):
        try:
            parts = shlex.split(cmd)
        except ValueError:
            return False
    else:
        return False

    if not parts:
        return False

    exe = os.path.basename(parts[0])
    return exe == "claude" and "-p" in parts[1:]


def _extract_prompt(cmd: Any, kwargs: dict[str, Any]) -> str:
    """Best-effort prompt extraction for local brain-only fallback text."""

    if isinstance(cmd, (list, tuple)):
        parts = [str(part) for part in cmd]
    elif isinstance(cmd, str):
        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = [cmd]
    else:
        parts = []

    prompt_parts: list[str] = []
    for index, part in enumerate(parts):
        if part == "-p" and index + 1 < len(parts):
            prompt_parts.append(parts[index + 1])

    input_value = kwargs.get("input")
    if isinstance(input_value, bytes):
        prompt_parts.append(input_value.decode("utf-8", errors="replace"))
    elif isinstance(input_value, str):
        prompt_parts.append(input_value)

    return "\n".join(piece for piece in prompt_parts if piece).strip()


def _wants_text(kwargs: dict[str, Any]) -> bool:
    return bool(
        kwargs.get("text")
        or kwargs.get("universal_newlines")
        or kwargs.get("encoding")
        or kwargs.get("errors")
    )


def _brainonly_claude_p_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """Local default for residual ``claude -p`` callers.

    The response is intentionally small and explicit: callers get a successful
    brain-only result instead of reaching the network/tooling by default.  If
    this function raises, the wrapper falls back to the original subprocess
    call, preserving emergency compatibility.
    """

    prompt = _extract_prompt(cmd, kwargs)
    summary = prompt.replace("\r", " ").replace("\n", " ").strip()
    if len(summary) > 240:
        summary = summary[:237] + "..."

    body = (
        "brain-only claude -p circuit breaker engaged\n"
        "external claude invocation was suppressed by default\n"
    )
    if summary:
        body += f"prompt: {summary}\n"

    stdout: str | bytes
    stderr: str | bytes
    if _wants_text(kwargs):
        stdout = body
        stderr = ""
    else:
        stdout = body.encode("utf-8")
        stderr = b""

    return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr=stderr)


def _guarded_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    if _is_claude_p_command(cmd) and os.environ.get("CRAB_ALLOW_CLAUDE_P") != "1":
        try:
            return _brainonly_claude_p_run(cmd, *args, **kwargs)
        except Exception:
            return _ORIGINAL_RUN(cmd, *args, **kwargs)
    return _ORIGINAL_RUN(cmd, *args, **kwargs)


def _guarded_check_output(cmd: Any, *args: Any, **kwargs: Any) -> Any:
    if _is_claude_p_command(cmd) and os.environ.get("CRAB_ALLOW_CLAUDE_P") != "1":
        completed = _guarded_run(
            cmd,
            *args,
            stdout=subprocess.PIPE,
            stderr=kwargs.pop("stderr", subprocess.PIPE),
            **kwargs,
        )
        if completed.returncode:
            raise subprocess.CalledProcessError(
                completed.returncode,
                cmd,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed.stdout
    return _ORIGINAL_CHECK_OUTPUT(cmd, *args, **kwargs)


def _guarded_check_call(cmd: Any, *args: Any, **kwargs: Any) -> int:
    if _is_claude_p_command(cmd) and os.environ.get("CRAB_ALLOW_CLAUDE_P") != "1":
        completed = _guarded_run(cmd, *args, **kwargs)
        if completed.returncode:
            raise subprocess.CalledProcessError(completed.returncode, cmd)
        return 0
    return _ORIGINAL_CHECK_CALL(cmd, *args, **kwargs)


subprocess.run = _guarded_run
subprocess.check_output = _guarded_check_output
subprocess.check_call = _guarded_check_call
