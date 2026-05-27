"""Self-drill for a low-risk two-function brain patch.

The drill is intentionally self-contained: a tiny in-memory module is patched in
two cooperating functions, then checked by a fit-room compile/import pass and a
fresh replay pass.  It gives the hand a deterministic, side-effect-light way to
practice coordinated edits before touching larger files.
"""

from __future__ import annotations

import importlib.util
import py_compile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class DualFunctionRun:
    """Evidence produced by the two-function self-drill."""

    changed_functions: tuple[str, str]
    fitroom_ok: bool
    replay_ok: bool
    before: str
    after: str


def baseline_source() -> str:
    """Return the tiny module that the brain will patch."""

    return '''def normalize_status(status):
    """Return a compact status token."""
    return str(status).strip().lower()


def render_status(status):
    """Render a status token for human-facing evidence."""
    return "status=" + normalize_status(status)
'''


def brain_dual_function_patch(source: str) -> str:
    """Apply one coordinated low-risk patch across two real functions.

    The first function learns a safe empty-value fallback.  The second function
    consumes the normalized value once, avoiding duplicate normalization while
    preserving the same external format.
    """

    old_normalize = '''def normalize_status(status):
    """Return a compact status token."""
    return str(status).strip().lower()
'''
    new_normalize = '''def normalize_status(status):
    """Return a compact status token."""
    token = str(status).strip().lower()
    return token or "unknown"
'''
    old_render = '''def render_status(status):
    """Render a status token for human-facing evidence."""
    return "status=" + normalize_status(status)
'''
    new_render = '''def render_status(status):
    """Render a status token for human-facing evidence."""
    token = normalize_status(status)
    return "status=" + token
'''

    if source.count(old_normalize) != 1:
        raise ValueError("normalize_status patch target is not unique")
    if source.count(old_render) != 1:
        raise ValueError("render_status patch target is not unique")
    return source.replace(old_normalize, new_normalize).replace(old_render, new_render)


def fitroom_import_source(source: str) -> ModuleType:
    """Compile and import patched source in a temporary fit room."""

    with tempfile.TemporaryDirectory(prefix="crab_dual_function_fitroom_") as tmp:
        path = Path(tmp) / "candidate.py"
        path.write_text(source, encoding="utf-8")
        py_compile.compile(str(path), doraise=True)

        spec = importlib.util.spec_from_file_location("candidate_dual_function", path)
        if spec is None or spec.loader is None:
            raise ImportError("could not create import spec for fitroom candidate")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def replay_patch(expected_source: str) -> bool:
    """Replay the same brain patch from a fresh baseline and compare output."""

    replayed = brain_dual_function_patch(baseline_source())
    return replayed == expected_source


def run_dual_function_drill() -> DualFunctionRun:
    """Execute the brain patch, fit-room validation, and replay validation."""

    before = baseline_source()
    after = brain_dual_function_patch(before)
    module = fitroom_import_source(after)

    fitroom_ok = (
        module.normalize_status("  OK  ") == "ok"
        and module.normalize_status("   ") == "unknown"
        and module.render_status("  READY ") == "status=ready"
    )
    replay_ok = replay_patch(after)

    return DualFunctionRun(
        changed_functions=("normalize_status", "render_status"),
        fitroom_ok=fitroom_ok,
        replay_ok=replay_ok,
        before=before,
        after=after,
    )


if __name__ == "__main__":
    result = run_dual_function_drill()
    if not (result.fitroom_ok and result.replay_ok):
        raise SystemExit(1)
    print("dual-function drill passed")
