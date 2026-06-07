import json
from pathlib import Path

# 读 intentpatch.py
ip = Path("intentpatch.py")
if ip.exists():
    src = ip.read_text()
    print("=== intentpatch.py 关键片段 ===")
    # 找 generate 函数
    if "def generate" in src:
        idx = src.find("def generate")
        print(src[idx:idx+1500])

print("\n=== patchfitroom.py 关键片段 ===")
pr = Path("patchfitroom.py")
if pr.exists():
    src = pr.read_text()
    for gate in ["gate_syntax", "gate_semantic", "gate_fitness_delta"]:
        if f"def {gate}" in src:
            idx = src.find(f"def {gate}")
            end = src.find("\ndef ", idx+1)
            snippet = src[idx:end if end > 0 else idx+500]
            print(f"\n--- {gate} ---")
            print(snippet[:600])

print("\n=== readpack.py 关键片段 ===")
rp = Path("readpack.py")
if rp.exists():
    src = rp.read_text()
    if "def pack" in src:
        idx = src.find("def pack")
        print(src[idx:idx+800])

print("\n=== crab.py apply_patch ===")
crab = Path("crab.py")
if crab.exists():
    src = crab.read_text()
    if "def apply_patch" in src:
        idx = src.find("def apply_patch")
        print(src[idx:idx+1200])
    if "def snapshot" in src:
        idx = src.find("def snapshot")
        print(src[idx:idx+800])
    if "def get_cell" in src:
        idx = src.find("def get_cell")
        print(src[idx:idx+500])
    if "def list_cells" in src:
        idx = src.find("def list_cells")
        print(src[idx:idx+500])
