#!/usr/bin/env python3
"""上手向导 🛬 —— 把「新贡献者 10 分钟跑起来」从一句口号变成一条**可验证**的路径。

为什么要有它：领地里已经有一排向**自己**看的层——checkup 照镜子、smoke 验 README
的命令真能跑、envcheck 校配置一致性。它们都在答「我自己还健不健康」，却没人替
**外人**走一遍那条最关键的路：一个素未谋面的人，照着 README 敲下去，到底能不能在
十分钟内从「git clone」走到「我亲手让这只螃蟹心跳了一次」？外人能顺利用起来，才是
真进步——一个谁都跑不起来的项目，再自洽也是孤岛。

文档会撒谎：它说「零依赖、敲两行就能跑」，可真相只有**亲手按顺序跑一遍**才知道。
本向导把那条上手路拆成几道**关卡**，按新人会遇到的先后顺序排好，逐道亲自验证：

  · 🐍 Python 够新吗      —— 版本低于约定，后面全白搭,先拦在最前
  · 📦 真的零依赖吗      —— 核心模块纯标准库就 import 得动,不需要先 pip 装东西
  · 🪞 起点干净吗        —— checkup.py 跑得起来且报健康(CONTRIBUTING 的第一步)
  · 🔥 命令没漂移吗      —— README 教的关键命令今天还原样在、还跑得通(借 smoke)
  · 🦀 能亲手心跳一次吗  —— 最后一关:照 README 让它在梦境模式下 `--once` 活一次

每道关卡都带三样东西,缺一不可:一句**它在验什么**、一个**预算分钟数**(累计不超 10
分钟才算「十分钟上手」名副其实)、以及一句**没过时怎么办的提示**——不是甩一句「失败」,
而是直接告诉新人「大概率是这里、这样修」。第一道没过就停:上手路是有顺序的,Python
都不对,后面的关卡跑了也是徒增噪音。

用法:
    python onboarding.py            # 走一遍上手路,逐关验证 + 累计耗时(退出码 0=畅通 / 1=有卡点)
    python onboarding.py --quiet    # 只在有卡点时说话(适合接进 CI / 钩子,守住「外人跑得起来」)
    python onboarding.py --list     # 只列出有哪些关卡与预算(不执行)
    python onboarding.py --json     # 机读:导出每关结论、耗时与提示

零第三方依赖,纯标准库。向导是观测者:只读地走一遍路,绝不写 journal / state,
最后那关在仓库的临时副本里跑 `--once`,副作用全落在临时目录、跑完即弃,绝不弄脏真实领地。
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
README = REPO_ROOT / "README.md"

_PY = sys.executable

# 「十分钟上手」不是修辞:所有关卡的预算分钟数累加必须 ≤ 这个数,否则名不副实。
TIME_BUDGET_MIN = 10

# 约定的最低 Python 版本(README 徽章写的是 3.8+)。
MIN_PY = (3, 8)

# 跑子进程时强制梦境模式:空 key=绝不真打大脑、空白名单=回到默认能力集,
# 让「跑不跑得起来」只取决于代码本身,而非本机 .env。与 smoke.py 同源。
_DREAM_ENV = {
    "OPENCRAB_API_KEY": "",
    "OPENCRAB_CAPABILITIES": "",
    "PYTHONIOENCODING": "utf-8",
}

# 复制临时副本时跳过:版本库、运行期记忆、缓存、真实 .env(免得把真 key 带进去)。
_COPY_IGNORE = shutil.ignore_patterns(".git", "state", "__pycache__", ".env", "*.pyc")


def _run(argv: list[str], cwd: pathlib.Path, timeout: int = 120) -> tuple[int, str]:
    """在 cwd 下按梦境模式跑一条命令,返回 (退出码, 合并的 stdout+stderr)。"""
    env = {**os.environ, **_DREAM_ENV}
    try:
        proc = subprocess.run(argv, cwd=str(cwd), env=env,
                              capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout + proc.stderr
    except Exception as e:   # 命令本身起不来,也是一种「新人会撞上的卡点」
        return -1, f"<执行异常> {e!r}"


def _run_isolated(argv: list[str], timeout: int = 120) -> tuple[int, str]:
    """把领地复制进临时目录再跑——有副作用的命令(如 `--once` 写 journal)全落在临时目录,跑完即弃。"""
    with tempfile.TemporaryDirectory(prefix="opencrab-onboard-") as tmp:
        sandbox = pathlib.Path(tmp) / "repo"
        shutil.copytree(REPO_ROOT, sandbox, ignore=_COPY_IGNORE)
        return _run(argv, sandbox, timeout=timeout)


# ── 每道关卡的检查逻辑:返回 (是否通过, 一句细节) ────────────────────────────
def _check_python(_: argparse.Namespace) -> tuple[bool, str]:
    cur = sys.version_info[:2]
    if cur >= MIN_PY:
        return True, f"Python {cur[0]}.{cur[1]}（≥ {MIN_PY[0]}.{MIN_PY[1]}）"
    return False, f"当前 Python {cur[0]}.{cur[1]}，低于约定的 {MIN_PY[0]}.{MIN_PY[1]}"


def _check_zero_deps(_: argparse.Namespace) -> tuple[bool, str]:
    """核心模块能纯标准库 import 起来——验证「零依赖」不是口号,不必先 pip 装东西。"""
    probe = "import crab, hands, checkup; print('ok')"
    code, out = _run([_PY, "-c", probe], REPO_ROOT, timeout=60)
    if code == 0 and "ok" in out:
        return True, "crab / hands / checkup 纯标准库即可导入"
    tail = out.strip().splitlines()[-1][:160] if out.strip() else "(无输出)"
    return False, f"导入失败：{tail}"


def _check_checkup(_: argparse.Namespace) -> tuple[bool, str]:
    """CONTRIBUTING 的第一步:checkup.py 跑得起来且报健康——起点干净,归因才清楚。"""
    code, out = _run([_PY, "checkup.py", "--quiet"], REPO_ROOT, timeout=90)
    if code == 0:
        return True, "checkup.py --quiet 全过（领地起点干净）"
    tail = out.strip().splitlines()[-1][:160] if out.strip() else "(无输出)"
    return False, f"自检没过（退出码 {code}）：{tail}"


def _check_smoke(_: argparse.Namespace) -> tuple[bool, str]:
    """借 smoke.py 验 README 教的关键命令今天还原样在、还跑得通——文档没对新人撒谎。"""
    code, out = _run([_PY, "smoke.py", "--quiet"], REPO_ROOT, timeout=180)
    if code == 0:
        return True, "smoke.py --quiet 全过（README 命令没漂移、真能跑）"
    tail = out.strip().splitlines()[-1][:160] if out.strip() else "(无输出)"
    return False, f"烟雾测试没过（退出码 {code}）：{tail}"


def _check_first_heartbeat(_: argparse.Namespace) -> tuple[bool, str]:
    """最后一关:照 README 让它在梦境模式下 `--once` 亲手心跳一次(临时副本里跑,不弄脏领地)。"""
    code, out = _run_isolated([_PY, "crab.py", "--once"], timeout=180)
    if code == 0 and "沉淀完毕" in out:
        return True, "python crab.py --once 走完一次心跳（醒来 → 沉淀完毕）"
    if code == 0:
        return True, "python crab.py --once 退出码 0（未见「沉淀完毕」，但已跑通）"
    tail = out.strip().splitlines()[-1][:160] if out.strip() else "(无输出)"
    return False, f"心跳没跑通（退出码 {code}）：{tail}"


@dataclasses.dataclass
class Gate:
    """上手路上的一道关卡:验什么、预算几分钟、没过时怎么办。

    `budget_min` 是给新人的**心理预期**(这步大概花多久),所有关卡累加须 ≤ 10 分钟,
    才对得起「十分钟上手」。`hint` 在没过时直接给出最可能的原因与修法——
    向导的价值不在于报「失败」,而在于让卡住的人知道下一步该做什么。
    """
    name: str
    icon: str
    summary: str                                       # 这关在验什么(一句话)
    budget_min: float                                  # 预算分钟数(累计 ≤ 10)
    check: "callable"                                  # (args) -> (ok, detail)
    hint: str                                          # 没过时的修复提示


GATES = [
    Gate("python", "🐍", "Python 版本够新（≥ 3.8）", 0.5, _check_python,
         f"装一个 ≥ {MIN_PY[0]}.{MIN_PY[1]} 的 Python；用 pyenv / 系统包管理器切换后重试。"),
    Gate("zero-deps", "📦", "核心模块纯标准库即可导入", 1.0, _check_zero_deps,
         "本项目零第三方依赖，不该需要 pip 装东西。报错多半是 Python 太旧或仓库不完整——"
         "先确认上一关通过、并完整 clone 了仓库。"),
    Gate("checkup", "🪞", "领地起点干净（checkup 报健康）", 2.0, _check_checkup,
         "跑 `python checkup.py` 看完整报告，按 ❌ 那几项的细节先把现有问题修好，"
         "别在带病的领地上叠新改动（见 CONTRIBUTING 第一步）。"),
    Gate("smoke", "🔥", "README 命令没漂移、真能跑", 3.5, _check_smoke,
         "跑 `python smoke.py` 看哪条示例红了：要么 README 与命令对不上(文档漂移)，"
         "要么命令本身跑不通——按提示让二者重新对齐。"),
    Gate("heartbeat", "🦀", "能亲手让它心跳一次（--once）", 3.0, _check_first_heartbeat,
         "照 README「唤醒它」一节跑 `python crab.py --once`（没填 key 也能跑，走梦境模式）；"
         "若报错，先回头确认前几关都已通过。"),
]


@dataclasses.dataclass
class Outcome:
    """一道关卡的结论:过没过、一句细节、实际耗时(秒)。"""
    gate: Gate
    ok: bool
    detail: str
    elapsed_s: float

    def to_meta(self) -> dict:
        return {"name": self.gate.name, "summary": self.gate.summary,
                "ok": self.ok, "detail": self.detail,
                "budget_min": self.gate.budget_min,
                "elapsed_s": round(self.elapsed_s, 1),
                "hint": None if self.ok else self.gate.hint}


@dataclasses.dataclass
class Report:
    outcomes: list[Outcome]
    stopped_at: Gate | None    # 在哪一关停下(第一道没过即停);None=全程畅通

    @property
    def ok(self) -> bool:
        return self.stopped_at is None

    @property
    def elapsed_s(self) -> float:
        return sum(o.elapsed_s for o in self.outcomes)


def walk(args: argparse.Namespace) -> Report:
    """按顺序走一遍上手路:逐关验证,第一道没过就停——上手路是有顺序的,前面塌了后面没意义。"""
    outcomes: list[Outcome] = []
    stopped_at: Gate | None = None
    for gate in GATES:
        t0 = time.monotonic()
        try:
            ok, detail = gate.check(args)
        except Exception as e:   # 关卡本身炸了也算没过,但绝不让它带崩整条向导
            ok, detail = False, f"<关卡异常> {e!r}"
        outcomes.append(Outcome(gate, ok, detail, time.monotonic() - t0))
        if not ok:
            stopped_at = gate
            break
    return Report(outcomes=outcomes, stopped_at=stopped_at)


def manifest() -> dict:
    """导出纯数据:走一遍上手路的每关结论、累计耗时与卡点提示(给 CI / 机读)。"""
    report = walk(argparse.Namespace())
    return {
        "ok": report.ok,
        "time_budget_min": TIME_BUDGET_MIN,
        "planned_min": round(sum(g.budget_min for g in GATES), 1),
        "elapsed_s": round(report.elapsed_s, 1),
        "stopped_at": report.stopped_at.name if report.stopped_at else None,
        "gates": [o.to_meta() for o in report.outcomes],
    }


def _print_list() -> None:
    planned = sum(g.budget_min for g in GATES)
    print(f"🛬 上手关卡（预算合计 {planned:.0f} 分钟 / 上限 {TIME_BUDGET_MIN} 分钟）：\n")
    for g in GATES:
        print(f"  {g.icon} {g.name}（约 {g.budget_min:.1f} 分钟）— {g.summary}")
    if planned > TIME_BUDGET_MIN:
        print(f"\n  ⚠️  预算合计 {planned:.0f} 分钟已超 {TIME_BUDGET_MIN} 分钟上限——该给关卡瘦身了。")


def _print_report(report: Report) -> None:
    print("🛬 opencrab 上手向导 —— 外人 10 分钟跑得起来吗\n")
    for o in report.outcomes:
        mark = "✅" if o.ok else "❌"
        print(f"  {mark} {o.gate.icon} {o.gate.name} — {o.detail}（{o.elapsed_s:.1f}s）")
    print()
    if report.ok:
        print(f"🦀 上手路畅通：{len(report.outcomes)} 道关卡全过，"
              f"实测约 {report.elapsed_s:.0f} 秒——外人照 README 能顺利跑起来。")
    else:
        g = report.stopped_at
        print(f"⚠️  上手路卡在「{g.icon} {g.name}」——外人到这步会跑不动，先修好这处。")
        print(f"   💡 {g.hint}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 上手向导 🛬")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quiet", action="store_true",
                   help="只在有卡点时说话（适合接进 CI / 钩子）")
    g.add_argument("--list", action="store_true", help="只列出有哪些关卡与预算（不执行）")
    g.add_argument("--json", action="store_true", help="导出机读：每关结论、耗时与提示")
    args = ap.parse_args(argv)

    if args.list:
        _print_list()
        return

    if args.json:
        import json
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        sys.exit(0)

    report = walk(args)

    if not (args.quiet and report.ok):
        if args.quiet:
            # 静默模式只在卡住时开口,直接给最关键的一句 + 提示。
            g = report.stopped_at
            print(f"🛬 上手路卡在「{g.icon} {g.name}」：{report.outcomes[-1].detail}")
            print(f"   💡 {g.hint}")
        else:
            _print_report(report)

    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
