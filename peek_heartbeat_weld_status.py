#!/usr/bin/env python3
"""Peek at the heartbeat weld status - what's IN_PROGRESS, what's blocking."""
import json
from pathlib import Path

def peek():
    # Check heartbeat tasks ledger
    tasks_file = Path("state/heartbeat_tasks.json")
    if tasks_file.exists():
        with open(tasks_file) as f:
            tasks = json.load(f)
        print("=== HEARTBEAT TASKS ===")
        for t in tasks:
            status = t.get("status", "unknown")
            name = t.get("name", t.get("task", "?"))
            print(f"  [{status}] {name}")
    
    # Check fitness.json
    fitness_file = Path("state/fitness.json")
    if fitness_file.exists():
        with open(fitness_file) as f:
            fitness = json.load(f)
        print("\n=== FITNESS.JSON (test entries) ===")
        for k, v in fitness.items():
            if "heartbeat" in k.lower() or "incomplete" in k.lower() or "weld" in k.lower():
                print(f"  {k}: {v}")
    
    # Check projects ledger for test_incomplete_heartbeat_weld
    ledger = Path("state/projects_ledger.json")
    if ledger.exists():
        with open(ledger) as f:
            projects = json.load(f)
        print("\n=== PROJECTS LEDGER (incomplete_heartbeat) ===")
        for p in projects:
            name = p.get("name", "")
            if "incomplete" in name.lower() or "heartbeat" in name.lower():
                print(f"  {json.dumps(p, indent=2)}")

if __name__ == "__main__":
    peek()
