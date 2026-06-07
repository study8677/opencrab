#!/usr/bin/env python3
"""验证 state/ 已提交到 git"""
import subprocess
import os

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

# 检查 state/ 是否在 git 仓库中
out, err, _ = run("git ls-files state/")
print("git ls-files state/:")
print(f"  stdout: '{out}'")
print(f"  stderr: '{err}'")

if out:
    print("\n✓ state/ 已被 git 跟踪!")
    # 显示具体文件
    files = out.split('\n')
    print(f"  包含 {len(files)} 个文件:")
    for f in files[:10]:
        print(f"    {f}")
    if len(files) > 10:
        print(f"    ... 还有 {len(files)-10} 个")
else:
    print("\n✗ state/ 仍未被 git 跟踪")

# 检查最近的提交
out, err, _ = run("git log --oneline -3 -- state/")
if out:
    print(f"\n最近涉及 state/ 的提交:")
    print(out)
else:
    print("\n没有涉及 state/ 的历史提交")
