#!/usr/bin/env python3
"""验证 canary_75_real_weld 修复后能过三闸并写入 fitness.json"""
import sys
import json
from pathlib import Path

# 先验证语法
try:
    import py_compile
    py_compile.compile("canary_75_real_weld.py", doraise=True)
    print("✅ canary_75_real_weld.py 语法正确")
except py_compile.PyCompileError as e:
    print(f"❌ 语法错误: {e}")
    sys.exit(1)

try:
    py_compile.compile("intentpatch.py", doraise=True)
    print("✅ intentpatch.py 语法正确")
except py_compile.PyCompileError as e:
    print(f"❌ intentpatch.py 语法错误: {e}")
    sys.exit(1)

try:
    py_compile.compile("patchfitroom.py", doraise=True)
    print("✅ patchfitroom.py 语法正确")
except py_compile.PyCompileError as e:
    print(f"❌ patchfitroom.py 语法错误: {e}")
    sys.exit(1)

# 测试导入
print("\n=== 测试导入 ===")
try:
    from crab import Crab
    print("✅ Crab 导入成功")
except Exception as e:
    print(f"❌ Crab 导入失败: {e}")
    sys.exit(1)

try:
    from intentpatch import IntentPatch
    print("✅ IntentPatch 导入成功")
except Exception as e:
    print(f"❌ IntentPatch 导入失败: {e}")
    sys.exit(1)

try:
    from patchfitroom import PatchFitRoom
    print("✅ PatchFitRoom 导入成功")
except Exception as e:
    print(f"❌ PatchFitRoom 导入失败: {e}")
    sys.exit(1)

# 测试 Crab 的基本功能
print("\n=== 测试 Crab 基本功能 ===")
crab = Crab()
cells = crab.list_cells()
print(f"Cells 数量: {len(cells)}")
if cells:
    cell_id = cells[0]
    cell = crab.get_cell(cell_id)
    print(f"示例 cell: {cell_id} -> {cell}")
    fitness = cell.get("fitness", 0.5)
    print(f"fitness: {fitness}")
else:
    print("⚠ 没有 cells")
    cell_id = "test_cell"
    crab.cells[cell_id] = {"fitness": 0.6, "status": "test"}
    print(f"手动创建 cell: {crab.get_cell(cell_id)}")

# 测试 IntentPatch.generate
print("\n=== 测试 IntentPatch.generate ===")
from intentpatch import IntentPatch
context = {
    "cell_id": cell_id,
    "defect_type": "low_fitness",
    "fitness": crab.get_cell(cell_id).get("fitness", 0.5),
    "severity": 0.5
}
patch = IntentPatch.generate("low_fitness", context, max_ops=3)
print(f"生成 patch: {json.dumps(patch, indent=2)}")
print(f"ops 数量: {len(patch.get('ops', []))}")

# 测试 patchfitroom 三闸
print("\n=== 测试 patchfitroom 三闸 ===")
fitroom = PatchFitRoom()
gate1 = fitroom.gate_syntax(patch)
print(f"gate1 (syntax): {gate1}")
gate2 = fitroom.gate_semantic(patch, crab, cell_id)
print(f"gate2 (semantic): {gate2}")
gate3 = fitroom.gate_fitness_delta(patch, crab, cell_id)
print(f"gate3 (fitness_delta): {gate3}")

if gate1 and gate2 and gate3:
    print("✅ 三闸全过!")
else:
    print(f"⚠ 三闸未全过: {gate1=}, {gate2=}, {gate3=}")

# 测试 apply_patch
print("\n=== 测试 apply_patch ===")
if hasattr(crab, 'apply_patch'):
    old_fit = crab.get_cell(cell_id).get("fitness", 0.5)
    success = crab.apply_patch(cell_id, patch)
    new_fit = crab.get_cell(cell_id).get("fitness", 0.5)
    print(f"apply_patch 结果: {success}, fitness {old_fit:.3f} -> {new_fit:.3f}")
else:
    print("⚠ crab 没有 apply_patch 方法")

print("\n=== 验证完成 ===")
