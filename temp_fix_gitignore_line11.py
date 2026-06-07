#!/usr/bin/env python3
"""Fix .gitignore line 11 to allow state/projects/ to be tracked by git."""
from pathlib import Path

gitignore = Path(".gitignore")
if not gitignore.exists():
    print(".gitignore not found")
    exit(1)

lines = gitignore.read_text().splitlines()
print(f"Current .gitignore line 11: {repr(lines[10]) if len(lines) >= 11 else 'N/A'}")

# If line 11 is "# state/projects/" (commented out), uncomment it
if len(lines) >= 11 and lines[10].strip() == "# state/projects/":
    lines[10] = "state/projects/"
    gitignore.write_text("\n".join(lines) + "\n")
    print("Fixed: uncommented line 11 -> state/projects/")
elif len(lines) >= 11 and lines[10].strip() == "state/projects/":
    print("Line 11 already is: state/projects/ (no change needed)")
else:
    print(f"Line 11 is: {repr(lines[10]) if len(lines) >= 11 else 'N/A'}")
    print("Need to check if this needs to be changed to allow state/projects/")
