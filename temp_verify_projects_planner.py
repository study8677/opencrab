#!/usr/bin/env python3
"""临时验证 planner 能否读到 projects/"""
import sys
import pathlib
import importlib.util

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.ModuleType(name)
    spec.loader.exec_module(mod)
    return mod

def main():
    print("=== 验证 planner.form_intent 能否读 projects/ ===\n")
    
    planner_path = pathlib.Path("planner.py")
    if not planner_path.exists():
        print("❌ planner.py 不存在")
        return
    
    try:
        planner_mod = load_module("planner", planner_path)
    except Exception as e:
        print(f"❌ 加载失败: {e}")
        return
    
    projects_dir = pathlib.Path("projects")
    state_dir = pathlib.Path("state")
    
    print(f"projects/: {'存在' if projects_dir.exists() else '不存在'}")
    print(f"state/: {'存在' if state_dir.exists() else '不存在'}")
    
    # 检查 form_intent
    if hasattr(planner_mod, "form_intent"):
        fi = getattr(planner_mod, "form_intent")
        import inspect
        src = inspect.getsource(fi)
        
        print(f"\nform_intent 源码包含:")
        for keyword in ["projects", "state", "Path", "read", "open"]:
            if keyword in src:
                count = src.count(keyword)
                print(f"  '{keyword}': {count} 次")
        
        # 查找实际路径引用
        import re
        path_refs = re.findall(r'["\']([^"\']*(?:projects|state)[^"\']*)["\']', src)
        if path_refs:
            print(f"\n实际路径引用:")
            for pr in path_refs[:5]:
                print(f"  {pr}")
        
        # 核真结论
        if "projects" not in src and "state" not in src:
            print("\n❌ form_intent 源码中不读任何项目目录")
        elif "projects" not in src and "state" in src:
            print("\n⚠️  form_intent 只读 state/，不读 projects/")
        else:
            print("\n✅ form_intent 源码中有项目目录引用")
    else:
        print("❌ 没有 form_intent 方法")

if __name__ == "__main__":
    main()
