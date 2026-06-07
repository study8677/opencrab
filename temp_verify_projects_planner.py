#!/usr/bin/env python3
"""最小验证：项目账接通状态 + planner.form_intent 真状态"""

import subprocess
import sys
sys.path.insert(0, '.')

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def main():
    print("=" * 60)
    print("【验证1】git ls-files state/projects/")
    print("=" * 60)
    files, err, rc = run_cmd("git ls-files state/projects/")
    if rc == 0:
        if files:
            print(f"✓ 项目文件存在 ({len(files.splitlines())} 个):")
            for f in files.splitlines():
                print(f"  - {f}")
        else:
            print("○ 项目目录为空")
    else:
        print(f"✗ git ls-files 失败: {err}")
    
    print()
    print("=" * 60)
    print("【验证2】planner.form_intent() 真状态")
    print("=" * 60)
    
    try:
        from planner import Planner
        p = Planner()
        intent = p.form_intent()
        print(f"✓ planner.form_intent() 返回: {type(intent)}")
        if isinstance(intent, dict):
            for k, v in intent.items():
                print(f"  {k}: {v}")
        else:
            print(f"  内容: {intent}")
    except Exception as e:
        print(f"✗ planner.form_intent() 失败: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 60)
    print("【结论】")
    print("=" * 60)
    
    # 检查 state/projects 是否有实质内容
    has_projects = bool(files.strip())
    
    # 检查 planner 状态
    planner_ok = False
    try:
        from planner import Planner
        p = Planner()
        intent = p.form_intent()
        planner_ok = intent is not None
    except:
        pass
    
    if has_projects and planner_ok:
        print("✓ 项目账已接通，可以标记完成，转身开啃「真适应度」")
    elif has_projects:
        print("△ 项目文件存在但 planner 状态待查")
    elif planner_ok:
        print("△ planner 可用但 projects 目录为空")
    else:
        print("○ 两者都需要进一步处理")

if __name__ == "__main__":
    main()
