#!/usr/bin/env python3
"""核真 planner.py 的核心功能——能否看到进行中项目"""
import sys
import pathlib
import importlib.util

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.ModuleType(name)
    spec.loader.exec_module(mod)
    return mod

def main():
    planner_path = pathlib.Path("planner.py")
    if not planner_path.exists():
        print("❌ planner.py 不存在")
        return
    
    try:
        planner_mod = load_module("planner", planner_path)
    except Exception as e:
        print(f"❌ 加载失败: {e}")
        return
    
    print(f"=== planner.py 核心函数 ===")
    funcs = [(n, getattr(planner_mod, n)) for n in dir(planner_mod) 
             if not n.startswith("_") and callable(getattr(planner_mod, n))]
    
    for name, func in funcs:
        import inspect
        try:
            sig = inspect.signature(func)
            print(f"  {name}{sig}")
        except:
            print(f"  {name}(...)")
    
    # 聚焦 form_intent
    if hasattr(planner_mod, "form_intent"):
        fi = getattr(planner_mod, "form_intent")
        import inspect
        src = inspect.getsource(fi)
        
        print(f"\n=== form_intent 源码 ({src.count(chr(10))+1} 行) ===")
        
        # 找关键引用
        keywords = ["projects", "state", "ledger", "read", "open", "Path"]
        for kw in keywords:
            if kw in src:
                lines_with_kw = [l.strip() for l in src.split("\n") if kw in l]
                print(f"\n  包含 '{kw}' 的行 ({len(lines_with_kw)} 处):")
                for l in lines_with_kw[:3]:
                    print(f"    {l}")
    
    # 检查 projects 目录
    print(f"\n=== projects/ 目录真实状态 ===")
    projects_dir = pathlib.Path("projects")
    state_dir = pathlib.Path("state")
    
    print(f"  projects/: {'✅' if projects_dir.exists() else '❌'}")
    print(f"  state/: {'✅' if state_dir.exists() else '❌'}")
    
    if projects_dir.exists():
        all_files = []
        for p in projects_dir.rglob("*"):
            if p.is_file():
                all_files.append(str(p))
        print(f"  projects/ 下共 {len(all_files)} 个文件")
        for f in all_files[:5]:
            print(f"    {f}")
    
    # 核真结论
    print(f"\n=== 核真结论 ===")
    if not projects_dir.exists():
        print("❌ projects/ 不存在——planner 读不到进行中项目（如果它只读 projects/）")
    else:
        has_projects = len(list(projects_dir.iterdir())) > 0
        if not has_projects:
            print("⚠️  projects/ 为空——没有进行中项目")
        else:
            print("✅ projects/ 有内容")

if __name__ == "__main__":
    main()
