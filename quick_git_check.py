#!/usr/bin/env python3
"""快速核真 git 跟踪状态"""
import subprocess
import pathlib

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def main():
    # 1. gitignore 中 state 条目
    gi = pathlib.Path(".gitignore")
    if gi.exists():
        lines = gi.read_text().splitlines()
        state_lines = [(i+1, l) for i, l in enumerate(lines) if "state" in l.lower()]
        print(f"=== .gitignore 中 state 条目 ===")
        if state_lines:
            for i, l in state_lines:
                print(f"  行 {i}: {l}")
        else:
            print("  ❌ 没有 state 相关条目")
        
        # 检查 projects 条目
        projects_lines = [(i+1, l) for i, l in enumerate(lines) if "projects" in l.lower()]
        print(f"\n=== .gitignore 中 projects 条目 ===")
        if projects_lines:
            for i, l in projects_lines:
                print(f"  行 {i}: {l}")
        else:
            print("  ⚠️  没有 projects 相关条目（可能被通配符覆盖）")
    
    # 2. git 跟踪的 files
    r = run("git ls-files 2>/dev/null")
    all_files = [f for f in r.stdout.strip().split("\n") if f]
    
    state_files = [f for f in all_files if "state" in f.lower()]
    projects_files = [f for f in all_files if "projects" in f.lower()]
    
    print(f"\n=== git 跟踪情况 ===")
    print(f"  总文件数: {len(all_files)}")
    print(f"  state 相关: {len(state_files)}")
    print(f"  projects 相关: {len(projects_files)}")
    
    for f in projects_files:
        print(f"    {f}")
    
    # 3. 根因
    print(f"\n=== 根因诊断 ===")
    if state_files:
        print(f"⚠️  git 仍在跟踪 {len(state_files)} 个 state 相关文件")
        print("   这意味着 .gitignore 的 state 条目没生效")
    else:
        print("✅ git 没有跟踪 state 文件（.gitignore 生效了）")
    
    if not projects_files:
        print("⚠️  git 没有跟踪 projects 文件——可能被忽略了")

if __name__ == "__main__":
    main()
