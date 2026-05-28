#!/usr/bin/env python3
"""
Run full golden task evaluation for evalbench to establish baseline.
This script imports evalbench and golden variant, runs all tasks, and outputs scores.
Enhanced: group by category and identify weakest 3 directions.
"""

import sys
import json
import datetime
from collections import defaultdict
from evalbench import EvalBench
from evalbench_golden_variant import GoldenVariant

def categorize_task(task_name: str) -> str:
    """Simple heuristic to group tasks into capability directions."""
    name_lower = task_name.lower()
    if 'code' in name_lower or 'function' in name_lower or 'bug' in name_lower:
        return 'code_understanding'
    if 'math' in name_lower or 'calc' in name_lower or 'number' in name_lower:
        return 'math_logic'
    if 'read' in name_lower or 'text' in name_lower or 'comprehension' in name_lower:
        return 'reading_comprehension'
    if 'logic' in name_lower or 'reason' in name_lower or 'puzzle' in name_lower:
        return 'logical_reasoning'
    if 'common' in name_lower or 'fact' in name_lower or 'knowledge' in name_lower:
        return 'common_sense'
    return 'other'

def run_evaluation():
    """Run full evaluation and return results for external use."""
    # Load golden tasks
    golden_tasks = GoldenVariant.get_all_tasks()
    if not golden_tasks:
        print("No golden tasks found!")
        return None

    # Initialize evaluator with golden tasks
    evaluator = EvalBench(tasks=golden_tasks)

    # Run evaluation on all tasks
    results = evaluator.run_all()

    # Group scores by category
    category_scores = defaultdict(list)
    category_tasks = defaultdict(list)
    for task in golden_tasks:
        task_name = task.get('task_name', task.get('name', str(task)))
        category = categorize_task(task_name)
        score = results.get(task_name, {}).get('score', 0)
        category_scores[category].append(score)
        category_tasks[category].append(task_name)

    # Print summary
    print("=== Baseline Evaluation Results ===")
    total_score = 0
    num_tasks = 0
    category_means = {}

    # Print per-task scores
    for task_name, result in results.items():
        score = result.get('score', 0)
        print(f"{task_name}: {score}")
        total_score += score
        num_tasks += 1

    average_score = total_score / num_tasks if num_tasks > 0 else 0
    print(f"\nAverage Score: {average_score:.3f}")

    # Print per-category scores
    print("\n=== Scores by Category ===")
    for cat, scores in sorted(category_scores.items()):
        cat_mean = sum(scores) / len(scores) if scores else 0
        category_means[cat] = cat_mean
        print(f"{cat}: {cat_mean:.3f} ({len(scores)} tasks)")

    # Identify weakest 3 categories
    weakest_cats = []
    if category_means:
        sorted_cats = sorted(category_means.items(), key=lambda x: x[1])
        weakest_cats = sorted_cats[:3]
        print("\n=== Weakest 3 Directions ===")
        for cat, score in weakest_cats:
            print(f"{cat}: {score:.3f}")

        # Save weakest directions for next evolution cycle
        with open("weakest_directions.json", "w") as f:
            json.dump({
                "weakest_directions": weakest_cats,
                "all_category_means": category_means,
                "overall_average": average_score
            }, f, indent=2)
        print("\nWeakest directions saved to weakest_directions.json")

    # Save detailed results to file
    with open("baseline_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Detailed results saved to baseline_results.json")

    # Save training data for train_weakness.py
    training_data = {
        "weakest_directions": weakest_cats,
        "category_details": {
            cat: {
                "mean": category_means.get(cat, 0),
                "tasks": category_tasks.get(cat, []),
                "scores": category_scores.get(cat, [])
            }
            for cat in category_means.keys()
        },
        "all_category_means": category_means,
        "overall_average": average_score,
        "timestamp": datetime.datetime.now().isoformat()
    }
    
    with open("eval_for_training.json", "w") as f:
        json.dump(training_data, f, indent=2)
    print("Training data saved to eval_for_training.json")

    return training_data

def main():
    run_evaluation()

if __name__ == "__main__":
    main()
