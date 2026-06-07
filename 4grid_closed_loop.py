"""
4格权衡 → 全链闭环主控
baseline → 脑补 → 三闸 → 3x → 焊全链
"""
import subprocess
import json
import sys
from pathlib import Path

def step(name, cmd):
    print(f"\n{'='*60}")
    print(f"STEP: {name}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"returncode: {result.returncode}")
    if result.stdout:
        print(f"stdout: {result.stdout[:300]}")
    if result.stderr:
        print(f"stderr: {result.stderr[:300]}")
    return result.returncode == 0

def main():
    print("="*60)
    print("4格权衡 → 全链闭环")
    print("="*60)
    
    log = {"steps": [], "success": False}
    
    # Step 0: 决策
    print("\n[决策] 挑 canary 格子 (概率60%)")
    log["steps"].append({"name": "decision", "chosen": "canary"})
    
    # Step 1: baseline
    fitness_before = json.loads(Path("fitness.json").read_text()).get("canary", "N/A")
    print(f"\n[基线] canary={fitness_before}")
    log["steps"].append({"name": "baseline", "canary": fitness_before})
    
    # Step 2: 脑补 (检查依赖)
    ok = step("brainonly_check", "python run_4grid_mini_brainonly.py")
    log["steps"].append({"name": "brainonly", "ok": ok})
    
    # Step 3: canary_weld 主体
    ok = step("canary_weld", "python canary_75_real_weld.py")
    log["steps"].append({"name": "canary_weld", "ok": ok})
    
    if not ok:
        # 降级: regression
        print("\n[降级] canary失败，尝试regression")
        ok = step("regression_fallback", "python regression.py")
        log["steps"].append({"name": "regression", "ok": ok})
    
    # Step 4: 三闸
    ok = step("3gate", "python run_4grid_3gate.py")
    log["steps"].append({"name": "3gate", "ok": ok})
    
    # Step 5: 3x验证
    ok = step("3x_verify", "python run_4grid_3x_verify.py")
    log["steps"].append({"name": "3x_verify", "ok": ok})
    
    # Step 6: 验证最终涨分
    fitness_after = json.loads(Path("fitness.json").read_text()).get("canary", "N/A")
    improved = fitness_after != fitness_before and fitness_after > fitness_before
    
    print(f"\n{'='*60}")
    print(f"最终结果: {fitness_before} → {fitness_after}")
    print(f"{'✅ 涨分焊死!' if improved else '❌ 未涨分'}")
    print(f"{'='*60}")
    
    log["steps"].append({"name": "final", "before": fitness_before, "after": fitness_after})
    log["success"] = improved
    
    # 保存日志
    Path("4grid_closed_loop_log.json").write_text(json.dumps(log, indent=2))
    
    return 0 if improved else 1

if __name__ == "__main__":
    sys.exit(main())
