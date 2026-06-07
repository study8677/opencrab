#!/usr/bin/env python3
"""Check projects.json for heartbeat weld entries."""
import json
from pathlib import Path

STATE_DIR = Path("state")
PROJECTS_FILE = STATE_DIR / "projects.json"

def main():
    print("=== PROJECTS HEARTBEAT WELD ENTRIES ===\n")
    
    if not PROJECTS_FILE.exists():
        print("No projects.json found")
        return
    
    with open(PROJECTS_FILE) as f:
        projects = json.load(f)
    
    print(f"Total projects: {len(projects)}")
    
    heartbeat_projects = []
    for p in projects:
        name = p.get("name", "").lower()
        if "heartbeat" in name or "weld" in name:
            heartbeat_projects.append(p)
    
    if heartbeat_projects:
        for p in heartbeat_projects:
            print(f"\n{name}: {p.get('status')}")
            print(json.dumps(p, indent=2))
    else:
        print("\nNo heartbeat/weld projects found")
    
    # Show project structure
    print("\n--- Sample project structure ---")
    if projects:
        print(json.dumps(projects[0], indent=2)[:500])

if __name__ == "__main__":
    main()
