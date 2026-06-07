#!/usr/bin/env python3
"""
do_canary_25_minimal_weld.py
从 autopsy_canary_75_25pct_rootcause.py 提取最小一个死因，
跑 astlocator → intentpatch → patchfitroom → 3x真焊链验证。
"""
import subprocess
import json
import sys
from pathlib import Path

# 1. 读取 autopsy 死因，提取最小一个
def load_minimal_defect():
    autopsy_path = Path("autopsy_canary_75_25pct_rootcause.py")
    if not autopsy_path.exists():
        print("ERROR: autopsy_canary_75_25pct_rootcause.py not found")
        sys.exit(1)
    
    # 读取 autopsy 文件找 ROOT_CAUSE
    content = autopsy_path.read_text()
    
    # 提取 defects 列表
    import re
    match = re.search(r'defects\s*=\s*\[(.*?)\]', content, re.DOTALL)
    if not match:
        print("ERROR: could not parse defects from autopsy")
        sys.exit(1)
    
    # 简单解析每个 defect
    defects_text = match.group(1)
    defect_blocks = re.findall(r'\{[^}]+\}', defects_text, re.DOTALL)
    
    defects = []
    for block in defect_blocks:
        d = {}
        for kv in re.findall(r"'(\w+)':\s*'([^']*)'", block):
            d[kv[0]] = kv[1]
        if d:
            defects.append(d)
    
    if not defects:
        print("ERROR: no defects parsed")
        sys.exit(1)
    
    # 选最小一个（按 severity/size 排序，这里简单取第一个）
    defect = defects[0]
    print(f"SELECTED MINIMAL DEFECT: {defect.get('cell', 'unknown')}")
    print(f"  symptom: {defect.get('symptom', '')}")
    print(f"  cause: {defect.get('cause', '')}")
    return defect

# 2. 运行 astlocator 找位置
def run_astlocator(defect):
    cmd = [
        "python", "-c",
        f"from astlocator import locate_defect; "
        f"result = locate_defect('{defect.get('cause', '')}'); "
        f"print(result)"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"\n[ASTLOCATOR] stdout:\n{result.stdout}")
    if result.returncode != 0:
        print(f"[ASTLOCATOR] stderr:\n{result.stderr}")
        return None
    return result.stdout.strip()

# 3. 运行 intentpatch 生成 patch
def run_intentpatch(defect, location):
    cmd = [
        "python", "-c",
        f"from intentpatch import generate_patch; "
        f"result = generate_patch('{defect.get('cause', '')}', '{location}'); "
        f"print(result)"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"\n[INTENTPATCH] stdout:\n{result.stdout}")
    if result.returncode != 0:
        print(f"[INTENTPATCH] stderr:\n{result.stderr}")
        return None
    return result.stdout.strip()

# 4. 运行 patchfitroom 验证
def run_patchfitroom(patch):
    cmd = [
        "python", "-c",
        f"from patchfitroom import fit_patch; "
        f"result = fit_patch({repr(patch)}); "
        f"print(result)"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"\n[PATCHFITROOM] stdout:\n{result.stdout}")
    if result.returncode != 0:
        print(f"[PATCHFITROOM] stderr:\n{result.stderr}")
        return None
    return result.stdout.strip()

# 5. 运行 3x 真焊链
def run_true_weld_chain(patch):
    weld_script = Path("canary_80_3x_autopsy_weld.py")
    if not weld_script.exists():
        print("ERROR: canary_80_3x_autopsy_weld.py not found")
        return None
    
    cmd = ["python", str(weld_script), "--patch", patch]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"\n[TRUE_WELD_3X] stdout:\n{result.stdout}")
    if result.returncode != 0:
        print(f"[TRUE_WELD_3X] stderr:\n{result.stderr}")
        return None
    return result.stdout.strip()

# 6. 主流程
def main():
    print("=" * 60)
    print("DO_CANARY_25_MINIMAL_WELD")
    print("=" * 60)
    
    # Step 1: 最小死因
    defect = load_minimal_defect()
    
    # Step 2: astlocator
    location = run_astlocator(defect)
    if not location:
        print("BLOCKED at astlocator")
        print("SIGNAL: astlocator cannot locate the cause")
        sys.exit(1)
    
    # Step 3: intentpatch
    patch = run_intentpatch(defect, location)
    if not patch:
        print("BLOCKED at intentpatch")
        print(f"SIGNAL: intentpatch failed to generate patch for cause='{defect.get('cause')}' at {location}")
        sys.exit(1)
    
    # Step 4: patchfitroom
    fit_result = run_patchfitroom(patch)
    if not fit_result:
        print("BLOCKED at patchfitroom")
        print(f"SIGNAL: patchfitroom rejected patch")
        sys.exit(1)
    
    # Step 5: 3x 真焊链
    weld_result = run_true_weld_chain(patch)
    if not weld_result:
        print("BLOCKED at true_weld_chain")
        print("SIGNAL: weld chain failed - no fitness improvement")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("WELD SUCCESS")
    print("=" * 60)
    print(f"Defect: {defect}")
    print(f"Location: {location}")
    print(f"Patch: {patch}")
    print(f"Weld result: {weld_result}")

if __name__ == "__main__":
    main()
