"""3x 复现验证 canary 补丁"""
import sys, json, subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def run_canary_and_score():
    """运行 canary 并从 fitness.json 读分数"""
    result = subprocess.run([sys.executable, "-c", """
import sys
sys.path.insert(0, ".")
from canary import Canary
c = Canary()
r = c.run()
print(r)
"""], capture_output=True, text=True, cwd=REPO_ROOT)
    print(f"canary run: {result.stdout}")
    
    fp = REPO_ROOT / "fitness.json"
    if not fp.exists():
        return None
    with open(fp) as f:
        data = json.load(f)
    return data.get("pass_rate") or data.get("score")

def verify_3x():
    scores = []
    for i in range(3):
        s = run_canary_and_score()
        scores.append(s)
        print(f"  Run {i+1}: score={s}")
    
    baseline = scores[0]
    if baseline is None:
        print("ERROR: no baseline score")
        return False
    
    all_ok = all(s is not None and s >= baseline + 1 for s in scores[1:])
    if all_ok:
        print(f"✓ 3x 验证通过: baseline={baseline}, new >= {baseline+1}")
        return True
    else:
        print(f"✗ 3x 验证失败: scores={scores}")
        return False

if __name__ == "__main__":
    ok = verify_3x()
    sys.exit(0 if ok else 1)
