#!/usr/bin/env python3
"""临时脚本：读取 autopsys_real_weld.py 并执行获取真实输出"""
import subprocess
import sys

print("=" * 60)
print("执行: python autopsy_real_weld.py")
print("=" * 60)

result = subprocess.run(
    ["python", "autopsy_real_weld.py"],
    capture_output=True,
    text=True,
    timeout=60
)

print("STDOUT:")
print(result.stdout)
if result.stderr:
    print("STDERR:")
    print(result.stderr)
print(f"\n退出码: {result.returncode}")
