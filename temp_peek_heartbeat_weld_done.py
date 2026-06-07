#!/usr/bin/env python3
"""Peek at heartbeat_weld status and what needs to be done."""

import sys
sys.path.insert(0, '.')

# Check run_incomplete_heartbeat_weld_to_done.py
with open('run_incomplete_heartbeat_weld_to_done.py') as f:
    content = f.read()
print("=== run_incomplete_heartbeat_weld_to_done.py ===")
print(content[:3000])
print("...")
print()

# Check heartbeat.py
with open('heartbeat.py') as f:
    content = f.read()
print("=== heartbeat.py ===")
print(content[:3000])
print("...")
print()

# Check if there's a TEST_ALL.py that might reference this test
with open('TEST_ALL.py') as f:
    content = f.read()
if 'test_incomplete_heartbeat_weld' in content:
    print("=== TEST_ALL.py mentions test_incomplete_heartbeat_weld ===")
    for line in content.split('\n'):
        if 'test_incomplete_heartbeat_weld' in line.lower():
            print(line)
print()
