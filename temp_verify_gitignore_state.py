#!/usr/bin/env python3
"""验证 state/ 目录是否被 git 跟踪，以及 form_intent 是否会读它。"""
import subprocess
import sys

def run_cmd(cmd, desc):
    print(f"\n{'='*60}")
    print(f"[{desc}]")
    print(f"CMD: {cmd}")
    print('-'*60)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr}")
    return result

# 1. 检查 .gitignore 中是否有 state/
print("\n[1] 检查 .gitignore 是否仍包含 state/")
run_cmd("grep -n 'state' .gitignore 2>/dev/null || echo 'NOT FOUND in .gitignore'", "grep state in .gitignore")

# 2. 检查 state/ 目录是否存在
print("\n[2] 检查 state/ 目录是否存在")
run_cmd("ls -la state/ 2>/dev/null || echo 'state/ 目录不存在'", "ls state/")

# 3. 用 git ls-files 检查 state/ 是否被跟踪
print("\n[3] git ls-files state/ - 检查 state/ 是否被 git 跟踪")
run_cmd("git ls-files state/", "git ls-files state/")

# 4. 检查 form_intent 函数是否读取 state/
print("\n[4] 检查 form_intent 代码是否读 state/")
run_cmd("grep -n 'state' crab.py intent.py planner.py 2>/dev/null | head -50", "grep state in form_intent files")

print("\n" + "="*60)
print("验证完成")
