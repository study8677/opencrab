#!/usr/bin/env python3
"""执行最终检查"""
import py_compile
import sys

files = [
    "canary_75_evolution.py",
    "go_canary_75.py",
    "check_crab.py",
    "execute_canary_75.py",
    "canary_75.py",
    "verify_all.py",
    "do_canary_readpack_brainonly_patch.py",
    "fitness_status.py",
    "check_fitness_json.py",
    "peek_weakest.py",
    "run_now.py",
    "run_canary_evolution.py",
]

ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"OK: {f}")
    except:
        print(f"FAIL: {f}")
        ok = False

import crab
print(f"crab OK: {crab.__file__}")

sys.exit(0 if ok else 1)
