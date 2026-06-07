#!/usr/bin/env python3
"""核真 fitness ledger 的 git 跟踪状态"""
import subprocess
import pathlib

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def main():
    print("=== 核真 fitness ledger git 跟踪状态 ===\n")
    
    # 找 fitness 相关文件
    patterns = ["**/fitness*.json", "**/fitness*.jsonl", "**/ledger*", "**/projects/**"]
    
    print("=== 搜索项目账本文件 ===")
    for pattern in patterns:
        for p in pathlib.Path(".").glob(pattern):
            if ".git" in str(p):
                continue
            rel = p.relative_to(".")
            size = p.stat().st_size if p.is_file() else 0
            lines = len(p.read_text().splitlines()) if p.is_file() else 0
            print(f"  {rel}: {size} bytes, {lines} 行")
    
    # git ls-files 查 projects
    r = run("git ls-files projects/ 2>/dev/null")
    git_projects = [f for f in r.stdout.strip().split("\n") if f]
    
    r2 = run("git ls-files '*.json' '*.jsonl' 2>/dev/null")
    git_json = [f for f in r2.stdout.strip().split("\n") if f]
    
    print(f"\n=== git 跟踪 ===")
    print(f"  projects/: {len(git_projects)} 个文件")
    print(f"  json/jsonl 总计: {len(git_json)} 个")
    
    # 总 git 行数
    total_lines = 0
    for f in git_projects + git_json:
        p = pathlib.Path(f)
        if p.exists() and p.stat().st_size < 1000000:  # < 1MB
            try:
                total_lines += len(p.read_text().splitlines())
            except:
                pass
    
    print(f"  git 跟踪的项目账本总行数: {total_lines}")
    
    # 检查未跟踪
    r3 = run("git status --porcelain 2>/dev/null")
    untracked = [l for l in r3.stdout.strip().split("\n") 
                 if l and l.startswith("??") and ("projects" in l or "fitness" in l)]
    
    if untracked:
        print(f"\n⚠️  有 {len(untracked)} 个未跟踪的项目/fitness 文件")
        for u in untracked[:5]:
            print(f"  {u}")

if __name__ == "__main__":
    main()
