#!/usr/bin/env python3
"""统一回归验证链 🧪🛤️ —— 一条命令把「防退化」的两道防线一起跑完。

opencrab 防退化一度散在两处，各看一层、各有各的报告：
  · `goldens.py`    回归快照：把关键命令的标准输出/错误/退出码固化成黄金样本，
                    逐字比对，专抓「命令还能跑、退出码还是 0，可输出已经变味」；
  · `goldenpath.py` 黄金路径：在临时副本里把核心生命线端到端跑一遍
                    (自检→启动+心跳→审计落盘→回放→失败分流)，专抓
                    「单测都绿、串起来却断了」的接缝退化。

两道防线同属「防退化」家族，但要敲两条命令、读两份报告，最容易漏跑其一。
这里把它们收敛成一个入口，按「由细到粗」的顺序串起来：
单命令快照(goldens) → 端到端生命线(goldenpath)，最后给一份合并结论。
原来的两条命令**原样保留**，谁想单看哪一层仍可直接敲。

用法:
    python regression.py            # 两层都跑一遍，按层打印 + 合并结论
    python regression.py --quiet    # 只在有回归时说话(适合钩子 / CI)
    python regression.py --update   # 确认当前行为正确后，(重新)录制两层的黄金样本
    python regression.py snapshot   # 只跑某一层(snapshot/path)
    python regression.py path --update

退出码：0 = 每一层都无回归；1 = 任意一层有回归/漂移/未录。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import goldenpath
import goldens


@dataclasses.dataclass
class Layer:
    """一层回归验证的归一化结论：跑哪层、过没过、一句话现状、多行明细。"""
    key: str          # 子命令名(snapshot/path)
    title: str        # 报告标题
    ok: bool
    summary: str      # 一句话结论
    detail: str       # 多行明细(每行一项)


def _run_snapshot() -> Layer:
    v = goldens.verify()
    lines: list[str] = []
    for name in v.passed:
        lines.append(f"  ✅ {name}")
    for name in v.missing:
        lines.append(f"  ⚪ {name} — 还没有黄金样本(先跑 python goldens.py --update)")
    for name in v.regressed:
        lines.append(f"  ❌ {name} — 行为变了：")
        lines += ["       " + line for line in v.diffs[name]]
    if v.ok:
        summary = f"{len(v.passed)}/{v.total} 条用例行为与样本一致"
    else:
        bits = []
        if v.regressed:
            bits.append(f"{len(v.regressed)} 条回归")
        if v.missing:
            bits.append(f"{len(v.missing)} 条未录")
        summary = "、".join(bits)
    return Layer("snapshot", "🧪 回归快照 · 单命令逐字比对", v.ok, summary, "\n".join(lines))


def _run_path() -> Layer:
    v = goldenpath.verify()
    lines: list[str] = []
    for st in v.stages:
        lines.append(f"  {'✅' if st.ok else '❌'} {st.label}")
        lines.append(f"       {st.detail}")
        if st.name in v.diffs:
            lines.append(f"       ↳ 指纹漂移：{v.diffs[st.name]}")
    if v.missing_golden:
        summary = "还没有黄金指纹(先跑 python goldenpath.py --update)"
        # 链已跑断时按未过收尾；仅缺指纹但链通畅，视作「待录」也算未过。
        ok = False
    elif v.ok:
        summary = f"{len(v.stages)} 段全部接得上，且与黄金指纹一致"
        ok = True
    else:
        bits = []
        if v.broken:
            bits.append(f"{len(v.broken)} 段跑断({', '.join(v.broken)})")
        if v.drifted:
            bits.append(f"{len(v.drifted)} 段指纹漂移({', '.join(v.drifted)})")
        summary = "；".join(bits)
        ok = False
    return Layer("path", "🛤️ 黄金路径 · 端到端必经链", ok, summary, "\n".join(lines))


# 由细到粗的顺序：先比单命令快照，再跑端到端生命线。
LAYERS = {
    "snapshot": _run_snapshot,
    "path": _run_path,
}
ORDER = ["snapshot", "path"]


def run(keys: list[str] | None = None) -> list[Layer]:
    """跑指定的几层(默认全跑)，返回归一化结论列表(某层自身炸了也收敛成未过)。"""
    keys = keys or ORDER
    out: list[Layer] = []
    for key in keys:
        runner = LAYERS[key]
        try:
            out.append(runner())
        except Exception as e:
            out.append(Layer(key, key, False, f"该层验证自身异常：{e}", ""))
    return out


def _update(keys: list[str]) -> None:
    """确认当前行为正确后，(重新)录制选定层的黄金样本。"""
    if "snapshot" in keys:
        touched = goldens.update()
        print(f"🧪 已录制 {len(touched)} 条回归快照：{', '.join(touched)}")
    if "path" in keys:
        fp = goldenpath.update()
        print(f"🛤️  已录制黄金指纹（{len(fp)} 段关键信号）")
    print("   样本写入 goldens/，记得连同改动一起提交。")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 统一回归验证链 🧪🛤️")
    ap.add_argument("layer", nargs="?", choices=ORDER,
                    help="只跑某一层(留空=全跑)")
    ap.add_argument("--update", action="store_true",
                    help="确认当前行为正确后，(重新)录制黄金样本")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有回归时输出(适合钩子 / CI)")
    args = ap.parse_args(argv)

    keys = [args.layer] if args.layer else ORDER

    if args.update:
        _update(keys)
        return

    layers = run(keys)
    clean = all(l.ok for l in layers)

    if not (args.quiet and clean):
        print("🦀 opencrab 统一回归验证\n")
        for l in layers:
            mark = "✅" if l.ok else "❌"
            print(f"{mark} {l.title} — {l.summary}")
            if l.detail:
                print(l.detail)
            print()

    if clean:
        if not args.quiet:
            print(f"🦀 无回归：{len(layers)} 层防退化验证全部通过，可以放心进化。")
    else:
        bad = [l.title for l in layers if not l.ok]
        print(f"⚠️  发现 {len(bad)} 层有回归（{'、'.join(bad)}），"
              "若改动是有意为之、确认无误后 python regression.py --update。")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
