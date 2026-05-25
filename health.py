#!/usr/bin/env python3
"""统一健康验证入口 🩺🪞🔧🔥 —— 一条命令把启动前的体检全跑一遍。

opencrab 的健康验证一度散在四处，各看一层、各有各的报告格式：
  · `probe.py`    依赖与外部工具够不够得着(解释器/标准库/git/执行器/第三方包)；
  · `envcheck.py` 配置与环境一致不一致(.env 缺键/孤儿键/数值/版本)；
  · `checkup.py`  整只螃蟹健不健康(文件/语法/导入/结构/仓库完整性)；
  · `smoke.py`    README 教的命令今天还真跑不跑得起来。

四个入口各自能跑很好，但「进化前照一次镜子」要敲四条命令、读四份报告，
最分散也最容易漏跑。这里把它们收敛成一个入口，按「由底向上」的顺序串起来：
能不能跑(probe) → 配置对不对(envcheck) → 整体健不健康(checkup) → 文档真不真(smoke)，
最后给一份合并结论。原来的四条命令**原样保留**，谁想单看哪一层仍可直接敲。

用法:
    python health.py                # 全跑一遍，按层打印 + 合并结论
    python health.py --quiet        # 只在有问题时说话(适合钩子 / CI)
    python health.py --strict       # 把 probe/envcheck 的 warn 也视作未过
    python health.py probe          # 只跑某一层(probe/env/checkup/smoke)
    python health.py env --strict   # 子命令同样接受 --quiet/--strict

退出码：0 = 每一层都过；1 = 任意一层未过。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import checkup
import envcheck
import probe
import smoke


@dataclasses.dataclass
class Layer:
    """一层健康验证的归一化结论：跑哪层、过没过、一句话现状、多行明细。"""
    key: str          # 子命令名(probe/env/checkup/smoke)
    title: str        # 报告标题
    ok: bool
    summary: str      # 一句话结论
    detail: str       # 多行明细(每行一项)


def _run_probe(strict: bool) -> Layer:
    findings = probe.run()
    healthy, errors, warns = probe.summarize(findings, strict=strict)
    summary = (f"{len(findings)} 项探测通过" + (f"（{warns} 处提醒）" if warns else "")
               if healthy else f"{errors} 处缺失")
    detail = "\n".join(_finding_line(f) for f in findings)
    return Layer("probe", "🩺 依赖与外部工具", healthy, summary, detail)


def _run_envcheck(strict: bool) -> Layer:
    findings = envcheck.run()
    healthy, errors, warns = envcheck.summarize(findings, strict=strict)
    summary = (f"{len(findings)} 项校验通过" + (f"（{warns} 处提醒）" if warns else "")
               if healthy else f"{errors} 处不一致")
    detail = "\n".join(_finding_line(f) for f in findings)
    return Layer("env", "🔧 配置与环境一致性", healthy, summary, detail)


def _run_checkup(strict: bool) -> Layer:
    healthy, results = checkup.run()
    failed = [label for ok, label, _ in results if not ok]
    summary = (f"{len(results)} 项全部通过" if healthy
               else f"{len(failed)} 处未过")
    detail = "\n".join(f"  {'✅' if ok else '❌'} {label}" + (f" — {d}" if d else "")
                       for ok, label, d in results)
    return Layer("checkup", "🪞 领地自检", healthy, summary, detail)


def _run_smoke(strict: bool) -> Layer:
    report = smoke.verify()
    failed = [o for o in report.outcomes if not o.ok]
    summary = (f"{len(report.outcomes)} 条示例都真能跑" if report.ok
               else f"{len(failed)} 条失败")
    detail = "\n".join(f"  {'✅' if o.ok else '❌'} {o.name} — {o.detail}"
                       for o in report.outcomes)
    return Layer("smoke", "🔥 README 烟雾测试", report.ok, summary, detail)


def _finding_line(f) -> str:
    """把 probe/envcheck 的 Finding 渲染成一行(含修复建议)。"""
    line = f"  {probe._MARK[f.level]} {f.label}" + (f" — {f.detail}" if f.detail else "")
    if f.fix:
        line += f"\n        ↳ 修复：{f.fix}"
    return line


# 由底向上的顺序：先确认跑得起来，再确认配置/结构/文档。
LAYERS = {
    "probe": _run_probe,
    "env": _run_envcheck,
    "checkup": _run_checkup,
    "smoke": _run_smoke,
}
ORDER = ["probe", "env", "checkup", "smoke"]


def run(keys: list[str] | None = None, *, strict: bool = False) -> list[Layer]:
    """跑指定的几层(默认全跑)，返回归一化结论列表(某层自身炸了也收敛成未过)。"""
    keys = keys or ORDER
    out: list[Layer] = []
    for key in keys:
        runner = LAYERS[key]
        try:
            out.append(runner(strict))
        except Exception as e:
            out.append(Layer(key, key, False, f"该层验证自身异常：{e}", ""))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 统一健康验证入口 🩺🪞🔧🔥")
    ap.add_argument("layer", nargs="?", choices=ORDER,
                    help="只跑某一层(留空=全跑)")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有问题时输出(适合钩子 / CI)")
    ap.add_argument("--strict", action="store_true",
                    help="把 probe/envcheck 的 warn 也视作未过")
    args = ap.parse_args(argv)

    keys = [args.layer] if args.layer else ORDER
    layers = run(keys, strict=args.strict)
    healthy = all(l.ok for l in layers)

    if not (args.quiet and healthy):
        print("🦀 opencrab 统一健康验证\n")
        for l in layers:
            mark = "✅" if l.ok else "❌"
            print(f"{mark} {l.title} — {l.summary}")
            if l.detail:
                print(l.detail)
            print()

    if healthy:
        if not args.quiet:
            print(f"🦀 健康：{len(layers)} 层验证全部通过，可以放心进化。")
    else:
        bad = [l.title for l in layers if not l.ok]
        print(f"⚠️  发现 {len(bad)} 层未过（{'、'.join(bad)}），先按上面的修复建议补齐再蜕壳。")
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
