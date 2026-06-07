#!/usr/bin/env python3
"""把 projects ledger 提交 git（如果还没跟踪的话）"""
import subprocess
import pathlib

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result

def main():
    print("=== 核真并修复 projects ledger git 跟踪 ===\n")
    
    projects_dir = pathlib.Path("projects")
    if not projects_dir.exists():
        print("❌ projects/ 不存在，无需操作")
        return
    
    # 检查 .gitignore 是否忽略了 projects
    gi = pathlib.Path(".gitignore")
    if gi.exists():
        gi_content = gi.read_text()
        if "projects" in gi_content:
            print("⚠️  .gitignore 包含 'projects' 条目")
            lines = gi_content.splitlines()
            for i, l in enumerate(lines, 1):
                if "projects" in l:
                    print(f"  行 {i}: {l}")
    
    # git status projects/
    r = run("git status --porcelain projects/ 2>/dev/null")
    status = r.stdout.strip()
    
    if not status:
        print("✅ projects/ 已经全部 git 跟踪")
        
        # 统计行数
        r2 = run("git ls-files projects/ 2>/dev/null")
        files = [f for f in r2.stdout.strip().split("\n") if f]
        total = 0
        for f in files:
            p = pathlib.Path(f)
            if p.exists():
                total += len(p.read_text().splitlines())
        print(f"   git 跟踪 {len(files)} 个文件，共 {total} 行")
    else:
        print("❌ projects/ 有未跟踪或修改的文件:")
        print(status)
        print("\n需要: git add projects/ && git commit")

if __name__ == "__main__":
    main()
