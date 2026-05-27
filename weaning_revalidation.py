"""Autonomy-meter × evidence-freshness bridge for weaning revalidation.

This module is intentionally dependency-light: it can be called by
``autonomy_meter`` when external aid is downgraded, or by
``evidence_freshness``/gate code when they need a deterministic revalidation
record.  The core policy is simple:

* no downgrade, no automatic weaning revalidation evidence;
* downgrade alone is not enough: the evidence carries recent trend data;
* freshness is explicit, so a weaning claim can be re-checked instead of
  becoming a slogan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping, Optional, Sequence


DEFAULT_REVALIDATION_TTL_HOURS = 72


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> datetime:
    if value is None:
        return _utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _stable_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_external_aid_downgraded(before: Any, after: Any) -> bool:
    """Return True when the external-aid level numerically decreased.

    The project has used several naming styles for autonomy/external-aid
    metrics.  This helper keeps the bridge tolerant: callers may pass numbers
    directly, enum values with ``value``, or mappings containing one of the
    common aid keys.
    """

    return _extract_aid_level(after) < _extract_aid_level(before)


def _extract_aid_level(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in (
            "external_aid",
            "external_aid_level",
            "aid_level",
            "outsourcing",
            "delegate_level",
            "assistance",
        ):
            if key in value:
                return _safe_float(value[key])
        return 0.0
    if hasattr(value, "value"):
        return _safe_float(getattr(value, "value"))
    return _safe_float(value)


def summarize_autonomy_trend(samples: Iterable[Any]) -> dict[str, Any]:
    """Summarize autonomy trend from recent samples.

    Samples may be numbers or mappings.  Mapping keys accepted for the autonomy
    score are intentionally broad to match nearby modules without importing
    them.
    """

    points = [_extract_autonomy_score(sample) for sample in samples]
    if not points:
        return {
            "sample_count": 0,
            "first": None,
            "last": None,
            "delta": 0.0,
            "direction": "unknown",
            "non_regression": False,
        }

    first = points[0]
    last = points[-1]
    delta = last - first
    if delta > 0:
        direction = "improving"
    elif delta < 0:
        direction = "declining"
    else:
        direction = "flat"

    return {
        "sample_count": len(points),
        "first": first,
        "last": last,
        "delta": delta,
        "direction": direction,
        "non_regression": delta >= 0,
    }


def _extract_autonomy_score(sample: Any) -> float:
    if isinstance(sample, Mapping):
        for key in (
            "autonomy",
            "autonomy_score",
            "score",
            "self_reliance",
            "self_reliance_score",
            "independence",
        ):
            if key in sample:
                return _safe_float(sample[key])
        return 0.0
    if hasattr(sample, "score"):
        return _safe_float(getattr(sample, "score"))
    return _safe_float(sample)


@dataclass(frozen=True)
class WeaningRevalidationEvidence:
    """Evidence emitted when external aid is downgraded."""

    evidence_id: str
    kind: str
    created_at: str
    expires_at: str
    previous_external_aid: float
    current_external_aid: float
    trend: dict[str, Any]
    status: str
    reason: str
    source: str = "autonomy_meter×evidence_freshness"

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "previous_external_aid": self.previous_external_aid,
            "current_external_aid": self.current_external_aid,
            "trend": dict(self.trend),
            "status": self.status,
            "reason": self.reason,
            "source": self.source,
        }


def build_weaning_revalidation_evidence(
    previous_external_aid: Any,
    current_external_aid: Any,
    autonomy_samples: Sequence[Any],
    *,
    created_at: Optional[datetime] = None,
    ttl_hours: int = DEFAULT_REVALIDATION_TTL_HOURS,
    subject: str = "weaning",
) -> Optional[dict[str, Any]]:
    """Build automatic revalidation evidence for an external-aid downgrade.

    Returns ``None`` when there is no downgrade.  When there is a downgrade,
    the returned record is suitable for JSONL/audit storage and includes
    freshness metadata plus trend-based pass/review status.
    """

    previous = _extract_aid_level(previous_external_aid)
    current = _extract_aid_level(current_external_aid)
    if current >= previous:
        return None

    now = _as_utc(created_at)
    expires = now + timedelta(hours=max(1, int(ttl_hours)))
    trend = summarize_autonomy_trend(autonomy_samples)
    status = "revalidate_pass" if trend.get("non_regression") else "revalidate_review"
    reason = (
        "external aid downgraded and autonomy trend is non-regressive"
        if status == "revalidate_pass"
        else "external aid downgraded but autonomy trend needs review"
    )

    seed = {
        "subject": subject,
        "previous_external_aid": previous,
        "current_external_aid": current,
        "created_at": _iso(now),
        "expires_at": _iso(expires),
        "trend": trend,
        "status": status,
    }
    evidence_id = "wean-reval-" + hashlib.sha256(_stable_json(seed).encode("utf-8")).hexdigest()[:16]

    return WeaningRevalidationEvidence(
        evidence_id=evidence_id,
        kind="weaning_revalidation",
        created_at=_iso(now),
        expires_at=_iso(expires),
        previous_external_aid=previous,
        current_external_aid=current,
        trend=trend,
        status=status,
        reason=reason,
    ).as_dict()


def collect_weaning_revalidation_evidence(
    previous_external_aid: Any,
    current_external_aid: Any,
    autonomy_samples: Sequence[Any],
    evidence_sink: Optional[Any] = None,
    **kwargs: Any,
) -> Optional[dict[str, Any]]:
    """Generate and optionally persist downgrade-triggered evidence.

    ``evidence_sink`` may be a callable, or an object exposing ``append``,
    ``add``, or ``record``.  Persistence failures are deliberately not hidden:
    a caller that cannot store revalidation evidence should fail loudly.
    """

    evidence = build_weaning_revalidation_evidence(
        previous_external_aid,
        current_external_aid,
        autonomy_samples,
        **kwargs,
    )
    if evidence is None or evidence_sink is None:
        return evidence

    if callable(evidence_sink):
        evidence_sink(evidence)
    elif hasattr(evidence_sink, "append"):
        evidence_sink.append(evidence)
    elif hasattr(evidence_sink, "add"):
        evidence_sink.add(evidence)
    elif hasattr(evidence_sink, "record"):
        evidence_sink.record(evidence)
    else:
        raise TypeError("evidence_sink must be callable or expose append/add/record")

    return evidence


__all__ = [
    "DEFAULT_REVALIDATION_TTL_HOURS",
    "WeaningRevalidationEvidence",
    "build_weaning_revalidation_evidence",
    "collect_weaning_revalidation_evidence",
    "is_external_aid_downgraded",
    "summarize_autonomy_trend",
]
