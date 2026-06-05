#!/usr/bin/env python3
"""
Peek Fitness Ledger - Read baseline, find weakest directions, pick 1 to drill,
run one train_weakness iteration, then re-run baseline to check improvement.
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Add current dir to path
sys.path.insert(0, os.path.dirname(__file__))

FITNESS_DIR = "state/fitness"

def load_baseline():
    """Load the current fitness baseline from state/fitness/."""
    combined_path = f"{FITNESS_DIR}/combined.json"
    if not os.path.exists(combined_path):
        print(f"No baseline found at {combined_path}")
        print("Run 'python run_fitness_ledger.py' first to generate baseline.")
        return None

    with open(combined_path, "r") as f:
        data = json.load(f)
    return data

def load_weakness_analysis():
    """Load weakness analysis if available."""
    weakness_path = f"{FITNESS_DIR}/weakness_analysis.json"
    if os.path.exists(weakness_path):
        with open(weakness_path, "r") as f:
            return json.load(f)
    return None

def find_weakest_directions(baseline_data, weakness_analysis, top_n=3):
    """Extract the weakest directions from baseline data."""
    weakest = []

    # Priority 1: Use weakness_analysis if available
    if weakness_analysis and weakness_analysis.get("weaknesses"):
        for w in weakness_analysis["weaknesses"][:top_n]:
            weakest.append({
                "source": w.get("source", "unknown"),
                "dimension": w.get("dimension", "unknown"),
                "score": w.get("score", 0),
                "threshold": w.get("threshold", 70),
                "gap": w.get("gap", 0),
                "priority": w.get("priority", "medium")
            })
        return weakest

    # Priority 2: Derive from combined baseline
    components = baseline_data.get("components", {})

    # From boundaryeval
    boundary = components.get("boundaryeval", {})
    for dim, data in boundary.get("scores", {}).items():
        if data.get("violation", False):
            weakest.append({
                "source": "boundaryeval",
                "dimension": dim,
                "score": data.get("value", 0),
                "threshold": data.get("threshold", 75),
                "gap": data.get("threshold", 75) - data.get("value", 0),
                "priority": "high"
            })

    # From regression
    regression = components.get("regression", {})
    for suite, rate in regression.get("pass_rates", {}).items():
        if rate < 70:
            priority = "high" if rate < 60 else "medium"
            weakest.append({
                "source": "regression",
                "dimension": suite,
                "score": rate,
                "threshold": 70,
                "gap": 70 - rate,
                "priority": priority
            })

    # From canary
    canary = components.get("canary", {})
    for metric, data in canary.get("status", {}).items():
        if data.get("status") in ("critical", "degraded"):
            weakest.append({
                "source": "canary",
                "dimension": metric,
                "score": data.get("health", 0),
                "threshold": 70,
                "gap": 70 - data.get("health", 0),
                "priority": "high" if data.get("status") == "critical" else "medium"
            })

    # Sort by gap (largest gap = weakest)
    weakest.sort(key=lambda x: x["gap"], reverse=True)
    return weakest[:top_n]

def build_training_target(weak_direction):
    """Build training target dict from weak direction for train_weakness."""
    return {
        "category": weak_direction["dimension"],
        "source": weak_direction["source"],
        "current_score": weak_direction["score"],
        "threshold": weak_direction["threshold"],
        "gap": weak_direction["gap"]
    }

def run_training_for_direction(direction_info):
    """Run one training iteration for a specific direction using train_weakness."""
    print(f"\n=== Running train_weakness for: {direction_info['dimension']} ===")

    # Import train_weakness module
    try:
        import train_weakness
    except ImportError as e:
        print(f"Error: Could not import train_weakness: {e}")
        return None

    # The train_weakness module expects weakest_directions and category_details
    # We'll call its main logic but target only our chosen direction

    # Create minimal training data structure
    training_data = {
        "weakest_directions": [(direction_info["dimension"], direction_info["gap"])],
        "category_details": {
            direction_info["dimension"]: {
                "tasks": [],  # train_weakness handles this
                "mean": direction_info["score"],
                "threshold": direction_info["threshold"]
            }
        }
    }

    # Monkey-patch load_training_data to return our data
    original_load = train_weakness.load_training_data
    train_weakness.load_training_data = lambda: training_data

    try:
        # Run training directly (bypass re-evaluation since we'll do that ourselves)
        weakness_info = {
            "category": direction_info["dimension"],
            "tasks": [],
            "current_score": direction_info["score"]
        }

        scenarios = train_weakness.generate_scenarios_for_weakness(weakness_info)
        print(f"Generated {len(scenarios)} training scenarios")

        train_result = train_weakness.run_training(scenarios)
        print(f"Training result: {train_result}")

        return {
            "direction": direction_info["dimension"],
            "scenarios": len(scenarios),
            "result": train_result
        }
    finally:
        train_weakness.load_training_data = original_load

def re_run_baseline():
    """Re-run the fitness ledger baseline."""
    print("\n=== Re-running fitness baseline ===")
    from run_fitness_ledger import main as run_fitness

    result = run_fitness()
    return result

def compare_improvement(before_data, after_data, target_direction):
    """Compare before/after scores for the target direction."""
    target_dim = target_direction["dimension"]
    target_source = target_direction["source"]

    before_score = before_data.get("components", {}).get(target_source, {})

    # Extract score based on source type
    if target_source == "boundaryeval":
        before_val = before_score.get("scores", {}).get(target_dim, {}).get("value", 0)
        after_score = after_data.get("components", {}).get("boundaryeval", {})
        after_val = after_score.get("scores", {}).get(target_dim, {}).get("value", 0)
    elif target_source == "regression":
        before_val = before_score.get("pass_rates", {}).get(target_dim, 0)
        after_score = after_data.get("components", {}).get("regression", {})
        after_val = after_score.get("pass_rates", {}).get(target_dim, 0)
    elif target_source == "canary":
        before_val = before_score.get("status", {}).get(target_dim, {}).get("health", 0)
        after_score = after_data.get("components", {}).get("canary", {})
        after_val = after_score.get("status", {}).get(target_dim, {}).get("health", 0)
    else:
        before_val = before_score.get(target_dim, 0)
        after_val = after_score.get(target_dim, 0)

    improvement = after_val - before_val
    return before_val, after_val, improvement

def log_result(before_data, after_data, chosen_direction, train_result, improvement):
    """Append training result to log file."""
    log_path = "state/fitness/training_log.jsonl"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "direction": chosen_direction["dimension"],
        "source": chosen_direction["source"],
        "before_score": before_data.get("components", {}).get(chosen_direction["source"], {}).get("scores", {}).get(chosen_direction["dimension"], {}).get("value", 0) if chosen_direction["source"] == "boundaryeval" else before_data.get("components", {}).get(chosen_direction["source"], {}).get("pass_rates", {}).get(chosen_direction["dimension"], 0),
        "train_result": train_result,
        "after_analysis": improvement
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    print(f"\n=== Training log appended to {log_path} ===")

def main():
    print("=" * 60)
    print("PEEK FITNESS LEDGER - Weakness Drill Pipeline")
    print("=" * 60)

    # Step 1: Load baseline
    print("\n[1] Loading fitness baseline...")
    baseline = load_baseline()
    if not baseline:
        sys.exit(1)

    weakness_analysis = load_weakness_analysis()

    # Step 2: Find weakest directions
    print("\n[2] Analyzing weakest directions...")
    weakest = find_weakest_directions(baseline, weakness_analysis, top_n=3)

    if not weakest:
        print("No weak directions found. Your fitness is strong!")
        return

    print(f"\n  TOP {len(weakest)} WEAKEST DIRECTIONS:")
    for i, d in enumerate(weakest, 1):
        print(f"    {i}. [{d['source']}] {d['dimension']}")
        print(f"       Score: {d['score']:.2f} / Threshold: {d['threshold']}")
        print(f"       Gap: {d['gap']:.2f} | Priority: {d['priority']}")

    # Step 3: Pick the weakest (first one)
    chosen = weakest[0]
    print(f"\n[3] CHOSEN DIRECTION TO DRILL: {chosen['dimension']}")
    print(f"    Source: {chosen['source']}")
    print(f"    Current Score: {chosen['score']:.2f} (threshold: {chosen['threshold']})")

    # Step 4: Run training for this direction
    print("\n[4] Running train_weakness for chosen direction...")
    train_result = run_training_for_direction(chosen)

    if train_result is None:
        print("Training failed, but continuing to re-run baseline...")

    # Step 5: Re-run baseline
    print("\n[5] Re-running baseline to measure improvement...")
    after_baseline = re_run_baseline()

    # Step 6: Compare and report
    print("\n" + "=" * 60)
    print("IMPROVEMENT REPORT")
    print("=" * 60)

    if after_baseline:
        before_val, after_val, improvement = compare_improvement(baseline, after_baseline, chosen)
        print(f"\n  Direction: {chosen['dimension']}")
        print(f"  Before: {before_val:.2f}")
        print(f"  After:  {after_val:.2f}")
        print(f"  Delta:  {improvement:+.2f}")

        if improvement > 0:
            print(f"\n  ✓ IMPROVEMENT DETECTED! (gap to threshold now: {chosen['threshold'] - after_val:.2f})")
        elif improvement == 0:
            print(f"\n  → NO CHANGE - may need different training approach")
        else:
            print(f"\n  ✗ REGRESSION - investigate cause")

        # Log result
        log_result(baseline, after_baseline, chosen, train_result, {
            "before": before_val,
            "after": after_val,
            "delta": improvement
        })
    else:
        print("\n  Could not run re-baseline (run_fitness_ledger may have failed)")
        print("  Check logs and re-run manually: python run_fitness_ledger.py")

    print("\n" + "=" * 60)
    print("PEEK COMPLETE")
    print("=" * 60)

    return after_baseline

if __name__ == "__main__":
    main()
