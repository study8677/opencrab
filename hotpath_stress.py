#!/usr/bin/env python3
"""opencrab 自生手热路径端到端压测 ⏱️🖐️

一句话：**拿几道真实小修当负载，把自生手的整条热路径——brain(产补丁) → 试衣(过五闸) →
验证(还能不能启动 + 真修好了没) → 回灌(提炼成证据)——逐段掐表跑一遍，量出第一个卡点。**

为什么要有它：`weaning_trial.py` 证明了 brain **修得对**(实战通过率)，`patchfitroom.py`
证明了补丁**落得稳**(五闸不伤身)，`handsdojo`/`handsfeedback` 证明了失败/成功都能**沉淀**。
可它们各自只验自己那一段对不对——没有谁回答过：这四段**串成一条热路径**跑起来，时间
都耗在哪？哪一段是把「会动手」拖成「手不稳」的瓶颈？会动手不等于手稳：稳，先得知道
慢在哪、卡在哪。这一层就专做这件事——给热路径装上秒表与卡点探针。

热路径四段（与 `hands.py` 真实动手时的顺序同构）：

  · 🧠 **brain**：`weaning_trial.brain_repair` 读报错→挑招改一处→自测，反复到修通或无招可解。
    内含 `patchcontract` 形状闸(畸形/越界当场拒)。修不动 = 这一段就是**硬卡点**，后段不必再跑。
  · 🪞 **试衣(fit)**：`patchfitroom.fit(apply=False)` 把候选穿到隔离副本上过**五闸**
    (形状/语法/触觉/import/契约)——只试穿、绝不写真文件。每道闸起一个子进程，最贵的一段。
  · ✅ **验证(verify)**：把候选 `compile`+`exec`(就是「还能不能启动」)，再用这道题的 oracle
    判「**真修好了没**」——能启动只证明没改死，oracle 过了才算这一爪真稳。
  · 🧾 **回灌(feed)**：`handsfeedback.distill` 把这次(构造的)成功动手提炼成回灌记录——
    **不写真账本**，只验证据能否成形、认得出改过的模块。

全程在隔离临时仓库 + 提炼态里跑：绝不雇爪子、不改真仓库、不写真账本/真证据——压测自己
绝不能成为新故障源。逐段用 `perf_counter` 掐墙钟，跑完报告：
  · 任一段失败 → 那是**硬卡点**(按 brain→fit→verify→feed 的路径序，第一个失败的段)，优先报。
  · 全过 → 墙钟占比最高的那一段就是**首个性能卡点**，配上各段毫秒数与占比。

每场压测的结论追加进 state/ 下被 .gitignore 的流水账，供事后复盘趋势。任一硬卡点退出码
非零——可挂钩子 / CI 当热路径门禁。零第三方依赖，纯标准库。

用法:
    python hotpath_stress.py            # 跑全部小修，打印逐段秒表 + 卡点报告
    python hotpath_stress.py --json     # 导出机读报告(给 health / 外部消费)
    python hotpath_stress.py --selfcheck  # 自检：热路径全段贯通且卡点判定成立(供 evidence 复跑)
    加 --quiet 静默，仅以退出码表态。
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import pathlib
import sys
import tempfile
import time
from time import perf_counter

import weaning_trial   # 复用它的 3 道真实小修(CHALLENGES)与 brain 自修(brain_repair)
import patchfitroom    # 试衣间五闸
import handsfeedback   # 回灌提炼(distill，纯函数、不写账本)
import jsonlstore

REPO_ROOT = pathlib.Path(__file__).resolve().parent
STRESS_LOG = REPO_ROOT / "state" / "hotpath_stress.jsonl"

# 热路径四段，按真实动手时的先后排序——卡点判定与路径短路都依赖这个顺序。
STAGE_BRAIN = "brain"     # 🧠 产 brain-only 补丁(含 patchcontract 形状闸)
STAGE_FIT = "fit"         # 🪞 试衣间五闸试穿(apply=False，零副作用)
STAGE_VERIFY = "verify"   # ✅ 还能不能启动 + oracle 判真修好了没
STAGE_FEED = "feed"       # 🧾 提炼成回灌记录(不写真账本)
STAGE_ORDER = [STAGE_BRAIN, STAGE_FIT, STAGE_VERIFY, STAGE_FEED]

# 每道真实小修在试衣阶段要落的临时模块名 + 契约该验它满足什么(给 fit 的契约闸用)。
# 用源码串而非 lambda：契约闸在子进程里跑 contracts.verify()，oracle 得能跨进程复刻。
# 键对齐 weaning_trial.CHALLENGES 的 name，缺一即视为题面变更、压测当场报错(别默默漏验)。
FIT_SPECS: dict[str, tuple[str, str]] = {
    "补冒号":     ("addmod",    "assert addmod.add(2, 3) == 5, 'add(2,3) 必须为 5'"),
    "括号 print": ("greetmod",  "assert greetmod.greet('crab') == 'hi crab', \"greet 必须拼出 'hi crab'\""),
    "名字纠偏":   ("doublemod", "assert doublemod.RESULT == 42, 'RESULT 必须为 42'"),
}

# 一个 contracts.py 的最小同构件：verify()/summarize() 与真层接口一致，只验当前这道小修。
_CONTRACTS_TMPL = '''\
import {mod}


class V:
    def __init__(self, module, ok, detail):
        self.module = module
        self.ok = ok
        self.detail = detail


def verify():
    try:
        {check}
        return [V({mod!r}, True, "")]
    except Exception as e:  # noqa: BLE001
        return [V({mod!r}, False, str(e))]


def summarize(vs):
    bad = [v for v in vs if not v.ok]
    return (not bad, len(bad))
'''


@dataclasses.dataclass(frozen=True)
class StageTiming:
    """热路径一段的秒表读数与判决。"""
    stage: str
    ok: bool
    ms: float          # 这一段的墙钟(毫秒)
    detail: str

    def to_meta(self) -> dict:
        return {"stage": self.stage, "ok": self.ok,
                "ms": round(self.ms, 2), "detail": self.detail}


@dataclasses.dataclass
class CaseResult:
    """一道真实小修跑完整条热路径的结果。"""
    name: str
    wound: str
    stages: list[StageTiming]
    blocked_at: str | None     # 硬卡点所在段(None = 全段贯通)

    @property
    def ok(self) -> bool:
        return self.blocked_at is None

    @property
    def total_ms(self) -> float:
        return sum(s.ms for s in self.stages)

    def to_meta(self) -> dict:
        return {"name": self.name, "wound": self.wound, "ok": self.ok,
                "blocked_at": self.blocked_at,
                "total_ms": round(self.total_ms, 2),
                "stages": [s.to_meta() for s in self.stages]}


def _run_oracle(candidate: str, oracle) -> tuple[bool, str]:
    """验证段：compile+exec 候选(还能不能启动)，再用 oracle 判真修好了没。"""
    try:
        code = compile(candidate, "<hotpath-candidate>", "exec")
    except SyntaxError as e:
        return False, f"候选编译不过(理应已被 brain 修通): {e}"
    ns: dict = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(code, ns)  # noqa: S102 —— 跑的是压测里自造的隔离源码，无外部输入
    except BaseException as e:  # noqa: BLE001
        return False, f"候选起跑即崩: {type(e).__name__}: {e}"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            won = bool(oracle(ns))
    except Exception as e:  # noqa: BLE001
        return False, f"oracle 判定时崩了: {type(e).__name__}"
    return won, ("能启动且 oracle 过——这一爪真修好了" if won
                 else "能启动，但 oracle 没过：补丁没真修好")


def _stress_fit(modname: str, before: str, candidate: str, check: str) -> StageTiming:
    """试衣段：在隔离临时仓库里让候选过五闸(apply=False)，掐这一段墙钟。"""
    t0 = perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="hotpath-fit-") as d:
            dp = pathlib.Path(d)
            (dp / "contracts.py").write_text(
                _CONTRACTS_TMPL.format(mod=modname, check=check), encoding="utf-8")
            target = dp / f"{modname}.py"
            target.write_text(before, encoding="utf-8")   # before = 坏源码，当被改的真文件
            r = patchfitroom.fit(target, candidate, repo=dp, apply=False,
                                 check_contracts=True)
        ms = (perf_counter() - t0) * 1000
        # apply=False 下「全闸通过」表现为 written=False、gate==""——这才是试穿过关。
        passed = (r.gate == "")
        if passed:
            return StageTiming(STAGE_FIT, True, ms,
                               f"五闸全过({' → '.join(r.gates_run)})")
        return StageTiming(STAGE_FIT, False, ms,
                           f"卡在 {r.gate} 闸：{r.detail}")
    except Exception as e:  # noqa: BLE001 —— 压测自己绝不成为新伤口
        return StageTiming(STAGE_FIT, False, (perf_counter() - t0) * 1000,
                           f"试衣段出意外: {type(e).__name__}: {e}")


def run_case(challenge) -> CaseResult:
    """让一道真实小修跑完整条热路径，逐段掐表；任一段失败即为硬卡点，后段不再跑。"""
    spec = FIT_SPECS.get(challenge.name)
    if spec is None:   # 题面变了却没同步 FIT_SPECS——别默默漏验，当场把它记成 brain 段硬卡点
        return CaseResult(
            challenge.name, challenge.wound,
            [StageTiming(STAGE_BRAIN, False, 0.0,
                         f"FIT_SPECS 缺「{challenge.name}」的试衣规格，无法压测")],
            blocked_at=STAGE_BRAIN)
    modname, check = spec
    stages: list[StageTiming] = []

    # ── 🧠 brain：产 brain-only 补丁(含形状闸) ──
    t0 = perf_counter()
    rep = weaning_trial.brain_repair(challenge.broken)
    ms = (perf_counter() - t0) * 1000
    if rep.fixed is None:
        stages.append(StageTiming(STAGE_BRAIN, False, ms,
                                  f"brain 无招可解，已回滚({'；'.join(rep.trace) or '—'})"))
        return CaseResult(challenge.name, challenge.wound, stages, blocked_at=STAGE_BRAIN)
    stages.append(StageTiming(STAGE_BRAIN, True, ms,
                              f"独立修通：{'；'.join(rep.trace) or '无需动手'}"))
    candidate = rep.fixed

    # ── 🪞 试衣：五闸试穿(apply=False) ──
    fit_stage = _stress_fit(modname, challenge.broken, candidate, check)
    stages.append(fit_stage)
    if not fit_stage.ok:
        return CaseResult(challenge.name, challenge.wound, stages, blocked_at=STAGE_FIT)

    # ── ✅ 验证：还能不能启动 + oracle 判真修好了没 ──
    t0 = perf_counter()
    won, why = _run_oracle(candidate, challenge.oracle)
    ms = (perf_counter() - t0) * 1000
    stages.append(StageTiming(STAGE_VERIFY, won, ms, why))
    if not won:
        return CaseResult(challenge.name, challenge.wound, stages, blocked_at=STAGE_VERIFY)

    # ── 🧾 回灌：提炼成回灌记录(不写真账本) ──
    t0 = perf_counter()
    fake_result = {                       # 构造一份「成功动手」结果，只喂 distill 提炼
        "branch": f"crab/hotpath-{modname}", "executor": "brain",
        "integrate": "merge", "changed": True, "ok": True,
        "self_test": "自测通过：改完还能正常启动",
        "diffstat": f"{modname}.py | 2 +-\n 1 file changed",
    }
    rec = handsfeedback.distill(fake_result)
    ms = (perf_counter() - t0) * 1000
    if rec is None or not rec.get("passed") or modname not in rec.get("modules", []):
        stages.append(StageTiming(STAGE_FEED, False, ms,
                                  f"提炼出的回灌记录不对劲：{rec}"))
        return CaseResult(challenge.name, challenge.wound, stages, blocked_at=STAGE_FEED)
    stages.append(StageTiming(STAGE_FEED, True, ms,
                              f"提炼成回灌记录(认出改过 {rec['modules']}、判 passed)"))
    return CaseResult(challenge.name, challenge.wound, stages, blocked_at=None)


def run() -> list[CaseResult]:
    """拿 weaning_trial 的 3 道真实小修当负载，逐道跑完整条热路径。"""
    return [run_case(c) for c in weaning_trial.CHALLENGES]


@dataclasses.dataclass(frozen=True)
class Bottleneck:
    """整场压测的卡点裁决。"""
    kind: str          # "hard"=有段跑失败 / "perf"=全过但某段最慢 / "none"=没有可量的负载
    stage: str         # 卡点所在段
    detail: str

    def to_meta(self) -> dict:
        return {"kind": self.kind, "stage": self.stage, "detail": self.detail}


def stage_totals(cases: list[CaseResult]) -> dict[str, float]:
    """各段在所有小修上累计的墙钟(毫秒)，按热路径顺序聚合。"""
    totals = {s: 0.0 for s in STAGE_ORDER}
    for c in cases:
        for s in c.stages:
            totals[s.stage] = totals.get(s.stage, 0.0) + s.ms
    return totals


def find_bottleneck(cases: list[CaseResult]) -> Bottleneck:
    """量出首个卡点：先看有没有硬卡点(按路径序最靠前的失败段)，没有再挑墙钟占比最高的段。"""
    # 1) 硬卡点优先：任一段失败，按 brain→fit→verify→feed 取最靠前的那个失败段。
    failed_stages = {c.blocked_at for c in cases if c.blocked_at}
    for stage in STAGE_ORDER:
        if stage in failed_stages:
            who = "、".join(c.name for c in cases if c.blocked_at == stage)
            return Bottleneck("hard", stage,
                              f"「{who}」卡在 {stage} 段——热路径在这里断了，先修通再谈快慢")
    # 2) 全过 → 性能卡点：墙钟占比最高的段。
    totals = stage_totals(cases)
    grand = sum(totals.values())
    if grand <= 0:
        return Bottleneck("none", "", "没有可量的负载")
    slow = max(totals, key=lambda s: totals[s])
    pct = totals[slow] / grand * 100
    return Bottleneck("perf", slow,
                      f"全段贯通；墙钟最重的是 {slow} 段：{totals[slow]:.1f}ms / 占 {pct:.0f}%")


def _record(cases: list[CaseResult], bn: Bottleneck) -> None:
    """整场压测结论落进流水账(写盘失败被吞，绝不反噬主流程)。"""
    try:
        jsonlstore.append_jsonl(STRESS_LOG, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "hotpath_stress",
            "ok": all(c.ok for c in cases),
            "bottleneck": bn.to_meta(),
            "stage_totals_ms": {k: round(v, 2) for k, v in stage_totals(cases).items()},
            "cases": [c.to_meta() for c in cases],
        })
    except Exception:  # noqa: BLE001
        pass


def _print(cases: list[CaseResult], bn: Bottleneck) -> None:
    print("⏱️🖐️  opencrab 自生手热路径端到端压测")
    print("    负载：weaning_trial 的 3 道真实小修")
    print(f"    热路径：{' → '.join(STAGE_ORDER)}\n")
    for c in cases:
        head = "✅" if c.ok else "❌"
        print(f"  {head} {c.name}（{c.wound}）— 合计 {c.total_ms:.1f}ms")
        for s in c.stages:
            mark = "·" if s.ok else "✗"
            print(f"      {mark} {s.stage:<7}{s.ms:7.1f}ms  {s.detail}")
    totals = stage_totals(cases)
    grand = sum(totals.values()) or 1.0
    print("\n    各段墙钟累计：")
    for stage in STAGE_ORDER:
        v = totals[stage]
        bar = "█" * round(v / grand * 24)
        print(f"      {stage:<7}{v:8.1f}ms  {v / grand * 100:4.0f}%  {bar}")
    print()
    if bn.kind == "hard":
        print(f"🛑 硬卡点：{bn.detail}")
    elif bn.kind == "perf":
        print(f"📍 首个卡点（性能）：{bn.detail}")
        print("    会动手已经成立；要让手更稳/更快，先从这一段下手。")
    else:
        print(f"⚠️  {bn.detail}")


def selfcheck(quiet: bool = False) -> bool:
    """自检：3 道小修热路径全段贯通，且卡点判定逻辑成立。供 evidence 复跑。"""
    failures: list[str] = []

    cases = run()
    for c in cases:
        if not c.ok:
            failures.append(f"「{c.name}」热路径没贯通，卡在 {c.blocked_at}："
                            + next((s.detail for s in c.stages if not s.ok), "?"))
        # 每道贯通的小修都该实打实跑过四段，且各段都有墙钟读数(掐表真在转)。
        elif [s.stage for s in c.stages] != STAGE_ORDER:
            failures.append(f"「{c.name}」跑过的段不齐：{[s.stage for s in c.stages]}")

    # 卡点判定：全过时必须报性能卡点、且点名的段确实是墙钟最重的那段。
    bn = find_bottleneck(cases)
    if all(c.ok for c in cases):
        if bn.kind != "perf":
            failures.append(f"全段贯通却没报性能卡点：{bn.to_meta()}")
        else:
            totals = stage_totals(cases)
            if bn.stage != max(totals, key=lambda s: totals[s]):
                failures.append(f"性能卡点点名 {bn.stage}，但墙钟最重的并非它：{totals}")

    # 硬卡点探针：构造一道 brain 修不动的伤(顶层 raise)，必须被判成 brain 段硬卡点。
    probe = run_case(weaning_trial.ROLLBACK_PROBE)
    if probe.ok or probe.blocked_at != STAGE_BRAIN:
        failures.append(f"硬卡点探针：无解伤本该卡在 brain 段，实得 blocked_at={probe.blocked_at}")
    probe_bn = find_bottleneck([probe])
    if probe_bn.kind != "hard" or probe_bn.stage != STAGE_BRAIN:
        failures.append(f"硬卡点探针：卡点裁决该是 brain 段 hard，实得 {probe_bn.to_meta()}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ hotpath_stress selfcheck：3 道真实小修热路径全段贯通，"
                  "性能卡点点到墙钟最重的段，硬卡点探针也被准确判出——压测可信。")
        else:
            print("❌ hotpath_stress selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


def manifest() -> dict:
    """机读快照，给 health / 外部消费。"""
    cases = run()
    bn = find_bottleneck(cases)
    return {"event": "hotpath_stress", "ok": all(c.ok for c in cases),
            "stages": STAGE_ORDER, "bottleneck": bn.to_meta(),
            "stage_totals_ms": {k: round(v, 2) for k, v in stage_totals(cases).items()},
            "cases": [c.to_meta() for c in cases]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手热路径端到端压测 ⏱️🖐️")
    ap.add_argument("--json", action="store_true", help="导出机读压测报告")
    ap.add_argument("--selfcheck", action="store_true", help="自检模式(给 evidence 复跑)")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    cases = run()
    bn = find_bottleneck(cases)
    _record(cases, bn)
    if args.json:
        if not args.quiet:
            print(json.dumps(manifest(), ensure_ascii=False, indent=2))
    elif not args.quiet:
        _print(cases, bn)

    sys.exit(0 if all(c.ok for c in cases) else 1)


if __name__ == "__main__":
    main()
