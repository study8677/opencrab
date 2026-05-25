#!/usr/bin/env python3
"""统一健康验证入口 🩺🪞🔥 —— 一条命令把启动前的体检全跑一遍。

opencrab 的健康验证一度散在多处，各看一层、各有各的报告格式：
  · `probe.py`    依赖与外部工具够不够得着 + 配置一致不一致(解释器/标准库/
    git/执行器/第三方包；.env 缺键/孤儿键/数值/版本) —— 原 envcheck 已并入此处；
  · `checkup.py`  整只螃蟹健不健康(文件/语法/导入/结构/仓库完整性)；
  · `smoke.py`    README 教的命令今天还真跑不跑得起来。

三个入口各自能跑很好，但「进化前照一次镜子」要敲三条命令、读三份报告，
最分散也最容易漏跑。这里把它们收敛成一个入口，按「由底向上」的顺序串起来：
能不能跑/配置对不对(probe) → 整体健不健康(checkup) → 文档真不真(smoke)，
最后给一份合并结论。原来的几条命令**原样保留**，谁想单看哪一层仍可直接敲。

用法:
    python health.py                # 全跑一遍，按层打印 + 合并结论
    python health.py --quiet        # 只在有问题时说话(适合钩子 / CI)
    python health.py --strict       # 把 probe 的 warn 也视作未过
    python health.py probe          # 只跑某一层(probe/checkup/smoke)
    python health.py checkup --strict   # 子命令同样接受 --quiet/--strict

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

# ── 各层共用的诊断原语 ───────────────────────────────────────────────
# probe / envcheck 一度各抄一份 Finding / _ok-_warn-_err / summarize / _MARK，
# checkup / envcheck 又各抄一份 .env 解析与数值/枚举校验表。重复=漂移的温床。
# 这里把它们收成唯一真相源；旧入口 `from health import ...` 取用、对外仍原样可见
# (cap_probe.summarize / cap_envcheck.summarize 经由各自模块取，故仍成立)。
# 关键约束：这些定义必须排在下面 import checkup/probe/... 之前——
# 否则跑 `python health.py` 时，被它导入的 probe 反过来 `from health import Finding`
# 会撞上「health 还没定义到这里」的半成品模块，触发循环导入。
OK, WARN, ERROR = "ok", "warn", "error"
_MARK = {OK: "✅", WARN: "⚠️", ERROR: "❌"}

# .env 里需要「能解析成数字」的配置(键 -> 解析器)，填错了心跳一启动就崩。
NUMERIC_ENV = {
    "OPENCRAB_TICK_SECONDS": int,
    "OPENCRAB_DAILY_ENERGY": int,
    "OPENCRAB_MOLT_EVERY": int,
    "OPENCRAB_HAND_BUDGET_USD": float,
}
# .env 里只能取有限几个值的配置(键 -> 合法集合)。
ENUM_ENV = {
    "OPENCRAB_AUTONOMY": {"journal", "propose", "merge", "publish"},
    "OPENCRAB_EXECUTOR": {"claude", "codex"},
}


@dataclasses.dataclass(frozen=True)
class Finding:
    """一条诊断发现：是什么、够不够得着/对不对、(若不对)怎么修。"""
    level: str        # ok / warn / error
    label: str        # 检查项名
    detail: str = ""  # 现状一句话
    fix: str = ""     # 可操作的修复建议(仅 warn/error 有意义)

    @property
    def passed(self) -> bool:
        return self.level == OK

    def to_meta(self) -> dict:
        return {"level": self.level, "label": self.label,
                "detail": self.detail, "fix": self.fix}


def _ok(label: str, detail: str = "") -> Finding:
    return Finding(OK, label, detail)


def _warn(label: str, detail: str, fix: str) -> Finding:
    return Finding(WARN, label, detail, fix)


def _err(label: str, detail: str, fix: str) -> Finding:
    return Finding(ERROR, label, detail, fix)


def summarize(findings: list[Finding], *, strict: bool = False) -> tuple[bool, int, int]:
    """归总：(是否健康, error 数, warn 数)。strict 下 warn 也算未过。"""
    errors = sum(1 for f in findings if f.level == ERROR)
    warns = sum(1 for f in findings if f.level == WARN)
    healthy = errors == 0 and (warns == 0 if strict else True)
    return healthy, errors, warns


def parse_env_file(path: pathlib.Path) -> dict[str, str]:
    """把一个 .env 风格文件解析成 dict(与 crab.py 同款极简解析，零依赖)。"""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        # 顺手剥掉行内注释(# 前需有空格，避免误伤值里的 #)
        out[key.strip()] = val.split(" #", 1)[0].strip()
    return out


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
