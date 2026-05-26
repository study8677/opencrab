#!/usr/bin/env python3
"""预注册假设台账 🔬 —— 每次自改前先押下一条「能被否定」的假设，连同最小验证与停止条件。

为什么要有它：`evidence.py` 证「我会的能力今天还跑得通」，`value.py`/`impact.py` 量
「这次改动值不值」——但它们都在**改完之后**回看。回看有个致命漏洞：结果出来了，人
(和我)总能给任何结果编一套自圆其说的解释。改好了说「果然如我所料」，改砸了说「本来
也没指望这个」。没有改动**之前**白纸黑字写下的预测，进步就永远不可证伪——堆再多模块，
也只是在事后追认既成事实。

本层把这件事反过来：**先押注，后揭晓**。每次自改前，先注册一条假设：

  · 断言(claim) —— 一句**可证伪**的话：这次改动会带来什么可观测的改进。
  · 验证(argv) —— 一条**当场能跑、会自己结束**的最小命令，退出码 0 = 预测成立。
                   越小越好：验证若比改动本身还贵，就不是真验证。
  · 预测(predict)—— 一句话写死「我赌会看到什么」，留给未来的自己原样对账。
  · 停止条件 —— 押注必须自带「认输线」，二选一或都给：
                   · by_days  —— 过这么多天还没确证，自动判否(refuted)；
                   · max_checks —— 验证跑这么多次还没确证，自动判否。

没有验证命令、或没有任何停止条件的「假设」一律**拒绝注册**——一条永远不会输的断言
不是假设，是信仰。注册这道门就是在逼自己：要改，先说清楚怎样才算改错了。

注册之后，每次 `--check` 真的把验证命令跑一遍并落账：
  · 跑通(退出码 0) → 🟢 确证(confirmed)，预测兑现，假设关闭；
  · 没跑通、但停止条件还没到 → 🟡 待定(open)，可以接着改、再验；
  · 没跑通、且停止条件已到(超期 / 验够次数) → 🔴 证伪(refuted)，按自己定的认输线认输。

🔴 证伪不是失败，是台账最值钱的产出：一条被诚实否定的假设，比十条没人敢验的断言更接近真相。
任何 🔴 证伪、或 🟡 待定但已超期(欠一个了断)都让退出码非零，可挂进钩子 / CI 当门禁。

用法：
    python hypothesis.py                       # 台账现状：每条假设的当前裁决
    python hypothesis.py --register NAME \\     # 改之前先押一条(缺验证/停止条件会被拒)
        --claim "..." --verify "python smoke.py --quiet" \\
        --predict "烟雾用例仍全过" --by-days 1 --max-checks 3
    python hypothesis.py --check NAME          # 跑验证、落裁决(不带 NAME=验全部待定的)
    python hypothesis.py --close NAME          # 主动撤回一条仍待定的假设(放弃验证)
    python hypothesis.py --quiet               # 只在有证伪/超期未决时说话(适合钩子 / CI)
    python hypothesis.py --json                # 机读：导出每条假设的当前裁决
    python hypothesis.py --selftest            # 自检折叠/裁决逻辑(给 smoke/contracts 当靶子)

零第三方依赖，纯标准库。台账落在被 .gitignore 的 state/ 里，写盘失败绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import shlex
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402  —— 台账复用「读一批 / 追一条」的单一真相源

LEDGER_PATH = REPO_ROOT / "state" / "hypothesis" / "ledger.jsonl"
CHECK_TIMEOUT = 120          # 单条验证命令的墙钟上限(秒)：最小验证不该把生命拖死

EV_REGISTER = "register"
EV_CHECK = "check"
EV_CLOSE = "close"           # 主动撤回(放弃验证，不算证伪也不算确证)


# ── 注册：押注前的可证伪性闸门 ────────────────────────────────────────
def falsifiable(argv: list[str], by_days: float, max_checks: int) -> tuple[bool, str]:
    """这条假设押得「能不能被否定」？不能被否定的就不让进台账。

    要求：① 有一条非空验证命令(否则无从验真伪)；② 至少一个停止条件
    (by_days>0 或 max_checks>0，否则它能永远赖在待定、永远不认输)。
    """
    if not argv:
        return False, "缺最小验证命令(--verify)：没法验的断言不是假设"
    if not (by_days > 0 or max_checks > 0):
        return False, "缺停止条件(--by-days / --max-checks)：永不认输的断言不是假设"
    return True, ""


def register(name: str, *, claim: str, argv: list[str], predict: str = "",
             by_days: float = 0.0, max_checks: int = 0,
             now: float | None = None) -> tuple[bool, str]:
    """改之前押下一条假设(通过可证伪性闸门才落账)。返回 (是否注册成功, 说明)。

    同名再注册=用新的覆盖旧的(新 register 事件的时间戳更大，折叠时只认最新那条)。
    """
    ok, reason = falsifiable(argv, by_days, max_checks)
    if not ok:
        return False, reason
    rec = {"name": name, "event": EV_REGISTER, "ts": time.time() if now is None else now,
           "claim": claim, "argv": argv, "predict": predict,
           "by_days": float(by_days), "max_checks": int(max_checks)}
    jsonlstore.append_jsonl(LEDGER_PATH, rec)
    return True, "已注册"


# ── 验证：真的把命令跑一遍 ────────────────────────────────────────────
def run_check(argv: list[str], *, now: float | None = None) -> dict:
    """跑一条假设的验证命令，返回可落账的记录(不负责落盘)。

    退出码 0 → ok=True(预测兑现)。超时 / 起不来 → ok=False，detail 记原因(绝不抛错)。
    """
    ts = time.time() if now is None else now
    try:
        proc = subprocess.run(argv, cwd=str(REPO_ROOT),
                              capture_output=True, text=True, timeout=CHECK_TIMEOUT)
        ok = proc.returncode == 0
        detail = "" if ok else (proc.stderr or proc.stdout or "").strip()[-500:]
    except subprocess.TimeoutExpired:
        ok, detail = False, f"验证命令超过 {CHECK_TIMEOUT}s 未结束"
    except Exception as e:  # noqa: BLE001 —— 验证是观测者，起不来也只是「这次没验成」
        ok, detail = False, f"{type(e).__name__}: {e}"
    return {"event": EV_CHECK, "ok": ok, "ts": ts, "detail": detail}


# ── 折叠：台账流水 → 每条假设的当前裁决 ──────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Verdict:
    """一条假设折叠后的当前裁决。"""
    name: str
    state: str                  # "confirmed" | "refuted" | "open" | "withdrawn"
    claim: str
    predict: str
    argv: list[str]
    by_days: float
    max_checks: int
    registered_at: float
    checks: int                 # 注册以来验证跑了几次
    last_ok: bool | None        # 最近一次验证是否通过(没验过→None)
    age_days: float             # 注册至今多少天
    detail: str                 # 证伪/最近失败的现场原文；否则空

    _MARKS = {"confirmed": "🟢", "refuted": "🔴", "open": "🟡", "withdrawn": "⚪"}
    _WORDS = {"confirmed": "确证", "refuted": "证伪", "open": "待定", "withdrawn": "撤回"}

    @property
    def mark(self) -> str:
        return self._MARKS[self.state]

    @property
    def word(self) -> str:
        return self._WORDS[self.state]

    @property
    def overdue(self) -> bool:
        """待定但停止条件已到——欠一个了断(下次 --check 就会被判否)。"""
        return self.state == "open" and self._stop_reached()

    def _stop_reached(self) -> bool:
        by_time = self.by_days > 0 and self.age_days > self.by_days
        by_count = self.max_checks > 0 and self.checks >= self.max_checks
        return by_time or by_count

    @property
    def needs_attention(self) -> bool:
        """要不要门禁拦下：已证伪(该记取)、或待定超期(欠了断)。"""
        return self.state == "refuted" or self.overdue

    def to_meta(self) -> dict:
        return {"name": self.name, "state": self.state, "claim": self.claim,
                "predict": self.predict, "checks": self.checks,
                "last_ok": self.last_ok, "age_days": round(self.age_days, 3),
                "by_days": self.by_days, "max_checks": self.max_checks,
                "detail": self.detail}


def _fold_one(reg: dict, checks: list[dict], *, now: float) -> Verdict:
    """把「一条注册 + 它之后的所有验证记录」折叠成当前裁决。

    裁决规则(先验证、后揭晓的核心)：
      · 任意一次验证跑通 → 确证(confirmed)，预测兑现，假设关闭；
      · 否则若停止条件已到(超期 / 验够次数) → 证伪(refuted)，按自己定的认输线认输；
      · 否则 → 待定(open)，还在押注窗口内，可接着改、再验。
    """
    name = reg.get("name", "")
    argv = reg.get("argv") or []
    by_days = float(reg.get("by_days", 0) or 0)
    max_checks = int(reg.get("max_checks", 0) or 0)
    reg_ts = float(reg.get("ts", now))
    age_days = max(0.0, (now - reg_ts) / 86400.0)

    n = len(checks)
    last_ok = bool(checks[-1].get("ok")) if checks else None
    confirmed = any(c.get("ok") for c in checks)
    last_detail = next((c.get("detail", "") for c in reversed(checks)
                        if not c.get("ok")), "")

    common = dict(name=name, claim=reg.get("claim", ""), predict=reg.get("predict", ""),
                  argv=argv, by_days=by_days, max_checks=max_checks,
                  registered_at=reg_ts, checks=n, last_ok=last_ok, age_days=age_days)

    if confirmed:
        return Verdict(state="confirmed", detail="", **common)

    by_time = by_days > 0 and age_days > by_days
    by_count = max_checks > 0 and n >= max_checks
    if by_time or by_count:
        why = []
        if by_time:
            why.append(f"已过 {age_days:.1f} 天(限 {by_days:g} 天)")
        if by_count:
            why.append(f"已验 {n} 次(限 {max_checks} 次)")
        reason = "；".join(why)
        return Verdict(state="refuted",
                       detail=(last_detail or f"停止条件已到：{reason}"), **common)

    return Verdict(state="open", detail=last_detail, **common)


def verdicts(*, rows: list[dict] | None = None, now: float | None = None) -> list[Verdict]:
    """读台账，折叠出每条假设的当前裁决(全程只读，不复跑、不落盘)。

    台账是只追加流水：按名取**最新**的 register 作为该假设的定义(同名覆盖)，
    再收集那条 register 之后、且未被更晚的 close/register 截断的验证记录。
    """
    now = time.time() if now is None else now
    rows = jsonlstore.read_jsonl(LEDGER_PATH) if rows is None else rows

    # 先定位每个名字「最新一次注册」的时间戳——它界定了当前这条假设的起点。
    latest_reg: dict[str, dict] = {}
    for r in rows:
        if r.get("event") != EV_REGISTER:
            continue
        name = r.get("name")
        if not isinstance(name, str):
            continue
        prev = latest_reg.get(name)
        if prev is None or r.get("ts", 0) >= prev.get("ts", 0):
            latest_reg[name] = r

    out: list[Verdict] = []
    for name, reg in latest_reg.items():
        reg_ts = float(reg.get("ts", 0))
        # 这条假设起点之后的事件：验证累加；遇到 close 则判为主动撤回。
        withdrawn = False
        checks: list[dict] = []
        for r in rows:
            if r.get("name") != name or r.get("ts", 0) < reg_ts:
                continue
            ev = r.get("event")
            if ev == EV_CHECK:
                checks.append(r)
            elif ev == EV_CLOSE and r.get("ts", 0) >= reg_ts:
                withdrawn = True
        if withdrawn and not any(c.get("ok") for c in checks):
            out.append(_fold_one(reg, checks, now=now).__class__(
                **{**_fold_one(reg, checks, now=now).to_meta_full(), "state": "withdrawn"}
            ) if False else dataclasses.replace(_fold_one(reg, checks, now=now),
                                                state="withdrawn"))
        else:
            out.append(_fold_one(reg, checks, now=now))
    out.sort(key=lambda v: (v.state != "refuted", not v.overdue, -v.registered_at))
    return out


def check(name: str, *, now: float | None = None) -> dict | None:
    """跑某条待定假设的验证命令并落账，返回那条记录(没这条/已关闭→None)。"""
    current = {v.name: v for v in verdicts(now=now)}
    v = current.get(name)
    if v is None:
        return None
    rec = run_check(v.argv, now=now)
    rec["name"] = name
    jsonlstore.append_jsonl(LEDGER_PATH, rec)
    return rec


def close(name: str, *, now: float | None = None) -> bool:
    """主动撤回一条仍待定的假设(放弃验证)。已确证/已证伪的不动。"""
    current = {v.name: v for v in verdicts(now=now)}
    v = current.get(name)
    if v is None or v.state != "open":
        return False
    return jsonlstore.append_jsonl(
        LEDGER_PATH,
        {"name": name, "event": EV_CLOSE, "ts": time.time() if now is None else now})


# ── 归一化 & 展示 ─────────────────────────────────────────────────────
def summarize(vs: list[Verdict]) -> tuple[bool, dict[str, int], int]:
    """是否「无需门禁介入」(无证伪、无超期未决)，外加各状态计数与超期数。"""
    counts = {"confirmed": 0, "refuted": 0, "open": 0, "withdrawn": 0}
    overdue = 0
    for v in vs:
        counts[v.state] += 1
        if v.overdue:
            overdue += 1
    clean = not any(v.needs_attention for v in vs)
    return clean, counts, overdue


def _fmt_age(d: float) -> str:
    return f"{d:.1f} 天" if d >= 1 else f"{d * 24:.1f} 小时"


def _print(vs: list[Verdict]) -> None:
    clean, counts, overdue = summarize(vs)
    print(f"🔬 opencrab 预注册假设台账（{len(vs)} 条）\n")
    if not vs:
        print("  （台账为空——下次自改前，先押一条能被否定的假设：")
        print("   python hypothesis.py --register NAME --claim ... --verify ... --by-days 1）")
        return
    for v in vs:
        flag = "  ⏰超期未决" if v.overdue else ""
        print(f"  {v.mark} {v.name}（{v.word}{flag}）—— {v.claim}")
        if v.predict:
            print(f"      预测：{v.predict}")
        print(f"      验证：{' '.join(shlex.quote(a) for a in v.argv[1:]) or (v.argv[0] if v.argv else '—')}"
              f"  ·  已验 {v.checks} 次 / 注册 {_fmt_age(v.age_days)}前")
        stop = []
        if v.by_days > 0:
            stop.append(f"{v.by_days:g} 天")
        if v.max_checks > 0:
            stop.append(f"{v.max_checks} 次")
        if stop:
            print(f"      认输线：{ ' 或 '.join(stop) }")
        if v.state == "refuted" and v.detail:
            print(f"      认输现场：{v.detail.splitlines()[0][:120]}")
    print()
    bar = "  ".join(f"{Verdict._MARKS[k]}{counts[k]}"
                    for k in ("confirmed", "refuted", "open", "withdrawn"))
    print(f"  小结：{bar}")
    if clean:
        print("🔬 没有待记取的证伪，也没有欠了断的假设。")
    else:
        if counts["refuted"]:
            print(f"🔴 {counts['refuted']} 条假设被证伪——别绕过，把它当作这次方向上最硬的反馈。")
        if overdue:
            print(f"⏰ {overdue} 条待定假设已超期：跑 `python hypothesis.py --check NAME` 给个了断。")


def manifest() -> dict:
    """导出纯数据：每条假设的当前裁决(给 health / 外部工具消费)。"""
    return {"verdicts": [v.to_meta() for v in verdicts()]}


# ── 自检：不依赖磁盘，纯逻辑校验折叠/裁决(给 smoke/contracts 当靶子) ───────
def _selftest() -> bool:
    """用合成事件喂折叠逻辑，断言裁决规则正确。退出码 0=逻辑无恙。"""
    T0 = 1_000_000.0
    DAY = 86400.0

    # ① 可证伪性闸门：没验证命令 / 没停止条件 → 拒。
    assert not falsifiable([], 1, 0)[0]
    assert not falsifiable(["x"], 0, 0)[0]
    assert falsifiable(["x"], 1, 0)[0]
    assert falsifiable(["x"], 0, 3)[0]

    def reg(name, **kw):
        return {"name": name, "event": EV_REGISTER, "ts": T0,
                "claim": "c", "argv": ["py", "x"], "predict": "p", **kw}

    def chk(name, ok, ts):
        return {"name": name, "event": EV_CHECK, "ok": ok, "ts": ts, "detail": "" if ok else "boom"}

    # ② 跑通一次即确证。
    rows = [reg("a", by_days=1), chk("a", False, T0 + 10), chk("a", True, T0 + 20)]
    va = {v.name: v for v in verdicts(rows=rows, now=T0 + 30)}["a"]
    assert va.state == "confirmed", va.state

    # ③ 超期且从未跑通 → 证伪。
    rows = [reg("b", by_days=1), chk("b", False, T0 + 10)]
    vb = {v.name: v for v in verdicts(rows=rows, now=T0 + 2 * DAY)}["b"]
    assert vb.state == "refuted", vb.state
    assert "boom" in vb.detail

    # ④ 验够次数且未通过 → 证伪(即便还没超期)。
    rows = [reg("c", max_checks=2, by_days=99),
            chk("c", False, T0 + 1), chk("c", False, T0 + 2)]
    vc = {v.name: v for v in verdicts(rows=rows, now=T0 + 3)}["c"]
    assert vc.state == "refuted", vc.state

    # ⑤ 窗口内、未通过 → 待定；且未超期。
    rows = [reg("d", by_days=5, max_checks=5), chk("d", False, T0 + 10)]
    vd = {v.name: v for v in verdicts(rows=rows, now=T0 + DAY)}["d"]
    assert vd.state == "open" and not vd.overdue, (vd.state, vd.overdue)

    # ⑥ 待定但停止条件已到 → 仍 open 但标记超期(欠了断)。
    rows = [reg("e", by_days=1)]
    ve = {v.name: v for v in verdicts(rows=rows, now=T0 + 2 * DAY)}["e"]
    # 没有任何验证记录、超期 → 折叠判为证伪(by_time)，需要门禁介入。
    assert ve.needs_attention, ve.state

    # ⑦ 同名再注册覆盖旧的:旧的已证伪,新的应回到待定。
    rows = [reg("f", by_days=1), chk("f", False, T0 + 10),
            {**reg("f", by_days=5), "ts": T0 + 3 * DAY}]
    vf = {v.name: v for v in verdicts(rows=rows, now=T0 + 3 * DAY + 10)}["f"]
    assert vf.state == "open", vf.state
    assert vf.checks == 0, vf.checks  # 新注册之后还没验过

    # ⑧ 主动撤回:待定 + close → withdrawn,不算证伪不需门禁。
    rows = [reg("g", by_days=5), {"name": "g", "event": EV_CLOSE, "ts": T0 + 10}]
    vg = {v.name: v for v in verdicts(rows=rows, now=T0 + DAY)}["g"]
    assert vg.state == "withdrawn" and not vg.needs_attention, vg.state

    # ⑨ 归一化:有证伪 → 不 clean。
    clean, counts, _ = summarize([vb, vd])
    assert not clean and counts["refuted"] == 1
    return True


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 预注册假设台账 🔬")
    ap.add_argument("--register", metavar="NAME", help="改之前押一条假设(需 --claim/--verify + 停止条件)")
    ap.add_argument("--claim", default="", help="可证伪的断言:这次改动会带来什么可观测改进")
    ap.add_argument("--verify", default="", help="最小验证命令(shell 串):退出码 0=预测成立")
    ap.add_argument("--predict", default="", help="一句话写死你赌会看到什么(对账用)")
    ap.add_argument("--by-days", type=float, default=0.0, help="停止条件:过这么多天没确证→判否")
    ap.add_argument("--max-checks", type=int, default=0, help="停止条件:验这么多次没确证→判否")
    ap.add_argument("--check", nargs="?", const="*", metavar="NAME",
                    help="跑验证、落裁决:不带名=验全部待定的,带名=只验该条")
    ap.add_argument("--close", metavar="NAME", help="主动撤回一条仍待定的假设")
    ap.add_argument("--quiet", action="store_true", help="只在有证伪/超期未决时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出机读裁决清单")
    ap.add_argument("--selftest", action="store_true", help="自检折叠/裁决逻辑(不碰磁盘)")
    args = ap.parse_args(argv)

    if args.selftest:
        try:
            _selftest()
        except AssertionError as e:
            print(f"🔴 自检失败:{e}")
            sys.exit(1)
        if not args.quiet:
            print("🟢 hypothesis 折叠/裁决逻辑自检全过。")
        sys.exit(0)

    if args.register:
        argv_cmd = shlex.split(args.verify)
        ok, reason = register(args.register, claim=args.claim, argv=argv_cmd,
                              predict=args.predict, by_days=args.by_days,
                              max_checks=args.max_checks)
        if ok:
            print(f"🔬 已押下假设『{args.register}』:{args.claim or '(无断言)'}")
            print("    改完后跑 `python hypothesis.py --check {}` 揭晓。".format(args.register))
            sys.exit(0)
        print(f"⚠️  拒绝注册『{args.register}』:{reason}")
        sys.exit(2)

    if args.close:
        if close(args.close):
            print(f"⚪ 已撤回假设『{args.close}』。")
            sys.exit(0)
        print(f"⚠️  没有名为『{args.close}』的待定假设(可能不存在或已有裁决)。")
        sys.exit(2)

    if args.check is not None:
        target = args.check
        current = verdicts()
        if target == "*":
            todo = [v.name for v in current if v.state == "open"]
        else:
            todo = [v.name for v in current if v.name == target]
            if not todo:
                print(f"⚠️  没有名为『{target}』的假设。")
                sys.exit(2)
        if not args.quiet:
            print(f"🔬 揭晓 {len(todo)} 条假设……\n" if todo else "🔬 没有待定假设可验。\n")
        for name in todo:
            rec = check(name)
            if rec is None:
                continue
            mark = "🟢" if rec["ok"] else "🔴"
            if not args.quiet:
                line = f"  {mark} {name}"
                if not rec["ok"] and rec["detail"]:
                    line += f" — {rec['detail'].splitlines()[0][:120]}"
                print(line)
        if not args.quiet:
            print()

    vs = verdicts()
    clean, _, _ = summarize(vs)
    if not (args.quiet and clean):
        if args.json:
            print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        else:
            _print(vs)
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
