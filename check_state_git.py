#!/usr/bin/env python3
"""检查 state/ 目录的 git 状态"""
import subprocess
import os

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

# 1. 检查 state/ 是否存在
state_exists = os.path.isdir('state')
print(f"state/ 目录存在: {state_exists}")

# 2. 检查 .gitignore 内容
gitignore_content = ""
if os.path.exists('.gitignore'):
    with open('.gitignore', 'r') as f:
        gitignore_content = f.read()
    print("\n=== .gitignore 内容 (含 state 的行) ===")
    for i, line in enumerate(gitignore_content.split('\n'), 1):
        if 'state' in line.lower():
            print(f"  行 {i}: {line}")

# 3. 检查 state/ 是否被 git 跟踪
print("\n=== git ls-files 检查 ===")
out, err, _ = run("git ls-files state/")
print(f"git ls-files state/: '{out}'")
if out:
    print("  → state/ 已被 git 跟踪")
else:
    print("  → state/ 未被 git 跟踪")

# 4. 检查 git status for state/
out, err, _ = run("git status --porcelain state/")
print(f"\ngit status --porcelain state/: '{out}'")
if not out:
    print("  → state/ 无变更 (可能已忽略)")

# 5. 检查 state/ 是否在 .gitignore 中
lines = gitignore_content.split('\n')
state_in_gitignore = [l for l in lines if 'state' in l.lower() and not l.strip().startswith('#')]
print(f"\nstate/ 在 .gitignore 中的行: {state_in_gitignore}")

if state_in_gitignore:
    print("\n❌ state/ 被 .gitignore 忽略，需要修复!")
else:
    print("\n✓ state/ 不在 .gitignore 中")
    if state_exists:
        print("   但需要确认 git add 状态")
EOF
