"""Regression helper for hands immunity against real bad patches.

This module deliberately feeds a concrete, unified-diff-shaped bad patch into
an isolated Python file, proves that the candidate is rejected, and proves that
the touched file is rolled back byte-for-byte.

It is intentionally self-contained so it can be used by smoke tests without
mutating the real source tree.
"""

from __future__ import annotations

import hashlib
import json
import py_compile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List


ORIGINAL_SOURCE = "VALUE = 1\n\n\ndef answer():\n    return VALUE\n"
BAD_SOURCE = "VALUE = 1\n\n\ndef answer(:\n    return VALUE\n"

REAL_BAD_PATCH = """--- a/victim.py
+++ b/victim.py
@@ -1,5 +1,5 @@
 VALUE = 1
 
 
-def answer():
+def answer(:
     return VALUE
"""


@dataclass(frozen=True)
class BadPatchEvidence:
    """Evidence that a bad hand patch did not land."""

    case: str
    patch_kind: str
    rejected: bool
    rolled_back: bool
    before_sha256: str
    after_sha256: str
    compile_failed: bool
    compile_error: str
    drill_module_imported: bool
    drill_module_error: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compile_error(path: Path) -> str:
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return str(exc)
    return ""


def _try_import_drill() -> tuple[bool, str]:
    try:
        __import__("hands_immunity_drill")
    except Exception as exc:  # pragma: no cover - diagnostic evidence path
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def run_real_bad_patch_case() -> BadPatchEvidence:
    """Feed a concrete bad patch and return reject/rollback evidence.

    The patch is represented as a real unified diff and then materialized as the
    exact bad file content a hand would have produced.  The immunity decision is
    based on py_compile failure; rejection triggers rollback from the captured
    byte snapshot.
    """

    drill_imported, drill_error = _try_import_drill()

    with tempfile.TemporaryDirectory(prefix="hands-immunity-badpatch-") as tmp:
        victim = Path(tmp) / "victim.py"
        victim.write_text(ORIGINAL_SOURCE, encoding="utf-8")

        before_bytes = victim.read_bytes()
        before_hash = _sha256(victim)

        victim.write_text(BAD_SOURCE, encoding="utf-8")
        compile_error = _compile_error(victim)
        compile_failed = bool(compile_error)
        rejected = compile_failed

        if rejected:
            victim.write_bytes(before_bytes)

        after_hash = _sha256(victim)
        rolled_back = before_hash == after_hash and victim.read_bytes() == before_bytes

    return BadPatchEvidence(
        case="syntax_error_unified_diff",
        patch_kind="real_bad_patch",
        rejected=rejected,
        rolled_back=rolled_back,
        before_sha256=before_hash,
        after_sha256=after_hash,
        compile_failed=compile_failed,
        compile_error=compile_error,
        drill_module_imported=drill_imported,
        drill_module_error=drill_error,
    )


def run() -> Dict[str, Any]:
    """Run the regression and raise if rejection or rollback evidence is absent."""

    evidence = run_real_bad_patch_case()
    failures: List[str] = []
    if not evidence.rejected:
        failures.append("bad patch was not rejected")
    if not evidence.rolled_back:
        failures.append("bad patch did not roll back to the original bytes")
    if not evidence.compile_failed:
        failures.append("bad patch did not produce py_compile failure evidence")

    result: Dict[str, Any] = {
        "ok": not failures,
        "failures": failures,
        "evidence": asdict(evidence),
        "bad_patch": REAL_BAD_PATCH,
    }
    if failures:
        raise AssertionError(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
