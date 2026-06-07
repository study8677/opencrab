#!/usr/bin/env python3
"""regression.py — 回归检查：确保补丁不引入新问题"""

import subprocess, sys, json
from pathlib import Path

def run_cmd(cmd, timeout=120):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr

def main():
    print("[regression] 检查回归...")

    checks = [
        ("语法", "python check_syntax.py"),
        ("Fitness基线", "python do_real_fitness_baseline.py"),
        ("Organ验证", "python organ_verification.py"),
    ]

    all_ok = True
    for name, cmd in checks:
        print(f"  [regression] {name}...", end="", flush=True)
        code, out, err = run_cmd(cmd, timeout=300)
        ok = code == 0
        print(f" {'✅' if ok else '❌'}")
        if not ok:
            all_ok = False

    if all_ok:
        print("[regression] ✅ 无回归")
        return 0
    else:
        print("[regression] ⚠️ 存在回归")
        return 1

if __name__ == "__main__":
    sys.exit(main())
