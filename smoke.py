#!/usr/bin/env python3
"""可执行示例 + 最小烟雾测试 🔥 —— 把 README 里的关键用法变成「真能跑」的验证。

为什么要有它：checkup 看「器官还在不在」、goldens 看「输出有没有悄悄变味」，
但还缺一层最朴素的保证——**README 教人敲的那几条命令，今天还跑得起来吗？**
文档与行为最容易在不知不觉中漂移：命令改了名、子命令删了、退出码变了，
README 却还停在旧版。烟雾测试专抓这种「文档说能跑、其实早跑不了」。

它做两件事，缺一不可：
  1) 文档同步：每条示例命令必须**原样**还出现在 README 里——README 删了或改了
     名字，这里立刻红，逼着文档跟代码一起走。
  2) 真能跑：把**只读、会自己结束**的命令直接在仓库里跑一遍；把**有副作用**的
     命令（如 `crab.py --once` 会写 journal / state）放进一个临时副本里跑，
     副作用全落在临时目录、跑完即弃，绝不弄脏真实领地。

一律按「梦境模式」(空 API key) 执行，绝不会在测试时真打大脑、真花体力。
零第三方依赖，纯标准库。

用法:
    python smoke.py            # 跑全部烟雾用例，打印报告(退出码 0=全过 / 1=有失败)
    python smoke.py --quiet    # 只在有失败时说话(适合接进 git 钩子 / CI)
    python smoke.py --list     # 只列出有哪些用例(不执行)
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

REPO_ROOT = pathlib.Path(__file__).resolve().parent
README = REPO_ROOT / "README.md"

_PY = sys.executable

# 跑用例时强制的环境：空 key=梦境模式(绝不真打大脑)、空白名单=回到默认能力集，
# 让「能不能跑」只取决于代码本身，而非本机 .env。
_DREAM_ENV = {
    "OPENCRAB_API_KEY": "",
    "OPENCRAB_CAPABILITIES": "",
    "PYTHONIOENCODING": "utf-8",
}

# 复制临时副本时跳过的东西：版本库、运行期记忆、缓存、真实 .env(免得带进真 key)。
_COPY_IGNORE = shutil.ignore_patterns(".git", "state", "__pycache__", ".env", "*.pyc")


@dataclasses.dataclass
class Sample:
    """一条「可执行示例」：README 里教的某条命令，连同怎么验证它真能跑。

    `doc` 是它在 README 里的**原样文本**，用来守「文档没漂移」这道防线。
    `argv` 为空表示「只校验文档、不执行」——留给那些天生不会自己结束的命令
    (如 `python crab.py` 持续心跳)，它们无法在测试里安全跑完。
    `isolate=True` 表示命令有副作用，要在仓库的临时副本里跑，跑完即弃。
    """
    name: str
    doc: str                    # 命令在 README 里的原样文本
    argv: list[str]             # 真正执行的命令(含解释器)；[] = 只校验文档
    summary: str
    expect_exit: int = 0        # 期望的退出码
    expect_substr: str = ""     # 输出里应出现的片段(留空=不检查内容，只看退出码)
    isolate: bool = False       # True = 在临时副本里跑(命令有副作用)


SAMPLES = [
    Sample("checkup", "python checkup.py", [_PY, "checkup.py"],
           "领地自检跑得起来、报告健康", expect_substr="健康"),
    Sample("checkup-quiet", "python checkup.py --quiet", [_PY, "checkup.py", "--quiet"],
           "自检 --quiet 全过时静默、退出码 0"),
    Sample("crab-once", "python crab.py --once", [_PY, "crab.py", "--once"],
           "心跳一次能从醒来走到沉淀(在临时副本里跑)",
           expect_substr="沉淀完毕", isolate=True),
    Sample("crab-live", "python crab.py", [],
           "持续心跳(天生不结束，只校验 README 仍这么教，不执行)"),
]


def _run(argv: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    """在 cwd 下按梦境模式跑一条命令，返回 (退出码, 合并的 stdout+stderr)。"""
    env = {**os.environ, **_DREAM_ENV}
    try:
        proc = subprocess.run(argv, cwd=str(cwd), env=env,
                              capture_output=True, text=True, timeout=120)
        return proc.returncode, proc.stdout + proc.stderr
    except Exception as e:   # 命令本身起不来，也是一种「跑不起来」
        return -1, f"<执行异常> {e!r}"


def _run_isolated(argv: list[str]) -> tuple[int, str]:
    """把领地复制进一个临时目录再跑——副作用全落在临时目录，跑完即弃。"""
    with tempfile.TemporaryDirectory(prefix="opencrab-smoke-") as tmp:
        sandbox = pathlib.Path(tmp) / "repo"
        shutil.copytree(REPO_ROOT, sandbox, ignore=_COPY_IGNORE)
        return _run(argv, sandbox)


@dataclasses.dataclass
class Outcome:
    """一条用例的结论。"""
    name: str
    ok: bool
    detail: str


def _check(sample: Sample, readme_text: str) -> Outcome:
    # 1) 文档同步：命令必须原样还在 README 里。
    if sample.doc not in readme_text:
        return Outcome(sample.name, False,
                       f"README 里找不到 `{sample.doc}` —— 文档漂移了？"
                       f"修复：让 README 与命令对齐，或更新本用例的 doc")

    # 2) 只校验文档的用例(argv 为空)到此为止。
    if not sample.argv:
        return Outcome(sample.name, True, f"`{sample.doc}`(只校验文档)")

    # 3) 真能跑：只读的就地跑，有副作用的进临时副本跑。
    exit_code, out = (_run_isolated(sample.argv) if sample.isolate
                      else _run(sample.argv, REPO_ROOT))
    if exit_code != sample.expect_exit:
        tail = out.strip().splitlines()[-1][:160] if out.strip() else "(无输出)"
        return Outcome(sample.name, False,
                       f"退出码 {exit_code}(期望 {sample.expect_exit})：{tail}")
    if sample.expect_substr and sample.expect_substr not in out:
        return Outcome(sample.name, False,
                       f"输出里没等到「{sample.expect_substr}」—— 行为变了？")
    where = "临时副本" if sample.isolate else "就地"
    return Outcome(sample.name, True, f"`{sample.doc}` 跑通({where})")


@dataclasses.dataclass
class Report:
    ok: bool
    outcomes: list[Outcome]
    uncovered: list[str]   # README 里出现、却没有对应用例的 python 命令(只提示)


def _readme_python_commands(text: str) -> list[str]:
    """从 README 的 ```bash``` 代码块里捞出所有 `python ...` 命令行(去重保序)。"""
    cmds: list[str] = []
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_block = not in_block if not in_block else False
            in_block = stripped.startswith("```bash") if stripped != "```" else False
            continue
        if in_block and stripped.startswith("python "):
            # 砍掉 `|| {...}` 之类的尾巴，只留核心命令
            core = stripped.split(" || ", 1)[0].split(" && ", 1)[0].strip()
            if core not in cmds:
                cmds.append(core)
    return cmds


def verify() -> Report:
    """跑完所有用例，外加扫一遍 README 里有没有「没被任何用例覆盖」的命令。"""
    text = README.read_text("utf-8") if README.is_file() else ""
    outcomes = [_check(s, text) for s in SAMPLES]
    documented = {s.doc for s in SAMPLES}
    uncovered = [c for c in _readme_python_commands(text) if c not in documented]
    ok = all(o.ok for o in outcomes)
    return Report(ok=ok, outcomes=outcomes, uncovered=uncovered)


def main() -> None:
    ap = argparse.ArgumentParser(description="opencrab 可执行示例 + 烟雾测试 🔥")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quiet", action="store_true",
                   help="只在有失败时输出(适合钩子 / CI)")
    g.add_argument("--list", action="store_true", help="只列出有哪些用例(不执行)")
    args = ap.parse_args()

    if args.list:
        print("🔥 烟雾用例：")
        for s in SAMPLES:
            mode = "仅文档" if not s.argv else ("临时副本" if s.isolate else "就地")
            print(f"  [{mode}] {s.name} — {s.summary}")
            print(f"          $ {s.doc}")
        return

    report = verify()
    failed = [o for o in report.outcomes if not o.ok]

    if not (args.quiet and report.ok):
        print("🔥 opencrab 烟雾测试 —— README 的关键用法真能跑吗\n")
        for o in report.outcomes:
            print(f"  {'✅' if o.ok else '❌'} {o.name} — {o.detail}")
        if report.uncovered:
            print("\n  ⚪ README 里这些命令还没被烟雾用例覆盖(建议补进 SAMPLES)：")
            for c in report.uncovered:
                print(f"       $ {c}")
        print()

    if report.ok:
        if not args.quiet:
            print(f"🦀 全通：{len(report.outcomes)} 条示例都真能跑、且 README 没漂移。")
        sys.exit(0)
    print(f"⚠️  烟雾测试发现 {len(failed)} 条失败——README 与行为对不上了，先修好再进化。")
    sys.exit(1)


if __name__ == "__main__":
    main()
