#!/usr/bin/env python3
"""快速查看 docs/index.html 内容"""
import os

path = "docs/index.html"
if os.path.exists(path):
    with open(path) as f:
        content = f.read()
    print(f"=== docs/index.html ({len(content)} bytes) ===")
    print(content[:3000])
else:
    print(f"{path} 不存在")
