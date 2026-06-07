#!/usr/bin/env python3
"""check_syntax.py — 检查 crab.py 语法正确性"""

import py_compile, sys
from pathlib import Path

def main():
    crab = Path("crab.py")
    if not crab.exists():
        print("[syntax] crab.py 不存在")
        return 1
    try:
        py_compile.compile(str(crab), doraise=True)
        print("[syntax] ✅ crab.py 语法正确")
        return 0
    except py_compile.PyCompileError as e:
        print(f"[syntax] ❌ 语法错误: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
