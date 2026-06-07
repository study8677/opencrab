#!/usr/bin/env python3
"""Peek at current docs/index.html to understand what placeholders/numbers exist."""
import os

html_path = os.path.join('docs', 'index.html')
if os.path.exists(html_path):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    print(f"=== docs/index.html ({len(content)} chars) ===")
    print(content[:3000])
else:
    print(f"{html_path} not found")
