#!/usr/bin/env python3
"""收成回查 🌾 —— 自改合并后 3/7/14 天回来看它，判成「真收益 / 泡沫 / 需退役」。

为什么要有它：领地里每天都在合并自改，合并那一刻所有信号都是绿的——证据
(evidence)刚验过、价值卡(value)刚写上、提交也夸下海口。可「合并即成功」是这只
螃蟹最舒服的自欺：一次小改在合并当天热热闹闹，之后**再没被任何一次心跳提起、也再
没被复验过**，它到底是真帮上了忙，还是只是又往壳上糊了一层好看的漆？分不清，进化
就会沦为「攒合并数」——改得越多，离真有用反而越远。

收成回查把判决**推迟到合并之后的真实使用里**。每次自改合并 = 播下一粒种，它需要时间
才结得出果。harvest 在合并后的三个回查点回来摸一摸：

  · 3 天 —— 头道回查：这两三天里，它还被提起 / 被跑过吗？还是合并完就凉了？
  · 7 天 —— 复查：一周下来，它进了真实使用的轨迹，还是成了写完即忘的旧壳？
  · 14 天 —— 终查：两周仍无人问津 + 证据发凉，基本可以判它「需退役」了。

每粒种在它当前够到的那个回查点上，按三处既有痕迹判一个收成：

  · 使用(usage) —— 合并**之后**，这个模块还在提交/运行/记忆里被碰过吗(timeline 派生)。
  · 失败(failure)—— 它此刻的证据账本是不是 🔴失守了(evidence)。当场在坏 = 最该先处理。
  · 证据(evidence)—— 合并后它的证据被复验过吗、还新鲜吗(evidence 的 state / age)。

据此落一个判决：

  🌾 真收益 —— 合并后仍被反复用到，且没在失败。这粒种真的结了果。
  🫧 泡沫   —— 到点了却没失败、也没人再碰：合并当天热闹一阵，之后归于沉寂。不是错，
               但提醒我「这次进化多半只是自娱自乐」，别拿它充进步。
  🥀 需退役 —— 此刻证据失守(当场在坏)，或拖到 14 天仍无使用且证据发凉。该修或该退役。
  ⏳ 未到点 —— 合并还不满 3 天，给它时间结果，暂不下判。

它是观测者：只读 git log（经 timeline 派生）与 evidence 账本，**不执行被测模块、不落盘、
不改任何文件**；任一处痕迹读不到，那一维记为「未知」并跳过，绝不臆测。

用法：
    python harvest.py                 # 全部已合并自改的收成回查（按判决分组）
    python harvest.py --due            # 只看到了回查点、却还没结果的（泡沫/需退役）
    python harvest.py --grep evidence  # 只看某个模块的收成
    python harvest.py --lookback 90    # 往回扫多少天的合并（默认 60）
    python harvest.py --quiet          # 只在有「需退役」时说话（适合钩子 / CI）
    python harvest.py --json           # 机读：导出每粒种的回查点、各维信号与判决

退出码：0 = 没有「需退役」的自改；1 = 有自改当场失守或久无使用证据发凉。零第三方依赖。
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

# 三个回查点（合并后第几天回来看），从早到晚。
CHECKPOINTS = (3, 7, 14)
DEFAULT_LOOKBACK = 60        # 往回扫多少天的合并提交：再早的种，结没结果早已尘埃落定
_STALE_DAYS = 7.0           # 证据账本「发凉」门槛：上次复验超过这么多天就算久未验证

# ── 四种收成判决 ───────────────────────────────────────────────────────
REAL = "real"               # 🌾 真收益：合并后仍被反复用到、没失败
BUBBLE = "bubble"           # 🫧 泡沫：到点没失败也没人再碰，热闹一阵归于沉寂
WILTING = "wilting"         # 🥀 需退役：当场证据失守，或 14 天仍无用且证据发凉
PENDING = "pending"         # ⏳ 未到点：合并不满 3 天，暂不下判

_MARK = {REAL: "🌾", BUBBLE: "🫧", WILTING: "🥀", PENDING: "⏳"}
_WORD = {REAL: "真收益", BUBBLE: "泡沫", WILTING: "需退役", PENDING: "未到点"}
_ORDER = (WILTING, BUBBLE, REAL, PENDING)   # 最该被看见的排前面


def _today() -> datetime.date:
    return datetime.date.today()


def _checkpoint_for(age_days: float) -> int | None:
    """这粒种当前够到的回查点：已过的最大那个；不满最早回查点则 None（未到点）。"""
    reached = [c for c in CHECKPOINTS if age_days >= c]
    return max(reached) if reached else None


@dataclasses.dataclass
class Harvest:
    """一粒种的收成回查：何时合并、隔了多久、合并后三维信号如何、判成什么。"""
    module: str                 # 模块名（stem），即这次自改推进的对象
    merged_at: str              # 最早一次以它为主题的 evolve 提交时刻（= 播种日）
    age_days: float             # 距今天数
    checkpoint: int | None      # 当前够到的回查点（None=未到点）

    uses_after: int = 0         # 合并后它在提交/运行/记忆里被碰过的次数
    failing: bool = False       # 此刻证据账本是否 🔴失守
    evidence_state: str | None = None  # fresh / stale / broken / unproven / None(无声明)
    evidence_age: float | None = None  # 证据上次复验距今天数

    verdict: str = PENDING
    reasons: list[str] = dataclasses.field(default_factory=list)

    def to_meta(self) -> dict:
        return {
            "module": self.module, "merged_at": self.merged_at,
            "age_days": round(self.age_days, 1), "checkpoint": self.checkpoint,
            "uses_after": self.uses_after, "failing": self.failing,
            "evidence_state": self.evidence_state,
            "evidence_age": (round(self.evidence_age, 1)
                             if self.evidence_age is not None else None),
            "verdict": self.verdict, "reasons": self.reasons,
        }


# ── 播种：从 git log 派生每个模块最早一次 evolve 提交（= 合并日） ────────────
def _plantings(lookback_days: int) -> dict[str, str]:
    """复用 timeline 的 git 派生，取每个模块**最早**一次以它为主题的提交时刻。

    timeline 读不到（无 git / 无提交）则回空——一粒种都收不上来，但绝不臆测。
    """
    try:
        import timeline
        events = timeline._commit_events(lookback_days)
    except Exception:
        return {}
    earliest: dict[str, str] = {}
    for e in events:
        if not e.topic:
            continue
        cur = earliest.get(e.topic)
        if cur is None or e.at < cur:
            earliest[e.topic] = e.at
    return earliest


# ── 使用维：合并之后，这个模块还在任何痕迹里被碰过吗 ─────────────────────────
def _uses_after(module: str, merged_at: str, lookback_days: int) -> int:
    """合并时刻**之后**，timeline 三股证据里点名该模块的节点数（播种当条不算）。"""
    try:
        import timeline
        events = timeline.collect(since_days=lookback_days, grep=module)
    except Exception:
        return 0
    return sum(1 for e in events if e.topic == module and e.at > merged_at)


# ── 证据维：合并后它的证据被复验过吗、还新鲜吗 ───────────────────────────────
def _evidence_index() -> dict[str, tuple[str | None, float | None]]:
    """复用 evidence.manifest()，取每个模块的证据 state 与距今天数；拿不到回空。"""
    try:
        import evidence
        m = evidence.manifest()
    except Exception:
        return {}
    out: dict[str, tuple[str | None, float | None]] = {}
    for st in m.get("status", []):
        name = st.get("name")
        if name:
            out[name] = (st.get("state"), st.get("age_days"))
    return out


# ── 判决：三维信号折叠成一个收成 ─────────────────────────────────────────────
def _judge(h: Harvest) -> None:
    """据「使用 / 失败 / 证据」三维，给这粒种定一个收成判决并记下为什么。"""
    reasons: list[str] = []

    # ⏳ 未到点：合并不满最早回查点，给它时间。
    if h.checkpoint is None:
        h.verdict = PENDING
        h.reasons = [f"合并才 {h.age_days:.1f} 天，不满 {CHECKPOINTS[0]} 天首回查，暂不下判"]
        return

    # 🥀 需退役（其一）：此刻证据账本失守——当场就在坏，最该先处理。
    if h.failing:
        h.verdict = WILTING
        h.reasons = [f"证据账本最近一次验证 🔴失守（合并已 {h.age_days:.1f} 天），先修或退役"]
        return

    fresh = (h.evidence_state == "fresh"
             or (h.evidence_age is not None and h.evidence_age < _STALE_DAYS))

    # 🌾 真收益：合并后仍被反复用到，且没在失败。
    if h.uses_after > 0:
        h.verdict = REAL
        reasons.append(f"合并后又被提及/跑到 {h.uses_after} 次（{h.checkpoint} 天回查仍在用）")
        if fresh:
            reasons.append("证据账本近期复验仍 ✅绿")
        h.reasons = reasons
        return

    # 没人再碰它——区分「还能再等」与「该退役了」。
    stale = (h.evidence_state in ("stale", "unproven")
             or (h.evidence_age is not None and h.evidence_age >= _STALE_DAYS))

    # 🥀 需退役（其二）：拖到最晚回查点仍无使用、且证据发凉/没验过。
    if h.checkpoint >= CHECKPOINTS[-1] and (stale or h.evidence_state is None):
        h.verdict = WILTING
        reasons.append(f"{h.checkpoint} 天回查仍无任何后续使用")
        if stale:
            age = f"{h.evidence_age:.0f} 天前" if h.evidence_age is not None else "已久"
            reasons.append(f"证据账本上次复验在 {age}（已发凉）")
        else:
            reasons.append("也没有证据账本可佐证它还在干活")
        h.reasons = reasons
        return

    # 🫧 泡沫：到点了、没失败、却也没人再碰——合并当天热闹一阵，之后归于沉寂。
    h.verdict = BUBBLE
    reasons.append(f"{h.checkpoint} 天回查：合并后再没被提起/跑到过")
    if fresh:
        reasons.append("证据虽仍新鲜，但没进真实使用——多半只是自娱自乐")
    h.reasons = reasons


def collect(lookback_days: int = DEFAULT_LOOKBACK, grep: str = "") -> list[Harvest]:
    """对齐 git 合并日 ⨉ 使用痕迹 ⨉ 证据账本，产出每粒种的收成回查（按判决排序）。"""
    plantings = _plantings(lookback_days)
    evid = _evidence_index()
    today = _today()

    harvests: list[Harvest] = []
    for module, merged_at in plantings.items():
        if grep and grep.lower() not in module.lower():
            continue
        try:
            merged_day = datetime.date.fromisoformat(merged_at[:10])
            age = (today - merged_day).days + _frac_of_day(merged_at)
        except Exception:
            continue
        age = max(0.0, age)
        ev_state, ev_age = evid.get(module, (None, None))
        h = Harvest(
            module=module, merged_at=merged_at, age_days=age,
            checkpoint=_checkpoint_for(age),
            uses_after=_uses_after(module, merged_at, lookback_days),
            failing=(ev_state == "broken"),
            evidence_state=ev_state, evidence_age=ev_age,
        )
        _judge(h)
        harvests.append(h)

    rank = {v: i for i, v in enumerate(_ORDER)}
    harvests.sort(key=lambda h: (rank[h.verdict], -h.age_days))
    return harvests


def _frac_of_day(iso: str) -> float:
    """把 ISO 时刻的时分换成 0~1 的当日占比，让 age 不至于把当天合并算成满整天。"""
    t = iso[11:16]
    if len(t) == 5 and t[2] == ":":
        try:
            hh, mm = int(t[:2]), int(t[3:])
            return -(hh * 60 + mm) / 1440.0   # 今天合并 → age 略小于整数天
        except Exception:
            return 0.0
    return 0.0


def summarize(harvests: list[Harvest]) -> dict[str, int]:
    """各判决的计数。"""
    out = {v: 0 for v in _ORDER}
    for h in harvests:
        out[h.verdict] += 1
    return out


def manifest(lookback_days: int = DEFAULT_LOOKBACK, grep: str = "") -> dict:
    """机读：每粒种的回查点、各维信号与判决 + 各判决计数 + 需退役名单。"""
    harvests = collect(lookback_days, grep)
    return {
        "lookback_days": lookback_days, "checkpoints": list(CHECKPOINTS),
        "grep": grep, "total": len(harvests),
        "counts": summarize(harvests),
        "wilting": [h.module for h in harvests if h.verdict == WILTING],
        "harvests": [h.to_meta() for h in harvests],
    }


# ── 渲染 ─────────────────────────────────────────────────────────────────
def _render(harvests: list[Harvest], lookback: int, due_only: bool) -> str:
    counts = summarize(harvests)
    L = [f"🌾 opencrab 收成回查 —— 自改合并后 {'/'.join(map(str, CHECKPOINTS))} 天，"
         f"回看真实使用（往回扫 {lookback} 天合并）", ""]

    if not harvests:
        L.append("   （往回扫不到任何以模块为主题的合并提交——把 --lookback 拉大些，"
                 "或先让它跑几跳积累 git log。）")
        return "\n".join(L)

    shown = harvests
    if due_only:   # 只看到点却还没结果的：泡沫 + 需退役
        shown = [h for h in harvests if h.verdict in (WILTING, BUBBLE)]
        if not shown:
            L.append("   ✅ 所有到了回查点的自改，要么真有收益、要么还没到点——没有泡沫/需退役。")
            return "\n".join(L)

    by_verdict: dict[str, list[Harvest]] = {}
    for h in shown:
        by_verdict.setdefault(h.verdict, []).append(h)

    for v in _ORDER:
        items = by_verdict.get(v, [])
        if not items:
            continue
        L.append(f"{_MARK[v]} {_WORD[v]}（{len(items)} 个）")
        for h in items:
            cp = f"{h.checkpoint}天回查" if h.checkpoint else "未到点"
            L.append(f"   {h.module}.py — 合并 {h.merged_at[:10]}（{h.age_days:.1f} 天前 · {cp}）")
            for why in h.reasons:
                L.append(f"      · {why}")
        L.append("")

    bar = "  ".join(f"{_MARK[v]}{_WORD[v]} {counts[v]}" for v in _ORDER)
    L.append(f"分布：{bar}")
    if counts[WILTING]:
        L.append(f"⚠️  有 {counts[WILTING]} 个自改需退役（当场失守，或久无使用证据发凉）——"
                 f"修好它，或让它体面退役，别留着糊壳。")
    elif counts[BUBBLE]:
        L.append(f"🫧 没有需退役的，但有 {counts[BUBBLE]} 个泡沫——合并后没进真实使用，"
                 f"下次别拿这类「热闹」充进步。")
    else:
        L.append("🦀 到点的自改都进了真实使用（真收益），没有泡沫，也没有需退役的。")
    return "\n".join(L)


# ── 自检：判决逻辑的真值表，不碰真账本、无副作用 ───────────────────────────────
def _selftest() -> list[str]:
    """返回失败清单（空 = 全过）；每条都是构造一粒种、跑 _judge、核判决的真实调用。"""
    fails: list[str] = []

    def case(uses: int, failing: bool, ev_state, ev_age, age: float, want: str, why: str):
        h = Harvest(module="x", merged_at="2026-01-01T00:00:00Z", age_days=age,
                    checkpoint=_checkpoint_for(age), uses_after=uses, failing=failing,
                    evidence_state=ev_state, evidence_age=ev_age)
        _judge(h)
        if h.verdict != want:
            fails.append(f"{why}：判成 {h.verdict}，应为 {want}")

    # 未到点：不满 3 天，无论别的信号如何都暂不下判。
    case(0, False, None, None, 1.0, PENDING, "合并 1 天该未到点")
    case(5, True, "broken", 0.0, 2.9, PENDING, "不满 3 天即便失守也先不判")
    # 真收益：到点、没失败、合并后仍被用到。
    case(3, False, "fresh", 1.0, 4.0, REAL, "3 天有后续使用且证据绿该判真收益")
    case(1, False, None, None, 9.0, REAL, "无证据声明但有后续使用仍算真收益")
    # 需退役（失守优先）：证据账本 broken，哪怕还有使用也判需退役。
    case(9, True, "broken", 0.0, 4.0, WILTING, "证据失守该判需退役（压过使用）")
    # 泡沫：到点、没失败、没人再碰，但还没到最晚回查点 / 证据仍新鲜。
    case(0, False, "fresh", 1.0, 4.0, BUBBLE, "3 天无使用但证据新鲜该判泡沫")
    case(0, False, "fresh", 2.0, 14.0, BUBBLE, "14 天无使用但证据仍新鲜仍算泡沫")
    # 需退役（拖太久）：14 天仍无使用，且证据发凉 / 没验过。
    case(0, False, "stale", 30.0, 14.0, WILTING, "14 天无使用且证据发凉该判需退役")
    case(0, False, None, None, 20.0, WILTING, "14 天无使用又无证据该判需退役")
    case(0, False, "unproven", None, 15.0, WILTING, "14 天无使用且从未验证该判需退役")
    # 7 天无使用、证据发凉，但还没拖到 14 天 → 仍是泡沫（再给一程观察）。
    case(0, False, "stale", 30.0, 8.0, BUBBLE, "7 天无使用证据发凉但未到 14 天仍判泡沫")

    # 回查点边界。
    if _checkpoint_for(2.9) is not None:
        fails.append("age 2.9 不该够到任何回查点")
    if _checkpoint_for(3.0) != 3:
        fails.append("age 3.0 该够到 3 天回查点")
    if _checkpoint_for(13.9) != 7:
        fails.append("age 13.9 该停在 7 天回查点")
    if _checkpoint_for(14.0) != 14:
        fails.append("age 14.0 该够到 14 天回查点")

    return fails


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 收成回查 🌾 —— 自改合并后 3/7/14 天回查真实使用，判真收益/泡沫/需退役")
    ap.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK, metavar="N",
                    help=f"往回扫多少天的合并提交（默认 {DEFAULT_LOOKBACK}）")
    ap.add_argument("--grep", default="", metavar="TEXT",
                    help="只看模块名含此子串的收成")
    ap.add_argument("--due", action="store_true",
                    help="只看到了回查点却还没结果的（泡沫 / 需退役）")
    ap.add_argument("--selftest", action="store_true",
                    help="只跑判决逻辑自检（真值表），不读 git / 证据")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有「需退役」自改时说话（适合钩子 / CI）")
    ap.add_argument("--json", action="store_true",
                    help="机读：导出每粒种的回查点、各维信号与判决")
    args = ap.parse_args(argv)

    if args.selftest:
        fails = _selftest()
        if fails:
            print(f"⚠️  收成判决自检发现 {len(fails)} 处不对：")
            for f in fails:
                print(f"  ❌ {f}")
            sys.exit(1)
        print("🌾 收成判决自检全过：未到点 / 真收益 / 泡沫 / 需退役 的真值表都对得上。")
        sys.exit(0)

    lookback = max(max(CHECKPOINTS), args.lookback)
    grep = args.grep.strip()

    if args.json:
        print(json.dumps(manifest(lookback, grep), ensure_ascii=False, indent=2))
        sys.exit(0)

    harvests = collect(lookback, grep)
    counts = summarize(harvests)
    wilting = counts[WILTING]

    if args.quiet:
        if wilting:
            names = "、".join(h.module for h in harvests if h.verdict == WILTING)
            print(f"🥀 收成回查：{wilting} 个自改需退役 —— {names}")
            for h in harvests:
                if h.verdict == WILTING:
                    print(f"   🥀 {h.module}.py：{'；'.join(h.reasons)}")
    else:
        print(_render(harvests, lookback, args.due))

    sys.exit(1 if wilting else 0)


if __name__ == "__main__":
    main()
