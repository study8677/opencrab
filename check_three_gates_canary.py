#!/usr/bin/env python3
"""
check_three_gates_canary.py - 试衣间三闸 for canary 80%
Gate1: 语法正确
Gate2: import 不炸  
Gate3: 基础功能不退
"""
import ast
import subprocess
import sys
from pathlib import Path

def gate1_syntax(path):
    """Gate 1: Python 语法正确"""
    try:
        with open(path) as f:
            compile(f.read(), str(path), 'exec')
        return True, "OK"
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"

def gate2_import(path):
    """Gate 2: 模块可导入"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"import sys; sys.path.insert(0, '.'); import {path.stem}"],
            capture_output=True, timeout=10
        )
        if result.returncode == 0:
            return True, "OK"
        return False, result.stderr.decode()[:100]
    except Exception as e:
        return False, str(e)

def gate3_smoke():
    """Gate 3: 基础冒烟测试"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", """
import crab
print("smoke_ok")
"""],
            capture_output=True, timeout=15
        )
        if result.returncode == 0 and b"smoke_ok" in result.stdout:
            return True, "OK"
        return False, result.stderr.decode()[:100]
    except Exception as e:
        return False, str(e)

def check_all(path="crab.py"):
    """三闸全检"""
    p = Path(path)
    if not p.exists():
        return {"error": f"{path} not found"}
    
    g1, m1 = gate1_syntax(p)
    g2, m2 = gate2_import(p)
    g3, m3 = gate3_smoke()
    
    result = {
        "gate1_syntax": g1,
        "gate1_msg": m1,
        "gate2_import": g2,
        "gate2_msg": m2,
        "gate3_smoke": g3,
        "gate3_msg": m3,
        "all_pass": g1 and g2 and g3
    }
    
    return result

def main():
    result = check_all()
    
    print("=" * 50)
    print("THREE GATES CHECK for canary")
    print("=" * 50)
    
    for k, v in result.items():
        status = "PASS" if isinstance(v, bool) and v else ("FAIL" if isinstance(v, bool) and not v else "")
        print(f"  {k}: {v} {status}")
    
    if result.get("all_pass"):
        print("\n>>> ALL GATES PASSED <<<")
        return 0
    else:
        print("\n>>> GATES FAILED - BLOCK <<<")
        return 1

if __name__ == "__main__":
    sys.exit(main())
