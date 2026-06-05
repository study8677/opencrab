#!/usr/bin/env python3
"""Main entry point: run the full evolution cycle."""

import subprocess
import sys

def main():
    print("=" * 60)
    print("EVOLUTION CYCLE: Find Weakest Cell → Surgical Fix → 3x Gate")
    print("=" * 60)
    
    # Step 1: Find weakest cell
    print("\n[STEP 1] Running evalbench baseline to find actual weakest cell...")
    result = subprocess.run([sys.executable, "find_weakest_cell.py"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}")
        sys.exit(1)
    print(result.stdout)
    
    # Step 2: Apply surgical fix and verify
    print("\n[STEP 2] Applying surgical fix with 3x reproduction gate...")
    result = subprocess.run([sys.executable, "single_point_surgery.py"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}")
        sys.exit(1)
    print(result.stdout)
    
    print("\n" + "=" * 60)
    print("EVOLUTION CYCLE COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
