#!/usr/bin/env python3
"""AST 级自生手改写器 🌳🖐️ —— 按函数节点最小替换，试衣间只过语法/import/回放三闸，过了才落真身。

为什么要有它：到今天为止，brain 亲手改一处真文件的链条是这样接起来的——`astlocator.py`
按**结构**(哪个函数/方法/CLI入口)找准下刀处、只换那一段(最小替换 + 补丁契约验「下刀浅」)，
`patchfitroom.py` 把一份**已经备好的整文件候选**穿进五闸再原子写回。可这两头中间缺一节：
谁来把「定位到 net_price 这个函数 → 只把它那一段换成新写法 → 再把这份只动了一个节点的整文件
拿去过闸落盘」这条**结构化改一处**的路一气呵成？过去要么手工把 astlocator 的产物再喂给
patchfitroom(两步、易错位)，要么干脆退回「整文件替换」——而文本级整文件落爪最容易漂：
缩进错一格、段外多删一行，补丁契约也未必拦得住语义漂移。

文本落爪易漂，**结构化动手能更稳地断奶**：先用 AST 把源码解析成节点树，只在「那一个函数节点」
的行区间内替换，段外每个字节按 astlocator 的最小替换原样不动；产出的整文件再进试衣间过闸。
这样「改哪儿」由结构定死、「改得对不对」由闸把关，两边都不靠手感。

本层就是那台改写器：给它**真仓库内的文件 + 目标节点限定名 + 一个只改那一段的 transform**，它

  1) 🌳 **结构最小替换**：调 `astlocator.rewrite` 按节点定位、splice 回那一段、过补丁契约——
     定不到位 / transform 抛错 / 越界大改，都在进试衣间之前就拦下(这是「下刀准 + 下刀浅」)。
  2) 🪞 **试衣间三闸**(候选整文件绝不直接写真身，先穿到隔离临时副本上，最便宜的先跑)：
       · 🔤 **语法闸(syntax)**：`py_compile` 候选——编译不过，拒。
       · 📦 **import 闸**：在「候选覆盖、其余取真仓库」的隔离 sys.path 里 import 这个模块，
         看它加载即崩没有(节点改完，模块还起得来吗)。
       · 🔁 **回放闸(replay)**：跑一段调用方给的**回放探针**——拿改写后的模块复演一遍预期行为，
         退出码 0 才算「这一节点真改对了」。没给回放探针就不写真身：**断奶要稳，没有回放确认
         的结构改写，宁可不落地**。

三闸全过且 `apply=True`，才把候选**原子写回**真文件(同目录临时文件 + `os.replace`，保留权限位)；
任何一步没过，**真文件分毫不动**，报告卡在哪、为什么。隔离做法与 `patchfitroom` 同源——直接复用
它的 staged 子进程与原子写回，免得两套机器各长各的 bug。

与全家一致：零第三方依赖，纯标准库；rewrite_fit 永不抛错，任何意外形态都收敛成「拒收、真身不动」——
一台会动手的改写器，第一要务仍是先学会不伤到自己。

用法:
    python astrewriter.py              # 演示：一个过三闸写回 + 几个各卡在不同闸的节点改写
    python astrewriter.py --selfcheck  # 自检：过闸写回 / 各闸拒收 / 拒收后真文件分毫不动(供 evidence 复跑)
    python astrewriter.py --json       # 机读：三闸闸序 + 阈值
    加 --quiet 静默，仅以退出码表态。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import astlocator  # noqa: E402 —— 结构最小替换：按节点定位 + splice 那一段 + 过补丁契约
import patchfitroom  # noqa: E402 —— 复用它的 staged 隔离子进程与原子写回，免得两套机器各长各的 bug

# ── 试衣间的三道闸：最便宜/最根本的先跑，前一道过了才跑下一道 ──────────────────
GATE_SYNTAX = "syntax"      # 语法：py_compile 候选整文件
GATE_IMPORT = "import"      # 加载：候选覆盖下 import 这个模块，看它起跑即崩没有
GATE_REPLAY = "replay"      # 回放：跑回放探针，拿改写后的模块复演预期行为，退出码 0 才算改对
GATE_ORDER = [GATE_SYNTAX, GATE_IMPORT, GATE_REPLAY]

# 进试衣间之前、astlocator 那一段「下刀准 + 下刀浅」失手时点名的位置(非试衣间闸)
STAGE_LOCATE = "locate"        # 定不到那个函数/方法/CLI 节点
STAGE_TRANSFORM = "transform"  # transform 抛错 / 产出不是字符串
STAGE_BOUNDED = "bounded"      # 改完仍被补丁契约判越界(或 no-op)
STAGE_SIGNATURE = "signature"  # brain-only 小修破坏函数签名，伤到调用接口


@dataclasses.dataclass(frozen=True)
class RewriteFitResult:
    """一次「结构最小替换 + 三闸试穿」的结论：写回了没、被哪步/哪道闸决定、为什么。"""
    written: bool            # 候选是否过了三闸并原子写回真文件
    gate: str                # 决定结果的位置：全过并写回→""；否则点名 locate/transform/bounded/syntax/import/replay
    detail: str              # 一句人话：为什么这么判 / 卡在哪
    target: str              # 改写的目标文件路径
    qualname: str            # 目标节点限定名(函数名 / 类名.方法名 / "__main__")
    locus: dict | None       # astlocator 定到的节点 meta(定不到 → None)
    gates_run: list[str]     # 实际依次跑过的试衣间闸(短路后不再往下；未进试衣间则为空)
    verdict: dict | None     # 补丁契约裁决 meta，便于账本翻查(未走到则 None)

    def to_meta(self) -> dict:
        return {"written": self.written, "gate": self.gate, "detail": self.detail,
                "target": self.target, "qualname": self.qualname, "locus": self.locus,
                "gates_run": self.gates_run, "verdict": self.verdict}


def rewrite_fit(target, qualname, transform, *, replay=None,
                repo=REPO_ROOT, apply: bool = True) -> RewriteFitResult:
    """按节点最小替换 target 里的 qualname 那一段，再过试衣间三闸；全过且 apply 才原子写回。

    target  : 真仓库内要被改的文件路径(其当前内容当 before)。
    qualname: 目标节点 —— 函数名 / 「类名.方法名」 / "__main__"(CLI 守卫块)，交给 astlocator 定位。
    transform: 只改 target 那一段，transform(old_segment: str) -> str。
    replay  : 回放探针源码(一段会 `import {模块名}` 并以退出码表态的 Python)。**不给则不写真身**——
              没有回放确认的结构改写，断奶期宁可不落地(返回 gate="replay")。
    apply   : False = 只试穿、过闸也不写回(看效果，不换上)。
    返回 RewriteFitResult：written + 卡在哪 + 现场。永不抛错——意外形态收敛成「拒收、真身不动」。
    """
    target = pathlib.Path(target)
    repo = pathlib.Path(repo)
    gates_run: list[str] = []
    try:
        before = target.read_text(encoding="utf-8") if target.exists() else ""

        # ── 下刀：结构定位 + 最小替换 + 补丁契约(「下刀准 + 下刀浅」，在进试衣间之前拦) ──
        rr = astlocator.rewrite(before, qualname, transform)
        locus_meta = rr.locus.to_meta() if rr.locus else None
        verdict_meta = rr.verdict.to_meta() if rr.verdict is not None else None
        if not rr.ok:
            if rr.locus is None:
                stage = STAGE_LOCATE
            elif rr.verdict is not None:        # 定到了位、splice 了，但契约判越界/no-op
                stage = STAGE_BOUNDED
            else:                               # transform 抛错 / 产出非字符串
                stage = STAGE_TRANSFORM
            return RewriteFitResult(False, stage, rr.reason, str(target), qualname,
                                    locus_meta, gates_run, verdict_meta)
        candidate = rr.source

        sig_verdict = astlocator.patchcontract.validate_signatures_unchanged(before, candidate)
        if not sig_verdict.ok:
            verdict_meta = sig_verdict.to_meta()
            return RewriteFitResult(False, STAGE_SIGNATURE, sig_verdict.reason, str(target), qualname,
                                    locus_meta, gates_run, verdict_meta)

        # ── 把候选以 {模块名}.py 写进只含它一个文件的隔离覆盖目录，三闸都在隔离子进程里跑 ──
        modname = target.stem
        with tempfile.TemporaryDirectory(prefix="astrewriter-") as d:
            staging = pathlib.Path(d)
            staged = staging / f"{modname}.py"
            staged.write_text(candidate, encoding="utf-8")

            def _fail(gate: str, detail: str) -> RewriteFitResult:
                return RewriteFitResult(False, gate, detail, str(target), qualname,
                                        locus_meta, gates_run, verdict_meta)

            # ── 闸 1) 语法：候选整文件编译不过即拒 ──
            gates_run.append(GATE_SYNTAX)
            r = patchfitroom._staged_run(
                f"import py_compile\npy_compile.compile({str(staged)!r}, doraise=True)",
                staging=staging, repo=repo)
            if r.returncode != 0:
                return _fail(GATE_SYNTAX, patchfitroom._tail(r) or "编译失败")

            # ── 闸 2) import：候选覆盖下加载本模块，看它起跑即崩没有 ──
            gates_run.append(GATE_IMPORT)
            r = patchfitroom._staged_run(
                f"import importlib\nimportlib.import_module({modname!r})",
                staging=staging, repo=repo)
            if r.returncode != 0:
                return _fail(GATE_IMPORT, patchfitroom._tail(r) or "加载即崩")

            # ── 闸 3) 回放：拿改写后的模块复演预期行为，退出码 0 才算这一节点真改对了 ──
            gates_run.append(GATE_REPLAY)
            if replay is None:
                return _fail(GATE_REPLAY,
                             "没给回放探针 —— 没有回放确认的结构改写，断奶期宁可不落地(真身不动)")
            r = patchfitroom._staged_run(replay, staging=staging, repo=repo)
            if r.returncode != 0:
                return _fail(GATE_REPLAY, patchfitroom._tail(r) or "回放未复演出预期行为")

            # ── 三闸全过 ──
            if not apply:
                return RewriteFitResult(False, "", "三闸通过(apply=False，看个效果未写回)",
                                        str(target), qualname, locus_meta, gates_run, verdict_meta)
            patchfitroom._atomic_write(target, candidate)
            return RewriteFitResult(True, "",
                                    f"三闸通过 → 已在「{qualname}」节点最小替换并原子写回真文件",
                                    str(target), qualname, locus_meta, gates_run, verdict_meta)
    except Exception as e:  # noqa: BLE001 —— 改写器绝不能成为新伤口：意外即收敛为拒收、不写回
        return RewriteFitResult(False, gates_run[-1] if gates_run else STAGE_LOCATE,
                                f"改写时出意外，保守拒收、真文件分毫不动：{type(e).__name__}: {e}",
                                str(target), qualname, None, gates_run, None)


def manifest() -> dict:
    """机读：三闸闸序 + 阈值(给 health / 外部消费)。"""
    return {
        "gates": GATE_ORDER,
        "pre_gate_stages": [STAGE_LOCATE, STAGE_TRANSFORM, STAGE_BOUNDED, STAGE_SIGNATURE],
        "gate_timeout": patchfitroom.GATE_TIMEOUT,
        "max_changed_lines": astlocator.patchcontract.DEFAULT_MAX_CHANGED_LINES,
        "max_line_delta": astlocator.patchcontract.DEFAULT_MAX_LINE_DELTA,
        "replay_required_to_write": True,
    }


# ── 自检用的最小仓库：一个带「逻辑伤」的函数 + 一处 import 期会触发的调用 ───────────
# bump 本该 +1 却写成 +2(能编译、能加载、报错无行号的逻辑伤)；READY = bump(0) 让模块在
# import 期就会调一次 bump——于是「改坏了函数体」既能被 import 闸(顶层调用崩)、也能被回放闸
# (行为不对)分别照出来，正好把三闸各自的职责钉死。
_CALC_SRC = (
    "def bump(n):\n"
    "    return n + 2\n"        # 伤：该 +1，写成了 +2
    "\n"
    "READY = bump(0)\n"          # import 期就调一次：节点改坏到「加载即崩」时这里先炸
    'MARK = "calc"\n'
)

# 回放探针：拿改写后的 calc 复演「bump(1) 应得 2」——只有真把 +2 修回 +1 才会退出 0。
_REPLAY = "import sys, calc\nsys.exit(0 if calc.bump(1) == 2 else 1)\n"


def _mini_repo(d: pathlib.Path) -> pathlib.Path:
    """在 d 里搭一个最小仓库(calc.py)，返回 calc.py 路径。"""
    target = d / "calc.py"
    target.write_text(_CALC_SRC, encoding="utf-8")
    return target


def selfcheck(quiet: bool = False) -> bool:
    """自检：过三闸写回 / 各闸拒收 / 拒收后真文件分毫不动。供 evidence 复跑。

    全程在隔离临时仓库里跑，绝不碰真仓库；三闸子进程确定性、无外部副作用。
    """
    failures: list[str] = []

    def in_repo(fn):
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            fn(dp, _mini_repo(dp))

    # 把 +2 改回 +1 的「只改那一段」transform(段外字节不动)
    fix = lambda seg: seg.replace("n + 2", "n + 1")  # noqa: E731

    # 1) 干净的结构改写：定位 bump 节点 → 只换 +2 为 +1 → 三闸全过 → 原子写回，且段外原样不动
    def s_pass(dp, target):
        r = rewrite_fit(target, "bump", fix, replay=_REPLAY, repo=dp)
        if not (r.written and r.gate == ""):
            failures.append(f"干净结构改写该过三闸写回，实得 {r.to_meta()}")
            return
        after = target.read_text(encoding="utf-8")
        if "return n + 1" not in after:
            failures.append("过闸后 bump 节点应已换成 +1，实际没换上")
        if 'MARK = "calc"' not in after or "READY = bump(0)" not in after:
            failures.append("最小替换不成立：定位节点段外的代码也被动了")
        if r.gates_run != GATE_ORDER:
            failures.append(f"过闸该依次跑满三闸，实得 {r.gates_run}")
    in_repo(s_pass)

    # 2) locate：目标节点不存在 → 在进试衣间之前就拦(gates_run 为空)，真文件分毫不动
    def s_locate(dp, target):
        before = target.read_text(encoding="utf-8")
        r = rewrite_fit(target, "no_such_fn", fix, replay=_REPLAY, repo=dp)
        if r.written or r.gate != STAGE_LOCATE or r.gates_run:
            failures.append(f"定不到的节点该卡在 locate(不进试衣间)，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("locate 拒收后真文件竟被改动")
    in_repo(s_locate)

    # 3) bounded：transform 把整段重写成大改 → 补丁契约判越界，进不了试衣间，真文件不动
    def s_bounded(dp, target):
        before = target.read_text(encoding="utf-8")
        overhaul = lambda seg: "def bump(n):\n" + "\n".join(f"    x{i} = {i}" for i in range(40)) + "\n    return n + 1\n"  # noqa: E731
        r = rewrite_fit(target, "bump", overhaul, replay=_REPLAY, repo=dp)
        if r.written or r.gate != STAGE_BOUNDED:
            failures.append(f"重写式大改该卡在 bounded(契约越界)，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("bounded 拒收后真文件竟被改动")
    in_repo(s_bounded)

    # 4) syntax：transform 产出语法残段(能过补丁契约的行数，但编译不过) → 卡在 syntax 闸
    def s_syntax(dp, target):
        before = target.read_text(encoding="utf-8")
        r = rewrite_fit(target, "bump", lambda seg: seg.replace("n + 2", "n +"), replay=_REPLAY, repo=dp)
        if r.written or r.gate != GATE_SYNTAX:
            failures.append(f"语法残段该卡在 syntax 闸，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("syntax 拒收后真文件竟被改动")
    in_repo(s_syntax)

    # 5) import：节点改成引用未定义名，能编译，但 import 期 READY = bump(0) 触发 NameError → 卡在 import 闸
    def s_import(dp, target):
        before = target.read_text(encoding="utf-8")
        r = rewrite_fit(target, "bump", lambda seg: seg.replace("n + 2", "nope"), replay=_REPLAY, repo=dp)
        if r.written or r.gate != GATE_IMPORT:
            failures.append(f"加载即崩(顶层调用炸)该卡在 import 闸，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("import 拒收后真文件竟被改动")
    in_repo(s_import)

    # 6) replay：能编译、能加载，但行为仍不对(+2 改成 +5) → 回放复演不出 bump(1)==2，卡在 replay 闸
    def s_replay(dp, target):
        before = target.read_text(encoding="utf-8")
        r = rewrite_fit(target, "bump", lambda seg: seg.replace("n + 2", "n + 5"), replay=_REPLAY, repo=dp)
        if r.written or r.gate != GATE_REPLAY:
            failures.append(f"行为仍不对的改写该卡在 replay 闸，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("replay 拒收后真文件竟被改动")
    in_repo(s_replay)

    # 7) 缺回放探针：能过语法/import，但没给回放探针 → 不写真身(断奶要稳)，真文件分毫不动
    def s_noreplay(dp, target):
        before = target.read_text(encoding="utf-8")
        r = rewrite_fit(target, "bump", fix, replay=None, repo=dp)
        if r.written or r.gate != GATE_REPLAY:
            failures.append(f"缺回放探针该卡在 replay 闸(不写真身)，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("缺回放探针时真文件竟被改动")
    in_repo(s_noreplay)

    # 8) apply=False：三闸全过也只看效果不写回，真文件分毫不动
    def s_dryfit(dp, target):
        before = target.read_text(encoding="utf-8")
        r = rewrite_fit(target, "bump", fix, replay=_REPLAY, repo=dp, apply=False)
        if r.written or r.gate != "":
            failures.append(f"apply=False 该过三闸但不写回，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("apply=False 竟把候选写回了真文件")
    in_repo(s_dryfit)

    # 8.5) signature：补丁虽能通过行为回放，但改了函数参数名 → 进试衣间前拒收，真文件不动
    def s_signature(dp, target):
        before = target.read_text(encoding="utf-8")
        break_sig = lambda seg: seg.replace("def bump(n):", "def bump(x):").replace("n + 2", "x + 1")  # noqa: E731
        r = rewrite_fit(target, "bump", break_sig, replay=_REPLAY, repo=dp)
        if r.written or r.gate != STAGE_SIGNATURE or r.gates_run:
            failures.append(f"破坏函数签名的小修该卡在 signature(不进试衣间)，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("signature 拒收后真文件竟被改动")
    in_repo(s_signature)

    # 9) no-op 探针：transform 没真改东西 → 补丁契约判 no-op，卡在 bounded、真文件不动
    def s_noop(dp, target):
        before = target.read_text(encoding="utf-8")
        r = rewrite_fit(target, "bump", lambda seg: seg, replay=_REPLAY, repo=dp)
        if r.written or r.gate != STAGE_BOUNDED:
            failures.append(f"原样改写该被契约判 no-op(卡在 bounded)，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("no-op 拒收后真文件竟被改动")
    in_repo(s_noop)

    ok = not failures
    if not quiet:
        if ok:
            print("✅ astrewriter selfcheck：按节点最小替换后过语法/import/回放三闸，"
                  "三闸各能拒收，缺回放不落地，且每次拒收后真文件分毫不动——结构化改写器可信。")
        else:
            print("❌ astrewriter selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    print("🌳🖐️  AST 级自生手改写器 —— 按 bump 节点最小替换，候选过语法/import/回放三闸：\n")
    print(f"   三闸闸序：{' → '.join(GATE_ORDER)}"
          f"（进闸前先过 astlocator 的「定位准 + 改动浅」；阈值：改动 ≤ "
          f"{astlocator.patchcontract.DEFAULT_MAX_CHANGED_LINES} 行）\n")
    samples = [
        ("✅ 干净结构改写：+2 修回 +1", lambda s: s.replace("n + 2", "n + 1"), _REPLAY, True),
        ("🎯 locate：目标节点不存在", lambda s: s, _REPLAY, True),
        ("🔤 syntax：改出语法残段", lambda s: s.replace("n + 2", "n +"), _REPLAY, True),
        ("📦 import：引用未定义名(顶层调用炸)", lambda s: s.replace("n + 2", "nope"), _REPLAY, True),
        ("🔁 replay：能编译能加载但行为仍不对(+5)", lambda s: s.replace("n + 2", "n + 5"), _REPLAY, True),
        ("🚧 缺回放探针：不写真身", lambda s: s.replace("n + 2", "n + 1"), None, True),
    ]
    with tempfile.TemporaryDirectory() as d:
        dp = pathlib.Path(d)
        for label, tf, rp, ap in samples:
            target = _mini_repo(dp)   # 每个候选都在全新的最小仓库上试穿
            qn = "no_such_fn" if "locate" in label else "bump"
            r = rewrite_fit(target, qn, tf, replay=rp, repo=dp, apply=ap)
            if r.written:
                mark = "🟢 过三闸写回"
            elif r.gate:
                mark = f"🔴 卡在 {r.gate}"
            else:
                mark = "🟡 未写回"
            ran = " → ".join(r.gates_run) if r.gates_run else "(未进试衣间)"
            print(f"  {label}\n      {mark}（试衣间跑过：{ran}）\n      {r.detail}")
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab AST 级自生手改写器 🌳🖐️")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：过三闸写回 / 各闸拒收 / 拒收后真文件分毫不动(供 evidence 复跑)")
    ap.add_argument("--json", action="store_true", help="机读：三闸闸序 + 阈值")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if not args.quiet:
        _demo()


if __name__ == "__main__":
    main()
