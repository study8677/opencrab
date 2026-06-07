#!/usr/bin/env python3
"""Peek .gitignore line 11 to check projects/ status."""
import os

def main():
    gitignore_path = ".gitignore"
    if not os.path.exists(gitignore_path):
        print("NO .gitignore found")
        return
    
    with open(gitignore_path) as f:
        lines = f.readlines()
    
    print(f".gitignore has {len(lines)} lines")
    if len(lines) >= 11:
        print(f"Line 11: {lines[10].rstrip()!r}")
    else:
        print("Less than 11 lines")
    
    print("\n--- First 15 lines ---")
    for i, line in enumerate(lines[:15], 1):
        print(f"  {i}: {line.rstrip()!r}")

if __name__ == "__main__":
    main()
