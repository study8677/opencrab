"""临时 peek: 看 canary 75% 那 25% 怎么死的"""
import json, subprocess, sys

def peek_canary_25_death():
    # 读 fitness.json 找最弱格
    with open("fitness.json") as f:
        fit = json.load(f)
    
    # 找 canary 75% 相关条目
    canary_entries = {k:v for k,v in fit.items() if "canary" in k.lower() and "75" in k}
    
    print("=== canary 75% 条目 ===")
    for k, v in canary_entries.items():
        print(f"{k}: {v}")
    
    # 如果没有，找到最弱格
    weakest = min(fit.items(), key=lambda x: x[1].get("pass_rate", 1.0))
    print(f"\n最弱格: {weakest[0]} = {weakest[1]}")
    
    # 看看 canary_75.py 本身
    print("\n=== canary_75.py 内容 ===")
    try:
        with open("canary_75.py") as f:
            print(f.read())
    except Exception as e:
        print(f"读取失败: {e}")

if __name__ == "__main__":
    peek_canary_25_death()
