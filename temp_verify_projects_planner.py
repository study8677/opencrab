#!/usr/bin/env python3
"""Test: planner.form_intent correctly picks continue vs start_new."""
import os, sys
from pathlib import Path

# ensure test fixtures exist
StateDir = Path("state/projects")
StateDir.mkdir(parents=True, exist_ok=True)

# fixture 1: existing project for "fitness"
fit_md = StateDir / "fitness_closed_loop.md"
fit_md.write_text("# Fitness Closed Loop\nTracking real fitness improvements.\n")

# fixture 2: existing project for "planner"
pln_md = StateDir / "planner_memory.md"
pln_md.write_text("# Planner Memory\nTracking planner evolution.\n")

sys.path.insert(0, ".")
from planner import form_intent

# Test 1: topic with existing project -> continue
result1 = form_intent("fitness")
assert result1["strategy"] == "continue", f"Expected continue, got {result1}"
print(f"✅ 继续旧项目: {result1}")

# Test 2: topic with NO existing project -> start_new
result2 = form_intent("totally_new_topic_xyz")
assert result2["strategy"] == "start_new", f"Expected start_new, got {result2}"
print(f"✅ 开新拍: {result2}")

# Test 3: existing by stem name
result3 = form_intent("planner")
assert result3["strategy"] == "continue", f"Expected continue, got {result3}"
print(f"✅ 续旧(按stem名): {result3}")

# cleanup
fit_md.unlink(missing_ok=True)
pln_md.unlink(missing_ok=True)

print("\n✅ planner.form_intent 能正确区分续旧 vs 开新！")
