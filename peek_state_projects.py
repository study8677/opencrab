#!/usr/bin/env python3
"""核真 state/ 和 projects/ 的真实关系"""
import pathlib

def main():
    print("=== 核真 state/ vs projects/ 关系 ===\n")
    
    state_dir = pathlib.Path("state")
    projects_dir = pathlib.Path("projects")
    
    # 1. 各自状态
    print(f"state/: {'✅' if state_dir.exists() else '❌'} {state_dir}")
    print(f"projects/: {'✅' if projects_dir.exists() else '❌'} {projects_dir}")
    
    # 2. state/ 内容
    if state_dir.exists():
        items = list(state_dir.iterdir())
        print(f"\n  state/ 下有 {len(items)} 个条目:")
        for it in sorted(items)[:10]:
            st = "d" if it.is_dir() else "f"
            print(f"    [{st}] {it.name}")
        if len(items) > 10:
            print(f"    ... 还有 {len(items)-10} 个")
    
    # 3. projects/ 内容
    if projects_dir.exists():
        items = list(projects_dir.iterdir())
        print(f"\n  projects/ 下有 {len(items)} 个条目:")
        for it in sorted(items)[:10]:
            st = "d" if it.is_dir() else "f"
            print(f"    [{st}] {it.name}")
        if len(items) > 10:
            print(f"    ... 还有 {len(items)-10} 个")
    
    # 4. 是否有重复
    print(f"\n=== 根因: 是否有重复数据? ===")
    
    state_projects = set()
    if state_dir.exists():
        for it in state_dir.iterdir():
            if it.is_dir():
                state_projects.add(it.name)
    
    projects_items = set()
    if projects_dir.exists():
        for it in projects_dir.iterdir():
            if it.is_dir():
                projects_items.add(it.name)
    
    overlap = state_projects & projects_items
    only_state = state_projects - projects_items
    only_projects = projects_items - state_projects
    
    print(f"  两者都有: {len(overlap)} 个")
    for name in sorted(overlap)[:5]:
        print(f"    {name}")
    
    print(f"  仅 state/: {len(only_state)} 个")
    for name in sorted(only_state)[:5]:
        print(f"    {name}")
    
    print(f"  仅 projects/: {len(only_projects)} 个")
    for name in sorted(only_projects)[:5]:
        print(f"    {name}")
    
    print(f"\n=== 结论 ===")
    if not state_dir.exists() and not projects_dir.exists():
        print("❌ 两个目录都不存在——系统没有项目记录")
    elif not projects_dir.exists() and state_dir.exists():
        print("❌ 只有 state/，没有 projects/——可能数据在 state/ 里")
    elif projects_dir.exists() and not state_dir.exists():
        print("✅ 只有 projects/，正常")
    else:
        if overlap:
            print(f"⚠️  {len(overlap)} 个项目同时在两个目录——数据重复可能是根因")

if __name__ == "__main__":
    main()
