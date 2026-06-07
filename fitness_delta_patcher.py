"""
fitness_delta_patcher.py - 两次基线 diff + 最弱格补丁

基于 run_fitness_baseline.py 写入的 fitness.json，
对比上次基线与本次基线，输出四格涨跌，
然后对真最弱格生成定向补丁脚本。

Usage:
    python fitness_delta_patcher.py              # 跑 diff + 补丁
    python fitness_delta_patcher.py --diff-only   # 仅 diff
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
FITNESS_PATH = REPO_ROOT / "fitness.json"
PREV_BASELINE_KEY = "previous_baseline"  # 保留上次基线用于 diff


def load_fitness():
    if not FITNESS_PATH.exists():
        print(f"⚠ fitness.json 不存在，先跑基线：python run_fitness_baseline.py")
        return None
    with open(FITNESS_PATH) as f:
        return json.load(f)


def save_fitness(data):
    with open(FITNESS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def do_diff(current: dict) -> dict:
    """对比上次基线与当前基线，返回涨跌"""
    prev = current.get("previous_baseline") or {}
    dims_curr = current.get("dimensions", {})
    dims_prev = prev.get("dimensions", {})

    result = {}
    for dim_name in ["arena", "boundaryeval", "regression", "canary"]:
        curr_d = dims_curr.get(dim_name, {})
        prev_d = dims_prev.get(dim_name, {})

        curr_pass = curr_d.get("passed", 0)
        curr_total = curr_d.get("total", 1)
        prev_pass = prev_d.get("passed", 0)
        prev_total = prev_d.get("total", 1)

        curr_rate = curr_pass / max(curr_total, 1)
        prev_rate = prev_pass / max(prev_total, 1)

        delta_pass = curr_pass - prev_pass
        delta_rate = curr_rate - prev_rate

        result[dim_name] = {
            "prev_pass": prev_pass,
            "prev_total": prev_total,
            "prev_rate": prev_rate,
            "curr_pass": curr_pass,
            "curr_total": curr_total,
            "curr_rate": curr_rate,
            "delta_pass": delta_pass,
            "delta_rate": delta_rate,
        }
    return result


def print_diff(diff: dict):
    print("\n" + "=" * 60)
    print("📊 基线 diff（上次 vs 本次）")
    print("=" * 60)
    header = f"{'格子':15s} {'上次':>8s} {'本次':>8s} {'涨跌':>8s} {'上次率':>8s} {'本次率':>8s} {'率涨跌':>8s}"
    print(header)
    print("-" * 75)

    weakest = None
    weakest_rate = 1.0

    for dim_name, d in diff.items():
        prev_str = f"{d['prev_pass']}/{d['prev_total']}"
        curr_str = f"{d['curr_pass']}/{d['curr_total']}"
        delta_str = f"{d['delta_pass']:+d}"
        prev_rate_str = f"{d['prev_rate']:.1%}"
        curr_rate_str = f"{d['curr_rate']:.1%}"
        delta_rate_str = f"{d['delta_rate']:+.1%}"

        marker = ""
        if d["curr_rate"] < weakest_rate:
            weakest_rate = d["curr_rate"]
            weakest = dim_name
            marker = " ◀◀◀ 真最弱"

        print(f"{dim_name:15s} {prev_str:>8s} {curr_str:>8s} {delta_str:>8s} {prev_rate_str:>8s} {curr_rate_str:>8s} {delta_rate_str:>8s}{marker}")

    print("-" * 75)

    # 涨跌汇总
    up = [k for k, v in diff.items() if v["delta_pass"] > 0]
    down = [k for k, v in diff.items() if v["delta_pass"] < 0]
    same = [k for k, v in diff.items() if v["delta_pass"] == 0]

    if up:
        print(f"  ↑ 涨格: {', '.join(up)}")
    if down:
        print(f"  ↓ 跌格: {', '.join(down)}")
    if same:
        print(f"  → 平格: {', '.join(same)}")

    print(f"\n📌 真最弱格: 「{weakest}」({weakest_rate:.1%})")
    return weakest, weakest_rate


def generate_patch(weakest: str, weakest_rate: float, diff: dict) -> str:
    """为最弱格生成补丁脚本"""
    d = diff[weakest]

    if weakest == "canary":
        # canary 是最难的，直接套 75 补丁
        script = f'''"""
canary_brainonly_fix_{weakest}.py - 定向补丁 for {weakest}
自动生成:  真最弱格 {weakest} (通过率 {d["curr_rate"]:.1%})
上次基线: {d["prev_pass"]}/{d["prev_total"]} ({d["prev_rate"]:.1%})
本次基线: {d["curr_pass"]}/{d["curr_total"]} ({d["curr_rate"]:.1%})
涨跌: {d["delta_pass"]:+d} 分
"""
import sys
sys.path.insert(0, ".")

from canary_75_real_weld import run_canary_weld

if __name__ == "__main__":
    run_canary_weld()
'''
    else:
        # 其他格子用 brainonly_replay 靶向
        script = f'''"""
brainonly_fix_{weakest}.py - 定向补丁 for {weakest}
自动生成:  真最弱格 {weakest} (通过率 {d["curr_rate"]:.1%})
上次基线: {d["prev_pass"]}/{d["prev_total"]} ({d["prev_rate"]:.1%})
本次基线: {d["curr_pass"]}/{d["curr_total"]} ({d["curr_rate"]:.1%})
涨跌: {d["delta_pass"]:+d} 分
"""
import sys
sys.path.insert(0, ".")

from brainonly_replay import run_replay

if __name__ == "__main__":
    run_replay(target="{weakest}")
'''
    return script


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--diff-only", action="store_true")
    args = parser.parse_args()

    data = load_fitness()
    if not data:
        sys.exit(1)

    # 如果还没有 previous_baseline，把当前 baseline 当作上次（首次运行）
    if "previous_baseline" not in data:
        print("ℹ 首次运行：把当前基线存档为「上次基线」")
        data["previous_baseline"] = {
            "timestamp": data.get("baseline", {}).get("timestamp", "unknown"),
            "dimensions": data.get("dimensions", {}),
        }
        save_fitness(data)
        print("已保存，下次再跑会做真正的 diff")
        return 0

    # 做 diff
    diff = do_diff(data)
    weakest, weakest_rate = print_diff(diff)

    if args.diff_only:
        return 0

    # 生成补丁
    patch_script = generate_patch(weakest, weakest_rate, diff)
    patch_name = f"patch_{weakest}.py"
    patch_path = REPO_ROOT / patch_name

    with open(patch_path, "w") as f:
        f.write(patch_script)

    print(f"\n🩹 补丁已生成: {patch_name}")
    print(f"   执行: python {patch_name}")

    # 把当前基线存档为下次 diff 的「上次」
    data["previous_baseline"] = {
        "timestamp": data.get("baseline", {}).get("timestamp", "unknown"),
        "dimensions": data.get("dimensions", {}),
    }
    save_fitness(data)

    return 0


if __name__ == "__main__":
    sys.exit(main())
