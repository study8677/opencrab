#!/usr/bin/env python3
"""核验 .gitignore 修复是否真生效"""
import subprocess
from pathlib import Path

def check_gitignore():
    target = "state/projects/项目账.md"
    result = subprocess.run(
        ["git", "check-ignore", "-v", target],
        capture_output=True, text=True
    )
    print(f"stdout: {result.stdout}")
    print(f"stderr: {result.stderr}")
    print(f"returncode: {result.returncode}")
    
    # returncode 0 = 被 gitignore 忽略（已修复）
    # returncode 128 = 路径不存在于 git 追踪中（正常）
    # returncode 1 = 路径未被忽略（未修复！）
    if result.returncode == 1:
        print("\n>>> .gitignore 未生效！路径仍在被追踪 <<<")
        return False
    elif result.returncode == 0:
        print("\n>>> .gitignore 已生效！路径已被忽略 <<<")
        return True
    else:
        print(f"\n>>> returncode={result.returncode}，需人工确认 <<<")
        return None

if __name__ == "__main__":
    check_gitignore()
