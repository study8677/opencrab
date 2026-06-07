#!/usr/bin/env python3
"""Generate retirement audit report with evidence."""

import json
from pathlib import Path
from datetime import datetime

def generate_audit_report():
    report = {
        "title": "Retirement Audit Report",
        "timestamp": datetime.now().isoformat(),
        "action": "garden_retirement_drill",
        "modules_retired": [],
        "attic_verification": {},
        "ledger_verification": {},
        "total_modules_before": None,
        "total_modules_after": None,
    }
    
    # Count modules before (approximate - we archived 5)
    all_py = list(Path(".").glob("*.py"))
    report["total_modules_current"] = len(all_py)
    
    # Check attic contents
    attic = Path("attic")
    if attic.exists():
        report["attic_verification"]["exists"] = True
        report["attic_verification"]["archived_modules"] = [
            f.name for f in attic.glob("*.py")
        ]
        report["attic_verification"]["count"] = len(list(attic.glob("*.py")))
    else:
        report["attic_verification"]["exists"] = False
    
    # Check ledger
    ledger = Path("retirement_ledger.jsonl")
    if ledger.exists():
        records = []
        with open(ledger) as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except:
                    pass
        report["ledger_verification"]["exists"] = True
        report["ledger_verification"]["record_count"] = len(records)
        report["ledger_verification"]["records"] = records
        report["modules_retired"] = [r["module"] for r in records if r.get("action") == "retire"]
    else:
        report["ledger_verification"]["exists"] = False
    
    # Verify each retired module is NOT in root
    for mod in report["modules_retired"]:
        exists_in_root = (Path(".") / mod).exists()
        report["modules_retired"].append({
            "module": mod,
            "still_in_root": exists_in_root,
            "archived": mod in report["attic_verification"].get("archived_modules", [])
        })
    
    return report

if __name__ == "__main__":
    report = generate_audit_report()
    
    print("=" * 60)
    print("RETIREMENT AUDIT REPORT")
    print("=" * 60)
    print(json.dumps(report, indent=2))
    
    with open("retirement_audit_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    print("\nReport saved to retirement_audit_report.json")
    
    # Verification summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    
    if report["ledger_verification"].get("exists"):
        print(f"✓ Ledger exists with {report['ledger_verification']['record_count']} records")
    else:
        print("✗ Ledger not found")
    
    if report["attic_verification"].get("exists"):
        print(f"✓ Attic exists with {report['attic_verification']['count']} archived modules")
        for m in report["attic_verification"].get("archived_modules", []):
            print(f"  - {m}")
    else:
        print("✗ Attic not found")
    
    print(f"\nCurrent root .py files: {report['total_modules_current']}")
