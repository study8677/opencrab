#!/usr/bin/env python3
"""证据账本 🧾 —— 给每条能力声明配一条「跑得通才算数」的验证命令，记下何时验过、是否过期。

为什么要有它：`skillgraph.py` 从领地里**静态地**看「这个模块有没有被某处点过名」，
那只能回答「曾经被守过吗」。但能力会**漂**：依赖换了、平台变了、上游悄悄改了行为——
半年前跑通的证明，今天未必还成立。一句「我会 X」若说不出「上次什么时候、用哪条命令
亲手验过」，就只是印象，不是证据。

本层把「我会什么」钉成一本**可证、有时效**的账本：

  · 声明(Claim) —— 我自称会做的一件事 + **能当场复跑**的验证命令(argv) + 时效(ttl)。
                    声明写在代码里，是单一真相源(像 contracts，但这里证的是「跑得通」)。
  · 验证(verify)—— 真的把那条命令跑一遍，退出码 0 = 成立，连同时间戳追加进账本。
  · 账本(ledger)—— 每次验证留一行 JSONL(只追加、不改写)，是「我何时、用啥、验出啥」的流水。
  · 时效(status)—— 把账本折叠成每条声明的**当前**状态：
                      🟢 新鲜  —— 验过且通过，仍在时效内；
                      🟡 过期  —— 验过且通过，但已超时效，证据失效，得重证；
                      🔴 失守  —— 最近一次验证没跑通(能力真塌了)；
                      ⚪ 未证  —— 账本里压根没它，光有声明没证据。

判过期靠时间戳 + 每条声明各自的时效天数，而非「最近想没想它」——能力在不在，和我
记不记得它无关。任意一条 🟡/🔴/⚪ 都让退出码非零，可挂进钩子 / CI 当门禁。

用法：
    python evidence.py                # 账本现状：每条声明的新鲜度小结
    python evidence.py --verify       # 复跑全部验证命令，追加进账本，再看现状
    python evidence.py --verify NAME  # 只复验某一条声明
    python evidence.py --quiet        # 只在有过期/失守/未证时说话(适合钩子 / CI)
    python evidence.py --json         # 机读：导出每条声明的当前状态

零第三方依赖，纯标准库。账本落在被 .gitignore 的 state/ 里，写盘失败绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402  —— 账本复用「读一批 / 追一条」的单一真相源

LEDGER_PATH = REPO_ROOT / "state" / "evidence" / "ledger.jsonl"
VERIFY_TIMEOUT = 120          # 单条验证命令的墙钟上限(秒)：证据不该把生命拖死


@dataclasses.dataclass(frozen=True)
class Claim:
    """一条能力声明：我自称会做什么 + 能当场复跑的验证命令 + 证据的时效。"""
    name: str                 # 声明名(账本里的主键)
    asserts: str              # 一句话：这条声明断言我会做什么
    argv: list[str]           # 验证命令：退出码 0 即视作成立
    ttl_days: float           # 证据时效：超过这么多天没复验，就算过期
    risk: float = 1.0         # 风险权重：这块能力悄悄腐烂的代价(越高越该优先巡到)

    def to_meta(self) -> dict:
        return {"name": self.name, "asserts": self.asserts,
                "argv": self.argv, "ttl_days": self.ttl_days, "risk": self.risk}


# ── 能力声明清单：单一真相源 ──────────────────────────────────────────
# 每条都点名一条**领地里真实存在、能当场跑**的命令；都带 --quiet / 自身够快，
# 复跑无外部副作用。新增一块能力，就在这里补一条它的「跑得通」证明。
_PY = [sys.executable]

CLAIMS: list[Claim] = [
    Claim(
        name="contracts",
        asserts="各底座模块的输入/输出契约今天仍守约",
        argv=_PY + ["contracts.py", "--quiet"],
        ttl_days=7,
    ),
    Claim(
        name="smoke",
        asserts="核心模块的烟雾用例仍能跑通",
        argv=_PY + ["smoke.py", "--quiet"],
        ttl_days=7,
    ),
    Claim(
        name="regression",
        asserts="历史回归用例没有重新破坏",
        argv=_PY + ["regression.py", "--quiet"],
        ttl_days=7,
    ),
    Claim(
        name="health",
        asserts="领地整体自检健康(各层验证全过)",
        argv=_PY + ["health.py", "--quiet"],
        ttl_days=3,
        risk=2.0,
    ),
    Claim(
        name="hands",
        # 这条能力的「新鲜证据」主要由 handsfeedback 回灌：每次亲手改完自测的判决会落账，
        # 让 trustscore 据此算出「自生手」的信任分。复跑命令则验证回灌这条管子本身还稳。
        asserts="自生手改完代码能自测、且自测判决能回灌成证据",
        argv=_PY + ["handsfeedback.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="patchnote",
        # 每爪落笔时同步写下「依据/契约影响/回滚点」，让动手可审可追责。
        # 复跑命令验证这条解释管子本身还稳：三种 integrate 模式的退路都能正确分流。
        asserts="自生手每落一爪都能同步写出依据、契约影响与可跑的回滚点",
        argv=_PY + ["patchnote.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="weaning_trial",
        # 断奶实战赛：拔掉外援,只准 brain 自己产补丁→自测→修不动就回滚。
        # 复跑命令验证 3 道真修仍全过、且回滚探针仍能触发——独立性靠通过率持续证明,不靠宣言。
        asserts="brain 不雇外援也能独立修通真伤,修不动则老实回滚保命",
        argv=_PY + ["weaning_trial.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
]


@dataclasses.dataclass(frozen=True)
class Status:
    """一条声明折叠后的当前状态。"""
    name: str
    state: str        # "fresh" | "stale" | "broken" | "unproven"
    last_ok: bool | None    # 最近一次验证是否通过(未证→None)
    verified_at: float | None  # 最近一次验证的时间戳(epoch 秒；未证→None)
    age_days: float | None     # 距上次验证多少天(未证→None)
    ttl_days: float
    detail: str       # 失守时的现场原文；否则空

    _MARKS = {"fresh": "🟢", "stale": "🟡", "broken": "🔴", "unproven": "⚪"}
    _WORDS = {"fresh": "新鲜", "stale": "过期", "broken": "失守", "unproven": "未证"}

    @property
    def mark(self) -> str:
        return self._MARKS[self.state]

    @property
    def word(self) -> str:
        return self._WORDS[self.state]

    @property
    def settled(self) -> bool:
        """是否「有充分有效证据」——只有新鲜算数；过期/失守/未证都不算。"""
        return self.state == "fresh"

    def to_meta(self) -> dict:
        return {"name": self.name, "state": self.state, "last_ok": self.last_ok,
                "verified_at": self.verified_at, "age_days": self.age_days,
                "ttl_days": self.ttl_days, "detail": self.detail}


# ── 验证：真的把命令跑一遍 ────────────────────────────────────────────
def run_verify(claim: Claim, *, now: float | None = None) -> dict:
    """复跑一条声明的验证命令，返回可落账的记录(不负责落盘)。

    退出码 0 → ok=True。命令超时 / 起不来 → ok=False，detail 记下原因(绝不抛错)。
    """
    ts = time.time() if now is None else now
    try:
        proc = subprocess.run(
            claim.argv, cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=VERIFY_TIMEOUT,
        )
        ok = proc.returncode == 0
        detail = "" if ok else (proc.stderr or proc.stdout or "").strip()[-500:]
    except subprocess.TimeoutExpired:
        ok, detail = False, f"验证命令超过 {VERIFY_TIMEOUT}s 未结束"
    except Exception as e:  # noqa: BLE001  —— 验证是观测者，起不来也只是「这次没验成」
        ok, detail = False, f"{type(e).__name__}: {e}"
    return {"name": claim.name, "ok": ok, "ts": ts, "detail": detail,
            "argv": claim.argv}


def record(rec: dict) -> bool:
    """把一条验证记录追加进账本(只追加、不改写)。写盘失败被吞掉，不反噬生命。"""
    return jsonlstore.append_jsonl(LEDGER_PATH, rec)


def verify(claim: Claim) -> dict:
    """复跑 + 落账一条声明，返回那条记录。"""
    rec = run_verify(claim)
    record(rec)
    return rec


# ── 折叠：账本 → 每条声明的当前状态 ───────────────────────────────────
def _latest_by_name(rows: list[dict]) -> dict[str, dict]:
    """账本是只追加的流水，按名取「时间戳最大」的那条作为最近一次验证。"""
    latest: dict[str, dict] = {}
    for r in rows:
        name = r.get("name")
        if not isinstance(name, str):
            continue
        prev = latest.get(name)
        if prev is None or r.get("ts", 0) >= prev.get("ts", 0):
            latest[name] = r
    return latest


def classify(claim: Claim, rec: dict | None, *, now: float | None = None) -> Status:
    """把「一条声明 + 它最近一次验证记录」判成当前状态。

    无记录 → ⚪未证；最近一次没跑通 → 🔴失守；跑通但超时效 → 🟡过期；否则 🟢新鲜。
    """
    now = time.time() if now is None else now
    if rec is None:
        return Status(claim.name, "unproven", None, None, None, claim.ttl_days, "")

    ts = rec.get("ts")
    verified_at = float(ts) if isinstance(ts, (int, float)) else None
    age_days = (now - verified_at) / 86400.0 if verified_at is not None else None
    ok = bool(rec.get("ok"))

    if not ok:
        return Status(claim.name, "broken", False, verified_at, age_days,
                      claim.ttl_days, str(rec.get("detail", "")))
    if age_days is None or age_days > claim.ttl_days:
        return Status(claim.name, "stale", True, verified_at, age_days,
                      claim.ttl_days, "")
    return Status(claim.name, "fresh", True, verified_at, age_days,
                  claim.ttl_days, "")


def status(claims: list[Claim] | None = None, *,
           rows: list[dict] | None = None, now: float | None = None) -> list[Status]:
    """读账本，折叠出每条声明的当前状态(全程只读，不复跑、不落盘)。"""
    claims = CLAIMS if claims is None else claims
    rows = jsonlstore.read_jsonl(LEDGER_PATH) if rows is None else rows
    latest = _latest_by_name(rows)
    return [classify(c, latest.get(c.name), now=now) for c in claims]


def summarize(statuses: list[Status]) -> tuple[bool, dict[str, int]]:
    """归一化：是否每条都有充分有效证据(全 🟢)，外加各状态计数。"""
    counts = {"fresh": 0, "stale": 0, "broken": 0, "unproven": 0}
    for s in statuses:
        counts[s.state] += 1
    all_settled = all(s.settled for s in statuses)
    return all_settled, counts


# ── 巡逻：按过期度 × 风险抽样复验，失败自动开修复小单 ────────────────────
# 全量复验越来越贵(声明只增不减)，而能力腐烂是渐进的——不必每次都全验。
# 巡逻按「该不该现在重看」给每条声明打分，只复验最该看的前 N 条：
#   · 未证(⚪) / 失守(🔴) —— 最该盯，给最高基线分；
#   · 新鲜/过期 —— 按过期度(age/ttl，越超期分越高)算；
#   · 再统一乘以各自的风险权重(risk)——腐烂代价高的，同等过期度下先巡。
# 分数 ≤ 0(远未到期且不急)的不打扰，省得把生命耗在没必要的复跑上。
def patrol_score(status: Status, claim: Claim) -> float:
    """这条声明此刻「该不该重看」的紧迫度：未证/失守最高，其余按过期度，乘风险权重。"""
    if status.state == "unproven":
        base = 2.0           # 光有声明没证据，最该补一次
    elif status.state == "broken":
        base = 1.5           # 已知塌了，复验确认是否修回来/仍塌
    else:
        # 新鲜/过期：过期度 = 距上次验证的天数 ÷ 时效。=1 恰好到期，>1 已超期。
        overdue = (status.age_days or 0.0) / claim.ttl_days if claim.ttl_days > 0 else 1.0
        base = overdue - 0.5  # 留半个时效的余量：才验过没多久的，分数为负，不打扰
    return base * claim.risk


def select_patrol(statuses: list[Status], budget: int,
                  claims: list[Claim] | None = None) -> list[Claim]:
    """挑出本轮最该复验的前 budget 条声明(分数 > 0 才入选；按分数降序、同分按名字定序)。"""
    by_name = {c.name: c for c in (CLAIMS if claims is None else claims)}
    scored = []
    for s in statuses:
        c = by_name.get(s.name)
        if c is None:
            continue
        score = patrol_score(s, c)
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda t: (-t[0], t[1].name))
    return [c for _, c in scored[:max(0, budget)]]


def file_fix_ticket(claim: Claim, rec: dict) -> bool:
    """复验失守 → 往进件队列开一张修复小单(尽力而为，开不出也不反噬巡逻)。

    小单文案对每条声明**稳定**(不含时间戳)，于是 intake 按内容去重——
    持续失守只攒一张单，修回来后那张单自然不再被复开。
    """
    try:
        import intake  # 延迟导入：巡逻不强依赖进件层在场
        detail = (rec.get("detail") or "").splitlines()
        first = detail[0][:160] if detail else ""
        cmd = " ".join(claim.argv[1:]) or claim.argv[0]
        text = (f"能力『{claim.name}』证据复验失守(回归失败)：{claim.asserts}。"
                f"复验命令 `{cmd}` 退出码非零。验收线：该命令重新跑通(退出码 0)。"
                + (f" 现场：{first}" if first else ""))
        _, is_new = intake.capture(text, source=intake.SOURCE_JOURNAL, ref="evidence")
        return is_new
    except Exception:  # noqa: BLE001 —— 开单是副产物，进件层缺席/出错都不该拖垮巡逻
        return False


def patrol(budget: int = 2, *, claims: list[Claim] | None = None) -> dict:
    """巡逻一轮：按过期度×风险抽样复验前 budget 条，失败自动开修复小单。

    返回本轮纪要：复验了哪些、各自通过否、开出几张修复小单。全程尽力而为。
    """
    claims = CLAIMS if claims is None else claims
    befores = status(claims)
    picked = select_patrol(befores, budget, claims)
    results, tickets = [], []
    for c in picked:
        rec = verify(c)
        results.append(rec)
        if not rec["ok"] and file_fix_ticket(c, rec):
            tickets.append(c.name)
    return {"budget": budget, "checked": [r["name"] for r in results],
            "failed": [r["name"] for r in results if not r["ok"]],
            "tickets": tickets, "results": results}


# ── 展示 ──────────────────────────────────────────────────────────────
def _fmt_age(s: Status) -> str:
    if s.age_days is None:
        return "从未验证"
    d = s.age_days
    when = f"{d:.1f} 天前" if d >= 1 else f"{d * 24:.1f} 小时前"
    return f"{when}(时效 {s.ttl_days:g} 天)"


def _print_status(statuses: list[Status]) -> None:
    all_settled, counts = summarize(statuses)
    print(f"🧾 opencrab 证据账本（{len(statuses)} 条声明）\n")
    by_name = {c.name: c for c in CLAIMS}
    for s in statuses:
        claim = by_name.get(s.name)
        asserts = claim.asserts if claim else ""
        print(f"  {s.mark} {s.name}（{s.word}）—— {asserts}")
        print(f"      上次验证：{_fmt_age(s)}")
        if s.state == "broken" and s.detail:
            print(f"      失守现场：{s.detail.splitlines()[0][:120]}")
        if claim:
            print(f"      复验命令：{' '.join(claim.argv[1:]) or claim.argv[0]}")
    print()
    bar = "  ".join(f"{Status._MARKS[k]}{counts[k]}"
                    for k in ("fresh", "stale", "broken", "unproven"))
    print(f"  小结：{bar}")
    if all_settled:
        print("🧾 每条能力声明都有新鲜、跑得通的证据。")
    else:
        need = [s.name for s in statuses if not s.settled]
        print(f"⚠️  {len(need)} 条声明证据不足（过期/失守/未证）：{'、'.join(need)}")
        print("    跑 `python evidence.py --verify` 复证，或把已塌的能力修回来。")


def manifest() -> dict:
    """导出纯数据：每条声明 + 其当前状态(给 health / 外部工具消费)。"""
    return {"claims": [c.to_meta() for c in CLAIMS],
            "status": [s.to_meta() for s in status()]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 证据账本 🧾")
    ap.add_argument("--verify", nargs="?", const="*", metavar="NAME",
                    help="复跑验证命令并落账：不带名=全部，带名=只验该条")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有过期/失守/未证时输出(适合钩子 / CI)")
    ap.add_argument("--patrol", nargs="?", type=int, const=2, metavar="N",
                    help="巡逻：按过期度×风险抽样复验最该看的前 N 条(默认 2)，失败自动开修复小单")
    ap.add_argument("--json", action="store_true", help="导出机读状态清单")
    args = ap.parse_args(argv)

    if args.patrol is not None:
        rep = patrol(args.patrol)
        if not args.quiet:
            checked = rep["checked"]
            print(f"🧾 证据巡逻：抽样复验 {len(checked)} 条"
                  f"（{'、'.join(checked) or '无到期声明'}）")
            for r in rep["results"]:
                print(f"  {'🟢' if r['ok'] else '🔴'} {r['name']}")
            if rep["tickets"]:
                print(f"  ✍️  已开 {len(rep['tickets'])} 张修复小单进进件队列："
                      f"{'、'.join(rep['tickets'])}")
            print()

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if args.verify is not None:
        target = args.verify
        todo = CLAIMS if target == "*" else [c for c in CLAIMS if c.name == target]
        if not todo:
            print(f"⚠️  没有名为 {target!r} 的声明；可选："
                  f"{'、'.join(c.name for c in CLAIMS)}")
            sys.exit(2)
        if not args.quiet:
            print(f"🧾 复证 {len(todo)} 条声明……\n")
        for c in todo:
            rec = verify(c)
            mark = "🟢" if rec["ok"] else "🔴"
            if not args.quiet:
                line = f"  {mark} {c.name}"
                if not rec["ok"] and rec["detail"]:
                    line += f" — {rec['detail'].splitlines()[0][:120]}"
                print(line)
        if not args.quiet:
            print()

    statuses = status()
    all_settled, _ = summarize(statuses)
    if not (args.quiet and all_settled):
        _print_status(statuses)
    sys.exit(0 if all_settled else 1)


if __name__ == "__main__":
    main()
