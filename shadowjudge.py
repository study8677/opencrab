#!/usr/bin/env python3
"""自生手影子双跑裁判 👯🖐️ —— 同一道小修，brain 产补丁、外部手仅作对照，量清差在哪。

为什么要有它：`weaning_trial.py` 已经能让 brain 拔掉外援、独立修通几道真伤，并用「实战
通过率」把独立性钉成数字。可那是 brain **一个人**在跑——它只回答「brain 能修通几道」，
答不出「**同一道题，brain 和一只 competent 的外部手比，差在哪**」。要稳妥断奶放量，得先
量清这条差距：哪些题 brain 已能独当一面、哪些题还得靠外援、以及 brain 失手时**因为什么**
失手(无招可解？补丁越界？改完跑崩？还是能启动却没真修好？)。

本层就是那个「影子双跑裁判」：每道小修同时交给两位选手——

  · **brain**(主角)：`weaning_trial.brain_repair`，拔掉外援、读报错→挑招→自测→修不动就回滚。
  · **外部手**(对照/影子)：一只 competent 的参考手，只作对照，**永不落盘**。
    默认是「金标准参考手」(`reference_hand`，直接采用该题的标准修法当对照基线)；
    也可换成真 CLI 影子手(`make_cli_hand`)，在隔离临时副本里跑、跑完即弃，绝不碰真仓库。

两位选手对**同一段** broken 各产一个候选补丁，再用同一把尺子裁决「这候选可用吗」：
  ① 没产出改动(None / 原样交回) → 弃修；
  ② 补丁过不了 `patchcontract` 的畸形/越界拒收闸 → 契约拒收；
  ③ 候选起跑即崩(compile+exec 那句「还能不能启动」) → 自测崩；
  ④ 能启动但没满足这道题的 oracle → 没真修好；
  ⑤ 全过 → 可用 ✅。

统计：brain 可用率 vs 外部手可用率、brain 失手的**失败因直方图**、以及最关键的
**差距点**(外部手可用而 brain 不可用的那几道题，连同 brain 当场的失败因)——这就是
「断奶还差哪几仗」的体检表。

**不落盘**：本层是纯测量，全程在内存里跑，**不写任何账本、不碰真仓库**——量差距这件事
本身不该留下副作用。零第三方依赖，纯标准库；裁决永不抛错，意外形态一律收敛成「不可用」。

用法:
    python shadowjudge.py              # 影子双跑：逐题对照 brain vs 外部手 + 差距体检
    python shadowjudge.py --json       # 机读：可用率 + 失败因直方图 + 差距点
    python shadowjudge.py --selfcheck  # 自检：五类裁决都判得准 + 差距点定得对(供 evidence 复跑)
    加 --quiet 静默，仅以退出码表态。
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import io
import json
import pathlib
import sys
from typing import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import patchcontract     # noqa: E402 —— 同一把畸形/越界拒收尺，裁决两位选手的候选
import weaning_trial      # noqa: E402 —— 复用 brain 的自修(brain_repair)与自测(_self_test)

# 差距门禁：brain 可用率低于此，退出码非零，可当断奶放量前的 CI / 钩子门禁。
# 取 0.6——量差距阶段不强求全过，但要求 brain 至少能独当多数小修，否则别谈放量。
BRAIN_USABLE_FLOOR = 0.6


# ── 五类裁决因：可用 + 四种失手，稳定的码便于直方图聚合 ───────────────────────
CAUSE_OK = "ok"                    # 可用：过契约 + 自测 + oracle
CAUSE_GAVE_UP = "gave-up"          # 弃修：None 或原样交回，没产出改动
CAUSE_CONTRACT = "contract-reject"  # 契约拒收：补丁畸形/越界
CAUSE_CRASH = "self-test-crash"    # 自测崩：候选起跑即崩
CAUSE_ORACLE = "oracle-fail"       # 没真修好：能启动但 oracle 不过

CAUSE_WORDS: dict[str, str] = {
    CAUSE_OK: "可用",
    CAUSE_GAVE_UP: "弃修(无招可解/原样交回)",
    CAUSE_CONTRACT: "补丁契约拒收(畸形/越界)",
    CAUSE_CRASH: "自测崩(起跑即崩)",
    CAUSE_ORACLE: "没真修好(能启动但 oracle 不过)",
}


@dataclasses.dataclass(frozen=True)
class Verdict:
    """对一个候选补丁的裁决：可用吗、卡在哪一类、为什么。"""
    usable: bool
    cause: str    # CAUSE_*
    detail: str

    def to_meta(self) -> dict:
        return {"usable": self.usable, "cause": self.cause, "detail": self.detail}


def judge_candidate(broken: str, candidate, oracle: Callable) -> Verdict:
    """用同一把尺子裁一个候选补丁可不可用：弃修→契约→自测→oracle，全过才可用。

    永不抛错：oracle 或自测里的任何意外都收敛成「不可用」并点名失败因——裁判自己绝不能
    成为新伤口。
    """
    try:
        # ① 弃修：没产出改动(None 或原样交回)，brain 老实回滚的那种
        if candidate is None or candidate == broken:
            return Verdict(False, CAUSE_GAVE_UP, "没产出改动(无招可解/原样交回)")
        # ② 契约：补丁畸形/越界，当场拒收
        v = patchcontract.validate(broken, candidate)
        if not v.ok:
            return Verdict(False, CAUSE_CONTRACT, f"补丁契约拒收：{v.code}")
        # ③ 自测：候选起跑即崩没有(与 hands/weaning 同源的「还能不能启动」)
        exc, ns = weaning_trial._self_test(candidate)
        if exc is not None:
            return Verdict(False, CAUSE_CRASH, f"起跑即崩：{type(exc).__name__}")
        # ④ oracle：能启动只证明没改死，过了 oracle 才算真修好
        with contextlib.redirect_stdout(io.StringIO()):
            won = bool(oracle(ns))
        if not won:
            return Verdict(False, CAUSE_ORACLE, "能启动但 oracle 不过(没真修好)")
        return Verdict(True, CAUSE_OK, "可用：过契约 + 自测 + oracle")
    except Exception as e:  # noqa: BLE001 —— 裁判绝不能崩，意外即收敛为「不可用」
        return Verdict(False, CAUSE_ORACLE, f"裁决时出意外，保守判不可用：{type(e).__name__}: {e}")


# ── 选手：brain(主角) 与 外部手(对照/影子) ────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Contender:
    """一位选手：拿到一道题，产出一个候选补丁(完整新源码)，或 None 表示弃修。"""
    name: str
    produce: Callable[["ShadowCase"], "str | None"]


def brain_contender() -> Contender:
    """主角 brain：拔掉外援，只凭 brain_repair 读报错→挑招→自测→修不动就回滚。

    只看得见 broken(看不见 gold/oracle)——绝不许它偷看标准答案，才是公平的独立性度量。
    """
    return Contender("brain", lambda case: weaning_trial.brain_repair(case.broken).fixed)


def reference_hand() -> Contender:
    """对照：一只 competent 的金标准参考手——直接采用该题的标准修法当对照基线。

    它只作影子对照、**永不落盘**：候选从 case.gold 注入，代表「一只够格的外部手会怎么修」。
    这样 brain 的差距才有一条稳定、确定、零成本的基线可比。
    """
    return Contender("reference-hand", lambda case: case.gold)


def make_cli_hand(executor: str = "claude") -> Contender:
    """真 CLI 影子手(实验性)：在隔离临时副本里雇 claude/codex 改一遍，跑完即弃。

    仅作对照，**绝不碰真仓库、绝不落盘**——真要拉真手上场比时才用，默认双跑用 reference_hand
    这条零成本基线。爪子 CLI 不在场时，该手对每道题一律「弃修」(产出 None)。
    """
    import hands  # 延迟导入：默认双跑不依赖真手在场

    def produce(case: "ShadowCase") -> "str | None":
        if not hands.has_hands(executor):
            return None
        import tempfile
        with tempfile.TemporaryDirectory(prefix="shadowhand-") as d:
            target = pathlib.Path(d) / "subject.py"
            target.write_text(case.broken, encoding="utf-8")
            task = (f"文件 {target.name} 里有一处小 bug，请只改那一处把它修对："
                    f"{case.wound}。只动这一个文件，不要新增文件。")
            cmd = hands._plan_cmd(task, executor, 0.2)
            import subprocess
            try:
                subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=300)
            except Exception:  # noqa: BLE001 —— 影子手跑挂了就当弃修，绝不反噬裁判
                return None
            out = target.read_text(encoding="utf-8")
            return out if out != case.broken else None
    return Contender(f"cli:{executor}", produce)


# ── 赛题：真实小修。每道带 broken + oracle + gold(一只 competent 外部手的参考修法) ──
@dataclasses.dataclass(frozen=True)
class ShadowCase:
    name: str
    wound: str          # 这道伤是什么(人话)
    broken: str         # 跑不起来 / 跑出错答案的源码
    oracle: Callable    # 拿修好后的命名空间判「真修好了没」
    gold: str           # 一只 competent 外部手会产出的参考修法(对照基线)
    want: str           # oracle 想验的事(人话)


CASES: list[ShadowCase] = [
    # —— 前三道：brain 招式库覆盖得到(补冒号 / 括号 print / 名字纠偏)，brain 本该独当 ——
    ShadowCase(
        name="补冒号",
        wound="def 行漏了结尾冒号，源码连编译都过不去",
        broken="def add(a, b)\n    return a + b\n",
        oracle=lambda ns: ns["add"](2, 3) == 5,
        gold="def add(a, b):\n    return a + b\n",
        want="add(2,3) == 5",
    ),
    ShadowCase(
        name="括号 print",
        wound="函数体里用了 Python2 的 print 语句，编译即报缺括号",
        broken='def greet(name):\n    print "hi " + name\n    return "hi " + name\n',
        oracle=lambda ns: ns["greet"]("crab") == "hi crab",
        gold='def greet(name):\n    print("hi " + name)\n    return "hi " + name\n',
        want='greet("crab") == "hi crab"',
    ),
    ShadowCase(
        name="名字纠偏",
        wound="顶层常量调用了某函数的拼错名，模块一加载就 NameError",
        broken="def double(x):\n    return x * 2\n\nRESULT = doubel(21)\n",
        oracle=lambda ns: ns["RESULT"] == 42,
        gold="def double(x):\n    return x * 2\n\nRESULT = double(21)\n",
        want="RESULT == double(21) == 42",
    ),
    # —— 后两道：纯逻辑错，编译/加载都过，brain 招式库够不着——专照出差距 ——
    ShadowCase(
        name="算符写反",
        wound="加法写成了减法，编译能过、跑得动，但算出的是错答案",
        broken="def add(a, b):\n    return a - b\n",
        oracle=lambda ns: ns["add"](2, 3) == 5,
        gold="def add(a, b):\n    return a + b\n",
        want="add(2,3) == 5（语义错，非语法错）",
    ),
    ShadowCase(
        name="漏 return",
        wound="函数算了却忘了 return，调用永远拿到 None",
        broken="def triple(x):\n    x * 3\n",
        oracle=lambda ns: ns["triple"](4) == 12,
        gold="def triple(x):\n    return x * 3\n",
        want="triple(4) == 12（漏 return，非语法错）",
    ),
]


# ── 影子双跑：每道题两位选手各产候选、各自裁决 ───────────────────────────────
@dataclasses.dataclass(frozen=True)
class Bout:
    """一道题的双跑结果：brain 与外部手各自的裁决。"""
    case: str
    wound: str
    brain: Verdict
    hand: Verdict

    @property
    def is_gap(self) -> bool:
        """差距点：外部手可用、brain 却不可用——这正是断奶还差的那一仗。"""
        return self.hand.usable and not self.brain.usable

    def to_meta(self) -> dict:
        return {"case": self.case, "wound": self.wound, "is_gap": self.is_gap,
                "brain": self.brain.to_meta(), "hand": self.hand.to_meta()}


def run(cases: list[ShadowCase] | None = None, *,
        hand: Contender | None = None) -> list[Bout]:
    """影子双跑：每道题让 brain 与外部手对同一段 broken 各产候选，各自裁决。"""
    cases = CASES if cases is None else cases
    hand = reference_hand() if hand is None else hand
    brain = brain_contender()
    bouts: list[Bout] = []
    for c in cases:
        bv = judge_candidate(c.broken, brain.produce(c), c.oracle)
        hv = judge_candidate(c.broken, hand.produce(c), c.oracle)
        bouts.append(Bout(c.name, c.wound, bv, hv))
    return bouts


def tally(bouts: list[Bout], *, hand_name: str = "reference-hand") -> dict:
    """把双跑结果折成体检表：可用率对照 + brain 失败因直方图 + 差距点清单。"""
    n = len(bouts)
    brain_usable = sum(1 for b in bouts if b.brain.usable)
    hand_usable = sum(1 for b in bouts if b.hand.usable)
    causes: collections.Counter = collections.Counter(
        b.brain.cause for b in bouts if not b.brain.usable)
    gaps = [b for b in bouts if b.is_gap]
    return {
        "total": n,
        "hand_name": hand_name,
        "brain_usable": brain_usable,
        "brain_rate": round(brain_usable / n, 4) if n else 0.0,
        "hand_usable": hand_usable,
        "hand_rate": round(hand_usable / n, 4) if n else 0.0,
        "gap": len(gaps),
        "fail_causes": dict(causes),
        "gaps": [{"case": g.case, "cause": g.brain.cause, "detail": g.brain.detail}
                 for g in gaps],
    }


def manifest() -> dict:
    """机读快照：体检表 + 失败因码表 + 门禁阈值(给 health / 外部消费；纯测量、不落盘)。"""
    bouts = run()
    t = tally(bouts)
    return {"event": "shadowjudge", **t,
            "cause_codes": CAUSE_WORDS, "brain_usable_floor": BRAIN_USABLE_FLOOR,
            "bouts": [b.to_meta() for b in bouts]}


# ── 展示 ───────────────────────────────────────────────────────────────
def _print(bouts: list[Bout], *, hand_name: str) -> None:
    t = tally(bouts, hand_name=hand_name)
    print("👯🖐️  自生手影子双跑裁判 —— 同一道小修，brain 产补丁、外部手仅作对照（不落盘）\n")
    for b in bouts:
        mark = "🏆" if b.brain.usable else ("📐" if b.is_gap else "❌")
        print(f"  {mark} {b.case}（{b.wound}）")
        print(f"      brain : {'✅可用' if b.brain.usable else '✗ ' + CAUSE_WORDS[b.brain.cause]}"
              f" —— {b.brain.detail}")
        print(f"      {hand_name:<14}: {'✅可用' if b.hand.usable else '✗ ' + CAUSE_WORDS[b.hand.cause]}")
    print(f"\n    可用率对照：brain {t['brain_usable']}/{t['total']} = {t['brain_rate']:.0%}"
          f"  |  {hand_name} {t['hand_usable']}/{t['total']} = {t['hand_rate']:.0%}")
    if t["fail_causes"]:
        causes = "、".join(f"{CAUSE_WORDS[c]}×{k}" for c, k in t["fail_causes"].items())
        print(f"    brain 失败因：{causes}")
    if t["gaps"]:
        print(f"\n    📐 差距点（外部手能修、brain 还修不动的 {t['gap']} 仗——断奶还差这几招）：")
        for g in t["gaps"]:
            print(f"        · {g['case']}：{CAUSE_WORDS[g['cause']]}")
    else:
        print("\n    📐 无差距点：这批题外部手能修的，brain 全都修得动——可考虑放量断奶。")


# ── 自检：五类裁决都判得准 + 差距点定得对(供 evidence 复跑) ─────────────────────
def selfcheck(quiet: bool = False) -> bool:
    """自检：①五类裁决码各判得准 ②影子双跑差距点定得对 ③不落盘。供 evidence 复跑。

    全程在内存里跑，确定性、无副作用、不碰真仓库。
    """
    failures: list[str] = []

    # ① 五类裁决码：用合成候选喂裁判，每一类都得判到对的 cause 上
    base = "def f():\n    return 1\n"
    ok_oracle = lambda ns: ns["f"]() == 1  # noqa: E731
    cases_cause = [
        ("弃修(None)", base, None, ok_oracle, False, CAUSE_GAVE_UP),
        ("弃修(原样)", base, base, ok_oracle, False, CAUSE_GAVE_UP),
        ("契约拒收(越界大改)", base, "\n".join(f"x{i}=1" for i in range(40)),
         ok_oracle, False, CAUSE_CONTRACT),
        ("自测崩(加载即崩)", base, "def f():\n    return 1\nraise RuntimeError('boom')\n",
         ok_oracle, False, CAUSE_CRASH),
        ("没真修好(oracle 不过)", base, "def f():\n    return 2\n", ok_oracle, False, CAUSE_ORACLE),
        ("可用(真修对)", "def f():\n    return 2\n", "def f():\n    return 1\n",
         ok_oracle, True, CAUSE_OK),
    ]
    for label, broken, cand, oracle, want_usable, want_cause in cases_cause:
        v = judge_candidate(broken, cand, oracle)
        if v.usable != want_usable:
            failures.append(f"裁决「{label}」usable 应为 {want_usable}，实得 {v.usable}")
        elif v.cause != want_cause:
            failures.append(f"裁决「{label}」cause 应为 {want_cause}，实得 {v.cause}")

    # oracle 自身抛错也得收敛成「不可用」而非崩裁判
    boom = judge_candidate(base, "def g():\n    return 1\n", lambda ns: ns["f"]())
    if boom.usable:
        failures.append("oracle 取不到名字本应判不可用，却判了可用")

    # ② 影子双跑：reference_hand 这批题应全可用；brain 应修通前 3 道、够不着后 2 道
    bouts = run()
    t = tally(bouts)
    if t["hand_rate"] != 1.0:
        failures.append(f"参考手应在这批题上 100% 可用，实得 {t['hand_rate']:.0%}")
    if t["brain_usable"] != 3:
        failures.append(f"brain 应修通 3 道(招式库覆盖的)，实得 {t['brain_usable']}")
    if t["gap"] != 2:
        failures.append(f"差距点应为 2(纯逻辑错 brain 够不着)，实得 {t['gap']}")
    gap_cases = {g["case"] for g in t["gaps"]}
    if gap_cases != {"算符写反", "漏 return"}:
        failures.append(f"差距点应是「算符写反 / 漏 return」，实得 {gap_cases}")
    # 差距点上 brain 的失败因应是「弃修」——这两道编译/加载都过，brain 无招可解、原样交回
    if any(g["cause"] != CAUSE_GAVE_UP for g in t["gaps"]):
        failures.append("差距点上 brain 的失败因应是 gave-up(无招可解/原样交回)")

    # ③ 不落盘：本层是纯测量，跑完一轮不该留下任何自家账本
    if (REPO_ROOT / "state" / "shadowjudge.jsonl").exists():
        failures.append("影子双跑不该落盘，却发现 state/shadowjudge.jsonl")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ shadowjudge selfcheck：五类裁决判得准、差距点定得对、且不落盘——影子双跑裁判可信。")
        else:
            print("❌ shadowjudge selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手影子双跑裁判 👯🖐️")
    ap.add_argument("--json", action="store_true", help="机读：可用率 + 失败因直方图 + 差距点")
    ap.add_argument("--selfcheck", action="store_true", help="自检模式(供 evidence 复跑)")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    bouts = run()
    t = tally(bouts)
    if args.json:
        if not args.quiet:
            print(json.dumps(manifest(), ensure_ascii=False, indent=2))
    elif not args.quiet:
        _print(bouts, hand_name="reference-hand")
    sys.exit(0 if t["brain_rate"] >= BRAIN_USABLE_FLOOR else 1)


if __name__ == "__main__":
    main()
