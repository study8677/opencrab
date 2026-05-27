"""Residual external-AI dependency map for weaning work.

This module is intentionally self contained and conservative: it does not call
any network/API/client code.  It scans local Python sources for hot-path entry
points that still mention common external-AI integration tokens, then ranks the
entries by likely runtime exposure and suggests a replacement order.

Use from Python:
    from weaning_residual_map import build_residual_dependency_map

Use as CLI:
    python weaning_residual_map.py
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


EXTERNAL_AI_TOKENS: Tuple[str, ...] = (
    "anthropic",
    "claude",
    "openai",
    "chat.completions",
    "responses.create",
    "completion",
    "llm",
    "language_model",
    "external ai",
    "external_ai",
    "delegate",
    "relay",
)

HOTPATH_TOKENS: Tuple[str, ...] = (
    "crab.py",
    "hands",
    "route",
    "delegate",
    "weaning",
    "planner",
    "patch",
    "release",
    "gate",
    "hotpath",
    "brainonly",
)

SAFE_REPLACEMENT_ORDER: Tuple[str, ...] = (
    "prefer existing brain-only/pure function path",
    "route through local evidence/readpack/replay data",
    "use deterministic heuristic or cached fixture",
    "require explicit external-cooldown waiver before any external AI call",
)


@dataclass(frozen=True)
class ResidualDependency:
    """A suspected remaining path to external AI."""

    path: str
    symbol: str
    line: int
    matched_tokens: Tuple[str, ...]
    hotpath_score: int
    replacement_order: Tuple[str, ...]

    @property
    def severity(self) -> str:
        if self.hotpath_score >= 4:
            return "hot"
        if self.hotpath_score >= 2:
            return "warm"
        return "cold"

    def as_row(self) -> str:
        tokens = ",".join(self.matched_tokens)
        return (
            f"{self.severity}\t{self.path}:{self.line}\t{self.symbol}\t"
            f"tokens={tokens}\treplace={self.replacement_order[0]}"
        )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _iter_py_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.glob("*.py")):
        if path.name.startswith("."):
            continue
        yield path


def _matched_tokens(text: str, tokens: Sequence[str] = EXTERNAL_AI_TOKENS) -> Tuple[str, ...]:
    low = text.lower()
    return tuple(token for token in tokens if token.lower() in low)


def _hotpath_score(path: Path, symbol: str, source_line: str) -> int:
    haystack = f"{path.name} {symbol} {source_line}".lower()
    score = sum(1 for token in HOTPATH_TOKENS if token.lower() in haystack)
    if symbol in {"main", "run", "route", "delegate", "apply", "plan", "execute"}:
        score += 1
    return score


def _symbol_name(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    return "<module>"


def _candidate_nodes(tree: ast.AST) -> Iterable[ast.AST]:
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node


def scan_file(path: Path, root: Path | None = None) -> List[ResidualDependency]:
    """Scan one Python file for suspected residual external-AI entries."""

    text = _read_text(path)
    if not _matched_tokens(text):
        return []

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    lines = text.splitlines()
    findings: List[ResidualDependency] = []
    seen = set()

    for node in _candidate_nodes(tree):
        if isinstance(node, ast.Module):
            start = 1
            end = len(lines)
            symbol = "<module>"
        else:
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start)
            symbol = _symbol_name(node)

        snippet = "\n".join(lines[max(0, start - 1) : end])
        tokens = _matched_tokens(snippet)
        if not tokens:
            continue

        source_line = lines[start - 1] if lines and 0 <= start - 1 < len(lines) else ""
        score = _hotpath_score(path, symbol, source_line)
        rel = str(path.relative_to(root)) if root else path.name
        key = (rel, symbol, start)
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            ResidualDependency(
                path=rel,
                symbol=symbol,
                line=start,
                matched_tokens=tokens,
                hotpath_score=score,
                replacement_order=SAFE_REPLACEMENT_ORDER,
            )
        )

    return findings


def build_residual_dependency_map(root: str | os.PathLike[str] = ".") -> List[ResidualDependency]:
    """Return suspected residual external-AI entries, hottest first."""

    base = Path(root)
    findings: List[ResidualDependency] = []
    for path in _iter_py_files(base):
        findings.extend(scan_file(path, base))

    return sorted(
        findings,
        key=lambda item: (-item.hotpath_score, item.path, item.line, item.symbol),
    )


def render_residual_dependency_map(findings: Sequence[ResidualDependency]) -> str:
    """Render a compact human-readable dependency map."""

    if not findings:
        return "断奶残依赖地图: 未发现疑似外部 AI 残依赖入口"

    rows = [
        "断奶残依赖地图: 疑似仍会间接调用外部 AI 的入口",
        "severity\tlocation\tsymbol\tmatched\treplacement-first-step",
    ]
    rows.extend(item.as_row() for item in findings)
    rows.append("替代顺序:")
    for index, step in enumerate(SAFE_REPLACEMENT_ORDER, 1):
        rows.append(f"{index}. {step}")
    return "\n".join(rows)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv or [])
    root = args[0] if args else "."
    findings = build_residual_dependency_map(root)
    print(render_residual_dependency_map(findings))
    return 1 if any(item.severity == "hot" for item in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
