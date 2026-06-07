#!/usr/bin/env python3
"""
temp_run_canary_80.py - 跑通 canary 80% 全链路
go_canary_80 → check_three_gates → reproduce_3x → commit
"""
import subprocess
import sys

def run_step(name, script):
    print(f"\n{'='*50}")
    print(f"STEP: {name}")
    print('='*50)
    result = subprocess.run([sys.executable, script])
    return result.returncode

def main():
    steps = [
        ("Three Gates Check", "check_three_gates_canary.py"),
        ("3x Reproduction", "reproduce_canary_3x.py"),
        ("Do Brain-only Fix", "do_canary_80_final.py"),
    ]
    
    for name, script in steps:
        rc = run_step(name, script)
        if rc != 0:
            print(f"\n[ABORT] Step failed: {name}")
            return rc
    
    print(f"\n{'='*50}")
    print("CANARY 80% PIPELINE COMPLETE")
    print('='*50)
    return 0

if __name__ == "__main__":
    sys.exit(main())
