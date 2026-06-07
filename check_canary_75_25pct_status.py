"""
Minimal status checker for canary 75% 25pct root cause analysis.
Prints current status and what's needed next.
"""
import json
from pathlib import Path

print("=" * 60)
print("CANARY 75% 25% FAILURE ROOTCAUSE ANALYSIS STATUS")
print("=" * 60)

# Check if we already have results
report_file = Path("canary_75_25pct_rootcause.json")
triage_file = Path("canary_75_25pct_triage.json")

if report_file.exists():
    with open(report_file) as f:
        report = json.load(f)
    print(f"\n✓ Rootcause report exists: {report_file}")
    print(f"  Total cases: {report.get('total', 'N/A')}")
    print(f"  Pass rate: {report.get('pass_rate', 'N/A')}%")
    print(f"  Classification: {report.get('classification', {})}")
    print(f"  Verdict: {report.get('verdict', 'N/A')}")
elif triage_file.exists():
    with open(triage_file) as f:
        triage = json.load(f)
    print(f"\n✓ Triage report exists: {triage_file}")
    print(f"  Total failures: {triage.get('total', 'N/A')}")
    print(f"  Type A: {triage.get('type_a_count', 0)}")
    print(f"  Type B: {triage.get('type_b_count', 0)}")
    print(f"  Type C: {triage.get('type_c_count', 0)}")
    print(f"  Type D: {triage.get('type_d_count', 0)}")
    print(f"  Recommendation: {triage.get('recommendation', 'N/A')}")
else:
    print("\n✗ No analysis results found yet.")
    print("\nStep 1: Run canary_75 to collect data:")
    print("  python run_canary_75_final.py")
    print("\nStep 2: Run the autopsy analysis:")
    print("  python canary_75_25pct_triage.py")

# Check for raw data sources
print("\n--- Data Source Check ---")
sources_found = []
for pattern in ["*canary*75*.jsonl", "*canary*75*.json"]:
    for p in list(Path(".").glob(pattern)) + list(Path("results").glob(pattern) if Path("results").exists() else []):
        if p not in sources_found:
            sources_found.append(p)

if sources_found:
    print(f"✓ Found {len(sources_found)} potential data files:")
    for p in sources_found[:5]:
        print(f"    {p}")
else:
    print("✗ No canary_75 data files found.")
    print("  Need to execute canary_75 benchmark first.")

print("\n--- Available Analysis Scripts ---")
for script in ["autopsy_canary_75_25pct_rootcause.py", "canary_75_25pct_triage.py"]:
    p = Path(script)
    status = "✓ exists" if p.exists() else "✗ missing"
    print(f"  {status}: {script}")

print("\n" + "=" * 60)
