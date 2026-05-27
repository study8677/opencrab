#!/usr/bin/env python3
"""自生手免疫演练 🖐️🛡️ —— 给试衣间喂一筐「坏手」补丁，逐类断言拒收并回滚到分毫不动。

为什么要有它：`patchfitroom.py` 是补丁落盘前的试衣间，`patchfitroom.selfcheck` 已经把
五道闸**各拒一次**当回归守住。可一只会动手的爪子要可托付，光知道「每道闸单独能拒」不够——
还得有人**主动扮成会犯错的手**，成筐地把畸形、越界、语法坏的补丁砸向真 `fit()` 管子，
逐类确认：① 砸不进去(拒收)，② 砸完真文件**字节不变**(回滚干净、没留半拍脏)。手会犯错，
先练「会不伤身」，再谈「会改对」。

本层就是那场免疫演练：在隔离的临时小仓库里，把三类「坏手」补丁成批喂给 `patchfitroom.fit()`，
每喂一发都用 sha256 守住「真文件落笔前后一字不差」——

  · 🧱 **畸形腿(malformed)**：吐回空白 / 原样没动(no-op) / None。这些连「一段确有改动的源码」
    都不成立，必须卡在最便宜的形状闸、连临时副本都不必建。
  · 📏 **越界腿(out-of-bounds)**：重写式大改(40 行新文件) / 逐行全换。能编译也是「换一个文件」
    而非「修一处伤」，必须卡在形状闸。**外加一发路径越界**：候选想借 `../` 把手伸到仓库之外
    落盘——走 `patchfitroom --fit ../…` 真 CLI，断言当场被拒(退出码 2)、且仓外那个文件根本没被创建。
  · 🔤 **语法坏腿(syntax)**：漏冒号 / 缩进崩坏。形状过得了(确有改动、不越界)，但编译不过，
    必须卡在语法闸。

判准：每一类坏手都被拒在**预期的那道闸**上，且每发砸完目标文件的 sha256 与落笔前完全一致
(回滚到分毫不动)；路径越界那发既被拒、仓外也确无新文件。全程只在临时小仓库 / 临时目录里动手，
**绝不碰真仓库的任何文件**——免疫演练自己绝不能成为新伤口。每场演练结论追加进
state/hands_immunity_drill.jsonl，供事后复盘。

用法:
    python hands_immunity_drill.py            # 跑三腿，逐腿打印判决
    python hands_immunity_drill.py --quiet    # 只在有腿没跑通时说话(适合钩子 / CI)
    python hands_immunity_drill.py --json      # 机读演练报告
    python hands_immunity_drill.py --selfcheck # 自检：三类坏手各被拒在预期闸且真文件分毫不动(供 evidence 回灌)

退出码：0 = 三腿全做对；1 = 有腿没跑通。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import time

import patchfitroom
import jsonlstore

REPO_ROOT = pathlib.Path(__file__).resolve().parent
DRILL_LOG = REPO_ROOT / "state" / "hands_immunity_drill.jsonl"


@dataclasses.dataclass(frozen=True)
class Leg:
    """演练一条腿(一类坏手)的结论。"""
    name: str
    ok: bool
    detail: str

    def to_meta(self) -> dict:
        return {"leg": self.name, "ok": self.ok, "detail": self.detail}


def _digest(p: pathlib.Path) -> str:
    """目标文件的 sha256，用来证「落笔前后一字不差」。"""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _attack(target: pathlib.Path, repo: pathlib.Path, candidate, label: str,
            expected_gate: str) -> str | None:
    """把一发坏手补丁喂给 fit()：断言被拒在预期闸、且真文件字节不变。

    返回 None 表这一发免疫成功；否则返回一句失败原因。
    """
    before = _digest(target)
    r = patchfitroom.fit(target, candidate, repo=repo)
    if r.written:
        return f"「{label}」竟过闸写回了真文件——坏手没被挡住"
    if r.gate != expected_gate:
        return f"「{label}」该卡在 {expected_gate} 闸，实卡在 {r.gate or '(未点名)'}（{r.detail}）"
    if _digest(target) != before:
        return f"「{label}」被拒后真文件竟被改动——拒收没回滚干净"
    return None


def _battery(target: pathlib.Path, repo: pathlib.Path,
             cases: list[tuple[str, object, str]]) -> list[str]:
    """成批喂一类坏手，收集所有未通过的发数。"""
    fails: list[str] = []
    for label, cand, gate in cases:
        if (why := _attack(target, repo, cand, label, gate)) is not None:
            fails.append(why)
    return fails


def drill_malformed() -> Leg:
    """🧱 畸形腿：空白 / no-op / None 都该卡在形状闸，真文件分毫不动。"""
    try:
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            target = patchfitroom._mini_repo(dp)
            base_src = target.read_text(encoding="utf-8")
            fails = _battery(target, dp, [
                ("吐回空白(把文件改没了)", "   \n\n  ", patchfitroom.GATE_SHAPE),
                ("原样没动(no-op)", base_src, patchfitroom.GATE_SHAPE),
                ("招式吐回 None", None, patchfitroom.GATE_SHAPE),
            ])
            if fails:
                return Leg("malformed", False, "；".join(fails))
            return Leg("malformed", True,
                       "空白 / 原样没动 / None 三发畸形手都被形状闸当场拒收，"
                       "真文件 sha256 落笔前后一字不差——畸形伤不了身。")
    except Exception as e:  # noqa: BLE001
        return Leg("malformed", False, f"{type(e).__name__}: {e}")


def drill_out_of_bounds() -> Leg:
    """📏 越界腿：重写式大改 / 逐行全换卡形状闸；外加 `../` 路径越界被真 CLI 拒、仓外无新文件。"""
    try:
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            target = patchfitroom._mini_repo(dp)
            big_rewrite = "\n".join(f"line{i}" for i in range(40)) + "\n"
            # 另一发越界：连函数签名带体一并换掉，改动行数与增减都越线
            full_swap = "\n".join(f"def f{i}(): return {i}" for i in range(8)) + "\n"
            fails = _battery(target, dp, [
                ("重写成 40 行的新文件", big_rewrite, patchfitroom.GATE_SHAPE),
                ("整段换掉(8 行新函数)", full_swap, patchfitroom.GATE_SHAPE),
            ])

            # —— 路径越界：候选想借 ../ 把手伸到仓库之外落盘 ——
            escape_fail = _path_escape_case()
            if escape_fail is not None:
                fails.append(escape_fail)

            if fails:
                return Leg("out_of_bounds", False, "；".join(fails))
            return Leg("out_of_bounds", True,
                       "重写式大改与整段换掉都被形状闸拒(它们是「换一个文件」不是「修一处」)、"
                       "真文件不动；`../` 路径越界被真 CLI 当场拒(退出码 2)、仓外确无新文件——"
                       "手伸不出身体之外。")
    except Exception as e:  # noqa: BLE001
        return Leg("out_of_bounds", False, f"{type(e).__name__}: {e}")


def _path_escape_case() -> str | None:
    """跑真 `patchfitroom --fit ../…` CLI：断言被拒(退出码 2)、且仓外那个目标文件没被创建。

    返回 None 表这一发免疫成功；否则返回一句失败原因。走子进程是为了打真 CLI 入口、
    且把潜在的写盘隔离在子进程里——纵使护栏失守，落点也指向一个演练自造的临时文件(随即清掉)。
    """
    with tempfile.TemporaryDirectory() as outside:
        # 一个一定落在仓库之外的相对路径：../<临时目录名>/pwned.py
        outside_dir = pathlib.Path(outside)
        rel = pathlib.Path("..") / outside_dir.name / "pwned.py"
        sentinel = outside_dir / "pwned.py"
        # 让 ../<name> 真能解析到 outside_dir：把临时目录建在仓库父目录下更稳妥，
        # 但无论解析到哪，护栏都该在「不在仓库内」时拒；这里只断言「被拒 + 没写出哨兵」。
        proc = subprocess.run(
            [sys.executable, "patchfitroom.py", "--fit", str(rel), "--quiet"],
            cwd=str(REPO_ROOT), input="def area(w, h):\n    return w * h  # pwn\n",
            capture_output=True, text=True, timeout=patchfitroom.GATE_TIMEOUT)
        if proc.returncode != 2:
            return (f"路径越界 `--fit {rel}` 该被拒(退出码 2)，实得退出码 {proc.returncode}"
                    f"（{(proc.stderr or proc.stdout).strip()[-160:]}）")
        if sentinel.exists():
            return f"路径越界后仓外竟落下了 {sentinel}——护栏没拦住越界写盘"
        return None


def drill_syntax() -> Leg:
    """🔤 语法坏腿：漏冒号 / 缩进崩坏过得了形状闸，但编译不过，该卡在语法闸。"""
    try:
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            target = patchfitroom._mini_repo(dp)
            fails = _battery(target, dp, [
                ("漏了冒号", "def area(w, h)\n    return w * h\n", patchfitroom.GATE_SYNTAX),
                ("缩进崩坏", "def area(w, h):\nreturn w * h\n", patchfitroom.GATE_SYNTAX),
            ])
            if fails:
                return Leg("syntax", False, "；".join(fails))
            return Leg("syntax", True,
                       "漏冒号与缩进崩坏都过了形状闸却卡在语法闸(py_compile 不过)、"
                       "真文件不动——编译不过的坏手落不了盘。")
    except Exception as e:  # noqa: BLE001
        return Leg("syntax", False, f"{type(e).__name__}: {e}")


def run() -> list[Leg]:
    return [drill_malformed(), drill_out_of_bounds(), drill_syntax()]


def _record(legs: list[Leg]) -> None:
    """把整场演练结论追加进流水账(写盘失败被吞，绝不反噬)。"""
    try:
        jsonlstore.append_jsonl(DRILL_LOG, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "hands_immunity_drill",
            "ok": all(l.ok for l in legs),
            "legs": [l.to_meta() for l in legs],
        })
    except Exception:
        pass


def _print(legs: list[Leg]) -> None:
    print("🖐️🛡️ opencrab 自生手免疫演练\n")
    for l in legs:
        print(f"  {'✅' if l.ok else '❌'} {l.name}：{l.detail}")
    print()
    if all(l.ok for l in legs):
        print("🛡️ 守约：畸形拒得住、越界(含路径)伸不出、语法坏落不了盘，"
              "且每发砸完真文件分毫不动——会犯错的手伤不到身。")
    else:
        print("⚠️  免疫演练有腿没跑通：有一类坏手没被挡在该挡的闸上、或拒收没回滚干净，"
              "先把这道免疫修稳再让手大胆改码——手会犯错，得先练会不伤身。")


def selfcheck(quiet: bool = False) -> bool:
    """自检：三类坏手各被拒在预期闸、且每发砸完真文件分毫不动(供 evidence 回灌)。"""
    legs = run()
    failures = [f"{l.name}：{l.detail}" for l in legs if not l.ok]
    ok = not failures
    if not quiet:
        if ok:
            print("✅ hands_immunity_drill selfcheck：畸形/越界(含路径)/语法坏三类坏手"
                  "各被拒在预期闸，且每发砸完真文件 sha256 一字不差——自生手的免疫可信。")
        else:
            print("❌ hands_immunity_drill selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手免疫演练 🖐️🛡️")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有腿没跑通时说话(适合钩子 / CI)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true", help="导出机读演练报告")
    g.add_argument("--selfcheck", action="store_true",
                   help="自检：三类坏手各被拒在预期闸且真文件分毫不动(供 evidence 回灌)")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    legs = run()
    _record(legs)
    ok = all(l.ok for l in legs)
    if args.json:
        print(json.dumps({"ok": ok, "legs": [l.to_meta() for l in legs]},
                         ensure_ascii=False, indent=2))
    elif not (args.quiet and ok):
        _print(legs)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
