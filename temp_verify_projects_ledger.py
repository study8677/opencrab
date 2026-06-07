#!/usr/bin/env python3
"""Verify the projects ledger and heartbeat_tasks integration."""
import sys
sys.path.insert(0, '.')

def main():
    print("=== Projects Ledger Status ===")
    try:
        from projects import load_projects_ledger
        ledger = load_projects_ledger()
        for pid, proj in ledger.items():
            if 'incomplete' in proj.get('name', '').lower() or \
               'heartbeat' in proj.get('name', '').lower():
                print(f"  {pid}: {proj}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n=== Heartbeat Tasks Status ===")
    try:
        from heartbeat_tasks import load_tasks, find_task
        tasks = load_tasks()
        print(f"  Total tasks: {len(tasks)}")
        for t in tasks:
            if 'incomplete' in t.description.lower() or \
               'heartbeat' in t.description.lower():
                print(f"  [{t.status}] {t.task_id}: {t.description}")
                if t.completed_at:
                    print(f"    completed_at: {t.completed_at}")
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == '__main__':
    main()
