"""Deterministic arbitration for conflicting evidence.

The module keeps the conflict rule small and replayable:

* evidence is normalized from dicts, dataclasses, or plain objects;
* each item receives a confidence and a trust score;
* trust can be supplied directly or obtained from ``trustscore`` when present;
* one attractive metric is not allowed to dominate corroborated evidence;
* every decision carries a replay payload that can be fed back to ``replay``.

The implementation is intentionally dependency-light.  ``evidence`` and
``trustscore`` are optional integrations: objects from those modules work as
plain Python objects, and trustscore hooks are discovered defensively.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


_POSITIVE = {"support", "supports", "for", "pro", "pass", "passed", "true", True, 1}
_NEGATIVE = {"oppose", "opposes", "against", "con", "fail", "failed", "false", False, -1}
_TRUST_HOOKS = (
    "score_evidence",
    "trust_score",
    "score",
    "compute_trust",
    "evaluate",
)


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def _plain(item: Any) -> Dict[str, Any]:
    if item is None:
        return {}
    if isinstance(item, Mapping):
        return dict(item)
    if is_dataclass(item):
        return asdict(item)
    data: Dict[str, Any] = {}
    for name in (
        "id",
        "claim",
        "stance",
        "direction",
        "verdict",
        "confidence",
        "score",
        "trust",
        "trust_score",
        "source",
        "metric",
        "metrics",
        "freshness",
        "payload",
    ):
        if hasattr(item, name):
            data[name] = getattr(item, name)
    if not data and hasattr(item, "__dict__"):
        data.update(vars(item))
    return data


def _call_trustscore(item: Any, data: Mapping[str, Any]) -> Optional[float]:
    """Best-effort integration with trustscore without depending on its API."""

    try:
        import trustscore  # type: ignore
    except Exception:
        return None

    for hook_name in _TRUST_HOOKS:
        hook = getattr(trustscore, hook_name, None)
        if not callable(hook):
            continue
        for arg in (item, data):
            try:
                scored = hook(arg)
            except TypeError:
                continue
            except Exception:
                break
            if isinstance(scored, Mapping):
                for key in ("trust", "trust_score", "score", "confidence"):
                    if key in scored:
                        return _clamp(scored[key])
            if hasattr(scored, "trust_score"):
                return _clamp(getattr(scored, "trust_score"))
            if hasattr(scored, "trust"):
                return _clamp(getattr(scored, "trust"))
            if isinstance(scored, (int, float)):
                return _clamp(scored)
    return None


def _stance_value(raw: Any) -> int:
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in _POSITIVE:
            return 1
        if lowered in _NEGATIVE:
            return -1
    if raw in _POSITIVE:
        return 1
    if raw in _NEGATIVE:
        return -1
    return 0


@dataclass(frozen=True)
class NormalizedEvidence:
    """Evidence shape used by the arbitrator."""

    id: str
    claim: str
    stance: int
    confidence: float
    trust: float
    source: str = "unknown"
    metric: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def weight(self) -> float:
        return _clamp(self.confidence * self.trust)


@dataclass(frozen=True)
class ArbitrationDecision:
    """Replayable decision for one conflict set."""

    verdict: str
    confidence: float
    rule: str
    winner: Optional[str]
    reasons: Tuple[str, ...]
    replay: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": self.confidence,
            "rule": self.rule,
            "winner": self.winner,
            "reasons": list(self.reasons),
            "replay": self.replay,
        }


def normalize_evidence(item: Any, index: int = 0) -> NormalizedEvidence:
    """Normalize dict/object/dataclass evidence into an arbitration record."""

    data = _plain(item)
    explicit_trust = data.get("trust_score", data.get("trust"))
    trust = _clamp(explicit_trust, default=-1.0)
    if trust < 0.0:
        scored = _call_trustscore(item, data)
        trust = _clamp(scored, default=0.5) if scored is not None else 0.5

    confidence = _clamp(
        data.get("confidence", data.get("score", data.get("probability", 0.5)))
    )
    stance = _stance_value(
        data.get("stance", data.get("direction", data.get("verdict", data.get("supports"))))
    )
    claim = str(data.get("claim", data.get("subject", "default")))
    source = str(data.get("source", data.get("origin", "unknown")))
    metric = data.get("metric")
    if metric is None and isinstance(data.get("metrics"), Mapping):
        metric = ",".join(sorted(str(key) for key in data["metrics"].keys()))

    evidence_id = str(data.get("id", data.get("name", f"e{index}")))
    payload = dict(data)
    return NormalizedEvidence(
        id=evidence_id,
        claim=claim,
        stance=stance,
        confidence=confidence,
        trust=trust,
        source=source,
        metric=str(metric) if metric is not None else None,
        payload=payload,
    )


def _cap_single_dominance(items: Sequence[NormalizedEvidence]) -> Dict[str, float]:
    """Score items while limiting the effect of one lone beautiful metric."""

    raw = {item.id: item.weight for item in items}
    if len(items) < 2:
        return raw

    total = sum(raw.values())
    if total <= 0.0:
        return raw

    cap = max(0.55, 1.0 / len(items) + 0.25) * total
    capped: Dict[str, float] = {}
    for item in items:
        capped[item.id] = min(raw[item.id], cap)
    return capped


def arbitrate(
    evidences: Iterable[Any],
    *,
    min_margin: float = 0.12,
    min_corroboration: int = 2,
) -> ArbitrationDecision:
    """Choose a stable verdict from conflicting evidence.

    Verdicts:
    * ``support``: positive evidence wins with enough weighted margin;
    * ``oppose``: negative evidence wins with enough weighted margin;
    * ``mixed``: both sides are close or only a single side lacks corroboration;
    * ``insufficient``: no directional evidence is available.
    """

    normalized = [normalize_evidence(item, idx) for idx, item in enumerate(evidences)]
    directional = [item for item in normalized if item.stance != 0]
    if not directional:
        replay_payload = _replay_payload(normalized, {}, 0.0, 0.0, min_margin, min_corroboration)
        return ArbitrationDecision(
            verdict="insufficient",
            confidence=0.0,
            rule="weighted_trust_with_single_metric_cap",
            winner=None,
            reasons=("no directional evidence",),
            replay=replay_payload,
        )

    capped = _cap_single_dominance(directional)
    support = sum(capped[item.id] for item in directional if item.stance > 0)
    oppose = sum(capped[item.id] for item in directional if item.stance < 0)
    total = support + oppose
    margin = abs(support - oppose) / total if total else 0.0
    support_count = sum(1 for item in directional if item.stance > 0 and capped[item.id] > 0)
    oppose_count = sum(1 for item in directional if item.stance < 0 and capped[item.id] > 0)

    reasons: List[str] = [
        f"support_weight={support:.3f}",
        f"oppose_weight={oppose:.3f}",
        f"margin={margin:.3f}",
    ]

    winner: Optional[str]
    if support > oppose:
        proposed = "support"
        winner = _best_id(directional, capped, 1)
        winning_count = support_count
    elif oppose > support:
        proposed = "oppose"
        winner = _best_id(directional, capped, -1)
        winning_count = oppose_count
    else:
        proposed = "mixed"
        winner = None
        winning_count = 0

    if proposed == "mixed" or margin < min_margin:
        verdict = "mixed"
        winner = None
        reasons.append("margin below replayable conflict threshold")
    elif winning_count < min_corroboration and len(directional) > 1:
        verdict = "mixed"
        reasons.append("single evidence item was not allowed to dominate")
    else:
        verdict = proposed
        reasons.append(f"{proposed} side wins after trustscore weighting")

    confidence = _clamp(0.5 + margin / 2.0 if verdict != "mixed" else 0.5 - margin / 4.0)
    replay_payload = _replay_payload(
        normalized, capped, support, oppose, min_margin, min_corroboration
    )
    return ArbitrationDecision(
        verdict=verdict,
        confidence=confidence,
        rule="weighted_trust_with_single_metric_cap",
        winner=winner,
        reasons=tuple(reasons),
        replay=replay_payload,
    )


def _best_id(items: Sequence[NormalizedEvidence], weights: Mapping[str, float], stance: int) -> Optional[str]:
    side = [item for item in items if item.stance == stance]
    if not side:
        return None
    return max(side, key=lambda item: (weights.get(item.id, 0.0), item.trust, item.confidence, item.id)).id


def _replay_payload(
    items: Sequence[NormalizedEvidence],
    capped: Mapping[str, float],
    support: float,
    oppose: float,
    min_margin: float,
    min_corroboration: int,
) -> Dict[str, Any]:
    return {
        "inputs": [
            {
                "id": item.id,
                "claim": item.claim,
                "stance": item.stance,
                "confidence": item.confidence,
                "trust": item.trust,
                "source": item.source,
                "metric": item.metric,
                "weight": item.weight,
                "capped_weight": capped.get(item.id, item.weight),
            }
            for item in items
        ],
        "totals": {"support": support, "oppose": oppose},
        "params": {
            "min_margin": min_margin,
            "min_corroboration": min_corroboration,
        },
    }


def replay(decision_or_payload: Any) -> ArbitrationDecision:
    """Replay an arbitration decision from its recorded payload."""

    if isinstance(decision_or_payload, ArbitrationDecision):
        payload = decision_or_payload.replay
    elif isinstance(decision_or_payload, Mapping) and "replay" in decision_or_payload:
        payload = decision_or_payload["replay"]
    else:
        payload = decision_or_payload

    inputs = list(payload.get("inputs", []))
    params = dict(payload.get("params", {}))
    return arbitrate(
        inputs,
        min_margin=float(params.get("min_margin", 0.12)),
        min_corroboration=int(params.get("min_corroboration", 2)),
    )


def replay_decision(decision_or_payload: Any) -> ArbitrationDecision:
    return replay(decision_or_payload)


def arbitrate_conflict(evidences: Iterable[Any], **kwargs: Any) -> ArbitrationDecision:
    return arbitrate(evidences, **kwargs)


def decide(evidences: Iterable[Any], **kwargs: Any) -> ArbitrationDecision:
    return arbitrate(evidences, **kwargs)


class ConflictArbitrator:
    """Small OO wrapper for callers that prefer a reusable arbitrator."""

    def __init__(self, min_margin: float = 0.12, min_corroboration: int = 2) -> None:
        self.min_margin = min_margin
        self.min_corroboration = min_corroboration

    def arbitrate(self, evidences: Iterable[Any]) -> ArbitrationDecision:
        return arbitrate(
            evidences,
            min_margin=self.min_margin,
            min_corroboration=self.min_corroboration,
        )

    def replay(self, decision_or_payload: Any) -> ArbitrationDecision:
        return replay(decision_or_payload)


def replay_sample() -> Dict[str, Any]:
    """Return a deterministic sample showing the anti-single-metric rule."""

    decision = arbitrate(
        [
            {
                "id": "pretty_metric",
                "claim": "patch improves reliability",
                "stance": "support",
                "confidence": 0.98,
                "trust": 0.72,
                "source": "benchmark",
                "metric": "headline_pass_rate",
            },
            {
                "id": "fresh_regression",
                "claim": "patch improves reliability",
                "stance": "oppose",
                "confidence": 0.71,
                "trust": 0.86,
                "source": "evidence",
                "metric": "fresh_failure",
            },
            {
                "id": "operator_note",
                "claim": "patch improves reliability",
                "stance": "oppose",
                "confidence": 0.62,
                "trust": 0.80,
                "source": "audit",
                "metric": "manual_replay",
            },
        ]
    )
    return decision.to_dict()


def build_replay_sample() -> Dict[str, Any]:
    return replay_sample()


__all__ = [
    "ArbitrationDecision",
    "ConflictArbitrator",
    "NormalizedEvidence",
    "arbitrate",
    "arbitrate_conflict",
    "build_replay_sample",
    "decide",
    "normalize_evidence",
    "replay",
    "replay_decision",
    "replay_sample",
]
