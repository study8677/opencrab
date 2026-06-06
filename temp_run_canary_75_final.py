#!/usr/bin/env python3
"""
真跑 do_canary_75_final.py，焊死 canary 75% 真缺陷
焊完看 fitness.json 是否真涨
"""
import subprocess
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def run_cmd(cmd):
    print(f"[CMD] {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0, result.stdout, result.stderr

def peek_fitness():
    """瞄一眼当前 fitness.json"""
    fp = REPO_ROOT / "fitness.json"
    if fp.exists():
        with open(fp) as f:
            data = json.load(f)
        canary = data.get("canary", "N/A")
        score = data.get("score") or data.get("pass_rate", "N/A")
        print(f"  当前 fitness.json: canary={canary}, score={score}")
        return canary
    else:
        print("  fitness.json 不存在")
        return None

def main():
    print("=" * 60)
    print("真跑 CANARY 75% 焊死流程")
    print("=" * 60)

    # 瞄一眼跑前状态
    print("\n[瞄] 跑前 fitness.json 状态:")
    before_canary = peek_fitness()

    # 真跑 do_canary_75_final.py
    print("\n[焊] 真跑 do_canary_75_final.py...")
    ok, out, err = run_cmd("python do_canary_75_final.py")
    print(f"  脚本退出码: {ok}")
    print(f"  输出:\n{out}")
    if err:
        print(f"  错误:\n{err}")

    # 瞄一眼跑后状态
    print("\n[瞄] 跑后 fitness.json 状态:")
    after_canary = peek_fitness()

    # 比对
    print("\n" + "=" * 60)
    print("结果比对")
    print("=" * 60)
    if before_canary is not None and after_canary is not None:
        try:
            before_val = float(str(before_canary).replace("%", ""))
            after_val = float(str(after_canary).replace("%", ""))
            delta = after_val - before_val
            print(f"  跑前 canary: {before_canary}")
            print(f"  跑后 canary: {after_canary}")
            print(f"  差值: {delta:+.1f}%")
            if delta > 0:
                print("  🟢 真涨了！焊枪响了！")
            elif delta == 0:
                print("  ⚪ 没涨也没跌，维持原样")
            else:
                print("  🔴 跌了！当场尸检焊枪卡哪")
        except Exception as e:
            print(f"  比对失败: {e}")
    else:
        print("  无法比对（fitness.json 不存在或状态异常）")

    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
