"""
fitness_replication_protocol.py

Top-level protocol: 3x replication gate for fitness闭环.

This is the entry point for any code that wants to safely
close the fitness loop with statistical honesty.

Usage:
    from fitness_replication_protocol import run_fitness闭环_with_gate
    result = run_fitness闭环_with_gate(target="accuracy")

The protocol:
  1. Read manifest → find weakest dimension
  2. Run train_weakness on that dimension
  3. Run golden eval 3 times
  4. Gate: all 3 must improve + jitter ≤ 15% + mean_delta ≥ 1%
  5. Commit or mark pending_diagnosis
  6. Log evidence to fitness_ledger

Author: opencrab hand
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from crab import log


def run_fitness_闭环_with_gate(
    crab_path: Path,
    train_fn: Callable[[], dict[str, Any]],
    eval_fn: Callable[[], dict[str, float]],
    manifest_path: Optional[Path] = None,
    min_improvement: float = 0.01,
    max_std_ratio: float = 0.15,
    required_passes: int = 3,
    write_manifest: bool = True,
) -> dict[str, Any]:
    """
    Core 3x replication gate for fitness闭环.

    Args:
        crab_path: path to crab workspace
        train_fn: callable that runs one round of training
        eval_fn: callable that runs golden eval once, returns {dim: score}
        manifest_path: defaults to crab_path / "manifest.json"
        min_improvement: minimum mean_delta per dimension
        max_std_ratio: max jitter = std_delta / |mean_delta|
        required_passes: number of re-test passes
        write_manifest: whether to persist results to manifest

    Returns:
        dict with committed, status, delta_record, dimension_results, pass_scores
    """
    if manifest_path is None:
        manifest_path = crab_path / "manifest.json"

    # 1. Baseline
    baseline = eval_fn()
    if not baseline:
        log("[fitness_replication] No baseline, aborting", level="error")
        return {"committed": False, "status": "no_baseline", "pass_scores": []}

    # 2. Train
    log("[fitness_replication] Training...")
    train_result = train_fn()

    # 3. Re-test N times
    pass_scores: list[dict[str, float]] = []
    for i in range(required_passes):
        scores = eval_fn()
        pass_scores.append(scores)
        log(f"[fitness_replication] Pass {i+1}/{required_passes}: {scores}")

    # 4. Evaluate each dimension
    all_dims = set()
    for ps in pass_scores:
        all_dims.update(ps.keys())

    dimension_results: dict[str, Any] = {}
    delta_record: dict[str, Any] = {}
    committed = False
    status = "pending_diagnosis"

    for dim in all_dims:
        pre = baseline.get(dim, 0.0)
        if pre == 0.0:
            log(f"[fitness_replication] Dim '{dim}' has zero baseline, skipping")
            continue

        post_vals = [ps.get(dim, 0.0) for ps in pass_scores]
        all_improved = all(v > pre for v in post_vals)
        deltas = [v - pre for v in post_vals]
        mean_delta = statistics.mean(deltas)
        std_delta = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
        jitter = abs(std_delta / mean_delta) if mean_delta != 0 else float("inf")

        improved_and_stable = (
            all_improved
            and mean_delta >= min_improvement
            and jitter <= max_std_ratio
        )

        dimension_results[dim] = {
            "baseline": pre,
            "post_vals": post_vals,
            "mean_delta": mean_delta,
            "std_delta": std_delta,
            "jitter": jitter,
            "all_improved": all_improved,
            "improved_and_stable": improved_and_stable,
        }

        log(
            f"[fitness_replication] {dim}: base={pre:.4f} "
            f"passes={post_vals} mean_d={mean_delta:.4f} "
            f"std_d={std_delta:.4f} jitter={jitter:.2%} "
            f"pass={improved_and_stable}"
        )

        if improved_and_stable:
            committed = True
            status = "reproduced"
            delta_record[dim] = {
                "before": pre,
                "after": statistics.mean(post_vals),
                "delta": mean_delta,
                "std": std_delta,
                "jitter": jitter,
                "passes": required_passes,
                "timestamp": datetime.utcnow().isoformat(),
            }

    # 5. Write manifest
    if write_manifest:
        _write_manifest(manifest_path, committed, status, delta_record, dimension_results)

    return {
        "committed": committed,
        "status": status,
        "delta_record": delta_record,
        "dimension_results": dimension_results,
        "pass_scores": pass_scores,
        "train_result": train_result,
    }


def _write_manifest(
    manifest_path: Path,
    committed: bool,
    status: str,
    delta_record: dict[str, Any],
    dimension_results: dict[str, Any],
) -> None:
    """Persist replication results to manifest."""
    try:
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
        else:
            manifest = {}

        if committed:
            fitness = manifest.get("fitness", {})
            for dim, vals in delta_record.items():
                if "dimensions" not in fitness:
                    fitness["dimensions"] = {}
                fitness["dimensions"][dim] = {
                    "score": vals["after"],
                    "delta": vals["delta"],
                    "std": vals["std"],
                    "jitter": vals["jitter"],
                    "verified": True,
                    "replication_passes": vals["passes"],
                    "timestamp": vals["timestamp"],
                }
            manifest["fitness"] = fitness
        else:
            # Mark pending diagnosis
            pd = manifest.get("pending_diagnosis", {})
            pd["last_attempt"] = datetime.utcnow().isoformat()
            pd["dimension_results"] = dimension_results
            pd["replication_status"] = "failed"
            manifest["pending_diagnosis"] = pd

        manifest_path.write_text(json.dumps(manifest, indent=2))
        log(f"[fitness_replication] Manifest updated: committed={committed} status={status}")
    except Exception as e:
        log(f"[fitness_replication] Failed to write manifest: {e}", level="error")


def jitter_ratio(deltas: list[float]) -> float:
    """std(Δ) / |mean(Δ)|. Inf if mean is zero."""
    if len(deltas) < 2:
        return 0.0
    mean_d = statistics.mean(deltas)
    if mean_d == 0:
        return float("inf")
    return statistics.stdev(deltas) / abs(mean_d)


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Run fitness闭环 with 3x replication gate"
    )
    parser.add_argument("--crab-path", type=str, default=".")
    parser.add_argument("--min-improvement", type=float, default=0.01)
    parser.add_argument("--max-std-ratio", type=float, default=0.15)
    parser.add_argument("--required-passes", type=int, default=3)
    args = parser.parse_args()

    crab_path = Path(args.crab_path)

    def dummy_train():
        log("[CLI] dummy_train called")
        return {"ok": True}

    def dummy_eval():
        import random
        return {"accuracy": 0.70 + random.uniform(0.05, 0.06)}

    result = run_fitness_闭环_with_gate(
        crab_path=crab_path,
        train_fn=dummy_train,
        eval_fn=dummy_eval,
        min_improvement=args.min_improvement,
        max_std_ratio=args.max_std_ratio,
        required_passes=args.required_passes,
    )
    print(json.dumps(result, indent=2, default=str))
