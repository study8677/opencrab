#!/usr/bin/env python3
"""运行 canary 75% 焊死流程"""
import subprocess
import sys

def main():
    print("启动 canary 75% 焊死流程...")
    result = subprocess.run([sys.executable, "do_canary_75_final.py"])
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
