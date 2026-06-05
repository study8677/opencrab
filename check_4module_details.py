#!/usr/bin/env python3
"""检查四个评测模块的详细结构"""
import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent

for fname in ["arena.py", "boundaryeval.py", "regression.py", "canary.py"]:
    p = REPO_ROOT / fname
    print(f"\n{'='*60}")
    print(f"📄 {fname}")
    if not p.exists():
        print("   ❌ 不存在")
        continue
    
    content = p.read_text()
    tree = ast.parse(content)
    
    # 找类
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    print(f"   类: {classes}")
    
    # 找主要函数
    funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')]
    print(f"   函数: {funcs[:10]}")
    
    # 显示前30行
    print("   前30行:")
    for i, line in enumerate(content.splitlines()[:30], 1):
        print(f"   {i:3}: {line[:90]}")
