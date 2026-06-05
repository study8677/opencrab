#!/usr/bin/env python3
"""运行基线测试"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

# 运行 quick 模式
print("="*60)
print("运行 run_fitness_baseline.py --quick")
print("="*60)

result = subprocess.run(
    [sys.executable, "run_fitness_baseline.py", "--quick", "--output-md"],
    cwd=REPO_ROOT,
    capture_output=True,
    text=True
)

print("STDOUT:")
print(result.stdout)
if result.stderr:
    print("STDERR:")
    print(result.stderr)
print(f"\n返回码: {result.returncode}")
