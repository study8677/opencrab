#!/usr/bin/env python3
"""Check state files for incomplete_heartbeat_weld."""

import sys, os
sys.path.insert(0, '.')

# Check state files
state_files = [
    'state/projects.json',
    'state/planner.json',
    '.crab/state.json',
]

for sf in state_files:
    if os.path.exists(sf):
        print(f"=== {sf} ===")
        with open(sf) as f:
            content = f.read()
        if 'incomplete_heartbeat_weld' in content:
            print(content[:2000])
        else:
            print("(no incomplete_heartbeat_weld reference)")
        print()
    else:
        print(f"{sf}: NOT FOUND")
        print()
