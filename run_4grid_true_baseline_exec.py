"""
跑 4 格真基线，拿真分数，写进 state/
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent
STATE_DIR = REPO_ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)

def run_module(mod_name: str) -> dict:
    """用 python -m 跑一个模块，捕获输出"""
    result = subprocess.run(
        [sys.executable, "-m", mod_name],
        capture_output=True, text=True, cwd=REPO_ROOT
    )
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}

def parse_score(stdout: str, mod_name: str) -> float | None:
    """从输出里捞分数"""
    # 尝试 JSON 格式
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("{") and '"score"' in line:
            try:
                data = json.loads(line)
                return data.get("score") or data.get("pass_rate")
            except:
                pass
        if line.startswith("{") and '"passed"' in line:
            try:
                data = json.loads(line)
                total = data.get("total", 1)
                passed = data.get("passed", 0)
                if total > 0:
                    return round(passed / total * 100, 1)
            except:
                pass
    # 尝试文本匹配
    import re
    m = re.search(r"(\d+\.?\d*)\s*(?:/|％|%)", stdout)
    if m:
        return float(m.group(1))
    # 尝试纯数字行
    for line in stdout.strip().split("\n"):
        line = line.strip().rstrip("%")
        try:
            v = float(line)
            if 0 <= v <= 100:
                return v
        except:
            pass
    return None

def main():
    print("=" * 60)
    print("🦀 跑真 4 格基线")
    print("=" * 60)

    grids = [
        ("arena",        "run_evalbench_golden_pipeline"),
        ("boundaryeval", "run_boundaryeval_fitness_baseline"),
        ("regression",   "run_fitness_baseline"),
        ("canary",       "run_canary_75_autopsy_25pct"),
    ]

    results = {}
    for grid_name, mod_name in grids:
        print(f"\n📦 跑 {grid_name} ({mod_name})...")
        r = run_module(mod_name)
        score = parse_score(r.stdout, mod_name)
        results[grid_name] = {
            "module": mod_name,
            "score": score,
            "stdout": r.stdout[:500],
            "stderr": r.stderr[:200],
        }
        status = f"✅ {score}%" if score is not None else f"⚠️ 未解析出分数"
        print(f"   {status}")

    # 找最弱（canary 除外）
    non_canary = {k: v for k, v in results.items() if k != "canary"}
    if non_canary:
        weakest = min(non_canary.items(), key=lambda x: x[1]["score"] if x[1]["score"] is not None else 999)
        weakest_name, weakest_data = weakest
        print(f"\n🐣 最弱格（canary 除外）: {weakest_name} = {weakest_data['score']}%")

    # 写 state/4grid_true_baseline.json
    ts = datetime.now().isoformat()
    out = {"timestamp": ts, "results": results, "weakest": weakest_name if non_canary else None}
    fp = STATE_DIR / "4grid_true_baseline.json"
    fp.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n📝 写入 {fp}")
    print(json.dumps(out, indent=2, ensure_ascii=False))

    return results, weakest_name if non_canary else None

if __name__ == "__main__":
    results, weakest = main()
    print(f"\n weakest={weakest}")
    sys.exit(0)
