#!/usr/bin/env python3
"""核真 .gitignore 第 11 行是否真的忽略 state/"""
import pathlib

def main():
    gitignore = pathlib.Path(".gitignore")
    if not gitignore.exists():
        print("❌ .gitignore 不存在")
        return
    
    lines = gitignore.read_text().splitlines()
    print(f"=== .gitignore 共 {len(lines)} 行 ===")
    for i, line in enumerate(lines, 1):
        marker = " ◄◄◄" if i == 11 else ""
        print(f"  {i:2}: {line}{marker}")
    
    if len(lines) >= 11:
        line11 = lines[10].strip()  # 0-indexed
        print(f"\n第 11 行内容: {repr(line11)}")
        if line11 == "state/" or line11 == "state":
            print("✅ .gitignore 第 11 行确实忽略 state/")
        else:
            print(f"❌ 第 11 行不是 'state/'，实际是: {repr(line11)}")
    else:
        print(f"\n❌ .gitignore 只有 {len(lines)} 行，不够 11 行")

if __name__ == "__main__":
    main()
