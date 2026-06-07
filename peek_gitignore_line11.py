#!/usr/bin/env python3
"""Peek .gitignore line 11 specifically for state/ directory handling."""
import subprocess

def main():
    print("=== .gitignore line 11 check ===")
    
    # Show the file
    try:
        with open(".gitignore") as f:
            lines = f.readlines()
        print(f"Total lines: {len(lines)}")
        print("\nFull .gitignore:")
        for i, line in enumerate(lines, 1):
            print(f"  {i:2}: {line.rstrip()}")
    except FileNotFoundError:
        print(".gitignore not found")
        return
    
    print("\n=== Line 11 specifically ===")
    if len(lines) >= 11:
        print(f"Line 11: {lines[10].rstrip()}")
    
    print("\n=== git check-ignore -v for state/projects/项目账.md ===")
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-v", "state/projects/项目账.md"],
            capture_output=True, text=True
        )
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        print(f"returncode: {result.returncode}")
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n=== git ls-files state/ ===")
    try:
        result = subprocess.run(
            ["git", "ls-files", "state/"],
            capture_output=True, text=True
        )
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        print(f"returncode: {result.returncode}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
