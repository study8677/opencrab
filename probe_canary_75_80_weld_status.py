#!/usr/bin/env python3
"""探针：快速摸清 canary 75→80 焊链现状"""
import json
import subprocess
from pathlib import Path

def probe():
    print("=== CANARY 75→80 BRAIN-ONLY WELD PROBE ===\n")
    
    # 1. 基线 fitness.json
    fitness_path = Path("fitness.json")
    if fitness_path.exists():
        with open(fitness_path) as f:
            fitness = json.load(f)
        baseline = fitness.get("canary_75", {})
        print(f"当前基线 canary_75: {baseline}")
    else:
        print("无 fitness.json")
        baseline = {}
    
    # 2. check three gates
    print("\n--- Three Gates Status ---")
    result = subprocess.run(["python", "check_three_gates.py"], capture_output=True, text=True)
    print(result.stdout[:500] if result.stdout else "无输出")
    
    # 3. check brainonly status
    print("\n--- Brainonly Status ---")
    result = subprocess.run(["python", "check_brainonly.py"], capture_output=True, text=True)
    print(result.stdout[:500] if result.stdout else "无输出")
    
    # 4. 尝试跑基线
    print("\n--- Baseline Run ---")
    result = subprocess.run(
        ["python", "-c", 
         "from canary import Canary; c = Canary(); print('canary_75:', c.canary_75(), 'canary_80:', c.canary_80())"],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print("ERROR:", result.stderr[:200])
    
    print("\n=== PROBE DONE ===")

if __name__ == "__main__":
    probe()
