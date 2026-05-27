"""Function-level read-pack trimming backed by :mod:`ast`.

This module is intentionally small and dependency-free so it can be used by
readpack/astlocator integration code without pulling in the rest of the system.

Main affordances:
- identify function/class spans from Python source;
- build compact, function-level read packs for low-risk patches;
- replay a small set of historical patches against the same trimming path.

The helpers accept in-memory source maps first.  That keeps tests and replay
drills deterministic, while callers may still pass real file paths through
``read_files`` when needed.
"""

from __future__ import annotations

import ast
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class AstSpan:
    """A source span discovered from AST line metadata."""

    path: str
    name: str
    kind: str
    start_line: int
    end_line: int

    def contains_line(self, line: int) -> bool:
        return self.start_line <= line <= self.end_line


@dataclass(frozen=True)
class ReadPackEntry:
    """A trimmed source excerpt suitable for focused repair."""

    path: str
    name: str
    kind: str
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class HistoricalPatchCase:
    """One replay case for validating context trimming behavior."""

    name: str
    before: Mapping[str, str]
    after: Mapping[str, str]
    expected_touched: int = 1


@dataclass(frozen=True)
class ReplayResult:
    """Outcome of one historical patch replay."""

    name: str
    ok: bool
    touched_entries: int
    reason: str


def read_files(paths: Iterable[str]) -> Dict[str, str]:
    """Return a ``path -> text`` map for UTF-8 Python files."""

    return {path: Path(path).read_text(encoding="utf-8") for path in paths}


def ast_spans(source: str, path: str = "<memory>") -> List[AstSpan]:
    """Locate function, async-function and class spans in *source*.

    Spans are sorted from narrowest to widest for deterministic nearest-owner
    selection.  Syntax errors yield an empty list instead of escaping; callers
    can then safely fall back to file-level context.
    """

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    spans: List[AstSpan] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end_line = getattr(node, "end_lineno", None)
            if isinstance(end_line, int):
                spans.append(
                    AstSpan(
                        path=path,
                        name=getattr(node, "name", "<anonymous>"),
                        kind=type(node).__name__,
                        start_line=int(node.lineno),
                        end_line=end_line,
                    )
                )

    spans.sort(key=lambda item: (item.end_line - item.start_line, item.start_line, item.name))
    return spans


def changed_lines(before: str, after: str) -> List[int]:
    """Return 1-based line numbers in *before* affected by a unified diff."""

    before_lines = before.splitlines()
    after_lines = after.splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    lines: List[int] = []

    for tag, a0, a1, _b0, _b1 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if a0 == a1:
            lines.append(max(1, a0))
        else:
            lines.extend(range(a0 + 1, a1 + 1))

    return sorted(set(lines))


def _excerpt(source: str, start_line: int, end_line: int, radius: int = 0) -> Tuple[int, int, str]:
    lines = source.splitlines()
    if not lines:
        return 1, 1, ""

    start = max(1, start_line - max(0, radius))
    end = min(len(lines), end_line + max(0, radius))
    return start, end, "\n".join(lines[start - 1 : end])


def function_level_readpack(
    before: Mapping[str, str],
    after: Mapping[str, str],
    *,
    context_radius: int = 0,
    max_entries: int = 8,
) -> List[ReadPackEntry]:
    """Build a compact read pack for changed Python functions/classes.

    ``before`` and ``after`` are source maps keyed by path.  Only changed paths
    ending in ``.py`` are considered.  For each touched line, the nearest AST
    span from the old source is selected.  If no span owns the line, a tiny
    line-level excerpt is emitted as ``kind="LineContext"``.
    """

    entries: List[ReadPackEntry] = []
    seen: set[Tuple[str, str, int, int]] = set()

    for path in sorted(set(before) | set(after)):
        if not path.endswith(".py"):
            continue
        old = before.get(path, "")
        new = after.get(path, "")
        if old == new:
            continue

        spans = ast_spans(old, path)
        for line in changed_lines(old, new):
            owner: Optional[AstSpan] = next((span for span in spans if span.contains_line(line)), None)

            if owner is None:
                start, end, text = _excerpt(old, line, line, context_radius)
                key = (path, "<line>", start, end)
                if key not in seen:
                    seen.add(key)
                    entries.append(
                        ReadPackEntry(
                            path=path,
                            name="<line>",
                            kind="LineContext",
                            start_line=start,
                            end_line=end,
                            text=text,
                        )
                    )
                continue

            start, end, text = _excerpt(old, owner.start_line, owner.end_line, context_radius)
            key = (path, owner.name, start, end)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                ReadPackEntry(
                    path=path,
                    name=owner.name,
                    kind=owner.kind,
                    start_line=start,
                    end_line=end,
                    text=text,
                )
            )

            if len(entries) >= max_entries:
                return entries

    return entries


def is_low_risk_patch(
    before: Mapping[str, str],
    after: Mapping[str, str],
    *,
    max_files: int = 2,
    max_changed_lines: int = 40,
) -> bool:
    """Heuristic gate for using function-level read packs.

    Low-risk means a small Python-only edit with bounded touched lines.
    """

    changed_paths = [path for path in sorted(set(before) | set(after)) if before.get(path, "") != after.get(path, "")]
    if not changed_paths or len(changed_paths) > max_files:
        return False
    if any(not path.endswith(".py") for path in changed_paths):
        return False

    total = 0
    for path in changed_paths:
        total += len(changed_lines(before.get(path, ""), after.get(path, "")))
        if total > max_changed_lines:
            return False

    return True


def low_risk_function_readpack(
    before: Mapping[str, str],
    after: Mapping[str, str],
    *,
    context_radius: int = 0,
) -> List[ReadPackEntry]:
    """Return a function-level read pack only when the patch is low-risk."""

    if not is_low_risk_patch(before, after):
        return []
    return function_level_readpack(before, after, context_radius=context_radius)


def replay_historical_patches(cases: Sequence[HistoricalPatchCase]) -> List[ReplayResult]:
    """Validate function-level trimming against historical patch cases."""

    results: List[ReplayResult] = []
    for case in cases:
        if not is_low_risk_patch(case.before, case.after):
            results.append(
                ReplayResult(
                    name=case.name,
                    ok=False,
                    touched_entries=0,
                    reason="patch was not classified as low-risk",
                )
            )
            continue

        pack = function_level_readpack(case.before, case.after)
        touched = len(pack)
        ok = touched == case.expected_touched
        results.append(
            ReplayResult(
                name=case.name,
                ok=ok,
                touched_entries=touched,
                reason="ok" if ok else f"expected {case.expected_touched} entries",
            )
        )

    return results


def three_builtin_replay_cases() -> List[HistoricalPatchCase]:
    """Return three tiny historical-style cases for smoke acceptance."""

    return [
        HistoricalPatchCase(
            name="single_return_fix",
            before={
                "calc.py": "def add(a, b):\n    return a - b\n\ndef untouched():\n    return 1\n",
            },
            after={
                "calc.py": "def add(a, b):\n    return a + b\n\ndef untouched():\n    return 1\n",
            },
        ),
        HistoricalPatchCase(
            name="guard_clause_fix",
            before={
                "gate.py": "def allowed(user):\n    if user is None:\n        return True\n    return user.active\n",
            },
            after={
                "gate.py": "def allowed(user):\n    if user is None:\n        return False\n    return user.active\n",
            },
        ),
        HistoricalPatchCase(
            name="method_constant_fix",
            before={
                "model.py": "class Meter:\n    def scale(self):\n        return 10\n\n    def label(self):\n        return 'm'\n",
            },
            after={
                "model.py": "class Meter:\n    def scale(self):\n        return 100\n\n    def label(self):\n        return 'm'\n",
            },
        ),
    ]


def replay_builtin_acceptance() -> bool:
    """Run the three built-in replay cases and return whether all pass."""

    return all(result.ok for result in replay_historical_patches(three_builtin_replay_cases()))
