#!/usr/bin/env python3
"""修复 state/ 目录的 git 忽略问题"""
import subprocess
import os
import re

def run(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"命令失败: {cmd}")
        print(f"stderr: {result.stderr}")
    return result.stdout.strip(), result.stderr.strip(), result.returncode

# 读取 .gitignore
with open('.gitignore', 'r') as f:
    content = f.read()

lines = content.split('\n')
new_lines = []
removed = []
for line in lines:
    # 匹配包含 state 的非注释行（可能是 state/ 或 state 或 /state）
    if re.match(r'^\s*state[/]?\s*$', line) or \
       re.match(r'^\s*/state[/]?\s*$', line) or \
       re.match(r'^\s*state/\*\s*$', line):
        removed.append(line)
        continue
    new_lines.append(line)

if removed:
    print(f"找到并移除 {len(removed)} 条 state 相关规则:")
    for r in removed:
        print(f"  - '{r}'")
    
    new_content = '\n'.join(new_lines)
    # 确保末尾有换行
    if not new_content.endswith('\n'):
        new_content += '\n'
    
    with open('.gitignore', 'w') as f:
        f.write(new_content)
    print("\n已更新 .gitignore")
else:
    print("未找到需要移除的 state 规则")

# 提交更改
print("\n=== 提交 .gitignore 修改 ===")
run("git add .gitignore")
out, err, _ = run("git diff --cached --stat")
print(f"git diff --cached: {out}")

# 检查 state/ 是否存在
if os.path.isdir('state'):
    print("\n=== 添加 state/ 目录 ===")
    # 强制添加（忽略 ignore 规则）
    run("git add -f state/")
    out, err, _ = run("git status --short state/")
    print(f"state/ 状态: {out}")
else:
    print("\nstate/ 目录不存在，跳过添加")

# 最终状态
print("\n=== 最终状态 ===")
out, err, _ = run("git status --short")
print(out)
