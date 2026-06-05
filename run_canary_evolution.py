#!/usr/bin/env python3
"""
run_canary_evolution.py - 运行 canary 75% 进化

用法:
    python run_canary_evolution.py          # 运行完整流程
    python run_canary_evolution.py --merge  # 只做并入
"""

import sys
import subprocess

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--merge', action='store_true', help='Only run merge')
    args = parser.parse_args()
    
    if args.merge:
        # 只做并入
        print("Running merge...")
        result = subprocess.run(
            ["python", "canary_75_evolution.py"],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        return result.returncode
    
    # 运行完整流程
    print("Running canary 75% evolution...")
    result = subprocess.run(
        ["python", "canary_75_evolution.py"],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
