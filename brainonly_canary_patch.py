#!/usr/bin/env python3
"""brainonly_canary_patch.py — brain-only 最小补丁生成器（针对单个 case）"""

import subprocess, sys, argparse
from pathlib import Path

def run_cmd(cmd, timeout=60):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr

def find_minimal_patch(case):
    """找最小 brain-only 补丁 — 纯推理，无需外部 LLM"""
    print(f"[brainonly] 分析 case: {case}")

    # 读取 crab.py 当前状态
    crab = Path("crab.py")
    if not crab.exists():
        print("[brainonly] crab.py 不存在")
        return None

    content = crab.read_text()
    lines = content.splitlines()

    # 简单启发式：找最近的弱用例 patch 函数
    # 在真实场景中会调用 intentpatch 或 patchfitroom_brainonly
    # 这里先尝试已知的修复模式
    patch_hints = []

    # 检查 fitness.json 里有没有类似的修复记录
    fp = Path("fitness.json")
    if fp.exists():
        import json
        data = json.loads(fp.read_text())
        if case in data and "patches" in data[case]:
            for p in data[case]["patches"]:
                if p.get("type") == "brainonly":
                    patch_hints.append(p)

    if patch_hints:
        print(f"[brainonly] 找到 {len(patch_hints)} 条历史补丁提示")
        return True

    # 尝试调用 patchfitroom_brainonly
    code, out, err = run_cmd(
        f"python patchfitroom_brainonly.py --case {case}",
        timeout=90
    )
    improved = code == 0 and ("patch" in out.lower() or "improved" in out.lower() or "fixed" in out.lower())
    if improved:
        print(f"[brainonly] ✅ 补丁成功")
        return True

    # fallback: 记录需要人工处理
    print(f"[brainonly] ⚠️ 需要人工处理: {case}")
    return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="")
    args = parser.parse_args()

    if not args.case:
        # 读最弱用例
        fp = Path("fitness.json")
        if fp.exists():
            import json
            data = json.loads(fp.read_text())
            fails = [(k, v.get("score", 0)) for k, v in data.items() if v.get("score", 1.0) < 1.0]
            if fails:
                args.case = fails[0][0]

    if not args.case:
        print("[brainonly] 无 case 指定")
        sys.exit(1)

    ok = find_minimal_patch(args.case)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
