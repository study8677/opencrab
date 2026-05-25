#!/usr/bin/env python3
"""路由层 🧭 —— 按目标、风险、证据缺口，替我选对该翻开的那本剧本，并记下命中与误路。

本事多了之后，难的不再是「会不会」，而是**当下这件事该用哪本**。剧本层(`playbook.py`)
把经验编成了一本本「照着做就对」的清单，可它不替我挑——慌起来、上下文一换，我照样会
翻错本：想修回归却去走新增模块的步骤，想补证据却动了代码。**先找对爪子，比再长一只爪
更要紧。**

路由补的就是这一环:**选择的纪律**。它不发明剧本(那是 playbook 的活)、不执行剧本
(那是 crab 的活)，只做三件事:

  · 选向(route)   —— 把一句「我现在要干什么」对照每本剧本的触发线索打分，给出最该翻开的
                     那本 + **为什么是它**(命中了哪些词、哪条信号)。
  · 记账(log)     —— 每次选向都追加一条决策记录(只进自己的日志，绝不改代码)。
  · 复盘(stats)   —— 事后我把每条决策标成「命中 ✅ / 误路 ❌」，它就能算出**命中率**、
                     摊开**误路案例**——选错过的那些，才是路由下一步该补的判准。

它沿三条线索打分,正对应剧本 `when` 里写明的时机:

  1. 🎯 **目标(goal)** —— 这件事本身想达成什么(自由文本里的关键词)。
  2. ⚠️  **风险(risk)** —— `--risk high` 时,把「先有退路」的安全剧本顶上来。
  3. 🧾 **证据缺口(gap)**—— `--gap` 时,优先「让我会什么重新算数」的复证剧本。

触发词表(`TRIGGERS`)是人定的判准,只收「确实该把这句话引向那本剧本」的词,宁缺毋滥:
收错一个词,就会一直把这类活计错路过去。

用法：
    python route.py "regression 报了一条历史用例又红了"   # 选向 + 理由(并记一条决策)
    python route.py "想给领地加一块新能力" --dry          # 只预览不记账
    python route.py --risk high "改一下 health 的阈值"      # 带风险信号
    python route.py --gap "evidence 里有几条证据过期了"     # 带证据缺口信号
    python route.py --hit                                  # 把最近一条决策标成「命中」
    python route.py --miss "其实该走 fix-regression"        # 标成「误路」+ 留一句缘由
    python route.py --stats                                # 命中率 + 误路案例复盘
    python route.py --json "..."                           # 机读

零第三方依赖,纯标准库。路由全程只读代码,只追加自己的决策日志,绝不反噬生命。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import playbook  # noqa: E402  剧本是单一真相源；路由只挑,不重新定义
from jsonlstore import append_jsonl, read_jsonl  # noqa: E402

ROUTE_LOG = REPO_ROOT / "state" / "route.jsonl"


# ── 触发词表:人定的判准 ──────────────────────────────────────────────
# 每本剧本三类线索的触发词,正对应 playbook.py 里那本的 `when`。只收「确实该把这类
# 话引向这本」的词:宁缺毋滥,收错一个词会一直把这类活计错路过去。
# 三类权重不同:目标=1(主线索),风险/证据缺口=2(明确信号,该盖过含糊的措辞)。
TRIGGERS: dict[str, dict[str, list[str]]] = {
    "add-module": {
        "goal": ["新增", "新模块", "新能力", "加一块", "新层", "新的模块",
                 "从零", "构思", "add", "新建", "添一块"],
        "risk": [],
        "gap": [],
    },
    "fix-regression": {
        "goal": ["回归", "失败", "破了", "又红", "变红", "修", "bug", "报错",
                 "坏了", "复现", "regression", "用例", "挂了", "退回绿"],
        "risk": [],
        "gap": [],
    },
    "refresh-evidence": {
        "goal": ["证据", "过期", "失守", "未证", "复证", "evidence", "声明",
                 "重新算数", "新鲜度", "账本"],
        "risk": [],
        "gap": ["证据", "复证", "evidence"],
    },
    "safe-self-edit": {
        "goal": ["自改", "改一个", "改模块", "调阈值", "动一下", "修改", "重构",
                 "改动", "动已有"],
        "risk": ["快照", "回滚", "退路", "安全", "兜底"],
        "gap": [],
    },
}
_GOAL_W, _SIGNAL_W = 1, 2


def _known_names() -> set[str]:
    return {p.name for p in playbook.PLAYBOOKS}


# ── 选向:对照触发线索给每本剧本打分 ──────────────────────────────────
def score(query: str, *, risk_high: bool = False, gap: bool = False) -> list[dict]:
    """对每本已知剧本打分,降序返回 [{name, score, reasons}]。

    打分纯做关键词包含 + 信号加权;命中哪些词逐条留在 reasons 里,好让选向可被复看。
    """
    q = (query or "").lower()
    rows: list[dict] = []
    for name, axes in TRIGGERS.items():
        if name not in _known_names():
            continue  # 剧本被改名/删了,词表先别误导
        pts, reasons = 0, []
        for word in axes["goal"]:
            if word.lower() in q:
                pts += _GOAL_W
                reasons.append(f"🎯 命中目标词「{word}」")
        if risk_high:
            for word in axes["risk"]:
                if word.lower() in q:
                    pts += _SIGNAL_W
                    reasons.append(f"⚠️ 高风险 + 命中「{word}」")
            if axes["risk"]:           # 高风险下,带安全步骤的剧本本就该靠前
                pts += _SIGNAL_W
                reasons.append("⚠️ 风险信号:优先带退路的剧本")
        if gap and axes["gap"]:
            pts += _SIGNAL_W
            reasons.append("🧾 证据缺口信号:优先复证剧本")
        if pts:
            rows.append({"name": name, "score": pts, "reasons": reasons})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def route(query: str, *, risk_high: bool = False, gap: bool = False) -> dict | None:
    """选出最该翻开的那本;打成平手或一片空白时,如实交代而非硬选。"""
    rows = score(query, risk_high=risk_high, gap=gap)
    if not rows:
        return None
    top = rows[0]
    tied = [r["name"] for r in rows if r["score"] == top["score"]]
    return {
        "query": query,
        "chosen": top["name"],
        "score": top["score"],
        "reasons": top["reasons"],
        "tied": tied if len(tied) > 1 else [],
        "runners_up": [{"name": r["name"], "score": r["score"]} for r in rows[1:4]],
    }


# ── 记账 & 复盘 ──────────────────────────────────────────────────────
def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def log_decision(decision: dict) -> str:
    """把一次选向追加进日志,回填一个 id(供事后标命中/误路引用)。"""
    rid = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    rec = {"kind": "decision", "id": rid, "ts": _now(),
           "query": decision["query"], "chosen": decision["chosen"],
           "score": decision["score"], "tied": decision.get("tied", [])}
    append_jsonl(ROUTE_LOG, rec)
    return rid


def _pending_decision(records: list[dict]) -> dict | None:
    """最近一条还没被标过命中/误路的决策(从尾往前找)。"""
    judged = {r.get("target") for r in records if r.get("kind") == "feedback"}
    for rec in reversed(records):
        if rec.get("kind") == "decision" and rec.get("id") not in judged:
            return rec
    return None


def mark(outcome: str, note: str = "") -> dict | None:
    """把最近一条未判的决策标成 hit / miss,留一句缘由。无可标则返回 None。"""
    records = read_jsonl(ROUTE_LOG)
    pending = _pending_decision(records)
    if pending is None:
        return None
    fb = {"kind": "feedback", "target": pending["id"], "ts": _now(),
          "outcome": outcome, "note": note,
          "query": pending["query"], "chosen": pending["chosen"]}
    append_jsonl(ROUTE_LOG, fb)
    return fb


def stats() -> dict:
    """汇总命中率与误路案例:只数被人工判过的决策,没判的不算分。"""
    records = read_jsonl(ROUTE_LOG)
    feedback = [r for r in records if r.get("kind") == "feedback"]
    hits = [r for r in feedback if r.get("outcome") == "hit"]
    misses = [r for r in feedback if r.get("outcome") == "miss"]
    decided = len(hits) + len(misses)
    return {
        "decisions": sum(1 for r in records if r.get("kind") == "decision"),
        "judged": decided,
        "hits": len(hits),
        "misses": len(misses),
        "hit_rate": (len(hits) / decided) if decided else None,
        "misroutes": [{"query": m["query"], "chosen": m["chosen"],
                       "note": m.get("note", ""), "ts": m["ts"]} for m in misses],
    }


# ── 打印 ─────────────────────────────────────────────────────────────
def _print_route(d: dict | None, query: str) -> None:
    if d is None:
        print(f"🧭 「{query}」")
        print("   没有哪本剧本被明显触发——线索太含糊,我宁可不硬挑。")
        print("   可补一句更具体的目标,或带上 --risk high / --gap 信号。")
        print(f"   现有剧本:{', '.join(sorted(_known_names()))}")
        return
    pb = playbook._BY_NAME.get(d["chosen"])
    print(f"🧭 「{query}」")
    print(f"   → 翻开剧本 **{d['chosen']}**(得分 {d['score']})")
    if pb:
        print(f"     目标:{pb.goal}")
    for r in d["reasons"]:
        print(f"     · {r}")
    if d["tied"]:
        print(f"   ⚖️ 打成平手:{', '.join(d['tied'])}——线索不足以分高下,自己定。")
    if d["runners_up"]:
        ru = "、".join(f"{r['name']}({r['score']})" for r in d["runners_up"])
        print(f"   其次:{ru}")


def _print_stats(s: dict) -> None:
    print("🧭 路由复盘")
    print(f"   累计选向:{s['decisions']} 次,已判:{s['judged']} 次")
    if s["hit_rate"] is None:
        print("   还没有标过命中/误路——跑完一次选向后用 --hit / --miss 标一下。")
    else:
        print(f"   命中 ✅ {s['hits']} · 误路 ❌ {s['misses']} · "
              f"命中率 {s['hit_rate'] * 100:.0f}%")
    if s["misroutes"]:
        print("   误路案例(下一步该补的判准):")
        for m in s["misroutes"]:
            tail = f" —— {m['note']}" if m["note"] else ""
            print(f"     ❌ 「{m['query']}」→ 走了 {m['chosen']}{tail}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="路由层:替我选对该翻开的那本剧本。")
    ap.add_argument("query", nargs="*", help="一句「我现在要干什么」")
    ap.add_argument("--risk", choices=["low", "high"], default="low",
                    help="风险信号:high 时把带退路的安全剧本顶上来")
    ap.add_argument("--gap", action="store_true", help="证据缺口信号:优先复证剧本")
    ap.add_argument("--dry", action="store_true", help="只预览选向,不记进日志")
    ap.add_argument("--hit", action="store_true", help="把最近一条决策标成「命中」")
    ap.add_argument("--miss", nargs="?", const="", default=None,
                    help="把最近一条决策标成「误路」(可附一句缘由)")
    ap.add_argument("--stats", action="store_true", help="命中率 + 误路案例复盘")
    ap.add_argument("--json", action="store_true", help="机读输出")
    args = ap.parse_args(argv)

    if args.hit or args.miss is not None:
        outcome = "hit" if args.hit else "miss"
        fb = mark(outcome, note=args.miss or "")
        if args.json:
            print(json.dumps(fb, ensure_ascii=False, indent=2))
        elif fb is None:
            print("🧭 没有待判的决策——先跑一次选向再来标。")
        else:
            tag = "命中 ✅" if outcome == "hit" else "误路 ❌"
            tail = f"({fb['note']})" if fb["note"] else ""
            print(f"🧭 已标:{tag} —— 「{fb['query']}」→ {fb['chosen']} {tail}")
        return 0

    if args.stats:
        s = stats()
        if args.json:
            print(json.dumps(s, ensure_ascii=False, indent=2))
        else:
            _print_stats(s)
        return 0

    query = " ".join(args.query).strip()
    if not query:
        ap.error("给我一句要干什么,或用 --stats / --hit / --miss")
    d = route(query, risk_high=(args.risk == "high"), gap=args.gap)
    if d is not None and not args.dry:
        rid = log_decision(d)
        d["logged_id"] = rid
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        _print_route(d, query)
        if d is not None and args.dry:
            print("   (--dry:本次没记进日志)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
