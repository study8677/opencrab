#!/usr/bin/env python3
"""验证 state/projects/ 是否被 git 跟踪，以及 planner 是否读取项目账"""
import subprocess
import os
import sys

# Step 1: 检查 git ls-files
print("=== Step 1: git ls-files state/projects/ ===")
result = subprocess.run(
    ["git", "ls-files", "state/projects/"],
    capture_output=True, text=True
)
print(f"returncode={result.returncode}")
print(f"stdout: {result.stdout!r}")
print(f"stderr: {result.stderr!r}")

# Step 2: 检查 state/projects/ 是否存在
projects_dir = "state/projects/"
if os.path.isdir(projects_dir):
    files = os.listdir(projects_dir)
    print(f"\n=== Step 2: state/projects/ exists, files={files}")
else:
    print(f"\n=== Step 2: state/projects/ does NOT exist yet")
    files = []

# Step 3: 检查 .gitignore 是否在忽略它
print("\n=== Step 3: git check-ignore ===")
for f in files:
    path = os.path.join(projects_dir, f)
    result = subprocess.run(
        ["git", "check-ignore", "-v", path],
        capture_output=True, text=True
    )
    print(f"  {f}: returncode={result.returncode}, stdout={result.stdout.strip()!r}")

# Step 4: 修复 .gitignore 并强制 add
print("\n=== Step 4: Fix .gitignore ===")
gitignore_path = ".gitignore"
if os.path.exists(gitignore_path):
    with open(gitignore_path) as f:
        content = f.read()
    print(f"Current .gitignore:\n{content[:500]}")
    
    # 检查是否有 state/projects/ 相关的忽略规则
    lines = content.split('\n')
    state_projects_ignored = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # 移除任何会忽略 state/projects/ 的模式
        if stripped == "state/projects/" or stripped == "state/projects" or \
           stripped.startswith("#") or stripped == "":
            if "state/projects" in line:
                print(f"  Removing ignore rule: {line!r}")
                continue
        new_lines.append(line)
    
    new_content = '\n'.join(new_lines)
    if "state/projects" not in new_content:
        new_content = new_content.rstrip() + "\n!state/projects/\n!state/projects/**\n"
    
    with open(gitignore_path, 'w') as f:
        f.write(new_content)
    print(f"Updated .gitignore. Now forcing git add...")
    
    # 强制 add
    subprocess.run(["git", "add", "-f", "state/projects/"], check=True)
    print("  git add -f state/projects/ succeeded")
    
    # 验证
    result = subprocess.run(
        ["git", "ls-files", "state/projects/"],
        capture_output=True, text=True
    )
    print(f"\n=== After fix: git ls-files state/projects/ ===")
    print(f"stdout: {result.stdout!r}")
else:
    print(".gitignore not found, creating one")
    with open(gitignore_path, 'w') as f:
        f.write("!state/projects/\n!state/projects/**\n")
    subprocess.run(["git", "add", "-f", "state/projects/"], check=True)
    print("  Created .gitignore and git add succeeded")

# Step 5: 实测 planner.form_intent 是否读取项目账
print("\n=== Step 5: Test planner.form_intent ===")
try:
    from planner import Planner
    planner = Planner()
    
    # 尝试调用 form_intent，模拟用户意图
    # 如果它读取了项目账，应该会问"续旧还是开新"
    print("Calling planner.form_intent (with no args)...")
    result = planner.form_intent()
    print(f"result type: {type(result)}")
    print(f"result: {result}")
    
    # 如果有 projects 相关的处理，应该在 result 或行为中体现
    if hasattr(result, 'message'):
        print(f"message: {result.message}")
    if hasattr(result, 'text'):
        print(f"text: {result.text}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Done ===")
