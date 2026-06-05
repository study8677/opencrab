"""
Drill: reproduce the 3x replication gate logic end-to-end.

Purpose: ensure the gate correctly accepts real improvements
and rejects drops / jitter before any code goes live.
"""
import statistics
from pathlib import Path
from typing import Any

from crab import log


def jitter_ratio(deltas: list[float]) -> float:
    """Compute std(Δ) / |mean(Δ)|. Infinity if mean is zero."""
    if len(deltas) < 2:
        return 0.0
    mean_d = statistics.mean(deltas)
    if mean_d == 0:
        return float("inf")
    return statistics.stdev(deltas) / abs(mean_d)


def replication_gate(
    baseline: dict[str, float],
    post_scores: list[dict[str, float]],
    min_improvement: float = 0.01,
    max_std_ratio: float = 0.15,
    required_passes: int = 3,
) -> dict[str, Any]:
    """
    Core replication gate logic.

    Args:
        baseline: pre-train scores per dimension
        post_scores: list of post-train scores (one per pass)
        min_improvement: minimum mean_delta to accept
        max_std_ratio: max jitter = std(Δ) / |mean(Δ)|
        required_passes: number of passes expected

    Returns:
        dict with keys: accepted, status, dimension_results, delta_record
    """
    assert len(post_scores) == required_passes, (
        f"Expected {required_passes} passes, got {len(post_scores)}"
    )

    dimension_results: dict[str, Any] = {}
    delta_record: dict[str, Any] = {}
    accepted = False
    status = "pending_diagnosis"

    all_dims = set()
    for ps in post_scores:
        all_dims.update(ps.keys())
    for dim in all_dims:
        pre = baseline.get(dim, 0.0)
        if pre == 0.0:
            continue

        post_vals = [ps.get(dim, 0.0) for ps in post_scores]
        all_improved = all(v > pre for v in post_vals)
        deltas = [v - pre for v in post_vals]
        mean_delta = statistics.mean(deltas)
        std_delta = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
        jit = jitter_ratio(deltas)

        improved_and_stable = (
            all_improved
            and mean_delta >= min_improvement
            and jit <= max_std_ratio
        )

        dimension_results[dim] = {
            "baseline": pre,
            "post_vals": post_vals,
            "mean_delta": mean_delta,
            "std_delta": std_delta,
            "jitter": jit,
            "all_improved": all_improved,
            "accepted": improved_and_stable,
        }

        if improved_and_stable:
            accepted = True
            status = "reproduced"
            delta_record[dim] = {
                "before": pre,
                "after": statistics.mean(post_vals),
                "delta": mean_delta,
                "std": std_delta,
                "jitter": jit,
            }

    return {
        "accepted": accepted,
        "status": status,
        "dimension_results": dimension_results,
        "delta_record": delta_record,
    }


# ----------------------------------------------------------------------
# Drill scenarios
# ----------------------------------------------------------------------

def scenario_real_improvement():
    """Honest 5% lift, low jitter -> ACCEPT."""
    baseline = {"accuracy": 0.70, "latency_ms": 150.0}
    post_scores = [
        {"accuracy": 0.755, "latency_ms": 142.0},
        {"accuracy": 0.752, "latency_ms": 143.5},
        {"accuracy": 0.758, "latency_ms": 141.0},
    ]
    result = replication_gate(baseline, post_scores)
    log(f"[drill] real_improvement: {result['status']} | accepted={result['accepted']}")
    assert result["accepted"], f"Should accept real improvement: {result}"
    assert result["status"] == "reproduced"
    log("  ✓ scenario_real_improvement PASSED")


def scenario_one_drop():
    """Pass 2 drops -> REJECT."""
    baseline = {"accuracy": 0.70}
    post_scores = [
        {"accuracy": 0.76},
        {"accuracy": 0.68},  # DROP
        {"accuracy": 0.75},
    ]
    result = replication_gate(baseline, post_scores)
    log(f"[drill] one_drop: {result['status']} | accepted={result['accepted']}")
    assert not result["accepted"], f"Should reject: {result}"
    assert result["status"] == "pending_diagnosis"
    log("  ✓ scenario_one_drop PASSED")


def scenario_high_jitter():
    """All improve but jitter > 15% -> REJECT."""
    baseline = {"accuracy": 0.70}
    post_scores = [
        {"accuracy": 0.90},  # outlier
        {"accuracy": 0.72},
        {"accuracy": 0.71},
    ]
    result = replication_gate(baseline, post_scores, max_std_ratio=0.15)
    log(f"[drill] high_jitter: {result['status']} | accepted={result['accepted']}")
    assert not result["accepted"], f"Should reject high jitter: {result}"
    log("  ✓ scenario_high_jitter PASSED")


def scenario_marginal_improvement():
    """All improve but mean_delta < min -> REJECT."""
    baseline = {"accuracy": 0.70}
    post_scores = [
        {"accuracy": 0.701},
        {"accuracy": 0.702},
        {"accuracy": 0.703},
    ]
    result = replication_gate(baseline, post_scores, min_improvement=0.01)
    log(f"[drill] marginal: {result['status']} | accepted={result['accepted']}")
    assert not result["accepted"]
    log("  ✓ scenario_marginal_improvement PASSED")


def scenario_brainonly_fake_progress():
    """Brainonly gives 3 improving scores with low jitter but it's all noise."""
    # This scenario shows the gate can't catch brainonly fabrication
    # if the eval is itself brainonly — that is a deeper problem.
    # But the gate at least ensures the *pattern* is consistent.
    baseline = {"accuracy": 0.70}
    post_scores = [
        {"accuracy": 0.751},
        {"accuracy": 0.752},
        {"accuracy": 0.753},
    ]
    result = replication_gate(baseline, post_scores, min_improvement=0.01, max_std_ratio=0.05)
    log(f"[drill] brainonly_fake_progress: status={result['status']} jitter={result['dimension_results'].get('accuracy',{}).get('jitter')}")
    # Gate passes pattern consistency — the trust issue is elsewhere
    log("  ✓ scenario_brainonly_fake_progress recorded (pattern consistent, trust elsewhere)")


def scenario_multiple_dims_mixed():
    """Dim A passes, dim B fails -> overall reject."""
    baseline = {"accuracy": 0.70, "robustness": 0.50}
    post_scores = [
        {"accuracy": 0.76, "robustness": 0.45},  # A up, B down
        {"accuracy": 0.75, "robustness": 0.44},
        {"accuracy": 0.77, "robustness": 0.46},
    ]
    result = replication_gate(baseline, post_scores)
    log(f"[drill] mixed_dims: {result['status']} | accepted={result['accepted']}")
    # Any dimension failing blocks the whole commit
    assert not result["accepted"]
    log("  ✓ scenario_multiple_dims_mixed PASSED")


if __name__ == "__main__":
    log("=" * 60)
    log("replication_gate_drill: 3x statistical honesty gate")
    log("=" * 60)
    scenario_real_improvement()
    scenario_one_drop()
    scenario_high_jitter()
    scenario_marginal_improvement()
    scenario_brainonly_fake_progress()
    scenario_multiple_dims_mixed()
    log("\n✓ All drill scenarios passed — gate is sound")
