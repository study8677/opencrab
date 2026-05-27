"""Brain-only default route for low-risk documentation fixes.

This module gives weaning a concrete, low-risk target: small documentation text
repairs are attempted locally first.  External help is only used as a degrade
path after the brain-only attempt fails, and every route decision can be audited
as JSONL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Callable, Iterable, Optional


ExternalFixer = Callable[[str], str]


@dataclass(frozen=True)
class DocfixAudit:
    """One auditable routing decision for a low-risk documentation fix."""

    route: str
    status: str
    reason: str
    changed: bool
    input_chars: int
    output_chars: int
    external_used: bool
    target: str = "low_risk_docfix"
    timestamp: str = ""

    def to_json(self) -> str:
        payload = asdict(self)
        if not payload["timestamp"]:
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class DocfixResult:
    """Result returned by the default route."""

    text: str
    audit: DocfixAudit


_DEFAULT_REPLACEMENTS = {
    "teh": "the",
    "recieve": "receive",
    "adress": "address",
    "occured": "occurred",
    "seperate": "separate",
    "definately": "definitely",
    "sucess": "success",
    "succcess": "success",
    "faild": "failed",
    "errored out": "failed",
}


def _apply_word_replacements(text: str, replacements: dict[str, str]) -> str:
    fixed = text
    for wrong, right in replacements.items():
        fixed = re.sub(rf"\b{re.escape(wrong)}\b", right, fixed)
        fixed = re.sub(
            rf"\b{re.escape(wrong.capitalize())}\b",
            right.capitalize(),
            fixed,
        )
    return fixed


def brain_only_docfix(
    text: str,
    *,
    replacements: Optional[dict[str, str]] = None,
) -> str:
    """Apply deterministic low-risk documentation repairs without assistance.

    The operation is intentionally conservative: typo replacements, trailing
    whitespace removal, excess blank-line collapse, and spacing after sentence
    punctuation.  It raises ValueError when no safe local edit is available so
    the caller can degrade explicitly.
    """

    if not isinstance(text, str):
        raise TypeError("text must be str")

    table = dict(_DEFAULT_REPLACEMENTS)
    if replacements:
        table.update(replacements)

    fixed = _apply_word_replacements(text, table)
    fixed = "\n".join(line.rstrip() for line in fixed.splitlines())
    fixed = re.sub(r"\n{3,}", "\n\n", fixed)
    fixed = re.sub(r"([.!?]) {2,}([A-Z0-9])", r"\1 \2", fixed)

    if text.endswith("\n") and not fixed.endswith("\n"):
        fixed += "\n"

    if fixed == text:
        raise ValueError("brain-only docfix produced no safe change")

    return fixed


def append_audit(path: str | Path, audit: DocfixAudit) -> None:
    """Append one JSONL audit event."""

    audit_path = Path(path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(audit.to_json())
        handle.write("\n")


def route_low_risk_docfix(
    text: str,
    *,
    external_fixer: Optional[ExternalFixer] = None,
    audit_path: str | Path | None = None,
) -> DocfixResult:
    """Default a real low-risk doc edit to brain-only, then degrade if needed.

    Route order:
    1. Attempt ``brain_only_docfix``.
    2. If it fails and ``external_fixer`` is supplied, call that fallback.
    3. Emit an audit event describing the selected path.
    """

    try:
        fixed = brain_only_docfix(text)
    except Exception as exc:  # narrow behavior, broad audit
        if external_fixer is None:
            audit = DocfixAudit(
                route="brain-only",
                status="failed",
                reason=str(exc),
                changed=False,
                input_chars=len(text),
                output_chars=len(text),
                external_used=False,
            )
            if audit_path is not None:
                append_audit(audit_path, audit)
            return DocfixResult(text=text, audit=audit)

        degraded = external_fixer(text)
        audit = DocfixAudit(
            route="external-degrade",
            status="degraded",
            reason=f"brain-only failed: {exc}",
            changed=degraded != text,
            input_chars=len(text),
            output_chars=len(degraded),
            external_used=True,
        )
        if audit_path is not None:
            append_audit(audit_path, audit)
        return DocfixResult(text=degraded, audit=audit)

    audit = DocfixAudit(
        route="brain-only",
        status="ok",
        reason="low-risk docfix handled locally",
        changed=fixed != text,
        input_chars=len(text),
        output_chars=len(fixed),
        external_used=False,
    )
    if audit_path is not None:
        append_audit(audit_path, audit)
    return DocfixResult(text=fixed, audit=audit)


def replay_docfixes(
    samples: Iterable[str],
    *,
    external_fixer: Optional[ExternalFixer] = None,
) -> list[DocfixResult]:
    """Run the default route over sample documentation snippets."""

    return [
        route_low_risk_docfix(sample, external_fixer=external_fixer)
        for sample in samples
    ]
