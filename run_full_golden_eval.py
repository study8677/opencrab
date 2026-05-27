#!/usr/bin/env python3
"""
Run full golden task evaluation for evalbench to establish baseline.
This script imports evalbench and golden variant, runs all tasks, and outputs scores.
"""

import sys
import json
from evalbench import EvalBench
from evalbench_golden_variant import GoldenVariant

def main():
    # Load golden tasks
    golden_tasks = GoldenVariant.get_all_tasks()
    
    # Initialize evaluator with golden tasks
    evaluator = EvalBench(tasks=golden_tasks)
    
    # Run evaluation on all tasks
    results = evaluator.run_all()
    
    # Print summary
    print("=== Baseline Evaluation Results ===")
    total_score = 0
    num_tasks = 0
    for task_name, result in results.items():
        score = result.get('score', 0)
        print(f"{task_name}: {score}")
        total_score += score
        num_tasks += 1
    
    average_score = total_score / num_tasks if num_tasks > 0 else 0
    print(f"\nAverage Score: {average_score}")
    
    # Save detailed results to file
    with open("baseline_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Detailed results saved to baseline_results.json")

if __name__ == "__main__":
    main()
