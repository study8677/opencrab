#!/usr/bin/env python3
"""临时脚本：快速扫一遍 canary_75 执行链的关键模块"""

import os, importlib, inspect

files = [
    "go_canary_75.py",
    "execute_canary_75.py",
    "do_canary_75_final.py",
    "astlocator.py",
    "readpack.py",
    "intentpatch.py",
    "patchfitroom.py",
    "canary_75.py",
]

for fname in files:
    if not os.path.exists(fname):
        print(f"=== {fname}: NOT FOUND ===\n")
        continue
    try:
        mod = importlib.import_module(fname.replace(".py", ""))
        members = [m for m in dir(mod) if not m.startswith("_")]
        print(f"=== {fname}: {members[:10]} ===")
        # 打印 docstring
        if mod.__doc__:
            print(f"  doc: {mod.__doc__[:100]}")
        # 打印 main/entry 函数签名
        for name in ["main", "run", "execute", "go", "weld", "do"]:
            if hasattr(mod, name):
                fn = getattr(mod, name)
                if callable(fn):
                    sig = inspect.signature(fn)
                    print(f"  {name}{sig}")
        print()
    except Exception as e:
        print(f"=== {fname}: ERROR {e} ===\n")
