#!/usr/bin/env python3
"""债账本 🧾 —— 给每一笔「先欠着」的技术债登记、定价、设到期复查与清偿命令。

自治进化里最甜也最毒的一句话是「先这样,回头再改」。回头往往不来:TODO 沉进注释、
临时豁免变成默认、绕过的边界长成习惯。单笔欠债不致命,致命的是**没人记得欠了谁、
欠了多久、什么时候该还**——于是「临时」悄悄腐蚀成「永久」,等到崩了才发现地基早被
蛀空。债账本补的就是这一环:把每一笔欠债**显式记下来**,让它逃不过下一次复查。

一笔合格的欠债登记钉死五样东西:
  · 是什么(title/kind) —— 一句话说清欠了什么。TODO、临时豁免、还是结构性技术债。
  · 为什么欠(why)       —— 当时为何选择先欠着。没有理由的债最容易变成永久。
  · 风险等级(risk)      —— low/med/high/critical。决定它该排在还债队列的哪一头。
  · 到期复查(due)       —— 一个日期。到了这天必须重新看一眼:还、还是续、还是认它转正。
  · 清偿命令(payoff)    —— 一串命令,跑通即证明「这笔债真的还清了,不是嘴上说还了」。

判准:债账本只登记、只提醒、只算账,**不替你还债**。唯一会真的跑外部命令的是
`--run`(执行某笔债的 payoff 命令验证是否已清),且必须显式开启;没有它,本模块
全程只读环境、只追加自己的账本,绝不反噬生命。到期与否由「今天」实时算出,不写死。

用法:
    # 登记一笔欠债:
    python debtledger.py --title "intent.py 跳过了空输入校验" \\
        --kind waiver --risk high --due 2026-06-10 \\
        --why "赶 dialogue 接入,先豁免,上线前必补" \\
        --where intent.py:88 \\
        --payoff "python intent.py --selfcheck"
    python debtledger.py --list                  # 列出未清的债(按风险+到期排序,标红逾期)
    python debtledger.py --list --due-soon 7      # 只看 7 天内到期或已逾期的
    python debtledger.py --show <id>              # 看某笔债的完整登记
    python debtledger.py --run <id>              # 真的跑该笔债的 payoff 命令(唯一会动外部)
    python debtledger.py --pay <id>              # 标记已清偿,销账
    python debtledger.py --waive <id> --until 2026-07-01  # 续期:把到期日往后挪并记一笔
    python debtledger.py --json --list            # 机读

零第三方依赖,纯标准库。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import append_jsonl, read_jsonl  # noqa: E402

DEBT_LOG = REPO_ROOT / "state" / "debtledger.jsonl"

# 债的状态机:欠着 → 还清 / 一直续期(续期不改状态,只挪到期日并留痕)。
STATUS_OPEN = "open"   # 还欠着,等复查或清偿
STATUS_PAID = "paid"   # 已清偿,销账
_STATUS_ICON = {STATUS_OPEN: "🧾", STATUS_PAID: "✅"}

# 债的种类:三类「先欠着」,登记口径不同但都得还。
KINDS = {
    "todo": "📝 TODO",      # 该做没做的事
    "waiver": "🚧 临时豁免",  # 明知不对、暂时放行的校验/边界
    "debt": "🏗️ 技术债",     # 结构性欠账:绕路实现、欠测试、欠文档
}
DEFAULT_KIND = "todo"

# 风险等级:决定还债队列的排序;数字越大越该先还。
RISK_RANK = {"low": 0, "med": 1, "high": 2, "critical": 3}
RISK_ICON = {"low": "🟢", "med": "🟡", "high": "🟠", "critical": "🔴"}
DEFAULT_RISK = "med"


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _today() -> _dt.date:
    return _dt.date.today()


def _parse_date(s: str | None) -> _dt.date | None:
    """把 YYYY-MM-DD 解析成 date;解析不了就回 None,绝不抛。"""
    if not s:
        return None
    try:
        return _dt.date.fromisoformat(s.strip())
    except Exception:
        return None


# ── 登记 ─────────────────────────────────────────────────────────────────
def build(title: str, kind: str, risk: str, due: str | None, why: str,
          where: str, payoff: list[str]) -> dict:
    """把一笔欠债组装成账本记录(还没落盘)。"""
    return {
        "kind": "debt",
        "id": _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
        "ts": _now(),
        "status": STATUS_OPEN,
        "title": title.strip(),
        "debt_kind": kind if kind in KINDS else DEFAULT_KIND,
        "risk": risk if risk in RISK_RANK else DEFAULT_RISK,
        "due": (_parse_date(due).isoformat() if _parse_date(due) else None),
        "why": (why or "").strip(),
        "where": (where or "").strip(),
        "payoff": [s.strip() for s in payoff if s.strip()],
    }


def gaps(debt: dict) -> list[str]:
    """挑出这笔登记**缺斤少两**的地方——没理由、没到期、没清偿命令的债最容易烂掉。"""
    out = []
    if not debt.get("why"):
        out.append("没写「为什么欠」:没有理由的债最容易变成永久。")
    if not debt.get("due"):
        out.append("没设「到期复查」:不定日子,这笔债就再没人回头看它。")
    if not debt.get("payoff"):
        out.append("没给「清偿命令」:还债时无法证明真的还清了,只能靠嘴。")
    return out


# ── 读账本 ───────────────────────────────────────────────────────────────
def _all() -> list[dict]:
    return [r for r in read_jsonl(DEBT_LOG) if r.get("kind") == "debt"]


def _latest_by_id() -> dict[str, dict]:
    """同一 id 可能被多次追加(续期/销账),取每个 id 的**最后一条**为准。"""
    out: dict[str, dict] = {}
    for r in _all():
        if r.get("id"):
            out[r["id"]] = r
    return out


def find(debt_id: str) -> dict | None:
    """按 id 取最新状态的债;支持前缀匹配。"""
    latest = _latest_by_id()
    if debt_id in latest:
        return latest[debt_id]
    hits = [v for k, v in latest.items() if k.startswith(debt_id)]
    return hits[0] if len(hits) == 1 else None


def open_debts() -> list[dict]:
    return [d for d in _latest_by_id().values() if d.get("status") == STATUS_OPEN]


def days_to_due(debt: dict) -> int | None:
    """距到期还剩几天:负数=已逾期,0=今天,正数=还有几天;没设到期回 None。"""
    due = _parse_date(debt.get("due"))
    if due is None:
        return None
    return (due - _today()).days


def is_overdue(debt: dict) -> bool:
    d = days_to_due(debt)
    return d is not None and d < 0


def sort_key(debt: dict) -> tuple:
    """还债队列的排序:先逾期、再风险高、再到期近。越该先还排越前。"""
    d = days_to_due(debt)
    overdue = 0 if (d is not None and d < 0) else 1   # 逾期优先(0 在前)
    risk = -RISK_RANK.get(debt.get("risk"), 1)        # 风险高优先
    due_in = d if d is not None else 10**6            # 到期近优先;没到期沉底
    return (overdue, risk, due_in)


# ── 状态流转 ─────────────────────────────────────────────────────────────
def mark_paid(debt: dict) -> dict:
    nxt = dict(debt)
    nxt["status"] = STATUS_PAID
    nxt["ts"] = _now()
    nxt["paid_at"] = _now()
    append_jsonl(DEBT_LOG, nxt)
    return nxt


def waive_until(debt: dict, until: str) -> dict | None:
    """续期:把到期日往后挪,并把旧到期日记进历史。新日子解析不了则回 None。"""
    new_due = _parse_date(until)
    if new_due is None:
        return None
    nxt = dict(debt)
    nxt["ts"] = _now()
    history = list(nxt.get("waive_history") or [])
    history.append({"from": nxt.get("due"), "to": new_due.isoformat(), "at": _now()})
    nxt["waive_history"] = history
    nxt["due"] = new_due.isoformat()
    append_jsonl(DEBT_LOG, nxt)
    return nxt


# ── 跑清偿验证(唯一会动外部的入口,须显式 --run) ──────────────────────────
def run_payoff(debt: dict, timeout: float = 120.0) -> list[dict]:
    """逐条跑 payoff 命令,回每条的 {cmd, ok, code}。逐条带超时,绝不卡死。"""
    results = []
    for cmd in debt.get("payoff", []):
        try:
            out = subprocess.run(cmd, cwd=REPO_ROOT, shell=True,
                                  capture_output=True, text=True, timeout=timeout)
            ok, code = out.returncode == 0, out.returncode
        except subprocess.TimeoutExpired:
            ok, code = False, "timeout"
        except Exception as e:  # noqa: BLE001
            ok, code = False, f"err:{e}"
        results.append({"cmd": cmd, "ok": ok, "code": code})
    return results


# ── 渲染 ─────────────────────────────────────────────────────────────────
def _due_phrase(debt: dict) -> str:
    """把到期状态说成人话:逾期 N 天 / 今天到期 / 还有 N 天 / 未设。"""
    d = days_to_due(debt)
    if d is None:
        return "未设到期"
    if d < 0:
        return f"⏰ 逾期 {-d} 天"
    if d == 0:
        return "⏰ 今天到期"
    return f"还有 {d} 天到期"


def render_markdown(debt: dict) -> str:
    """把一笔欠债渲染成自包含的 markdown。"""
    risk = debt.get("risk", DEFAULT_RISK)
    kind = debt.get("debt_kind", DEFAULT_KIND)
    L = [f"# 🧾 欠债 · {debt['title']}", "",
         f"> id `{debt['id']}` · 登记于 {debt['ts']} · 状态 {debt.get('status')}", "",
         f"- 种类:{KINDS.get(kind, kind)}",
         f"- 风险:{RISK_ICON.get(risk, '')} {risk}",
         f"- 到期复查:{debt.get('due') or '(未设)'} —— {_due_phrase(debt)}"]
    if debt.get("where"):
        L.append(f"- 位置:`{debt['where']}`")
    if debt.get("why"):
        L += ["", "## 为什么欠着", debt["why"]]
    L += ["", "## 🧹 清偿命令(跑通即证明真的还清)"]
    L += [f"- `{s}`" for s in debt.get("payoff", [])] or ["- (未给)"]
    hist = debt.get("waive_history") or []
    if hist:
        L += ["", "## 🔁 续期记录"]
        L += [f"- {h.get('at','')}:{h.get('from') or '(无)'} → {h.get('to')}" for h in hist]
    L.append("")
    return "\n".join(L)


def _print_debt(debt: dict) -> None:
    print(render_markdown(debt))
    g = gaps(debt)
    if g:
        print("⚠️ 这笔债登记得还不够死:")
        for s in g:
            print(f"   · {s}")


def _print_list(rows: list[dict]) -> None:
    if not rows:
        print("🧾 没有未清的债 —— 用 --title 登记一笔,或 --json --list 看全部。")
        return
    overdue = [d for d in rows if is_overdue(d)]
    head = f"🧾 未清的债({len(rows)} 笔"
    head += f",其中 {len(overdue)} 笔已逾期)" if overdue else ")"
    print(head + ":")
    for d in sorted(rows, key=sort_key):
        risk = d.get("risk", DEFAULT_RISK)
        kind = d.get("debt_kind", DEFAULT_KIND)
        print(f"   {RISK_ICON.get(risk,'')} {d['id'][:15]}  {d['title']}")
        loc = f" · {d['where']}" if d.get("where") else ""
        print(f"       {KINDS.get(kind, kind)} · {_due_phrase(d)}{loc}")


def _print_run(debt: dict, results: list[dict]) -> None:
    print(f"🧹 跑欠债 {debt['id'][:15]} 的清偿命令({len(results)} 条):")
    if not results:
        print("   (这笔债没写 payoff 命令 —— 无从验证是否还清)")
        return
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        print(f"   {mark} `{r['cmd']}`  (code={r['code']})")
    bad = [r for r in results if not r["ok"]]
    if bad:
        print(f"   ⚠️ {len(bad)} 条没通过 —— 这笔债还没还清,别急着 --pay。")
    else:
        print("   全部通过 —— 可以放心 --pay 销账了。")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="债账本:登记 TODO/临时豁免/技术债,设到期复查与清偿命令。")
    ap.add_argument("--title", help="一句话说清欠了什么(登记新债时必给)")
    ap.add_argument("--kind", default=DEFAULT_KIND, choices=list(KINDS),
                    help=f"债的种类(默认 {DEFAULT_KIND})")
    ap.add_argument("--risk", default=DEFAULT_RISK, choices=list(RISK_RANK),
                    help=f"风险等级(默认 {DEFAULT_RISK})")
    ap.add_argument("--due", help="到期复查日 YYYY-MM-DD")
    ap.add_argument("--why", default="", help="为什么选择先欠着")
    ap.add_argument("--where", default="", help="债在哪(如 intent.py:88)")
    ap.add_argument("--payoff", action="append", default=[], metavar="命令",
                    help="清偿验证命令(可多次)")
    ap.add_argument("--dry", action="store_true", help="只看不存")
    ap.add_argument("--list", action="store_true", help="列出未清的债")
    ap.add_argument("--due-soon", type=int, metavar="天数", dest="due_soon",
                    help="配合 --list:只看 N 天内到期或已逾期的")
    ap.add_argument("--show", metavar="ID", help="看某笔债的完整登记")
    ap.add_argument("--run", metavar="ID", help="真的跑该笔债的 payoff 命令(唯一会动外部)")
    ap.add_argument("--pay", metavar="ID", help="标记已清偿,销账")
    ap.add_argument("--waive", metavar="ID", help="续期:把到期日往后挪(配合 --until)")
    ap.add_argument("--until", help="配合 --waive:新的到期日 YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="机读输出")
    args = ap.parse_args(argv)

    # ── 查看类 ──
    if args.list:
        rows = open_debts()
        if args.due_soon is not None:
            rows = [d for d in rows if (days_to_due(d) is not None
                                        and days_to_due(d) <= args.due_soon)]
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            _print_list(rows)
        return 0

    if args.show:
        debt = find(args.show)
        if debt is None:
            ap.error(f"找不到欠债(或前缀不唯一):{args.show}")
        if args.json:
            print(json.dumps(debt, ensure_ascii=False, indent=2))
        else:
            _print_debt(debt)
        return 0

    if args.run:
        debt = find(args.run)
        if debt is None:
            ap.error(f"找不到欠债(或前缀不唯一):{args.run}")
        results = run_payoff(debt)
        if args.json:
            print(json.dumps({"id": debt["id"], "results": results},
                             ensure_ascii=False, indent=2))
        else:
            _print_run(debt, results)
        return 0

    if args.pay:
        debt = find(args.pay)
        if debt is None:
            ap.error(f"找不到欠债(或前缀不唯一):{args.pay}")
        debt = mark_paid(debt)
        if args.json:
            print(json.dumps(debt, ensure_ascii=False, indent=2))
        else:
            print(f"✅ 欠债 {debt['id'][:15]} 已清偿销账。")
        return 0

    if args.waive:
        debt = find(args.waive)
        if debt is None:
            ap.error(f"找不到欠债(或前缀不唯一):{args.waive}")
        if not args.until:
            ap.error("--waive 续期需要 --until YYYY-MM-DD 给出新的到期日")
        nxt = waive_until(debt, args.until)
        if nxt is None:
            ap.error(f"--until 不是合法日期:{args.until}")
        if args.json:
            print(json.dumps(nxt, ensure_ascii=False, indent=2))
        else:
            print(f"🔁 欠债 {nxt['id'][:15]} 已续期至 {nxt['due']}(旧债不灭,只是又给了它一程)。")
            _print_debt(nxt)
        return 0

    # ── 登记 ──
    if not args.title:
        ap.error("登记新债请给 --title;或用 --list / --show / --run / --pay / --waive")
    debt = build(args.title, args.kind, args.risk, args.due,
                 args.why, args.where, args.payoff)
    if not args.dry:
        append_jsonl(DEBT_LOG, debt)
    if args.json:
        print(json.dumps(debt, ensure_ascii=False, indent=2))
    else:
        _print_debt(debt)
        if args.dry:
            print("   (--dry:本次没落账本)")
        else:
            print(f"\n🧾 已登记入账:{debt['id'][:15]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
