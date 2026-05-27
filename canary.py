#!/usr/bin/env python3
"""金丝雀闸 🐤🚦 —— 一次自改要不要「放量」，先在少量黄金任务与最热旅程上试跑。

为什么要有它：releasegate 在签发前问「能不能安全推出去」，evalbench 问「我做任务
的质量在不在升」。但它们都偏向**全量**视角——跑齐所有黄金集、汇齐所有哨卡，慢且重。
这只螃蟹每天都在自改一个器官，真正想要的，是一道**便宜、快、先于全量**的试跑闸：

  **这次蜕壳，先只在「少量最有代表性的黄金任务 + 当场最烫的用户旅程」上看一眼——
  没把这层小队伍跑坏，再放量去做全量回归 / 合并；跑坏了，趁早按住、别铺开。**

金丝雀的价值就是**用最小的样本最早地发现坏蜕壳**：与其全量回归跑完才发现退步，
不如先拿一小队真实任务当探针。它取两条最敏感的赛道当金丝雀队伍：

  · 🐤 **黄金赛道**：从 evalbench 黄金集里取**少量**(默认 3 条)真实任务，按三维启发式
                     打分，聚合成「金丝雀分」，和 evalbench 上一次**全量基线**比——
                     掉得超过容差(默认 1.0)就算金丝雀报警。这只是条**绊线**，不是
                     精密度量：子集对全量本就不严格可比，但够用来「先于全量喊停」。
  · 🔥 **旅程赛道**：从 usageheat 取**当场发烫**(入口推不开 / 证据失守)的器官——
                     最热的用户旅程里只要有一个在当场失败，金丝雀就报警：别拿一个
                     正在烧的表面去放量。

裁决三档：🟢 放量(两条赛道都过阈，去全量 / 合并)、🔴 按住(有赛道报警，先修再铺)、
⬜ 未知(黄金集没 bless 或读不到基线——盲跑不放量，先去 bless 补基线)。

它是观测者：只读 evalbench / usageheat 的派生，把「放量还是按住」摆出来，
**不跑任务、不改黄金集、不动代码**。读不到依赖就退化成「未知」而非崩。
零第三方依赖，纯标准库。和 releasegate(全量签发) / evalbench(全量质量) 互补：
那两者是全量终审，canary 是**先于全量的快筛绊线**。

用法:
    python canary.py              # 跑金丝雀，打印放量/按住裁决
    python canary.py -n 5         # 黄金赛道取 5 条(默认 3)
    python canary.py --brain      # 黄金赛道用真大脑当评委(默认启发式，更快更省)
    python canary.py --quiet      # 只在按住(报警)时说话，适合钩子 / CI
    python canary.py --json       # 导出纯数据(给 health / 外部消费)

退出码：0 = 放量(或未知)；1 = 按住(至少一条赛道报警)。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── 金丝雀参数：小样本、先于全量的快筛绊线 ────────────────────────────────
CANARY_GOLDENS = 3       # 黄金赛道默认取多少条真实任务当金丝雀(少而精)
CANARY_TOLERANCE = 1.0   # 金丝雀分相对全量基线最多可下探多少(总分满分 9)，超了报警

# 裁决三档：和 releasegate 同口径——未知保守按下「不放量」。
VERDICT_RAMP = "ramp"        # 🟢 过阈，放量
VERDICT_HOLD = "hold"        # 🔴 报警，按住
VERDICT_UNKNOWN = "unknown"  # ⬜ 盲跑：没基线/没金丝雀队伍，保守不放量
_ICON = {VERDICT_RAMP: "🟢", VERDICT_HOLD: "🔴", VERDICT_UNKNOWN: "⬜"}
# 哪些裁决会按下「不放量」：报警当然，未知也保守拦下(盲跑不等于安全)。
_HOLDING = {VERDICT_HOLD, VERDICT_UNKNOWN}


@dataclasses.dataclass(frozen=True)
class Lane:
    """一条金丝雀赛道：取了哪些样本、亮什么灯、一句结论、报警项与提醒项。"""
    key: str
    icon: str
    name: str
    verdict: str
    headline: str                    # 一句话结论，可直接打印
    alarms: tuple[str, ...] = ()     # 报警的具体原因(按住清单的素材)
    notes: tuple[str, ...] = ()      # 不报警但值得看一眼

    @property
    def holds(self) -> bool:
        return self.verdict in _HOLDING

    def to_meta(self) -> dict:
        return {"key": self.key, "name": self.name, "verdict": self.verdict,
                "headline": self.headline,
                "alarms": list(self.alarms), "notes": list(self.notes)}


def _unavailable(key: str, icon: str, name: str, err: Exception) -> Lane:
    """某条赛道的依赖导入/执行失败：记为未知，保守不放量。"""
    return Lane(key=key, icon=icon, name=name, verdict=VERDICT_UNKNOWN,
                headline=f"赛道不可用，无法判定（{type(err).__name__}: {err}）",
                alarms=(f"修复 {key} 依赖后重跑金丝雀，或人工确认该面安全。",))


# ── 黄金赛道：少量真实任务打分，和全量基线比 ──────────────────────────────
def _baseline_total() -> float | None:
    """evalbench 上一次全量评测的聚合总分，当金丝雀的对照基线；读不到返回 None。"""
    try:
        import evalbench
        hist = evalbench._read_history()
    except Exception:  # noqa: BLE001 —— 读不到基线按盲跑处理
        return None
    for run in reversed(hist):
        avg = (run or {}).get("averages") or {}
        if "total" in avg:
            try:
                return float(avg["total"])
            except (TypeError, ValueError):
                return None
    return None


def lane_goldens(n: int = CANARY_GOLDENS, use_brain: bool = False) -> Lane:
    """黄金赛道：取少量黄金任务现评，聚合成金丝雀分，与全量基线比容差。"""
    key, icon, name = "goldens", "🐤", "黄金赛道"
    try:
        import evalbench
        goldens = evalbench.load_goldens()[:max(1, n)]
        scorer = evalbench._brain_score if use_brain else evalbench._heuristic_score
    except Exception as e:  # noqa: BLE001
        return _unavailable(key, icon, name, e)

    if not goldens:
        return Lane(key, icon, name, VERDICT_UNKNOWN,
                    "黄金集还没 bless，没有金丝雀队伍可跑。",
                    alarms=("先 `python evalbench.py --bless` 冻结黄金集，再放量。",))

    rated: list = []
    for g in goldens:
        ep = evalbench._latest_attempt(g.task)
        if ep is not None:
            rated.append(scorer(g.id, ep))

    if not rated:
        return Lane(key, icon, name, VERDICT_UNKNOWN,
                    f"取了 {len(goldens)} 条金丝雀任务，但近期都没够像的经历可评。",
                    alarms=("近期没有可评的真实经历，无从快筛——先跑出经历再放量。",))

    canary = round(sum(s.total for s in rated) / len(rated), 2)
    base = _baseline_total()
    cohort = f"{len(rated)}/{len(goldens)} 条评得上，金丝雀分 {canary}（满分 9）"

    if base is None:
        return Lane(key, icon, name, VERDICT_UNKNOWN,
                    f"{cohort}，但 evalbench 还没有全量基线可比。",
                    notes=("先 `python evalbench.py` 留下一次全量基线，金丝雀才有对照。",))

    drop = round(base - canary, 2)
    if drop > CANARY_TOLERANCE:
        return Lane(key, icon, name, VERDICT_HOLD,
                    f"{cohort}，比全量基线 {base} 掉了 {drop}（超容差 {CANARY_TOLERANCE}）。",
                    alarms=(f"金丝雀分较基线下探 {drop} > {CANARY_TOLERANCE}，"
                            "疑似坏蜕壳——先查这几条任务为何变差，别放量。",))
    note = () if drop <= 0 else (f"较基线略降 {drop}（在容差 {CANARY_TOLERANCE} 内）。",)
    return Lane(key, icon, name, VERDICT_RAMP,
                f"{cohort}，对照全量基线 {base} 未越容差。", notes=note)


# ── 旅程赛道：最热的用户旅程里有没有当场在烧的 ────────────────────────────
def _cooling_journey_notes(m: dict) -> tuple[str, ...]:
    """最常用但证据已过期/未证(还没失守)的热旅程——不按住放量，只提醒先复证别等它烧起来。"""
    notes = []
    for j in m.get("journeys", []):
        # 失守(broken)已进 hot 名单、会触发按住，这里只挑「常用且证据将凉」的过期/未证。
        if j.get("has_claim") and j.get("verify_state") in ("stale", "unproven"):
            word = "过期" if j["verify_state"] == "stale" else "未证"
            notes.append(f"热旅程 {j['name']}.py（近窗口被点名 {j.get('mentions', 0)} 次）"
                         f"证据{word}，建议先 `python evidence.py --verify {j['name']}` 复证。")
    return tuple(notes)


def lane_journeys() -> Lane:
    """旅程赛道：usageheat 里当场发烫(入口推不开/证据失守)的器官即金丝雀报警。

    此外把「最常用但证据将凉」(过期/未证)的热旅程挂为提醒——不按住放量，
    但先于失守提示去复证：强弱应先盯真实常用处。
    """
    key, icon, name = "journeys", "🔥", "旅程赛道"
    try:
        import usageheat
        m = usageheat.manifest()
    except Exception as e:  # noqa: BLE001
        return _unavailable(key, icon, name, e)

    notes = _cooling_journey_notes(m)
    hot = list(m.get("hot", []))
    if hot:
        shown = "、".join(f"{h}.py" for h in hot[:5])
        more = f" 等 {len(hot)} 个" if len(hot) > 5 else ""
        return Lane(key, icon, name, VERDICT_HOLD,
                    f"最热旅程里有 {len(hot)} 个器官当场在烧：{shown}{more}。",
                    alarms=(f"先修好发烫器官（{shown}{more}）再放量，"
                            "别拿正在失败的表面去铺开。",),
                    notes=notes)
    return Lane(key, icon, name, VERDICT_RAMP,
                f"最热旅程无当场失败（共扫 {m.get('total', 0)} 个器官，0 发烫）。",
                notes=notes)


# ── 总决：两条赛道合成「放量 / 按住」 ─────────────────────────────────────
def assess(n: int = CANARY_GOLDENS, use_brain: bool = False) -> list[Lane]:
    """跑齐两条金丝雀赛道，返回有序列表（顺序即展示顺序）。"""
    return [lane_goldens(n, use_brain), lane_journeys()]


def decide(lanes: list[Lane]) -> tuple[bool, str]:
    """合成总决：任一赛道报警/未知就按住。返回 (放量?, 一句话)。"""
    holding = [ln for ln in lanes if ln.holds]
    if not holding:
        return True, "✅ 放量：两条金丝雀赛道都过阈，可去全量回归 / 合并。"
    names = "、".join(ln.name for ln in holding)
    return False, f"🛑 按住：{len(holding)} 条赛道未过——{names}，先修再铺开。"


def manifest(n: int = CANARY_GOLDENS, use_brain: bool = False) -> dict:
    """导出纯数据（给 health / 外部工具消费）。"""
    lanes = assess(n, use_brain)
    ramp, verdict_line = decide(lanes)
    return {
        "ramp": ramp,
        "verdict": verdict_line,
        "goldens_n": n,
        "judge": "brain" if use_brain else "heuristic",
        "tolerance": CANARY_TOLERANCE,
        "lanes": [ln.to_meta() for ln in lanes],
        "alarms": [a for ln in lanes for a in ln.alarms],
        "notes": [w for ln in lanes for w in ln.notes],
    }


# ── 渲染：放量理由 / 按住清单 ─────────────────────────────────────────────
def _render(lanes: list[Lane]) -> None:
    print("🐤 opencrab 金丝雀闸 —— 放量前的快筛绊线\n")
    for ln in lanes:
        print(f"  {_ICON[ln.verdict]} {ln.icon} {ln.name}：{ln.headline}")
        for a in ln.alarms:
            print(f"        🔴 {a}")
        for w in ln.notes:
            print(f"        🟡 {w}")
    print()

    ramp, verdict_line = decide(lanes)
    if ramp:
        print("🚀 放量理由")
        for ln in lanes:
            print(f"  · {ln.icon} {ln.name} — {ln.headline}")
    else:
        print("⏸️  按住清单（先动这些再放量）")
        n = 0
        for ln in lanes:
            if not ln.holds:
                continue
            for a in (ln.alarms or (ln.headline,)):
                n += 1
                print(f"  {n}. {ln.icon} {ln.name}：{a}")
    print()
    print(verdict_line)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 金丝雀闸 🐤🚦")
    ap.add_argument("-n", "--goldens", type=int, default=CANARY_GOLDENS,
                    help=f"黄金赛道取多少条真实任务（默认 {CANARY_GOLDENS}）")
    ap.add_argument("--brain", action="store_true",
                    help="黄金赛道用真大脑当评委（默认启发式，更快更省）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在按住（报警）时输出，适合钩子 / CI")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(args.goldens, args.brain),
                         ensure_ascii=False, indent=2))
        return

    lanes = assess(args.goldens, args.brain)
    ramp, _ = decide(lanes)
    if not (args.quiet and ramp):
        _render(lanes)
    sys.exit(0 if ramp else 1)


if __name__ == "__main__":
    main()
