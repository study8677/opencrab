"""Readpack-only blind self-drill for small, low-risk real functions.

The drill samples an existing Python function from the local tree, hides the
rest of the file from the patch-producing "brain", and optionally sends the
brain's patch through a patchfitroom callable.  It is intentionally small and
standalone so it can be used in rehearsals without coupling to private APIs.
"""

from __future__ import annotations

import ast
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


LOW_RISK_MAX_LINES = 40
LOW_RISK_MAX_ARGS = 6
DEFAULT_EXCLUDES = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "site-packages",
}


@dataclass(frozen=True)
class FunctionCandidate:
    """A sampled real function that is small enough for blind patch practice."""

    path: str
    name: str
    lineno: int
    end_lineno: int
    arg_count: int
    line_count: int


@dataclass(frozen=True)
class BlindTrial:
    """Result of one readpack-only blind patch attempt."""

    candidate: FunctionCandidate
    readpack: str
    patch_text: str
    fit_result: Any


def _iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        parts = set(path.parts)
        if parts.intersection(DEFAULT_EXCLUDES):
            continue
        if path.name.startswith("test_"):
            continue
        yield path


def _safe_source(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    except OSError:
        return None


def _arg_count(node: ast.FunctionDef) -> int:
    args = node.args
    return (
        len(args.posonlyargs)
        + len(args.args)
        + len(args.kwonlyargs)
        + (1 if args.vararg else 0)
        + (1 if args.kwarg else 0)
    )


def _looks_low_risk(node: ast.FunctionDef) -> bool:
    end_lineno = getattr(node, "end_lineno", None)
    if end_lineno is None:
        return False
    if node.decorator_list:
        return False
    if _arg_count(node) > LOW_RISK_MAX_ARGS:
        return False
    if end_lineno - node.lineno + 1 > LOW_RISK_MAX_LINES:
        return False

    risky_calls = {
        "open",
        "exec",
        "eval",
        "compile",
        "input",
        "__import__",
    }
    risky_attrs = {
        "remove",
        "unlink",
        "rmdir",
        "rename",
        "replace",
        "chmod",
        "chown",
        "system",
        "popen",
        "run",
        "call",
        "check_call",
        "check_output",
    }

    for child in ast.walk(node):
        if isinstance(child, (ast.Global, ast.Nonlocal, ast.Delete, ast.Yield, ast.YieldFrom)):
            return False
        if isinstance(child, ast.Await):
            return False
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name) and func.id in risky_calls:
                return False
            if isinstance(func, ast.Attribute) and func.attr in risky_attrs:
                return False
    return True


def discover_low_risk_functions(root: str | Path = ".") -> list[FunctionCandidate]:
    """Return small real functions suitable for blind patch drills."""

    base = Path(root)
    found: list[FunctionCandidate] = []
    for path in _iter_python_files(base):
        source = _safe_source(path)
        if not source:
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not _looks_low_risk(node):
                continue
            end_lineno = int(getattr(node, "end_lineno"))
            try:
                rel = str(path.relative_to(base))
            except ValueError:
                rel = str(path)
            found.append(
                FunctionCandidate(
                    path=rel,
                    name=node.name,
                    lineno=node.lineno,
                    end_lineno=end_lineno,
                    arg_count=_arg_count(node),
                    line_count=end_lineno - node.lineno + 1,
                )
            )
    return found


def make_readpack(candidate: FunctionCandidate, root: str | Path = ".") -> str:
    """Build the only context shown to the brain for a candidate function."""

    path = Path(root) / candidate.path
    source = _safe_source(path)
    if source is None:
        raise FileNotFoundError(candidate.path)

    lines = source.splitlines()
    start = max(1, candidate.lineno)
    end = min(len(lines), candidate.end_lineno)
    snippet = "\n".join(
        f"{lineno:04d}: {lines[lineno - 1]}"
        for lineno in range(start, end + 1)
    )

    return "\n".join(
        [
            "READPACK_ONLY_BLIND_SELF_DRILL",
            f"path: {candidate.path}",
            f"function: {candidate.name}",
            f"span: {candidate.lineno}-{candidate.end_lineno}",
            f"args: {candidate.arg_count}",
            f"lines: {candidate.line_count}",
            "constraints:",
            "- produce the smallest safe patch",
            "- do not assume unseen file context",
            "- prefer no-op clarification if evidence is insufficient",
            "source:",
            snippet,
        ]
    )


def default_patchfitroom(patch_text: str, readpack: str) -> dict[str, Any]:
    """Conservative local fitroom fallback when no project fitroom is injected."""

    ok = bool(patch_text and patch_text.strip())
    has_contract_shape = (
        "<<<EDIT " in patch_text
        or "<<<WRITE " in patch_text
        or "---OLD---" in patch_text
    )
    return {
        "ok": ok and has_contract_shape,
        "reason": "patch has expected text contract shape" if has_contract_shape else "missing patch contract markers",
        "readpack_bytes": len(readpack.encode("utf-8")),
        "patch_bytes": len(patch_text.encode("utf-8")) if patch_text else 0,
    }


Brain = Callable[[str], str]
PatchFitroom = Callable[[str, str], Any]


def run_blind_trial(
    brain: Brain,
    patchfitroom: PatchFitroom | None = None,
    root: str | Path = ".",
    seed: int | None = None,
    candidates: Iterable[FunctionCandidate] | None = None,
) -> BlindTrial:
    """Sample one low-risk function, ask brain using only readpack, then fit it.

    The brain callable receives exactly one string: the readpack.  It is not
    handed the path object, full file contents, or candidate object.
    """

    pool = list(candidates) if candidates is not None else discover_low_risk_functions(root)
    if not pool:
        raise RuntimeError("no low-risk function candidates found")

    rng = random.Random(seed)
    candidate = rng.choice(pool)
    readpack = make_readpack(candidate, root=root)
    patch_text = brain(readpack)
    fit = patchfitroom or default_patchfitroom
    fit_result = fit(patch_text, readpack)
    return BlindTrial(
        candidate=candidate,
        readpack=readpack,
        patch_text=patch_text,
        fit_result=fit_result,
    )


def dry_brain(readpack: str) -> str:
    """A safe placeholder brain for smoke tests; it intentionally changes nothing."""

    del readpack
    return "NOTE: dry run only; no patch proposed"


def smoke(root: str | Path = ".", seed: int = 0) -> dict[str, Any]:
    """Run a deterministic no-write smoke check of the blind drill machinery."""

    trial = run_blind_trial(dry_brain, root=root, seed=seed)
    return {
        "candidate": trial.candidate,
        "fit_result": trial.fit_result,
        "readpack_only": "source:" in trial.readpack and "READPACK_ONLY" in trial.readpack,
    }


if __name__ == "__main__":
    result = smoke()
    print(result)
