#!/usr/bin/env python3
"""修复 .gitignore 并 commit"""
import subprocess
from pathlib import Path

def fix_gitignore():
    gitignore = Path(".gitignore")
    
    # 读取现有内容
    if gitignore.exists():
        content = gitignore.read_text()
    else:
        content = ""
    
    # 检查是否已有 state/projects/ 相关忽略规则
    if "state/projects/" not in content:
        # 添加忽略规则
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n# State projects\nstate/projects/\n"
        gitignore.write_text(content)
        print("已更新 .gitignore")
    else:
        print(".gitignore 已包含 state/projects/ 规则")
    
    # 验证
    result = subprocess.run(
        ["git", "check-ignore", "-v", "state/projects/项目账.md"],
        capture_output=True, text=True
    )
    print(f"验证结果: returncode={result.returncode}")
    print(f"stdout: {result.stdout}")
    
    # Commit
    subprocess.run(["git", "add", ".gitignore"], check=True)
    subprocess.run([
        "git", "commit", "-m", 
        "fix: ignore state/projects/ to prevent ledger contamination"
    ], check=True)
    print("已 commit")

if __name__ == "__main__":
    fix_gitignore()
