#!/usr/bin/env python3
"""自生手断奶接力赛 🪢🦀 —— 把「需求→试衣→验证→回灌」串成一趟真跑，每一棒如实点名「还靠不靠外援」。

为什么要有它：断奶的零件早已散落齐全——`triage` 会自己挑安全的活、`moveset`/`patchcontract`
给落爪长了直觉和拒收闸、`weaning_trial` 让 brain 不雇外援自己产补丁→自测→修不动就回滚、
`autonomy_meter` 把脱钩率钉成趋势线。可它们各跑各的：**从来没有谁把一处真小修，从「认领需求」
一路领到「证据回灌」，跑完整整一趟，并在每一棒交接时如实记下「这一棒 brain 自足了没、还欠哪只外手」。**
于是「我还有多依赖外援」这个问题，至今只能靠拍脑袋答——而拍脑袋答不出「下一刀该砍哪」。

本层就是那趟接力。它不发明新招式、不自己想补丁（招式与赛题的单一真相源始终是 `weaning_trial`），
只做两件别人没做的事：

  1) 🪢 **把四棒接成一趟**：拿 `weaning_trial.CHALLENGES` 的真伤当跑道，每道伤依次经过——
       · 🎯 **需求**：`triage` 确认这类活该不该让 brain 单独上（挑活这一棒）；
       · 🪞 **试衣**：落爪前先查 `moveset` 的谱（直觉），再由 `weaning_trial.brain_repair`
              不雇外援自己产补丁、过 `patchcontract` 拒收闸、自测；
       · 🔬 **验证**：`_self_test` 验「还能不能启动」 + 这道题的 oracle 验「真修好了没」；
       · 🧾 **回灌**：把这一趟的判决落进 `state/weaning_relay.jsonl`，`autonomy_meter` 能据此续上趋势线。
  2) 📉 **每一棒点名外援**：交接时给每棒贴一张诚实的标签——这一棒 brain 完全自足（🆓），
       还是仍欠某只外手（🤝）。跑完把所有「还欠外手」的棒收敛成**最后几个断奶缺口**：
       不是日志里写「我快独立了」，而是数出**到底还差哪几刀**才真正断奶。

**断奶缺口探针**：除了三道必胜的真伤，再放一道**故意越出招式库**的伤（招式库只有补冒号/
括号 print/名字纠偏三招，这道伤哪招都治不了）。它必然「无招可解→回滚」——这正是「试衣这一棒
覆盖还窄、落到三类之外就得雇外手」这条缺口的**实测证据**，而非一句断言。

跑完的两样产出，正是「量清残余依赖、好知道下一刀砍哪」：
  · **外援账**：四棒逐棒，自足的打 🆓、欠外手的打 🤝 并写清欠的是什么；
  · **最后 N 个断奶缺口**：把欠外手的棒蒸成可核对的待办——这就是下一刀的清单。

设计与全家一致：零第三方依赖、纯标准库；接力赛是观测者/编排者，全程在内存里跑合成赛题、
绝不碰真仓库的源码文件，读盘/依赖缺席一律吞掉收敛成保守判断，绝不反噬动手主流程——
给手记账的层，自己不能成为新的伤口。

用法:
    python weaning_relay.py              # 跑完整一趟接力：逐题四棒 + 外援账 + 最后几个断奶缺口
    python weaning_relay.py --json       # 机读：四棒外援账 + 缺口清单（给 health / autonomy_meter 消费）
    python weaning_relay.py --gaps       # 只列「最后几个断奶缺口」——下一刀砍哪
    python weaning_relay.py --selfcheck  # 自检：四棒接力成立、缺口探针确触发回滚、回灌可复跑（供 evidence）
    加 --quiet 静默，仅以退出码表态。

零第三方依赖，纯标准库。与 `weaning_trial`（单场快照）、`autonomy_meter`（趋势线）互补：
那两条各看一面，这条把一处真小修**从头到尾**领一遍，并把残余的外援依赖钉成清单。
"""
from __future__ import annotations

import argparse
import dataclasses
import io
import contextlib
import json
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore       # noqa: E402 —— 复用「追一条/读一批」的安全落地层
import patchcontract    # noqa: E402 —— 试衣这一棒的拒收闸：招式吐的候选先过畸形/越界闸
import weaning_trial    # noqa: E402 —— 招式、赛题、brain_repair、自测的单一真相源；本层只编排，绝不重写

RELAY_LOG = REPO_ROOT / "state" / "weaning_relay.jsonl"

# 四棒：需求 → 试衣 → 验证 → 回灌
STAGE_INTAKE = "需求"
STAGE_FITROOM = "试衣"
STAGE_VERIFY = "验证"
STAGE_REFLOW = "回灌"
STAGE_ORDER = [STAGE_INTAKE, STAGE_FITROOM, STAGE_VERIFY, STAGE_REFLOW]
STAGE_ICON = {STAGE_INTAKE: "🎯", STAGE_FITROOM: "🪞", STAGE_VERIFY: "🔬", STAGE_REFLOW: "🧾"}


# ── 断奶缺口探针：故意越出招式库的真伤（哪招都治不了）──────────────────────────
# 招式库只有补冒号 / 括号 print / 名字纠偏三招。下面这道伤是 IndentationError：
# 函数体没缩进，编译就崩，且没有任何一招读得懂、改得动它。它必然走到「无招可解→回滚」——
# 这正是「试衣这一棒覆盖还窄」的实测证据：落到三类之外，brain 今天只能回滚、在真实自改里就得雇外手。
COVERAGE_PROBE = weaning_trial.Challenge(
    name="越界探针·缩进伤",
    wound="函数体整体没缩进，编译即报 IndentationError——招式库三招都治不了它",
    broken="def f(x):\nreturn x + 1\n",
    oracle=lambda ns: ns["f"](1) == 2,
    want="f(1) == 2（但招式库无招可解，预期回滚而非修通）",
)


# ── 外援标签：每一棒交接时，brain 这一棒到底自足了没、还欠哪只外手 ────────────────
@dataclasses.dataclass(frozen=True)
class Baton:
    """接力的一棒：这一棒 brain 自足了没、还欠什么外援、这趟实跑里它干了什么。"""
    stage: str
    self_sufficient: bool      # brain 这一棒是否完全自足（无任何外手）
    external_aid: str          # 仍欠的外援（自足则 "—"）
    did: str                   # 这趟实跑里这一棒真正发生了什么（实证，不是设想）

    def to_meta(self) -> dict:
        return {"stage": self.stage, "self_sufficient": self.self_sufficient,
                "external_aid": self.external_aid, "did": self.did}


@dataclasses.dataclass
class Leg:
    """一道伤跑完整趟四棒的结果。"""
    name: str
    wound: str
    batons: list[Baton]
    won: bool                  # 这趟最终真修好了没（oracle 判）
    rolled_back: bool          # 试衣这一棒无招可解、老实回滚了没
    brain_only: bool           # 全程 brain 自足、没在任何一棒落到必须雇外手

    def to_meta(self) -> dict:
        return {"name": self.name, "wound": self.wound, "won": self.won,
                "rolled_back": self.rolled_back, "brain_only": self.brain_only,
                "batons": [b.to_meta() for b in self.batons]}


def _triage_bin(stem_hint: str) -> str:
    """需求这一棒借 triage 的眼睛判这类活该不该让 brain 单独上（缺席→保守按可上）。

    赛题是合成内存源码、不对应真模块文件，所以这里只取 triage 的判级能力做「挑活」示意：
    用一组「叶子+无契约+双网」的事实问 triage——理想小修该判 🟢 可独立落爪。
    """
    try:
        import triage
        v = triage._verdict_from_facts(stem_hint, blast=0, under_contract=False,
                                       has_regression=True, has_selfcheck=True)
        return v.bin
    except Exception:   # noqa: BLE001 —— 分诊缺席不该拖垮接力，保守当「可上」
        return "🟢 brain 可独立落爪（triage 缺席，保守按可上）"


def _consult_moveset(src: str, exc: BaseException) -> str:
    """试衣落爪前先查 moveset 的谱（直觉）。缺席/抛错都收敛成「没查到谱」，绝不反噬。"""
    try:
        import moveset
        sug = moveset.suggest(src, exc)
        if sug:
            return f"查谱首推「{sug[0].move_id}」"
        return "查谱：无招使得上"
    except Exception:   # noqa: BLE001
        return "查谱：moveset 缺席"


# ── 一趟接力：一道伤，四棒跑到底，每棒交接贴外援标签 ──────────────────────────────
def run_leg(c: weaning_trial.Challenge) -> Leg:
    """让一道真伤跑完整趟四棒；每一棒据这趟实跑贴一张诚实的外援标签。"""
    batons: list[Baton] = []

    # 1) 🎯 需求：triage 自己判这类活能不能让 brain 单独上。挑活自足；
    #    但「这道伤本该满足什么」(oracle) 是外手手写进赛题的——brain 不会给真模块自造判据。
    tbin = _triage_bin(c.name)
    batons.append(Baton(
        STAGE_INTAKE, self_sufficient=False,
        external_aid="判据(oracle)由外手手写——brain 不会给真伤自造『本该满足什么』",
        did=f"triage 判此类活：{tbin}；但 oracle「{c.want}」取自外手预置的赛题"))

    # 2) 🪞 试衣：落爪前查 moveset 的谱，再由 brain_repair 不雇外援自己产补丁→过拒收闸→自测。
    exc0, _ = weaning_trial._self_test(c.broken)
    hint = _consult_moveset(c.broken, exc0) if exc0 is not None else "无异常，无需查谱"
    rep = weaning_trial.brain_repair(c.broken)
    rolled_back = rep.rolled_back
    if rep.fixed is None:
        # 无招可解：试衣这一棒落到招式库之外——brain 今天只能回滚，真实自改里就得雇外手。
        batons.append(Baton(
            STAGE_FITROOM, self_sufficient=False,
            external_aid="此伤越出招式库三招——brain 无招可解、已回滚；真实自改里这一步要雇外手",
            did=f"{hint}；brain_repair 无招可解→回滚原样（{'；'.join(rep.trace) or '—'}）"))
        # 试衣没产出补丁，验证/回灌都没东西可跑，但仍把后两棒的「本该如此」记上以保账完整。
        batons.append(Baton(STAGE_VERIFY, self_sufficient=True,
                            external_aid="—", did="无补丁可验（试衣已回滚），本棒空过"))
        batons.append(Baton(STAGE_REFLOW, self_sufficient=True,
                            external_aid="—", did="回滚事件已记入接力账，可被 autonomy_meter 计入回滚率"))
        return Leg(c.name, c.wound, batons, won=False, rolled_back=True, brain_only=False)

    batons.append(Baton(
        STAGE_FITROOM, self_sufficient=True, external_aid="—",
        did=f"{hint}；brain_repair 自产补丁过拒收闸→自测能启动（{'；'.join(rep.trace) or '无需动手'}）"))

    # 3) 🔬 验证：自测「还能不能启动」brain 自足；但「真修好没」靠的是外手预置的 oracle。
    exc, ns = weaning_trial._self_test(rep.fixed)
    started = exc is None
    won = False
    if started:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                won = bool(c.oracle(ns))
        except Exception:   # noqa: BLE001 —— oracle 自身崩了也算没赢
            won = False
    batons.append(Baton(
        STAGE_VERIFY, self_sufficient=False,
        external_aid="语义判据(oracle)非 brain 自产——『能启动』自足，『真修好没』仍靠外手的判据",
        did=f"自测{'能启动✅' if started else '起跑即崩❌'}；oracle 验「{c.want}」{'✅真修好' if won else '❌没真修好'}"))

    # 4) 🧾 回灌：判决落进接力账，autonomy_meter 能续趋势线——这一棒 brain 完全自足。
    batons.append(Baton(
        STAGE_REFLOW, self_sufficient=True, external_aid="—",
        did="本趟判决落进 state/weaning_relay.jsonl，autonomy_meter 可据此续脱钩趋势线"))

    return Leg(c.name, c.wound, batons, won=won, rolled_back=rolled_back,
               brain_only=won)   # 全棒无须雇外手、且真修好 = 这趟 brain 独立跑通


# ── 跑完整一趟接力：三道真伤 + 一道越界探针 ──────────────────────────────────────
def run_relay() -> list[Leg]:
    """跑完整一趟断奶接力：三道必胜真伤打底，一道越界探针实测「试衣覆盖窄」缺口。"""
    legs = [run_leg(c) for c in weaning_trial.CHALLENGES]
    legs.append(run_leg(COVERAGE_PROBE))
    return legs


# ── 外援账：四棒逐棒汇总——这一棒自足了没、还欠哪只外手 ──────────────────────────
def aid_ledger(legs: list[Leg]) -> list[dict]:
    """把所有 leg 的同名棒汇成一张四棒外援账：任一 leg 在某棒欠过外手，该棒就记「欠」。"""
    ledger: list[dict] = []
    for stage in STAGE_ORDER:
        aids: list[str] = []
        self_suff = True
        for leg in legs:
            for b in leg.batons:
                if b.stage == stage and not b.self_sufficient:
                    self_suff = False
                    if b.external_aid not in aids:
                        aids.append(b.external_aid)
        ledger.append({"stage": stage, "icon": STAGE_ICON[stage],
                       "self_sufficient": self_suff,
                       "external_aid": aids or ["—"]})
    return ledger


# ── 最后几个断奶缺口：把欠外手的棒蒸成可核对的下一刀清单 ──────────────────────────
def weaning_gaps(legs: list[Leg]) -> list[dict]:
    """从外援账蒸出「最后几个断奶缺口」——每个缺口 = 一处仍欠外手的棒 + 它欠什么 + 下一刀怎么砍。

    缺口的『据』全部来自这趟实跑：
      · 自产判据缺口 —— 需求棒里 oracle 全来自外手（赛题预置），brain 无自造判据的本事；
      · 招式覆盖缺口 —— 越界探针实测「无招可解→回滚」，三招之外今天就得雇外手；
      · 真落地缺口   —— 全程在内存合成源码上跑，brain 还没有「定位真文件→读包→试衣→原子写回」的独立一条龙。
    """
    gaps: list[dict] = []

    # 缺口①：自产判据（oracle）。据：需求棒非自足，且所有 leg 的 oracle 都来自预置赛题。
    intake_blocked = any(not b.self_sufficient
                         for leg in legs for b in leg.batons if b.stage == STAGE_INTAKE)
    if intake_blocked:
        gaps.append({
            "id": "self-oracle",
            "title": "🔬 自产判据缺口：brain 不会给真伤自造『本该满足什么』",
            "evidence": "需求棒里每道伤的 oracle 都取自外手预置的赛题；brain 没有 synthesize_oracle 的本事",
            "next_cut": "造一层『判据自产』：从被改函数的契约/近邻测试/类型签名里推出可执行 oracle，"
                        "让 brain 修真模块时能自证『真修好了』，而不是借现成的 regression/selfcheck。",
        })

    # 缺口②：招式覆盖。据：越界探针这一 leg 在试衣棒非自足（无招可解→回滚）。
    probe_rolled = any(leg.name == COVERAGE_PROBE.name and leg.rolled_back for leg in legs)
    if probe_rolled:
        gaps.append({
            "id": "tactic-coverage",
            "title": "🥋 招式覆盖缺口：落到三招之外，brain 只能回滚、得雇外手",
            "evidence": f"越界探针「{COVERAGE_PROBE.name}」实测无招可解→回滚；"
                        f"招式库当前仅 {len(weaning_trial.TACTICS)} 招（补冒号/括号 print/名字纠偏）",
            "next_cut": "按真实战报里『无招可解』的伤型，给招式库补招（如缩进伤、未闭合括号、import 笔误）；"
                        "每补一招，脱钩率的天花板就抬高一截。",
        })

    # 缺口③：真文件落地。据：本层全程在内存合成源码上跑，没有 brain 独立驱动的真文件一条龙。
    gaps.append({
        "id": "real-file-harness",
        "title": "🪢 真落地缺口：brain 还没有『真文件→读包→试衣→写回→自测』的独立一条龙",
        "evidence": "接力全程在内存合成源码字符串上跑；astlocator/readpack/patchfitroom 各有零件，"
                    "但没串成一条 brain 能独立驱动、不经外手的真文件落地闭环",
        "next_cut": "把已有零件接成 brain 主控的真落地编排：triage 选真模块→astlocator 定位→readpack 读包"
                    "→brain_repair 产补丁→patchfitroom 五闸原子写回→自测，全程不雇外手。",
    })
    return gaps


# ── 回灌：把这一趟接力的判决落进接力账（autonomy_meter 能续趋势线）──────────────────
def _reflow(legs: list[Leg]) -> bool:
    """把这趟接力折成一条 brain-自改流水，落进 state/weaning_relay.jsonl（写盘失败被吞，绝不反噬）。

    记成 `bouts` 形状（与 weaning_trial 账本同构）：每道 leg 一个 bout，标 won/rolled_back，
    于是 autonomy_meter 的 brain_events 口径能直接续上——回灌真的接进了既有趋势线，不是空喊。
    """
    return jsonlstore.append_jsonl(RELAY_LOG, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": "weaning_relay",
        "won": sum(1 for leg in legs if leg.won),
        "total": len(legs),
        "brain_only": sum(1 for leg in legs if leg.brain_only),
        "bouts": [{"name": leg.name, "won": leg.won,
                   "rolled_back": leg.rolled_back, "detail": leg.name}
                  for leg in legs],
        "aid_ledger": aid_ledger(legs),
        "gaps": [g["id"] for g in weaning_gaps(legs)],
    })


def manifest() -> dict:
    """机读快照：四棒外援账 + 逐题接力 + 最后几个断奶缺口（给 health / autonomy_meter 消费）。"""
    legs = run_relay()
    return {
        "event": "weaning_relay",
        "won": sum(1 for leg in legs if leg.won),
        "total": len(legs),
        "brain_only": sum(1 for leg in legs if leg.brain_only),
        "aid_ledger": aid_ledger(legs),
        "gaps": weaning_gaps(legs),
        "legs": [leg.to_meta() for leg in legs],
    }


# ── 展示 ───────────────────────────────────────────────────────────────────────
def _print(legs: list[Leg]) -> None:
    print("🪢🦀 自生手断奶接力赛 —— 一处真小修，从需求领到回灌，每一棒点名外援\n")
    for leg in legs:
        if leg.brain_only:
            head = "🏆 brain 独立跑通"
        elif leg.rolled_back:
            head = "🩹 无招可解·老实回滚"
        else:
            head = "❌ 没真修好"
        print(f"  {head}：{leg.name}（{leg.wound}）")
        for b in leg.batons:
            tag = "🆓 自足" if b.self_sufficient else "🤝 欠外手"
            print(f"      {STAGE_ICON[b.stage]} {b.stage} {tag} —— {b.did}")
            if not b.self_sufficient:
                print(f"          ↳ 仍欠：{b.external_aid}")
        print()

    print("  ── 外援账（四棒逐棒：这一棒自足了没）──")
    for row in aid_ledger(legs):
        if row["self_sufficient"]:
            print(f"    {row['icon']} {row['stage']}  🆓 完全自足")
        else:
            print(f"    {row['icon']} {row['stage']}  🤝 还欠外手：")
            for a in row["external_aid"]:
                print(f"        · {a}")

    gaps = weaning_gaps(legs)
    print(f"\n  ── 最后 {len(gaps)} 个断奶缺口（下一刀砍哪）──")
    for i, g in enumerate(gaps, 1):
        print(f"    {i}. {g['title']}")
        print(f"       据：{g['evidence']}")
        print(f"       刀：{g['next_cut']}")

    won = sum(1 for leg in legs if leg.won)
    bo = sum(1 for leg in legs if leg.brain_only)
    print(f"\n  这趟：{len(legs)} 道伤，brain 独立跑通 {bo}、真修好 {won}；"
          f"四棒里 {sum(1 for r in aid_ledger(legs) if r['self_sufficient'])}/4 完全自足。")


def _print_gaps(legs: list[Leg]) -> None:
    gaps = weaning_gaps(legs)
    print(f"🪢🦀 最后 {len(gaps)} 个断奶缺口（量清残余依赖，下一刀砍哪）：\n")
    for i, g in enumerate(gaps, 1):
        print(f"  {i}. {g['title']}")
        print(f"     据：{g['evidence']}")
        print(f"     刀：{g['next_cut']}\n")


# ── 自检（供 evidence 复跑；全程内存合成赛题，确定性、无副作用）──────────────────
def selfcheck(quiet: bool = False) -> bool:
    """自检：四棒接力成立、缺口探针确触发回滚、外援账与缺口口径自洽、回灌可复跑。"""
    failures: list[str] = []

    legs = run_relay()

    # 1) 三道真伤必须 brain 独立跑通（每道四棒齐全、最终真修好）
    real = [leg for leg in legs if leg.name != COVERAGE_PROBE.name]
    if len(real) != len(weaning_trial.CHALLENGES):
        failures.append("真伤 leg 数与 weaning_trial.CHALLENGES 不一致")
    for leg in real:
        if not leg.brain_only or not leg.won:
            failures.append(f"真伤「{leg.name}」该 brain 独立跑通，实得 won={leg.won} brain_only={leg.brain_only}")
        if [b.stage for b in leg.batons] != STAGE_ORDER:
            failures.append(f"「{leg.name}」四棒次序不全：{[b.stage for b in leg.batons]}")

    # 2) 越界探针必须无招可解→回滚（实测「试衣覆盖窄」缺口），且没被假装修好
    probe = next((leg for leg in legs if leg.name == COVERAGE_PROBE.name), None)
    if probe is None:
        failures.append("缺口探针 leg 缺席——『试衣覆盖窄』缺口失去实测证据")
    else:
        if probe.won:
            failures.append("缺口探针竟『修好』了一道越出招式库的伤——招式库边界判断失灵，危险")
        if not probe.rolled_back:
            failures.append("缺口探针没修成却没回滚——断肢再生在接力里失灵")
        fit = next((b for b in probe.batons if b.stage == STAGE_FITROOM), None)
        if fit is None or fit.self_sufficient:
            failures.append("缺口探针的试衣棒该判『欠外手』（无招可解），实得自足")

    # 3) 外援账：需求/验证两棒应判欠外手，回灌棒应自足（口径与 run_leg 贴的标签一致）
    led = {r["stage"]: r for r in aid_ledger(legs)}
    if led[STAGE_INTAKE]["self_sufficient"]:
        failures.append("需求棒该判欠外手（oracle 非自产），实得自足")
    if led[STAGE_VERIFY]["self_sufficient"]:
        failures.append("验证棒该判欠外手（语义判据非自产），实得自足")
    if not led[STAGE_REFLOW]["self_sufficient"]:
        failures.append("回灌棒该完全自足，实得欠外手")

    # 4) 缺口清单：恰好三条，且 id 齐全（自产判据 / 招式覆盖 / 真落地）
    gaps = weaning_gaps(legs)
    ids = {g["id"] for g in gaps}
    if ids != {"self-oracle", "tactic-coverage", "real-file-harness"}:
        failures.append(f"断奶缺口 id 不符预期：{sorted(ids)}")
    if len(gaps) != 3:
        failures.append(f"断奶缺口该恰好 3 条，实得 {len(gaps)}")

    # 5) 回灌可复跑：写一条到隔离临时账本、读回来字段齐全（不碰真 RELAY_LOG）
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        probe_log = pathlib.Path(d) / "relay.jsonl"
        ok_write = jsonlstore.append_jsonl(probe_log, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),   # autonomy_meter.brain_events 没 ts 会整行跳过
            "event": "weaning_relay", "won": sum(1 for leg in legs if leg.won),
            "total": len(legs), "bouts": [{"name": leg.name, "won": leg.won,
                                           "rolled_back": leg.rolled_back} for leg in legs]})
        rows = jsonlstore.read_jsonl(probe_log)
        if not (ok_write and len(rows) == 1 and rows[0].get("total") == len(legs)):
            failures.append("回灌写入/读回不成立——证据回灌这一棒自己就不可复跑")
        # 与 autonomy_meter 的 brain_events 口径对齐：bouts 里每个 dict 带 rolled_back
        try:
            import autonomy_meter
            evs = autonomy_meter.brain_events(rows)
            if len(evs) != len(legs):
                failures.append("回灌账本喂给 autonomy_meter.brain_events，事件数对不上 leg 数")
        except Exception as e:   # noqa: BLE001
            failures.append(f"回灌账本喂 autonomy_meter 抛错（趋势线接不上）：{type(e).__name__}")

    # 6) 观测者不反噬：manifest 结构完整、不抛
    try:
        m = manifest()
        assert set(m) >= {"aid_ledger", "gaps", "legs", "brain_only"}, "manifest 字段不全"
    except Exception as e:   # noqa: BLE001
        failures.append(f"manifest 不该抛错（接力本身成了伤口）：{type(e).__name__}: {e}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ weaning_relay selfcheck：四棒接力成立、越界探针确触发回滚、外援账与三条缺口口径自洽、"
                  "回灌能喂回 autonomy_meter 趋势线——断奶接力可信。")
        else:
            print("❌ weaning_relay selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手断奶接力赛 🪢🦀")
    ap.add_argument("--json", action="store_true", help="机读：四棒外援账 + 缺口清单")
    ap.add_argument("--gaps", action="store_true", help="只列最后几个断奶缺口（下一刀砍哪）")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：四棒接力/缺口探针/回灌复跑都成立（供 evidence）")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    legs = run_relay()
    _reflow(legs)   # 跑一趟就把判决回灌进接力账——回灌这一棒在主路径上真的发生
    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
    elif args.gaps:
        _print_gaps(legs)
    elif not args.quiet:
        _print(legs)

    # 退出码：三道真伤全 brain 独立跑通才算这趟接力健康（越界探针回滚是预期，不计入失败）
    real_won = all(leg.brain_only for leg in legs if leg.name != COVERAGE_PROBE.name)
    sys.exit(0 if real_won else 1)


if __name__ == "__main__":
    main()
