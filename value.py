#!/usr/bin/env python3
"""价值账本 💎 —— 给每次进化绑定「真实场景 · 受益者 · 验收样例 · 反指标」，逼自己回答「这真有用吗」。

为什么要有它：领地里已经有一堆向**内**看的层——证据(evidence)证「跑得通」、契约
(contracts)证「接口没变」、健康(health)证「自检全过」。它们都能让我心安理得地说
「今天又进化了」，却答不上最要命的一问：**这次进化，到底让谁、在什么场景下、过得更
好了？** 没有这一问，我会滑进一种舒适的自欺——把流程越打磨越精致，指标越刷越绿，却
离「真的更有用」越来越远。绿灯堆成山，也可能只是在原地把螺丝拧得更亮。

本层把每次进化钉在一张**朝外**的价值卡上，四样缺一不可：

  · 场景(scenario) —— 一句话：谁、在什么情境下、会真的用到这次进化。说不出场景的
                       进化，多半是自娱自乐。
  · 受益者(beneficiary)—— 这次进化让谁过得更好(我自己 / 用我的人 / 下游某个层)。
                       「没有受益者」本身就是一条最强的反对意见。
  · 验收样例(acceptance)—— 一条**能当场复跑**的命令：跑通(退出码 0)就证明这份价值
                       此刻**真的兑现得了**，而不是停留在 README 的承诺里。
  · 反指标(counter) —— 一条**不该因为这次进化而变红**的守卫命令：跑通=没有「优化了
                       局部、拖垮了整体」。它是价值的另一只脚——只看验收会让我为了
                       好看的数字牺牲别处；反指标盯着那个「别处」。

一张卡只有**验收通过且反指标也通过**，才算「兑现」💎；验收过但反指标红 = 这次进化
是「赚了吆喝赔了买卖」🔻，比没做更危险，因为它伪装成进步。

另有一问朝向「被遗忘的进化」：领地里哪些模块**压根没有一张价值卡**？那些就是「只优
化了内部流程、从没绑过受益者」的嫌疑名单(--coverage)——不是说它们没用，而是说我从
没逼自己说清它们对谁有用。

用法：
    python value.py                  # 价值清单：每次进化的场景 / 受益者 / 验收 / 反指标
    python value.py --check          # 复跑全部验收与反指标，看哪些价值此刻真兑现得了
    python value.py --check NAME      # 只核一张卡
    python value.py --coverage       # 哪些模块还没有价值卡(没绑受益者的嫌疑名单)
    python value.py --quiet          # 只在有未兑现/反指标变红/缺卡时说话(适合钩子 / CI)
    python value.py --json           # 机读：导出全部价值卡

零第三方依赖，纯标准库。账本只读领地，复跑无副作用；任何写盘/起不来都不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
CHECK_TIMEOUT = 120          # 单条验收/反指标命令的墙钟上限(秒)：核价值不该把生命拖死
_PY = [sys.executable]


@dataclasses.dataclass(frozen=True)
class ValueCard:
    """一张价值卡：把一次进化钉在「场景 · 受益者 · 验收样例 · 反指标」四问上。

    四问缺一不可——少了任何一问，这次进化就回答不了「它到底对谁、在哪、真有用吗」。
    """
    name: str               # 进化名(账本主键，通常对应一个模块)
    scenario: str           # 真实使用场景：谁在什么情境下会用到
    beneficiary: str        # 受益者：这次进化让谁过得更好
    acceptance: list[str]   # 验收样例命令：退出码 0 = 价值此刻真的兑现得了
    counter: list[str]      # 反指标守卫命令：退出码 0 = 没有「优化局部、拖垮整体」
    counter_why: str        # 一句话：这条反指标在盯着哪个「别处」不被牺牲
    user_journey: list[str] = dataclasses.field(
        default_factory=lambda: _PY + ["userlab.py", "--run", "value-seeker", "--quiet"]
    )                       # 可复跑用户旅程：退出码 0 = 真实使用者从头走得到尾

    def to_meta(self) -> dict:
        return {"name": self.name, "scenario": self.scenario,
                "beneficiary": self.beneficiary, "acceptance": self.acceptance,
                "counter": self.counter, "counter_why": self.counter_why,
                "user_journey": self.user_journey}


# ── 价值卡清单：单一真相源 ────────────────────────────────────────────
# 每张卡都把一次进化绑到**领地里真实存在、能当场跑**的验收与反指标命令上；
# 都用 --quiet / 自身够快，复跑无外部副作用。新做一块东西，就在这里逼自己答清四问：
# 它服务什么场景、让谁更好、拿什么证明兑现、又拿什么守住别处不被牺牲。
CARDS: list[ValueCard] = [
    ValueCard(
        name="evidence",
        scenario="我对外宣称「我会做 X」之前，先确认这话今天还跑得通、没过期",
        beneficiary="信我这句话的人——以及半年后不想被旧承诺坑到的我自己",
        acceptance=_PY + ["evidence.py", "--json"],
        counter=_PY + ["contracts.py", "--quiet"],
        counter_why="证据账本不能为了好看而偷改各层的输入/输出契约",
    ),
    ValueCard(
        name="health",
        scenario="任何一次改动落地前/后，一键问「领地整体还健康吗」",
        beneficiary="改完代码心里没底的我，和接手这个仓的任何人",
        acceptance=_PY + ["health.py", "--quiet"],
        counter=_PY + ["smoke.py", "--quiet"],
        counter_why="整体自检不能空过——核心烟雾用例必须仍然真的跑得通",
    ),
    ValueCard(
        name="value",
        scenario="每做完一次进化，逼自己当场答清「这对谁、在哪、真有用吗」",
        beneficiary="容易沉迷打磨内部流程、忘了朝外看的我自己",
        acceptance=_PY + ["value.py", "--json"],
        counter=_PY + ["value.py", "--coverage", "--quiet"],
        counter_why="价值层自己不能变成「没绑受益者的孤儿模块」——它得先过自己这关",
    ),
    ValueCard(
        name="revisit",
        scenario="隔一阵回头复核：近 N 次「合并即宣布进化了」的自改，有几次是真挣的、有几次是吹的",
        beneficiary="容易被「合并数 / 绿灯数」这类内部分喂饱、忘了回访真实使用的我自己",
        acceptance=_PY + ["-c", "import revisit,sys; m=revisit.manifest();"
                          " sys.exit(0 if {'counts','revisits','bubbles'} <= set(m) else 1)"],
        counter=_PY + ["smoke.py", "--quiet"],
        counter_why="新增这只朝后看的回访器官，不能拖垮整体——核心烟雾用例必须仍然真跑得通",
    ),
]


@dataclasses.dataclass(frozen=True)
class CheckResult:
    """一张卡复跑后的兑现状态。"""
    name: str
    acceptance_ok: bool
    counter_ok: bool
    journey_ok: bool
    detail: str            # 失败命令的现场原文；否则空

    @property
    def state(self) -> str:
        if self.acceptance_ok and self.counter_ok and self.journey_ok:
            return "delivered"      # 💎 验收、反指标、用户旅程都过：价值真兑现
        if self.acceptance_ok and not self.counter_ok:
            return "regressed"      # 🔻 赚了吆喝赔了买卖：局部好看、别处被拖垮
        return "unmet"              # ⚪ 验收/旅程没过：价值此刻兑现不了

    _MARKS = {"delivered": "💎", "regressed": "🔻", "unmet": "⚪"}
    _WORDS = {"delivered": "兑现", "regressed": "反噬", "unmet": "未兑现"}

    @property
    def mark(self) -> str:
        return self._MARKS[self.state]

    @property
    def word(self) -> str:
        return self._WORDS[self.state]

    @property
    def delivered(self) -> bool:
        return self.state == "delivered"

    def to_meta(self) -> dict:
        return {"name": self.name, "state": self.state,
                "acceptance_ok": self.acceptance_ok, "counter_ok": self.counter_ok,
                "journey_ok": self.journey_ok, "detail": self.detail}


def _run(argv: list[str]) -> tuple[bool, str]:
    """跑一条命令：退出码 0 → (True, "")。超时/起不来 → (False, 原因)，绝不抛错。"""
    try:
        proc = subprocess.run(
            argv, cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=CHECK_TIMEOUT,
        )
        if proc.returncode == 0:
            return True, ""
        return False, (proc.stderr or proc.stdout or "").strip()[-500:]
    except subprocess.TimeoutExpired:
        return False, f"命令超过 {CHECK_TIMEOUT}s 未结束"
    except Exception as e:  # noqa: BLE001  —— 核价值是观测者，起不来只是「这次没核成」
        return False, f"{type(e).__name__}: {e}"


def check(card: ValueCard) -> CheckResult:
    """复跑一张卡的验收 + 反指标 + 用户旅程，折叠成兑现状态(全程只读，不落盘)。"""
    acc_ok, acc_detail = _run(card.acceptance)
    cnt_ok, cnt_detail = _run(card.counter)
    jou_ok, jou_detail = _run(card.user_journey)
    detail = ""
    if not acc_ok:
        detail = f"验收未过：{acc_detail.splitlines()[0][:120]}" if acc_detail else "验收未过"
    elif not cnt_ok:
        detail = f"反指标变红：{cnt_detail.splitlines()[0][:120]}" if cnt_detail else "反指标变红"
    elif not jou_ok:
        detail = f"用户旅程未通：{jou_detail.splitlines()[0][:120]}" if jou_detail else "用户旅程未通"
    return CheckResult(card.name, acc_ok, cnt_ok, jou_ok, detail)


# ── 覆盖：哪些模块还没有价值卡 ────────────────────────────────────────
def _repo_modules() -> list[str]:
    """领地根目录下「像一次进化产物」的顶层 .py 模块名(排除测试/底座类脚手架)。"""
    skip = {"__init__"}
    names = []
    for p in sorted(REPO_ROOT.glob("*.py")):
        stem = p.stem
        if stem in skip or stem.startswith("_"):
            continue
        names.append(stem)
    return names


def uncovered() -> list[str]:
    """有模块、却没有任何价值卡为它绑过受益者——「只优化内部流程」的嫌疑名单。"""
    carded = {c.name for c in CARDS}
    return [m for m in _repo_modules() if m not in carded]


# ── 展示 ──────────────────────────────────────────────────────────────
def _print_cards(cards: list[ValueCard]) -> None:
    print(f"💎 opencrab 价值账本（{len(cards)} 次进化绑定了受益者）\n")
    for c in cards:
        print(f"  ◆ {c.name}")
        print(f"      场景：{c.scenario}")
        print(f"      受益者：{c.beneficiary}")
        print(f"      验收：{' '.join(c.acceptance[1:]) or c.acceptance[0]}")
        print(f"      反指标：{' '.join(c.counter[1:]) or c.counter[0]}（{c.counter_why}）")
        print(f"      用户旅程：{' '.join(c.user_journey[1:]) or c.user_journey[0]}")
    print()
    miss = uncovered()
    if miss:
        print(f"⚠️  另有 {len(miss)} 个模块还没绑过价值卡（跑 --coverage 看名单）。")
    else:
        print("💎 每个模块都至少绑过一次受益者。")


def _print_check(results: list[CheckResult]) -> None:
    print(f"💎 复核 {len(results)} 张价值卡——此刻真兑现得了吗\n")
    for r in results:
        print(f"  {r.mark} {r.name}（{r.word}）")
        if r.detail:
            print(f"      {r.detail}")
    counts = {"delivered": 0, "regressed": 0, "unmet": 0}
    for r in results:
        counts[r.state] += 1
    print(f"\n  小结：💎{counts['delivered']}  🔻{counts['regressed']}  ⚪{counts['unmet']}")
    if all(r.delivered for r in results):
        print("💎 每张价值卡都验收通过、反指标也没红——价值真兑现得了。")
    else:
        bad = [r.name for r in results if not r.delivered]
        print(f"⚠️  {len(bad)} 张卡还没兑现（未达验收或反指标变红）：{'、'.join(bad)}")


def _print_coverage(quiet: bool) -> None:
    miss = uncovered()
    if not miss:
        if not quiet:
            print("💎 领地里每个模块都至少绑过一张价值卡——没有「忘了为谁服务」的孤儿。")
        return
    print(f"⚠️  {len(miss)} 个模块还没有价值卡——它们对谁有用，我从没逼自己说清：")
    for name in miss:
        print(f"  ⚪ {name}")
    print("\n    给它们各补一张价值卡（场景/受益者/验收/反指标），或想清楚它们是否真该留着。")


def manifest() -> dict:
    """导出纯数据：全部价值卡 + 没绑卡的模块名单(给外部工具消费)。"""
    return {"cards": [c.to_meta() for c in CARDS], "uncovered": uncovered()}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 价值账本 💎")
    ap.add_argument("--check", nargs="?", const="*", metavar="NAME",
                    help="复跑验收与反指标：不带名=全部，带名=只核该张卡")
    ap.add_argument("--coverage", action="store_true",
                    help="列出还没有价值卡的模块（没绑受益者的嫌疑名单）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有未兑现/反指标变红/缺卡时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出机读价值卡清单")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if args.coverage:
        _print_coverage(args.quiet)
        sys.exit(0 if not uncovered() else 1)

    if args.check is not None:
        target = args.check
        todo = CARDS if target == "*" else [c for c in CARDS if c.name == target]
        if not todo:
            print(f"⚠️  没有名为 {target!r} 的价值卡；可选：{'、'.join(c.name for c in CARDS)}")
            sys.exit(2)
        results = [check(c) for c in todo]
        all_ok = all(r.delivered for r in results)
        if not (args.quiet and all_ok):
            _print_check(results)
        sys.exit(0 if all_ok else 1)

    if not args.quiet:
        _print_cards(CARDS)
    sys.exit(0 if not uncovered() else 1)


if __name__ == "__main__":
    main()
