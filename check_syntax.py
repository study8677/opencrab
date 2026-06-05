#!/usr/bin/env python3
"""检查所有修改文件的语法"""
import py_compile
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

files = [
    "readpack.py",
    "intentpatch.py", 
    "patchfitroom.py",
    "arena.py",
    "boundaryeval.py",
    "regression.py",
    "canary.py",
    "run_fitness_baseline.py",
    "fitness.json",
]

errors = []
for f in files:
    path = REPO_ROOT / f
    if not path.exists():
        print(f"⚠️ {f}: 不存在")
        continue
    try:
        if f.endswith('.py'):
            py_compile.compile(str(path), doraise=True)
        print(f"✅ {f}: 语法正确")
    except py_compile.PyCompileError as e:
        errors.append(f"❌ {f}: {e}")
        print(f"❌ {f}: 语法错误")

if errors:
    print("\n语法错误汇总:")
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print("\n✅ 所有文件语法检查通过")
