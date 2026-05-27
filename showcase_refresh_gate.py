"""Refresh gate for the public showcase page.

This module keeps ``docs/index.html`` honest without relying on shell tools.
It inspects the live repository, derives evidence-backed counts, and can emit
a unified diff patch that refreshes the showcase freshness block.

Typical use::

    python showcase_refresh_gate.py
    python showcase_refresh_gate.py --check

Exit codes:
    0: no refresh needed, or patch printed successfully
    1: target page missing
    2: --check found that a refresh patch is needed
"""

from __future__ import annotations

import argparse
import ast
import difflib
import html
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
import zlib


START = "<!-- crab-showcase-refresh:start -->"
END = "<!-- crab-showcase-refresh:end -->"


@dataclass(frozen=True)
class ShowcaseFacts:
    """Evidence visible to the outside world."""

    module_count: int
    commit_count: int
    skill_count: int
    head: str
    checked_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def find_repo_root(start: Optional[Path] = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for path in (here, *here.parents):
        if (path / "crab.py").exists() or (path / ".git").exists():
            return path
    return here


def iter_python_files(root: Path) -> Iterable[Path]:
    ignored_dirs = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv"}
    for path in sorted(root.rglob("*.py")):
        if any(part in ignored_dirs for part in path.parts):
            continue
        yield path


def count_modules(root: Path) -> int:
    return sum(1 for _ in iter_python_files(root))


def count_public_skills(root: Path) -> int:
    """Count public Python definitions as a stable local proxy for skills."""

    total = 0
    for path in iter_python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    total += 1
    return total


def resolve_git_dir(root: Path) -> Optional[Path]:
    git = root / ".git"
    if git.is_dir():
        return git
    if git.is_file():
        try:
            text = git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        prefix = "gitdir:"
        if text.lower().startswith(prefix):
            return (git.parent / text[len(prefix) :].strip()).resolve()
    return None


def read_head(git_dir: Optional[Path]) -> str:
    if git_dir is None:
        return "unknown"
    try:
        head_text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if head_text.startswith("ref:"):
        ref = head_text[4:].strip()
        ref_path = git_dir / ref
        try:
            return ref_path.read_text(encoding="utf-8").strip()[:12]
        except OSError:
            packed = git_dir / "packed-refs"
            try:
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line and not line.startswith("#") and line.endswith(" " + ref):
                        return line.split(" ", 1)[0][:12]
            except OSError:
                pass
            return "unknown"
    return head_text[:12] if head_text else "unknown"


def count_reflog_commits(git_dir: Path) -> int:
    log = git_dir / "logs" / "HEAD"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    seen = {
        line.split(" ", 2)[1]
        for line in lines
        if len(line.split(" ", 2)) >= 2 and not line.split(" ", 2)[1].startswith("0000000")
    }
    return len(seen)


def count_loose_commit_objects(git_dir: Path) -> int:
    objects = git_dir / "objects"
    if not objects.is_dir():
        return 0
    total = 0
    for bucket in objects.iterdir():
        if not bucket.is_dir() or len(bucket.name) != 2 or bucket.name in {"info", "pack"}:
            continue
        for obj in bucket.iterdir():
            if not obj.is_file():
                continue
            try:
                raw = zlib.decompress(obj.read_bytes(), max_length=32)
            except (OSError, zlib.error):
                continue
            if raw.startswith(b"commit "):
                total += 1
    return total


def count_commits(root: Path) -> int:
    git_dir = resolve_git_dir(root)
    if git_dir is None:
        return 0
    return max(count_reflog_commits(git_dir), count_loose_commit_objects(git_dir))


def collect_facts(root: Optional[Path] = None) -> ShowcaseFacts:
    repo = find_repo_root(root)
    git_dir = resolve_git_dir(repo)
    return ShowcaseFacts(
        module_count=count_modules(repo),
        commit_count=count_commits(repo),
        skill_count=count_public_skills(repo),
        head=read_head(git_dir),
        checked_at=utc_now(),
    )


def render_block(facts: ShowcaseFacts) -> str:
    return "\n".join(
        [
            START,
            (
                '<section id="crab-showcase-refresh" '
                f'data-modules="{facts.module_count}" '
                f'data-commits="{facts.commit_count}" '
                f'data-skills="{facts.skill_count}" '
                f'data-head="{html.escape(facts.head, quote=True)}" '
                f'data-checked-at="{html.escape(facts.checked_at, quote=True)}">'
            ),
            "  <h2>Freshness evidence</h2>",
            "  <ul>",
            f"    <li>Python modules: {facts.module_count}</li>",
            f"    <li>Observed commits: {facts.commit_count}</li>",
            f"    <li>Public skills: {facts.skill_count}</li>",
            f"    <li>HEAD: {html.escape(facts.head)}</li>",
            f"    <li>Checked at: {html.escape(facts.checked_at)}</li>",
            "  </ul>",
            "</section>",
            END,
        ]
    )


def replace_or_insert_block(document: str, block: str) -> str:
    if START in document and END in document:
        before, rest = document.split(START, 1)
        _old, after = rest.split(END, 1)
        return before + block + after
    lower = document.lower()
    body_at = lower.rfind("</body>")
    insertion = "\n" + block + "\n"
    if body_at >= 0:
        return document[:body_at] + insertion + document[body_at:]
    suffix = "" if document.endswith("\n") else "\n"
    return document + suffix + block + "\n"


def build_patch(index_path: Path, facts: Optional[ShowcaseFacts] = None) -> str:
    old = index_path.read_text(encoding="utf-8")
    new = replace_or_insert_block(old, render_block(facts or collect_facts(index_path.parent)))
    if old == new:
        return ""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=str(index_path),
            tofile=str(index_path),
        )
    )


def default_index(root: Optional[Path] = None) -> Path:
    return find_repo_root(root) / "docs" / "index.html"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Emit a freshness patch for docs/index.html.")
    parser.add_argument("--index", type=Path, default=None, help="Path to docs/index.html")
    parser.add_argument("--check", action="store_true", help="Exit 2 when a refresh patch is needed")
    args = parser.parse_args(argv)

    index_path = args.index or default_index()
    if not index_path.exists():
        print(f"missing showcase page: {index_path}")
        return 1

    patch = build_patch(index_path)
    if patch:
        print(patch, end="")
        return 2 if args.check else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
