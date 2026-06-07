#!/usr/bin/env python3
"""Inspect the heartbeat mechanism - what tasks are tracked, what blocks completion."""
import json
from pathlib import Path

def inspect():
    print("=== CRAB HEARTBEAT INSPECTION ===\n")
    
    # 1. Check heartbeat.py - the core engine
    heartbeat_py = Path("heartbeat.py")
    if heartbeat_py.exists():
        print(f"heartbeat.py exists: {heartbeat_py.stat().st_size} bytes")
        # Find test_incomplete_heartbeat_weld references
        content = heartbeat_py.read_text()
        if "incomplete_heartbeat_weld" in content:
            lines = [l for l in content.split('\n') if 'incomplete_heartbeat_weld' in l]
            print(f"  References to incomplete_heartbeat_weld: {len(lines)}")
            for l in lines[:5]:
                print(f"    {l.strip()}")
    else:
        print("heartbeat.py NOT FOUND")
    
    # 2. Check heartbeat_tasks.py
    tasks_py = Path("heartbeat_tasks.py")
    if tasks_py.exists():
        print(f"\nheartbeat_tasks.py exists: {tasks_py.stat().st_size} bytes")
    
    # 3. Check run_incomplete_heartbeat_weld_to_done.py
    runner = Path("run_incomplete_heartbeat_weld_to_done.py")
    if runner.exists():
        print(f"\nrun_incomplete_heartbeat_weld_to_done.py exists: {runner.stat().st_size} bytes")
        content = runner.read_text()
        print("  Key logic snippet:")
        for i, line in enumerate(content.split('\n')):
            if 'def ' in line or 'IN_PROGRESS' in line or 'DONE' in line:
                print(f"    {i+1}: {line}")
    
    # 4. Check state files
    for sf in ["state/heartbeat_tasks.json", "state/fitness.json", "state/projects_ledger.json"]:
        p = Path(sf)
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            print(f"\n{sf}:")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        name = item.get("name", "") or item.get("task", "")
                        if "heartbeat" in name.lower() or "incomplete" in name.lower():
                            print(f"  {json.dumps(item)}")
            elif isinstance(data, dict):
                for k, v in data.items():
                    if "heartbeat" in k.lower() or "incomplete" in k.lower():
                        print(f"  {k}: {v}")

if __name__ == "__main__":
    inspect()
