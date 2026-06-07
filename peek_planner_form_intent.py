#!/usr/bin/env python3
"""核真 planner.form_intent 能否读到进行中项目"""
import sys
import pathlib

# 加载 planner
sys.path.insert(0, str(pathlib.Path(".").resolve()))
import importlib.util

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.ModuleType(name)
    spec.loader.exec_module(mod)
    return mod

def main():
    # 1. 加载 planner
    planner_path = pathlib.Path("planner.py")
    if not planner_path.exists():
        print("❌ planner.py 不存在")
        return
    
    try:
        planner_mod = load_module("planner", planner_path)
    except Exception as e:
        print(f"❌ planner.py 加载失败: {e}")
        return
    
    print(f"=== planner.py 已加载 ===")
    print(f"  可用: form_intent" if hasattr(planner_mod, "form_intent") else "  ❌ 没有 form_intent")
    
    # 2. 检查 form_intent 签名和实现
    if hasattr(planner_mod, "form_intent"):
        import inspect
        fi = getattr(planner_mod, "form_intent")
        print(f"\n=== form_intent 信息 ===")
        print(f"  类型: {type(fi)}")
        print(f"  签名: {inspect.signature(fi)}")
        src = inspect.getsource(fi)
        print(f"  源码行数: {src.count(chr(10)) + 1}")
        
        # 3. 检查是否涉及 projects 目录
        if "projects" in src:
            print("\n  ✅ 源码中涉及 'projects'")
            for line in src.split("\n"):
                if "projects" in line:
                    print(f"    {line.strip()}")
        else:
            print("\n  ❌ 源码中不涉及 'projects'")
        
        if "state" in src:
            print("\n  ⚠️  源码中涉及 'state'")
            for line in src.split("\n"):
                if "state" in line:
                    print(f"    {line.strip()}")
        
        # 4. 检查 projects 目录和 state 目录
        projects_dir = pathlib.Path("projects")
        state_dir = pathlib.Path("state")
        
        has_projects = projects_dir.exists()
        has_state = state_dir.exists()
        
        print(f"\n=== 目录存在性 ===")
        print(f"  projects/: {'✅ 存在' if has_projects else '❌ 不存在'}")
        print(f"  state/: {'✅ 存在' if has_state else '❌ 不存在'}")
        
        if has_projects:
            items = list(projects_dir.iterdir())
            print(f"  projects/ 下有 {len(items)} 个项目")
            for it in items[:5]:
                print(f"    {it.name}")
        
        # 5. 尝试实际调用（dry run）
        print(f"\n=== 根因诊断 ===")
        if not has_projects and not has_state:
            print("⚠️  projects/ 和 state/ 都不存在——form_intent 可能读不到任何项目")
        elif has_projects and "projects" not in src:
            print("⚠️  projects/ 存在，但 form_intent 源码不看它——可能是根因")
        elif has_state and "state" in src and not has_projects:
            print("⚠️  form_intent 看 state/ 但不看板 projects/——可能读不到进行中项目")
        else:
            print("✅ form_intent 和目录结构一致")
    else:
        print("❌ planner.py 中没有 form_intent 函数")
        print("\n=== 可能的替代方案 ===")
        for name in dir(planner_mod):
            if not name.startswith("_"):
                obj = getattr(planner_mod, name)
                if callable(obj):
                    print(f"  {name}")

if __name__ == "__main__":
    main()
