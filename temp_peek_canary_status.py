"""
快速检查 canary.py 当前源码状态
"""
from pathlib import Path

canary = Path("canary.py")
if canary.exists():
    src = canary.read_text()
    print(f"=== canary.py 当前状态 ===")
    print(f"总行数: {len(src.splitlines())}")
    
    # 找关键方法
    if "_check_recent_activity" in src:
        # 提取该方法
        lines = src.splitlines()
        in_method = False
        method_lines = []
        for i, line in enumerate(lines):
            if "def _check_recent_activity" in line:
                in_method = True
            if in_method:
                method_lines.append(f"{i+1}: {line}")
                if line.strip() and not line.startswith(" ") and not line.startswith("\t"):
                    if len(method_lines) > 3:
                        break
                if line.strip() and not line[0].isspace() and i > 0:
                    if "def " in line:
                        break
        
        print("\n_check_recent_activity 方法:")
        for m in method_lines[:20]:
            print(m)
        
        # 检查 bug
        bug1 = ">= 0  # 总是返回 True" in src
        bug2 = "> 0" in src and ">= 0" in src
        print(f"\n关键检查:")
        print(f"  '>= 0  # 总是返回 True' 存在: {bug1}")
        print(f"  '> 0' 存在: {'> 0' in src}")
        print(f"  '>= 0' 存在: {'>= 0' in src}")
    else:
        print("canary.py 中没有 _check_recent_activity 方法")
else:
    print("canary.py 不存在!")
    
    # 检查 fitness.json
fitness = Path("fitness.json")
if fitness.exists():
    import json
    data = json.loads(fitness.read_text())
    print(f"\n=== fitness.json 摘要 ===")
    print(f"weld_count: {data.get('weld_count', 0)}")
    print(f"total_delta: {data.get('total_delta', 0.0)}")
    print(f"runs 数量: {len(data.get('runs', []))}")
else:
    print("\nfitness.json 不存在")
