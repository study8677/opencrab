#!/usr/bin/env python3
"""Probe 9 unknown modules and retire any that have zero import/CLI/contract."""
import subprocess, json, os, shutil, sys

TARGETS = [
    "autonomy_meter",
    "crab_heartbeat_inspect",
    "hands_astbridge",
    "peek_baseline",
    "read_state",
    "showcase",
    "showcase_freshness_gate",
    "temp_peek",
    "test_brainonly_graduation_sample",
]

PROBER = "unknown_organ_prober.py"
RETIRE = "retirement_drill.py"
ATTIC  = "attic"

def run_prober(name: str) -> dict:
    result = subprocess.run(
        [sys.executable, PROBER, name],
        capture_output=True, text=True
    )
    print(f"\n=== probe: {name} ===")
    print(result.stdout[:2000])
    if result.stderr:
        print("STDERR:", result.stderr[:500])
    # Try parse JSON from output
    try:
        out = result.stdout
        # find JSON blob
        start = out.find('{')
        end   = out.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(out[start:end])
    except Exception:
        pass
    return {}

def retire(name: str) -> bool:
    result = subprocess.run(
        [sys.executable, RETIRE, name, "--attic", ATTIC],
        capture_output=True, text=True
    )
    print(f"\n=== retire: {name} ===")
    print(result.stdout[:2000])
    if result.returncode == 0:
        print(f"  ✓ moved to {ATTIC}/")
        return True
    else:
        print("STDERR:", result.stderr[:500])
        return False

def main():
    retired = []
    kept    = []
    for name in TARGETS:
        info = run_prober(name)
        # criteria: zero imports, zero CLI, zero contract
        imports  = info.get("imports",  [])
        cli      = info.get("cli",      [])
        contracts= info.get("contracts", [])
        if not imports and not cli and not contracts:
            print(f"  → ALL ZERO: imports={len(imports)} cli={len(cli)} contracts={len(contracts)}")
            if retire(name):
                retired.append(name)
            else:
                kept.append(name + " [retire FAILED]")
        else:
            print(f"  → keep: imports={len(imports)} cli={len(cli)} contracts={len(contracts)}")
            kept.append(name)

    print("\n\n=== SUMMARY ===")
    print(f"Retired ({len(retired)}): {retired}")
    print(f"Kept    ({len(kept)}): {kept}")

if __name__ == "__main__":
    main()
