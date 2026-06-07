#!/usr/bin/env python3
"""Check if we can complete the incomplete heartbeat weld task."""
import json
from pathlib import Path
from datetime import datetime

STATE_DIR = Path("state")
TASKS_FILE = STATE_DIR / "heartbeat_tasks.json"
PROJECTS_FILE = STATE_DIR / "projects.json"
PLANNER_FILE = STATE_DIR / "planner.json"

def main():
    print("=== INCOMPLETE HEARTBEAT WELD READINESS ===\n")
    
    task_name = "test_incomplete_heartbeat_weld"
    project_name = "heartbeat_weld"
    
    # 1. Check task status
    print("--- Task Status ---")
    if TASKS_FILE.exists():
        with open(TASKS_FILE) as f:
            tasks = json.load(f)
        found = False
        for t in tasks:
            if t.get("name") == task_name:
                print(f"Found task: {task_name}")
                print(f"  Status: {t.get('status')}")
                print(f"  Steps: {t.get('steps', [])}")
                found = True
        if not found:
            print(f"Task '{task_name}' not in tasks")
    else:
        print("No tasks file")
    
    # 2. Check if there's a project entry to update
    print("\n--- Project Entry ---")
    if PROJECTS_FILE.exists():
        with open(PROJECTS_FILE) as f:
            projects = json.load(f)
        
        # Look for heartbeat_weld project
        hw_project = None
        for p in projects:
            if "heartbeat_weld" in p.get("name", "").lower():
                hw_project = p
                break
        
        if hw_project:
            print(f"Found project: {hw_project.get('name')}")
            print(f"  Status: {hw_project.get('status')}")
            print(f"  Ledger: {hw_project.get('ledger', {})}")
        else:
            print(f"No project '{project_name}' found")
            print("  Need to add it to projects.json")
    else:
        print("No projects file")
    
    # 3. Check planner form_intent
    print("\n--- Planner form_intent ---")
    if PLANNER_FILE.exists():
        with open(PLANNER_FILE) as f:
            planner = json.load(f)
        
        if "form_intent" in planner:
            fi = planner["form_intent"]
            print(f"form_intent type: {type(fi).__name__}")
            if isinstance(fi, list):
                print(f"  entries: {len(fi)}")
                # Check for incomplete heartbeat weld entries
                incomplete = [e for e in fi if "heartbeat_weld" in str(e).lower()]
                if incomplete:
                    print(f"  incomplete entries: {incomplete}")
        else:
            print("No form_intent key")
    else:
        print("No planner file")
    
    print("\n--- Readiness Assessment ---")
    print("To complete this weld, we need to:")
    print("1. Update task status to DONE in heartbeat_tasks.json")
    print("2. Create/update project entry with status=DONE")
    print("3. Ensure form_intent has no blocking entries")
    print("4. Commit the changes")

if __name__ == "__main__":
    main()
