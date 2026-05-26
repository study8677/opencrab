#!/usr/bin/env python3
"""节拍 🥁 —— 把「需求→落地」一圈拆成五拍，量出每拍**耗多少时、产多少值**，
再揪出两种最该动手的环节：**能并行省掉的干等**，和**花得多、产得少**的低收益拍。

为什么要有它：领地里已经有摩擦账本(friction)记「哪一步不顺」、有审计(audit)记「这次
怎么跑的」、有时间线(timeline)把提交/运行/记忆缝成一条线。它们各看一面，却没人把三股
证据**叠到同一根节拍上**回答提速前最先要问的那句话——**我到底慢在哪一拍、那一拍慢得
值不值？** 没有这张账，提速全凭手感：要么去优化一个本就不费时的环节，要么把力气砸在
一个再快也产不出东西的拍上。**提速前先要知道慢在哪,且那处慢得冤不冤。**

一圈五拍,沿用摩擦账本的「需求→验证」五段(单一真相源,口径一致)：
    intent(读需求) · plan(定方案) · build(动手做) · verify(自测验证) · land(落地合并)

每拍钉两个量,各从最该负责的那股证据派生:
  · 耗时(cost) —— 这一拍**磨掉多少分钟**。取自摩擦账本按阶段汇总:它记的正是「这段
        花了多久、其中多少是纯干等」。这是唯一**实测的、按拍可分的**时间。
  · 产出(yield) —— 这一拍**端出多少件可见的值**。按「值在哪一拍落地」把另两股证据派到拍上:
        land  ← 提交(每条 commit = 一件交付出去的值)
        build ← 审计里真改了代码的运行(changed)
        verify← 审计里没翻车、走到收场的运行(过了自测)
        intent← 形成过意图的运行(起了个头,值最虚)
        plan  ← 审计里做过的决策步(权衡也是产出,但只是过程)

有了「耗时 × 产出」,每拍的**收益率 = 产出 / 每分钟**就出来了,两类环节随之浮现:

  · 🔀 可并行 —— 这一拍的耗时大头是**干等**(摩擦里的 wait)。人闲着只等外部过程跑完,
        是教科书级的并行/后台/缓存候选:把同步的等改成异步,这段时间近乎白捡回来。
  · 🐌 低收益 —— 这一拍**耗时在中位以上、收益率却在中位以下**:花得多、产得少的时间沟。
        提速的钱该先砸这儿,而不是去拧一个本就不费时、或再快也产不出东西的拍。

另有一个**整圈**视角(每拍耗时/收益的总账):从审计的真实墙钟,算出平均**每次心跳跑多久**、
其中**多少比例真改了东西**(价值命中率)——回答「一拍下来,时间换没换来东西」。

判准:节拍是观测者——只读 friction / audit / git log 三处既有证据派生,**不执行、不落盘、
不改任何账本**。证据不足时闭嘴(攒够样本才敢点名),读不到的源当空,绝不反噬生命。

用法:
    python cadence.py             # 五拍节拍表 + 整圈每拍耗时/收益 + 可并行/低收益环节
    python cadence.py --since 14  # 把回看窗口收/放到近 N 天(默认 14)
    python cadence.py --quiet     # 只在「攒够样本且确有可并行/低收益环节」时说话(钩子/CI)
    python cadence.py --json      # 机读:导出五拍量化 + 整圈指标 + 两类环节

零第三方依赖,纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import friction  # noqa: E402  —— 复用五段定义与摩擦账本读取(单一真相源)

DEFAULT_SINCE = 14

# 攒够这么多「拍」(有耗时或有产出的拍)才敢点名低收益——样本太少,中位数没意义。
MIN_BEATS = 3
# 整圈视角:攒够这么多次运行才敢报「每拍耗时/价值命中率」。
MIN_RUNS = 3

# 五拍按时间顺序,沿用摩擦账本的阶段(口径一致)。
STAGES = friction.STAGES  # {"intent": "读需求", ...}
_ORDER = list(STAGES)


# ══ 三股证据 → 按拍量化 ══════════════════════════════════════════════════
def _cost_by_stage(since_days: int) -> tuple[dict[str, float], dict[str, float]]:
    """摩擦账本按阶段汇总:返回 (每拍总耗分钟, 每拍其中的纯干等分钟)。读不到当空。"""
    cost: dict[str, float] = {s: 0.0 for s in _ORDER}
    wait: dict[str, float] = {s: 0.0 for s in _ORDER}
    try:
        items = friction.load(since_days)
    except Exception:
        items = []
    for f in items:
        if f.stage in cost:
            cost[f.stage] += f.cost
            if f.kind == "wait":
                wait[f.stage] += f.cost
    return cost, wait


@dataclasses.dataclass(frozen=True)
class RunFacts:
    """从审计派生的整圈事实:跑了几次、平均墙钟、价值命中(真改了东西)几次。"""
    runs: int
    changed: int          # 真改了代码的运行数(价值命中)
    passed: int           # 没翻车、走到收场的运行数
    decisions: int        # 决策步总数(分到 plan 拍)
    wall_seconds: list[float]  # 每次运行的墙钟秒(用于算平均每拍耗时)

    @property
    def avg_wall(self) -> float:
        return sum(self.wall_seconds) / len(self.wall_seconds) if self.wall_seconds else 0.0

    @property
    def hit_rate(self) -> float:
        """价值命中率:真改了东西的运行 / 总运行。"""
        return self.changed / self.runs if self.runs else 0.0


def _parse_ts(ts: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _run_facts(since_days: int) -> RunFacts:
    """近 N 天审计:逐次运行统计墙钟、是否真改、是否过关、决策步数。读不到当空。"""
    try:
        import audit
    except Exception:
        return RunFacts(0, 0, 0, 0, [])
    runs = changed = passed = decisions = 0
    walls: list[float] = []
    today = datetime.date.today()
    for delta in range(since_days + 1):
        day = (today - datetime.timedelta(days=delta)).isoformat()
        try:
            traces = audit.reconstruct(day)
        except Exception:
            continue
        for t in traces:
            runs += 1
            if not t.failed:
                passed += 1
            steps = t.steps
            decisions += sum(1 for s in steps if s.event == "decision")
            if any(s.event == "act" and s.fields.get("changed") for s in steps):
                changed += 1
            start, end = _parse_ts(t.started_at), _parse_ts(t.ended_at)
            if start and end and end >= start:
                walls.append((end - start).total_seconds())
    return RunFacts(runs, changed, passed, decisions, walls)


def _commit_count(since_days: int) -> int:
    """近 N 天的提交数(每条 = land 拍的一件交付)。复用 timeline 的 git 派生。"""
    try:
        import timeline
        return len(timeline._commit_events(since_days))
    except Exception:
        return 0


# ── 把产出按「值在哪一拍落地」派到拍上 ───────────────────────────────────
def _yield_by_stage(facts: RunFacts, commits: int) -> dict[str, float]:
    """每拍产出单位:land←提交, build←真改运行, verify←过关运行, intent←总运行, plan←决策步。"""
    return {
        "intent": float(facts.runs),
        "plan": float(facts.decisions),
        "build": float(facts.changed),
        "verify": float(facts.passed),
        "land": float(commits),
    }


# ══ 一拍 ════════════════════════════════════════════════════════════════
@dataclasses.dataclass(frozen=True)
class Beat:
    """节拍表的一拍:这一段磨多少时(含多少干等)、端出多少值、收益率几何。"""
    stage: str
    cost_min: float      # 这一拍磨掉的分钟(摩擦账本汇总)
    wait_min: float      # 其中纯干等的分钟
    units: float         # 这一拍端出的产出单位

    @property
    def label(self) -> str:
        return STAGES.get(self.stage, self.stage)

    @property
    def rate(self) -> float | None:
        """收益率 = 产出 / 每分钟。这一拍没记耗时(无从评)→ None。"""
        return self.units / self.cost_min if self.cost_min > 0 else None

    @property
    def wait_share(self) -> float:
        """干等占这一拍耗时的比例(0~1);没记耗时记 0。"""
        return self.wait_min / self.cost_min if self.cost_min > 0 else 0.0

    @property
    def parallelizable(self) -> bool:
        """耗时大头是干等(过半)→ 可并行/后台/缓存的候选。"""
        return self.cost_min > 0 and self.wait_share >= 0.5

    def to_meta(self) -> dict:
        return {"stage": self.stage, "label": self.label,
                "cost_min": round(self.cost_min, 1), "wait_min": round(self.wait_min, 1),
                "units": round(self.units, 1),
                "rate": (round(self.rate, 3) if self.rate is not None else None),
                "wait_share": round(self.wait_share, 2),
                "parallelizable": self.parallelizable}


def build_beats(since_days: int) -> tuple[list[Beat], RunFacts]:
    """把三股证据叠到五拍上,按 _ORDER 返回五拍 + 整圈事实。"""
    cost, wait = _cost_by_stage(since_days)
    facts = _run_facts(since_days)
    units = _yield_by_stage(facts, _commit_count(since_days))
    beats = [Beat(stage=s, cost_min=cost[s], wait_min=wait[s], units=units[s])
             for s in _ORDER]
    return beats, facts


# ── 两类环节:可并行 / 低收益 ─────────────────────────────────────────────
def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def parallel_beats(beats: list[Beat]) -> list[Beat]:
    """可并行的拍:干等过半,耗时降序——干等越多越先治。"""
    return sorted((b for b in beats if b.parallelizable),
                  key=lambda b: b.wait_min, reverse=True)


def low_yield_beats(beats: list[Beat]) -> list[Beat]:
    """低收益的拍:耗时在中位以上、收益率却在中位以下——花得多、产得少的时间沟。

    只在攒够拍(有耗时的拍 ≥ MIN_BEATS)时才点名;否则中位数不可信,返回空。
    纯干等的拍交给「可并行」治,不在这里重复点名。
    """
    timed = [b for b in beats if b.cost_min > 0 and b.rate is not None]
    if len(timed) < MIN_BEATS:
        return []
    cost_mid = _median([b.cost_min for b in timed])
    rate_mid = _median([b.rate for b in timed])  # type: ignore[misc]
    sinks = [b for b in timed
             if b.cost_min >= cost_mid and b.rate <= rate_mid and not b.parallelizable]
    return sorted(sinks, key=lambda b: (b.rate, -b.cost_min))  # type: ignore[arg-type]


# ══ 渲染 ════════════════════════════════════════════════════════════════
def _fmt_rate(b: Beat) -> str:
    if b.rate is None:
        return "—（未记耗时）"
    return f"{b.rate:.2f} 件/分"


def _print_table(beats: list[Beat]) -> None:
    total_cost = sum(b.cost_min for b in beats)
    total_units = sum(b.units for b in beats)
    if total_cost == 0 and total_units == 0:
        print("🥁 节拍表还空着——既没有摩擦耗时,也没有运行/提交产出可叠。")
        print("   先用 `python friction.py log ...` 记几处耗时,跑几次心跳,再回来量节拍。")
        return
    print(f"🥁 opencrab 节拍表（五拍 / 合计 {total_cost:.0f} 分钟 / {total_units:.0f} 件产出）\n")
    for i, b in enumerate(beats, 1):
        wait_tail = f"，其中干等 {b.wait_min:.0f}" if b.wait_min > 0 else ""
        flag = "  🔀可并行" if b.parallelizable else ""
        print(f"  {i}. {b.label}（{b.stage}）"
              f"耗 {b.cost_min:.0f} 分{wait_tail} · 产 {b.units:.0f} 件 · 收益 {_fmt_rate(b)}{flag}")


def _print_cycle(facts: RunFacts) -> None:
    if facts.runs < MIN_RUNS:
        print(f"  整圈视角:运行样本不足 {MIN_RUNS} 次,先多跑几拍心跳再算平均耗时/命中率。")
        return
    avg = facts.avg_wall
    avg_str = f"{avg:.0f} 秒" if avg < 90 else f"{avg / 60:.1f} 分"
    print(f"  整圈视角（近窗口 {facts.runs} 次心跳）:"
          f"平均每拍跑 {avg_str} · 价值命中率 {facts.hit_rate * 100:.0f}%"
          f"（{facts.changed}/{facts.runs} 次真改了东西）")


def _print_findings(parallel: list[Beat], low: list[Beat]) -> None:
    if parallel:
        print("\n🔀 可并行环节（干等过半,改成异步/后台/缓存近乎白捡回时间）：")
        for b in parallel:
            print(f"    · {b.label}：干等 {b.wait_min:.0f} 分 / 共 {b.cost_min:.0f} 分"
                  f"（{b.wait_share * 100:.0f}%）")
    if low:
        print("\n🐌 低收益环节（耗时中位以上、收益率中位以下,提速的钱先砸这儿）：")
        for b in low:
            print(f"    · {b.label}：耗 {b.cost_min:.0f} 分 · 产 {b.units:.0f} 件 · 收益 {_fmt_rate(b)}")
    if not parallel and not low:
        print("\n✅ 没揪出明显的可并行干等或低收益时间沟——节奏暂时还算紧。")


def manifest(since_days: int) -> dict:
    """导出机读:五拍量化 + 整圈指标 + 两类环节。"""
    beats, facts = build_beats(since_days)
    parallel = parallel_beats(beats)
    low = low_yield_beats(beats)
    cycle = {
        "runs": facts.runs,
        "avg_wall_seconds": round(facts.avg_wall, 1),
        "hit_rate": round(facts.hit_rate, 3),
        "changed": facts.changed,
        "enough_runs": facts.runs >= MIN_RUNS,
    }
    return {
        "since_days": since_days,
        "beats": [b.to_meta() for b in beats],
        "cycle": cycle,
        "parallelizable": [b.to_meta() for b in parallel],
        "low_yield": [b.to_meta() for b in low],
    }


def _has_findings(parallel: list[Beat], low: list[Beat]) -> bool:
    return bool(parallel or low)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 节拍 🥁:从审计/提交/摩擦量化每拍耗时-收益,揪可并行与低收益环节。")
    ap.add_argument("--since", type=int, default=DEFAULT_SINCE, metavar="N",
                    help=f"只看近 N 天(默认 {DEFAULT_SINCE})")
    ap.add_argument("--quiet", action="store_true",
                    help="只在攒够样本且确有可并行/低收益环节时说话(钩子 / CI)")
    ap.add_argument("--json", action="store_true",
                    help="导出机读:五拍量化 + 整圈指标 + 两类环节")
    args = ap.parse_args(argv)

    since = args.since if args.since and args.since > 0 else DEFAULT_SINCE

    if args.json:
        print(json.dumps(manifest(since), ensure_ascii=False, indent=2))
        sys.exit(0)

    beats, facts = build_beats(since)
    parallel = parallel_beats(beats)
    low = low_yield_beats(beats)

    if args.quiet:
        if _has_findings(parallel, low):
            n = len(parallel) + len(low)
            print(f"🥁 节拍:揪出 {n} 个待治环节"
                  f"（{len(parallel)} 可并行 / {len(low)} 低收益）——跑 `cadence.py` 看明细。")
            sys.exit(1)
        sys.exit(0)

    _print_table(beats)
    print()
    _print_cycle(facts)
    _print_findings(parallel, low)
    print("\n  节拍只观测、不拍板:它把「我感觉慢」翻成「这一拍耗这么多、产这么点」,提速前先认这笔账。")
    sys.exit(0)


if __name__ == "__main__":
    main()
