#!/usr/bin/env python3
"""临时脚本：读 astlocator / readpack / intentpatch / patchfitroom 的关键函数"""
import os, importlib, inspect

for fname in ["astlocator", "readpack", "intentpatch", "patchfitroom"]:
    if not os.path.exists(f"{fname}.py"):
        print(f"=== {fname}.py NOT FOUND ===\n")
        continue
    mod = importlib.import_module(fname)
    print(f"=== {fname}.py ===")
    for name, obj in sorted(vars(mod).items()):
        if name.startswith("_"):
            continue
        if callable(obj) and not isinstance(obj, type):
            try:
                sig = str(inspect.signature(obj))
            except:
                sig = "(?)"
            doc = (obj.__doc__ or "")[:60].strip()
            print(f"  {name}{sig}  # {doc}")
    print()
