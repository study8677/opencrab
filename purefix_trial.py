#!/usr/bin/env python3
"""opencrab 自生手·纯函数小修实战赛 🧪🦀

一句话：**从「会修编译不过的语法伤」迈向「会亲手改一处代码逻辑」——
拉 brain 上场,只准它对一个低风险解析/格式化纯函数,凭一组「它本该满足什么」的
判据(失败的测试)自己产补丁、过试衣间、跑回归,修不动就老实回滚。**

为什么要有它:`weaning_trial.py` 的招式库只治**语法级真伤**(补冒号 / print 括号 /
名字纠偏)——那些是「编译/加载就崩」的伤,报错本身就指向下刀处。可「亲手改代码逻辑」
是另一回事:函数**能编译、能跑、不崩**,只是**算错了**——没有任何异常会冒出来指路,
唯一的信号是「给定输入,输出不对」。要修这种伤,驱动力就不再是 `except`,而是一组
**失败的判据(测试样例)**:brain 试一处通用小修→拿全部判据复验→过了才算修对。

赛制(全程在隔离内存里跑,绝不碰真仓库、不雇任何爪子、不写真账本)：

  · 出 3 道**真实纯函数小修**:每道是一个能跑但算错的解析/格式化函数 + 一组
    (输入, 期望输出) 判据。伤是真的边界/去空白/差一错,**答案不写在题面里**——
    brain 得靠「试通用小修 + 判据复验」自己撞对那一处。
  · brain 上场:`purefix_repair` 依次拿**通用变异算子**(MUTATORS)对源码改一处,
    每个候选先过 `patchcontract` 拒收闸(畸形/越界当场拒),再拿**全部判据**复验;
    第一个让判据全过的候选即收下。所有算子都试遍仍没有一个让判据全过 = 无招可解,
    当场回滚原样(断肢再生),报告「没修成」——绝不硬塞一个仍然算错的补丁。
  · 裁决:brain 交出的补丁,再拿这道题的全部判据独立复验一遍才算赢。
  · 经试衣间:selfcheck 里把一道修好的真补丁,**真的送进 `patchfitroom` 过闸**——
    证明 brain 产的纯函数补丁不只在内存里对,还扛得住「形状/语法/触觉/import」那几道
    针对真文件的闸,过了才会原子写回。这就是「经试衣间验证」落到实处。
  · 计分:实战通过率 = 真修好的题数 / 总题数。低于门槛退出码非零,可当断奶门禁。

变异算子库(都是**通用**小修,绝不内嵌某道题的标准答案,靠判据复验撞对那一处)：
  🔧 边界松紧 : 每处 `<`/`>`/`<=`/`>=` 逐处单独松/紧一档——治差一的边界比较。
  🔧 整数差一 : 每个整数字面量逐个 ±1——治差一的常量/下标。
  🔧 去空白   : 每条 `return <表达式>` 句尾补一次 `.strip()`——治解析后忘去首尾空白。

回滚自测也要被验:selfcheck 里塞一道**没有任何小修能补上**的伤(要求反转词序,
不是改一处能成的),断言 brain 既修不动、又老实回滚原样,而非硬塞坏补丁。

用法:
    python purefix_trial.py             # 跑实战赛,打印逐题战报 + 通过率
    python purefix_trial.py --json      # 机读战报(给 health / 外部消费)
    python purefix_trial.py --selfcheck # 自检:3 道全过 + 回滚探针 + 一道真过试衣间
    加 --quiet 静默,仅以退出码表态。
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import pathlib
import re
import sys
import tempfile
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore
import patchcontract   # 自生补丁契约:变异算子吐出的候选,先过「畸形/越界」拒收闸才准复验

TRIAL_LOG = REPO_ROOT / "state" / "purefix_trial.jsonl"

PASS_THRESHOLD = 1.0   # 断奶门禁:3 道纯函数小修必须全过——独立改逻辑不留及格线的余地


# ── 变异算子库:每个算子读源码、产一批「改一处」的通用候选,绝不内嵌某题答案 ────────
_CMP = re.compile(r"<=|>=|<|>")            # 先匹配双字符,绝不把 <= 拆成 <
_CMP_SWAP = {"<": "<=", ">": ">=", "<=": "<", ">=": ">"}


def mut_relax_comparison(src: str) -> list[str]:
    """边界松紧:每处比较运算符逐处单独松/紧一档(< ↔ <=、> ↔ >=)。治差一的边界比较。"""
    out: list[str] = []
    for m in _CMP.finditer(src):
        repl = _CMP_SWAP[m.group(0)]
        out.append(src[:m.start()] + repl + src[m.end():])
    return out


_INT = re.compile(r"\b\d+\b")


def mut_adjust_int_literal(src: str) -> list[str]:
    """整数差一:每个整数字面量逐个 ±1(负数跳过)。治差一的常量/下标/宽度。"""
    out: list[str] = []
    for m in _INT.finditer(src):
        val = int(m.group(0))
        for nv in (val + 1, val - 1):
            if nv < 0:
                continue
            out.append(src[:m.start()] + str(nv) + src[m.end():])
    return out


_RETURN = re.compile(r"^(\s*return\s+)(.+?)(\s*)$")


def mut_add_strip(src: str) -> list[str]:
    """去空白:每条 `return <表达式>` 句尾补一次 .strip()。治解析后忘去首尾空白。

    若表达式算出来的不是字符串,补 .strip() 会在复验时抛错→那个候选自然落选,安全。
    """
    out: list[str] = []
    lines = src.split("\n")
    for i, ln in enumerate(lines):
        m = _RETURN.match(ln)
        if not m:
            continue
        indent, expr, tail = m.group(1), m.group(2), m.group(3)
        if expr.endswith(".strip()"):
            continue
        new = lines[:]
        new[i] = f"{indent}{expr}.strip(){tail}"
        out.append("\n".join(new))
    return out


MUTATORS: list = [mut_relax_comparison, mut_adjust_int_literal, mut_add_strip]


# ── 判据复验:exec 候选,拿全部 (输入, 期望) 跑一遍,全中才算这一处改对 ──────────
def _passes_all(src: str, fname: str, cases: list[tuple]) -> bool:
    """exec 候选源码、取出 fname,拿全部判据复验。任何环节崩/算错都判没过。

    跑的是赛题里我们自造的隔离纯函数,无外部输入;stdout 重定向掉,别污染战报。
    """
    ns: dict = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(src, "<purefix-candidate>", "exec"), ns)  # noqa: S102 —— 隔离自造源码
    except BaseException:  # noqa: BLE001 —— 加载即崩的候选直接判没过
        return False
    fn = ns.get(fname)
    if not callable(fn):
        return False
    for args, expected in cases:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                got = fn(*args)
        except BaseException:  # noqa: BLE001 —— 跑崩的候选判没过(比如对非串补 .strip())
            return False
        if got != expected:
            return False
    return True


@dataclasses.dataclass
class Repair:
    """brain 一次纯函数小修的全过程。"""
    fixed: str | None          # 修好的源码;None = 无招可解,已回滚原样
    rolled_back: bool          # 是否触发了回滚(断肢再生)
    trace: list[str]           # 每一爪:哪个算子产的候选、被契约拒了还是判据没过


def purefix_repair(broken: str, fname: str, cases: list[tuple],
                   *, max_candidates: int = 64) -> Repair:
    """brain 独立小修:拿通用算子改一处→过契约→全部判据复验,第一个全过的收下。

    驱动力不是异常而是「失败的判据」:函数本来能跑不崩,只是算错。所有算子都试遍仍
    没有候选让判据全过 = 无招可解,回滚原样、报告没修成(绝不硬塞仍算错的补丁)。
    """
    trace: list[str] = []
    if _passes_all(broken, fname, cases):
        return Repair(fixed=None, rolled_back=False, trace=["原样已满足判据,无需小修"])

    seen = 0
    for mut in MUTATORS:
        for cand in mut(broken):
            if cand == broken:
                continue
            seen += 1
            if seen > max_candidates:        # 候选爆炸的兜底:别把生命耗在搜索上
                trace.append("候选数越上限,停搜")
                return Repair(fixed=None, rolled_back=True, trace=trace)
            verdict = patchcontract.validate(broken, cand)  # 拒收闸:畸形/越界当场拒,换下一个
            if not verdict.ok:
                trace.append(f"{mut.__name__} 候选被契约拒收({verdict.code})")
                continue
            if _passes_all(cand, fname, cases):
                trace.append(f"{mut.__name__} ⮕ 判据全过")
                return Repair(fixed=cand, rolled_back=False, trace=trace)
    trace.append("无招可解:所有通用小修都没让判据全过")
    return Repair(fixed=None, rolled_back=True, trace=trace)


# ── 赛题:真实纯函数小修。伤是真的,答案不写在题面里 ──────────────────────────
@dataclasses.dataclass(frozen=True)
class Challenge:
    name: str
    wound: str                 # 这道伤是什么(人话)
    broken: str                # 能跑但算错的源码
    fname: str                 # 要修的函数名
    cases: list[tuple]         # 一组 (入参元组, 期望输出) —— 既是判据也是 oracle
    want: str                  # 这组判据想验的事(人话)


CHALLENGES: list[Challenge] = [
    Challenge(
        name="端口边界差一",
        wound="校验端口区间时上界用了 < 65535,把合法的 65535 误判为非法(差一)",
        broken="def valid_port(p):\n    return 0 < p < 65535\n",
        fname="valid_port",
        cases=[((65535,), True), ((80,), True), ((0,), False), ((70000,), False)],
        want="valid_port 在 1..65535 都为真,0 与越界为假",
    ),
    Challenge(
        name="解析去空白",
        wound="从 'key = value' 取 key 时忘了去首尾空白,返回了带空格的脏 key",
        broken='def parse_key(line):\n    return line.split("=")[0]\n',
        fname="parse_key",
        cases=[((" name = bob",), "name"), (("a=b",), "a"), (("  x =1",), "x")],
        want="parse_key 取到的 key 已去掉首尾空白",
    ),
    Challenge(
        name="行宽常量差一",
        wound="判断一行是否放得下时上界写成 <= 79,把恰好 80 列的行误判为放不下(差一)",
        broken="def fits_line(s):\n    return len(s) <= 79\n",
        fname="fits_line",
        cases=[(("a" * 80,), True), (("a" * 81,), False), (("",), True)],
        want="fits_line 在 0..80 列为真,81 列起为假",
    ),
]

# 回滚探针:要求反转词序——不是「改一处」能成的伤,任何通用小修都补不上。
# 专验 brain 修不动时老实回滚原样、报告没修成,而非硬塞坏补丁。
ROLLBACK_PROBE = Challenge(
    name="回滚探针",
    wound="要求把词序反转,这要重写函数体,没有任何「改一处」的小修能补上",
    broken="def reverse_words(s):\n    return s\n",
    fname="reverse_words",
    cases=[(("a b c",), "c b a"), (("hi there",), "there hi")],
    want="brain 修不动 → 回滚原样、报告没修成(而非硬塞坏补丁)",
)


@dataclasses.dataclass
class Bout:
    """一道题的实战结果。"""
    name: str
    wound: str
    survived: bool             # brain 交出的补丁能编译能跑吗
    won: bool                  # 全部判据复验过没过——这才算赢
    rolled_back: bool
    detail: str

    def to_meta(self) -> dict:
        return {"name": self.name, "wound": self.wound, "survived": self.survived,
                "won": self.won, "rolled_back": self.rolled_back, "detail": self.detail}


def fight(c: Challenge) -> Bout:
    """让 brain 独立小修一道题,再拿全部判据独立裁决胜负。"""
    rep = purefix_repair(c.broken, c.fname, c.cases)
    if rep.fixed is None:
        return Bout(c.name, c.wound, survived=False, won=False, rolled_back=rep.rolled_back,
                    detail=f"无招可解,已回滚原样({'；'.join(rep.trace) or '—'})")
    won = _passes_all(rep.fixed, c.fname, c.cases)   # 独立复验:driver 说过了,这里再钉一遍
    fixes = "；".join(rep.trace) or "无需动手"
    detail = (f"独立小修通:{fixes}|验「{c.want}」✅"
              if won else f"补丁能跑却没真修好(验「{c.want}」失败):{fixes}")
    return Bout(c.name, c.wound, survived=True, won=won, rolled_back=False, detail=detail)


def run() -> list[Bout]:
    """跑全部真实纯函数小修,得到逐题战果。"""
    return [fight(c) for c in CHALLENGES]


def pass_rate(bouts: list[Bout]) -> float:
    return (sum(1 for b in bouts if b.won) / len(bouts)) if bouts else 0.0


# ── 经试衣间:把一道修好的真补丁,真的送进 patchfitroom 过闸 ────────────────────
def _through_fitroom(broken: str, fixed: str) -> tuple[bool, str]:
    """把 broken→fixed 这次小修当作针对真文件的补丁,送进 patchfitroom 过闸。

    在隔离临时仓库里跑,绝不碰真仓库;无 contracts.py 故跳过契约闸,验形状/语法/触觉/import
    四闸——证明 brain 产的纯函数补丁不只内存里对,还扛得住针对真文件的那几道闸。
    返回 (是否过闸写回, 一句现场)。patchfitroom 缺席/出意外都收敛为「没过」,绝不反噬。
    """
    try:
        import patchfitroom
    except Exception as e:  # noqa: BLE001
        return False, f"patchfitroom 缺席({type(e).__name__}),跳过试衣间这一验"
    try:
        with tempfile.TemporaryDirectory(prefix="purefix-") as d:
            dp = pathlib.Path(d)
            target = dp / "subject.py"
            target.write_text(broken, encoding="utf-8")
            r = patchfitroom.fit(target, fixed, repo=dp, check_contracts=False)
            return r.written, r.detail
    except Exception as e:  # noqa: BLE001
        return False, f"送试衣间时出意外:{type(e).__name__}: {e}"


def _record(bouts: list[Bout]) -> None:
    """战报落进流水账(写盘失败被吞,绝不反噬主流程)。"""
    try:
        jsonlstore.append_jsonl(TRIAL_LOG, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "purefix_trial",
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
    print("🧪🦀 opencrab 自生手·纯函数小修实战赛")
    print("    赛制:拔掉外援,只准 brain 凭失败的判据自己产补丁→过契约→复验→修不动就回滚\n")
    for b in bouts:
        mark = "🏆" if b.won else ("🩹" if b.rolled_back else "❌")
        print(f"  {mark} {b.name}（{b.wound}）")
        print(f"      {b.detail}")
    print(f"\n    实战通过率：{won}/{len(bouts)} = {rate:.0%}")
    if rate >= PASS_THRESHOLD:
        print("🧪 小修成立：没雇一只爪子,brain 凭失败的判据撞对了那一处逻辑,把这几道真伤都修对了。")
    else:
        lost = "、".join(b.name for b in bouts if not b.won)
        print(f"⚠️  小修未成：「{lost}」brain 还修不对——逻辑独立性差这几仗,先补算子再谈拔外援。")


def selfcheck(quiet: bool = False) -> bool:
    """自检:3 道纯函数小修必须全过 + 回滚探针成立 + 一道真补丁真能过试衣间。供 evidence 复跑。"""
    failures: list[str] = []

    bouts = run()
    for b in bouts:
        if not b.won:
            failures.append(f"纯函数小修「{b.name}」没修对:{b.detail}")

    # 回滚探针:无招可解时,brain 必须回滚原样、报告没修成,而非硬塞坏补丁。
    rep = purefix_repair(ROLLBACK_PROBE.broken, ROLLBACK_PROBE.fname, ROLLBACK_PROBE.cases)
    if rep.fixed is not None:
        failures.append("回滚探针:brain 竟「修好」了一道没有小修能补的伤——回滚没触发,危险")
    elif not rep.rolled_back:
        failures.append("回滚探针:brain 没修成却没标记回滚——断肢再生失灵")

    # 经试衣间:挑第一道修好的真补丁,真的送进 patchfitroom 过闸,过了才算「逻辑补丁能落盘」。
    c0 = CHALLENGES[0]
    r0 = purefix_repair(c0.broken, c0.fname, c0.cases)
    if r0.fixed is None:
        failures.append("经试衣间:第一道题没修出补丁,无从送试衣间")
    else:
        written, detail = _through_fitroom(c0.broken, r0.fixed)
        if not written:
            failures.append(f"经试衣间:修好的纯函数补丁竟没过试衣间——{detail}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ purefix_trial selfcheck：3 道纯函数小修全过 + 回滚探针成立 + 修好的补丁真能过试衣间"
                  "——brain 亲手改逻辑这一步可信。")
        else:
            print("❌ purefix_trial selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


def manifest() -> dict:
    """机读快照,给 health / 外部消费。"""
    bouts = run()
    return {"event": "purefix_trial", "pass_rate": pass_rate(bouts),
            "won": sum(1 for b in bouts if b.won), "total": len(bouts),
            "mutators": [m.__name__ for m in MUTATORS],
            "bouts": [b.to_meta() for b in bouts]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手·纯函数小修实战赛 🧪🦀")
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
