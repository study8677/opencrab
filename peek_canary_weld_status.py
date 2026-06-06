#!/usr/bin/env python3
"""Quick peek at canary weld status - is it truly stuck at >=75%?"""

import json
from pathlib import Path

def peek_canary_weld_status():
    """Check if canary is welded (stuck at high fitness)."""
    print("=== CANARY WELD STATUS ===\n")
    
    status = {
        "canary_exists": False,
        "fitness_json": {},
        "baseline_score": None,
        "is_welded": False,
        "threshold": 75.0
    }
    
    # Check canary file
    canary_path = Path("canary_75.py")
    status["canary_exists"] = canary_path.exists()
    if canary_path.exists():
        with open(canary_path) as f:
            lines = len(f.read().splitlines())
        print(f"Canary file: EXISTS ({lines} lines)")
    else:
        print("Canary file: NOT FOUND")
    
    # Check fitness.json
    fitness_path = Path("fitness.json")
    if fitness_path.exists():
        with open(fitness_path) as f:
            fitness_data = json.load(f)
        status["fitness_json"] = fitness_data
        
        peak = fitness_data.get("peak", {})
        peak_score = peak.get("score", 0)
        print(f"\nFitness.json peak: {peak_score}%")
        
        canary_welded = fitness_data.get("canary_75_welded", {})
        if canary_welded:
            print(f"Canary welded: {canary_welded.get('score', 'unknown')}%")
        
        if peak_score >= status["threshold"]:
            status["is_welded"] = True
            print(f"\n✓ CANARY IS WELDED at {peak_score}%")
        else:
            print(f"\n✗ CANARY NOT WELDED (peak {peak_score}% < {status['threshold']}%)")
    else:
        print("\nFitness.json: NOT FOUND")
    
    # Check latest baseline
    baseline_path = Path("fitness_baseline_results.json")
    if baseline_path.exists():
        with open(baseline_path) as f:
            baseline = json.load(f)
        score = baseline.get("baseline", {}).get("score", 0)
        status["baseline_score"] = score
        print(f"\nLatest baseline: {score}%")
    else:
        print("\nNo baseline run found - run run_fitness_baseline to check")
    
    print(f"\n{'='*40}")
    print(f"Decision: {'WELDED ✓' if status['is_welded'] else 'NOT WELDED ✗'}")
    
    return status

if __name__ == "__main__":
    peek_canary_weld_status()
