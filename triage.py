#!/usr/bin/env python3
"""自生手任务分诊 🩺🖐️ —— 有手之后，先学会自己挑「安全又有价值」的活。

为什么要有它：`weaning_trial` 证明了 brain 能不靠外援自己产补丁、`patchfitroom` 给落爪
铺了五道闸、`moveset` 给落爪前长了直觉、`touch` 给手长了触觉。手已经能动、也摔不死自己。
可一只成熟的手，下一课不是「改得更猛」，而是**会自己选活**——同样是一处小修，落在
`jsonlstore`（半个仓库都 import 它、还钉着契约）上，和落在一个没人依赖的叶子模块上，
风险天差地别。过去这道「该不该让 brain 单独上」的判断一直是我临场拍脑袋；分诊就把它钉成
一张可核对的表：**哪些小修可以放心交给 brain 独立落爪，哪些得先补证据/缩影响面、或干脆雇手。**

分诊不自己想补丁，也不动任何文件——它只把每个候选目标放到**三面镜子**前照一遍，各给一个
可核对的「风险/缺口」分，合成一个「可独立落爪度」，再像急诊分诊那样把候选分进三档：

  · 🎯 **影响面**（impact surface）：顺着 import 图算这个模块的**传递反向依赖**——动它会牵动
        多少个下游。牵动越多 = 爆炸半径越大 = 越不该让 brain 单独碰。（复用 `impact.py` 的依赖图，
        单一真相源，那边的图一改这边自动跟着变。）
  · 🧬 **契约风险**（contract risk）：这个模块在 `contracts.py` 里有没有钉死的对外契约？
        有 = 它是**载重的承诺**，下游按它的 in/out 语义吃饭，一处「小修」也是高风险大事；
        没有 = 没有正式承诺可毁，风险低。
  · 🔬 **证据缺口**（evidence gap）：万一 brain 落了个**编译过、却语义微错**的补丁，谁接得住？
        接得住的证据有两类——被 `regression.py` 点名（输出/退出码漂移会被快照逮到）、自带
        `--selfcheck`（一条能当场复跑的自证）。两样都没有 = 缺口最大 = brain 的补丁无从被证明
        安全，不该单独落。

合成（权重见 `WEIGHTS`，合计 1.0）：可独立落爪度 = 1 − 加权风险。再按两道阈值分诊：

  🟢 **brain 可独立落爪**：影响面小、无载重契约、证据接得住——放心交给 brain 自己上。
  🟡 **先补证据/缩面，或雇手**：某一面偏高——补条 regression/selfcheck、或拆小、或雇爪子。
  🔴 **别让 brain 单独碰**：载重 bedrock + 大爆炸半径——这种活要人盯着、要雇手、要多闸护着。

每一分都附一行**可核对的依据**（牵动了哪几个下游、是否在契约名册、缺哪类证据），分诊不靠
感觉、靠这些数字说话。它只读、只排序、不落盘、不改任何文件——**最终让不让手上，仍由我拍板。**

与全家一致：零第三方依赖、纯标准库；分诊是观测者/参谋，读盘失败、依赖缺席一律吞掉收敛成
保守判断，绝不反噬动手主流程——给手挑活的层，自己不能成为新的伤口。

用法：
    python triage.py                  # 给全领地模块分诊，按可独立落爪度排序，打印三档 + 三维拆解
    python triage.py --files a.py b.py # 只分诊给定的几个目标（如本次 diff / compass 候选）
    python triage.py --green           # 只列 🟢 可独立落爪的小修（手该先挑的活）
    python triage.py --top 10          # 只看前 N 个
    python triage.py --json            # 机读：导成 JSON（给 planner / hands 前置消费）
    python triage.py --selfcheck       # 自检：三维评分与三档分诊在合成输入上判得对（供 evidence 复跑）
    加 --quiet 静默。

零第三方依赖，纯标准库。与 `prioritizer.py`（先做哪个）互补：那条排「最该做」，
这条排「哪个能放心让手单独做」。
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

# ── 三维权重：合计 1.0 ────────────────────────────────────────────────
# 影响面给最重：爆炸半径是「单独让手上」最不可逆的代价——改坏一个叶子和改坏一个 bedrock，
# 收拾难度差一个量级。契约风险次之（载重承诺一毁，下游集体遭殃）。证据缺口最轻但不可省：
# 它不是「会不会坏」，而是「坏了接不接得住」——缺口可以靠补一条 selfcheck/regression 当场补上，
# 比缩影响面/解契约便宜得多，所以它更多是「先补这个再上」的提示，而非一票否决。
WEIGHTS = {"impact": 0.45, "contract": 0.35, "evidence": 0.20}

# 影响面归一化上限：传递反向依赖达到这个数就算「满半径」。本仓约百来个模块，
# 牵动 10+ 个下游已属 bedrock 级；超过按满算。
IMPACT_CAP = 10

# 分诊阈值（按可独立落爪度，越高越能放心单独让手上）。
GREEN_AT = 0.66   # ≥ → 🟢 可独立落爪
YELLOW_AT = 0.40  # ≥ 且 < GREEN → 🟡 先补证据/缩面或雇手；< → 🔴 别单独碰

BIN_GREEN = "🟢 brain 可独立落爪"
BIN_YELLOW = "🟡 先补证据/缩面，或雇手"
BIN_RED = "🔴 别让 brain 单独碰"


@dataclasses.dataclass(frozen=True)
class Axis:
    """一面镜子的读数：risk ∈ [0,1]（越高越不该单独让手上），附一行可核对依据。"""
    risk: float
    basis: str

    def clamp(self) -> "Axis":
        return Axis(max(0.0, min(1.0, self.risk)), self.basis)


@dataclasses.dataclass(frozen=True)
class Verdict:
    """一个候选目标的分诊结论。"""
    target: str            # 模块 stem（如 "jsonlstore"）
    landability: float     # 可独立落爪度 ∈ [0,1]，越高越能放心单独让手上
    bin: str               # 三档之一（BIN_GREEN / BIN_YELLOW / BIN_RED）
    axes: dict[str, Axis]  # impact / contract / evidence 三面读数

    def to_meta(self) -> dict:
        return {"target": self.target, "landability": round(self.landability, 3),
                "bin": self.bin,
                "axes": {k: {"risk": round(v.risk, 3), "basis": v.basis}
                         for k, v in self.axes.items()}}


# ── 领地事实采集（读真仓库；任何一步缺席都退守保守判断，绝不抛错）──────────
def _under_contract() -> set[str]:
    """`contracts.py` 钉了契约的模块名集合（读不到→空集，宁可少判契约风险也不误高）。"""
    try:
        import contracts
        return {c.module for c in contracts.CONTRACTS}
    except Exception:   # noqa: BLE001 —— 契约名册缺席不该拖垮分诊
        return set()


def _regression_text() -> str:
    """regression.py 的源码文本：模块 stem 出现在其中即视作「被回归点名」。"""
    try:
        return (REPO_ROOT / "regression.py").read_text("utf-8", errors="ignore")
    except Exception:   # noqa: BLE001
        return ""


def _reverse_deps() -> dict[str, set[str]]:
    """文件 -> 「（传递地）import 了它」的下游文件集合。复用 impact.py 的依赖图。"""
    try:
        import impact
        fwd = impact._forward_graph()
        rev = impact._reverse(fwd)
        # 传递闭包：不只直接 import，顺着图把间接牵连的也算进爆炸半径。
        return {f: impact._closure({f}, rev) for f in rev}
    except Exception:   # noqa: BLE001 —— 依赖图缺席→后面退守「半径未知、给中性」
        return {}


def _stem(path: str) -> str:
    return pathlib.PurePosixPath(str(path)).stem if path else ""


def _rel_for_stem(stem: str) -> str:
    """把一个模块 stem 还原成仓库相对路径（顶层优先；找不到回 stem.py）。"""
    top = REPO_ROOT / f"{stem}.py"
    if top.exists():
        return f"{stem}.py"
    for p in REPO_ROOT.rglob(f"{stem}.py"):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if not rel.startswith(("state/", ".git/")):
            return rel
    return f"{stem}.py"


def _has_selfcheck(stem: str) -> bool:
    """模块自带可当场复跑的自证（--selfcheck / def _selfcheck）。读不到→False(保守算缺)。"""
    try:
        src = (REPO_ROOT / _rel_for_stem(stem)).read_text("utf-8", errors="ignore")
    except Exception:   # noqa: BLE001
        return False
    return "--selfcheck" in src or "def _selfcheck" in src


# ── 三面镜子（纯函数：吃已采集的事实，吐 Axis；可被 selfcheck 喂合成输入）────
def _impact_axis(blast: int | None) -> Axis:
    """🎯 影响面：传递反向依赖数 → 爆炸半径风险。blast=None 表示半径未知，给中性偏稳。"""
    if blast is None:
        return Axis(0.5, "依赖图不可用 → 影响面未知，保守按中等爆炸半径计").clamp()
    risk = min(1.0, blast / IMPACT_CAP)
    if blast == 0:
        basis = "无下游依赖（叶子模块）→ 改它牵动不到别人，爆炸半径最小"
    else:
        basis = f"{blast} 个下游（传递）依赖它 → 爆炸半径{'大' if risk >= 0.8 else '中' if risk >= 0.4 else '小'}"
    return Axis(risk, basis).clamp()


def _contract_axis(under_contract: bool) -> Axis:
    """🧬 契约风险：在 contracts.py 钉了对外承诺的，是载重 bedrock，一处小修也是高风险。"""
    if under_contract:
        return Axis(0.9, "在 contracts.py 钉着对外契约 → 载重承诺，下游按其 in/out 吃饭，改动高风险").clamp()
    return Axis(0.1, "未钉对外契约 → 无正式承诺可毁，契约风险低").clamp()


def _evidence_axis(has_regression: bool, has_selfcheck: bool) -> Axis:
    """🔬 证据缺口：落了语义微错的补丁，谁接得住？regression 快照 + selfcheck 自证两类网。"""
    nets = []
    if has_regression:
        nets.append("被 regression 点名")
    if has_selfcheck:
        nets.append("自带 selfcheck")
    if not nets:
        return Axis(1.0, "既未被 regression 点名、又无 selfcheck → 补丁微错无从被逮，证据缺口最大").clamp()
    if len(nets) == 2:
        return Axis(0.1, "regression 快照 + selfcheck 双网兜底 → 补丁若微错会被当场逮到，缺口小").clamp()
    return Axis(0.5, f"仅「{nets[0]}」单网兜底 → 半数证据，建议补齐另一类再单独让手上").clamp()


def _compose(axes: dict[str, Axis]) -> float:
    """三面风险加权 → 可独立落爪度 = 1 − 加权风险。"""
    risk = sum(WEIGHTS[k] * axes[k].risk for k in WEIGHTS)
    return max(0.0, min(1.0, 1.0 - risk))


def _bin_of(landability: float) -> str:
    if landability >= GREEN_AT:
        return BIN_GREEN
    if landability >= YELLOW_AT:
        return BIN_YELLOW
    return BIN_RED


def _verdict_from_facts(stem: str, *, blast: int | None, under_contract: bool,
                        has_regression: bool, has_selfcheck: bool) -> Verdict:
    """把一个目标的四项事实合成一条分诊结论（纯函数，无 IO，便于自检）。"""
    axes = {
        "impact": _impact_axis(blast),
        "contract": _contract_axis(under_contract),
        "evidence": _evidence_axis(has_regression, has_selfcheck),
    }
    land = _compose(axes)
    # 「无证据不放绿」硬规则：哪怕是零下游、零契约的叶子，只要 regression / selfcheck 两类网
    # 全无，brain 的补丁就**无从被证明**没改错——加权分再高也压回 🟡（先补一条 selfcheck/regression
    # 再单独让手上）。已经更低（落进 🔴）的不动，cap 只往下不往上。
    if axes["evidence"].risk >= 1.0:
        land = min(land, GREEN_AT - 0.01)
    return Verdict(stem, land, _bin_of(land), axes)


# ── 对真仓库分诊 ───────────────────────────────────────────────────────
def _candidate_stems(files: list[str] | None) -> list[str]:
    """分诊对象：给定 --files 就用它们；否则全领地顶层模块（不含 state/.git，去重保序）。"""
    if files:
        seen, out = set(), []
        for f in files:
            s = _stem(f)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out
    stems = sorted(p.stem for p in REPO_ROOT.glob("*.py"))
    return stems


def triage(files: list[str] | None = None) -> list[Verdict]:
    """给候选目标分诊，按可独立落爪度降序（同分按 target 名稳定排序）。"""
    contracted = _under_contract()
    reg_text = _regression_text()
    rev = _reverse_deps()
    # stem -> 它对应的仓库相对路径（供反向依赖按文件查）
    out: list[Verdict] = []
    for stem in _candidate_stems(files):
        rel = _rel_for_stem(stem)
        blast = len(rev[rel]) if rel in rev else (0 if rev else None)
        v = _verdict_from_facts(
            stem,
            blast=blast,
            under_contract=stem in contracted,
            has_regression=bool(stem) and stem in reg_text,
            has_selfcheck=_has_selfcheck(stem),
        )
        out.append(v)
    out.sort(key=lambda v: (-v.landability, v.target))
    return out


def manifest(files: list[str] | None = None, top: int | None = None) -> dict:
    """机读：分诊表 + 阈值/权重（给 planner / hands 前置消费）。"""
    verdicts = triage(files)
    if top is not None:
        verdicts = verdicts[:top]
    counts = {BIN_GREEN: 0, BIN_YELLOW: 0, BIN_RED: 0}
    for v in verdicts:
        counts[v.bin] = counts.get(v.bin, 0) + 1
    return {
        "weights": WEIGHTS,
        "thresholds": {"green_at": GREEN_AT, "yellow_at": YELLOW_AT, "impact_cap": IMPACT_CAP},
        "bins": {"green": counts[BIN_GREEN], "yellow": counts[BIN_YELLOW], "red": counts[BIN_RED]},
        "verdicts": [v.to_meta() for v in verdicts],
    }


# ── 渲染 ───────────────────────────────────────────────────────────────
def render(verdicts: list[Verdict], *, top: int | None = None, green_only: bool = False) -> str:
    rows = [v for v in verdicts if v.bin == BIN_GREEN] if green_only else list(verdicts)
    if top is not None:
        rows = rows[:top]
    L = ["🩺🖐️  自生手任务分诊 —— 哪些小修可以放心交给 brain 独立落爪：\n"]
    if not rows:
        L.append("   （没有符合条件的候选。）")
        return "\n".join(L)
    for v in rows:
        a = v.axes
        L.append(f"  {v.bin}  ·  {v.target}   可独立落爪度 {v.landability:.2f}")
        L.append(f"      🎯 影响面 {a['impact'].risk:.2f} —— {a['impact'].basis}")
        L.append(f"      🧬 契约   {a['contract'].risk:.2f} —— {a['contract'].basis}")
        L.append(f"      🔬 证据   {a['evidence'].risk:.2f} —— {a['evidence'].basis}")
        L.append("")
    g = sum(1 for v in verdicts if v.bin == BIN_GREEN)
    y = sum(1 for v in verdicts if v.bin == BIN_YELLOW)
    r = sum(1 for v in verdicts if v.bin == BIN_RED)
    L.append(f"  合计：🟢 {g} 可独立落爪 · 🟡 {y} 先补证据/缩面 · 🔴 {r} 别单独碰")
    return "\n".join(L)


# ── 自检 ───────────────────────────────────────────────────────────────
def _selfcheck(*, quiet: bool = False) -> bool:
    failures: list[str] = []

    def expect_bin(label, *, blast, contract, reg, selfck, want):
        v = _verdict_from_facts(label, blast=blast, under_contract=contract,
                                has_regression=reg, has_selfcheck=selfck)
        if v.bin != want:
            failures.append(f"「{label}」应判 {want}，实得 {v.bin}（落爪度 {v.landability:.2f}）")
        return v

    # 理想的可独立落爪小修：叶子模块、无契约、双网兜底 → 🟢
    expect_bin("叶子+无约+双网", blast=0, contract=False, reg=True, selfck=True, want=BIN_GREEN)
    # 载重 bedrock：高扇入 + 钉契约（哪怕双网）→ 🔴，别让手单独碰
    expect_bin("bedrock+契约+双网", blast=12, contract=True, reg=True, selfck=True, want=BIN_RED)
    # 叶子但零证据：半径小，可一旦微错无人接 → 不该直接 🟢
    leaf_blind = expect_bin("叶子+无约+无网", blast=0, contract=False, reg=False, selfck=False, want=BIN_YELLOW)

    # 单调性：其余不变，证据从无到有，落爪度必须不降
    full = _verdict_from_facts("x", blast=0, under_contract=False, has_regression=True, has_selfcheck=True)
    if not (full.landability >= leaf_blind.landability):
        failures.append("补齐证据后落爪度反而下降，违反单调性")

    # 单调性：其余不变，影响面越大落爪度越低
    small = _verdict_from_facts("x", blast=0, under_contract=False, has_regression=True, has_selfcheck=True)
    big = _verdict_from_facts("x", blast=IMPACT_CAP, under_contract=False, has_regression=True, has_selfcheck=True)
    if not (big.landability < small.landability):
        failures.append("影响面增大后落爪度未下降，违反单调性")

    # 契约让风险升：其余不变，钉契约后落爪度必须降
    no_c = _verdict_from_facts("x", blast=1, under_contract=False, has_regression=True, has_selfcheck=True)
    with_c = _verdict_from_facts("x", blast=1, under_contract=True, has_regression=True, has_selfcheck=True)
    if not (with_c.landability < no_c.landability):
        failures.append("钉契约后落爪度未下降，契约风险没生效")

    # landability 与 axes 永远在 [0,1]
    for v in (full, big, with_c, leaf_blind):
        if not (0.0 <= v.landability <= 1.0) or any(not (0.0 <= ax.risk <= 1.0) for ax in v.axes.values()):
            failures.append(f"{v.target} 的分数越界 [0,1]")

    # 对真仓库跑一遍 triage 不抛错，且每条结论结构完整
    try:
        real = triage()
        for v in real:
            assert v.bin in (BIN_GREEN, BIN_YELLOW, BIN_RED), f"未知档位 {v.bin}"
            assert set(v.axes) == {"impact", "contract", "evidence"}, "三维不全"
        # 钉了契约的 bedrock（如 jsonlstore）在真仓库里不该被判 🟢 可独立落爪
        bench = {v.target: v for v in real}
        if "jsonlstore" in bench and bench["jsonlstore"].bin == BIN_GREEN:
            failures.append("jsonlstore 是钉契约的 bedrock，真仓库分诊不该判它 🟢 可独立落爪")
    except Exception as e:   # noqa: BLE001
        failures.append(f"对真仓库 triage 抛错（分诊本身成了伤口）：{type(e).__name__}: {e}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ triage selfcheck：三维评分单调、三档分诊判得对，载重 bedrock 不被误放给手，"
                  "对真仓库跑通不抛错——手会自己挑安全的活了。")
        else:
            print("❌ triage selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手任务分诊 🩺🖐️")
    ap.add_argument("--files", nargs="+", metavar="PATH",
                    help="只分诊给定的几个目标（默认全领地顶层模块）")
    ap.add_argument("--green", action="store_true", help="只列 🟢 可独立落爪的小修")
    ap.add_argument("--top", type=int, metavar="N", help="只看前 N 个")
    ap.add_argument("--json", action="store_true", help="机读：分诊表 + 阈值/权重")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：三维评分与三档分诊判得对（供 evidence 复跑）")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if _selfcheck(quiet=args.quiet) else 1)

    if args.json:
        print(json.dumps(manifest(args.files, top=args.top), ensure_ascii=False, indent=2))
        return

    verdicts = triage(args.files)
    if not args.quiet:
        print(render(verdicts, top=args.top, green_only=args.green))


if __name__ == "__main__":
    main()
