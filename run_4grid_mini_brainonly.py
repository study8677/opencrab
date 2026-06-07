"""
4格权衡 → 脑补阶段: 补全缺失模块
arena / boundaryeval / regression / canary 中缺失的最小单元
"""
import subprocess
import json
import sys
from pathlib import Path

def check_module(name, path):
    p = Path(path)
    exists = p.exists()
    print(f"  {name}: {'✅' if exists else '❌'} {path}")
    return exists

def main():
    print("=" * 60)
    print("4格权衡 → 脑补阶段: 检查缺失模块")
    print("=" * 60)
    
    # canary 格子需要的最小模块
    print("\n【canary 格子 最小依赖】")
    deps = {
        "canary.py": check_module("canary.py", "canary.py"),
        "canary_75_real_weld.py": check_module("canary_75_real_weld.py", "canary_75_real_weld.py"),
        "autopsy.py": check_module("autopsy.py", "autopsy.py"),
        "patchfitroom.py": check_module("patchfitroom.py", "patchfitroom.py"),
        "evalbench.py": check_module("evalbench.py", "evalbench.py"),
        "fitness.json": Path("fitness.json").exists(),
    }
    
    missing = [k for k, v in deps.items() if not v]
    
    if not missing:
        print("\n✅ 所有依赖完整，直接跑全链")
        return 0
    
    print(f"\n⚠️  缺失模块: {missing}")
    print("尝试自动生成最小可用模块...")
    
    # 对于缺失的模块，生成最小stub
    if "fitness.json" not in missing and not Path("fitness.json").exists():
        Path("fitness.json").write_text(json.dumps({
            "arena": 0.5,
            "boundaryeval": 0.5,
            "regression": 0.5,
            "canary": 0.5
        }, indent=2))
        print("  ✅ 已生成 fitness.json 基线")
    
    # 尝试运行
    print("\n尝试运行 canary_75_real_weld.py...")
    result = subprocess.run(
        "python canary_75_real_weld.py",
        shell=True, capture_output=True, text=True
    )
    print(f"  stdout: {result.stdout[:300]}")
    print(f"  stderr: {result.stderr[:300]}")
    
    return 0 if result.returncode == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
