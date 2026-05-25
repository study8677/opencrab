#!/usr/bin/env python3
"""策略竞技场 🥊 —— 把同一个目标同时交给 2~3 种不同的「进化策略」并行出方案，
自动对比各派的证据、分歧与预期收益，最后选出最值得真做的那一条。

为什么要有它：这只螃蟹已经会记教训(memory)、会规划长线(planner)、动手前还会用沙盘
(simulator)预演收益/风险/成本——**可它从头到尾只有「一个自己」在想**：沙盘里那三格
(保守/稳健/激进)是同一套脑子捏出来的模板，谁也不替谁说话、谁也不反驳谁。于是它永远
缺一层真正的**策略竞争**：没有几个立场不同的「自己」各自端出主张、亮出证据、当面分出
高下，就容易一条道走到黑——想保守时整盘都保守，想冒进时整盘都冒进，从不让对立的声音
先吵一架。

竞技场补的正是这层「让多个自己辩论后择优」：

  - 🐢 稳健派、🧱 营造派、🚀 开拓派各是一种**进化策略**，拿到同一目标各自独立出一份
    方案(approach / 规模 / 要不要碰要害 / 补不补自测 / 可不可逆)，并亮出支撑自己主张
    的证据(memory 里同类的成败、mentor 里可借的招式)。
  - 每份方案都过一遍沙盘(simulator.appraise)算出收益/风险/成本，竞技场再据各派引用的
    证据给「预期收益」做加减——被成功/招式背书的进取加分，无视失败教训的冒进扣分。
  - 自动摊出**分歧**(各派在规模/要害/自测/可逆上吵得最凶的轴)与**共识**(都同意的点)，
    再按预期收益择优；胜负咬得太紧(margin 小)时如实提醒「这仗势均力敌，先做更小验证」。

它只裁出「先做哪条」，不动手、更不替 judge 拍板——竞技场是事前的「择优参谋」，沙盘补
单方案的推演，它补的是多方案的竞争。软引入 simulator / memory / mentor：哪个上游缺席
都从容退化(沙盘没装就用本地兜底打分，证据井打不上水就空着)，绝不因某个依赖缺位而崩。
每场比赛落进被 .gitignore 的 state/arena/，可回溯但绝不反噬：读写出错统统吞掉，
竞技场不能成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python arena.py "<目标 / 要做的事>"                   # 默认三派同场竞技、择优
    python arena.py "<目标>" --strategy steady,builder    # 只让指定派上场
    python arena.py "<目标>" --constraint "纯标准库" --constraint "别碰 crab.py"
    python arena.py "<目标>" --kickoff                    # 把胜出方案直接交给 planner 起计划
    python arena.py --recent                              # 回看最近落档的几场比赛
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_ARENA_DIR = _REPO_ROOT / "state" / "arena"         # 落在被 .gitignore 的 state/ 里
_ROUNDS = _ARENA_DIR / "rounds.jsonl"               # 每场比赛的快照(可回看)

# 领地的要害器官：方案要碰它们，风险天然更重。软对齐 judge/simulator 的同名清单，
# 拿不到就用本地兜底，绝不因 import 失败而崩。
try:
    from judge import _VITAL as _VITAL              # type: ignore
except Exception:                                   # pragma: no cover
    _VITAL = {"crab.py", "hands.py", "checkup.py", "audit.py",
              "capabilities/__init__.py"}

_BIG_LINES = 400        # 「巨改」阈值(与 simulator 对齐)
_WIDE_FILES = 12        # 改动面「失控」阈值
_EVIDENCE_CAP = 2       # 单份方案证据加减分的封顶，免得证据压过沙盘本身的净收益
_CLOSE_MARGIN = 1       # 冠亚军预期收益差 ≤ 此值即判「势均力敌」


# ── 一条证据（从记忆/招式井打上来，供各派引用） ─────────────────────
@dataclasses.dataclass
class Evidence:
    """支撑(或反对)某种主张的一条证据：来自 memory 的成败往事、或 mentor 的可迁移招式。"""
    kind: str                   # success / failure / move
    text: str                   # 人话证据
    weight: float = 0.5         # 相关度/份量 0~1

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一份方案（一派的主张） ──────────────────────────────────────────
@dataclasses.dataclass
class Proposal:
    """某一派进化策略对同一目标端出的方案：先描述怎么改 + 亮出证据，再过沙盘算收益。"""
    strategy: str                               # 策略代号(steady/builder/pioneer)
    title: str                                  # 这一派的名号(带 emoji)
    stance: str = ""                            # 这一派的总主张(人话)
    approach: str = ""                          # 具体怎么改
    new_modules: int = 0
    est_lines: int = 0
    touches: list = dataclasses.field(default_factory=list)
    has_selftest: bool = True
    reversible: bool = True
    cites: list = dataclasses.field(default_factory=list)       # list[Evidence]，引用的证据

    # —— 评估产物(由 weigh 填) ——
    benefit: int = 0
    risk: int = 0
    cost: int = 0
    failure_chain: list = dataclasses.field(default_factory=list)
    evidence_adj: int = 0                       # 据引用证据给预期收益的加减
    reasons: list = dataclasses.field(default_factory=list)
    violations: list = dataclasses.field(default_factory=list)

    @property
    def net(self) -> int:
        """沙盘净收益 = 收益 − 风险 − 成本。"""
        return self.benefit - self.risk - self.cost

    @property
    def expected(self) -> int:
        """预期收益 = 沙盘净收益 + 证据加减——竞技场据此排名次。"""
        return self.net + self.evidence_adj

    def touches_vital(self) -> list:
        return sorted(f for f in self.touches if f.replace("\\", "/") in _VITAL)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["net"], d["expected"] = self.net, self.expected
        return d

    def render(self) -> str:
        head = (f"   {self.title}  预期{self.expected:+d}"
                f"（净{self.net:+d}=收益+{self.benefit} 风险-{self.risk} 成本-{self.cost}"
                + (f" 证据{self.evidence_adj:+d}" if self.evidence_adj else "") + "）")
        lines = [head]
        if self.stance:
            lines.append(f"      主张：{self.stance}")
        if self.approach:
            lines.append(f"      做法：{self.approach}")
        for ev in self.cites:
            mark = {"success": "✅", "failure": "⚠️", "move": "📒"}.get(ev.kind, "·")
            lines.append(f"      {mark} {ev.text}")
        if self.failure_chain:
            lines.append("      失败链：" + " → ".join(self.failure_chain))
        for v in self.violations:
            lines.append(f"      ⛔ {v}")
        return "\n".join(lines)


# ── 各派策略：拿同一目标各自出一份方案 ──────────────────────────────
def _mk_steady(goal: str, pool: list[Evidence]) -> Proposal:
    """🐢 稳健派：先有再好。抄最近的同类模块、小步改名、补全自测、保证可逆。
    引用记忆里同类的**失败**当作「别浪」的证据——栽过的地方更该收着走。"""
    cites = [e for e in pool if e.kind == "failure"][:2]
    return Proposal(
        strategy="steady", title="🐢 稳健派",
        stance="先有再好，宁可少长一点也别翻车",
        approach="抄领地里最接近的同类模块、改名微调，补全自测、保证可逆",
        new_modules=1, est_lines=90, has_selftest=True, reversible=True, cites=cites)


def _mk_builder(goal: str, pool: list[Evidence]) -> Proposal:
    """🧱 营造派：从零写一个聚焦的新模块，纯标准库、补自测、对齐风格。
    引用 mentor 里可借的招式当作「有现成路子」的证据——既稳又能长出新本事。"""
    cites = ([e for e in pool if e.kind == "move"][:1]
             + [e for e in pool if e.kind == "success"][:1])
    return Proposal(
        strategy="builder", title="🧱 营造派",
        stance="稳扎稳打长出一个新本事，既不照抄也不冒进",
        approach="从零写一个聚焦的新模块，纯标准库、补自测、对齐既有风格",
        new_modules=1, est_lines=300, has_selftest=True, reversible=True, cites=cites)


def _mk_pioneer(goal: str, pool: list[Evidence]) -> Proposal:
    """🚀 开拓派：一步到位，顺手把相关主循环重构，赌一次长出最多新本事。
    引用招式与成功往事当作「值得搏」的证据；但它要碰要害、可能省自测，竞技场会据证据扣分。"""
    cites = ([e for e in pool if e.kind == "move"][:1]
             + [e for e in pool if e.kind == "success"][:1])
    return Proposal(
        strategy="pioneer", title="🚀 开拓派",
        stance="一步到位、长得最多——赌一把大的",
        approach="顺手把相关主循环一起重构，一次到位",
        new_modules=1, est_lines=560, touches=["crab.py"],
        has_selftest=False, reversible=False, cites=cites)


_STRATEGIES = {
    "steady": _mk_steady,
    "builder": _mk_builder,
    "pioneer": _mk_pioneer,
}


# ── 证据池：从记忆/招式井各打一桶水 ─────────────────────────────────
def _gather_evidence(goal: str) -> list[Evidence]:
    """汇一池证据供各派引用：memory 里同类的成/败往事 + mentor 里高迁移的可借招式。
    任一口井缺席/出错都从容跳过，返回能打上来的部分。"""
    pool: list[Evidence] = []
    try:
        import memory
        for s, ep in memory.recall(goal, k=4):
            if s < 0.4:
                continue
            if ep.ok:
                pool.append(Evidence("success", f"记忆：同类做过且成功 — {ep.headline()}", s))
            else:
                pool.append(Evidence("failure", f"记忆：同类栽过 — {ep.headline()}", s))
    except Exception:
        pass
    try:
        import mentor
        for c in mentor.recent(20):
            if int(c.get("transfer", 0)) >= 4:
                title = str(c.get("title", "")).split("（来自")[0].strip()[:36]
                pool.append(Evidence("move", f"招式：有现成高迁移招式可借 — {title}", 0.6))
    except Exception:
        pass
    return pool


# ── 给一份方案过沙盘 + 据证据加减 ───────────────────────────────────
def weigh(p: Proposal, *, goal: str = "", constraints: list | None = None) -> Proposal:
    """先过沙盘(simulator.appraise，缺席则本地兜底)算收益/风险/成本，
    再据这一派**引用了哪些证据**给预期收益加减——就地改写 p 并返回。"""
    constraints = constraints or []
    warn = next((e.text for e in p.cites if e.kind == "failure"), "")
    _appraise(p, goal=goal, constraints=constraints, memory_warn=warn)

    # 证据加减：被成功/招式背书的进取加分；冒进(碰要害或省自测)却握着失败证据则扣分。
    adj = 0
    for ev in p.cites:
        if ev.kind in ("success", "move"):
            adj += 1
        elif ev.kind == "failure" and (p.touches_vital() or not p.has_selftest):
            adj -= 1                            # 明知栽过还冒进，证据反过来压它
    p.evidence_adj = max(-_EVIDENCE_CAP, min(_EVIDENCE_CAP, adj))
    return p


def _appraise(p: Proposal, *, goal: str, constraints: list, memory_warn: str) -> None:
    """优先借 simulator 的沙盘脑子打分；装不上沙盘就用本地兜底，绝不因缺席而崩。"""
    try:
        import simulator
        sb = simulator.Sandbox(
            name=p.title, approach=p.approach, new_modules=p.new_modules,
            est_lines=p.est_lines, touches=list(p.touches),
            has_selftest=p.has_selftest, reversible=p.reversible)
        simulator.appraise(sb, goal=goal, constraints=constraints, memory_warn=memory_warn)
        p.benefit, p.risk, p.cost = sb.benefit, sb.risk, sb.cost
        p.failure_chain, p.reasons, p.violations = sb.failure_chain, sb.reasons, sb.violations
        return
    except Exception:
        pass
    _appraise_local(p, memory_warn=memory_warn)


def _appraise_local(p: Proposal, *, memory_warn: str) -> None:
    """沙盘缺席时的本地兜底打分(与 simulator 的口径大体对齐，保守取重)。"""
    benefit = 2 * p.new_modules if p.new_modules else (1 if p.est_lines else 0)
    cost = p.est_lines // 150 + (1 if p.est_lines >= _BIG_LINES else 0) \
        + (1 if len(p.touches) >= _WIDE_FILES else 0)
    vital = p.touches_vital()
    risk = (2 if vital else 0) + (0 if p.has_selftest else 2) \
        + (0 if p.reversible else 1) + (1 if p.est_lines >= _BIG_LINES else 0) \
        + (1 if memory_warn else 0)
    chain: list = []
    if vital:
        chain.append(f"动了要害器官 {', '.join(vital)}")
    if not p.has_selftest:
        chain.append("没有自测兜底 → 回归不会被当场发现")
    if memory_warn:
        chain.append("重蹈覆辙：记忆里同类栽过")
    p.benefit, p.risk, p.cost = benefit, risk, cost
    p.failure_chain = chain or ["没有明显的连环失败点——这条路就算栽也栽得轻。"]


# ── 一场比赛：同一目标下各派的竞争 ──────────────────────────────────
@dataclasses.dataclass
class Match:
    """一场策略竞技：同一目标/约束下各派的方案 + 分歧 + 共识 + 一句「先做哪条」。"""
    goal: str
    constraints: list = dataclasses.field(default_factory=list)
    proposals: list = dataclasses.field(default_factory=list)    # list[Proposal]
    at: str = ""

    def ranked(self) -> list[Proposal]:
        """排名次：踩硬约束的一律压到最后，再按预期收益高、风险低、可逆优先。"""
        return sorted(
            self.proposals,
            key=lambda p: (bool(p.violations), -p.expected, p.risk, not p.reversible))

    def winner(self) -> Proposal | None:
        r = self.ranked()
        return r[0] if r else None

    def margin(self) -> int:
        """冠亚军预期收益之差——差得越小，这仗越「势均力敌」，越该先做小验证。"""
        r = self.ranked()
        return (r[0].expected - r[1].expected) if len(r) >= 2 else 99

    def divergence(self) -> list[str]:
        """摊出各派吵得最凶的轴：规模 / 碰要害 / 补自测 / 可逆 / 新模块数。"""
        ps = self.proposals
        if len(ps) < 2:
            return []
        out: list[str] = []

        def _bucket(n: int) -> str:
            return "小" if n < 150 else ("中" if n < _BIG_LINES else "大")
        if len({_bucket(p.est_lines) for p in ps}) > 1:
            spread = ", ".join(f"{p.title.split()[0]}{p.est_lines}行" for p in ps)
            out.append(f"改动规模分歧：{spread}")
        if len({bool(p.touches_vital()) for p in ps}) > 1:
            who = [p.title.split()[-1] for p in ps if p.touches_vital()]
            out.append(f"是否碰要害器官有分歧：{'、'.join(who)} 要碰，其余不碰")
        if len({p.has_selftest for p in ps}) > 1:
            who = [p.title.split()[-1] for p in ps if not p.has_selftest]
            out.append(f"要不要补自测有分歧：{'、'.join(who)} 想省")
        if len({p.reversible for p in ps}) > 1:
            who = [p.title.split()[-1] for p in ps if not p.reversible]
            out.append(f"可逆性有分歧：{'、'.join(who)} 的方案难回退")
        return out

    def consensus(self) -> list[str]:
        """摊出各派都同意的点——共识是最强的事前信号。"""
        ps = self.proposals
        if len(ps) < 2:
            return []
        out: list[str] = []
        if all(p.has_selftest for p in ps):
            out.append("各派都同意补自测")
        if all(p.reversible for p in ps):
            out.append("各派都同意保持可逆")
        if all(not p.touches_vital() for p in ps):
            out.append("各派都同意不碰要害器官")
        if all(p.new_modules >= 1 for p in ps):
            out.append("各派都同意这事该长出新模块（而非纯打磨）")
        return out

    def to_dict(self) -> dict:
        return {"at": self.at, "goal": self.goal, "constraints": list(self.constraints),
                "proposals": [p.to_dict() for p in self.proposals],
                "divergence": self.divergence(), "consensus": self.consensus(),
                "winner": (self.winner().strategy if self.winner() else None)}

    def render(self) -> str:
        lines = [f"🥊  策略竞技场 · 目标：{self.goal[:60]}"]
        if self.constraints:
            lines.append("   约束：" + " ｜ ".join(self.constraints))
        lines.append("")
        win = self.winner()
        for p in self.ranked():
            crown = " 👑 胜出" if p is win and not p.violations else ""
            warn = " ⛔违约" if p.violations else ""
            block = p.render()
            block = block.replace("\n", crown + warn + "\n", 1) if (crown or warn) \
                else block
            lines.append(block)
            lines.append("")

        div, con = self.divergence(), self.consensus()
        if con:
            lines.append("   🤝 共识：" + "；".join(con))
        if div:
            lines.append("   ⚔️ 分歧：")
            for d in div:
                lines.append(f"      · {d}")
        lines.append("")

        if win is None:
            lines.append("   （没有任何方案上场——先用 --strategy 选几派、或别把它们都筛掉。）")
        elif win.violations:
            lines.append("   ⚠️ 预期最高的方案踩了硬约束——别用它，回去让各派重出一份不违约的。")
        elif win.expected <= 0:
            lines.append(f"   ⚠️ 连胜出的「{win.title}」预期收益也不正——这事现在不值得真做，先放放。")
        elif self.margin() <= _CLOSE_MARGIN:
            lines.append(f"   ⚖️ 这仗势均力敌（冠亚军只差 {self.margin()}）：先做更小的验证、"
                         f"别急着全押「{win.title}」。")
        else:
            lines.append(f"   👉 择优：真做「{win.title}」——它在预期收益上明显领先（差 {self.margin()}），"
                         f"动手前盯紧它失败链的头一环。")
        return "\n".join(lines)


# ── 核心：开一场比赛 ────────────────────────────────────────────────
def compete(goal: str, strategies: list | None = None,
            constraints: list | None = None) -> Match:
    """让指定(默认全部)策略拿同一目标各出一份方案，过沙盘 + 据证据加减，组成一场比赛。

    任一派/任一证据井缺席都从容跳过；只要还有一派出得了方案，比赛照常开。
    """
    goal = (goal or "").strip() or "(未命名目标)"
    constraints = constraints or []
    names = strategies or list(_STRATEGIES)
    pool = _gather_evidence(goal)

    proposals: list[Proposal] = []
    for name in names:
        mk = _STRATEGIES.get(name)
        if mk is None:
            continue
        p = mk(goal, pool)
        weigh(p, goal=goal, constraints=constraints)
        proposals.append(p)
    return Match(goal=goal, constraints=constraints, proposals=proposals)


# ── 落地 / 回看 ─────────────────────────────────────────────────────
def save(match: Match) -> Match:
    """把一场比赛追加一份快照到 state/arena/rounds.jsonl；写入异常一律吞掉，绝不反噬。"""
    match.at = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        _ARENA_DIR.mkdir(parents=True, exist_ok=True)
        with _ROUNDS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(match.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass        # 竞技场是参谋，落档失败也绝不弄死这只生命
    return match


def arena(goal: str, strategies: list | None = None,
          constraints: list | None = None) -> Match:
    """开一场比赛并落档，供心跳动手前「让几个自己先吵一架再择优」时调用。"""
    return save(compete(goal, strategies, constraints))


def recent(limit: int = 10) -> list[dict]:
    """读出最近落档的比赛快照(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _ROUNDS.exists():
        return []
    out: list[dict] = []
    for line in _ROUNDS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


def kickoff(goal: str, strategies: list | None = None,
            constraints: list | None = None) -> dict:
    """择优后把胜出方案当目标直接交给 planner 起一份计划（主动把竞技结果落成行动）。

    这是竞技场唯一一处「越过参谋身份去推一把」的动作，且仍只动 planner（不动手改代码、
    不替 judge 拍板）。胜者违约/预期不正/planner 缺席时从容返回说明，绝不抛异常打断心跳。
    """
    m = save(compete(goal, strategies, constraints))
    win = m.winner()
    if win is None:
        return {"ok": False, "reason": "没有任何方案上场，无从择优"}
    if win.violations:
        return {"ok": False, "reason": f"胜出的「{win.title}」踩了硬约束，不该真做"}
    if win.expected <= 0:
        return {"ok": False, "reason": f"胜出的「{win.title}」预期收益不正，先放放"}
    try:
        import planner
        plan = planner.plan_goal(f"{goal}（按{win.title}：{win.stance}）")
        return {"ok": True, "winner": win.title, "goal": goal, "steps": len(plan.steps)}
    except Exception as e:
        return {"ok": False, "reason": f"planner 没接上：{e}", "winner": win.title}


# ── CLI ─────────────────────────────────────────────────────────────
def _cmd_recent(n: int = 10) -> None:
    rows = recent(n)
    if not rows:
        print("🥊  还没有落档的比赛（给我一个目标、或用 arena(...) 后再来看）。")
        return
    print(f"🥊  最近 {len(rows)} 场比赛：")
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        goal = str(r.get("goal", ""))[:36]
        ps = r.get("proposals") or []
        win = r.get("winner") or "—"
        print(f"  {ts}  {goal}  ({len(ps)} 派同场 → 胜出「{win}」)")


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="arena.py",
        description="🥊 策略竞技场：把同一目标交给 2~3 派进化策略并行出方案，对比证据/分歧/预期收益后择优",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("goal", nargs="*", help="目标 / 要做的事")
    ap.add_argument("--strategy", default="",
                    help=f"只让指定派上场（逗号分隔，可选 {'/'.join(_STRATEGIES)}；默认全上）")
    ap.add_argument("--constraint", action="append", default=[],
                    help="一条硬约束（可多次），如「纯标准库」「别碰 crab.py」")
    ap.add_argument("--kickoff", action="store_true",
                    help="把胜出方案直接交给 planner 起一份计划（把竞技结果落成行动）")
    ap.add_argument("--recent", action="store_true", help="回看最近落档的比赛后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    goal = " ".join(args.goal)
    if not goal:
        ap.error("请给一个目标描述（或用 --recent）")

    names = [s.strip() for s in args.strategy.split(",") if s.strip()] or None
    if names:
        bad = [s for s in names if s not in _STRATEGIES]
        if bad:
            ap.error(f"未知策略 {bad}；可选：{'/'.join(_STRATEGIES)}")

    if args.kickoff:
        out = kickoff(goal, names, args.constraint)
        if out.get("ok"):
            print(f"🥊  已择优并发起：planner 已就「{out['winner']}」的主张起了一份 {out['steps']} 步的计划。")
            print("    用 `python planner.py --show` 看路线。")
        else:
            print(f"🥊  没能发起：{out.get('reason', '未知原因')}")
        return

    print(arena(goal, names, args.constraint).render())


if __name__ == "__main__":
    main()
