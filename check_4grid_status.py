"""
快速检查4格状态 - 哪个格子最值得下刀
"""
import json
from pathlib import Path

def main():
    print("=" * 60)
    print("4格状态检查")
    print("=" * 60)
    
    # 读取 fitness.json
    fitness = {}
    if Path("fitness.json").exists():
        fitness = json.loads(Path("fitness.json").read_text())
    
    # 读取4grid决策
    decision = {}
    if Path("4grid_decision.json").exists():
        decision = json.loads(Path("4grid_decision.json").read_text())
    
    print(f"\nfitness.json: {fitness}")
    print(f"\n决策: {decision}")
    
    # 各格子状态
    for name in ["arena", "boundaryeval", "regression", "canary"]:
        score = fitness.get(name, "N/A")
        chosen = decision.get("chosen") == name
        print(f"  {name}: {score} {'← 已选' if chosen else ''}")
    
    # 检查闭环日志
    if Path("4grid_closed_loop.json").exists():
        closed = json.loads(Path("4grid_closed_loop.json").read_text())
        print(f"\n闭环历史: {closed.get('闭环成功', False)}")
        print(f"最终canary: {closed.get('final_canary', 'N/A')}")

if __name__ == "__main__":
    main()
