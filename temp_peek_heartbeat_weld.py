import os, sys
# peek at heartbeat weld status

# Read run_incomplete_heartbeat_weld_to_done.py
print("=== run_incomplete_heartbeat_weld_to_done.py ===")
if os.path.exists("run_incomplete_heartbeat_weld_to_done.py"):
    with open("run_incomplete_heartbeat_weld_to_done.py") as f:
        print(f.read())

print("\n=== heartbeat_tasks.py (first 200 lines) ===")
if os.path.exists("heartbeat_tasks.py"):
    with open("heartbeat_tasks.py") as f:
        lines = f.readlines()
        for line in lines[:200]:
            print(line, end='')
else:
    print("NOT FOUND")

print("\n=== heartbeat.py (first 150 lines) ===")
if os.path.exists("heartbeat.py"):
    with open("heartbeat.py") as f:
        lines = f.readlines()
        for line in lines[:150]:
            print(line, end='')
else:
    print("NOT FOUND")
