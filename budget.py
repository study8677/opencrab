#!/usr/bin/env python3
"""自改预算 💰 —— 给每次自我改动预设**会节制**的边界:时间、命令、文件改动、风险,
超额自动喊停并记下理由。

为什么要有它:真正的自主不是把资源跑满,而是会克制。一个没有预算的自改循环,最容易
滑向「拿动作量伪装进步」——改得越多越像在干活,跑得越久越像在努力,可领地未必更好,
只是更乱、更难回滚。古德哈特会在这里钻空子:一旦「改了多少」成了隐性的成绩单,节制
就成了第一个被牺牲的美德。

本预算把「这次自改我允许自己花多少」逼成一份**开工前就立好、随时可查的硬边界**:

  · ⏱️ 时间   —— 这次自改最多花多少分钟(超了就该收尾,而不是无限期磨)
  · 🔧 命令   —— 最多跑多少条「动手」命令(由调用方主动记账,见 --spend)
  · 📝 文件   —— 最多改动多少个文件(diff 一数便知,改面越大越该警觉)
  · ➕ 行数   —— 最多改动多少行(增+删,大改先怀疑自己是不是收不住了)
  · ⚠️ 风险   —— 最多累计多少风险分(碰核心/闸门/密钥的文件按权重加分)

开工即立账:`--open` 记下基线(当前 HEAD 与开工时刻)与四档上限,落进 state。此后随时
`--check`:用 git 量出此刻已花的时间/文件/行数/风险,逐档对照上限。**任一档超额** →
状态判「该停手」、退出码 1(可接进心跳钩子,让循环自己刹车),并把超了哪档、超了多少
记进账本——节制要留痕,才不会下次又装作没看见。

用法:
    python budget.py --open --name slug \\        # 开工立账:记基线 + 四档上限
        [--minutes 30] [--cmds 20] [--files 8] [--lines 400] [--risk 12]
    python budget.py --spend [name]               # 给「命令」档 +1(动手前主动记一笔)
    python budget.py --check [name]               # 量当前花费,逐档对照,超额即喊停(退1)
    python budget.py --stop "理由" [--name slug]  # 主动收尾:记下停手理由,结清这本账
    python budget.py                              # 等同 --check:列各档花费/上限/裁决
    python budget.py --json                       # 机读:导出当前账与逐档花费

退出码:默认/--check 时,只要有在开的预算「该停手」→ 1,否则 0。
零第三方依赖,纯标准库。预算是观测者:只读 git、只写自己那本账,绝不碰工作区、绝不真
打大脑。它不替你停手,只把「该停了」喊得足够大声、记得足够清楚。
"""
from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import pathlib
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
LEDGER = REPO_ROOT / "state" / "budget.jsonl"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import append_jsonl, read_jsonl  # noqa: E402

# 各档默认上限:刻意定得「够做一件正经事,但拦得住失控」。调用方可逐档覆盖。
DEFAULTS = {
    "minutes": 30,   # 一次自改的合理窗口;超了多半是卡住了,该收尾复盘
    "cmds": 20,      # 「动手」命令条数(由 --spend 记账,见下)
    "files": 8,      # 改动文件数;一次碰太多文件,回滚与审阅都变难
    "lines": 400,    # 改动行数(增+删);大改应先在分支上养(见 branchlab.py)
    "risk": 12,      # 累计风险分;碰核心/闸门/密钥按权重加分(见 _RISK_WEIGHTS)
}

# 风险权重:改到哪些文件更可能伤到领地。第一个匹配上的模式生效(由具体到笼统)。
# 与 invariant/policy 同源的直觉——核心心跳、能力闸门、密钥最该被慎重对待。
_RISK_WEIGHTS: list[tuple[str, int]] = [
    (".env", 5),                 # 密钥与真实配置,碰它=可能真打大脑/泄密
    ("crab.py", 5),              # 核心心跳,改坏=整个生命循环停摆
    ("capabilities/*", 4),       # 能力闸门,放宽=自我授权扩权
    ("policy.py", 4),
    ("contracts.py", 4),
    ("invariant.py", 4),
    ("jsonlstore.py", 3),        # 落地层,被记录系统共用,改坏面广
    ("*.py", 1),                 # 寻常 Python 改动
    ("journal/*", 0),            # 日志/文档,改了也不伤运行
    ("docs/*", 0),
    ("*.md", 0),
]


def _git(args: list[str]) -> tuple[int, str]:
    """在领地里跑一条 git,返回 (退出码, 合并输出)。失败永不抛错。"""
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                             capture_output=True, text=True, timeout=15)
        return out.returncode, (out.stdout + out.stderr).strip()
    except Exception as e:
        return -1, f"<git 异常> {e!r}"


def _risk_of(path: str) -> int:
    """一个改动文件值多少风险分:第一个匹配上的权重模式生效。"""
    p = path.replace("\\", "/")
    for pat, w in _RISK_WEIGHTS:
        if fnmatch.fnmatch(p, pat) or p == pat:
            return w
    return 1   # 未归类的文件按寻常改动计 1 分,宁可高估也不漏算


@dataclasses.dataclass
class Spend:
    """从基线量到此刻、这次自改已经花掉的四档(命令档由账本累加)。"""
    minutes: float          # ⏱️ 已花分钟
    cmds: int               # 🔧 已记的动手命令条数
    files: int              # 📝 已改动文件数
    lines: int              # ➕ 已改动行数(增+删)
    risk: int               # ⚠️ 累计风险分
    changed: list[str]      # 改动文件清单(供解释风险来源)


@dataclasses.dataclass
class Budget:
    """一次自改的预算契约:开工时刻、基线提交,与四档上限。

    四档缺省即用 DEFAULTS。`base_commit` 是开工那一刻的 HEAD,之后无论领地自己提交
    几次,`--check` 都用 `base...工作区` 量出累计花费——既盖得住已提交的改动,也盖得住
    还在工作区里的脏改动。`closed_at`/`stop_reason` 非空表示这本账已结清(主动收尾)。
    """
    name: str
    opened_at: float
    base_commit: str
    max_minutes: float
    max_cmds: int
    max_files: int
    max_lines: int
    max_risk: int
    note: str = ""
    cmds_spent: int = 0          # 由 --spend 累加的动手命令计数
    closed_at: float = 0.0       # >0 表示已结清
    stop_reason: str = ""        # 主动收尾时记下的理由

    def to_record(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_record(cls, d: dict) -> "Budget":
        return cls(
            name=d["name"],
            opened_at=float(d.get("opened_at", 0.0)),
            base_commit=d.get("base_commit", ""),
            max_minutes=float(d.get("max_minutes", DEFAULTS["minutes"])),
            max_cmds=int(d.get("max_cmds", DEFAULTS["cmds"])),
            max_files=int(d.get("max_files", DEFAULTS["files"])),
            max_lines=int(d.get("max_lines", DEFAULTS["lines"])),
            max_risk=int(d.get("max_risk", DEFAULTS["risk"])),
            note=d.get("note", ""),
            cmds_spent=int(d.get("cmds_spent", 0)),
            closed_at=float(d.get("closed_at", 0.0)),
            stop_reason=d.get("stop_reason", ""),
        )

    @property
    def is_open(self) -> bool:
        return self.closed_at <= 0.0


def _load() -> list[Budget]:
    """读出账本里每个 name 的最新状态(同名以最后一条为准:覆盖/记账/收尾都靠追加)。"""
    by_name: dict[str, Budget] = {}
    for rec in read_jsonl(LEDGER):
        try:
            b = Budget.from_record(rec)
        except Exception:
            continue   # 坏行跳过,账本读取永不抛错
        by_name[b.name] = b
    return list(by_name.values())


def _get(name: str | None) -> Budget | None:
    """取指定 name 的预算;不给 name 时取唯一一本在开的(便于无脑 --check)。"""
    budgets = _load()
    if name:
        for b in budgets:
            if b.name == name:
                return b
        return None
    opening = [b for b in budgets if b.is_open]
    return opening[-1] if opening else (budgets[-1] if budgets else None)


def _changed_since(base: str) -> tuple[list[str], int]:
    """量出基线以来改动的文件清单与总行数(增+删)。

    用 `git diff --numstat base`(默认对比工作区,盖得住已提交+脏改动),再补上
    `git status --porcelain` 里的未跟踪新文件。二进制文件 numstat 记 `-`,按 0 行计。
    """
    files: dict[str, int] = {}   # path -> 该文件改动行数
    if base:
        code, out = _git(["diff", "--numstat", base])
        if code == 0:
            for ln in out.splitlines():
                parts = ln.split("\t")
                if len(parts) != 3:
                    continue
                add, dele, path = parts
                n = (int(add) if add.isdigit() else 0) + (int(dele) if dele.isdigit() else 0)
                files[path.strip()] = files.get(path.strip(), 0) + n
    # 未跟踪的新文件 diff 看不见,从 porcelain 补进来(行数按其当前长度估)。
    _, st = _git(["status", "--porcelain"])
    for ln in st.splitlines():
        if ln.startswith("??"):
            path = ln[3:].strip()
            if path and path not in files:
                fp = REPO_ROOT / path
                try:
                    files[path] = len(fp.read_text("utf-8", errors="ignore").splitlines())
                except Exception:
                    files[path] = 0
    return sorted(files), sum(files.values())


def measure(b: Budget) -> Spend:
    """量出这本预算从基线到此刻的四档花费。"""
    minutes = max(0.0, (time.time() - b.opened_at) / 60.0)
    changed, lines = _changed_since(b.base_commit)
    risk = sum(_risk_of(p) for p in changed)
    return Spend(minutes=minutes, cmds=b.cmds_spent, files=len(changed),
                 lines=lines, risk=risk, changed=changed)


@dataclasses.dataclass
class Verdict:
    """对一本预算量完之后的逐档裁决。"""
    budget: Budget
    spend: Spend
    breaches: list[str]      # 超额的档(人话,空=全在预算内)

    @property
    def over_budget(self) -> bool:
        return bool(self.breaches)

    def to_meta(self) -> dict:
        b, s = self.budget, self.spend
        return {
            "name": b.name, "is_open": b.is_open, "note": b.note,
            "spent": {
                "minutes": round(s.minutes, 1), "cmds": s.cmds,
                "files": s.files, "lines": s.lines, "risk": s.risk,
            },
            "limits": {
                "minutes": b.max_minutes, "cmds": b.max_cmds,
                "files": b.max_files, "lines": b.max_lines, "risk": b.max_risk,
            },
            "changed": s.changed,
            "breaches": self.breaches,
            "verdict": "该停手" if self.over_budget else ("已结清" if not b.is_open else "在预算内"),
            "stop_reason": b.stop_reason,
        }


def evaluate(b: Budget) -> Verdict:
    """量出花费并逐档对照上限,凑出超额清单。"""
    s = measure(b)
    breaches: list[str] = []
    if s.minutes > b.max_minutes:
        breaches.append(f"⏱️ 时间 {s.minutes:.1f} 分 > 上限 {b.max_minutes:g} 分")
    if s.cmds > b.max_cmds:
        breaches.append(f"🔧 命令 {s.cmds} 条 > 上限 {b.max_cmds} 条")
    if s.files > b.max_files:
        breaches.append(f"📝 文件 {s.files} 个 > 上限 {b.max_files} 个")
    if s.lines > b.max_lines:
        breaches.append(f"➕ 行数 {s.lines} 行 > 上限 {b.max_lines} 行")
    if s.risk > b.max_risk:
        breaches.append(f"⚠️ 风险 {s.risk} 分 > 上限 {b.max_risk} 分")
    return Verdict(b, s, breaches)


# ── 命令 ─────────────────────────────────────────────────────────────────────
def open_budget(name: str, minutes: float, cmds: int, files: int,
                lines: int, risk: int, note: str) -> Budget:
    """开工立账:记下基线 HEAD 与开工时刻、四档上限,落进账本。"""
    code, head = _git(["rev-parse", "HEAD"])
    base = head.strip() if code == 0 else ""
    b = Budget(name=name, opened_at=time.time(), base_commit=base,
               max_minutes=float(minutes), max_cmds=int(cmds), max_files=int(files),
               max_lines=int(lines), max_risk=int(risk), note=note)
    append_jsonl(LEDGER, b.to_record())
    return b


def spend_cmd(name: str | None) -> Budget | None:
    """给「命令」档 +1:动手命令前主动记一笔(命令档无法被 git 被动量出)。"""
    b = _get(name)
    if b is None:
        return None
    b.cmds_spent += 1
    append_jsonl(LEDGER, b.to_record())
    return b


def stop_budget(name: str | None, reason: str) -> Budget | None:
    """主动收尾:记下停手理由,结清这本账(此后不再计入「在开」)。"""
    b = _get(name)
    if b is None:
        return None
    b.closed_at = time.time()
    b.stop_reason = reason
    append_jsonl(LEDGER, b.to_record())
    return b


# ── 输出 ─────────────────────────────────────────────────────────────────────
def _bar(spent: float, limit: float) -> str:
    """一档花费占上限的进度条:超额则标红警告。"""
    ratio = (spent / limit) if limit > 0 else (1.0 if spent > 0 else 0.0)
    filled = min(10, int(ratio * 10 + 0.999)) if spent > 0 else 0
    bar = "█" * filled + "░" * (10 - filled)
    flag = " 🚨超" if ratio > 1.0 else ""
    return f"{bar} {ratio * 100:3.0f}%{flag}"


def _print_verdict(v: Verdict) -> None:
    b, s = v.budget, v.spend
    state = "🚨 该停手" if v.over_budget else ("🔒 已结清" if not b.is_open else "🟢 在预算内")
    print(f"💰 预算「{b.name}」 {state}" + (f"  · {b.note}" if b.note else ""))
    print(f"   ⏱️ 时间  {s.minutes:6.1f}/{b.max_minutes:<5g} 分  {_bar(s.minutes, b.max_minutes)}")
    print(f"   🔧 命令  {s.cmds:6d}/{b.max_cmds:<5d} 条  {_bar(s.cmds, b.max_cmds)}")
    print(f"   📝 文件  {s.files:6d}/{b.max_files:<5d} 个  {_bar(s.files, b.max_files)}")
    print(f"   ➕ 行数  {s.lines:6d}/{b.max_lines:<5d} 行  {_bar(s.lines, b.max_lines)}")
    print(f"   ⚠️ 风险  {s.risk:6d}/{b.max_risk:<5d} 分  {_bar(s.risk, b.max_risk)}")
    if v.over_budget:
        print("   超额:")
        for br in v.breaches:
            print(f"     · {br}")
        print(f"   👉 该收尾了——记下进展与理由,`python budget.py --stop \"…\" --name {b.name}` 结账。")
    if not b.is_open and b.stop_reason:
        print(f"   📌 收尾理由：{b.stop_reason}")
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自改预算 💰")
    ap.add_argument("--open", action="store_true", help="开工立账:记基线 + 四档上限")
    ap.add_argument("--name", help="预算代号;--open 必填,其余命令可省(默认取唯一在开的)")
    ap.add_argument("--minutes", type=float, default=DEFAULTS["minutes"], help=f"时间上限/分(默认 {DEFAULTS['minutes']})")
    ap.add_argument("--cmds", type=int, default=DEFAULTS["cmds"], help=f"命令上限/条(默认 {DEFAULTS['cmds']})")
    ap.add_argument("--files", type=int, default=DEFAULTS["files"], help=f"文件上限/个(默认 {DEFAULTS['files']})")
    ap.add_argument("--lines", type=int, default=DEFAULTS["lines"], help=f"行数上限/行(默认 {DEFAULTS['lines']})")
    ap.add_argument("--risk", type=int, default=DEFAULTS["risk"], help=f"风险上限/分(默认 {DEFAULTS['risk']})")
    ap.add_argument("--note", default="", help="这次自改想干什么(一句话,记进账)")
    ap.add_argument("--spend", action="store_true", help="给「命令」档 +1(动手前记一笔)")
    ap.add_argument("--check", nargs="?", const="*", metavar="NAME", help="量当前花费并逐档裁决")
    ap.add_argument("--stop", metavar="理由", help="主动收尾:记下停手理由,结清这本账")
    ap.add_argument("--json", action="store_true", help="导出机读:当前账与逐档花费")
    args = ap.parse_args(argv)

    if args.open:
        if not args.name:
            ap.error("--open 立账必须带 --name(预算代号)")
        b = open_budget(args.name, args.minutes, args.cmds, args.files,
                        args.lines, args.risk, args.note)
        print(f"💰 已立账「{b.name}」 基线 {b.base_commit[:8] or '(无 HEAD)'}")
        print(f"   上限：⏱️{b.max_minutes:g}分 · 🔧{b.max_cmds}条 · 📝{b.max_files}个 · ➕{b.max_lines}行 · ⚠️{b.max_risk}分")
        if b.note:
            print(f"   📝 {b.note}")
        print(f"   🪜 动手吧——随时 `python budget.py --check {b.name}` 看还剩多少额度。")
        return

    if args.spend:
        b = spend_cmd(args.name)
        if b is None:
            print("💰 没有可记账的预算(先 --open 立一本)。")
            sys.exit(1)
        print(f"💰「{b.name}」命令档 +1 → 已记 {b.cmds_spent}/{b.max_cmds} 条。")
        return

    if args.stop is not None:
        b = stop_budget(args.name, args.stop)
        if b is None:
            print("💰 没有可收尾的预算(先 --open 立一本)。")
            sys.exit(1)
        v = evaluate(b)
        print(f"💰 已结清「{b.name}」 停手理由：{args.stop}")
        _print_verdict(v)
        return

    # 默认行为 == --check:量当前花费并裁决。
    name = None if (args.check in (None, "*")) else args.check
    if name:
        b = _get(name)
        verdicts = [evaluate(b)] if b else []
    else:
        verdicts = [evaluate(b) for b in _load()]

    if args.json:
        print(json.dumps([v.to_meta() for v in verdicts], ensure_ascii=False, indent=2))
        sys.exit(0)

    if not verdicts:
        print("💰 还没立过预算。开工前先 `python budget.py --open --name <题> [--minutes ...]`,")
        print("   把「这次自改我允许自己花多少」立成硬边界——会节制,才是真自主。")
        sys.exit(0)

    for v in verdicts:
        _print_verdict(v)
    # 有在开的预算超额 → 退出码 1,提醒循环刹车。
    sys.exit(1 if any(v.over_budget and v.budget.is_open for v in verdicts) else 0)


if __name__ == "__main__":
    main()
