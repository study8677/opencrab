#!/usr/bin/env python3
"""opencrab 自生手断奶实战赛 🍼🦀

一句话：**别再宣称 brain 能独立修代码——拉它上场,只准它自己产补丁、自己自测、
修不动就自己回滚,用「实战通过率」把独立性钉成数字。**

为什么要有它：`hands.py` 至今是**雇佣**爪子(claude / codex CLI)动手,brain 只攥着 git
与免疫闸。可「会指挥别人」不等于「自己会动手」。断奶,就是把外援拔掉,看 brain 在没有
任何 LLM 外援的前提下,**单凭读懂报错→改源码→自测→回滚**这套纯逻辑,能修好几道真伤。
独立性不能靠日志里写「我能自主」——只能靠一场场实战的通过率证明。

赛制(全程在隔离临时态里跑,绝不碰真仓库、不雇任何爪子、不写真账本)：

  · 出 3 道**真实小修**:每道是一段确实跑不起来的源码 + 一条「它本该满足什么」的判据(oracle)。
    伤口是真的语法/命名错,**答案不写在题面里**——brain 得自己从报错里推。
  · brain 上场:`brain_repair` 只会一件事——把候选源码 `compile`+`exec` 跑一遍当自测
    (正是 `hands._self_test` 那句「还能不能启动」),跑崩了就读异常、从招式库里挑一招改一处,
    再跑;反复到修通或**无招可解**。无招可解 = 当场把候选丢回原样(断肢再生),报告「没修成」。
  · 裁决:brain 交出的补丁,再用这道题的 oracle 判「**真修好了没**」——
    自测「能启动」只证明没把自己改死,oracle 过了才算这一仗赢。
  · 计分:实战通过率 = 真修好的题数 / 总题数。低于门槛,退出码非零,可当 CI / 钩子的断奶门禁。

招式库(都是**通用**战术,读报错决定怎么改,绝不内嵌某道题的标准答案)：
  🔧 补冒号    : SyntaxError「expected ':'」→ 给报错那行补上结尾冒号。
  🔧 括号 print: SyntaxError「Missing parentheses in call to 'print'」→ 把 `print X` 收成 `print(X)`。
  🔧 名字纠偏  : NameError → 把认不出的名字,用 difflib 跟「内建 + 本模块定义过的名字」做最近匹配后改回。

回滚自测本身也要被验:selfcheck 里塞一道**故意无招可解**的伤(顶层 `raise`),断言 brain
既修不动、又把源码原样吐回——证明它不会硬塞一个改坏的补丁,而是老实回滚保命。

用法:
    python weaning_trial.py                 # 跑实战赛,打印逐题战报 + 通过率
    python weaning_trial.py --json          # 机读战报(给 health / 外部消费)
    python weaning_trial.py --selfcheck     # 自检:3 道全过 + 回滚探针成立,作 evidence 复跑命令
    加 --quiet 静默,仅以退出码表态。
"""
from __future__ import annotations

import argparse
import builtins
import contextlib
import dataclasses
import difflib
import io
import json
import pathlib
import re
import sys
import time

import jsonlstore
import patchcontract   # 自生补丁契约：招式吐出的候选，先过「畸形/越界」拒收闸才准收

REPO_ROOT = pathlib.Path(__file__).resolve().parent
TRIAL_LOG = REPO_ROOT / "state" / "weaning_trial.jsonl"

PASS_THRESHOLD = 1.0   # 断奶门禁:3 道真修,必须全过——独立性不留及格线的余地


# ── 招式库：每招读懂一类报错,改一处源码,绝不内嵌某道题的答案 ────────────────
def _split(src: str) -> list[str]:
    return src.split("\n")


def tactic_missing_colon(src: str, exc: BaseException) -> str | None:
    """补冒号：SyntaxError「expected ':'」→ 给报错那行补上结尾冒号。"""
    if not (isinstance(exc, SyntaxError) and exc.msg and "':'" in exc.msg):
        return None
    lines = _split(src)
    i = (exc.lineno or 1) - 1
    if not (0 <= i < len(lines)):
        return None
    code = lines[i].rstrip()
    if not code or code.endswith(":"):
        return None
    lines[i] = code + ":"
    return "\n".join(lines)


def tactic_print_parens(src: str, exc: BaseException) -> str | None:
    """括号 print：SyntaxError「Missing parentheses…print」→ 把 `print X` 收成 `print(X)`。"""
    if not (isinstance(exc, SyntaxError) and exc.msg
            and "Missing parentheses in call to 'print'" in exc.msg):
        return None
    lines = _split(src)
    i = (exc.lineno or 1) - 1
    if not (0 <= i < len(lines)):
        return None
    m = re.match(r"^(\s*)print\s+(.+?)\s*$", lines[i])
    if not m:
        return None
    lines[i] = f"{m.group(1)}print({m.group(2)})"
    return "\n".join(lines)


def _known_names(src: str) -> list[str]:
    """本模块里能被认出的名字：内建 + 顶层 def/class/赋值/import 绑定过的名字。"""
    names = set(dir(builtins))
    names.update(re.findall(r"^(?:def|class)\s+(\w+)", src, re.M))
    names.update(re.findall(r"^(\w+)\s*=", src, re.M))
    names.update(re.findall(r"^\s*import\s+(\w+)", src, re.M))
    return sorted(names)


def tactic_name_typo(src: str, exc: BaseException) -> str | None:
    """名字纠偏：NameError → 把认不出的名字,跟已知名字做最近匹配后整词改回。"""
    if not isinstance(exc, NameError):
        return None
    name = getattr(exc, "name", None)
    if not name:
        m = re.search(r"name '(\w+)'", str(exc))
        name = m.group(1) if m else None
    if not name:
        return None
    cands = difflib.get_close_matches(name, _known_names(src), n=1, cutoff=0.6)
    if not cands or cands[0] == name:
        return None
    fixed = re.sub(rf"\b{re.escape(name)}\b", cands[0], src)
    return fixed if fixed != src else None


TACTICS: list = [tactic_missing_colon, tactic_print_parens, tactic_name_typo]


# ── brain 的自测：就一句「还能不能启动」(compile + exec),与 hands 同源 ──────
def _self_test(src: str) -> tuple[BaseException | None, dict]:
    """跑一遍候选源码。返回 (异常或 None, 命名空间)；异常为 None 即「能启动」。"""
    try:
        code = compile(src, "<brain-candidate>", "exec")
    except SyntaxError as e:
        return e, {}
    ns: dict = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # 别让题面源码的打印污染战报
            exec(code, ns)  # noqa: S102 —— 跑的是赛题里我们自造的隔离源码,无外部输入
    except BaseException as e:  # noqa: BLE001 —— 任何起跑即崩都算没通过自测
        return e, ns
    return None, ns


@dataclasses.dataclass
class Repair:
    """brain 一次自修的全过程。"""
    fixed: str | None          # 修好的源码；None = 无招可解,已回滚原样
    rolled_back: bool          # 是否触发了回滚(断肢再生)
    trace: list[str]           # 每一爪：用哪招应对了哪类报错


def brain_repair(broken: str, *, max_rounds: int = 6) -> Repair:
    """brain 独立自修：读报错→挑一招改一处→自测,反复;无招可解就回滚到原样。"""
    src = broken
    trace: list[str] = []
    for _ in range(max_rounds):
        exc, _ns = _self_test(src)
        if exc is None:
            return Repair(fixed=src, rolled_back=False, trace=trace)
        for tactic in TACTICS:
            cand = tactic(src, exc)
            if cand is None or cand == src:
                continue
            # 拒收闸：招式吐出的候选先过补丁契约——畸形(空/非串)或越界(重写式大改)当场拒，
            # 换下一招;一只可托付的爪子,落笔前先得能判「这一爪收不收」。
            verdict = patchcontract.validate(src, cand)
            if not verdict.ok:
                trace.append(f"{tactic.__name__} 补丁被契约拒收({verdict.code})")
                continue
            trace.append(f"{tactic.__name__} ⮕ {type(exc).__name__}")
            src = cand
            break
        else:  # 一招都使不上(或都被契约拒收) —— 老实回滚,绝不硬塞一个改坏的补丁
            trace.append(f"无招可解 {type(exc).__name__}: {str(exc)[:60]}")
            return Repair(fixed=None, rolled_back=True, trace=trace)
    # 招数用尽仍没修通：回滚保命
    if _self_test(src)[0] is None:
        return Repair(fixed=src, rolled_back=False, trace=trace)
    trace.append("回合用尽仍未修通")
    return Repair(fixed=None, rolled_back=True, trace=trace)


# ── 赛题：真实小修。伤口是真的,答案不写在题面里 ──────────────────────────
@dataclasses.dataclass(frozen=True)
class Challenge:
    name: str
    wound: str                 # 这道伤是什么(人话)
    broken: str                # 跑不起来的源码
    oracle: "callable"         # 拿修好后的命名空间判「真修好了没」
    want: str                  # oracle 想验的事(人话)


CHALLENGES: list[Challenge] = [
    Challenge(
        name="补冒号",
        wound="def 行漏了结尾冒号,源码连编译都过不去",
        broken="def add(a, b)\n    return a + b\n",
        oracle=lambda ns: ns["add"](2, 3) == 5,
        want="add(2,3) == 5",
    ),
    Challenge(
        name="括号 print",
        wound="函数体里用了 Python2 的 print 语句,编译即报缺括号",
        broken='def greet(name):\n    print "hi " + name\n    return "hi " + name\n',
        oracle=lambda ns: ns["greet"]("crab") == "hi crab",
        want='greet("crab") == "hi crab"',
    ),
    Challenge(
        name="名字纠偏",
        wound="顶层常量调用了某函数的拼错名,模块一加载就 NameError",
        broken="def double(x):\n    return x * 2\n\nRESULT = doubel(21)\n",
        oracle=lambda ns: ns["RESULT"] == 42,
        want="RESULT == double(21) == 42",
    ),
]

# 回滚探针：故意无招可解的伤(顶层就 raise),专验 brain 修不动时老实回滚、不硬塞。
ROLLBACK_PROBE = Challenge(
    name="回滚探针",
    wound="顶层直接 raise,任何招式都治不了——专验回滚是否真的会触发",
    broken='raise RuntimeError("无法修复的伤")\n',
    oracle=lambda ns: False,
    want="brain 修不动 → 回滚原样、报告没修成(而非硬塞坏补丁)",
)


@dataclasses.dataclass
class Bout:
    """一道题的实战结果。"""
    name: str
    wound: str
    survived: bool             # brain 交出的补丁「能启动」吗(自测过没过)
    won: bool                  # oracle 判「真修好了没」——这才算赢
    rolled_back: bool
    detail: str

    def to_meta(self) -> dict:
        return {"name": self.name, "wound": self.wound, "survived": self.survived,
                "won": self.won, "rolled_back": self.rolled_back, "detail": self.detail}


def fight(c: Challenge) -> Bout:
    """让 brain 独立修一道题,再用 oracle 裁决胜负。"""
    rep = brain_repair(c.broken)
    if rep.fixed is None:
        return Bout(c.name, c.wound, survived=False, won=False, rolled_back=rep.rolled_back,
                    detail=f"无招可解,已回滚原样({'；'.join(rep.trace) or '—'})")
    exc, ns = _self_test(rep.fixed)
    if exc is not None:   # 理论上不该到这,brain 已自测过;兜底防串味
        return Bout(c.name, c.wound, survived=False, won=False, rolled_back=False,
                    detail=f"交出的补丁竟跑不起来:{type(exc).__name__}")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            won = bool(c.oracle(ns))
    except Exception as e:  # noqa: BLE001 —— oracle 自身崩了也算没赢
        return Bout(c.name, c.wound, survived=True, won=False, rolled_back=False,
                    detail=f"补丁能启动,但 oracle 判定时崩了:{type(e).__name__}")
    fixes = "；".join(rep.trace) or "无需动手"
    detail = (f"独立修通:{fixes}|验「{c.want}」{'✅' if won else '❌'}"
              if won else f"补丁能启动却没真修好(验「{c.want}」失败):{fixes}")
    return Bout(c.name, c.wound, survived=True, won=won, rolled_back=False, detail=detail)


def run() -> list[Bout]:
    """跑全部真实小修,得到逐题战果。"""
    return [fight(c) for c in CHALLENGES]


def pass_rate(bouts: list[Bout]) -> float:
    return (sum(1 for b in bouts if b.won) / len(bouts)) if bouts else 0.0


def _record(bouts: list[Bout]) -> None:
    """战报落进流水账(写盘失败被吞,绝不反噬主流程)。"""
    try:
        jsonlstore.append_jsonl(TRIAL_LOG, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "weaning_trial",
            "pass_rate": pass_rate(bouts),
            "won": sum(1 for b in bouts if b.won),
            "total": len(bouts),
            "bouts": [b.to_meta() for b in bouts],
        })
    except Exception:  # noqa: BLE001
        pass


def _print(bouts: list[Bout]) -> None:
    rate = pass_rate(bouts)
    won = sum(1 for b in bouts if b.won)
    print("🍼🦀 opencrab 自生手断奶实战赛")
    print("    赛制:拔掉外援,只准 brain 自己产补丁→自测→修不动就回滚\n")
    for b in bouts:
        mark = "🏆" if b.won else ("🩹" if b.rolled_back else "❌")
        print(f"  {mark} {b.name}（{b.wound}）")
        print(f"      {b.detail}")
    print(f"\n    实战通过率：{won}/{len(bouts)} = {rate:.0%}")
    if rate >= PASS_THRESHOLD:
        print("🍼 断奶成立：没雇一只爪子,brain 单凭读报错→改源码→自测,把这几道真伤都修通了。")
    else:
        lost = "、".join(b.name for b in bouts if not b.won)
        print(f"⚠️  断奶未成：「{lost}」brain 还修不动——独立性差这几仗,先补招式再谈拔外援。")


def selfcheck(quiet: bool = False) -> bool:
    """自检:3 道真修必须全过,且回滚探针必须触发回滚、修不动。供 evidence 复跑。"""
    failures: list[str] = []

    bouts = run()
    for b in bouts:
        if not b.won:
            failures.append(f"真修「{b.name}」没修通:{b.detail}")

    # 回滚探针:无招可解时,brain 必须回滚原样、报告没修成,而非硬塞坏补丁。
    rep = brain_repair(ROLLBACK_PROBE.broken)
    if rep.fixed is not None:
        failures.append("回滚探针:brain 竟「修好」了一道无解伤——回滚没触发,危险")
    elif not rep.rolled_back:
        failures.append("回滚探针:brain 没修成却没标记回滚——断肢再生失灵")

    # 拒收闸探针:brain_repair 收候选前依赖的补丁契约,必须把畸形/越界的当场拒收。
    # 这是「自生补丁可拒绝」的最小证明——拒收闸一旦失灵,brain 就会照单全收坏补丁。
    legit = "def add(a, b):\n    return a + b\n"      # 正当的「修一处」候选
    if not patchcontract.accepts("def add(a, b)\n    return a + b\n", legit):
        failures.append("拒收闸探针:正当的「修一处」补丁竟被契约拒收")
    overhaul = "\n".join(f"line{i}" for i in range(50))   # 重写式大改 = 越界
    if patchcontract.accepts("def add(a, b)\n    return a + b\n", overhaul):
        failures.append("拒收闸探针:重写式越界补丁竟被契约接收——危险,brain 会照单全收")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ weaning_trial selfcheck：3 道真修全过 + 回滚探针成立——断奶机制可信。")
        else:
            print("❌ weaning_trial selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


def manifest() -> dict:
    """机读快照,给 health / 外部消费。"""
    bouts = run()
    return {"event": "weaning_trial", "pass_rate": pass_rate(bouts),
            "won": sum(1 for b in bouts if b.won), "total": len(bouts),
            "bouts": [b.to_meta() for b in bouts]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手断奶实战赛 🍼🦀")
    ap.add_argument("--json", action="store_true", help="导出机读战报")
    ap.add_argument("--selfcheck", action="store_true", help="自检模式(给 evidence 复跑)")
    ap.add_argument("--quiet", action="store_true", help="静默,仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    bouts = run()
    _record(bouts)
    if args.json:
        if not args.quiet:
            print(json.dumps(manifest(), ensure_ascii=False, indent=2))
    elif not args.quiet:
        _print(bouts)
    sys.exit(0 if pass_rate(bouts) >= PASS_THRESHOLD else 1)


if __name__ == "__main__":
    main()
