#!/usr/bin/env python3
"""Probe: find modules with zero cross-references for retirement."""

import ast
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(".")
PY_FILES = list(ROOT.glob("*.py"))
PY_FILES = [f for f in PY_FILES if f.name not in {"__init__.py", "sitecustomize.py"}]

def get_imports(file_path):
    """Extract all imports from a Python file."""
    imports = set()
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
    except Exception:
        pass
    return imports

def get_all_string_refs(file_path):
    """Get all string references that might indicate module usage."""
    refs = set()
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Check if it looks like a module/file reference
                val = node.value
                if ".py" in val or "/" in val or "\\" in val:
                    refs.add(val)
            elif isinstance(node, ast.Name):
                refs.add(node.id)
    except Exception:
        pass
    return refs

def scan_references(module_name, py_files):
    """Check if module_name is referenced by any other file."""
    stem = module_name.replace(".py", "")
    refs = []
    
    for f in py_files:
        if f.name == module_name:
            continue
        try:
            content = f.read_text(encoding="utf-8")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if stem in line or module_name in line:
                    # Skip comments
                    code_part = line.split("#")[0]
                    if stem in code_part or module_name.replace(".py", "") in code_part:
                        refs.append({"file": f.name, "line": i, "text": line.strip()[:80]})
        except Exception:
            continue
    
    return refs

# Build import graph
imports_map = {}
for f in PY_FILES:
    imports_map[f.name] = get_imports(f)

# Scan for zero-ref candidates
print("=== Scanning for Zero-Reference Modules ===\n")

candidates = []
checked = set()

for f in PY_FILES:
    mod_name = f.name
    stem = mod_name.replace(".py", "")
    
    # Count how many files import or reference this module
    ref_count = 0
    refs = []
    
    for other_file, imports in imports_map.items():
        if other_file == mod_name:
            continue
        if stem in imports:
            ref_count += 1
            refs.append(other_file)
    
    # Also check string references
    string_refs = scan_references(mod_name, PY_FILES)
    
    if ref_count == 0 and len(string_refs) == 0:
        candidates.append({
            "module": mod_name,
            "import_refs": refs,
            "string_refs": string_refs,
            "total_refs": ref_count + len(string_refs)
        })
        print(f"CANDIDATE: {mod_name} (0 refs)")
    else:
        checked.add(mod_name)
        print(f"  {mod_name}: {ref_count} import refs, {len(string_refs)} string refs")

print(f"\n=== Zero-Reference Candidates ({len(candidates)}) ===")
for c in candidates:
    print(f"  - {c['module']}")

# Save evidence
with open("zero_ref_candidates.json", "w") as f:
    json.dump({
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "total_candidates": len(candidates),
        "candidates": candidates
    }, f, indent=2)

print(f"\nEvidence saved to zero_ref_candidates.json")
