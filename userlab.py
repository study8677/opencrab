#!/usr/bin/env python3
"""用户实验室 🧪 —— 把新手 / 维护者 / 外部协作者的真实旅程，跑成一条条端到端验收脚本。
逼自己从「模块各自会跑」进化到「人真的用得顺」。

为什么要有它：领地里已经有一排向**单点**看的层——烟雾(smoke)证「核心还活着」、契约
(contracts)证「接口没变」、价值(value)证「对谁有用」、健康(health)证「自检全过」。
它们各自把一块拧得发亮，却没人回答一个更朴素、也更要命的问题：**把它们串起来，一个
真实的人从头走到尾，顺不顺？** 单点全绿，不等于旅程走得通——新手可能卡在第一步、维
护者可能改完发现没法确认没退化、外部协作者可能对着文档照做却处处碰壁。这些「接缝处的
不顺」永远不会让任何单个模块变红，所以它**隐形**。

本层换一个视角：不按模块切，按**人**切。给领地里三种真实使用者各写一条旅程——

  · 🐣 新手(newcomer)    —— 第一次拿到这个仓：它能跑吗？我从哪看起、怎么确认它没坏？
  · 🛠️ 维护者(maintainer) —— 要动它了：改之前/改之后，怎么一键确认「整体没退化」？
  · 🤝 协作者(collaborator)—— 想从外部贡献：文档与对外承诺，照着做真的兑现得了吗？

一条旅程是一串**有先后的步骤**，每步是这个人会真的做的一个动作，背后绑一条**能当场复
跑**的命令。把整条旅程从头跑到尾、每步都退出码 0，才算「这个人此刻真的用得顺」✅；中
途任何一步红了，就精确地指出**这个人会在哪一步卡住**——那处接缝，就是下一个该治的「不
顺」。

它和烟雾(smoke)的差别：烟雾问「零件还转吗」，用户实验室问「人沿着零件走，路通吗」。同
一批命令，换成「以谁的身份、为了什么、按什么顺序」走一遍，卡点才会从接缝里浮出来。

用法：
    python userlab.py                  # 列出三条旅程及其步骤(只读，不执行)
    python userlab.py --run            # 端到端跑全部旅程，看每种人此刻走不走得通
    python userlab.py --run newcomer   # 只跑某一种人的旅程
    python userlab.py --persona NAME   # 只看某条旅程的步骤(不执行)
    python userlab.py --verify         # 自检回放引擎：「卡在第几步」这条断点逻辑还准不准
    python userlab.py --quiet          # 只在有旅程走不通时说话(适合钩子 / CI)
    python userlab.py --json           # 机读：导出旅程定义 +（含 --run 时）逐步结果

零第三方依赖，纯标准库。实验室只读领地、复跑无副作用；任何写盘/起不来都不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
STEP_TIMEOUT = 120          # 单步命令的墙钟上限(秒)：跑旅程不该把生命拖死
_PY = [sys.executable]


@dataclasses.dataclass(frozen=True)
class Step:
    """旅程里的一步：这个人此刻在做的一个动作，绑一条能当场复跑的命令。"""
    action: str             # 一句话：这个人在这一步想做成什么
    argv: list[str]         # 退出码 0 = 这一步对这个人此刻真的走得通

    @property
    def cmd(self) -> str:
        """命令的可读形式(隐去 python 解释器路径)。"""
        return " ".join(self.argv[1:]) if self.argv[:1] == _PY else " ".join(self.argv)

    def to_meta(self) -> dict:
        return {"action": self.action, "cmd": self.cmd}


@dataclasses.dataclass(frozen=True)
class Journey:
    """一条端到端旅程：一种真实使用者，按先后顺序走过的若干步。"""
    persona: str            # 旅程主键：newcomer / maintainer / collaborator
    icon: str               # 这种人的图标
    title: str              # 这种人是谁
    goal: str               # 这种人走这趟，到底想确认什么
    steps: list[Step]       # 有先后的步骤——前一步通了才轮到下一步

    def to_meta(self) -> dict:
        return {"persona": self.persona, "icon": self.icon, "title": self.title,
                "goal": self.goal, "steps": [s.to_meta() for s in self.steps]}


# ── 三条旅程：单一真相源 ──────────────────────────────────────────────
# 每条旅程把一种真实使用者「为了什么、按什么顺序、做哪些动作」钉成一串步骤；每步都绑
# 领地里**真实存在、能当场跑、且 --quiet 够快**的命令。新做一种「人会怎么用」的设想，
# 就在这里把它写成一条能端到端复跑的旅程——而不是停在脑补里。
JOURNEYS: list[Journey] = [
    Journey(
        persona="newcomer",
        icon="🐣",
        title="新手——第一次拿到这个仓",
        goal="确认「它真的能跑」，并知道从哪一眼看出它没坏",
        steps=[
            Step("先跑核心烟雾，确认最关键的几条路此刻还活着",
                 _PY + ["smoke.py", "--quiet"]),
            Step("再做一次整体自检，确认领地作为一个整体是健康的",
                 _PY + ["health.py", "--quiet"]),
        ],
    ),
    Journey(
        persona="maintainer",
        icon="🛠️",
        title="维护者——要动这个仓了",
        goal="改之前/改之后，一键确认「接口没变、价值还兑现、整体没退化」",
        steps=[
            Step("先确认各层对外接口没被悄悄改坏(契约还成立)",
                 _PY + ["contracts.py", "--quiet"]),
            Step("再复核价值卡，确认每次进化绑的受益者此刻还真兑现得了",
                 _PY + ["value.py", "--check", "--quiet"]),
            Step("最后整体自检兜底，确认改动没在别处留暗伤",
                 _PY + ["health.py", "--quiet"]),
        ],
    ),
    Journey(
        persona="collaborator",
        icon="🤝",
        title="外部协作者——想从外部贡献",
        goal="确认「文档说的 = 仓里做得到的」，照着文档做不会处处碰壁",
        steps=[
            Step("先核对文档与代码是否同步(README/用法没和实现脱节)",
                 _PY + ["docsync.py", "--quiet"]),
            Step("再复跑对外承诺的证据，确认「我会做 X」这类话今天还兑现得了",
                 _PY + ["evidence.py", "--quiet"]),
        ],
    ),
    Journey(
        persona="value-seeker",
        icon="💎",
        title="价值复核者——判断一次进化是否真的有用",
        goal="确认进化不只自测变绿，还能挂到一条真实、可复跑、无递归的用户旅程上",
        steps=[
            Step("先读出价值账本，确认每张卡都有场景、受益者、验收、反指标与旅程字段",
                 _PY + ["value.py", "--json"]),
            Step("再读出用户实验室旅程定义，确认这条验收路本身可被复跑和审计",
                 _PY + ["userlab.py", "--json"]),
            Step("最后跑核心烟雾，确认这条朝外的价值复核没有牺牲最基本可用性",
                 _PY + ["smoke.py", "--quiet"]),
        ],
    ),
]


@dataclasses.dataclass(frozen=True)
class StepResult:
    """一步复跑后的结果。"""
    step: Step
    ok: bool
    detail: str             # 失败命令的现场原文；通过则空

    def to_meta(self) -> dict:
        return {**self.step.to_meta(), "ok": self.ok, "detail": self.detail}


@dataclasses.dataclass(frozen=True)
class JourneyResult:
    """一条旅程端到端跑完后的结果：在第几步卡住(没卡=全程走通)。"""
    journey: Journey
    steps: list[StepResult]

    @property
    def passed(self) -> bool:
        """整条旅程每一步都通——这种人此刻真的从头走得到尾。"""
        return all(s.ok for s in self.steps)

    @property
    def blocked_at(self) -> int:
        """第一处卡住的步号(从 1 起)；全通返回 0。"""
        for i, s in enumerate(self.steps, start=1):
            if not s.ok:
                return i
        return 0

    def to_meta(self) -> dict:
        return {"persona": self.journey.persona, "passed": self.passed,
                "blocked_at": self.blocked_at,
                "steps": [s.to_meta() for s in self.steps]}


def _run(argv: list[str]) -> tuple[bool, str]:
    """跑一条命令：退出码 0 → (True, "")。超时/起不来 → (False, 原因)，绝不抛错。"""
    try:
        proc = subprocess.run(
            argv, cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=STEP_TIMEOUT,
        )
        if proc.returncode == 0:
            return True, ""
        return False, (proc.stderr or proc.stdout or "").strip()[-500:]
    except subprocess.TimeoutExpired:
        return False, f"命令超过 {STEP_TIMEOUT}s 未结束"
    except Exception as e:  # noqa: BLE001  —— 跑旅程是观测者，起不来只是「这次没跑成」
        return False, f"{type(e).__name__}: {e}"


def walk(journey: Journey) -> JourneyResult:
    """端到端走一条旅程：按顺序跑每步，**一步卡住就停**——精确定位这种人会在哪儿被挡。

    停在第一处失败，是刻意的：真实使用者也会卡在那一步、走不下去；继续硬跑后面的步骤，
    只会用一堆「其实根本到不了」的失败淹没真正的卡点。
    """
    results: list[StepResult] = []
    for step in journey.steps:
        ok, detail = _run(step.argv)
        first = detail.splitlines()[0][:120] if detail else ""
        results.append(StepResult(step, ok, first))
        if not ok:
            break
    return JourneyResult(journey, results)


def _find(persona: str) -> Journey | None:
    for j in JOURNEYS:
        if j.persona == persona:
            return j
    return None


# ── 回放引擎自检：把「卡在第几步」这条断点逻辑钉成回归 🛤️ ────────────────
# 整条回放的命根子，是 walk() 能不能**准确地停在第一处失败、并报对是哪一步卡的**：
# 报错了步号，治接缝就被引去治错地方；该停时不停、硬跑后面的步，又会用一堆「其实根本
# 到不了」的失败淹没真正的卡点。这套定位逻辑此前没有任何回归守着——谁哪天改坏了 walk
# 的短路或步号计数，三条真旅程也未必当场翻红，于是它**隐形**。
#
# 这里用一组**合成旅程**喂给真正的 walk()：每步只绑一条退出码写死的命令(0=通/非0=卡)，
# 于是结果完全可预期。断言 walk() 在该停的那步停(只跑到那步、不再往后)、且 blocked_at
# 正是那步——把「首个断点」的定位钉死成自检，不碰真旅程、无副作用、纯标准库可当场复跑。
def _exit_step(action: str, code: int) -> Step:
    """造一条「退出码写死」的合成步骤：code=0 当场就通，非 0 当场就卡。"""
    return Step(action, _PY + ["-c", f"import sys; sys.exit({code})"])


# 每条样例：(名字, 各步退出码, 期望卡在第几步(0=全通), 期望真正跑到的步数)。
# 覆盖断点定位的关键分支：全通、第一步就卡、中途卡、末步卡，以及单步两种结局。
REPLAY_SAMPLES: tuple[tuple[str, tuple[int, ...], int, int], ...] = (
    ("三步全通——一路走到尾",        (0, 0, 0), 0, 3),
    ("第一步就卡——立刻停住",        (1, 0, 0), 1, 1),
    ("中途第二步卡——停在卡点",      (0, 1, 0), 2, 2),
    ("末步才卡——前两步通了也得报",  (0, 0, 1), 3, 3),
    ("单步旅程·通",                (0,),      0, 1),
    ("单步旅程·卡",                (1,),      1, 1),
)


@dataclasses.dataclass(frozen=True)
class ReplayCheck:
    """一条回放自检：合成旅程跑完后，断点定位是否和预期一字不差。"""
    name: str
    expected_blocked_at: int
    got_blocked_at: int
    expected_ran: int           # 期望真正跑到的步数(短路后不应再跑后续步)
    got_ran: int

    @property
    def ok(self) -> bool:
        return (self.got_blocked_at == self.expected_blocked_at
                and self.got_ran == self.expected_ran)

    def to_meta(self) -> dict:
        return {"name": self.name, "ok": self.ok,
                "expected_blocked_at": self.expected_blocked_at,
                "got_blocked_at": self.got_blocked_at,
                "expected_ran": self.expected_ran, "got_ran": self.got_ran}


def verify() -> list[ReplayCheck]:
    """跑回放引擎自检：每条合成旅程走完后，walk() 是否准确报出「卡在第几步、跑到第几步」。"""
    out: list[ReplayCheck] = []
    for name, codes, exp_block, exp_ran in REPLAY_SAMPLES:
        steps = [_exit_step(f"第{i}步", c) for i, c in enumerate(codes, start=1)]
        j = Journey("__verify__", "🧪", name, name, steps)
        r = walk(j)
        out.append(ReplayCheck(name, exp_block, r.blocked_at, exp_ran, len(r.steps)))
    return out


# ── 展示 ──────────────────────────────────────────────────────────────
def _print_journeys(journeys: list[Journey]) -> None:
    print(f"🧪 opencrab 用户实验室（{len(journeys)} 条端到端旅程）\n")
    for j in journeys:
        print(f"  {j.icon} {j.persona}：{j.title}")
        print(f"      想确认：{j.goal}")
        for i, s in enumerate(j.steps, start=1):
            print(f"        {i}. {s.action}")
            print(f"           └ {s.cmd}")
        print()
    print("  跑 `--run` 把这些旅程从头到尾走一遍，看每种人此刻是否真的用得顺。")


def _print_results(results: list[JourneyResult]) -> None:
    print(f"🧪 端到端走完 {len(results)} 条旅程——每种人此刻走得通吗\n")
    for r in results:
        j = r.journey
        if r.passed:
            print(f"  ✅ {j.icon} {j.persona}（{len(r.steps)} 步全通：用得顺）")
        else:
            print(f"  ⛔ {j.icon} {j.persona}（卡在第 {r.blocked_at} 步：走不到尾）")
        for i, s in enumerate(r.steps, start=1):
            mark = "✓" if s.ok else "✗"
            print(f"        {mark} {i}. {s.step.action}")
            if not s.ok:
                print(f"           └ {s.step.cmd}")
                if s.detail:
                    print(f"             现场：{s.detail}")
    passed = sum(1 for r in results if r.passed)
    print(f"\n  小结：✅{passed}  ⛔{len(results) - passed}")
    if passed == len(results):
        print("🧪 三种人都从头走到了尾——接缝处此刻是顺的。")
    else:
        bad = [r.journey.persona for r in results if not r.passed]
        print(f"⚠️  {len(bad)} 种人此刻会卡住：{'、'.join(bad)}（顺着卡住那步去治接缝）")


def _print_replay(checks: list[ReplayCheck]) -> None:
    bad = [c for c in checks if not c.ok]
    print(f"🛤️ 回放引擎自检（{len(checks)} 条合成旅程喂给真正的 walk()）\n")
    for c in checks:
        mark = "✓" if c.ok else "✗"
        print(f"  {mark} {c.name}")
        if not c.ok:
            print(f"      期望：卡在第 {c.expected_blocked_at} 步、跑到第 {c.expected_ran} 步")
            print(f"      实际：卡在第 {c.got_blocked_at} 步、跑到第 {c.got_ran} 步")
    if bad:
        print(f"\n⚠️  {len(bad)} 条断点定位漂了——walk() 的短路/步号逻辑被改坏了，回去对照。")
    else:
        print("\n✅ 每条断点都停在该停的那步——回放引擎此刻报得准。")


def manifest(run: bool, journeys: list[Journey]) -> dict:
    """导出纯数据：旅程定义；若 run=True 还附上逐步端到端结果。"""
    out: dict = {"journeys": [j.to_meta() for j in journeys]}
    if run:
        out["results"] = [walk(j).to_meta() for j in journeys]
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 用户实验室 🧪")
    ap.add_argument("--run", nargs="?", const="*", metavar="PERSONA",
                    help="端到端跑旅程：不带名=全部，带名=只跑该种人")
    ap.add_argument("--persona", metavar="NAME",
                    help="只看某种人的旅程步骤(不执行)")
    ap.add_argument("--verify", action="store_true",
                    help="自检回放引擎的断点定位(合成旅程→期望卡在第几步)")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有旅程走不通时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true",
                    help="导出机读：旅程定义 +（含 --run 时）逐步结果")
    args = ap.parse_args(argv)

    # 回放引擎自检：独立一条路，只关心 walk() 的断点定位准不准，不碰真旅程
    if args.verify:
        checks = verify()
        all_ok = all(c.ok for c in checks)
        if args.json:
            print(json.dumps([c.to_meta() for c in checks], ensure_ascii=False, indent=2))
        elif not (args.quiet and all_ok):
            _print_replay(checks)
        sys.exit(0 if all_ok else 1)

    # 选定要操作的旅程集合(--run NAME / --persona NAME 都可定位单条)
    target = args.run if (args.run and args.run != "*") else args.persona
    if target:
        j = _find(target)
        if j is None:
            print(f"⚠️  没有名为 {target!r} 的旅程；可选：{'、'.join(x.persona for x in JOURNEYS)}")
            sys.exit(2)
        chosen = [j]
    else:
        chosen = JOURNEYS

    # 预检查：确保旅程中引用的所有 .py 脚本都存在，提前暴露「文件不存在」这种低级卡点
    missing = []
    for j in chosen:
        for step in j.steps:
            for arg in step.argv[1:]:
                if arg.endswith('.py') and not (REPO_ROOT / arg).exists():
                    missing.append((j.persona, step.action, arg))
    if missing:
        print("⚠️  以下旅程步骤中引用的 .py 文件不存在，无法完整运行旅程：")
        for persona, action, script in missing:
            print(f"    {persona}: {action} -> {script}")
        print("请确保这些文件存在，或调整旅程定义。")
        sys.exit(2)

    if args.json:
        print(json.dumps(manifest(args.run is not None, chosen),
                         ensure_ascii=False, indent=2))
        return

    if args.run is not None:
        # 预检查：确保旅程中引用的所有 .py 脚本都存在，提前暴露「文件不存在」这种低级卡点
        missing = []
        for j in chosen:
            for step in j.steps:
                for arg in step.argv[1:]:
                    if arg.endswith('.py') and not (REPO_ROOT / arg).exists():
                        missing.append((j.persona, step.action, arg))
        if missing:
            print("⚠️  以下旅程步骤中引用的 .py 文件不存在，无法完整运行旅程：")
            for persona, action, script in missing:
                print(f"    {persona}: {action} -> {script}")
            print("请确保这些文件存在，或调整旅程定义。")
            sys.exit(2)
        results = [walk(j) for j in chosen]
        all_ok = all(r.passed for r in results)
        if not (args.quiet and all_ok):
            _print_results(results)
        sys.exit(0 if all_ok else 1)

    if args.quiet:
        # 静默模式不主动执行旅程；没跑就没有「走不通」可报。
        sys.exit(0)

    _print_journeys(chosen)
    sys.exit(0)


if __name__ == "__main__":
    main()
