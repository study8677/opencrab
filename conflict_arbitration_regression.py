"""Regression checks for conflict_arbitration multi-evidence outcomes."""

from typing import Dict, Any

from conflict_arbitration import ConflictArbitrator


def run_regression() -> Dict[str, Any]:
    arbitrator = ConflictArbitrator()

    adopt = arbitrator.arbitrate_plans([
        {
            "id": "high-value",
            "value": 0.9,
            "risk": 0.1,
            "evidence": [{"id": "fresh-pass", "weight": 2, "freshness": 1.0}],
            "actions": [{"target": "x.py", "op": "edit", "value": "A"}],
        },
        {
            "id": "low-value",
            "value": 0.2,
            "risk": 0.1,
            "evidence": [{"id": "fresh-pass-2", "weight": 1, "freshness": 1.0}],
            "actions": [{"target": "x.py", "op": "edit", "value": "B"}],
        },
    ])
    assert adopt["decisions"][0]["outcome"] == "adopt"
    assert adopt["selected_actions"][0]["plan_id"] == "high-value"

    defer = arbitrator.arbitrate_plans([
        {
            "id": "close-a",
            "value": 0.50,
            "risk": 0.1,
            "confidence": 0.5,
            "evidence": [{"id": "fresh-a", "weight": 1, "freshness": 1.0}],
            "actions": [{"target": "y.py", "op": "edit", "value": "A"}],
        },
        {
            "id": "close-b",
            "value": 0.49,
            "risk": 0.1,
            "confidence": 0.5,
            "evidence": [{"id": "fresh-b", "weight": 1, "freshness": 1.0}],
            "actions": [{"target": "y.py", "op": "edit", "value": "B"}],
        },
    ])
    assert defer["decisions"][0]["outcome"] == "defer"
    assert len(defer["deferred_actions"]) == 2

    verify = arbitrator.arbitrate_plans([
        {
            "id": "weak-evidence",
            "value": 1.0,
            "risk": 0.1,
            "evidence": [{"id": "stale", "weight": 1, "freshness": 0.0}],
            "actions": [{"target": "z.py", "op": "edit", "value": "A"}],
        },
        {
            "id": "weaker",
            "value": 0.1,
            "risk": 0.1,
            "evidence": [{"id": "fresh", "weight": 1, "freshness": 1.0}],
            "actions": [{"target": "z.py", "op": "edit", "value": "B"}],
        },
    ])
    assert verify["decisions"][0]["outcome"] == "verify"
    assert len(verify["verification_actions"]) == 2

    return {
        "adopt": adopt["decisions"][0],
        "defer": defer["decisions"][0],
        "verify": verify["decisions"][0],
    }


if __name__ == "__main__":
    print(run_regression())
