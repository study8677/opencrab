"""
4格权衡 → 三闸验证阶段
Gate 1: evidence_freshness - 证据新鲜度
Gate 2: tiergate - 层级门控
Gate 3: replication_gate - 复制门控
"""
import subprocess
import json
import sys
from pathlib import Path

def run_gate(name, cmd):
    print(f"\n>>> Gate: {name}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    ok = result.returncode == 0
    print(f"    {'✅ PASS' if ok else '❌ FAIL'}")
    if result.stdout:
        print(f"    stdout: {result.stdout[:200]}")
    return ok

def main():
    print("=" * 60)
    print("4格权衡 → 三闸验证")
    print("=" * 60)
    
    gates = [
        ("Gate1: evidence_freshness", "python evidence_freshness.py"),
        ("Gate2: tiergate", "python tiergate.py"),
        ("Gate3: replication_gate", "python replication_gate.py"),
    ]
    
    results = {}
    for name, cmd in gates:
        results[name] = run_gate(name, cmd)
    
    passed = sum(1 for v in results.values() if v)
    print(f"\n三闸结果: {passed}/{len(gates)} 通过")
    
    # 保存结果
    Path("4grid_3gate_results.json").write_text(json.dumps(results, indent=2))
    
    return 0 if passed == len(gates) else 1

if __name__ == "__main__":
    sys.exit(main())
