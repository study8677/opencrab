#!/usr/bin/env python3
"""Peek at the current state of test_incomplete_heartbeat_weld and related infrastructure."""
import sys
sys.path.insert(0, '.')

def main():
    # Check heartbeat_tasks for this specific test
    try:
        from heartbeat_tasks import load_tasks
        tasks = load_tasks()
        target = [t for t in tasks if 'test_incomplete_heartbeat_weld' in str(t)]
        print("=== heartbeat_tasks ===")
        for t in target:
            print(f"  {t}")
    except Exception as e:
        print(f"heartbeat_tasks error: {e}")

    # Check projects ledger
    try:
        from projects import load_projects_ledger, update_project_status
        ledger = load_projects_ledger()
        target_proj = [p for p in ledger.values() if 'test_incomplete_heartbeat_weld' in p.get('name', '')]
        print("\n=== projects ledger ===")
        for p in target_proj:
            print(f"  {p}")
    except Exception as e:
        print(f"projects error: {e}")

    # Check crab heartbeat state
    try:
        import crab
        print(f"\n=== crab.py has heartbeat_cross_project: {hasattr(crab, 'cross_project_heartbeat_continuation') or hasattr(crab, 'heartbeat_cross_project_regression')}")
        # Check what's in crab.py related to heartbeat
        heartbeat_members = [m for m in dir(crab) if 'heartbeat' in m.lower() or 'cross' in m.lower()]
        print(f"  heartbeat/cross members: {heartbeat_members}")
    except Exception as e:
        print(f"crab.py error: {e}")

if __name__ == '__main__':
    main()
