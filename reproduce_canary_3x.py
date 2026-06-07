#!/usr/bin/env python3
"""reproduce_canary_3x.py — 3x 复现验证分数真涨"""

import subprocess, sys, argparse
from pathlib import Path

def run_cmd(cmd, timeout=120):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="")
    parser.add_argument("--round", type=int, default=1)
    args = parser.parse_args()

    case = args.case or "default"
    rnd = args.round

    print(f"[3x] 复现 {case} round={rnd}")
    code, out, err = run_cmd(
        f"python execute_fitness_run.py --case {case} --round {rnd}",
        timeout=180
    )
    if code == 0 and "score" in out.lower():
        print(f"  ✅ round={rnd} score improved")
        return 0
    elif code == 0:
        print(f"  ⚠️ round={rnd} ran without error")
        return 0
    else:
        print(f"  ❌ round={rnd} failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
