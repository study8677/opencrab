#!/usr/bin/env python3
"""garden_audit — garden 巡园结果 × heat×trust 低价值 × retirement_drill 验证。

用法:
    python garden_audit.py              # 巡园 + 排序 + 验证
    python garden_audit.py --dry-run    # 只列候选，不实际调用 retirement_drill
    python garden_audit.py --min-effort 中   # 只看工时>=中的候选
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import json
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# ── 尝试导入领地内部数据源 ────────────────────────────────────────────
def _load_heat_map() -> dict[str, float]:
    """从 usageheat.py 的输出里捞 heat 数据（返回 0.0 表示查不到）。"""
    try:
        # usageheat 有一个 --json 选项吗？试试看
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "usageheat.py"), "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            return {m["module"]: m.get("heat", 0.0) for m in data.get("modules", [])}
    except Exception:
        pass
    return {}


def _load_trust_map() -> dict[str, float]:
    """从 trustscore.py 的输出里捞 trust 数据（返回 0.5 表示查不到）。"""
    try:
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "trustscore.py"), "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            return {m["module"]: m.get("trust", 0.5) for m in data.get("modules", [])}
    except Exception:
        pass
    return {}


def _call_retirement_drill(module: str) -> tuple[bool, str]:
    """对单个模块调用 retirement_drill，返回 (有替代路径?, 原因)。"""
    try:
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "retirement_drill.py"), module],
            capture_output=True, text=True, timeout=60,
        )
        out = r.stdout + r.stderr
        # retirement_drill 退出码 0 = 找到替代路径
        has_alt = (r.returncode == 0)
        # 尝试从输出里抓一行摘要
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        summary = lines[-1] if lines else ("通过" if has_alt else "无替代")
        return has_alt, summary
    except Exception as e:
        return False, f"钻探失败: {e}"


def _heat_trust_score(module: str, heat_map: dict, trust_map: dict) -> float:
    """heat × (1 - trust)：越高表示越值得审视（低价值、低信任）。"""
    h = heat_map.get(module, 0.0)
    t = trust_map.get(module, 0.5)
    return h * (1.0 - t)


def _run_garden() -> list[dict]:
    """调用 garden.py --json 拿原始养护小单。"""
    try:
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "garden.py"), "--json"],
            capture_output=True, text=True, timeout=60,
        )
        if r.stdout.strip():
            return json.loads(r.stdout).get("chores", [])
    except Exception as e:
        print(f"[WARN] garden.py 调用失败: {e}", file=sys.stderr)
    return []


def _module_from_target(target: str) -> str:
    """从 chore target 提取模块名。"""
    # "foo.py::bar" → "foo"   "foo.py:12" → "foo"
    m = re.match(r"([a-zA-Z_]\w*)\.py(?:::\w+|:)", target)
    if m:
        return m.group(1)
    # 整个 target 当模块名试试（doc 类）
    base = pathlib.Path(target).stem
    if base and base != "garden_audit":
        return base
    return ""


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="garden × heat×trust × retirement_drill 审计")
    ap.add_argument("--dry-run", action="store_true", help="只列候选，不验证替代路径")
    ap.add_argument("--min-effort", choices=["小", "中"], default=None,
                    help="只看指定工时档以上的候选")
    ap.add_argument("--top", type=int, default=5, help="最多列几个候选（默认 5）")
    args = ap.parse_args(argv)

    print("🌱 garden_audit: 静态巡园 + 价值评分 + 替代路径钻探")
    print("─" * 60)

    # 1. 静态巡园
    chores = _run_garden()
    if not chores:
        print("⚠️  garden.py 没扫到任何养护小单（或调用失败）")
        sys.exit(0)

    # 2. 加载 heat / trust
    heat_map = _load_heat_map()
    trust_map = _load_trust_map()
    print(f"  heat 数据: {len(heat_map)} 模块")
    print(f"  trust 数据: {len(trust_map)} 模块")

    # 3. 为每个 chore 算分 + 过滤
    scored: list[dict] = []
    for c in chores:
        module = _module_from_target(c["target"])
        if not module or module == "garden_audit":
            continue
        effort = c.get("effort", "小")
        if args.min_effort == "中" and effort == "小":
            continue
        score = _heat_trust_score(module, heat_map, trust_map)
        scored.append({**c, "_module": module, "_score": score})

    # 4. 按 score 降序排（最高分 = 最值得审视）
    scored.sort(key=lambda x: x["_score"], reverse=True)
    candidates = scored[: args.top]

    if not candidates:
        print("⚠️  没有符合条件的候选（可能是 heat/trust 数据太少）")
        sys.exit(0)

    print(f"\n📋 低 heat × 低 trust 候选（共 {len(candidates)} 个，score 越高越可疑）：\n")

    results: list[dict] = []
    for i, c in enumerate(candidates, 1):
        module = c["_module"]
        score = c["_score"]
        kind_icon = {"todo": "🏷️", "orphan": "🧟", "entry": "🕸️", "doc": "📜"}.get(c["kind"], "❓")
        print(f"  {i}. {kind_icon} [{c['target']}]  工时:{c['effort']}  "
              f"heat×(1-trust)={score:.4f}")
        print(f"       现状：{c['detail']}")
        print(f"       验收：{c['accept']}")

        if args.dry_run:
            print(f"       → [DRY] 不验证替代路径")
        else:
            has_alt, reason = _call_retirement_drill(module)
            status = "✅ 有替代路径" if has_alt else "🚫 未找到替代"
            print(f"       → retirement_drill: {status}  ({reason})")
            results.append({
                "target": c["target"],
                "module": module,
                "kind": c["kind"],
                "score": score,
                "has_alt": has_alt,
                "drill_reason": reason,
                "verdict": "可删除" if has_alt else "暂保留",
            })
        print()

    # 5. 总结
    if not args.dry_run and results:
        deletable = [r for r in results if r["has_alt"]]
        print("─" * 60)
        print(f"✅ 可安全删除（已证替代路径）: {len(deletable)} 个")
        for r in deletable:
            print(f"   - {r['target']}  score={r['score']:.4f}")
        kept = [r for r in results if not r["has_alt"]]
        print(f"🚫 暂保留（无替代路径）: {len(kept)} 个")
        for r in kept:
            print(f"   - {r['target']}  score={r['score']:.4f}")

        if deletable:
            print("\n⚠️  真正要删时，用 git rm 配合 commit——别让瘦身变假行空。")
            sys.exit(0)
        else:
            print("\n📭 没有找到有替代路径的候选，一棵草也别拔。")
            sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
