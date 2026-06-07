#!/usr/bin/env python3
"""do_real_fitness_baseline.py — 跑真实 fitness 基线，返回原始分数"""

import subprocess, json, sys
from pathlib import Path

def run_cmd(cmd, timeout=300):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr

def main():
    print("[基线] 运行 evalbench 真实基线...")
    code, out, err = run_cmd("python evalbench.py --baseline", timeout=600)
    print(out[-3000:] if len(out) > 3000 else out)
    if err:
        print("[stderr]", err[-1000:])

    # 尝试解析 JSON 输出
    scores = {}
    try:
        import re, json
        # 找 JSON 块
        for m in re.finditer(r'\{[^{}]*"score"[^{}]*\}', out):
            try:
                obj = json.loads(m.group())
                if "case" in obj or "name" in obj:
                    k = obj.get("case") or obj.get("name")
                    v = obj.get("score", 0.0)
                    scores[k] = v
            except:
                pass
    except Exception as e:
        print(f"[解析] JSON解析失败: {e}")

    if not scores:
        # fallback: 读现有 fitness.json
        fp = Path("fitness.json")
        if fp.exists():
            raw = json.loads(fp.read_text())
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(v, dict):
                        scores[k] = v.get("score", 0.0)
                    else:
                        scores[k] = float(v)

    print(f"[基线] 共 {len(scores)} 条记录")
    for k, v in sorted(scores.items(), key=lambda x: x[1])[:20]:
        icon = "✅" if v >= 1.0 else "❌"
        print(f"  {icon} {k}: {v:.3f}")
    return scores

if __name__ == "__main__":
    main()
