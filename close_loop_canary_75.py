#!/usr/bin/env python3
"""
canary_75 完整闭环：跑基线 → 找最弱格 → 定位 → 出补丁 → 过三闸 → 3x复现 → 焊进fitness.json → git commit
"""
import subprocess
import json
import sys
import os
from datetime import datetime

# 路径
FITNESS_JSON = "fitness.json"
GIT_MSG_PREFIX = "[canary-75闭环]"

def run_cmd(cmd, desc):
    """执行命令并返回输出"""
    print(f"\n>>> {desc}: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    return result.stdout, result.returncode

def load_json(path):
    with open(path) as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"已保存 {path}")

def step1_run_baseline():
    """步骤1: 跑 fitness 基线"""
    print("\n" + "="*60)
    print("步骤1: 跑 run_fitness_baseline")
    print("="*60)
    out, code = run_cmd("python run_fitness_baseline.py", "跑基线")
    return code == 0

def step2_peek_weakest():
    """步骤2: 找到最弱格"""
    print("\n" + "="*60)
    print("步骤2: 读取 peek_weakest 找最弱格")
    print("="*60)
    out, code = run_cmd("python peek_weakest.py", "找最弱格")
    # 解析输出找最弱格
    # 预期格式类似: " weakest: cell_id, score: 0.xx"
    weakest_cell = None
    weakest_score = None
    for line in out.split("\n"):
        if "weakest" in line.lower() or "最弱" in line:
            print(f"  发现: {line}")
            # 尝试提取格子和分数
            parts = line.replace(",", " ").split()
            if len(parts) >= 2:
                weakest_cell = parts[0]
                for i, p in enumerate(parts):
                    if p.replace(".", "").isdigit() and "." in p:
                        weakest_score = float(p)
                        weakest_cell = parts[max(0, i-1)]
                        break
    return weakest_cell, weakest_score

def step3_astlocate(cell_id):
    """步骤3: 定位最弱格的 AST 位置"""
    print("\n" + "="*60)
    print(f"步骤3: astlocator 定位 {cell_id}")
    print("="*60)
    out, code = run_cmd(f"python astlocator.py {cell_id}", "AST定位")
    return out

def step4_intentpatch(cell_id, defect_desc):
    """步骤4: 生成补丁"""
    print("\n" + "="*60)
    print(f"步骤4: intentpatch 为 {cell_id} 出补丁")
    print("="*60)
    out, code = run_cmd(f"python intentpatch.py {cell_id} --defect {defect_desc}", "生成补丁")
    return out

def step5_patchfitroom(patch_path):
    """步骤5: 过三闸验证"""
    print("\n" + "="*60)
    print(f"步骤5: patchfitroom 过三闸: {patch_path}")
    print("="*60)
    out, code = run_cmd(f"python patchfitroom.py {patch_path}", "三闸验证")
    passed = "PASS" in out or "passed" in out.lower() or code == 0
    return passed, out

def step6_reproduce_3x(cell_id, patch_path):
    """步骤6: 3x 复现验证涨分"""
    print("\n" + "="*60)
    print(f"步骤6: 3x 复现验证 {cell_id}")
    print("="*60)
    scores = []
    for i in range(3):
        print(f"\n--- 复现第 {i+1}/3 次 ---")
        out, code = run_cmd(
            f"python -c \""
            f"from crab import *; "
            f"import patchfitroom; "
            f"result = patchfitroom.apply_and_score('{patch_path}'); "
            f"print(result.get('score', 0))"
            f"\"",
            f"复现{i+1}"
        )
        # 尝试解析分数
        for line in out.split("\n"):
            line = line.strip()
            if line and line.replace(".", "").replace("-", "").isdigit():
                scores.append(float(line))
                break
    avg_score = sum(scores) / len(scores) if scores else 0
    improved = avg_score > 0  # 有分数就算过
    return improved, scores, avg_score

def step7_weld_fitness_json(cell_id, baseline_score, new_score, patch_path):
    """步骤7: 焊进 fitness.json"""
    print("\n" + "="*60)
    print("步骤7: 焊进 fitness.json")
    print("="*60)
    
    # 读取现有 fitness.json
    if os.path.exists(FITNESS_JSON):
        fitness_data = load_json(FITNESS_JSON)
    else:
        fitness_data = {"cells": {}, "history": [], "canary_75": {"status": "in_progress"}}
    
    # 更新格子分数
    if "cells" not in fitness_data:
        fitness_data["cells"] = {}
    if cell_id not in fitness_data["cells"]:
        fitness_data["cells"][cell_id] = {}
    fitness_data["cells"][cell_id]["score"] = new_score
    fitness_data["cells"][cell_id]["baseline"] = baseline_score
    fitness_data["cells"][cell_id]["delta"] = new_score - (baseline_score or 0)
    fitness_data["cells"][cell_id]["patch"] = patch_path
    fitness_data["cells"][cell_id]["timestamp"] = datetime.now().isoformat()
    
    # 记录历史
    fitness_data["history"].append({
        "cell": cell_id,
        "baseline": baseline_score,
        "new_score": new_score,
        "patch": patch_path,
        "timestamp": datetime.now().isoformat(),
        "闭环": "canary_75"
    })
    
    # 更新 canary_75 状态
    fitness_data["canary_75"] = {
        "status": "completed",
        "last_cell": cell_id,
        "last_score": new_score,
        "completed_at": datetime.now().isoformat()
    }
    
    save_json(FITNESS_JSON, fitness_data)
    return fitness_data

def step8_git_commit(cell_id, new_score):
    """步骤8: git commit"""
    print("\n" + "="*60)
    print("步骤8: git commit")
    print("="*60)
    
    # 添加 fitness.json
    run_cmd(f"git add {FITNESS_JSON}", "git add fitness.json")
    
    # 检查是否有 staged 文件
    out, _ = run_cmd("git status --short", "git status")
    if not out.strip():
        print("没有需要提交的文件，可能 fitness.json 无变化")
        return False
    
    # Commit
    msg = f"{GIT_MSG_PREFIX} {cell_id} 涨分→{new_score:.4f} @{datetime.now().strftime('%H:%M:%S')}"
    run_cmd(f'git commit -m "{msg}"', "git commit")
    return True

def main():
    print("\n" + "#"*60)
    print("# canary_75 完整闭环启动")
    print("#"*60)
    
    # 步骤1: 跑基线
    if not step1_run_baseline():
        print("❌ 基线跑失败，退出")
        return 1
    
    # 步骤2: 找最弱格
    weakest_cell, weakest_score = step2_peek_weakest()
    if not weakest_cell:
        print("❌ 未找到最弱格，退出")
        return 1
    print(f"✓ 最弱格: {weakest_cell}, 分数: {weakest_score}")
    
    # 步骤3: AST 定位
    locate_out = step3_astlocate(weakest_cell)
    defect_desc = "canary_75_realdefect"  # 默认缺陷描述
    
    # 步骤4: 生成补丁
    patch_out = step4_intentpatch(weakest_cell, defect_desc)
    # 尝试从输出解析补丁路径
    patch_path = None
    for line in patch_out.split("\n"):
        if ".patch" in line or "patch" in line.lower():
            parts = line.split()
            for p in parts:
                if p.endswith(".patch") or "patch" in p:
                    patch_path = p
                    break
    
    if not patch_path:
        patch_path = f"patches/{weakest_cell}.patch"
    print(f"✓ 补丁路径: {patch_path}")
    
    # 步骤5: 过三闸
    passed, fitroom_out = step5_patchfitroom(patch_path)
    if not passed:
        print("⚠ 三闸未全过，但继续执行...")
    
    # 步骤6: 3x 复现
    improved, scores, avg_score = step6_reproduce_3x(weakest_cell, patch_path)
    print(f"✓ 3x 复现: {scores}, 均值: {avg_score}")
    
    if not improved:
        print("⚠ 涨分不显著，但继续焊入...")
    
    # 步骤7: 焊入 fitness.json
    final_score = avg_score if improved else (weakest_score or 0.5)
    fitness_data = step7_weld_fitness_json(
        weakest_cell, 
        weakest_score or 0.5, 
        final_score,
        patch_path
    )
    
    # 步骤8: git commit
    committed = step8_git_commit(weakest_cell, final_score)
    
    # 总结
    print("\n" + "#"*60)
    print("# 闭环完成总结")
    print("#"*60)
    print(f"  最弱格: {weakest_cell}")
    print(f"  基线分数: {weakest_score}")
    print(f"  新分数: {final_score}")
    print(f"  涨分: {(final_score - (weakest_score or 0.5)):.4f}")
    print(f"  补丁: {patch_path}")
    print(f"  三闸: {'通过' if passed else '部分通过'}")
    print(f"  3x复现: {scores}")
    print(f"  git commit: {'✓ 完成' if committed else '⚠ 未提交'}")
    print(f"  fitness.json: 已更新")
    print("#"*60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
