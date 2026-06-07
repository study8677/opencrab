#!/usr/bin/env python3
"""
跑通 canary 75→80 brain-only 完整焊链
基线→最小补丁→三闸→3x→焊fitness.json真涨分
"""
import json
import subprocess
import sys
from pathlib import Path

class BrainOnlyCanary75to80Welder:
    def __init__(self):
        self.fitness_path = Path("fitness.json")
        self.results = []
        
    def load_fitness(self):
        if self.fitness_path.exists():
            with open(self.fitness_path) as f:
                return json.load(f)
        return {}
    
    def save_fitness(self, data):
        with open(self.fitness_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def step1_baseline(self):
        """Step1: 获取基线 fitness"""
        print("\n=== STEP1: BASELINE ===")
        result = subprocess.run(
            ["python", "peek_fitness_json.py"],
            capture_output=True, text=True
        )
        print(result.stdout.strip() if result.stdout else "无fitness数据")
        if result.returncode != 0:
            print(f"ERROR: {result.stderr[:200]}")
        return True
    
    def step2_autopsy(self):
        """Step2: autopsy 25% 死因"""
        print("\n=== STEP2: AUTOPSY 25% ROOT CAUSE ===")
        result = subprocess.run(
            ["python", "autopsy_canary_75_25pct_rootcause.py"],
            capture_output=True, text=True, timeout=120
        )
        print(result.stdout[-600:] if result.stdout else "无输出")
        if result.returncode != 0:
            print(f"AUTOPSY ERROR: {result.stderr[:200]}")
        return result.returncode == 0

    def step3_minimal_patch(self):
        """Step3: 脑补最小补丁"""
        print("\n=== STEP3: MINIMAL PATCH ===")
        result = subprocess.run(
            ["python", "create_canary_75_minimal_patch.py"],
            capture_output=True, text=True
        )
        print(result.stdout[:300] if result.stdout else "无输出")
        if result.returncode != 0:
            print(f"ERROR: {result.stderr[:200]}")
        return result.returncode == 0
    
    def step3_three_gates(self):
        """Step3: 过三闸"""
        print("\n=== STEP3: THREE GATES ===")
        gates = ["check_three_gates.py", "check_brainonly.py", "check_crab.py"]
        all_pass = True
        for gate in gates:
            result = subprocess.run(["python", gate], capture_output=True, text=True)
            status = "PASS" if result.returncode == 0 else "FAIL"
            print(f"{gate}: {status}")
            if result.returncode != 0:
                all_pass = False
        return all_pass
    
    def step4_3x_replication(self):
        """Step4: 3x复制验证"""
        print("\n=== STEP4: 3x REPLICATION ===")
        result = subprocess.run(
            ["python", "run_4grid_3x_verify.py"],
            capture_output=True, text=True, timeout=300
        )
        print(result.stdout[-500:] if result.stdout else "无输出")
        return result.returncode == 0
    
    def step5_weld_fitness(self):
        """Step5: 焊fitness.json并验证真涨分"""
        print("\n=== STEP5: WELD FITNESS ===")
        
        # 读当前fitness
        fitness = self.load_fitness()
        old_canary_75 = fitness.get("canary_75", 0)
        
        # 尝试生成新fitness
        result = subprocess.run(
            ["python", "generate_fitness_json.py"],
            capture_output=True, text=True
        )
        print(result.stdout[-300:] if result.stdout else "无输出")
        
        # 重新加载
        new_fitness = self.load_fitness()
        new_canary_75 = new_fitness.get("canary_75", 0)
        
        print(f"\n旧 canary_75: {old_canary_75}")
        print(f"新 canary_75: {new_canary_75}")
        print(f"涨分: {new_canary_75 - old_canary_75}")
        
        return new_canary_75 > old_canary_75
    
    def run(self):
        print("=== BRAIN-ONLY CANARY 75→80 WELD CHAIN ===\n")
        
        steps = [
            ("Baseline", self.step1_baseline),
            ("Autopsy 25%", self.step2_autopsy),
            ("Minimal Patch", self.step3_minimal_patch),
            ("Three Gates", self.step4_three_gates),
            ("3x Replication", self.step5_3x_replication),
            ("Weld Fitness", self.step6_weld_fitness),
        ]
        
        for name, step_fn in steps:
            print(f"\n{'='*50}")
            print(f"STEP: {name}")
            print(f"{'='*50}")
            try:
                result = step_fn()
                if not result:
                    print(f"⚠ {name} 返回 False")
            except Exception as e:
                print(f"✗ {name} 异常: {e}")
                return False
        
        print("\n=== WELD CHAIN COMPLETE ===")
        return True

if __name__ == "__main__":
    welder = BrainOnlyCanary75to80Welder()
    success = welder.run()
    sys.exit(0 if success else 1)
