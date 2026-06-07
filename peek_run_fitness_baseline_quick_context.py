"""快速检查 run_fitness_baseline.py 的前置条件状态"""
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def main():
    print("=" * 60)
    print("run_fitness_baseline.py 前置条件检查")
    print("=" * 60)
    
    # 1. 检查 fitness.json
    fitness_path = REPO_ROOT / "fitness.json"
    if fitness_path.exists():
        with open(fitness_path) as f:
            fitness = json.load(f)
        print(f"\n[fitness.json 存在]")
        if "baseline" in fitness:
            print(f"  当前 baseline pass_rate: {fitness['baseline'].get('pass_rate', 'N/A')}")
            print(f"  当前 baseline canary_pass_rate: {fitness['baseline'].get('canary_pass_rate', 'N/A')}")
            if "dimensions" in fitness:
                for dim, d in fitness["dimensions"].items():
                    print(f"  - {dim}: {d.get('passed',0)}/{d.get('total',0)}")
        else:
            print(f"  但没有 baseline 字段，需要运行 run_fitness_baseline.py")
    else:
        print(f"\n[fitness.json 不存在，需要运行 run_fitness_baseline.py]")
    
    # 2. 检查 docs/index.html
    docs_path = REPO_ROOT / "docs" / "index.html"
    if docs_path.exists():
        with open(docs_path) as f:
            content = f.read()
        print(f"\n[docs/index.html 存在]")
        # 提取模块数
        if "modules" in content.lower() or "module" in content.lower():
            import re
            # 找类似 "26 modules" 或 "220+ modules"
            matches = re.findall(r'(\d+[\+\]?)\s*(?:modules|Module)', content, re.I)
            if matches:
                print(f"  模块数: {matches[:3]}")
        # 找 commit 数
        commits = re.findall(r'(\d+)\s*(?:commits|commit)', content, re.I)
        if commits:
            print(f"  Commit 数: {commits[:3]}")
    else:
        print(f"\n[docs/index.html 不存在]")
    
    # 3. 检查四个核心模块是否存在
    core_modules = ["arena", "boundaryeval", "regression", "canary"]
    print(f"\n[核心模块检查]")
    for mod in core_modules:
        mod_path = REPO_ROOT / f"{mod}.py"
        if mod_path.exists():
            size = os.path.getsize(mod_path)
            print(f"  ✅ {mod}.py ({size} bytes)")
        else:
            print(f"  ❌ {mod}.py 不存在")
    
    # 4. 检查 evidence 目录
    evidence_dir = REPO_ROOT / "evidence" / "baseline"
    print(f"\n[evidence/baseline/ 目录]")
    if evidence_dir.exists():
        files = list(evidence_dir.glob("*.json"))
        print(f"  存在 {len(files)} 个基线文件")
    else:
        print(f"  目录不存在，需要创建")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        print(f"  已创建目录")
    
    print("\n" + "=" * 60)
    print("结论：准备运行 run_fitness_baseline.py")
    print("=" * 60)

if __name__ == "__main__":
    main()
