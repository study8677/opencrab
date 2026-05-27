"""Process-wide startup hooks for crab.

The weaning drills must be able to run with external crutches unplugged.  This
module is imported automatically by Python when present on sys.path, so it is a
small, dependency-free guard against accidentally launching the Claude CLI from
any entrypoint in the hands/weaning chain.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any


_BLOCKED_EXTERNALS = {"claude"}
_ALLOW_ENV = "CRAB_ALLOW_EXTERNAL_CLAUDE"


def _command_name(cmd: Any) -> str:
    """Return the executable basename for a subprocess/os command."""

    if isinstance(cmd, (list, tuple)):
        if not cmd:
            return ""
        head = cmd[0]
    else:
        text = os.fspath(cmd) if isinstance(cmd, os.PathLike) else str(cmd)
        stripped = text.strip()
        if not stripped:
            return ""
        head = stripped.split()[0]

    try:
        return os.path.basename(os.fspath(head))
    except TypeError:
        return os.path.basename(str(head))


def _external_blocked(cmd: Any) -> bool:
    if os.environ.get(_ALLOW_ENV) == "1":
        return False
    return _command_name(cmd) in _BLOCKED_EXTERNALS


def _raise_blocked(cmd: Any) -> None:
    name = _command_name(cmd) or str(cmd)
    raise RuntimeError(
        f"external assistant disabled for weaning drill: {name!r}; "
        f"set {_ALLOW_ENV}=1 only for an explicit external-aid run"
    )


_ORIGINAL_POPEN = subprocess.Popen
_ORIGINAL_RUN = subprocess.run
_ORIGINAL_CALL = subprocess.call
_ORIGINAL_CHECK_CALL = subprocess.check_call
_ORIGINAL_CHECK_OUTPUT = subprocess.check_output
_ORIGINAL_OS_SYSTEM = os.system


class _GuardedPopen(_ORIGINAL_POPEN):
    def __init__(self, args: Any, *pargs: Any, **kwargs: Any) -> None:
        if _external_blocked(args):
            _raise_blocked(args)
        super().__init__(args, *pargs, **kwargs)


def _guarded_run(*popenargs: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    cmd = popenargs[0] if popenargs else kwargs.get("args")
    if _external_blocked(cmd):
        _raise_blocked(cmd)
    return _ORIGINAL_RUN(*popenargs, **kwargs)


def _guarded_call(*popenargs: Any, **kwargs: Any) -> int:
    cmd = popenargs[0] if popenargs else kwargs.get("args")
    if _external_blocked(cmd):
        _raise_blocked(cmd)
    return _ORIGINAL_CALL(*popenargs, **kwargs)


def _guarded_check_call(*popenargs: Any, **kwargs: Any) -> int:
    cmd = popenargs[0] if popenargs else kwargs.get("args")
    if _external_blocked(cmd):
        _raise_blocked(cmd)
    return _ORIGINAL_CHECK_CALL(*popenargs, **kwargs)


def _guarded_check_output(*popenargs: Any, **kwargs: Any) -> bytes:
    cmd = popenargs[0] if popenargs else kwargs.get("args")
    if _external_blocked(cmd):
        _raise_blocked(cmd)
    return _ORIGINAL_CHECK_OUTPUT(*popenargs, **kwargs)


def _guarded_system(command: Any) -> int:
    if _external_blocked(command):
        _raise_blocked(command)
    return _ORIGINAL_OS_SYSTEM(command)


subprocess.Popen = _GuardedPopen
subprocess.run = _guarded_run
subprocess.call = _guarded_call
subprocess.check_call = _guarded_check_call
subprocess.check_output = _guarded_check_output
os.system = _guarded_system
