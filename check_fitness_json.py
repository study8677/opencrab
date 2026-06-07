#!/usr/bin/env python3
"""Read and validate fitness.json to see if score has improved beyond 75.0%"""
import json
import os
from pathlib import Path

def check_fitness_json():
    # Find fitness.json - check common locations
    candidates = [
        Path("fitness.json"),
        Path("results/fitness.json"),
        Path("run/fitness.json"),
        Path("eval/fitness.json"),
        Path("benchmark/fitness.json"),
    ]
    
    found_path = None
    for p in candidates:
        if p.exists():
            found_path = p
            break
    
    # Also try to find it recursively
    if not found_path:
        for root, dirs, files in os.walk("."):
            if "fitness.json" in files:
                found_path = Path(root) / "fitness.json"
                break
    
    if not found_path:
        print("❌ fitness.json NOT FOUND in common locations")
        print("Searched:", [str(p) for p in candidates])
        return None
    
    print(f"📄 Found: {found_path}")
    
    with open(found_path) as f:
        data = json.load(f)
    
    print("\n" + "="*50)
    print("FITNESS JSON CONTENTS:")
    print("="*50)
    print(json.dumps(data, indent=2))
    print("="*50)
    
    # Extract score
    score = data.get("score") or data.get("fitness") or data.get("accuracy") or data.get("result")
    
    if score is None:
        # Try nested structures
        if isinstance(data, dict):
            for key in ["result", "metrics", "evaluation", "summary"]:
                if key in data:
                    nested = data[key]
                    if isinstance(nested, dict):
                        score = nested.get("score") or nested.get("fitness") or nested.get("accuracy")
                        if score is not None:
                            print(f"\n📊 Extracted score from '{key}': {score}")
                            break
    
    if score is None:
        print("\n⚠️  Could not extract score from:", list(data.keys()) if isinstance(data, dict) else type(data))
        return None
    
    score_pct = float(score) * 100 if float(score) <= 1.0 else float(score)
    
    print(f"\n🎯 CURRENT SCORE: {score_pct:.1f}%")
    
    # Decision
    if score_pct <= 75.0:
        print("\n🔴 SCORE STUCK AT ~75% - NOT IMPROVED")
        print("   Must凿 25% 真缺陷, stop saying 'running'")
        print("   Need to find and fix real defects, not fake patches")
        return "STUCK"
    elif score_pct > 75.0:
        print(f"\n🟢 SCORE IMPROVED TO {score_pct:.1f}%")
        print("   Progress confirmed - can continue to next weld step")
        return "IMPROVED"
    else:
        return "UNKNOWN"

if __name__ == "__main__":
    result = check_fitness_json()
    print(f"\n{'='*50}")
    print(f"VERDICT: {result}")
    print(f"{'='*50}")
