"""Utilities for clearing unnamed/unknown organs.

This module keeps the work deliberately small and safe: it can run minimal
verification for Python modules and attach three navigation labels:

- purpose: why this organ appears to exist
- evidence: what lightweight check supports keeping it visible
- debt: what remains unclear or risky

It is import-safe and uses only the standard library.
"""

from __future__ import annotations

import importlib
import py_compile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class OrganClearance:
    """A compact clearance card for one Python organ."""

    module: str
    path: str
    compile_ok: bool
    import_ok: bool | None
    purpose: str
    evidence: str
    debt: str

    @property
    def is_cleared(self) -> bool:
        """Return True when the organ passed all checks that were requested."""

        return self.compile_ok and self.import_ok is not False


_PURPOSE_HINTS: tuple[tuple[str, str], ...] = (
    ("regression", "guards a previously observed behavior against relapse"),
    ("drill", "rehearses a recovery, release, onboarding, or autonomy motion"),
    ("gate", "decides whether a change may proceed under stated constraints"),
    ("audit", "inspects behavior, evidence, permissions, or dependencies"),
    ("evidence", "collects, checks, or strengthens support for decisions"),
    ("weaning", "reduces reliance on external help or unsafe default paths"),
    ("handoff", "transfers context or responsibility across actors or stages"),
    ("interop", "checks compatibility between neighboring organs or formats"),
    ("replay", "re-runs prior traces to expose drift or regressions"),
    ("redteam", "probes adversarial or failure-oriented behavior"),
    ("privacy", "protects sensitive data boundaries"),
    ("supplychain", "checks dependency and provenance risk"),
    ("onboarding", "helps a new user or agent reach useful operation"),
    ("coldstart", "supports survival from sparse context"),
    ("retirement", "removes low-value or unsafe organs deliberately"),
)


def module_name_from_path(path: str | Path, root: str | Path = ".") -> str:
    """Return an import-style module name for a Python file under *root*."""

    file_path = Path(path)
    try:
        rel = file_path.resolve().relative_to(Path(root).resolve())
    except ValueError:
        rel = file_path
    return ".".join(rel.with_suffix("").parts)


def infer_purpose(module: str) -> str:
    """Infer a conservative purpose label from a module name."""

    lowered = module.lower().replace(".", "_")
    for token, purpose in _PURPOSE_HINTS:
        if token in lowered:
            return purpose
    return "unknown-purpose organ requiring one-line owner/use clarification"


def _compile(path: Path) -> tuple[bool, str]:
    try:
        py_compile.compile(str(path), doraise=True)
    except Exception as exc:  # pragma: no cover - exact compiler errors vary.
        return False, f"py_compile failed: {exc.__class__.__name__}: {exc}"
    return True, "py_compile passed"


def _try_import(module: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module)
    except Exception as exc:  # pragma: no cover - import side effects vary.
        return False, f"import failed: {exc.__class__.__name__}: {exc}"
    return True, "import passed"


def clear_organ(
    path: str | Path,
    root: str | Path = ".",
    *,
    import_check: bool = False,
) -> OrganClearance:
    """Run minimal verification and produce labels for one organ.

    Import checks are opt-in because some repository modules may be CLI-like or
    have intentional side effects. Compilation is always checked.
    """

    file_path = Path(path)
    module = module_name_from_path(file_path, root)
    compile_ok, compile_evidence = _compile(file_path)

    import_ok: bool | None = None
    evidence_parts = [compile_evidence]
    if import_check and compile_ok:
        import_ok, import_evidence = _try_import(module)
        evidence_parts.append(import_evidence)

    if not compile_ok:
        debt = "syntax or compile failure blocks safe navigation"
    elif import_ok is False:
        debt = "import failure needs owner review before promotion from ?"
    elif infer_purpose(module).startswith("unknown-purpose"):
        debt = "purpose still inferred as unknown; add explicit owner/use note"
    else:
        debt = "keep label fresh when behavior or ownership changes"

    return OrganClearance(
        module=module,
        path=str(file_path),
        compile_ok=compile_ok,
        import_ok=import_ok,
        purpose=infer_purpose(module),
        evidence="; ".join(evidence_parts),
        debt=debt,
    )


def iter_python_files(root: str | Path = ".") -> Iterator[Path]:
    """Yield repository Python files, skipping common generated caches."""

    base = Path(root)
    for path in sorted(base.glob("*.py")):
        if path.name.startswith(".") or path.name == "sitecustomize.py":
            continue
        yield path


def clear_unknown_organs(
    paths: Iterable[str | Path] | None = None,
    root: str | Path = ".",
    *,
    import_check: bool = False,
) -> list[OrganClearance]:
    """Clear a batch of organs that are still shown as unknown elsewhere."""

    selected = list(paths) if paths is not None else list(iter_python_files(root))
    return [
        clear_organ(path, root=root, import_check=import_check)
        for path in selected
    ]


def format_clearance(card: OrganClearance) -> str:
    """Render a clearance card as one compact navigation line."""

    import_label = "not-requested" if card.import_ok is None else str(card.import_ok)
    return (
        f"{card.module}: purpose={card.purpose}; "
        f"evidence={card.evidence}; "
        f"compile_ok={card.compile_ok}; import_ok={import_label}; "
        f"debt={card.debt}"
    )
