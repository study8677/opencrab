#!/usr/bin/env python3
"""检查 crab.py 结构"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parent

with open(REPO_ROOT / "crab.py") as f:
    content = f.read()

# 解析 AST 获取函数和类
tree = ast.parse(content)
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        print(f"{type(node).__name__}: {node.name}")
