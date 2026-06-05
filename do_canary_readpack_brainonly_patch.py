#!/usr/bin/env python3
"""
do_canary_readpack_brainonly_patch.py

对最弱格 canary 75% 下刀：
1. reproduce_canary_3x 找挂的 case
2. readpack 圈最小修面
3. brain-only 出补丁
4. 过三闸并入
5. 让 canary 真分涨
"""

import subprocess
import sys
import json
import os
from pathlib import Path

def run_cmd(cmd, desc):
    """运行命令并返回输出"""
    print(f"\n{'='*60}")
    print(f"[{desc}]")
    print(f"{'='*60}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr}")
    return result.stdout, result.returncode

def main():
    # Step 1: 用 reproduce_canary_3x 找挂的 case
    print("\n" + "="*70)
    print("STEP 1: reproduce_canary_3x 找挂的 case")
    print("="*70)
    
    # 运行 reproduce_canary_3x
    stdout, rc = run_cmd("python reproduce_canary_3x.py 2>&1 | head -100", "reproduce_canary_3x")
    
    # 找失败的 case
    failed_cases = []
    lines = stdout.split('\n')
    for i, line in enumerate(lines):
        if 'FAIL' in line or 'ERROR' in line or 'FAILED' in line:
            # 提取 case 信息
            if i > 0:
                failed_cases.append(lines[i-1] if lines[i-1].strip() else line)
    
    print(f"\n找到 {len(failed_cases)} 个失败的 case")
    
    # 如果没找到失败，用 peek_weakest 看最弱的
    if not failed_cases:
        print("\nreproduce_canary_3x 没有输出失败，尝试 peek_weakest...")
        stdout, rc = run_cmd("python peek_weakest.py --limit 5", "peek_weakest")
        
        # 尝试解析最弱的 case
        for line in stdout.split('\n'):
            if 'canary' in line.lower() or '75' in line:
                failed_cases.append(line.strip())
    
    if not failed_cases:
        print("没有找到失败的 case，尝试直接运行 fitness 测试...")
        # 直接运行 fitness 测试看结果
        stdout, rc = run_cmd("python -c \"from fitness_status import get_fitness_summary; print(get_fitness_summary())\"", "fitness_status")
    
    print(f"\n准备处理 {len(failed_cases)} 个 case")
    
    # Step 2: 对每个失败的 case 进行 readpack + brainonly
    for idx, case in enumerate(failed_cases[:3]):  # 只处理前3个
        print(f"\n{'='*70}")
        print(f"处理 Case {idx+1}: {case}")
        print("="*70)
        
        # 提取 case ID
        case_id = case.split('/')[-1] if '/' in case else case.split('\\')[-1] if '\\' in case else case
        
        # Step 2: readpack 圈最小修面
        print(f"\n[STEP 2] readpack 圈最小修面...")
        stdout, rc = run_cmd(f"python readpack.py --case {case_id} 2>&1", "readpack")
        
        # 解析 readpack 输出，找最小 patch
        min_patch = None
        for line in stdout.split('\n'):
            if 'min_patch' in line.lower() or 'minimal' in line.lower():
                min_patch = line.strip()
        
        # Step 3: brain-only 出补丁
        print(f"\n[STEP 3] brain-only 出补丁...")
        
        # 尝试直接调用 brainonly 相关功能
        brainonly_cmd = f"python brainonly_canary_patch.py --case {case_id}"
        if min_patch:
            brainonly_cmd += f" --patch {min_patch}"
        
        stdout, rc = run_cmd(brainonly_cmd, "brainonly_patch")
        
        # Step 4: 过三闸
        print(f"\n[STEP 4] 过三闸...")
        stdout, rc = run_cmd("python check_three_gates_canary.py 2>&1", "three_gates")
        
        # 检查是否通过
        passed = "PASS" in stdout or "pass" in stdout
        if passed:
            print("✓ 三闸通过!")
        else:
            print("✗ 三闸未完全通过，继续优化...")
        
        # Step 5: 如果三闸通过，并入
        if passed:
            print(f"\n[STEP 5] 并入 canary...")
            stdout, rc = run_cmd("python run_canary_evolution.py --merge 2>&1", "merge")
    
    # 最终验证
    print("\n" + "="*70)
    print("最终验证: canary 真分涨")
    print("="*70)
    
    # 运行 fitness baseline 看分数变化
    stdout, rc = run_cmd("python -c \"from check_fitness_json import check_fitness; result = check_fitness(); print(f'Fitness: {result}')\"", "final_check")

if __name__ == "__main__":
    main()
