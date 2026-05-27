#!/usr/bin/env python3
"""试衣间拒收返工单 🪞🧵 —— 把一次被拒收的补丁，自动封成可复跑的 replay 案例 + 一道 coach 训练题。

为什么要有它：`patchfitroom.py` 这间试衣间会把候选补丁拦在语法/import/契约各道闸外，
真文件分毫不动——它**当场就把伤挡住了**。可挡住之后，那次拒收就随退出码一起蒸发了：
没人记得「brain 那一爪当时为什么不该收」，下次同样的错法照样会再产一遍。自生的手会犯错
不可怕，可怕的是**犯过的错复练不到**。这里把每一次拒收都收成两样东西，让它能被反复练回来：

  1) 🎞️ **一个 replay 案例**：把「这段候选 + 这个目标文件」封成一条可重跑的回归用例。
     重跑走的是 `patchfitroom --fit-dry`（只试穿、绝不写真文件），于是 replay 的判定天然成立——
       · reproduced  今天这段候选仍被同一道闸拒 —— 这个坑还在；
       · fixed       今天它过闸了（目标/契约已演进得能接住它）—— 坑填上了。
     复跑零副作用：dry 模式下哪怕五闸全过也不写回，回归套永远不会反手改坏真仓库。

  2) 🏋️ **一道 coach 训练回合**：把这次拒收当成一次失败现场喂给 `coach.py`，长出
     「复现→定根因→最小修→加守卫→沉记忆」那套对症练习——把「为什么这一爪不收」练成本事。

接口的核心是 `seal(result, candidate)`：吃一个 `patchfitroom.FitResult` 与对应的候选源码。
**只封拒收**（written=False 且确实卡在某道闸）；过了闸的、apply=False 看效果的，都不是要返工的料，
直接跳过。`persist=False` 时只搭出案例/回合对象给人预览、绝不落盘（契约验收即走这条纯净路径）。

设计原则与 replay/coach 一致：零第三方依赖、纯标准库；封存是观测者，落盘失败一律吞掉，
绝不反噬这只生命——给摔倒立档的手，自己不能成为新的伤口。

用法:
    python fitrework.py                       # 演示：几种拒收各封一遍(不落盘)
    python fitrework.py --selfcheck           # 自检：拒收才封 / 过闸跳过 / 案例命令可零副作用重跑
    python fitrework.py --json                # 机读：返工单结构说明
    python fitrework.py --fit PATH            # 从 stdin 读候选，对 PATH 试穿；拒收则自动封成返工单

零第三方依赖，纯标准库。
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

import errors
import patchfitroom
import replay


@dataclasses.dataclass
class SealResult:
    """一次封存的结论：拒收被封成了哪个 replay 案例 / 哪道 coach 题，落没落盘。"""
    sealed: bool          # 这次拒收是否被封成返工单(过了闸/无 gate → False)
    reason: str           # 一句人话：封了 / 为何没封
    gate: str             # 被哪道闸拒(shape/syntax/import/contract)
    target: str           # 被改的目标文件
    topic: str            # 训练题主题(也是案例标题)
    case_id: str          # replay 案例号(没封→"")
    persisted: bool       # 是否真落盘(persist=False 或落盘失败→False)

    def to_meta(self) -> dict:
        return dataclasses.asdict(self)


def _relpath(target: pathlib.Path) -> str:
    """目标文件相对仓库根的路径(给 replay 命令用)；不在仓库内则退回原样。"""
    try:
        return str(pathlib.Path(target).resolve().relative_to(REPO_ROOT))
    except Exception:
        return str(target)


def _replay_command(target: pathlib.Path) -> list[str]:
    """重跑这次拒收的命令：用 --fit-dry 只试穿不写回，于是回归套零副作用。"""
    return [sys.executable, "patchfitroom.py", "--fit-dry", _relpath(target), "--quiet"]


def _topic(result: patchfitroom.FitResult) -> str:
    """一句训练主题 / 案例标题：点名目标与卡住的那道闸。"""
    name = pathlib.Path(result.target).name
    return f"试衣间在「{result.gate}」闸拒收了对 {name} 的补丁"


def _build_case(result: patchfitroom.FitResult, candidate: str,
                *, persist: bool) -> replay.Case:
    """据一次拒收搭出一个 replay 案例对象。

    退出码定 1、stderr 留空：与 `--fit-dry` 重跑一次拒收时的现场(打印走 stdout、stderr 空、退出 1)
    同构，好让 replay 的分流码前后一致地判 reproduced；现场细节落在 stdout/note 里供 --show 翻查。
    env 仅在 persist 时抓真实摘要——预览路径不必为此起 git 子进程。
    """
    command = _replay_command(pathlib.Path(result.target))
    detail = f"试衣间拒收：卡在 {result.gate} 闸 —— {result.detail}"
    return replay.Case(
        case_id=replay._new_case_id(),
        created_at=datetime.datetime.now().isoformat(timespec="milliseconds"),
        title=_topic(result),
        command=command,
        cwd=".",
        env=replay.env_summary() if persist else {},
        stdin=candidate,
        exit_code=1,
        stdout=detail,
        stderr="",
        error=errors.triage(stderr="", exit_code=1, message=" ".join(command)),
        note=(f"由试衣间拒收自动封存。gate={result.gate}；"
              f"重跑走 --fit-dry，过闸即判 fixed、仍被同闸拒即 reproduced。"),
    )


def seal(result: patchfitroom.FitResult, candidate: str, *,
         persist: bool = True, level: int = 1) -> SealResult:
    """把一次试衣间拒收封成「replay 案例 + coach 训练题」。

    只封拒收：written=True(已写回) 或 gate=="" (apply=False 只看效果) 都不是要返工的料，跳过。
    persist=True 才落盘(案例进 state/replay、训练回合进 state/coach)；False 只搭对象供预览。
    封存是观测者：任何落盘异常都被吞掉，绝不让「给拒收立档」反过来弄死这只生命。
    """
    if result.written or not result.gate:
        return SealResult(False, "候选已过闸/已写回，没有要返工的拒收", result.gate or "",
                          result.target, "", "", False)

    topic = _topic(result)
    case = _build_case(result, candidate, persist=persist)

    persisted = False
    if persist:
        case_saved = replay.save_case(case)
        _seal_coach(result)             # coach 落档失败自身已吞，不影响案例已存的事实
        persisted = bool(case_saved)

    return SealResult(
        sealed=True,
        reason=("已封成 replay 案例 + coach 训练题" if persist
                else "已搭出返工单(未落盘，仅预览)"),
        gate=result.gate, target=result.target, topic=topic,
        case_id=case.case_id, persisted=persisted)


def _seal_coach(result: patchfitroom.FitResult):
    """把这次拒收当失败现场喂给 coach，落一道对症训练回合；coach 缺席/出错都不致命。"""
    try:
        import coach
        situation = (f"{_topic(result)}。拒收原因：{result.detail}。"
                     f"这是一次自生补丁被试衣间拦下的失败，需补练到不再产同类候选。")
        return coach.train_on_failure(situation)
    except Exception:
        return None   # coach 是陪练者，缺席或出错都不能反噬封存这一步


def coach_round(result: patchfitroom.FitResult):
    """据一次拒收生成(但不落档)一个 coach 训练回合，供预览/自检；coach 缺席则返回 None。"""
    try:
        import coach
        situation = (f"{_topic(result)}。拒收原因：{result.detail}。"
                     f"这是一次自生补丁被试衣间拦下的失败，需补练到不再产同类候选。")
        return coach.coach(situation)
    except Exception:
        return None


def manifest() -> dict:
    """机读：返工单的结构说明(给 health / 外部消费)。"""
    return {
        "seals": "patchfitroom 拒收(written=False 且卡在某闸)",
        "into": ["replay 案例(命令走 patchfitroom --fit-dry，重跑零副作用)",
                 "coach 失败训练回合"],
        "replay_verdicts": {"reproduced": "仍被同一道闸拒", "fixed": "今天能过闸了"},
        "gates": patchfitroom.GATE_ORDER,
    }


# ── 自检 ─────────────────────────────────────────────────────────────
def _fake_reject(gate: str = "syntax") -> patchfitroom.FitResult:
    """造一个「被某道闸拒收」的 FitResult(纯内存，不碰真文件)。"""
    return patchfitroom.FitResult(
        written=False, gate=gate, detail=f"演示：卡在 {gate} 闸",
        target=str(REPO_ROOT / "contracts.py"),
        gates_run=patchfitroom.GATE_ORDER[:patchfitroom.GATE_ORDER.index(gate) + 1],
        shape={"ok": True, "code": "", "reason": ""})


def selfcheck(quiet: bool = False) -> bool:
    """自检：拒收才封 / 过闸跳过 / 案例命令能零副作用重跑出同样的拒收。

    纯净路径(persist=False)不落盘、不起 git；末了用真 `--fit-dry` 子进程验一次重跑零副作用。
    """
    import subprocess
    failures: list[str] = []

    # 1) 一次拒收(persist=False)：封成返工单，案例命令走 --fit-dry，stdin 即候选
    cand = "def area(w, h)\n    return w * h\n"   # 漏冒号，会被语法闸拒
    rej = _fake_reject("syntax")
    s = seal(rej, cand, persist=False)
    if not s.sealed:
        failures.append(f"拒收应被封成返工单，实得 {s.to_meta()}")
    if s.case_id == "" or s.persisted:
        failures.append(f"persist=False 应有案例号且不落盘，实得 {s.to_meta()}")
    case = _build_case(rej, cand, persist=False)
    if case.stdin != cand:
        failures.append("案例须把候选源码原样存进 stdin，供重跑")
    if "--fit-dry" not in case.command:
        failures.append(f"重跑命令须走 --fit-dry(零副作用)，实得 {case.command}")
    if case.command[-2] != "contracts.py":
        failures.append(f"重跑命令须点名目标的仓库内相对路径，实得 {case.command}")

    # 2) 过了闸的(written=True 或 gate=="")不该封
    passed = patchfitroom.FitResult(True, "", "全闸通过 → 已写回",
                                    str(REPO_ROOT / "contracts.py"), [], None)
    if seal(passed, cand, persist=False).sealed:
        failures.append("已过闸写回的不该被封成返工单")
    dryok = patchfitroom.FitResult(False, "", "全闸通过(apply=False)",
                                   str(REPO_ROOT / "contracts.py"), [], None)
    if seal(dryok, cand, persist=False).sealed:
        failures.append("apply=False 只看效果(gate=='')的不该被封")

    # 3) coach 题确为「对着失败补练」(kind=failure)，能渲染
    rnd = coach_round(rej)
    if rnd is not None:
        if getattr(rnd, "kind", "") != "failure":
            failures.append(f"拒收该开「对着失败补练」的回合，实得 kind={getattr(rnd, 'kind', '?')}")
        try:
            rnd.render()
        except Exception as e:  # noqa: BLE001
            failures.append(f"训练回合渲染不该抛错：{e!r}")

    # 4) 案例命令能真重跑：起一次 --fit-dry 子进程，空白候选必被 shape 闸拒(退出 1)。
    #    dry=apply=False 本就不写文件,空白候选更在 shape 闸短路、连临时副本/子进程都不建,
    #    故零副作用是结构保证;此处只验命令确实可跑且如期判拒(不比对真文件内容——本仓库会被并发自改)。
    try:
        r = subprocess.run(
            [sys.executable, "patchfitroom.py", "--fit-dry", "contracts.py", "--quiet"],
            cwd=str(REPO_ROOT), input="   \n", capture_output=True, text=True, timeout=60)
        if r.returncode != 1:
            failures.append(f"空白候选 --fit-dry 重跑应退出 1(拒收)，实得 {r.returncode}")
    except Exception as e:  # noqa: BLE001
        failures.append(f"--fit-dry 重跑不该抛错：{e!r}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ fitrework selfcheck：拒收才封、过闸跳过，案例命令走 --fit-dry 能零副作用重跑——返工单可信。")
        else:
            print("❌ fitrework selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    print("🪞🧵  试衣间拒收返工单 —— 几种拒收各封一遍(仅预览，不落盘)：\n")
    for gate in ("shape", "syntax", "import", "contract"):
        rej = _fake_reject(gate)
        s = seal(rej, "def area(w, h)\n    return w * h\n", persist=False)
        rnd = coach_round(rej)
        kind = getattr(rnd, "kind", "?") if rnd else "(coach 缺席)"
        print(f"  🔴 卡在 {gate} 闸")
        print(f"      → replay 案例 {s.case_id}（命令走 --fit-dry，重跑零副作用）")
        print(f"      → coach 训练题：{s.topic}（kind={kind}）")
    passed = patchfitroom.FitResult(True, "", "全闸通过 → 已写回", "x.py", [], None)
    print(f"\n  🟢 过闸写回的：{seal(passed, '...', persist=False).reason}（不返工）")
    print()


def _fit_from_stdin(path: str, *, quiet: bool) -> int:
    """从 stdin 读候选，对真仓库内 path 试穿落盘；拒收则自动封成返工单。返回退出码。"""
    target = (REPO_ROOT / path).resolve()
    if not target.is_relative_to(REPO_ROOT):
        if not quiet:
            print(f"⛔ 拒绝：{path} 解析到仓库之外，试衣间只对仓库内文件落盘")
        return 2
    candidate = sys.stdin.read()
    result = patchfitroom.fit(target, candidate, repo=REPO_ROOT)
    if result.written:
        if not quiet:
            print(f"🟢 {target.name}：全闸通过 → 已原子写回（{' → '.join(result.gates_run)}）")
        return 0
    s = seal(result, candidate, persist=True)
    if not quiet:
        print(f"🔴 {target.name}：卡在 {result.gate} 闸 —— {result.detail}")
        if s.sealed:
            mark = "已封存" if s.persisted else "已搭出(落盘未成)"
            print(f"   🧵 {mark}返工单：replay 案例 {s.case_id} + 一道 coach 训练题")
            print(f"      复跑验证：python replay.py --replay {s.case_id[-15:]}")
    return 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 试衣间拒收返工单 🪞🧵")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：拒收才封 / 过闸跳过 / 案例命令能零副作用重跑(供 evidence 复跑)")
    ap.add_argument("--json", action="store_true", help="机读：返工单结构说明")
    ap.add_argument("--fit", metavar="PATH",
                    help="从 stdin 读候选源码，对 PATH 试穿；拒收则自动封成返工单")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)
    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return
    if args.fit:
        sys.exit(_fit_from_stdin(args.fit, quiet=args.quiet))
    if not args.quiet:
        _demo()


if __name__ == "__main__":
    main()
