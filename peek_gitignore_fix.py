#!/usr/bin/env python3
"""查看 .gitignore 当前内容"""
from pathlib import Path

gitignore = Path(".gitignore")
if gitignore.exists():
    content = gitignore.read_text()
    print("=== .gitignore 内容 ===")
    print(content)
    print("=== 行号 ===")
    for i, line in enumerate(content.splitlines(), 1):
        print(f"{i:3}: {line}")
else:
    print(".gitignore 不存在！")
