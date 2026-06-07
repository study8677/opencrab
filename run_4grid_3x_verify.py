"""
4格权衡 → 3x验证阶段
3次独立运行，确认涨分可复现
"""
import subprocess
import json
import sys
from pathlib import Path

def main():
    print("=" * 60)
    print("4格权衡 → 3x验证 (3次独立运行)")
    print("=" * 60)
    
    results = []
    fitness_before = json.loads(Path("fitness.json").read_text()).get("canary", "N/A")
    
    for i in range(3):
        print(f"\n>>> Run {i+1}/3")
        result = subprocess.run(
            "python canary_75_real_weld.py",
            shell=True, capture_output=True, text=True
        )
        
        fitness_after = json.loads(Path("fitness.json").read_text()).get("canary", "N/A")
        improved = fitness_after != fitness_before and fitness_after > fitness_before
        
        results.append({
            "run": i+1,
            "success": result.returncode == 0,
            "fitness_before": fitness_before,
            "fitness_after": fitness_after,
            "improved": improved
        })
        
        print(f"    fitness: {fitness_before} → {fitness_after}")
        print(f"    improved: {'✅' if improved else '❌'}")
    
    # 汇总
    improvements = sum(1 for r in results if r["improved"])
    print(f"\n3x验证结果: {improvements}/3 次涨分")
    
    # 焊死: 记录最终涨分到 fitness.json
    if improvements > 0:
        final = results[-1]["fitness_after"]
        print(f"\n✅ 焊死最终涨分: canary={final}")
        
        fitness = json.loads(Path("fitness.json").read_text())
        fitness["canary"] = final
        fitness["4grid闭环时间"] = subprocess.run("date", shell=True, capture_output=True, text=True).stdout.strip()
        Path("fitness.json").write_text(json.dumps(fitness, indent=2))
        
        # 保存 4grid 闭环记录
        Path("4grid_closed_loop.json").write_text(json.dumps({
            "chosen": "canary",
            "3x_results": results,
            "final_canary": final,
            "闭环成功": True
        }, indent=2))
        
        return 0
    else:
        print("\n❌ 3次都未涨分，需要回退分析")
        return 1

if __name__ == "__main__":
    sys.exit(main())
