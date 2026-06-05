#!/usr/bin/env python3
"""检查四维评测模块是否存在"""
from pathlib import Path

REPO_ROOT = Path(__file__).parent

modules = ["arena.py", "boundaryeval.py", "regression.py", "canary.py"]
for m in modules:
    p = REPO_ROOT / m
    print(f"{m}: {'✅' if p.exists() else '❌'} (exists={p.exists()})")
    if p.exists():
        # 检查关键类
        content = p.read_text()
        has_class = "class " in content
        print(f"   has class: {has_class}")
        if has_class:
            import re
            classes = re.findall(r'class (\w+)', content)
            print(f"   classes: {classes}")
