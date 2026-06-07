#!/usr/bin/env python3
"""临时脚本：读取 canary_75_real_weld.py 源码"""
from pathlib import Path

p = Path("canary_75_real_weld.py")
if p.exists():
    content = p.read_text()
    print(f"=== canary_75_real_weld.py ({len(content)} chars) ===")
    print(content)
else:
    print("❌ canary_75_real_weld.py 不存在")
