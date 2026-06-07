#!/usr/bin/env python3
"""Quick check of fitness.json - show heartbeat-related entries."""
import json
from pathlib import Path

def check():
    f = Path("state/fitness.json")
    if not f.exists():
        print("state/fitness.json NOT FOUND")
        return
    
    with open(f) as fp:
        data = json.load(fp)
    
    print("=== FITNESS.JSON ===")
    print(f"Total entries: {len(data)}")
    
    # Show all entries, sorted
    for k in sorted(data.keys()):
        v = data[k]
        marker = " "
        if isinstance(v, float):
            if v >= 0.9:
                marker = "✓"
            elif v >= 0.5:
                marker = "~"
            else:
                marker = "✗"
        print(f"  [{marker}] {k}: {v}")
    
    # Summary
    completed = sum(1 for v in data.values() if isinstance(v, (int, float)) and v >= 0.9)
    print(f"\nCompleted: {completed}/{len(data)}")

if __name__ == "__main__":
    check()
