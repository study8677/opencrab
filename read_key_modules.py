#!/usr/bin/env python3
"""read_key_modules: display content of key modules for analysis."""
import os

KEY_MODULES = [
    'regression.py',
    'canary.py',
    'canary_75.py',
    'brainonly_canary_patch.py',
    'brainonly_blindfix_regression.py',
    'brainonly_benefit_chain_regression.py',
    'boundaryeval_regression.py',
]

def main():
    for mod in KEY_MODULES:
        if os.path.exists(mod):
            print(f"\n{'='*60}")
            print(f"FILE: {mod}")
            print('='*60)
            with open(mod) as f:
                print(f.read())
        else:
            print(f"\n{'='*60}")
            print(f"FILE: {mod} — NOT FOUND")
            print('='*60)

if __name__ == '__main__':
    main()
