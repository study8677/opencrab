#!/usr/bin/env python3
"""检查关键模块是否存在且可用"""

import sys
from pathlib import Path

def check_module(name):
    """检查模块是否存在"""
    try:
        __import__(name)
        return True, None
    except ImportError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Error: {e}"

def main():
    modules = [
        'crab',
        'fitness_status',
        'check_fitness_json',
        'check_three_gates_canary',
    ]
    
    print("检查关键模块:")
    all_ok = True
    for m in modules:
        ok, err = check_module(m)
        status = "✓" if ok else "✗"
        print(f"  {status} {m}")
        if not ok:
            print(f"    -> {err}")
            all_ok = False
    
    if not all_ok:
        print("\n部分模块不可用，需要修复")
        sys.exit(1)
    else:
        print("\n所有关键模块可用")
        sys.exit(0)

if __name__ == "__main__":
    main()
