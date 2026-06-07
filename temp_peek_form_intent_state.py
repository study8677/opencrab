#!/usr/bin/env python3
"""Check form_intent state for continuation."""
import json
from pathlib import Path

STATE_DIR = Path("state")
PLANNER_FILE = STATE_DIR / "planner.json"

def main():
    print("=== FORM_INTENT STATE ===\n")
    
    if not PLANNER_FILE.exists():
        print("No planner.json found")
        return
    
    with open(PLANNER_FILE) as f:
        planner = json.load(f)
    
    print("Planner top-level keys:", list(planner.keys()))
    
    if "form_intent" in planner:
        fi = planner["form_intent"]
        print(f"\nform_intent entries: {len(fi) if isinstance(fi, (list, dict)) else 'not list/dict'}")
        print(json.dumps(fi, indent=2)[:1000])
    else:
        print("\nNo 'form_intent' key in planner")
    
    # Check for any incomplete items
    for key in ["pending", "incomplete", "queue"]:
        if key in planner:
            print(f"\n{key}: {planner[key]}")

if __name__ == "__main__":
    main()
