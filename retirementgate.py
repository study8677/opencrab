#!/usr/bin/env python3
"""退役候选闸 ⚰️🚪 —— 串起 usageheat × trustscore/evidence × lifecycle，把「冷且证据过期」的
器官摊成一张候选单，**只开复验/退役单，绝不替谁删一个字节**。

为什么要有它：领地里躺着八十多个 `*.py`，每一个都自称一项能力。可进化默认「我身上的器官
都还活着、都还在用」，于是一遍遍往上加新壳。`usageheat.py` 已能标出哪些器官冰封（久无人问津
且账本发凉），但冰封只是**一维提醒**——它不回答「那到底该复验、还是该退役？又凭什么不是删错」。
上一回（见 `docs/retirement-watch.md`）正是因为缺这层判别，差点把活还没核对清楚的器官当冗余瘦掉。
**真精简要先有证据，避免再犯假瘦身。**

这一层不新增能力，只把三处既有判断**对齐到同一个器官**上，合成一张「退役候选单」：

  · 🧊 **用量热力**（usageheat）—— 这器官是不是「冰封」：最近窗口里没在任何心跳被提起，
    且证据账本发凉 / 从未验证。冰封 = 又冷、证据又过期，这正是退役候选的入场券。
  · 🎚️ **信任分**（trustscore / evidence）—— 它有没有可复跑的证据声明？若有，信任分多低？
    有声明 = 还能「再证一遍」→ 该先开**复验单**；没声明 = 根本无从复验 → 才轮到**退役单**。
  · 🐚 **生命周期**（lifecycle）—— 它此刻在哪个阶段？已 `retired` 的早已脱壳（在 attic，不再候选）；
    已 `deprecated` 的是「退役进行中、悬而未决」，单列盯它别烂尾；只有还在 `stable/incubating`
    的冰封器官，才是**新候选**。

据此给每个候选派一张单（单 ≠ 令，只是「先看清、再决定」的待办）：

  · 🔁 **复验单**（reverify）—— 器官有证据声明但已过期/失守/不可信。退役前**先逼它再证一遍**：
    跑一遍它的验证命令，信任分若回到线上就撤单留人；仍不过，才升级为退役单。
  · ⚰️ **退役单**（retire）—— 器官连一条可复跑的证据声明都没有（写完即遗忘的旧壳）。无从复验，
    故走退役流程——但**退役单不等于删除令**：它把 `lifecycle.py` 进入 `retired` 的硬闸条目
    （指明继任者 successor + before/after 证据对照）原样抄在单上，逼人在删之前把对照摆上桌。

判准：退役候选闸是**观测者**——只读 usageheat/trustscore/evidence/lifecycle 的 manifest，
绝不写 journal、不改任何源文件、不执行被管模块、不替谁决定删留。任一处信号读不到，那一维记为
「未知」并据此降级判断，绝不臆测。候选单是**建议**，默认不让退出码非零（像冰封一样只是提醒）；
`--gate` 下若存在「退役单」候选才让退出码非零（可挂钩子 / CI 当「该清账了」的轻推）。

用法：
    python retirementgate.py            # 打印退役候选单（复验/退役 + 悬而未决）
    python retirementgate.py --days 14  # usageheat 审计回溯窗口（默认 7 天）
    python retirementgate.py --probe    # 让 usageheat 额外实跑 --help（推不开的更早暴露）
    python retirementgate.py --quiet     # 只在有候选时说话（适合钩子 / CI）
    python retirementgate.py --gate      # 有「退役单」候选即退出码非零（清账轻推）
    python retirementgate.py --json      # 机读：每个候选的体温/信任/阶段/单据类型与理由

退出码：默认恒 0（候选只是建议）。仅 --gate 时，存在退役单候选→1，否则 0。
候选单快照落在被 .gitignore 的 state/ 下（每次扫描重写），写盘失败绝不反噬生命。零第三方依赖。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TICKETS_PATH = REPO_ROOT / "state" / "retirementgate" / "tickets.jsonl"

# ── 单据类型 ──────────────────────────────────────────────────────────
TICKET_REVERIFY = "reverify"   # 🔁 有证据声明但已过期/不可信 → 先复验再说
TICKET_RETIRE = "retire"       # ⚰️ 无可复跑证据 → 走退役（经 lifecycle 硬闸，非直接删）
TICKET_PENDING = "pending"     # 🍂 已 deprecated 但未完成退役 → 悬而未决，盯着别烂尾

_TICKET_ICON = {TICKET_REVERIFY: "🔁", TICKET_RETIRE: "⚰️", TICKET_PENDING: "🍂"}
_TICKET_WORD = {TICKET_REVERIFY: "复验单", TICKET_RETIRE: "退役单", TICKET_PENDING: "悬而未决"}
_ORDER = (TICKET_RETIRE, TICKET_REVERIFY, TICKET_PENDING)

# lifecycle 已走到这些阶段的，不再算「新候选」：retired 早已脱壳，deprecated 另列悬而未决。
_STAGE_RETIRED = "retired"
_STAGE_DEPRECATED = "deprecated"

# 退役硬闸条目（原样抄自 lifecycle.check_transition 的退役红线，让退役单自带「删前先证」清单）。
_RETIRE_GATE = (
    "指明继任者 successor：本事搬去哪，依赖方才知道往哪走",
    "before 证据：证明它退役前确实在干活 / 它的输出长什么样（没删错东西）",
    "after 证据：证明这活如今由谁接、或已被证明无人再需要（删了不留窟窿）",
)


@dataclasses.dataclass
class Candidate:
    """一个器官跨三维对齐后的退役候选画像 + 派给它的单据。"""
    name: str                       # 模块名（stem，如 "batchflow"）
    summary: str                    # 一句自述
    ticket: str                     # reverify / retire / pending
    # 🧊 用量维
    temp: str = ""                  # usageheat 体温（这里恒为「冰封」或 deprecated 旁路）
    mentions: int = 0
    # 🎚️ 信任维
    has_claim: bool = False         # 是否有可复跑的证据声明
    verify_state: str | None = None  # fresh/stale/broken/unproven/None
    trust_score: float | None = None  # trustscore 合成分（无声明→None）
    age_days: float | None = None   # 证据账本上次复验距今天数
    # 🐚 生命周期维
    stage: str | None = None        # lifecycle 当前阶段（未登记→None）
    reasons: list[str] = dataclasses.field(default_factory=list)

    def to_meta(self) -> dict:
        return {
            "name": self.name, "summary": self.summary,
            "ticket": self.ticket, "ticket_word": _TICKET_WORD[self.ticket],
            "temp": self.temp, "mentions": self.mentions,
            "has_claim": self.has_claim, "verify_state": self.verify_state,
            "trust_score": round(self.trust_score, 4) if self.trust_score is not None else None,
            "age_days": self.age_days, "stage": self.stage,
            "reasons": self.reasons,
            "retire_gate": list(_RETIRE_GATE) if self.ticket == TICKET_RETIRE else [],
        }


# ── 三处信号：各自尽力而为，读不到就降级，绝不臆测 ──────────────────────────
def _cold_organs(days: int, probe: bool) -> dict[str, dict]:
    """从 usageheat 取「冰封」器官（冷 + 证据过期）。读不到则回空。"""
    try:
        import usageheat
        m = usageheat.manifest(days=days, probe=probe)
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for h in m.get("heats", []):
        if h.get("temp") == usageheat.TEMP_COLD:
            out[h["name"]] = h
    return out


def _trust_by_name() -> dict[str, "object"]:
    """从 trustscore 取每条声明的信任画像（含分数/状态）。读不到则回空。"""
    try:
        import trustscore
        return {t.name: t for t in trustscore.assess()}
    except Exception:
        return {}


def _stages() -> dict[str, str]:
    """从 lifecycle 取每个器官此刻的阶段，键归一化为 stem（去掉 .py）。读不到则回空。"""
    try:
        import lifecycle
        cur = lifecycle.current_stages()
    except Exception:
        return {}
    return {_stem(cap): stage for cap, stage in cur.items()}


def _stem(name: str) -> str:
    """把 'foo.py' / 'foo' 统一成 'foo'，好让三处信号对齐到同一个器官。"""
    return name[:-3] if name.endswith(".py") else name


# ── 合成：把三维对齐到同一器官，派单 ──────────────────────────────────────
def _build_candidate(name: str, heat: dict, trust, stage: str | None) -> Candidate:
    """据三维信号给一个冰封器官派单，并记下「为什么是这张单」。"""
    has_claim = trust is not None
    verify_state = heat.get("verify_state")
    reasons: list[str] = []

    # 用量维：冰封本身就是「冷 + 证据过期」，把 usageheat 给的理由透传一两条。
    mentions = int(heat.get("mentions") or 0)
    reasons.extend(heat.get("reasons", [])[:2])

    if has_claim:
        # 有可复跑证据 → 先复验。把信任分作为「多不可信」的量化理由。
        ticket = TICKET_REVERIFY
        score = getattr(trust, "score", None)
        band = getattr(trust, "word", "")
        if score is not None:
            reasons.append(f"有证据声明可复跑，但信任分仅 {score:.2f}（{band}）—— 退役前先逼它再证一遍")
        else:
            reasons.append("有证据声明可复跑 —— 退役前先复验，过则留人")
    else:
        # 连一条可复跑证据都没有 → 无从复验，走退役流程（经 lifecycle 硬闸）。
        ticket = TICKET_RETIRE
        reasons.append("没有任何可复跑的证据声明 —— 无从复验，按 lifecycle 退役硬闸走 before/after 对照")

    return Candidate(
        name=name, summary=heat.get("summary", ""), ticket=ticket,
        temp=heat.get("temp", ""), mentions=mentions,
        has_claim=has_claim, verify_state=verify_state,
        trust_score=getattr(trust, "score", None) if has_claim else None,
        age_days=heat.get("age_days"), stage=stage, reasons=reasons,
    )


def build(days: int = 7, probe: bool = False) -> list[Candidate]:
    """对齐三处信号，产出退役候选单（按单据类型 → 信任分 → 名字排序）。

    候选 = usageheat 判为「冰封」（冷 + 证据过期）且 lifecycle 阶段不在 retired 的器官。
    其中已 deprecated 的另派「悬而未决」单（退役进行中，盯着别烂尾），其余按有无证据声明
    分派复验单 / 退役单。
    """
    cold = _cold_organs(days, probe)
    trusts = _trust_by_name()
    stages = _stages()

    cands: list[Candidate] = []
    for name in sorted(cold):
        stage = stages.get(name)
        if stage == _STAGE_RETIRED:
            continue  # 早已脱壳（多半在 attic），不再候选
        if stage == _STAGE_DEPRECATED:
            c = _build_candidate(name, cold[name], trusts.get(name), stage)
            c.ticket = TICKET_PENDING
            c.reasons.insert(0, "已宣告废弃但退役未落地 —— 退役进行中，盯着别烂尾")
            cands.append(c)
            continue
        cands.append(_build_candidate(name, cold[name], trusts.get(name), stage))

    rank = {t: i for i, t in enumerate(_ORDER)}
    cands.sort(key=lambda c: (rank[c.ticket],
                              c.trust_score if c.trust_score is not None else -1.0,
                              c.name))
    return cands


def summarize(cands: list[Candidate]) -> dict[str, int]:
    out = {t: 0 for t in _ORDER}
    for c in cands:
        out[c.ticket] += 1
    return out


def manifest(days: int = 7, probe: bool = False) -> dict:
    """机读：全候选画像 + 各单据计数 + 退役硬闸条目。"""
    cands = build(days=days, probe=probe)
    counts = summarize(cands)
    return {
        "days": days, "probed": probe, "total": len(cands),
        "counts": counts,
        "retire_gate": list(_RETIRE_GATE),
        "candidates": [c.to_meta() for c in cands],
    }


# ── 候选单快照：落在 gitignore 的 state/ 下，每次扫描重写 ──────────────────
def write_tickets(cands: list[Candidate]) -> bool:
    """把候选单写成快照（整文件重写，描述「此刻」该清哪些账）。写盘尽力而为，失败被吞掉。"""
    try:
        TICKETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TICKETS_PATH.open("w", encoding="utf-8") as f:
            for c in cands:
                f.write(json.dumps(c.to_meta(), ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001 —— 快照是副产物，写不出也不该拖垮观测
        return False


# ── 渲染 ─────────────────────────────────────────────────────────────
def _render(cands: list[Candidate], days: int, probed: bool) -> str:
    counts = summarize(cands)
    L = [f"⚰️🚪 opencrab 退役候选闸 —— 冰封(冷×证据过期) ⨉ 信任 ⨉ 生命周期"
         f"（近 {days} 天审计{'，已实跑入口' if probed else ''}）", ""]

    if not cands:
        L.append("🦀 没有退役候选：在用的器官要么不冷，要么证据还新鲜。无需清账。")
        return "\n".join(L)

    by_ticket: dict[str, list[Candidate]] = {}
    for c in cands:
        by_ticket.setdefault(c.ticket, []).append(c)

    for tk in _ORDER:
        items = by_ticket.get(tk, [])
        if not items:
            continue
        L.append(f"{_TICKET_ICON[tk]} {_TICKET_WORD[tk]}（{len(items)} 个）")
        for c in items:
            stage = f"，生命周期 {c.stage}" if c.stage else ""
            L.append(f"   {c.name}.py — {c.summary}（点名 {c.mentions} 次{stage}）")
            for why in c.reasons:
                L.append(f"      · {why}")
        L.append("")

    if counts[TICKET_RETIRE]:
        L.append("⚰️ 退役单 ≠ 删除令。进入 lifecycle 的 retired 前，必须先把这对照摆上桌：")
        for line in _RETIRE_GATE:
            L.append(f"      · {line}")
        L.append("   没有对照，谁也不许删——见 docs/retirement-watch.md。")
    bar = "  ".join(f"{_TICKET_ICON[t]}{_TICKET_WORD[t]} {counts[t]}" for t in _ORDER)
    L.append(f"\n分布：{bar}")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 退役候选闸 ⚰️🚪 —— 串起用量/信任/生命周期，给冷且证据过期的器官开复验/退役单（不删）")
    ap.add_argument("--days", type=int, default=7, metavar="N",
                    help="usageheat 审计回溯窗口天数（默认 7）")
    ap.add_argument("--probe", action="store_true",
                    help="让 usageheat 额外实跑每扇门的 --help")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quiet", action="store_true",
                   help="只在有候选时说话（适合钩子 / CI）")
    g.add_argument("--json", action="store_true",
                   help="机读：导出每个候选的体温/信任/阶段/单据类型与理由")
    ap.add_argument("--gate", action="store_true",
                    help="有「退役单」候选即退出码非零（清账轻推）")
    args = ap.parse_args(argv)

    if args.days < 1:
        print(f"❌ --days 需为正整数，收到 {args.days}")
        sys.exit(2)

    if args.json:
        print(json.dumps(manifest(days=args.days, probe=args.probe),
                         ensure_ascii=False, indent=2))
        sys.exit(0)

    cands = build(days=args.days, probe=args.probe)
    write_tickets(cands)
    counts = summarize(cands)

    if args.quiet:
        if cands:
            print(f"⚰️🚪 退役候选闸：{counts[TICKET_RETIRE]} 张退役单、"
                  f"{counts[TICKET_REVERIFY]} 张复验单、{counts[TICKET_PENDING]} 个悬而未决")
    else:
        print(_render(cands, args.days, args.probe))

    # 默认恒 0（候选只是建议）；仅 --gate 时，存在退役单候选才轻推非零。
    sys.exit(1 if (args.gate and counts[TICKET_RETIRE]) else 0)


if __name__ == "__main__":
    main()
