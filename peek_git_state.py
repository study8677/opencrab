#!/usr/bin/env python3
"""验证 git 状态：gitignore 修复 + state/projects/ 跟踪"""
import subprocess
import os

def run(cmd, desc=""):
    result = subprocess.run(cmd, capture_output=True, text=True, shell=isinstance(cmd, str))
    print(f"\n{'='*50}")
    print(f"  {desc or ' '.join(cmd if isinstance(cmd, list) else cmd.split())}")
    print(f"{'='*50}")
    print(f"Exit: {result.returncode}")
    if result.stdout.strip():
        print(f"OUT:\n{result.stdout}")
    if result.stderr.strip():
        print(f"ERR:\n{result.stderr}")
    return result

def main():
    # 1. 检查 state/projects/ 是否被 gitignore 忽略
    run(['git', 'check-ignore', '-v', 'state/projects/'], "git check-ignore state/projects/")
    
    # 2. 检查 state/ 是否被整体忽略
    run(['git', 'check-ignore', '-v', 'state/'], "git check-ignore state/")
    
    # 3. 查看 .gitignore 前 15 行
    print(f"\n{'='*50}")
    print("  .gitignore (前15行)")
    print(f"{'='*50}")
    if os.path.exists('.gitignore'):
        with open('.gitignore', 'r') as f:
            lines = f.readlines()
        for i, line in enumerate(lines[:15], 1):
            marker = " <-- LINE 11" if i == 11 else ""
            print(f"  {i:2}: {line.rstrip()}{marker}")
    else:
        print("  .gitignore 不存在")
    
    # 4. 检查 git ls-files
    run(['git', 'ls-files', 'state/projects/'], "git ls-files state/projects/")
    
    # 5. 列出 state/projects/ 目录内容
    print(f"\n{'='*50}")
    print("  state/projects/ 目录内容")
    print(f"{'='*50}")
    if os.path.exists('state/projects/'):
        for f in os.listdir('state/projects/'):
            path = f'state/projects/{f}'
            ignored = subprocess.run(['git', 'check-ignore', '-v', path], capture_output=True)
            status = "🚫 ignored" if ignored.returncode == 0 else "✅ tracked"
            print(f"  {status}: {f}")
    else:
        print("  state/projects/ 目录不存在")

if __name__ == '__main__':
    main()
