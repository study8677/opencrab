#!/usr/bin/env python3
"""Quick peek before self-evolve."""
import os

# Check planner.py
print("=== planner.py (first 80 lines) ===")
try:
    with open("planner.py") as f:
        lines = f.readlines()
        for i, line in enumerate(lines[:80], 1):
            print(f"{i:3d}: {line}", end="")
except Exception as e:
    print(f"Error: {e}")

print("\n=== .gitignore ===")
try:
    with open(".gitignore") as f:
        print(f.read())
except Exception as e:
    print(f"Error: {e}")

print("\n=== state/projects/ exists? ===")
state_projects = "state/projects"
if os.path.exists(state_projects):
    print(f"YES: {state_projects}")
    try:
        files = os.listdir(state_projects)
        print(f"  Files: {files[:10]}...")
    except:
        pass
else:
    print(f"NO: {state_projects} does not exist")

print("\n=== state/ exists? ===")
if os.path.exists("state"):
    print("YES: state/")
    try:
        print(f"  Contents: {os.listdir('state')}")
    except:
        pass
else:
    print("NO: state/ does not exist")
