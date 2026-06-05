#!/usr/bin/env python3
"""检查四个评测模块的接口是否匹配 run_fitness_baseline.py 的调用"""
from pathlib import Path
import re

REPO_ROOT = Path(__file__).parent

# run_fitness_baseline.py 期望的接口：
expected = {
    "arena.py": ["class Arena", "def run", "result.get('passed'", "result.get('failed'", "result.get('total'"],
    "boundaryeval.py": ["class BoundaryEval", "def run", "result.get('passed'", "result.get('failed'", "result.get('total'"],
    "regression.py": ["class RegressionSuite", "def run", "result.get('passed'", "result.get('failed'", "result.get('total'"],
    "canary.py": ["class Canary", "def run", "result.get('passed'", "result.get('failed'", "result.get('total'"],
}

for fname, required in expected.items():
    p = REPO_ROOT / fname
    print(f"\n{'='*50}")
    print(f"📄 {fname}")
    
    if not p.exists():
        print("   ❌ 不存在 - 需要创建存根或修复")
        continue
    
    content = p.read_text()
    missing = []
    for req in required:
        if req not in content:
            missing.append(req)
    
    if missing:
        print(f"   ⚠️ 缺少: {missing}")
    else:
        print("   ✅ 接口完整")
    
    # 找类和方法
    classes = re.findall(r'class (\w+)', content)
    funcs = re.findall(r'def (\w+)\(', content)
    print(f"   类: {classes}")
    print(f"   方法: {funcs}")
