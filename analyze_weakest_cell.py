#!/usr/bin/env python3
"""analyze_weakest_cell: find brain-only patchable weakness in 4 fitness dimensions."""
import ast
import os

def count_lines(filepath):
    """Count non-empty lines in a Python file."""
    try:
        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip() and not l.strip().startswith('#')]
        return len(lines)
    except:
        return 999

def get_module_info(name):
    """Get file path and line count for a module."""
    candidates = [f"{name}.py", f"{name}/__init__.py"]
    for c in candidates:
        if os.path.exists(c):
            return c, count_lines(c)
    return None, 999

def main():
    modules = {
        'arena': 'arena.py',
        'boundaryeval': 'boundaryeval.py',
        'regression': 'regression.py',
        'canary': 'canary.py',
        # Brain-only variants
        'brainonly_benefit_review': 'brainonly_benefit_review.py',
        'brainonly_external_validation': 'brainonly_external_validation.py',
        'brainonly_graduation_sample': 'brainonly_graduation_sample.py',
        'brainonly_heatmap': 'brainonly_heatmap.py',
        'brainonly_replay': 'brainonly_replay.py',
        'brainonly_benefit_chain_regression': 'brainonly_benefit_chain_regression.py',
        'brainonly_blindfix_regression': 'brainonly_blindfix_regression.py',
        'brainonly_canary_patch': 'brainonly_canary_patch.py',
        # Regression variants
        'boundaryeval_aegis_absorption_regression': 'boundaryeval_aegis_absorption_regression.py',
        'boundaryeval_malicious_intent_regression': 'boundaryeval_malicious_intent_regression.py',
        'boundaryeval_redteam_regression': 'boundaryeval_redteam_regression.py',
        'boundaryeval_regression': 'boundaryeval_regression.py',
    }
    
    print("=== Module Line Counts (smaller = simpler to patch) ===\n")
    rows = []
    for name, path in modules.items():
        if os.path.exists(path):
            lines = count_lines(path)
            size = "SMALL" if lines < 100 else "MEDIUM" if lines < 300 else "LARGE"
            rows.append((name, path, lines, size))
            print(f"{name:45s} {lines:4d} lines [{size}]")
    
    # Find brain-only modules that are small enough for single-point surgery
    print("\n=== Brain-Only Modules Eligible for Single-Point Surgery (≤100 lines) ===")
    eligible = [(n, p, l) for n, p, l, s in rows if 'brainonly' in n and l <= 100]
    for n, p, l in sorted(eligible, key=lambda x: x[2]):
        print(f"  {n}: {l} lines -> {p}")
    
    if eligible:
        # Pick the smallest one
        best = min(eligible, key=lambda x: x[2])
        print(f"\n*** BEST TARGET: {best[0]} ({best[2]} lines) ***")
        
        # Show its content
        print(f"\n=== Content of {best[1]} ===")
        with open(best[1]) as f:
            print(f.read())
    else:
        print("\nNo brain-only module ≤100 lines. Checking MEDIUM (≤300)...")
        eligible = [(n, p, l) for n, p, l, s in rows if 'brainonly' in n and l <= 300]
        if eligible:
            best = min(eligible, key=lambda x: x[2])
            print(f"\n*** BEST TARGET: {best[0]} ({best[2]} lines) ***")
            with open(best[1]) as f:
                print(f.read())

if __name__ == '__main__':
    main()
