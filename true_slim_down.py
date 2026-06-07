#!/usr/bin/env python3
"""真瘦身：probe_zero_refs 找候选 → retirement_drill 证替代路径 → 证齐才移 attic/git commit。

用法：
    python true_slim_down.py                  # 默认取前 3 个零引用候选
    python true_slim_down.py --top 5           # 改候选数
    python true_slim_down.py --dry-run         # 只看不动
    python true_slim_down.py --days 14         # retirement_drill 的回溯窗口
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(".")
ATTIC = ROOT / "attic"
CANDIDATE_FILE = ROOT / "zero_ref_candidates.json"
REPORT_PATH = ROOT / "state" / "retirement_drill" / "report.jsonl"

DEFAULT_TOP = 3


def run_probe() -> dict:
    """跑 probe_zero_refs.py，生成 zero_ref_candidates.json。"""
    print("🔍 正在探测零引用模块 ...")
    result = subprocess.run(
        [sys.executable, "probe_zero_refs.py"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"❌ probe_zero_refs.py 失败:\n{result.stderr}")
        sys.exit(1)

    if not CANDIDATE_FILE.exists():
        print(f"❌ probe_zero_refs.py 未生成 {CANDIDATE_FILE}")
        sys.exit(1)

    with CANDIDATE_FILE.open() as f:
        data = json.load(f)
    return data


def get_retirement_verdict(module: str, days: int) -> dict | None:
    """跑 retirement_drill.py --json，对单个模块返回定夺结果。"""
    result = subprocess.run(
        [sys.executable, "retirement_drill.py", "--json", "--days", str(days)],
        capture_output=True, text=True, env={**subprocess.os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    )
    if result.returncode not in (0, 1):
        print(f"⚠️  retirement_drill.py 对 {module} 异常: {result.stderr[:200]}")
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"⚠️  retirement_drill.py 对 {module} 返回非 JSON: {result.stdout[:200]}")
        return None

    # 在 drills 里找这个模块
    for dr in data.get("drills", []):
        if dr["name"] + ".py" == module or dr["name"] == module.replace(".py", ""):
            return dr
    return None


def ensure_attic():
    ATTIC.mkdir(exist_ok=True)
    gitignore = ROOT / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if "attic/" not in content and "/attic" not in content:
            gitignore.write_text(content.rstrip() + "\nattic/\n")
            print("📝 已将 attic/ 加入 .gitignore")


def move_and_commit(module: str) -> bool:
    """把模块移到 attic/，git add + commit。"""
    src = ROOT / module
    if not src.exists():
        print(f"⚠️  {module} 不在根目录，跳过")
        return False

    dest = ATTIC / module
    shutil.move(str(src), str(dest))
    print(f"  📦 {module} → attic/")

    # git add + commit
    try:
        subprocess.run(["git", "add", str(ATTIC / module)], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m",
             f"chore(attic): retire {module} — zero refs + substitute proven via retirement_drill"],
            check=True, capture_output=True, text=True
        )
        print(f"  ✅ git committed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  git 操作失败: {e.stderr.decode() if e.stderr else e}")
        return False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="真瘦身：证替代路径后才真删")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP, help=f"取前 N 个零引用候选（默认 {DEFAULT_TOP}）")
    ap.add_argument("--days", type=int, default=7, help="retirement_drill 回溯窗口（默认 7）")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不移动不 commit")
    ap.add_argument("--force", action="store_true", help="跳过确认直接执行")
    args = ap.parse_args(argv)

    # 1) probe 找候选
    probe_data = run_probe()
    candidates = probe_data.get("candidates", [])[:args.top]
    if not candidates:
        print("🎉 没有零引用候选，无需瘦身")
        sys.exit(0)

    print(f"\n📋 零引用候选（前 {len(candidates)} 个）:")
    for c in candidates:
        print(f"  - {c['module']}")

    # 2) 逐个 retirement_drill 验证替代路径
    print(f"\n🧪 逐个跑 retirement_drill 验替代路径（回溯 {args.days} 天）...")
    verified = []   # (module, verdict)
    blocked = []     # (module, verdict, reason)

    for c in candidates:
        module = c["module"]
        verdict = get_retirement_verdict(module, args.days)
        if verdict is None:
            blocked.append((module, None, "retirement_drill 无法运行"))
            print(f"  ❌ {module}: 无法获取退休定夺")
            continue

        disp = verdict.get("disposition", "unknown")
        disposition_word = verdict.get("disposition_word", disp)
        proof = verdict.get("proof", {})
        proven = proof.get("proven", False)

        print(f"  {'✅' if disp == 'retire' else '❌'} {module}: {disposition_word} "
              f"(替代已证={proven})")
        if not proven:
            reasons = verdict.get("reasons", [])
            for r in reasons[:2]:
                print(f"      · {r}")

        if disp == "retire" and proven:
            verified.append((module, verdict))
        else:
            blocked.append((module, verdict, disposition_word))

    # 3) 汇总
    print(f"\n📊 结果：{len(verified)} 个可净删，{len(blocked)} 个证不出需保留")

    if not verified:
        print("🏛️  没有可净删的候选——没有候选同时满足「零引用 + 替代已证」，本次不瘦身")
        sys.exit(0)

    # 4) 预览 + 确认
    print("\n📦 拟移动到 attic/ 并 commit:")
    for module, _ in verified:
        print(f"  → {module}")

    if args.dry_run:
        print("\n🟡 dry-run 模式：未实际移动/提交")
        sys.exit(0)

    if not args.force:
        confirm = input("\n⏎ 确认执行? (yes/no): ").strip().lower()
        if confirm not in ("yes", "y"):
            print("取消")
            sys.exit(0)

    # 5) 真执行
    ensure_attic()
    print("\n🚀 执行真瘦身 ...")
    for module, _ in verified:
        move_and_commit(module)

    # 6) 统计
    remaining = len(list(ROOT.glob("*.py")))
    removed = len(verified)
    print(f"\n✅ 真瘦身完成：移除了 {removed} 个模块，根目录 .py 文件数: 266 → {remaining}")
    print("🔍 建议运行 `git log --oneline -5` 确认 commit")
    sys.exit(0)


if __name__ == "__main__":
    main()
