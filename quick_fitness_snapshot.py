#!/usr/bin/env python3
"""quick_fitness_snapshot: Fast peek at arena/boundaryeval/regression/canary scores."""
import json
import os
import sys

def peek_module(module_name):
    """Try to import and call a quick_report() on a module."""
    try:
        mod = __import__(module_name)
        if hasattr(mod, 'quick_report'):
            return mod.quick_report()
        if hasattr(mod, 'report'):
            return mod.report()
        if hasattr(mod, 'score'):
            return {"score": mod.score}
        # Try to find a data file
        data_paths = [
            f"{module_name}_result.json",
            f"{module_name}/result.json",
            f"results/{module_name}.json",
            f".{module_name}_fitness.json",
        ]
        for p in data_paths:
            if os.path.exists(p):
                with open(p) as f:
                    return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    return {"error": "no data found"}

def main():
    modules = ['arena', 'boundaryeval', 'regression', 'canary', 
               'boundaryeval_aegis_absorption_regression',
               'boundaryeval_malicious_intent_regression',
               'boundaryeval_redteam_regression',
               'boundaryeval_regression',
               'brainonly_benefit_chain_regression',
               'brainonly_blindfix_regression',
               'brainonly_canary_patch']
    
    print("=== Fitness Snapshot ===\n")
    results = {}
    for m in modules:
        r = peek_module(m)
        results[m] = r
        print(f"[{m}]")
        print(json.dumps(r, indent=2))
        print()
    
    # Also check if there's a fitness ledger
    ledger_paths = [
        'fitness_ledger.json',
        '.fitness_ledger.json',
        'data/fitness_ledger.json',
    ]
    for lp in ledger_paths:
        if os.path.exists(lp):
            print(f"=== Fitness Ledger ({lp}) ===")
            with open(lp) as f:
                ledger = json.load(f)
            print(json.dumps(ledger, indent=2))
            break
    
    # Save snapshot
    with open('fitness_snapshot.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("\nSaved snapshot to fitness_snapshot.json")

if __name__ == '__main__':
    main()
