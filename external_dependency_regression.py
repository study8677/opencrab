"""
Regression test to ensure no new external AI dependencies are introduced.
Runs the external dependency scanner and checks against a baseline.
"""

import os
import sys
import tempfile
from external_dependency_scanner import scan_directory, check_for_new_calls, generate_weaning_list, update_baseline

BASELINE_FILE = os.path.join(os.path.dirname(__file__), '.external_baseline.list')


def test_no_new_external_calls():
    """Test that no new external calls are added to the codebase."""
    # Scan the current directory
    scan_dir = os.path.dirname(os.path.abspath(__file__))
    results = scan_directory(scan_dir)
    
    # Check against baseline
    is_clean, new_calls = check_for_new_calls(BASELINE_FILE, results)
    
    if not is_clean:
        print("FAIL: New external calls detected:", file=sys.stderr)
        for call in new_calls:
            print(f"  {call['file']}:{call['line']}: {call['type']}", file=sys.stderr)
        # Also print the weaning list for context
        print("\nCurrent weaning list:", file=sys.stderr)
        print(generate_weaning_list(results), file=sys.stderr)
        assert False, "New external AI dependencies found"
    else:
        # Update baseline with current results (so that removed calls are also reflected)
        update_baseline(BASELINE_FILE, results)
        print("PASS: No new external calls detected.")


if __name__ == '__main__':
    test_no_new_external_calls()
