#!/usr/bin/env python3
"""修复 .gitignore 第11行，移除对 state/projects/ 的忽略"""
import subprocess
import os

def fix_gitignore_line11():
    with open('.gitignore', 'r') as f:
        lines = f.readlines()
    
    print(f"原始第11行: {lines[10].rstrip()}")
    
    # 注释掉第11行
    if not lines[10].strip().startswith('#'):
        lines[10] = '# ' + lines[10]
    
    with open('.gitignore', 'w') as f:
        f.writelines(lines)
    
    print(f"修改后第11行: {lines[10].rstrip()}")
    
    # 验证 git check-ignore
    result = subprocess.run(
        ['git', 'check-ignore', '-v', 'state/projects/'],
        capture_output=True, text=True
    )
    print(f"\ngit check-ignore 验证:")
    print(f"  Exit code: {result.returncode} (0=正常追踪, 非0=被忽略)")
    
    # git add + commit
    subprocess.run(['git', 'add', '.gitignore'])
    result = subprocess.run(
        ['git', 'commit', '-m', 'fix: allow state/projects/ in git - fix cross-heartbeat memory loss'],
        capture_output=True, text=True
    )
    print(f"\nCommit 结果:")
    print(f"  {result.stdout}")
    if result.stderr:
        print(f"  {result.stderr}")
    
    # git status
    result = subprocess.run(['git', 'status'], capture_output=True, text=True)
    print(f"\ngit status:")
    print(result.stdout)

if __name__ == '__main__':
    fix_gitignore_line11()
