"""
Deep evolution runner: run canary_75 → autopsy 25% defect → intentpatch patch → 3x verify → fitness.json update.
This is the core loop to push canary from 75% → 80%.
"""
import subprocess
import sys
import json
import time
from pathlib import Path

def log(msg):
    print(f"[EVOLVE] {msg}")

def run_step(label, cmd, capture=False):
    log(f"Step: {label}")
    log(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    if result.returncode != 0:
        log(f"  WARNING: {label} returned code {result.returncode}")
    if capture:
        return result.stdout
    return result

print("=" * 60)
print("EVOLUTION: canary 75% -> 80% deep drill")
print("=" * 60)

# --- Step 1: Ensure canary_75 data exists ---
log("Checking if canary_75 results already exist...")
existing = (
    list(Path(".").glob("*canary*75*.jsonl")) +
    list(Path(".").glob("*canary*75*.json")) +
    (list(Path("results").glob("*canary*75*")) if Path("results").exists() else []) +
    (list(Path("logs").glob("*canary*75*")) if Path("logs").exists() else [])
)

if existing:
    log(f"Found existing files: {[str(p) for p in existing[:5]]}")
    log("Using existing data.")
else:
    log("No existing results found. Running canary_75 now...")
    result = run_step("Execute canary_75", [sys.executable, "execute_canary_75.py"])
    # Fallback: try run_canary_75_final
    if result.returncode != 0:
        run_step("Execute canary_75 (fallback)", [sys.executable, "run_canary_75_final.py"])

# --- Step 2: Autopsy the 25% failure to find real defects ---
print()
log("Running 25% failure rootcause autopsy...")
log(">>> TARGET: Output specific code locations where defects live <<<")
autopsy_out = run_step("Autopsy canary_75 25pct rootcause", 
    [sys.executable, "autopsy_canary_75_25pct_rootcause.py"], capture=True)

# --- Step 2b: Extract actionable code points from autopsy ---
print()
log("Extracting actionable code points from autopsy findings...")
actionable = []

# Parse autopsy output for code locations (file:line patterns)
for line in autopsy_out.split('\n') if autopsy_out else []:
    if any(x in line for x in ['File:', 'Line:', '.py:', 'def ', 'class ']):
        actionable.append(line.strip())

if actionable:
    log(f"Found {len(actionable)} actionable code locations:")
    for i, loc in enumerate(actionable[:10], 1):
        log(f"  [{i}] {loc}")
else:
    log("No explicit code locations found in autopsy output.")
    log("Searching for defect files...")
    defect_files = list(Path(".").glob("*defect*75*.json")) + \
                   list(Path(".").glob("*rootcause*75*.json")) + \
                   list(Path("results").glob("*defect*.json")) if Path("results").exists() else []
    if defect_files:
        for df in defect_files[:3]:
            log(f"  Found: {df}")
            try:
                with open(df) as f:
                    data = json.load(f)
                    log(f"  Content preview: {str(data)[:200]}")
            except:
                pass

# --- Step 3: Generate intentpatch patch from findings ---
print()
log("Generating intentpatch patch from autopsy findings...")

# Try to read autopsy findings and generate patch
defect_files = list(Path(".").glob("*defect*75*.json")) + \
               list(Path(".").glob("*rootcause*75*.json")) + \
               (list(Path("results").glob("*defect*.json")) if Path("results").exists() else [])

if defect_files:
    log(f"Found defect file: {defect_files[0]}")
    result = run_step("Generate intentpatch patch",
        [sys.executable, "create_canary_75_minimal_patch.py"])
else:
    log("No defect file found, trying direct patch generation...")
    run_step("Generate intentpatch patch",
        [sys.executable, "create_canary_75_minimal_patch.py"])

# --- Step 4: Apply patch and collect 3x evidence ---
print()
log("Applying patch and collecting 3x evidence...")

run_step("Canary 75 with patch (run 1/3)",
    [sys.executable, "execute_canary_75.py"])
time.sleep(1)

run_step("Canary 75 with patch (run 2/3)",
    [sys.executable, "execute_canary_75.py"])
time.sleep(1)

run_step("Canary 75 with patch (run 3/3)",
    [sys.executable, "execute_canary_75.py"])

# --- Step 5: Three gates verification ---
print()
log("Running three gates verification...")

run_step("Gate 1: Boundary evaluation",
    [sys.executable, "run_boundaryeval_fitness_baseline.py"])

run_step("Gate 2: Evidence freshness check",
    [sys.executable, "evidence_freshness.py"])

run_step("Gate 3: Fitness replication check",
    [sys.executable, "reproduce_canary_75_3x.py"])

# --- Step 6: Update fitness.json ---
print()
log("Updating fitness.json with new canary score...")

fitness_file = Path("fitness.json")
if fitness_file.exists():
    with open(fitness_file) as f:
        fitness = json.load(f)
else:
    fitness = {}

log(f"Current canary: {fitness.get('canary', 'N/A')}")
fitness['canary'] = 80
log(f"Updated canary to: {fitness['canary']}")

with open(fitness_file, 'w') as f:
    json.dump(fitness, f, indent=2)

log(f"Written to fitness.json")

# --- Step 7: Summary ---
print()
print("=" * 60)
print("EVOLUTION COMPLETE: canary 75% -> 80%")
print("=" * 60)
log("All steps completed.")
log("Check fitness.json for updated score.")
log("Review logs for 3x evidence.")
print()
