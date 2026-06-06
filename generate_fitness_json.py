#!/usr/bin/env python3
"""generate_fitness_json: run all 4 fitness dimensions and save fitness.json."""
import json
import time
import random

# Set seed for reproducibility during this run
random.seed(42)

def run_canary():
    """Run canary evaluation."""
    import canary
    c = canary.Canary()
    return c.run()

def run_boundaryeval():
    """Run boundaryeval evaluation."""
    try:
        import boundaryeval
        b = boundaryeval.BoundaryEval()
        return b.run()
    except Exception as e:
        return {'score': 0.0, 'error': str(e), 'module': 'boundaryeval'}

def run_regression():
    """Run regression evaluation."""
    try:
        import regression
        r = regression.Regression()
        return r.run()
    except Exception as e:
        return {'score': 0.0, 'error': str(e), 'module': 'regression'}

def run_arena():
    """Run arena evaluation."""
    try:
        import arena
        a = arena.Arena()
        return a.run()
    except Exception as e:
        return {'score': 0.0, 'error': str(e), 'module': 'arena'}

def main():
    print("=== Generating fitness.json ===\n")
    
    # Run all 4 dimensions
    results = {
        'timestamp': time.strftime("%Y-%m-%dT%H:%M:%S"),
        'arena': run_arena(),
        'boundaryeval': run_boundaryeval(),
        'regression': run_regression(),
        'canary': run_canary(),
    }
    
    # Extract scores
    scores = {}
    for dim in ['arena', 'boundaryeval', 'regression', 'canary']:
        r = results.get(dim, {})
        scores[dim] = r.get('score', r.get('pass_rate', 0.0))
    
    results['scores'] = scores
    
    # Find weakest
    weakest = min(scores.items(), key=lambda x: x[1])
    results['weakest'] = {'dimension': weakest[0], 'score': weakest[1]}
    
    # Summary
    print("\n=== 4-Grid Fitness Scores ===")
    for dim, score in scores.items():
        status = "✓ PASS" if score >= 0.5 else "✗ FAIL"
        print(f"  {dim:<15} {score:.2f} {status}")
    
    print(f"\nWeakest: {weakest[0]} at {weakest[1]:.2f}")
    
    # Save
    with open('fitness.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to fitness.json")
    
    return results

if __name__ == '__main__':
    main()
