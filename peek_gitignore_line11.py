#!/usr/bin/env python3
"""Quick peek at .gitignore line 11."""
with open(".gitignore", "r", encoding="utf-8") as f:
    lines = f.readlines()
    for i, line in enumerate(lines[:15], 1):
        marker = " <<<< LINE 11" if i == 11 else ""
        print(f"Line {i:2d}: {line.rstrip()}{marker}")
