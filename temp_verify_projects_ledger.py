#!/usr/bin/env python3
"""临时验证 projects/ ledger 的 git 跟踪行数"""
import subprocess
import pathlib

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def main():
    print("=== 验证 projects/ ledger git 跟踪行数 ===\n")
    
    # 检查目录存在
    projects_dir = pathlib.Path("projects")
    state_dir = pathlib.Path("state")
    
    print(f"projects/: {'存在' if projects_dir.exists() else '不存在'}")
    print(f"state/: {'存在' if state_dir.exists() else '不存在'}")
    
    # git ls-files
    r = run("git ls-files projects/ 2>/dev/null")
    git_files = [f for f in r.stdout.strip().split("\n") if f]
    
    print(f"\ngit 跟踪 projects/ 下 {len(git_files)} 个文件")
    
    # 统计行数
    total = 0
    details = []
    for f in git_files:
        p = pathlib.Path(f)
        if p.exists():
            try:
                lines = len(p.read_text().splitlines())
                total += lines
                details.append((f, lines))
            except:
                pass
    
    print(f"总行数: {total}")
    for f, n in sorted(details, key=lambda x: -x[1]):
        print(f"  {f}: {n} 行")
    
    # 未跟踪
    r2 = run("git status --porcelain projects/ 2>/dev/null")
    untracked = [l for l in r2.stdout.strip().split("\n") if l.startswith("??")]
    if untracked:
        print(f"\n⚠️  {len(untracked)} 个未跟踪文件:")
        for u in untracked:
            print(f"  {u}")

if __name__ == "__main__":
    main()
