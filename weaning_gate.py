#!/usr/bin/env python3
"""自生手断奶守门闸 🚪🍼 —— 低风险小修默认走 brain-only，**只有失败才降级雇外援，且每次降级都如实记账**。

为什么要有它：断奶的零件早齐了——`triage` 会挑安全的活、`tiergate` 排出可接的阶梯、
`weaning_trial` 让 brain 不雇外援自己产补丁→自测→修不动就回滚、`weaning_relay` 把一处真小修
从头领到尾、`autonomy_meter` 把脱钩率钉成趋势线。可它们都缺一条**路由默认值的纪律**：
当一处低风险小修摆在面前，**默认该让谁上？** 过去这仍是临场拍脑袋——心一虚就顺手雇外援，
于是「明明 brain 自己能办」的活也被外包出去，断奶永远差最后一口气。

守门闸补的就是这一环:**断奶的默认路由 + 失败才降级的记账**。它不发明招式、不自己想补丁
(招式与赛题的单一真相源始终是 `weaning_trial`)，只把「该让谁上」这一拍板钉成一条可核对的策略：

  1) 🚪 **默认 brain-only(decide)**：先用一条**可计算的入场判据**判这活在不在 brain 的断奶范围内——
       「启动期就崩」(编译/加载即报错)的小修正是 brain 招式所长，**一律默认派 brain 单独上**，
       不再因心虚而预先外包。能编译能加载、只是算错的活(语义伤)还超出当前范围，**才**预先走外援
       (`route="external"`)——这叫「还没断到这口奶」，不算降级。

  2) 🍼→🤝 **失败才降级(downgrade)**：默认派给 brain 的活，brain 真上场修(复用 `weaning_trial.fight`)。
       修通了 = **自足断奶**(SELF 🍼✅)；修不动/没真修好，**才**降级雇外援(DOWNGRADE 🍼→🤝)——
       而且每降一次都**当场记一笔账**：降在哪道活、为什么(brain 的回滚轨迹/没赢的判据)。
       降级不是悄悄发生的退让，是一条留痕的、事后能复盘的账目。

  3) 🧾 **断奶账(stats)**：把账本收敛成两个能上趋势线的数——
       · **断奶率** = brain 自足的活 / 默认派给 brain 的活：派出去的，brain 自己扛下了几成。
       · **降级率** = 降级的活 / 默认派给 brain 的活：派出去又不得不雇外援的占比，越低越接近真断奶。
       再摊开**每一笔降级的缘由**：这些「brain 还接不住」的活，才是下一刀该补的招式缺口。

**失败降级探针**：除了三道必胜的真伤(brain 该自足)，再放两道反例——
  · 一道**顶层 raise** 的伤(启动期崩、入场判据放行 brain 上，但哪招都治不了)：必然走「brain 失败→降级→记账」，
    这是「失败才降级且留痕」这条路径的**实测证据**，而非一句断言；
  · 一道**能编译能跑、只是算错**的语义伤(超出当前断奶范围)：必然**预先**走外援、且**不计为降级**——
    证明守门闸不会把「还没断到的奶」误记成「降级」，账目分得清。

设计与全家一致：零第三方依赖、纯标准库；守门闸是参谋/守门，全程在内存里跑合成赛题、绝不碰真仓库源码，
读盘/依赖缺席一律吞掉收敛成保守判断(判不准就当「超出范围、走外援」，绝不冒进默认 brain)，
绝不反噬动手主流程——给手定默认路由的层，自己不能成为新的伤口。

用法:
    python weaning_gate.py             # 跑一遍守门:逐活路由 + 断奶率/降级率 + 每笔降级缘由(并记账)
    python weaning_gate.py --json      # 机读:逐活决策 + 两个率(给 health / autonomy_meter 消费)
    python weaning_gate.py --dry       # 只看决策,不记账
    python weaning_gate.py --stats     # 只复盘历史账本:断奶率/降级率趋势 + 降级缘由
    python weaning_gate.py --selfcheck # 自检:三真伤自足 / raise 探针确走「失败→降级→记账」/ 语义伤预路由不计降级
    加 --quiet 静默,仅以退出码表态。

零第三方依赖,纯标准库。与 `weaning_relay`(把一处小修从头领到尾)、`tiergate`(可接阶梯)互补:
那两条管「怎么跑、能跑多难」，这条管「该让谁上、什么时候才许降级」——断奶的默认路由纪律。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class HandsWeaningDecision:
    """Decision record for routing hands.py through weaning by default."""

    use_brain_only: bool
    reason: str
    downgrade_reason: str = ""


def hands_default_decision(
    *,
    intent: str = "",
    risk: str = "low",
    brain_only_failed: bool = False,
    failure_reason: str = "",
    context: Mapping[str, Any] | None = None,
) -> HandsWeaningDecision:
    """Choose the default hands route during weaning.

    Low-risk self edits should first try the brain-only fitting room.  External
    help is only selected after that attempt fails, and the downgrade reason is
    kept explicit so callers can persist it in their own ledger.
    """

    normalized_risk = (risk or "low").strip().lower()
    if normalized_risk in {"low", "safe", "routine", "small"} and not brain_only_failed:
        return HandsWeaningDecision(
            use_brain_only=True,
            reason="weaning_default_low_risk_brain_only_first",
        )

    reason = failure_reason.strip() if failure_reason else ""
    if brain_only_failed:
        reason = reason or "brain_only_attempt_failed"
    elif normalized_risk not in {"low", "safe", "routine", "small"}:
        reason = f"risk_not_low:{normalized_risk}"
    else:
        reason = "external_fallback_requested"

    return HandsWeaningDecision(
        use_brain_only=False,
        reason="weaning_default_external_fallback",
        downgrade_reason=reason,
    )


def run_hands_default(
    brain_only: Callable[[], Any],
    external: Callable[[str], Any],
    *,
    intent: str = "",
    risk: str = "low",
    record: Callable[[str], None] | None = None,
) -> Any:
    """Run hands default route: brain-only first for low-risk edits, else fallback."""

    first = hands_default_decision(intent=intent, risk=risk)
    if first.use_brain_only:
        try:
            return brain_only()
        except Exception as exc:  # noqa: BLE001 - fallback must preserve downgrade reason
            downgrade = hands_default_decision(
                intent=intent,
                risk=risk,
                brain_only_failed=True,
                failure_reason=f"{exc.__class__.__name__}: {exc}",
            )
            if record is not None:
                record(downgrade.downgrade_reason)
            return external(downgrade.downgrade_reason)

    if record is not None:
        record(first.downgrade_reason)
    return external(first.downgrade_reason)

import argparse
import dataclasses
import json
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore        # noqa: E402 —— 复用「追一条/读一批」的安全落地层
import weaning_trial     # noqa: E402 —— 招式、赛题、fight、自测的单一真相源；本层只定路由、绝不重写

GATE_LOG = REPO_ROOT / "state" / "weaning_gate.jsonl"

# ── 三种归宿:一处小修最终落到谁手里 ──────────────────────────────────────
OUTCOME_SELF = "SELF"            # 🍼✅ 默认派 brain，brain 自足修通——一次成功的断奶
OUTCOME_DOWNGRADE = "DOWNGRADE"  # 🍼→🤝 默认派 brain，brain 没扛住——失败才降级雇外援,记一笔账
OUTCOME_EXTERNAL = "EXTERNAL"    # 🤝 超出当前断奶范围,预先走外援——「还没断到这口奶」,不计降级
OUTCOME_ICON = {OUTCOME_SELF: "🍼✅", OUTCOME_DOWNGRADE: "🍼→🤝", OUTCOME_EXTERNAL: "🤝"}


def in_brain_scope(broken: str) -> tuple[bool, str]:
    """入场判据:这活在不在 brain 当前的断奶范围内?

    判准只有一条、且可计算:**启动期就崩**(编译/加载即报错)的小修,正是 brain 招式
    (补冒号 / print 括号 / 名字纠偏)所长——默认放 brain 单独上。能编译能加载、只是算错的
    语义伤,还超出当前范围,预先走外援。判不准(自测自身炸了)一律保守当「超出范围」,
    绝不冒进默认 brain——守门闸宁可少断一口奶,也不把 brain 推去接它接不住的活。
    """
    try:
        exc, _ns = weaning_trial._self_test(broken)
    except Exception as e:  # noqa: BLE001 —— 连自测都炸,保守判出范围
        return False, f"入场自测自身异常({type(e).__name__})——保守判定超出范围,走外援"
    if exc is None:
        return False, "能编译能加载、只是算错(语义伤)——超出当前断奶范围,预先走外援"
    return True, f"启动期就崩({type(exc).__name__})——正是 brain 招式所长,默认 brain-only"


@dataclasses.dataclass
class Decision:
    """守门闸对一处小修的一次拍板。"""
    name: str
    wound: str
    route: str                 # "brain" | "external"——最终落到谁手里
    outcome: str               # SELF / DOWNGRADE / EXTERNAL
    downgraded: bool           # 是否是「默认派 brain 又不得不降级」(只有 DOWNGRADE 为真)
    reason: str                # 入场判据 / brain 的战果细节 / 降级缘由

    def to_meta(self) -> dict:
        return {"name": self.name, "wound": self.wound, "route": self.route,
                "outcome": self.outcome, "downgraded": self.downgraded, "reason": self.reason}


def decide(c: "weaning_trial.Challenge") -> Decision:
    """对一道小修守门:默认 brain-only,失败才降级;超出范围的预先走外援。"""
    elig, why = in_brain_scope(c.broken)
    if not elig:
        # 超出当前断奶范围:预先走外援。这不是降级——是「还没断到这口奶」。
        return Decision(c.name, c.wound, route="external", outcome=OUTCOME_EXTERNAL,
                        downgraded=False, reason=why)
    # 默认派 brain 单独上,让它真上场修(复用单一真相源的 fight,绝不自己产补丁)。
    bout = weaning_trial.fight(c)
    if bout.won:
        return Decision(c.name, c.wound, route="brain", outcome=OUTCOME_SELF,
                        downgraded=False, reason=f"{why}|brain 自足修通:{bout.detail}")
    # brain 没扛住——失败才降级雇外援,并把缘由记进这一笔账。
    return Decision(c.name, c.wound, route="external", outcome=OUTCOME_DOWNGRADE,
                    downgraded=True, reason=f"brain 未竟,降级雇外援:{bout.detail}")


# ── 守门赛题:三道必胜真伤 + 两道反例探针 ─────────────────────────────────
# 反例一:顶层 raise——入场放行 brain 上,但哪招都治不了,必走「失败→降级→记账」。
RAISE_PROBE = weaning_trial.Challenge(
    name="降级探针·顶层raise",
    wound="顶层直接 raise,启动即崩(入场放行),但任何招式都治不了——专验「失败才降级且留痕」",
    broken='raise RuntimeError("brain 治不了的伤")\n',
    oracle=lambda ns: False,
    want="brain 修不动 → 降级雇外援 + 记一笔账(而非悄悄外包或硬塞坏补丁)",
)
# 反例二:能编译能跑、只是算错——语义伤,超出当前断奶范围,必预路由外援、不计降级。
SEMANTIC_PROBE = weaning_trial.Challenge(
    name="范围外·语义伤",
    wound="函数能编译能跑、只是把加号写成减号(算错),没有任何启动期异常指路——超出当前断奶范围",
    broken="def add(a, b):\n    return a - b\n",
    oracle=lambda ns: ns["add"](2, 3) == 5,
    want="守门闸预先走外援、不计为降级(分清「还没断到的奶」与「降级」)",
)

# 守门跑道:三真伤(该自足) + 两探针(该降级 / 该预路由外援)。
GATE_TASKS: list["weaning_trial.Challenge"] = [*weaning_trial.CHALLENGES, RAISE_PROBE, SEMANTIC_PROBE]


@dataclasses.dataclass
class GateRun:
    """一趟守门的全部决策 + 两个率。"""
    decisions: list[Decision]

    @property
    def brain_dispatched(self) -> list[Decision]:
        """默认派给 brain 的活(SELF + DOWNGRADE)——断奶率/降级率的分母。"""
        return [d for d in self.decisions if d.outcome in (OUTCOME_SELF, OUTCOME_DOWNGRADE)]

    @property
    def weaned_rate(self) -> float:
        """断奶率 = brain 自足的活 / 默认派给 brain 的活。"""
        dispatched = self.brain_dispatched
        if not dispatched:
            return 0.0
        return sum(1 for d in dispatched if d.outcome == OUTCOME_SELF) / len(dispatched)

    @property
    def downgrade_rate(self) -> float:
        """降级率 = 降级的活 / 默认派给 brain 的活。"""
        dispatched = self.brain_dispatched
        if not dispatched:
            return 0.0
        return sum(1 for d in dispatched if d.downgraded) / len(dispatched)

    @property
    def downgrades(self) -> list[Decision]:
        return [d for d in self.decisions if d.downgraded]


def run(tasks: list["weaning_trial.Challenge"] | None = None) -> GateRun:
    """跑一遍守门:对每道小修拍板该让谁上。"""
    tasks = GATE_TASKS if tasks is None else tasks
    return GateRun([decide(c) for c in tasks])


def _record(gr: GateRun) -> None:
    """把一趟守门落进账本——每一笔决策一行,降级缘由可事后复盘。记账失败被吞掉,绝不反噬。"""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    append_jsonl = jsonlstore.append_jsonl
    append_jsonl(GATE_LOG, {
        "ts": ts,
        "kind": "summary",
        "weaned_rate": round(gr.weaned_rate, 4),
        "downgrade_rate": round(gr.downgrade_rate, 4),
        "dispatched": len(gr.brain_dispatched),
        "downgrades": len(gr.downgrades),
    })
    for d in gr.decisions:
        rec = {"ts": ts, "kind": "decision", **d.to_meta()}
        append_jsonl(GATE_LOG, rec)


def _print(gr: GateRun) -> None:
    print("🚪🍼 自生手断奶守门闸 —— 低风险小修默认 brain-only,失败才降级记账\n")
    for d in gr.decisions:
        icon = OUTCOME_ICON.get(d.outcome, "·")
        print(f"  {icon} {d.name}（{d.wound}）")
        print(f"      └ 落到 {d.route}：{d.reason}")
    disp = len(gr.brain_dispatched)
    print(f"\n  默认派给 brain：{disp} 道")
    print(f"  断奶率（自足/派出）：{gr.weaned_rate:.0%}")
    print(f"  降级率（降级/派出）：{gr.downgrade_rate:.0%}")
    if gr.downgrades:
        print("\n  🧾 降级账（brain 还接不住、下一刀该补的招式缺口）：")
        for d in gr.downgrades:
            print(f"      · {d.name}：{d.reason}")
    else:
        print("\n  🧾 本趟无降级——派给 brain 的活全数自足 🍼✅")


def _stats() -> dict:
    """复盘历史账本:历次 summary 的两个率 + 摊开降级缘由。"""
    rows = jsonlstore.read_jsonl(GATE_LOG)
    summaries = [r for r in rows if r.get("kind") == "summary"]
    downgrades = [r for r in rows if r.get("kind") == "decision" and r.get("downgraded")]
    return {
        "runs": len(summaries),
        "weaned_rate_series": [r.get("weaned_rate") for r in summaries],
        "downgrade_rate_series": [r.get("downgrade_rate") for r in summaries],
        "latest_weaned_rate": summaries[-1].get("weaned_rate") if summaries else None,
        "latest_downgrade_rate": summaries[-1].get("downgrade_rate") if summaries else None,
        "downgrade_reasons": [{"name": r.get("name"), "reason": r.get("reason")} for r in downgrades],
    }


def manifest() -> dict:
    """守门闸的能力清单（给 skillgraph / health 等盘点者读）。"""
    return {
        "module": "weaning_gate",
        "role": "断奶默认路由守门闸:低风险小修默认 brain-only,失败才降级且记账",
        "outcomes": list(OUTCOME_ICON.keys()),
        "log": str(GATE_LOG.relative_to(REPO_ROOT)),
        "tasks": [c.name for c in GATE_TASKS],
        "single_source": "weaning_trial",
    }


def selfcheck(quiet: bool = False) -> bool:
    """自检:三真伤自足 / raise 探针走「失败→降级→记账」/ 语义伤预路由且不计降级。"""
    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        ok = ok and cond
        if not quiet:
            print(f"  {'✅' if cond else '❌'} {msg}")

    gr = run()
    by_name = {d.name: d for d in gr.decisions}

    # 1) 三道必胜真伤:默认派 brain 且自足修通,既不预路由外援、也不降级。
    for c in weaning_trial.CHALLENGES:
        d = by_name.get(c.name)
        check(d is not None and d.outcome == OUTCOME_SELF and d.route == "brain" and not d.downgraded,
              f"真伤「{c.name}」默认 brain-only 且自足断奶(SELF,未降级)")

    # 2) raise 探针:入场放行 brain 上,brain 治不了 → 失败才降级 + 留痕记账。
    rp = by_name.get(RAISE_PROBE.name)
    check(rp is not None and rp.outcome == OUTCOME_DOWNGRADE and rp.downgraded and rp.route == "external",
          "raise 探针:brain 失败 → 降级雇外援(DOWNGRADE,留痕)——「失败才降级」路径确触发")

    # 3) 语义伤:超出范围,预先走外援,且**不**计为降级(分清「还没断到的奶」与「降级」)。
    sp = by_name.get(SEMANTIC_PROBE.name)
    check(sp is not None and sp.outcome == OUTCOME_EXTERNAL and not sp.downgraded and sp.route == "external",
          "语义伤:超出范围预路由外援(EXTERNAL),且不计为降级——账目分得清")

    # 4) 两个率算得对:派出 4 道(3 真伤 + raise 探针),自足 3、降级 1。
    check(len(gr.brain_dispatched) == 4, f"分母正确:默认派给 brain 共 4 道(实得 {len(gr.brain_dispatched)})")
    check(abs(gr.weaned_rate - 0.75) < 1e-9, f"断奶率 = 3/4 = 75%(实得 {gr.weaned_rate:.0%})")
    check(abs(gr.downgrade_rate - 0.25) < 1e-9, f"降级率 = 1/4 = 25%(实得 {gr.downgrade_rate:.0%})")

    # 5) 入场判据本身:启动崩=入场,能跑=出场——可计算、不靠感觉。
    check(in_brain_scope("def f(\n")[0] is True, "入场判据:编译就崩 → 判入场(brain 招式所长)")
    check(in_brain_scope("X = 1\n")[0] is False, "入场判据:能编译能加载 → 判出场(超出范围)")

    if not quiet:
        print(f"\n{'✅ 守门闸自检通过' if ok else '❌ 守门闸自检未通过'}")
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="自生手断奶守门闸:低风险小修默认 brain-only,失败才降级记账")
    ap.add_argument("--json", action="store_true", help="机读:逐活决策 + 两个率")
    ap.add_argument("--dry", action="store_true", help="只看决策,不记账")
    ap.add_argument("--stats", action="store_true", help="复盘历史账本:两个率趋势 + 降级缘由")
    ap.add_argument("--selfcheck", action="store_true", help="自检(供 evidence 复跑)")
    ap.add_argument("--quiet", action="store_true", help="静默,仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    if args.stats:
        st = _stats()
        if args.json:
            print(json.dumps(st, ensure_ascii=False, indent=2))
        elif not args.quiet:
            print(f"🧾 守门账本复盘：{st['runs']} 趟")
            print(f"  最近断奶率：{st['latest_weaned_rate']}　最近降级率：{st['latest_downgrade_rate']}")
            for r in st["downgrade_reasons"]:
                print(f"  · 降级 {r['name']}：{r['reason']}")
        sys.exit(0)

    gr = run()
    if not args.dry:
        _record(gr)
    if args.json:
        print(json.dumps({
            "decisions": [d.to_meta() for d in gr.decisions],
            "weaned_rate": round(gr.weaned_rate, 4),
            "downgrade_rate": round(gr.downgrade_rate, 4),
            "dispatched": len(gr.brain_dispatched),
            "downgrades": len(gr.downgrades),
        }, ensure_ascii=False, indent=2))
    elif not args.quiet:
        _print(gr)


if __name__ == "__main__":
    main()
