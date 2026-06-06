"""读取 crab.py 中的 apply_patch 方法"""
from pathlib import Path

path = Path("crab.py")
if path.exists():
    source = path.read_text()
    # 找 apply_patch
    if "apply_patch" in source:
        idx = source.find("def apply_patch")
        print("=== apply_patch 片段 ===")
        print(source[idx:idx+500])
    else:
        print("crab.py 没有 apply_patch")
else:
    print("crab.py 不存在")
