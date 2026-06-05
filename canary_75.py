#!/usr/bin/env python3
"""
canary_75.py - 主入口

用法:
    python canary_75.py          # 完整流程
    python canary_75.py --dry    # 干跑
"""

import sys
import subprocess

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry', action='store_true', help='Dry run')
    args = parser.parse_args()
    
    if args.dry:
        print("Dry run mode")
        # 只是检查
        subprocess.run(["python", "check_syntax.py"])
        return 0
    
    # 运行完整流程
    print("Running canary 75% evolution...")
    return subprocess.call(["python", "go_canary_75.py"])

if __name__ == "__main__":
    sys.exit(main())
