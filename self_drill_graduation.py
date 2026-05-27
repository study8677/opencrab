"""Self-contained graduation drill evidence for the opencrab hand.

This module is intentionally dependency-light: it demonstrates the
astlocator -> patchfitroom -> regression chain with pure Python helpers so it
can be compiled and imported even when the wider toolchain is unavailable.
"""

from __future__ import annotations

import ast
import importlib
import py_compile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class DrillEvidence:
    """Compact evidence produced by the graduation drill."""

    target: str
    located_kind: str
    located_name: str
    patch_unique: bool
    compile_ok: bool
    import_ok: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "located_kind": self.located_kind,
            "located_name": self.located_name,
            "patch_unique": self.patch_unique,
            "compile_ok": self.compile_ok,
            "import_ok": self.import_ok,
        }


def astlocator_first_definition(source: str) -> tuple[str, str]:
    """Return the first class/function definition as astlocator-style proof."""

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            return ("class", node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ("function", node.name)
    return ("module", "<module>")


def patchfitroom_unique_replace(source: str, old: str, new: str) -> str:
    """Apply a patch only when the old text occurs exactly once."""

    count = source.count(old)
    if count != 1:
        raise ValueError(f"patch does not fit uniquely: occurrences={count}")
    return source.replace(old, new, 1)


def regression_compile(paths: Iterable[str | Path]) -> bool:
    """Compile selected Python files as a minimal regression gate."""

    for path in paths:
        py_compile.compile(str(path), doraise=True)
    return True


def regression_import(module_names: Sequence[str]) -> bool:
    """Import selected modules as a minimal regression gate."""

    for name in module_names:
        importlib.import_module(name)
    return True


def run_graduation_drill(
    target_path: str | Path = "self_drill_graduation.py",
    import_names: Sequence[str] = ("crab",),
) -> DrillEvidence:
    """Run the local graduation drill and return auditable evidence."""

    path = Path(target_path)
    source = path.read_text(encoding="utf-8")
    located_kind, located_name = astlocator_first_definition(source)

    probe_old = "dependency-light"
    probe_new = "dependency-light"
    patchfitroom_unique_replace(source, probe_old, probe_new)

    compile_ok = regression_compile((path,))
    import_ok = regression_import(import_names)

    return DrillEvidence(
        target=str(path),
        located_kind=located_kind,
        located_name=located_name,
        patch_unique=True,
        compile_ok=compile_ok,
        import_ok=import_ok,
    )


__all__ = [
    "DrillEvidence",
    "astlocator_first_definition",
    "patchfitroom_unique_replace",
    "regression_compile",
    "regression_import",
    "run_graduation_drill",
]
