#!/usr/bin/env python3
"""临时验证 .gitignore 第 11 行的准确性"""
import pathlib

def main():
    gi = pathlib.Path(".gitignore")
    if not gi.exists():
        print("❌ .gitignore 不存在")
        return
    
    lines = gi.read_text().splitlines()
    
    print(f"=== .gitignore 第 11 行核真 ===")
    print(f"总共 {len(lines)} 行\n")
    
    for i in range(min(15, len(lines))):
        marker = " ◄◄◄ 行 11" if i == 10 else ""
        print(f"  {i+1:2}: {lines[i]}{marker}")
    
    if len(lines) >= 11:
        line11 = lines[10].strip()
        print(f"\n行 11 内容: {repr(line11)}")
        if line11 == "state/":
            print("✅ 第 11 行 = 'state/' —— .gitignore 确实忽略 state/")
        elif line11 == "state":
            print("✅ 第 11 行 = 'state' —— .gitignore 忽略 state（无斜线）")
        else:
            print(f"❌ 第 11 行不是 state，真实内容: {repr(line11)}")
    else:
        print(f"\n❌ .gitignore 只有 {len(lines)} 行，不够 11 行")

if __name__ == "__main__":
    main()
