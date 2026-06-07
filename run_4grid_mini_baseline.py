"""
运行选定格子的最小 baseline
4grid: 挑 canary 格子 → 跑 baseline → 脑补 → 三闸 → 3x → 焊全链
"""
import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime

FITNESS_FILE = Path("fitness.json")
LOG_FILE = Path("4grid_mini_baseline_log.json")

def load_fitness():
    if FITNESS_FILE.exists():
        return json.loads(FITNESS_FILE.read_text())
    return {}

def save_fitness(data):
    FITNESS_FILE.write_text(json.dumps(data, indent=2))

def run_step(cmd, desc):
    print(f"\n>>> {desc}")
    print(f"    cmd: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"    stdout: {result.stdout[:200] if result.stdout else 'N/A'}")
    print(f"    stderr: {result.stderr[:200] if result.stderr else 'N/A'}")
    return result.returncode == 0

def main():
    print("=" * 60)
    print("4格权衡 → canary格子 → 全链闭环")
    print("=" * 60)
    
    log = {
        "start": datetime.now().isoformat(),
        "chosen": "canary",
        "steps": []
    }
    
    # Step 1: 读当前基线
    fitness_before = load_fitness()
    canary_before = fitness_before.get("canary", "N/A")
    print(f"\n[1] 基线: canary={canary_before}")
    log["steps"].append({"step": "baseline", "canary": canary_before})
    
    # Step 2: 运行 canary_75_real_weld 完整闭环
    # 这是最可能单拍涨分的格子
    success = run_step(
        "python canary_75_real_weld.py",
        "Step 2: canary_75_real_weld - 完整闭环"
    )
    log["steps"].append({"step": "canary_weld", "success": success})
    
    if success:
        # Step 3: 验证 fitness.json 涨分
        fitness_after = load_fitness()
        canary_after = fitness_after.get("canary", "N/A")
        print(f"\n[3] 结果: canary={canary_after}")
        log["steps"].append({"step": "verify", "canary": canary_after})
        
        if canary_after != canary_before:
            delta = f"{canary_before} → {canary_after}"
            print(f"\n✅ 涨分确认: {delta}")
            log["delta"] = delta
            log["success"] = True
        else:
            print(f"\n❌ 未涨分: {canary_after}")
            log["success"] = False
    else:
        print("\n❌ canary_weld 失败，尝试降级到 regression")
        # 降级: regression格子
        success = run_step(
            "python regression.py",
            "Step 2b: regression - 降级备选"
        )
        log["steps"].append({"step": "regression_fallback", "success": success})
    
    log["end"] = datetime.now().isoformat()
    LOG_FILE.write_text(json.dumps(log, indent=2))
    print(f"\n日志: {LOG_FILE}")
    
    return 0 if log.get("success") else 1

if __name__ == "__main__":
    sys.exit(main())
