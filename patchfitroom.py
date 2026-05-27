#!/usr/bin/env python3
"""brain 补丁试衣间 🪞🖐️ —— 补丁先穿在临时副本上过闸，过了才原子写回真身。

为什么要有它：`weaning_trial.py` 让 brain 在**纯内存**里产补丁、自测、回滚——它跑的是
一段段孤立源码，从不碰真仓库的文件。`patchcontract.py` 只验补丁的**形状**(畸形/越界)。
`astlocator`/`readpack` 帮 brain 找准下刀处、读懂上下文。可链条的最后一步——把一个
**针对真文件**的候选补丁安全落盘——一直缺一道闸：过去要么像 `hands.py` 那样先写真文件、
靠 git 提交后再回滚(改坏了仓库已经脏了一拍)，要么干脆没有谁来兜底。一只会动手的爪子，
**第一要务是先学会不伤到自己**：落笔之前，得先有个地方让补丁「试穿」，确认不割伤身体，
才准换上。

本层就是那间试衣间：候选补丁**绝不直接写真文件**，而是先穿到一份隔离的临时副本上，
依次过三道闸——

  1) 🧱 **形状闸(shape)**：先过 `patchcontract` 的畸形/越界拒收闸(纯内存、瞬时)。
     None/空白/非串/重写式大改，当场拒，连临时副本都不必建。
  2) 🔤 **语法闸(syntax)**：把候选 `py_compile` 一遍——编译不过，拒。
  3) 👋 **触觉闸(touch)**：过 `touch.py` 比对落笔前后的副作用足迹(纯内存、`ast.parse` 绝不执行)——
     候选若在原本只算数的地方**新增**了 IO/环境变量/网络/执行命令，当场拒。只拒新增、不算原有的账。
  4) 📦 **import 闸**：在「候选覆盖、其余模块仍取真仓库」的隔离 sys.path 里 import 这个模块，
     看它**加载即崩**没有(就是 `hands._self_test`/`weaning` 那句「还能不能启动」)。
  5) 📜 **契约闸(contract)**：在同一套覆盖下跑 `contracts.py` 的全部验收样例——
     这一爪有没有把本模块的契约、或任何下游模块的契约暗中改塌。

五闸全过，且 `apply=True`，才把候选**原子写回**真文件(同目录临时文件 + `os.replace`，
保留原权限位)；任何一闸没过，**真文件分毫不动**，报告卡在哪道闸、为什么。闸按「最便宜/
最根本的先跑」排序，前一道过了才跑下一道，省得把生命耗在注定要拒的候选上。

隔离怎么做到「候选覆盖、其余取真仓库」：把候选以 `{模块名}.py` 写进一个**只含它一个文件**
的临时覆盖目录，子进程里把这个目录插到 `sys.path` 最前、真仓库紧随其后。于是任何
`import {模块名}` 都解析到候选，它的依赖照旧从真仓库取——真文件在写回之前始终没被碰过。

用法:
    python patchfitroom.py                 # 演示：一个过闸写回 + 几个各卡在不同闸的候选
    python patchfitroom.py --selfcheck     # 自检：过闸写回 / 各闸拒收 / 拒收后真文件分毫不动
    python patchfitroom.py --json          # 机读：闸序 + 阈值
    python patchfitroom.py --fit PATH      # 从 stdin 读候选源码，对 PATH(真仓库内)试穿落盘
    python patchfitroom.py --fit-dry PATH  # 同上但只试穿不写回(过闸→0/拒收→1)，供 replay 零副作用重跑
    加 --quiet 静默，仅以退出码表态。

零第三方依赖，纯标准库；fit 永不抛错形态的拒收闸自己绝不能成为新伤口。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import patchcontract  # noqa: E402 —— 形状闸复用补丁契约：畸形/越界先拦在门外
import touch  # noqa: E402 —— 触觉闸复用自生手触觉层：比对落笔前后的副作用足迹，新增危险即拒

GATE_TIMEOUT = 60      # 单道子进程闸的墙钟上限(秒)：试穿不该把生命拖死

# ── 五道闸的名字与次序(最便宜/最根本的先跑，前一道过了才跑下一道) ────────────
GATE_SHAPE = "shape"        # 形状：畸形/越界(纯内存，瞬时)
GATE_SYNTAX = "syntax"      # 语法：py_compile
GATE_TOUCH = "touch"        # 触觉：比对前后副作用足迹，新增 IO/env/网络/执行命令即拒(纯内存)
GATE_IMPORT = "import"      # 加载：import 这个模块，看它起跑即崩没有
GATE_CONTRACT = "contract"  # 契约：跑 contracts.py 全部验收样例
GATE_ORDER = [GATE_SHAPE, GATE_SYNTAX, GATE_TOUCH, GATE_IMPORT, GATE_CONTRACT]


@dataclasses.dataclass(frozen=True)
class FitResult:
    """一次试穿的结论：写回了没、被哪道闸决定、为什么。"""
    written: bool          # 候选是否过了全闸并原子写回真文件
    gate: str              # 决定结果的闸：全过并写回→""；否则点名失败的那道闸
    detail: str            # 一句人话：为什么这么判 / 卡在哪
    target: str            # 试穿的目标文件路径
    gates_run: list[str]   # 实际依次跑过的闸(短路后不再往下)
    shape: dict | None     # 形状闸(patchcontract)的裁决 meta，便于账本翻查

    def to_meta(self) -> dict:
        return {"written": self.written, "gate": self.gate, "detail": self.detail,
                "target": self.target, "gates_run": self.gates_run, "shape": self.shape}


def _tail(proc: subprocess.CompletedProcess) -> str:
    """从子进程输出里取末尾一段当现场原文(stderr 优先)。"""
    return (proc.stderr or proc.stdout or "").strip()[-300:]


def _staged_run(snippet: str, *, staging: pathlib.Path, repo: pathlib.Path,
                timeout: int = GATE_TIMEOUT) -> subprocess.CompletedProcess:
    """在「候选覆盖、其余取真仓库」的隔离 sys.path 里跑一段探针代码。

    staging 插到最前、repo 紧随其后：任何 import 这个模块都命中候选，它的依赖照旧
    从真仓库解析。子进程跑(而非本进程 import)以保证每道闸彼此隔离、不串 import 缓存。
    """
    prelude = (
        "import sys\n"
        f"sys.path.insert(0, {str(staging)!r})\n"
        f"sys.path.insert(1, {str(repo)!r})\n"
    )
    return subprocess.run([sys.executable, "-c", prelude + snippet],
                          cwd=str(repo), capture_output=True, text=True, timeout=timeout)


def _atomic_write(target: pathlib.Path, text: str) -> None:
    """把候选原子写回真文件：同目录临时文件 + fsync + os.replace，并保留原权限位。

    os.replace 在同一文件系统内是原子的——要么旧内容、要么新内容，绝不会落下半截文件。
    """
    target = pathlib.Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode if target.exists() else None
    fd, tmp = tempfile.mkstemp(dir=str(target.parent),
                               prefix=f".{target.stem}.", suffix=".fitting")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)        # 原子换上
        if mode is not None:
            os.chmod(target, mode)     # 换上后再保留原权限位：先 replace 再 chmod，
            #                            万一两步之间被打断,留下的也是内容已对、仅权限待修的真文件
    except BaseException:
        try:
            os.unlink(tmp)             # 没换成就清掉半成品，不留垃圾
        except OSError:
            pass
        raise


def fit(target, candidate, *, repo=REPO_ROOT, check_contracts: bool = True,
        apply: bool = True,
        max_changed_lines: int = patchcontract.DEFAULT_MAX_CHANGED_LINES,
        max_line_delta: int = patchcontract.DEFAULT_MAX_LINE_DELTA) -> FitResult:
    """让候选补丁在临时副本上过五闸；全过且 apply 才原子写回真文件，否则真文件分毫不动。

    target  : 真仓库内要被改的文件路径(其当前内容当 before)。
    candidate: 候选的**完整新源码**(像 weaning 的招式吐出的整段源码)。
    apply   : False = 只试穿、过闸也不写回(试衣间看个效果，不换上)。
    返回 FitResult：written + 卡在哪道闸 + 现场。永不抛错——意外形态收敛成「拒收」。
    """
    target = pathlib.Path(target)
    repo = pathlib.Path(repo)
    gates_run: list[str] = []
    try:
        before = target.read_text(encoding="utf-8") if target.exists() else ""

        # ── 闸 1) 形状：畸形/越界先拦在门外(纯内存、瞬时，连临时副本都不必建) ──
        gates_run.append(GATE_SHAPE)
        verdict = patchcontract.validate(before, candidate,
                                         max_changed_lines=max_changed_lines,
                                         max_line_delta=max_line_delta)
        if not verdict.ok:
            return FitResult(False, GATE_SHAPE, verdict.reason,
                             str(target), gates_run, verdict.to_meta())

        # ── 把候选以 {模块名}.py 写进只含它一个文件的隔离覆盖目录 ──
        modname = target.stem
        with tempfile.TemporaryDirectory(prefix="fitroom-") as d:
            staging = pathlib.Path(d)
            staged = staging / f"{modname}.py"
            staged.write_text(candidate, encoding="utf-8")

            # ── 闸 2) 语法：编译不过即拒 ──
            gates_run.append(GATE_SYNTAX)
            r = _staged_run(
                f"import py_compile\npy_compile.compile({str(staged)!r}, doraise=True)",
                staging=staging, repo=repo)
            if r.returncode != 0:
                return FitResult(False, GATE_SYNTAX, _tail(r) or "编译失败",
                                 str(target), gates_run, verdict.to_meta())

            # ── 闸 3) 触觉：比对落笔前后副作用足迹，候选新增 IO/env/网络/执行命令即拒 ──
            # 纯内存、本进程 ast.parse(绝不执行候选)，便宜得很；放在 import/契约之前，
            # 让「能编译、能加载、契约也守约，却偷长出新副作用」的隐蔽伤先被摸出来。
            gates_run.append(GATE_TOUCH)
            tv = touch.feel(before, candidate)
            if not tv.ok:
                return FitResult(False, GATE_TOUCH, tv.detail,
                                 str(target), gates_run, verdict.to_meta())

            # ── 闸 4) import：候选覆盖下加载本模块，看它起跑即崩没有 ──
            gates_run.append(GATE_IMPORT)
            r = _staged_run(
                f"import importlib\nimportlib.import_module({modname!r})",
                staging=staging, repo=repo)
            if r.returncode != 0:
                return FitResult(False, GATE_IMPORT, _tail(r) or "加载即崩",
                                 str(target), gates_run, verdict.to_meta())

            # ── 闸 5) 契约：同一覆盖下跑全部契约验收样例，看有没有暗中改塌某条契约 ──
            if check_contracts and (repo / "contracts.py").exists():
                gates_run.append(GATE_CONTRACT)
                snippet = (
                    "import contracts, sys\n"
                    "vs = contracts.verify()\n"
                    "bad = [v for v in vs if not v.ok]\n"
                    "for b in bad:\n"
                    "    print(b.module, '违约:', b.detail)\n"
                    "sys.exit(1 if bad else 0)\n"
                )
                r = _staged_run(snippet, staging=staging, repo=repo)
                if r.returncode != 0:
                    return FitResult(False, GATE_CONTRACT, _tail(r) or "契约违约",
                                     str(target), gates_run, verdict.to_meta())

            # ── 全闸通过 ──
            if not apply:
                return FitResult(False, "", "全闸通过(apply=False，看个效果未写回)",
                                 str(target), gates_run, verdict.to_meta())
            _atomic_write(target, candidate)
            return FitResult(True, "", "全闸通过 → 已原子写回真文件",
                             str(target), gates_run, verdict.to_meta())
    except Exception as e:  # noqa: BLE001 —— 试衣间自己绝不能成为新伤口：意外即收敛为拒收、不写回
        return FitResult(False, gates_run[-1] if gates_run else GATE_SHAPE,
                         f"试穿时出意外，保守拒收、真文件分毫不动：{type(e).__name__}: {e}",
                         str(target), gates_run, None)


def manifest() -> dict:
    """机读：闸序 + 阈值(给 health / 外部消费)。"""
    return {
        "gates": GATE_ORDER,
        "gate_timeout": GATE_TIMEOUT,
        "max_changed_lines": patchcontract.DEFAULT_MAX_CHANGED_LINES,
        "max_line_delta": patchcontract.DEFAULT_MAX_LINE_DELTA,
    }


# ── 自检用的最小仓库：一个被验的模块 + 一条管着它的契约 ───────────────────────
_WIDGET_SRC = "def area(w, h):\n    return w * h\n"

# 一个 contracts.py 的最小同构件：verify()/summarize() 与真层接口一致，只验 widget.area
_CONTRACTS_SRC = '''\
import widget


class V:
    def __init__(self, module, ok, detail):
        self.module = module
        self.ok = ok
        self.detail = detail


def verify():
    try:
        assert widget.area(2, 3) == 6, "area(2,3) 必须为 6"
        return [V("widget", True, "")]
    except Exception as e:  # noqa: BLE001
        return [V("widget", False, str(e))]


def summarize(vs):
    bad = [v for v in vs if not v.ok]
    return (not bad, len(bad))
'''


def _mini_repo(d: pathlib.Path) -> pathlib.Path:
    """在 d 里搭一个最小仓库(widget.py + contracts.py)，返回 widget.py 路径。"""
    (d / "contracts.py").write_text(_CONTRACTS_SRC, encoding="utf-8")
    target = d / "widget.py"
    target.write_text(_WIDGET_SRC, encoding="utf-8")
    return target


def selfcheck(quiet: bool = False) -> bool:
    """自检：过闸写回 / 各闸拒收 / 拒收后真文件分毫不动。供 evidence 复跑。

    全程在隔离临时仓库里跑，绝不碰真仓库；确定性、无外部副作用。
    """
    failures: list[str] = []

    def in_repo(fn):
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            fn(dp, _mini_repo(dp))

    # 1) 干净的「修一处」补丁：五闸全过 → 原子写回，真文件确实变了
    def s_pass(dp, target):
        cand = "def area(w, h):\n    return w * h  # 量过了\n"
        r = fit(target, cand, repo=dp)
        if not (r.written and r.gate == ""):
            failures.append(f"干净补丁该过闸写回，实得 {r.to_meta()}")
        elif target.read_text(encoding="utf-8") != cand:
            failures.append("过闸后真文件内容应已换成候选，实际没换上")
    in_repo(s_pass)

    # 2) 形状闸：畸形(空白)候选当场拒，连临时副本都不建，真文件分毫不动
    def s_shape(dp, target):
        before = target.read_text(encoding="utf-8")
        r = fit(target, "   \n", repo=dp)
        if r.written or r.gate != GATE_SHAPE:
            failures.append(f"空白候选该卡在 shape 闸，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("shape 拒收后真文件竟被改动")
    in_repo(s_shape)

    # 3) 语法闸：漏冒号 → 编译不过，真文件分毫不动
    def s_syntax(dp, target):
        before = target.read_text(encoding="utf-8")
        r = fit(target, "def area(w, h)\n    return w * h\n", repo=dp)
        if r.written or r.gate != GATE_SYNTAX:
            failures.append(f"漏冒号候选该卡在 syntax 闸，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("syntax 拒收后真文件竟被改动")
    in_repo(s_syntax)

    # 4) 触觉闸：能编译，但在原本只算数的函数里偷起 os.system → 新增执行命令，拒，真文件不动
    def s_touch(dp, target):
        before = target.read_text(encoding="utf-8")
        cand = "import os\ndef area(w, h):\n    os.system('echo hi')\n    return w * h\n"
        r = fit(target, cand, repo=dp)
        if r.written or r.gate != GATE_TOUCH:
            failures.append(f"偷起 os.system 的候选该卡在 touch 闸，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("touch 拒收后真文件竟被改动")
    in_repo(s_touch)

    # 5) import 闸：能编译但加载即崩(顶层 raise) → 拒，真文件分毫不动
    def s_import(dp, target):
        before = target.read_text(encoding="utf-8")
        cand = 'def area(w, h):\n    return w * h\nraise RuntimeError("加载即崩")\n'
        r = fit(target, cand, repo=dp)
        if r.written or r.gate != GATE_IMPORT:
            failures.append(f"加载即崩候选该卡在 import 闸，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("import 拒收后真文件竟被改动")
    in_repo(s_import)

    # 6) 契约闸：能编译、能加载，但把语义改塌(area 返回 w+h) → 契约验收不过，拒，真文件不动
    def s_contract(dp, target):
        before = target.read_text(encoding="utf-8")
        r = fit(target, "def area(w, h):\n    return w + h\n", repo=dp)
        if r.written or r.gate != GATE_CONTRACT:
            failures.append(f"改塌语义的候选该卡在 contract 闸，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("contract 拒收后真文件竟被改动")
    in_repo(s_contract)

    # 7) apply=False：五闸全过也只看效果不写回，真文件分毫不动
    def s_dryfit(dp, target):
        before = target.read_text(encoding="utf-8")
        r = fit(target, "def area(w, h):\n    return w * h  # 试穿\n",
                repo=dp, apply=False)
        if r.written or r.gate != "":
            failures.append(f"apply=False 该过闸但不写回，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != before:
            failures.append("apply=False 竟把候选写回了真文件")
    in_repo(s_dryfit)

    ok = not failures
    if not quiet:
        if ok:
            print("✅ patchfitroom selfcheck：过闸写回成立，五道闸各能拒收，"
                  "且每次拒收后真文件分毫不动——试衣间可信。")
        else:
            print("❌ patchfitroom selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    print("🪞🖐️  brain 补丁试衣间 —— 候选先穿临时副本过五闸，过了才原子写回：\n")
    print(f"   闸序：{' → '.join(GATE_ORDER)}"
          f"（阈值：改动 ≤ {patchcontract.DEFAULT_MAX_CHANGED_LINES} 行、"
          f"行数增减 ≤ {patchcontract.DEFAULT_MAX_LINE_DELTA}）\n")
    samples = [
        ("✅ 干净修一处(加行内注释)", "def area(w, h):\n    return w * h  # 量过了\n"),
        ("🧱 形状：改成空白", "   \n"),
        ("🔤 语法：漏了冒号", "def area(w, h)\n    return w * h\n"),
        ("👋 触觉：偷起 os.system(新增执行命令)",
         "import os\ndef area(w, h):\n    os.system('echo hi')\n    return w * h\n"),
        ("📦 import：加载即崩", 'def area(w, h):\n    return w * h\nraise RuntimeError("崩")\n'),
        ("📜 契约：把 * 改成 +(语义塌了)", "def area(w, h):\n    return w + h\n"),
    ]
    with tempfile.TemporaryDirectory() as d:
        dp = pathlib.Path(d)
        for label, cand in samples:
            target = _mini_repo(dp)   # 每个候选都在全新的最小仓库上试穿
            r = fit(target, cand, repo=dp)
            if r.written:
                mark = "🟢 过闸写回"
            else:
                mark = f"🔴 卡在 {r.gate} 闸" if r.gate else "🟡 未写回"
            print(f"  {label}\n      {mark}（跑过：{' → '.join(r.gates_run)}）\n      {r.detail}")
    print()


def _fit_from_stdin(path: str, *, quiet: bool, dry: bool = False) -> int:
    """从 stdin 读候选源码，对真仓库内的 path 试穿。返回退出码。

    dry=False：五闸全过则原子写回，退出码 0 表「已写回」。
    dry=True ：apply=False，只试穿看过不过闸、绝不写真文件；退出码 0 表「五闸全过(本可写回)」、
               1 表「卡在某道闸」。供 replay 把一次拒收当回归用例重跑——零副作用地判收/拒。
    """
    target = (REPO_ROOT / path).resolve()
    if not target.is_relative_to(REPO_ROOT):   # 只许试穿真仓库内的文件，挡掉 ../ 越界写盘
        if not quiet:
            print(f"⛔ 拒绝：{path} 解析到仓库之外（{target}），试衣间只对仓库内文件落盘")
        return 2
    candidate = sys.stdin.read()
    r = fit(target, candidate, repo=REPO_ROOT, apply=not dry)
    passed = r.written or (dry and r.gate == "")   # dry 下过闸表现为 written=False、gate==""
    if not quiet:
        if passed:
            tail = "全闸通过（试穿不写回）" if dry else "全闸通过 → 已原子写回"
            print(f"🟢 {target.name}：{tail}（{' → '.join(r.gates_run)}）")
        else:
            where = f"卡在 {r.gate} 闸" if r.gate else "未写回"
            print(f"🔴 {target.name}：{where} —— {r.detail}")
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab brain 补丁试衣间 🪞🖐️")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：过闸写回 / 各闸拒收 / 拒收后真文件分毫不动(供 evidence 复跑)")
    ap.add_argument("--json", action="store_true", help="机读：闸序 + 阈值")
    ap.add_argument("--fit", metavar="PATH",
                    help="从 stdin 读候选源码，对真仓库内 PATH 试穿落盘")
    ap.add_argument("--fit-dry", metavar="PATH", dest="fit_dry",
                    help="同 --fit 但只试穿不写回(apply=False)：退出码 0=过闸 1=拒收，供 replay 零副作用重跑")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if args.fit:
        sys.exit(_fit_from_stdin(args.fit, quiet=args.quiet))

    if args.fit_dry:
        sys.exit(_fit_from_stdin(args.fit_dry, quiet=args.quiet, dry=True))

    if not args.quiet:
        _demo()


if __name__ == "__main__":
    main()
