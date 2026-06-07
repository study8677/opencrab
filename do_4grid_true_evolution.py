"""
总控：跑基线 → 找最弱 → brain-only 焊链 → 涨则 commit / 不涨写账
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

print("=" * 70)
print("🦀 4格真进化循环")
print("=" * 70)

# Step 1: 跑基线
print("\n[Step 1] 跑真基线...")
import run_4grid_true_baseline_exec as rb
results, weakest = rb.main()
if not weakest:
    print("❌ 找不到最弱格，退出")
    sys.exit(1)

print(f"\n最弱格是: {weakest} = {results[weakest]['score']}%")

# Step 2: brain-only 焊链
print(f"\n[Step 2] 对 {weakest} 做 brain-only 焊链...")
import do_4grid_brainonly_weld as dw
dw.main()

print("\n✅ 循环完成")
