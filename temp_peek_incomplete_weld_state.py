#!/usr/bin/env python3
"""Quick peek at incomplete heartbeat weld state."""
import json
from pathlib import Path

STATE_DIR = Path("state")
TASKS_FILE = STATE_DIR / "heartbeat_tasks.json"
PROJECTS_FILE = STATE_DIR / "projects.json"
PLANNER_FILE = STATE_DIR / "planner.json"

def main():
    print("=== INCOMPLETE HEARTBEAT WELD STATE ===\n")
    
    # Check tasks
    if TASKS_FILE.exists():
        with open(TASKS_FILE) as f:
            tasks = json.load(f)
        for t in tasks:
            if "heartbeat_weld" in t.get("name", ""):
                print(f"Task: {t.get('name')}")
                print(f"  Status: {t.get('status')}")
                print(f"  Steps: {t.get('steps', [])}")
                print()
    else:
        print("No heartbeat_tasks.json")
    
    # Check projects
    if PROJECTS_FILE.exists():
        with open(PROJECTS_FILE) as f:
            projects = json.load(f)
        for p in projects:
            if "heartbeat_weld" in p.get("name", "").lower():
                print(f"Project: {p.get('name')}")
                print(f"  Status: {p.get('status')}")
                print(f"  Ledger: {p.get('ledger', {})}")
                print()
    else:
        print("No projects.json")
    
    # Check planner form_intent
    if PLANNER_FILE.exists():
        with open(PLANNER_FILE) as f:
            planner = json.load(f)
        print("Planner keys:", list(planner.keys())[:10])
        if "form_intent" in planner:
            print("form_intent:", planner["form_intent"])
    else:
        print("No planner.json")
    
    # Check git status
    import subprocess
    result = subprocess.run(["git", "status", "--short"], capture_output=True, text=True)
    print("\nGit status:")
    print(result.stdout[:500] if result.stdout else "(clean)")

if __name__ == "__main__":
    main()
