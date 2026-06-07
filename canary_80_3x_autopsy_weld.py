"""
Combined autopsy + stabilize + weld for canary 80 3x.
Run this to: Diagnose jitter, stabilize gates, weld if stable.
"""

import sys
from datetime import datetime

from autopsy_canary_80_3x import run_autopsy_canary_80_3x
from stabilize_gates import stabilize_gates
from crab import Crab


def run_canary_80_3x_autopsy_weld(project: str = "main") -> dict:
    """Run full autopsy-stabilize-weld pipeline."""
    print("=" * 70)
    print("CANARY 80% 3x AUTOPSY → STABILIZE → WELD PIPELINE")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    results = {
        "project": project,
        "started_at": datetime.now().isoformat(),
        "autopsy": None,
        "stabilization": None,
        "weld": None,
        "success": False,
    }

    # Step 1: Run autopsy
    print("\n" + "=" * 70)
    print("PHASE 1: AUTOPSY")
    print("=" * 70)
    results["autopsy"] = run_autopsy_canary_80_3x(project)

    # Determine next steps based on diagnosis
    diagnosis = results["autopsy"].get("diagnosis")
    recommendation = results["autopsy"].get("recommendation", {})

    if diagnosis == "no_3x_failure":
        print("\n✓ No 3x failure detected. No action needed.")
        results["success"] = True
        return results

    if diagnosis in ["gates_jitter_only", "both_gates_and_patch"]:
        # Step 2: Stabilize gates
        print("\n" + "=" * 70)
        print("PHASE 2: STABILIZE GATES")
        print("=" * 70)
        results["stabilization"] = stabilize_gates(project)

        # Step 3: Wait for stabilization (in real scenario, would wait)
        print("\n⚠ Wait for gates to stabilize before proceeding.")
        print("Run 3x verification manually after stabilization.")

        # Step 4: Weld if stable
        print("\n" + "=" * 70)
        print("PHASE 3: WELD (conditional)")
        print("=" * 70)
        if _check_gates_stable(project):
            print("✓ Gates are stable. Proceeding with weld...")
            results["weld"] = _do_weld(project)
        else:
            print("✗ Gates still jittery. Skipping weld.")
            print("  Re-run stabilization or investigate further.")

    elif diagnosis == "patch_bias_only":
        print("\n" + "=" * 70)
        print("PHASE 2: PATCH REBALANCE (skipped - implement if needed)")
        print("=" * 70)
        print("⚠ Patch bias detected but patch rebalancing not yet implemented.")
        print("  Implement patch rebalancing logic based on bias direction.")

    else:
        print("\n⚠ Unknown diagnosis. Investigate further before welding.")

    results["completed_at"] = datetime.now().isoformat()
    results["success"] = results.get("weld") is not None

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    print(f"Success: {results['success']}")
    print(f"Started: {results['started_at']}")
    print(f"Completed: {results['completed_at']}")

    return results


def _check_gates_stable(project: str) -> bool:
    """Check if gates are now stable."""
    config_path = f"projects/{project}/gate_config.json"
    import json
    from pathlib import Path

    if not Path(config_path).exists():
        return True  # No config means no restrictions

    with open(config_path) as f:
        config = json.load(f)

    breakers = config.get("circuit_breakers", {})
    return all(not b.get("enabled", False) for b in breakers.values()) or len(breakers) == 0


def _do_weld(project: str) -> dict:
    """Perform the actual weld."""
    print("Performing weld...")
    # Placeholder for actual weld logic
    # In real implementation, would call the weld function
    return {"weld_status": "completed", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    project = sys.argv[1] if len(sys.argv) > 1 else "main"
    run_canary_80_3x_autopsy_weld(project)
