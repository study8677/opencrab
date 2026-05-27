"""Unknown-organ clearance notes for small, previously "?" modules.

This module is intentionally read-only: it imports candidate organs, inspects
their public surface, and returns a compact settlement report.  It is meant to
turn "unknown" into one of:

* documented: importable and has an observable public API;
* retire-candidate: absent, unimportable, or effectively empty.

The first clearance batch covers ``autonomy_meter`` and ``hands_astbridge``.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


CLEARANCE_TARGETS: Tuple[str, ...] = (
    "autonomy_meter",
    "hands_astbridge",
)


@dataclass(frozen=True)
class OrganClearance:
    """A measured status line for one candidate organ."""

    module: str
    importable: bool
    public_callables: Tuple[str, ...]
    public_constants: Tuple[str, ...]
    note: str
    retire_candidate: bool


def _public_members(module_name: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    module = importlib.import_module(module_name)
    callables: List[str] = []
    constants: List[str] = []

    for name, value in inspect.getmembers(module):
        if name.startswith("_"):
            continue
        if inspect.ismodule(value):
            continue
        if inspect.isfunction(value) or inspect.isclass(value):
            callables.append(name)
        elif isinstance(value, (str, int, float, bool, tuple, list, dict, set, frozenset, type(None))):
            constants.append(name)

    return tuple(sorted(callables)), tuple(sorted(constants))


def measure_unknown_organs(targets: Iterable[str] = CLEARANCE_TARGETS) -> Dict[str, OrganClearance]:
    """Import and classify candidate unknown organs.

    The function is deliberately conservative: an import failure or a module
    with no public callable/constant surface is marked as a retirement
    candidate.  Importable modules with any public surface are treated as
    documented rather than retired.
    """

    report: Dict[str, OrganClearance] = {}

    for module_name in targets:
        try:
            callables, constants = _public_members(module_name)
        except Exception as exc:  # pragma: no cover - diagnostic path
            report[module_name] = OrganClearance(
                module=module_name,
                importable=False,
                public_callables=(),
                public_constants=(),
                note=f"import failed during clearance probe: {exc.__class__.__name__}: {exc}",
                retire_candidate=True,
            )
            continue

        if callables or constants:
            note = (
                "importable; public surface observed "
                f"({len(callables)} callables, {len(constants)} constants)"
            )
            retire_candidate = False
        else:
            note = "importable but no public surface observed; keep on retirement watch"
            retire_candidate = True

        report[module_name] = OrganClearance(
            module=module_name,
            importable=True,
            public_callables=callables,
            public_constants=constants,
            note=note,
            retire_candidate=retire_candidate,
        )

    return report


def clearance_summary(targets: Iterable[str] = CLEARANCE_TARGETS) -> str:
    """Return a stable human-readable summary for clearance ledgers."""

    rows = []
    for module_name, item in sorted(measure_unknown_organs(targets).items()):
        status = "retire-candidate" if item.retire_candidate else "documented"
        rows.append(
            f"{module_name}: {status}; importable={item.importable}; "
            f"callables={list(item.public_callables)}; constants={list(item.public_constants)}; "
            f"note={item.note}"
        )
    return "\n".join(rows)


if __name__ == "__main__":
    print(clearance_summary())
