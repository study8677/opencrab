#!/usr/bin/env python3
"""Quick view of fitness ledger status."""
import os
import json
import sys
from datetime import datetime

def main():
    print("=" * 70)
    print("FITNESS LEDGER STATUS")
    print("=" * 70)
    
    base = "state/fitness"
    
    # Check what exists
    components = ["arena", "boundaryeval", "regression", "canary"]
    
    print("\n📁 Component Files:")
    all_exist = True
    for comp in components:
        path = f"{base}/{comp}/latest.json"
        exists = os.path.exists(path)
        status = "✓" if exists else "✗"
        print(f"   {status} {comp}/latest.json")
        if not exists:
            all_exist = False
    
    # Show latest results if available
    if all_exist:
        print("\n📊 Latest Results:")
        
        # Arena
        with open(f"{base}/arena/latest.json") as f:
            arena = json.load(f)
        print(f"\n   Arena: {len(arena.get('agents', []))} agents evaluated")
        if "scores" in arena:
            for agent, score in arena["scores"].items():
                print(f"      {agent}: {score}")
        
        # Boundary
        with open(f"{base}/boundaryeval/latest.json") as f:
            boundary = json.load(f)
        violations = boundary.get("violations", [])
        print(f"\n   Boundary: {len(boundary.get('dimensions', []))} dimensions")
        print(f"      Violations: {violations if violations else 'None'}")
        
        # Regression
        with open(f"{base}/regression/latest.json") as f:
            regression = json.load(f)
        if isinstance(regression, dict):
            suites = [v for k, v in regression.items() if isinstance(v, dict)]
            if suites and "pass_rate" in suites[0]:
                rates = [s["pass_rate"] for s in suites]
                overall = sum(rates) / len(rates) if rates else 0
                print(f"\n   Regression: {len(suites)} suites, overall {overall:.1f}%")
            else:
                print(f"\n   Regression: {len(regression)} suites")
        
        # Canary
        with open(f"{base}/canary/latest.json") as f:
            canary = json.load(f)
        health = canary.get("health_score", "N/A")
        print(f"\n   Canary: health score {health}")
        
        # Weakness analysis
        weakness_path = f"{base}/meta/weakness_analysis.json"
        if os.path.exists(weakness_path):
            with open(weakness_path) as f:
                weakness = json.load(f)
            print(f"\n🎯 Top Weaknesses ({weakness.get('weakness_count', 0)} total):")
            for i, w in enumerate(weakness.get("weaknesses", [])[:5], 1):
                print(f"   {i}. [{w['source']}] {w['dimension']}")
                print(f"      Score: {w['score']:.1f} | Gap: {w['gap']:.1f} | {w['priority']}")
    else:
        print("\n⚠ Some components missing. Run execute_fitness_run.py to populate.")
    
    print("\n" + "=" * 70)
    print(f"Status check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

if __name__ == "__main__":
    main()
