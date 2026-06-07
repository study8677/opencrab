#!/usr/bin/env python3
"""核真 git 真跟踪了几行项目账本（projects 目录）"""
import subprocess
import pathlib

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def main():
    # 1. 检查 .gitignore 对 state/ 的处理
    gi = pathlib.Path(".gitignore")
    gi_lines = gi.read_text().splitlines() if gi.exists() else []
    state_ignored = any("state" in l.strip() for l in gi_lines)
    
    print("=== .gitignore 中 state 相关条目 ===")
    for i, l in enumerate(gi_lines, 1):
        if "state" in l.lower():
            print(f"  行 {i}: {l}")
    print(f"  .gitignore 忽略 state: {state_ignored}")
    
    # 2. 检查 projects 目录
    projects_dir = pathlib.Path("projects")
    if not projects_dir.exists():
        print("\n❌ projects/ 目录不存在")
        return
    
    print(f"\n=== projects/ 目录结构 ===")
    for item in sorted(projects_dir.iterdir()):
        print(f"  {'d' if item.is_dir() else 'f'}: {item.name}")
    
    # 3. 检查 git 跟踪的文件
    r = run("git ls-files projects/")
    git_files = [f for f in r.stdout.strip().split("\n") if f]
    
    r2 = run("git ls-files projects/ --stage")
    stage_lines = r2.stdout.strip().split("\n") if r2.stdout.strip() else []
    
    print(f"\n=== git 跟踪 projects/ 下 {len(git_files)} 个文件 ===")
    for f in git_files:
        print(f"  {f}")
    
    # 4. 检查是否有未跟踪文件
    r3 = run("git status --porcelain projects/")
    untracked = [l for l in r3.stdout.strip().split("\n") if l and l.startswith("??")]
    
    print(f"\n=== 未跟踪文件: {len(untracked)} 个 ===")
    for u in untracked:
        print(f"  {u}")
    
    # 5. 统计总行数
    total_lines = 0
    file_lines = {}
    for f in git_files:
        p = pathlib.Path(f)
        if p.exists() and p.suffix in (".json", ".jsonl", ".md", ".txt"):
            lines = len(p.read_text().splitlines())
            total_lines += lines
            file_lines[f] = lines
    
    print(f"\n=== git 跟踪的账本总行数: {total_lines} ===")
    for f, n in sorted(file_lines.items(), key=lambda x: -x[1]):
        print(f"  {f}: {n} 行")
    
    print("\n=== 根因诊断 ===")
    if state_ignored:
        print("⚠️  .gitignore 整体忽略 state/，但 projects/ 在其中吗？")
    print(f"⚠️  git 跟踪 {len(git_files)} 个文件，共 {total_lines} 行")
    print(f"⚠️  未跟踪文件: {len(untracked)} 个")

if __name__ == "__main__":
    main()
