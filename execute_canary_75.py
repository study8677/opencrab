#!/usr/bin/env python3
"""
execute_canary_75.py

对最弱格 canary 75% 下刀的核心执行器：
1. 找挂的 case
2. readpack 圈最小修面
3. brain-only 出补丁
4. 过三闸并入
5. canary 真分涨

不需要跑三遍基线，直接动手。
"""

import subprocess
import json
import sys
import os
from pathlib import Path

def log(msg):
    print(f"[canary_75] {msg}")

def run_cmd(cmd, timeout=60):
    """运行命令"""
    log(f"Running: {cmd}")
    try:
        result = subprocess.run(
            cmd if isinstance(cmd, list) else cmd.split(),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=isinstance(cmd, str)
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1

def step1_find_weakest():
    """找最弱的 case"""
    log("STEP 1: 找最弱的 canary 75% case")
    
    # 方式1: reproduce_canary_3x
    stdout, stderr, rc = run_cmd("python reproduce_canary_3x.py")
    
    # 解析失败
    failures = []
    for line in stdout.split('\n'):
        if 'test_' in line and 'FAILED' in line:
            # 提取 test name
            parts = line.split('::')
            if len(parts) > 1:
                test = parts[-1].split('[')[0].strip()
                failures.append(test)
    
    # 方式2: 直接运行测试
    if not failures:
        stdout, stderr, rc = run_cmd("python -m pytest tests/test_canary.py -v --tb=line 2>&1")
        for line in stdout.split('\n'):
            if 'FAILED' in line and 'test_' in line:
                failures.append(line.strip())
    
    log(f"找到 {len(failures)} 个失败的 case")
    return failures

def step2_readpack(case):
    """readpack 圈最小修面"""
    log(f"STEP 2: readpack for {case}")
    
    # 尝试运行 readpack
    stdout, stderr, rc = run_cmd(f"python readpack.py --case {case}")
    
    # 解析 patch 信息
    patch_info = {
        'file': None,
        'function': None,
        'line': None,
        'patch': None,
    }
    
    in_patch = False
    patch_lines = []
    
    for line in stdout.split('\n'):
        if 'PATCH_START' in line:
            in_patch = True
            continue
        if 'PATCH_END' in line:
            in_patch = False
            continue
        if in_patch:
            try:
                data = json.loads(line)
                patch_info.update(data)
            except:
                pass
        if 'file' in line.lower() or 'File:' in line:
            patch_info['file'] = line.split(':')[-1].strip()
        if 'patch' in line.lower() and ':' in line:
            patch_info['patch'] = line.split(':', 1)[-1].strip()
    
    log(f"readpack 结果: {patch_info}")
    return patch_info

def step3_brainonly(case, patch_info):
    """brain-only 出补丁"""
    log(f"STEP 3: brainonly patch for {case}")
    
    # 构建命令
    cmd = f"python brainonly_canary_patch.py --case {case}"
    if patch_info.get('file'):
        cmd += f" --file {patch_info['file']}"
    if patch_info.get('function'):
        cmd += f" --function {patch_info['function']}"
    if patch_info.get('line'):
        cmd += f" --line {patch_info['line']}"
    
    stdout, stderr, rc = run_cmd(cmd)
    
    # 解析 patch
    patch = None
    in_code = False
    code_lines = []
    
    for line in stdout.split('\n'):
        if 'PATCH_CODE_START' in line:
            in_code = True
            continue
        if 'PATCH_CODE_END' in line:
            in_code = False
            patch = '\n'.join(code_lines)
            continue
        if in_code:
            code_lines.append(line)
    
    if not patch:
        patch = stdout  # fallback
    
    log(f"brainonly 生成 patch 长度: {len(patch)}")
    return patch

def step4_three_gates():
    """过三闸"""
    log("STEP 4: 过三闸")
    
    stdout, stderr, rc = run_cmd("python check_three_gates_canary.py")
    
    # 解析结果
    gates = {}
    overall = False
    
    for line in stdout.split('\n'):
        for gate in ['gate1', 'gate2', 'gate3', 'Gate 1', 'Gate 2', 'Gate 3']:
            if gate in line:
                if 'PASS' in line:
                    gates[gate.lower().replace(' ', '').replace('gate ', 'gate')] = True
                elif 'FAIL' in line:
                    gates[gate.lower().replace(' ', '').replace('gate ', 'gate')] = False
        if 'Overall' in line or 'overall' in line:
            if 'PASS' in line:
                overall = True
            elif 'FAIL' in line:
                overall = False
    
    log(f"三闸结果: {gates}, overall={overall}")
    return overall, gates

def step5_merge():
    """并入"""
    log("STEP 5: 并入")
    
    # 尝试运行并入
    stdout, stderr, rc = run_cmd("python run_canary_evolution.py --merge")
    
    merged = 'MERGED' in stdout or rc == 0
    log(f"并入结果: {'成功' if merged else '失败'}")
    return merged

def step6_verify():
    """验证 canary 真分涨"""
    log("STEP 6: 验证 canary 真分涨")
    
    # 检查 fitness
    stdout, stderr, rc = run_cmd(
        "python -c \"from check_fitness_json import check_fitness; print(check_fitness())\""
    )
    
    score = None
    for line in stdout.split('\n'):
        if 'canary' in line.lower() or 'score' in line.lower():
            log(f"  {line}")
            # 尝试提取数字
            import re
            nums = re.findall(r'\d+\.?\d*', line)
            if nums:
                score = float(nums[0])
    
    return score

def main():
    print("\n" + "="*70)
    print("CANARY 75% EVOLUTION - 对最弱格下刀")
    print("="*70)
    
    # Step 1: 找最弱
    failures = step1_find_weakest()
    
    if not failures:
        log("没有找到失败的 case，检查当前 fitness...")
        score = step6_verify()
        if score is not None:
            log(f"当前 canary 分数: {score}")
            if score >= 75:
                log("canary 已经在 75% 或以上!")
                return 0
            else:
                log(f"canary 分数 {score}% < 75%，需要优化")
                # 尝试其他方式找弱点
                failures = ["canary_75_weak"]
    
    # 处理每个失败
    for case in failures[:2]:
        print(f"\n--- 处理 case: {case} ---")
        
        # Step 2: readpack
        patch_info = step2_readpack(case)
        
        # Step 3: brainonly
        patch = step3_brainonly(case, patch_info)
        
        # Step 4: 三闸
        passed, gates = step4_three_gates()
        
        if passed:
            # Step 5: 并入
            merged = step5_merge()
            if merged:
                log(f"✓ case {case} 已并入")
        else:
            log(f"✗ case {case} 三闸未通过: {gates}")
    
    # Step 6: 验证
    score = step6_verify()
    
    print("\n" + "="*70)
    print("EVOLUTION COMPLETE")
    print("="*70)
    
    if score is not None:
        log(f"最终 canary 分数: {score}%")
        if score >= 75:
            log("✓ canary 真分涨到 75% 或以上!")
            return 0
    
    log("需要继续优化")
    return 1

if __name__ == "__main__":
    sys.exit(main())
