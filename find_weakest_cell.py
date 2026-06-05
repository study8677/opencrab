#!/usr/bin/env python3
"""Run evalbench baseline to find the actual weakest cell (no guessing)."""

import json
import subprocess
import sys
from pathlib import Path

def run_evalbench_baseline():
    """Run evalbench and get real scores."""
    result = subprocess.run(
        ["python", "-m", "evalbench", "--mode", "baseline", "--json-output"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent
    )
    if result.returncode != 0:
        print(f"ERROR: evalbench failed: {result.stderr}")
        sys.exit(1)
    return json.loads(result.stdout)

def find_weakest_cell(scores):
    """Find the cell with lowest score."""
    weakest = None
    min_score = float('inf')
    for cell_id, score_data in scores.items():
        if isinstance(score_data, dict):
            score = score_data.get('score', score_data.get('accuracy', 100))
        else:
            score = score_data
        if score < min_score:
            min_score = score
            weakest = cell_id
    return weakest, min_score

if __name__ == "__main__":
    print("Running evalbench baseline to find weakest cell...")
    scores = run_evalbench_baseline()
    
    weakest_cell, min_score = find_weakest_cell(scores)
    
    print(f"\n=== WEAKEST CELL FOUND ===")
    print(f"Cell: {weakest_cell}")
    print(f"Score: {min_score}")
    print(f"\nFull scores: {json.dumps(scores, indent=2)}")
    
    # Save for next step
    with open('.weakest_cell.json', 'w') as f:
        json.dump({'cell': weakest_cell, 'score': min_score, 'all_scores': scores}, f, indent=2)
    print(f"\nSaved to .weakest_cell.json")
