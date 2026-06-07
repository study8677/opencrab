"""
4-Grid Evolvability Analysis: arena / boundaryeval / regression / canary
每个格子的最小可下刀点 + 预估单拍涨分概率
"""
import json
from pathlib import Path

# 当前 fitness.json 基线
FITNESS_FILE = Path("fitness.json")
BASE_SCORES = {}
if FITNESS_FILE.exists():
    try:
        BASE_SCORES = json.loads(FITNESS_FILE.read_text())
    except:
        BASE_SCORES = {}

print("=" * 60)
print("四格权衡分析 - 最小可下刀点")
print("=" * 60)

GRID = {
    "arena": {
        "module": "arena.py",
        "min_cut": "run_arena_single_round() - 单轮评估看分差",
        "dependency": "projects/*.py + evalbench",
        "last_score": BASE_SCORES.get("arena", "N/A"),
        "single_shot_prob": 0.25,
        "why": "改动最小，但 arena 只测不修，涨分靠其他格子"
    },
    "boundaryeval": {
        "module": "boundaryeval.py",
        "min_cut": "run_boundaryeval_with_delta() - 单边界差分测试",
        "dependency": "evalbench + crab.py",
        "last_score": BASE_SCORES.get("boundaryeval", "N/A"),
        "single_shot_prob": 0.15,
        "why": "boundaryeval 只测边界case，修不修看运气"
    },
    "regression": {
        "module": "regression.py",
        "min_cut": "run_regression_with_evidence() - 已知弱项打补丁",
        "dependency": "weakest_cell + patchfitroom",
        "last_score": BASE_SCORES.get("regression", "N/A"),
        "single_shot_prob": 0.45,
        "why": "regression 跑已知弱项，修复后直接验证，涨分概率最高"
    },
    "canary": {
        "module": "canary.py",
        "min_cut": "run_canary_75_real_weld() - 75%场景焊死修复",
        "dependency": "autopsy + patchcourse + 3-gate",
        "last_score": BASE_SCORES.get("canary", "N/A"),
        "single_shot_prob": 0.60,
        "why": "canary 75%是最成熟闭环，端到端真验证"
    }
}

for name, info in GRID.items():
    print(f"\n【{name.upper()}】")
    print(f"  模块: {info['module']}")
    print(f"  最小刀口: {info['min_cut']}")
    print(f"  依赖链: {info['dependency']}")
    print(f"  当前分: {info['last_score']}")
    print(f"  单拍涨分概率: {info['single_shot_prob']:.0%}")
    print(f"  理由: {info['why']}")

print("\n" + "=" * 60)
print("决策: 挑 canary 格子 (概率60%)")
print("=" * 60)
print("""
理由:
1. canary_75_real_weld.py 已是最成熟闭环
2. 端到端: autopsy → patchcourse → 3-gate → 3x → fitness.json
3. 75%场景覆盖，焊死修复后直接真涨分
4. 之前尸检、定位、gitignore、garden各做各的 - 今天焊全链

下一步: 运行 canary_75_real_weld.py 完整闭环
""")

# 保存决策
with open("4grid_decision.json", "w") as f:
    json.dump({
        "chosen": "canary",
        "probability": 0.60,
        "rationale": "canary_75_real_weld 是最成熟闭环，端到端真验证"
    }, f, indent=2)

print("决策已保存到 4grid_decision.json")
