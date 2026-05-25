#!/usr/bin/env python3
"""场景铸造 🔨🎬 —— 把一句真实用户目标，自动铸成一条可跑场景 + 一组验收样例。
逼自己从「会自检」进化到「更懂真实用途」。

为什么要有它：领地里已经有一排「会跑」的层——烟雾(smoke)证零件活着、健康(health)
做整体自检、用户实验室(userlab)按**写死的三种人**走端到端旅程。但它们都从**我预设**
的视角出发：我替使用者想好了「他要确认什么、按什么顺序走」。真实世界反过来——人先有
一个**用自己的话说出来的目标**(「我想确认改完没把别处弄坏」「照着文档我真贡献得了吗」)，
然后才需要有人把这句话**翻译**成「那你该跑哪几条命令、跑出什么才算成」。这一步翻译，
过去只在我脑子里、没有单一真相源，也没法被测——于是「懂不懂真实用途」全凭临场感觉。

场景铸造把这步翻译**钉成可执行的物件**。给它一句目标(`--goal "..."`)，它做两件事：

  · 🎬 **铸出一条场景(scenario)**——把目标按关键词匹配到领地里**真实存在**的能力，
    排成一串有先后的步骤，每步绑一条能当场复跑的命令；
  · ✅ **附上验收样例(acceptance)**——每条样例是「跑这条命令 → 期望这样收场」的断言
    (期望退出码、可选期望输出里出现某串)。验收样例答的是「凭什么说目标达成了」，
    而不只是「命令没崩」。

和 userlab 的差别：userlab 是「**我**替三种写死的人，预排好旅程」；场景铸造是「**你**
说一句目标，我当场把它**翻译**成可跑场景」。前者是预设旅程的执行器，后者是目标→场景的
**铸造器**。铸造逻辑本身可测：`--verify` 跑一组(目标原话 → 期望命中哪个场景)的自检样例,
翻译漂了立刻暴露——交给 health 当一层守。

匹配是朴素的关键词打分，不假装懂自然语言：宁可粗、不可玄，这样才测得动、也解释得清;
匹配不到任何场景时，它**老实说铸不出来**，绝不硬凑。它只读领地、复跑无副作用，任何
写盘/起不来都吞掉不反噬生命——铸造器是观测者，不能成为新的故障源。

用法：
    python scenarioforge.py                      # 列出所有可铸场景及其步骤/验收(不执行)
    python scenarioforge.py --goal "我改完想确认没弄坏别处"   # 把这句目标铸成场景(不执行)
    python scenarioforge.py --goal "..." --run   # 铸出场景后，端到端跑并逐条验收
    python scenarioforge.py --run [KEY]          # 跑全部(或某个)预置场景并验收
    python scenarioforge.py --verify             # 跑铸造路由自检(目标原话→期望场景)
    python scenarioforge.py --quiet              # 只在有验收不过/铸不出时说话(钩子/CI)
    python scenarioforge.py --json               # 机读：导出场景定义 +（含 --run 时）验收结果

退出码：列表/铸造=0；--run 全验收通过=0、有不过=1、铸不出=2；--verify 路由全对=0、漂了=1。
零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
STEP_TIMEOUT = 120          # 单条验收命令的墙钟上限(秒)：铸造器不该把生命拖死
_PY = [sys.executable]


# ── 一条验收样例 ────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Accept:
    """场景里的一步 = 一条验收样例：跑一条命令，期望它这样收场才算「这一步达成」。"""
    action: str                       # 一句话：使用者在这一步想确认什么
    argv: list[str]                   # 要跑的命令
    expect_code: int = 0              # 期望退出码(默认 0)
    expect_text: str | None = None    # 可选：期望在合并输出里出现这串(更强的断言)

    @property
    def cmd(self) -> str:
        """命令的可读形式(隐去 python 解释器路径)。"""
        return " ".join(self.argv[1:]) if self.argv[:1] == _PY else " ".join(self.argv)

    @property
    def expectation(self) -> str:
        """把期望译成一句人话——验收样例的「凭什么算成」。"""
        parts = [f"退出码 {self.expect_code}"]
        if self.expect_text:
            parts.append(f"输出含「{self.expect_text}」")
        return " 且 ".join(parts)

    def to_meta(self) -> dict:
        return {"action": self.action, "cmd": self.cmd,
                "expect_code": self.expect_code, "expect_text": self.expect_text,
                "expectation": self.expectation}


# ── 一条可铸场景 ────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Scenario:
    """一句真实目标铸成的场景：谁、为了确认什么、按什么顺序跑、跑成什么算达成。"""
    key: str                          # 场景主键(slug)
    icon: str                         # 图标
    goal: str                         # 这条场景服务的真实用户目标(一句人话)
    keywords: tuple[str, ...]         # 铸造时拿目标原话来打分命中的关键词
    steps: tuple[Accept, ...]         # 有先后的验收样例——前一步达成才轮到下一步

    def to_meta(self) -> dict:
        return {"key": self.key, "icon": self.icon, "goal": self.goal,
                "keywords": list(self.keywords),
                "steps": [s.to_meta() for s in self.steps]}


# ── 场景目录：单一真相源 ────────────────────────────────────────────
# 每条场景把「一句真实目标」钉成「跑哪几条真实命令、跑成什么算达成」。新设想一种
# 「人会带着什么目标来用」，就在这里把它铸成一条能端到端复跑+验收的场景——而不是
# 停在「我觉得他大概想……」里。命令一律绑领地里**真实存在、--quiet 够快**的层。
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="trust-it-runs",
        icon="🐣",
        goal="我第一次拿到这个仓，想确认它真的能跑、此刻没坏",
        keywords=("能跑", "没坏", "第一次", "拿到", "信任", "可用", "works", "run", "活着"),
        steps=(
            Accept("先跑核心烟雾，确认最关键的几条路此刻还活着",
                   _PY + ["smoke.py", "--quiet"]),
            Accept("再整体自检，确认领地作为一个整体是健康的",
                   _PY + ["health.py", "--quiet"]),
        ),
    ),
    Scenario(
        key="ship-a-change",
        icon="🛠️",
        goal="我要改它，想在改完后确认没把别处悄悄弄坏",
        keywords=("改", "修改", "动它", "退化", "regression", "弄坏", "没坏", "改完", "发布"),
        steps=(
            Accept("先确认各层对外接口没被改坏(契约还成立)",
                   _PY + ["contracts.py", "--quiet"]),
            Accept("再复核价值卡，确认每次进化绑的受益者此刻还兑现得了",
                   _PY + ["value.py", "--check", "--quiet"]),
            Accept("最后整体自检兜底，确认改动没在别处留暗伤",
                   _PY + ["health.py", "--quiet"]),
        ),
    ),
    Scenario(
        key="contribute-from-docs",
        icon="🤝",
        goal="我照着文档从外部贡献，想确认文档说的真做得到",
        keywords=("文档", "贡献", "docs", "承诺", "照着", "外部", "readme", "兑现"),
        steps=(
            Accept("先核对文档与代码是否同步(用法没和实现脱节)",
                   _PY + ["docsync.py", "--quiet"]),
            Accept("再复跑对外承诺的证据，确认「我会做 X」这类话今天还兑现得了",
                   _PY + ["evidence.py", "--quiet"]),
        ),
    ),
    Scenario(
        key="stay-on-mission",
        icon="🧭",
        goal="我想确认某个改动没越红线、还在使命方向上",
        keywords=("红线", "边界", "使命", "方向", "意图", "越线", "触线", "该不该"),
        steps=(
            Accept("跑意图声明的自检，确认每条红线/使命判据此刻没漂",
                   _PY + ["intent.py", "--quiet"]),
            Accept("确认意图清单里仍钉着「边界」这类红线声明(不是空架子)",
                   _PY + ["intent.py", "--json"], expect_text="boundary"),
        ),
    ),
    Scenario(
        key="real-use-flows",
        icon="🧪",
        goal="我想确认真实使用者从头到尾用得顺、不卡在接缝上",
        keywords=("旅程", "真实", "端到端", "用得顺", "接缝", "使用者", "上手", "流程"),
        steps=(
            Accept("端到端走完三种人的旅程，确认每种人此刻都从头走得到尾",
                   _PY + ["userlab.py", "--run", "--quiet"]),
        ),
    ),
)


# ── 铸造：把一句目标原话翻译成一条场景 ──────────────────────────────
def _tokens(text: str) -> str:
    """归一化目标原话：转小写，便于关键词做包含匹配(中文按子串、英文大小写无关)。"""
    return text.lower()


def forge(goal_text: str) -> tuple[Scenario | None, dict[str, int]]:
    """把一句目标原话铸成场景：按关键词命中数给每条场景打分，取最高分那条。

    返回 (命中的场景或 None, 每条场景的得分明细)。一个关键词都不命中 → None，
    表示「这句目标我铸不出来」——老实说铸不出，绝不硬凑一条不相干的场景。
    """
    hay = _tokens(goal_text)
    scores: dict[str, int] = {}
    for sc in SCENARIOS:
        scores[sc.key] = sum(1 for kw in sc.keywords if kw.lower() in hay)
    best_key = max(scores, key=lambda k: scores[k]) if scores else None
    if best_key is None or scores[best_key] == 0:
        return None, scores
    best = next(sc for sc in SCENARIOS if sc.key == best_key)
    return best, scores


def _find(key: str) -> Scenario | None:
    for sc in SCENARIOS:
        if sc.key == key:
            return sc
    return None


# ── 验收：复跑一条命令，按期望判定是否达成 ──────────────────────────
@dataclasses.dataclass(frozen=True)
class StepResult:
    step: Accept
    ok: bool
    detail: str             # 没达成时的现场原文(退出码/缺失串/异常)；达成则空

    def to_meta(self) -> dict:
        return {**self.step.to_meta(), "ok": self.ok, "detail": self.detail}


@dataclasses.dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    steps: list[StepResult]

    @property
    def passed(self) -> bool:
        return all(s.ok for s in self.steps)

    @property
    def blocked_at(self) -> int:
        """第一处没达成的步号(从 1 起)；全达成返回 0。"""
        for i, s in enumerate(self.steps, start=1):
            if not s.ok:
                return i
        return 0

    def to_meta(self) -> dict:
        return {"key": self.scenario.key, "passed": self.passed,
                "blocked_at": self.blocked_at,
                "steps": [s.to_meta() for s in self.steps]}


def _check(step: Accept) -> tuple[bool, str]:
    """跑一条验收命令并按期望判定：退出码对 + (有要求时)输出含期望串 → 达成。

    超时/起不来 → (False, 原因)，绝不抛错——验收是观测者，起不来只是「这次没验成」。
    """
    try:
        proc = subprocess.run(
            step.argv, cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=STEP_TIMEOUT,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            tail = out.strip().splitlines()
            why = tail[-1][:120] if tail else ""
            return False, f"退出码 {proc.returncode}(期望 {step.expect_code})" + (f"：{why}" if why else "")
        if step.expect_text and step.expect_text not in out:
            return False, f"输出里没出现期望的「{step.expect_text}」"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, f"命令超过 {STEP_TIMEOUT}s 未结束"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def run(scenario: Scenario) -> ScenarioResult:
    """端到端跑一条场景：按顺序逐条验收，**一步没达成就停**——精确定位卡在哪一步。"""
    results: list[StepResult] = []
    for step in scenario.steps:
        ok, detail = _check(step)
        results.append(StepResult(step, ok, detail))
        if not ok:
            break
    return ScenarioResult(scenario, results)


# ── 铸造路由自检：目标原话 → 期望命中的场景 ─────────────────────────
# 拿一组「人真会这么说」的目标原话，钉死它该被铸成哪条场景。翻译逻辑一漂(改了关键词、
# 加了新场景把旧的抢走)，这里立刻变红——交给 health 当一层守。
ROUTING_SAMPLES: tuple[tuple[str, str], ...] = (
    ("我第一次 clone 下来，它能跑吗？", "trust-it-runs"),
    ("我改完代码，想确认没把别处弄坏", "ship-a-change"),
    ("我想照着文档贡献，文档说的做得到吗", "contribute-from-docs"),
    ("这个改动有没有越过红线、还在使命上吗", "stay-on-mission"),
    ("真实使用者端到端用得顺吗", "real-use-flows"),
)


@dataclasses.dataclass(frozen=True)
class RouteCheck:
    text: str
    expected: str
    got: str | None         # 实际铸到的场景 key；铸不出为 None

    @property
    def ok(self) -> bool:
        return self.got == self.expected

    def to_meta(self) -> dict:
        return {"text": self.text, "expected": self.expected,
                "got": self.got, "ok": self.ok}


def verify() -> list[RouteCheck]:
    """跑铸造路由自检：每句目标原话铸出来的场景，是否正是它该命中的那条。"""
    out: list[RouteCheck] = []
    for text, expected in ROUTING_SAMPLES:
        sc, _ = forge(text)
        out.append(RouteCheck(text, expected, sc.key if sc else None))
    return out


# ── 展示 ──────────────────────────────────────────────────────────────
def _print_scenario(sc: Scenario, *, indent: str = "  ") -> None:
    print(f"{indent}{sc.icon} {sc.key}：{sc.goal}")
    for i, s in enumerate(sc.steps, start=1):
        print(f"{indent}    {i}. {s.action}")
        print(f"{indent}       └ {s.cmd}")
        print(f"{indent}         ✅ 算达成：{s.expectation}")


def _print_catalog(scenarios: tuple[Scenario, ...]) -> None:
    print(f"🔨 opencrab 场景铸造（{len(scenarios)} 条可铸场景）\n")
    for sc in scenarios:
        _print_scenario(sc)
        print()
    print("  用 `--goal \"<你的目标>\"` 把一句真实目标当场铸成场景；加 `--run` 端到端验收。")


def _print_results(results: list[ScenarioResult]) -> None:
    print(f"🔨 端到端验收 {len(results)} 条场景——目标此刻真达成了吗\n")
    for r in results:
        sc = r.scenario
        if r.passed:
            print(f"  ✅ {sc.icon} {sc.key}（{len(r.steps)} 步全验收通过：目标达成）")
        else:
            print(f"  ⛔ {sc.icon} {sc.key}（卡在第 {r.blocked_at} 步：目标未达成）")
        for i, s in enumerate(r.steps, start=1):
            mark = "✓" if s.ok else "✗"
            print(f"        {mark} {i}. {s.step.action}")
            if not s.ok:
                print(f"           └ {s.step.cmd}")
                print(f"             现场：{s.detail}")
    passed = sum(1 for r in results if r.passed)
    print(f"\n  小结：✅{passed}  ⛔{len(results) - passed}")
    if passed == len(results):
        print("🔨 所有场景的目标此刻都验收得过——这些用途是真兑现得了的。")
    else:
        bad = [r.scenario.key for r in results if not r.passed]
        print(f"⚠️  {len(bad)} 条场景的目标此刻没达成：{'、'.join(bad)}（顺着卡住那步去治）")


def _print_routes(checks: list[RouteCheck]) -> None:
    bad = [c for c in checks if not c.ok]
    print(f"🔨 铸造路由自检（{len(checks)} 句目标原话）\n")
    for c in checks:
        mark = "✓" if c.ok else "✗"
        print(f"  {mark} 「{c.text}」")
        if not c.ok:
            print(f"      期望铸成 {c.expected}，实际铸成 {c.got or '（铸不出）'}")
    if bad:
        print(f"\n⚠️  {len(bad)} 句目标被铸错了——翻译逻辑漂了，去对照关键词。")
    else:
        print("\n✅ 每句目标都铸到了该去的场景——翻译此刻没漂。")


def manifest(scenarios: tuple[Scenario, ...], *, do_run: bool) -> dict:
    out: dict = {"scenarios": [sc.to_meta() for sc in scenarios]}
    if do_run:
        out["results"] = [run(sc).to_meta() for sc in scenarios]
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 场景铸造 🔨")
    ap.add_argument("--goal", metavar="TEXT",
                    help="把一句真实用户目标铸成场景(不带 --run 则只展示)")
    ap.add_argument("--run", nargs="?", const="*", metavar="KEY",
                    help="端到端跑并验收：不带名=全部预置场景，带名=只跑该场景")
    ap.add_argument("--verify", action="store_true",
                    help="跑铸造路由自检(目标原话→期望场景)")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有验收不过/铸不出/路由漂时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true",
                    help="导出机读：场景定义 +（含 --run 时）验收结果")
    args = ap.parse_args(argv)

    # 路由自检：独立一条路，只关心翻译对不对
    if args.verify:
        checks = verify()
        all_ok = all(c.ok for c in checks)
        if args.json:
            print(json.dumps([c.to_meta() for c in checks], ensure_ascii=False, indent=2))
        elif not (args.quiet and all_ok):
            _print_routes(checks)
        sys.exit(0 if all_ok else 1)

    # 选定要操作的场景集合
    if args.goal is not None:
        sc, scores = forge(args.goal)
        if sc is None:
            ranked = sorted(scores.items(), key=lambda kv: -kv[1])
            if args.json:
                print(json.dumps({"goal": args.goal, "forged": None, "scores": scores},
                                 ensure_ascii=False, indent=2))
            else:
                print(f"🔨 这句目标我铸不出场景：「{args.goal}」")
                print("   一个关键词都没命中。可铸的场景关键词维度：")
                for sc2 in SCENARIOS:
                    print(f"     · {sc2.icon} {sc2.key}：{'、'.join(sc2.keywords[:5])}…")
            sys.exit(2)
        chosen: tuple[Scenario, ...] = (sc,)
        if not args.json and not args.quiet:
            print(f"🔨 把目标「{args.goal}」铸成了场景 {sc.icon} {sc.key}：\n")
            _print_scenario(sc)
            print()
    elif args.run and args.run != "*":
        sc = _find(args.run)
        if sc is None:
            print(f"⚠️  没有名为 {args.run!r} 的场景；可选：{'、'.join(s.key for s in SCENARIOS)}")
            sys.exit(2)
        chosen = (sc,)
    else:
        chosen = SCENARIOS

    do_run = args.run is not None or (args.goal is not None and args.run is not None)
    # --goal 配 --run 时也要跑
    do_run = args.run is not None

    if args.json:
        print(json.dumps(manifest(chosen, do_run=do_run), ensure_ascii=False, indent=2))
        return

    if do_run:
        results = [run(sc) for sc in chosen]
        all_ok = all(r.passed for r in results)
        if not (args.quiet and all_ok):
            _print_results(results)
        sys.exit(0 if all_ok else 1)

    if args.quiet:
        # 静默模式不主动跑验收；没跑就没有「没达成」可报。
        sys.exit(0)

    if args.goal is None:
        _print_catalog(chosen)
    sys.exit(0)


if __name__ == "__main__":
    main()
