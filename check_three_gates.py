#!/usr/bin/env python3
"""检查三闸文件结构"""
from pathlib import Path

REPO_ROOT = Path(__file__).parent

for fname in ["readpack.py", "intentpatch.py", "patchfitroom.py"]:
    p = REPO_ROOT / fname
    print(f"\n{'='*60}")
    print(f"📄 {fname}")
    print(f"   行数: {len(p.read_text().splitlines()) if p.exists() else 'N/A'}")
    if p.exists():
        lines = p.read_text().splitlines()
        for i, line in enumerate(lines[:50], 1):
            print(f"   {i:3}: {line[:100]}")
        if len(lines) > 50:
            print(f"   ... ({len(lines)-50} more lines)")
