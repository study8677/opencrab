#!/usr/bin/env python3
"""
canary_75_evolution.py

对最弱格 canary 75% 下刀：
1. reproduce_canary_3x 找挂的 case
2. readpack 圈最小修面
3. brain-only 出补丁
4. 过三闸并入
5. 让 canary 真分涨

这是真正的进化，不是跑基线。
"""

import subprocess
import json
import sys
import os
from pathlib import Path

class CanaryEvolver:
    def __init__(self):
        self.failed_cases = []
        self.patches = []
        self.results = []
    
    def run_cmd(self, cmd, desc, timeout=60):
        """运行命令"""
        print(f"\n{'='*60}")
        print(f"[{desc}]")
        print(f"{'='*60}")
        try:
            result = subprocess.run(
                cmd if isinstance(cmd, list) else cmd.split(),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=isinstance(cmd, str)
            )
            print(result.stdout)
            if result.stderr:
                print(f"STDERR: {result.stderr[:500]}")
            return result.stdout, result.returncode
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT: {desc}")
            return "", -1
    
    def step1_find_failures(self):
        """Step 1: reproduce_canary_3x 找挂的 case"""
        print("\n" + "="*70)
        print("STEP 1: reproduce_canary_3x 找挂的 case")
        print("="*70)
        
        stdout, rc = self.run_cmd("python reproduce_canary_3x.py 2>&1", "reproduce_canary_3x")
        
        in_failed_section = False
        for line in stdout.split('\n'):
            if 'FAILED_CASES_START' in line:
                in_failed_section = True
                continue
            if 'FAILED_CASES_END' in line:
                in_failed_section = False
                continue
            if in_failed_section and 'CASE:' in line:
                case = line.replace('CASE:', '').strip()
                if case:
                    self.failed_cases.append(case)
        
        for line in stdout.split('\n'):
            if 'FAILED' in line and 'test_' in line.lower():
                parts = line.split('::')
                if len(parts) > 1:
                    test_name = parts[-1].split('[')[0].strip()
                    if test_name not in self.failed_cases:
                        self.failed_cases.append(test_name)
        
        print(f"\n找到 {len(self.failed_cases)} 个失败的 case: {self.failed_cases}")
        
        if not self.failed_cases:
            print("\n没有找到失败，尝试 peek_weakest...")
            stdout, rc = self.run_cmd("python peek_weakest.py 2>&1", "peek_weakest")
            
            for line in stdout.split('\n'):
                if 'FAILED' in line:
                    self.failed_cases.append(line.strip())
        
        return len(self.failed_cases) > 0
    
    def step2_readpack(self, case):
        """Step 2: readpack 圈最小修面"""
        print(f"\n{'='*70}")
        print(f"STEP 2: readpack 圈最小修面 for {case}")
        print("="*70)
        
        stdout, rc = self.run_cmd(f"python readpack.py --case {case} 2>&1", "readpack")
        
        min_patch = None
        patch_info = {}
        
        in_patch_section = False
        for line in stdout.split('\n'):
            if 'PATCH_START' in line:
                in_patch_section = True
                continue
            if 'PATCH_END' in line:
                in_patch_section = False
                continue
            if in_patch_section:
                try:
                    data = json.loads(line)
                    patch_info.update(data)
                except:
                    pass
        
        for line in stdout.split('\n'):
            if 'minimal' in line.lower() or 'min_patch' in line.lower():
                min_patch = line.strip()
        
        return patch_info, min_patch
    
    def step3_brainonly(self, case, patch_info):
        """Step 3: brain-only 出补丁"""
        print(f"\n{'='*70}")
        print(f"STEP 3: brain-only 出补丁 for {case}")
        print("="*70)
        
        cmd = f"python brainonly_canary_patch.py --case {case}"
        
        if patch_info:
            if 'file' in patch_info:
                cmd += f" --file {patch_info['file']}"
            if 'function' in patch_info:
                cmd += f" --function {patch_info['function']}"
            if 'line' in patch_info:
                cmd += f" --line {patch_info['line']}"
        
        stdout, rc = self.run_cmd(cmd, "brainonly_patch")
        
        patch = None
        for line in stdout.split('\n'):
            if 'PATCH_CODE_START' in line:
                lines = []
                continue_line = True
            elif 'PATCH_CODE_END' in line:
                patch = '\n'.join(lines)
            elif 'continue_line' in dir() and 'lines' in dir():
                lines.append(line)
        
        return patch if 'patch' in dir() else stdout
    
    def step4_three_gates(self):
        """Step 4: 过三闸"""
        print(f"\n{'='*70}")
        print("STEP 4: 过三闸")
        print("="*70)
        
        stdout, rc = self.run_cmd("python check_three_gates_canary.py 2>&1", "three_gates")
        
        results = {}
        in_results = False
        
        for line in stdout.split('\n'):
            if 'GATE_RESULTS_START' in line:
                in_results = True
                continue
            if 'GATE_RESULTS_END' in line:
                in_results = False
                continue
            if in_results:
                try:
                    data = json.loads(line)
                    results = data
                except:
                    pass
        
        gate_status = {}
        for line in stdout.split('\n'):
            for gate in ['gate1', 'gate2', 'gate3']:
                if gate.upper() in line or gate in line:
                    if 'PASS' in line:
                        gate_status[gate] = True
                    elif 'FAIL' in line:
                        gate_status[gate] = False
        
        all_passed = all(gate_status.values()) if gate_status else False
        print(f"\n三闸结果: {gate_status}")
        print(f"Overall: {'PASS' if all_passed else 'FAIL'}")
        
        return all_passed, gate_status
    
    def step5_merge(self):
        """Step 5: 并入"""
        print(f"\n{'='*70}")
        print("STEP 5: 并入 canary")
        print("="*70)
        
        stdout, rc = self.run_cmd("python run_canary_evolution.py --merge 2>&1", "merge")
        
        return "MERGED" in stdout or rc == 0
    
    def step6_verify(self):
        """Step 6: 验证 canary 真分涨"""
        print(f"\n{'='*70}")
        print("STEP 6: 验证 canary 真分涨")
        print("="*70)
        
        stdout, rc = self.run_cmd(
            "python -c \"from check_fitness_json import check_fitness; print(check_fitness())\"",
            "fitness_check"
        )
        
        score = None
        for line in stdout.split('\n'):
            if 'canary' in line.lower() or '75' in line or 'score' in line.lower():
                print(f"  {line}")
                try:
                    import re
                    nums = re.findall(r'\d+\.?\d*', line)
                    if nums:
                        score = float(nums[0])
                except:
                    pass
        
        return score
    
    def evolve(self):
        """执行完整进化流程"""
        print("\n" + "#"*70)
        print("# CANARY 75% EVOLUTION")
        print("# 对最弱格下刀，让 canary 真分涨")
        print("#"*70)
        
        if not self.step1_find_failures():
            print("没有找到失败的 case，检查 fitness baseline...")
            self.step6_verify()
            return False
        
        for case in self.failed_cases[:2]:
            print(f"\n{'#'*70}")
            print(f"# 处理失败 case: {case}")
            print(f"{'#'*70}")
            
            patch_info, min_patch = self.step2_readpack(case)
            patch = self.step3_brainonly(case, patch_info)
            passed, gate_status = self.step4_three_gates()
            
            if passed:
                merged = self.step5_merge()
                
                if merged:
                    self.results.append({
                        'case': case,
                        'status': 'merged',
                        'gates': gate_status,
                    })
            else:
                self.results.append({
                    'case': case,
                    'status': 'blocked',
                    'gates': gate_status,
                })
                print(f"三闸未通过，继续优化...")
        
        score = self.step6_verify()
        
        print("\n" + "="*70)
        print("EVOLUTION SUMMARY")
        print("="*70)
        print(f"处理的 case: {len(self.results)}")
        for r in self.results:
            print(f"  {r['case']}: {r['status']}")
        print(f"Canary 分数: {score}")
        
        return len([r for r in self.results if r['status'] == 'merged']) > 0

def main():
    evolver = CanaryEvolver()
    success = evolver.evolve()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
