#!/usr/bin/env python3
"""快速检查语法"""

import py_compile
import sys

files = [
    'canary_75_evolution.py',
    'do_canary_readpack_brainonly_patch.py',
    'execute_canary_75.py',
    'go_canary_75.py',
    'check_crab.py',
]

ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"✓ {f}")
    except py_compile.PyCompileError as e:
        print(f"✗ {f}: {e}")
        ok = False

sys.exit(0 if ok else 1)
