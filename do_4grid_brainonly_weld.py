"""
对最弱格做 brain-only 焊链
"""
import subprocess, sys, json
from pathlib import Path

REPO_ROOT = Path(__file__).parent
STATE_DIR = REPO_ROOT / "state"

def load_baseline():
    fp = STATE_DIR / "4grid_true_baseline.json"
    if not fp.exists():
        print(f"⚠️  {fp} 不存在，先跑基线")
        sys.exit(1)
    return json.loads(fp.read_text())

def run_brainonly(grid: str) -> dict:
    """跑 brainonly 并返回前后分数"""
    # 加载基线分数
    baseline = load_baseline()
    before_score = baseline["results"].get(grid, {}).get("score")

    # 调用对应的 brainonly 脚本
    mod_map = {
        "arena":        "brainonly_benefit_review",
        "boundaryeval": "brainonly_external_validation",
        "regression":   "brainonly_blindfix_regression",
        "canary":       "brainonly_canary_patch",
    }
    mod = mod_map.get(grid, "brainonly_benefit_review")

    print(f"🧠 跑 brainonly: {mod} (grid={grid})")
    r = subprocess.run([sys.executable, "-m", mod], capture_output=True, text=True, cwd=REPO_ROOT)
    print(r.stdout[:500])
    if r.stderr:
        print(f"STDERR: {r.stderr[:200]}")

    # 重新跑基线获取新分数
    import run_4grid_true_baseline_exec as rb
    rb_results, _ = rb.main()
    after_score = rb_results.get(grid, {}).get("score")

    delta = None
    if before_score is not None and after_score is not None:
        delta = round(after_score - before_score, 1)

    return {"before": before_score, "after": after_score, "delta": delta}

def write_blocker(grid: str, msg: str):
    fp = REPO_ROOT / "state" / "项目账.md"
    entry = f"\n## {grid} 卡点 @{__import__('datetime').datetime.now().isoformat()}\n\n{msg}\n"
    fp.write_text(fp.read_text() + entry if fp.exists() else f"# 项目账\n{entry}")
    print(f"📝 写入卡点到 {fp}")

def main():
    baseline = load_baseline()
    weakest = baseline.get("weakest")
    if not weakest:
        print("⚠️ 没有找到最弱格")
        return

    print(f"\n{'='*60}")
    print(f"🔧 对 {weakest} 做 brain-only 焊链")
    print(f"{'='*60}")

    result = run_brainonly(weakest)
    print(f"\n结果: before={result['before']}% → after={result['after']}% (delta={result['delta']}%)")

    if result["delta"] is not None and result["delta"] > 0:
        print(f"✅ 涨了 {result['delta']}%！准备 commit...")
        # 简单 commit
        subprocess.run(["git", "add", "-A"], cwd=REPO_ROOT)
        subprocess.run(["git", "commit", "-m", f"brainonly weld {weakest} +{result['delta']}%"], cwd=REPO_ROOT)
        print("✅ 已 commit")
    else:
        print(f"⚠️ 没涨，写卡点")
        write_blocker(weakest, f"brainonly 焊链后 delta={result['delta']}%，未涨。\nstdout: {result.get('stdout','')}")

if __name__ == "__main__":
    main()
