#!/usr/bin/env python3
"""验证 state/projects/ 的 gitignore 状态"""
import subprocess
import os

def check_gitignore():
    # 运行 git check-ignore -v
    result = subprocess.run(
        ['git', 'check-ignore', '-v', 'state/projects/'],
        capture_output=True, text=True
    )
    print(f"Exit code: {result.returncode}")
    print(f"Stdout: {result.stdout}")
    print(f"Stderr: {result.stderr}")
    
    # 读取 .gitignore 第11行
    if os.path.exists('.gitignore'):
        with open('.gitignore', 'r') as f:
            lines = f.readlines()
        print(f"\n.gitignore 共 {len(lines)} 行:")
        for i, line in enumerate(lines[:15], 1):
            marker = " <-- LINE 11" if i == 11 else ""
            print(f"  {i:2}: {line.rstrip()}{marker}")
    else:
        print(".gitignore 不存在")

if __name__ == '__main__':
    check_gitignore()
