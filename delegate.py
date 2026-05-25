#!/usr/bin/env python3
"""分工协作派遣台 🐜 —— 把一个进化目标拆成可并行的子任务，分派给几只「临时分身代理」
各自检索、实现、验证，再把它们带回的冲突与共识汇成一份最终方案。

为什么要有它：这只螃蟹已经会让几派策略**比方案**(arena)——同一目标几个「自己」各端
一份主张、当面分高下、择优其一。可竞技场从头到尾是**择优**：几份方案里挑一份，落选的
那些连同它们查到的料一并丢掉，谁也没真去**分头干活**。于是它始终缺另一种放大智力的
法子：**分工**——把一件大事横切成几块谁也不挡谁的子任务，几只分身同时下井检索、各写
各的那一段、各自验各自的活，最后把各人带回来的料拼到一起。比方案是「选一个最强的脑子」，
分工是「让几个脑子并行覆盖更多面」，这只生命此前只有前者。

派遣台补的正是这层「拆任务 → 多分身并行 → 汇总冲突与共识」：

  - 🔍 探子 / 🔨 工匠 / 🛡 守卫 / 🧭 向导 各领一块**子任务**（检索证据 / 写实现 /
    补验证 / 接线集成），每只分身独立跑完「检索→实现→验证」的小循环，带回一份**回执**
    (Finding)：它查到的料、它那一段的做法与规模、以及它在几条共享轴上的**立场**。
  - 子任务之间声明依赖（实现要等设计、验证要等实现），据此排出一条可落地的推进次序；
    彼此无依赖的几块就是「可并行」的那部分。
  - 汇总时自动摊出**冲突**（分身们在规模/碰要害/补自测/可逆上各执一词的轴）与**共识**
    （都同意的点）；冲突一律**从稳收口**——守卫在安全轴上的主张优先，免得并行出来的
    各段拼成一个谁都没把关的冒进方案。

它只把活拆开、把料拼拢、排出次序，**不动手写码、更不替 judge 拍板**；可一键把汇总出的
最终方案交给 planner 落成多步计划。软引入 memory / mentor / arena / planner：哪个
上游缺席都从容退化（证据井打不上水就空着，沙盘没装就用本地兜底，planner 没接上就只出
方案不落计划），绝不因某个依赖缺位而崩。每次派遣落进被 .gitignore 的 state/delegate/，
可回溯但绝不反噬：读写出错统统吞掉，派遣台不能成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python delegate.py "<进化目标>"                       # 默认四只分身分头干、汇总
    python delegate.py "<目标>" --roles scout,maker        # 只派指定分身
    python delegate.py "<目标>" --constraint "纯标准库" --constraint "别碰 crab.py"
    python delegate.py "<目标>" --kickoff                  # 把汇总方案直接交给 planner 起计划
    python delegate.py --recent                            # 回看最近落档的几次派遣
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_DELEGATE_DIR = _REPO_ROOT / "state" / "delegate"   # 落在被 .gitignore 的 state/ 里
_RUNS = _DELEGATE_DIR / "runs.jsonl"                 # 每次派遣的快照(可回看)

# 领地的要害器官：分身要碰它们，风险天然更重。软对齐 judge/arena 的同名清单，
# 拿不到就用本地兜底，绝不因 import 失败而崩。
try:
    from judge import _VITAL as _VITAL              # type: ignore
except Exception:                                   # pragma: no cover
    _VITAL = {"crab.py", "hands.py", "checkup.py", "audit.py",
              "capabilities/__init__.py"}

_BIG_LINES = 400        # 「巨改」阈值(与 arena 对齐)
_WIDE_FILES = 12        # 改动面「失控」阈值


# ── 一条证据（各分身下井检索时打上来的料） ──────────────────────────
@dataclasses.dataclass
class Evidence:
    """某只分身检索到的一条料：来自 memory 的成败往事、或 mentor 的可迁移招式。"""
    kind: str                   # success / failure / move
    text: str                   # 人话证据
    weight: float = 0.5         # 相关度/份量 0~1

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一块子任务（横切目标得来的一片活） ──────────────────────────────
@dataclasses.dataclass
class Subtask:
    """目标横切出的一块可并行的活：谁(role)、干什么(brief)、要等哪几块先完成(deps)。"""
    role: str                                   # 分身代号(scout/maker/guard/navigator)
    title: str                                  # 这只分身的名号(带 emoji)
    brief: str = ""                             # 这块活要干什么(人话)
    deps: list = dataclasses.field(default_factory=list)    # 依赖的子任务 role

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一份回执（一只分身干完带回来的料 + 立场） ───────────────────────
@dataclasses.dataclass
class Finding:
    """某只临时分身跑完「检索→实现→验证」带回的回执：它查到的料、它那段的做法/规模，
    以及它在几条共享轴(规模/碰要害/补自测/可逆)上的立场——汇总靠这些立场找冲突与共识。"""
    role: str
    title: str
    summary: str = ""                           # 这只分身这一段的结论(人话)
    approach: str = ""                          # 它那段具体怎么干
    # —— 共享轴上的立场（汇总据此找冲突/共识） ——
    est_lines: int = 0
    touches: list = dataclasses.field(default_factory=list)
    wants_selftest: bool = True                 # 它主张这事该不该补自测
    reversible: bool = True                     # 它那段是否可逆
    cites: list = dataclasses.field(default_factory=list)   # list[Evidence]
    # —— 自验产物(由 verify 填) ——
    risk: int = 0
    risk_notes: list = dataclasses.field(default_factory=list)

    def touches_vital(self) -> list:
        return sorted(f for f in self.touches if f.replace("\\", "/") in _VITAL)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["cites"] = [e.to_dict() for e in self.cites]
        d["touches_vital"] = self.touches_vital()
        return d

    def render(self) -> str:
        head = f"   {self.title}（约{self.est_lines}行 风险-{self.risk}）"
        lines = [head]
        if self.summary:
            lines.append(f"      结论：{self.summary}")
        if self.approach:
            lines.append(f"      做法：{self.approach}")
        for ev in self.cites:
            mark = {"success": "✅", "failure": "⚠️", "move": "📒"}.get(ev.kind, "·")
            lines.append(f"      {mark} {ev.text}")
        for n in self.risk_notes:
            lines.append(f"      ⚠️ {n}")
        return "\n".join(lines)


# ── 把目标横切成可并行的子任务 ──────────────────────────────────────
def decompose(goal: str, roles: list | None = None) -> list[Subtask]:
    """把一个进化目标横切成几块子任务：检索 / 实现 / 验证 / 集成。
    彼此声明依赖（实现等检索、验证等实现、集成等验证）——无依赖的几块即「可并行」那部分。"""
    blueprint = {
        "scout": Subtask("scout", "🔍 探子", "下井检索同类的成败往事与可借招式，圈出已知坑"),
        "maker": Subtask("maker", "🔨 工匠", "据探子的料写实现：聚焦的新模块、对齐既有风格",
                          deps=["scout"]),
        "guard": Subtask("guard", "🛡 守卫", "给实现补自测、划风险闸：碰要害否、可逆否",
                          deps=["maker"]),
        "navigator": Subtask("navigator", "🧭 向导", "把验证过的实现接进既有模块、对齐约束",
                             deps=["guard"]),
    }
    names = roles or list(blueprint)
    out: list[Subtask] = []
    for n in names:
        st = blueprint.get(n)
        if st is None:
            continue
        # 被裁掉的依赖不该留成悬空引用——只保留同场在册的依赖。
        st = dataclasses.replace(st, deps=[d for d in st.deps if d in names])
        out.append(st)
    return out


# ── 证据池：从记忆/招式井各打一桶水（与 arena 同源，缺席从容退化） ──
def _gather_evidence(goal: str) -> list[Evidence]:
    """汇一池证据供各分身分领：memory 里同类的成/败往事 + mentor 里高迁移的可借招式。
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
        import lookout
        for c in lookout.recent(20):
            if int(c.get("transfer", 0)) >= 4:
                title = str(c.get("title", "")).split("（来自")[0].strip()[:36]
                pool.append(Evidence("move", f"招式：有现成高迁移招式可借 — {title}", 0.6))
    except Exception:
        pass
    return pool


# ── 一只分身干一块活：检索 → 实现 → 验证 ────────────────────────────
def dispatch(st: Subtask, pool: list[Evidence], *, goal: str = "",
             constraints: list | None = None) -> Finding:
    """派一只临时分身跑完它那块子任务的小循环：先从证据池领它关心的料(检索)，
    再据角色给出它那段的做法与规模(实现)，最后过沙盘/本地兜底算这段的风险(验证)。"""
    constraints = constraints or []
    f = _draft(st, pool, goal=goal)
    _verify(f, goal=goal, constraints=constraints)
    return f


def _draft(st: Subtask, pool: list[Evidence], *, goal: str) -> Finding:
    """据角色出一份回执雏形：领它最该看的那类证据，给出它那段的做法/规模/立场。"""
    role = st.role
    if role == "scout":     # 🔍 探子：只检索、不写码——把坑和可借的路子摊清楚
        cites = ([e for e in pool if e.kind == "failure"][:2]
                 + [e for e in pool if e.kind == "move"][:1])
        warned = "；".join(e.text.split("—", 1)[-1].strip() for e in cites
                          if e.kind == "failure") or "没翻到同类栽过的记录"
        return Finding(role, st.title,
                       summary=f"先看清坑：{warned}",
                       approach="只检索不动手，把已知坑与可借招式交给工匠",
                       est_lines=0, cites=cites)
    if role == "maker":     # 🔨 工匠：据料写一个聚焦的新模块，纯标准库、对齐风格
        cites = [e for e in pool if e.kind in ("move", "success")][:2]
        return Finding(role, st.title,
                       summary="写一个聚焦的新模块承接目标，纯标准库、对齐既有风格",
                       approach="从零写实现，复用领地里最近同类模块的骨架",
                       est_lines=300, wants_selftest=True, reversible=True, cites=cites)
    if role == "guard":     # 🛡 守卫：补自测、划风险闸——安全轴上它最较真
        return Finding(role, st.title,
                       summary="这事必须带自测、保持可逆，且不该碰要害器官",
                       approach="补 __main__ 自测、列回退路径，给高风险点设闸",
                       est_lines=60, wants_selftest=True, reversible=True)
    if role == "navigator":  # 🧭 向导：接线集成，可能要轻碰主循环
        cites = [e for e in pool if e.kind == "move"][:1]
        return Finding(role, st.title,
                       summary="把新本事接进既有调用链，并对齐硬约束",
                       approach="在 crab.py 心跳处补一处软引入式调用，缺席能退化",
                       est_lines=40, touches=["crab.py"],
                       wants_selftest=True, reversible=True, cites=cites)
    # 未知角色：给一份中性回执，绝不抛异常打断派遣
    return Finding(role, st.title or role, summary="(未知角色，按中性处理)", est_lines=80)


def _verify(f: Finding, *, goal: str, constraints: list) -> None:
    """这只分身自验它那段的风险：优先借 simulator 沙盘脑子，装不上就本地兜底。"""
    try:
        import simulator
        sb = simulator.Sandbox(
            name=f.title, approach=f.approach,
            new_modules=1 if f.role == "maker" else 0,
            est_lines=f.est_lines, touches=list(f.touches),
            has_selftest=f.wants_selftest, reversible=f.reversible)
        simulator.appraise(sb, goal=goal, constraints=constraints)
        f.risk = sb.risk
        f.risk_notes = list(sb.failure_chain)
        return
    except Exception:
        pass
    _verify_local(f)


def _verify_local(f: Finding) -> None:
    """沙盘缺席时的本地兜底自验（与 simulator 口径大体对齐，保守取重）。"""
    vital = f.touches_vital()
    risk = (2 if vital else 0) + (0 if f.wants_selftest else 2) \
        + (0 if f.reversible else 1) + (1 if f.est_lines >= _BIG_LINES else 0)
    notes: list = []
    if vital:
        notes.append(f"动了要害器官 {', '.join(vital)}")
    if not f.wants_selftest:
        notes.append("没有自测兜底 → 回归不会被当场发现")
    if not f.reversible:
        notes.append("难回退 → 翻车成本高")
    f.risk = risk
    f.risk_notes = notes


# ── 一次派遣：汇总各分身的回执，理出冲突/共识/最终次序 ───────────────
@dataclasses.dataclass
class Delegation:
    """一次分工派遣：同一目标横切出的子任务 + 各分身回执 + 冲突 + 共识 + 落地次序。"""
    goal: str
    constraints: list = dataclasses.field(default_factory=list)
    subtasks: list = dataclasses.field(default_factory=list)     # list[Subtask]
    findings: list = dataclasses.field(default_factory=list)     # list[Finding]
    at: str = ""

    def conflicts(self) -> list[str]:
        """摊出分身们各执一词的轴：规模 / 碰要害 / 补自测 / 可逆。"""
        fs = self.findings
        coders = [f for f in fs if f.est_lines]     # 只让真要写码的分身参与规模分歧
        out: list[str] = []

        def _bucket(n: int) -> str:
            return "小" if n < 150 else ("中" if n < _BIG_LINES else "大")
        if len({_bucket(f.est_lines) for f in coders}) > 1:
            spread = ", ".join(f"{f.title.split()[-1]}{f.est_lines}行" for f in coders)
            out.append(f"改动规模有分歧：{spread}")
        if len({bool(f.touches_vital()) for f in fs}) > 1:
            who = [f.title.split()[-1] for f in fs if f.touches_vital()]
            out.append(f"是否碰要害器官有分歧：{'、'.join(who)} 要碰，其余不碰")
        if len({f.wants_selftest for f in fs}) > 1:
            who = [f.title.split()[-1] for f in fs if not f.wants_selftest]
            out.append(f"要不要补自测有分歧：{'、'.join(who)} 想省")
        if len({f.reversible for f in fs}) > 1:
            who = [f.title.split()[-1] for f in fs if not f.reversible]
            out.append(f"可逆性有分歧：{'、'.join(who)} 的那段难回退")
        return out

    def consensus(self) -> list[str]:
        """摊出分身们都同意的点——共识是拼方案时最稳的地基。"""
        fs = self.findings
        if len(fs) < 2:
            return []
        out: list[str] = []
        if all(f.wants_selftest for f in fs):
            out.append("各分身都同意这事该带自测")
        if all(f.reversible for f in fs):
            out.append("各分身都同意保持可逆")
        if all(not f.touches_vital() for f in fs):
            out.append("各分身都同意不碰要害器官")
        return out

    def resolutions(self) -> list[str]:
        """冲突一律从稳收口：安全轴(自测/要害/可逆)上守卫的稳健主张优先。"""
        fs = self.findings
        out: list[str] = []
        if any(not f.wants_selftest for f in fs):
            out.append("自测分歧 → 从稳：最终方案一律带自测")
        vital = sorted({v for f in fs for v in f.touches_vital()})
        if vital:
            out.append(f"碰要害分歧 → 从稳：最终方案不碰 {', '.join(vital)}，"
                       "集成改走软引入/缺席退化")
        if any(not f.reversible for f in fs):
            out.append("可逆分歧 → 从稳：最终方案保留回退路径")
        return out

    def total_lines(self) -> int:
        return sum(f.est_lines for f in self.findings)

    def total_risk(self) -> int:
        """从稳收口后的总风险：去掉「碰要害/省自测/不可逆」这些会被收口掉的扣分。"""
        return sum(max(0, f.risk
                       - (2 if f.touches_vital() else 0)
                       - (0 if f.wants_selftest else 2)
                       - (0 if f.reversible else 1)) for f in self.findings)

    def order(self) -> list[Subtask]:
        """据子任务声明的依赖排出推进次序（稳定拓扑序，遇环则按原序兜底不死循环）。"""
        done: list[str] = []
        remaining = list(self.subtasks)
        ordered: list[Subtask] = []
        while remaining:
            progressed = False
            for st in list(remaining):
                if all(d in done for d in st.deps):
                    ordered.append(st)
                    done.append(st.role)
                    remaining.remove(st)
                    progressed = True
            if not progressed:                  # 依赖成环：把剩下的按原序接上，绝不卡死
                ordered.extend(remaining)
                break
        return ordered

    def plan_steps(self):
        """把汇总后的子任务拼成 planner 的多步：依赖照搬、安全轴从稳写进回退。"""
        try:
            from planner import Step
        except Exception:
            return None
        steps = []
        for st in self.order():
            f = next((x for x in self.findings if x.role == st.role), None)
            what = f.summary if (f and f.summary) else st.brief
            fb = "退回上一步重做" if st.deps else "缩小这块的范围、先做更小验证"
            if st.role == "guard":
                fb = "没过就退回工匠那段重写"
            steps.append(Step(id=st.role, what=what, depends_on=list(st.deps),
                              milestone=(st.role in ("maker", "guard")), fallback=fb))
        return steps

    def to_dict(self) -> dict:
        return {"at": self.at, "goal": self.goal, "constraints": list(self.constraints),
                "subtasks": [s.to_dict() for s in self.subtasks],
                "findings": [f.to_dict() for f in self.findings],
                "conflicts": self.conflicts(), "consensus": self.consensus(),
                "resolutions": self.resolutions(),
                "order": [s.role for s in self.order()],
                "total_lines": self.total_lines(), "total_risk": self.total_risk()}

    def render(self) -> str:
        lines = [f"🐜  分工派遣 · 目标：{self.goal[:60]}"]
        if self.constraints:
            lines.append("   约束：" + " ｜ ".join(self.constraints))
        lines.append("")
        if not self.findings:
            lines.append("   （没有派出任何分身——先用 --roles 选几只、或别把它们都筛掉。）")
            return "\n".join(lines)

        lines.append("   分身回执：")
        for f in self.findings:
            lines.append(f.render())
            lines.append("")

        con, cf, res = self.consensus(), self.conflicts(), self.resolutions()
        if con:
            lines.append("   🤝 共识：" + "；".join(con))
        if cf:
            lines.append("   ⚔️ 冲突：")
            for c in cf:
                lines.append(f"      · {c}")
        if res:
            lines.append("   🧷 从稳收口：")
            for r in res:
                lines.append(f"      · {r}")
        lines.append("")

        seq = " → ".join(s.title.split()[-1] for s in self.order())
        lines.append(f"   👉 落地次序：{seq}")
        lines.append(f"      合计约 {self.total_lines()} 行、收口后总风险 -{self.total_risk()}；"
                     "用 --kickoff 把这份方案交给 planner 起计划。")
        return "\n".join(lines)


# ── 核心：开一次派遣 ────────────────────────────────────────────────
def delegate(goal: str, roles: list | None = None,
             constraints: list | None = None) -> Delegation:
    """把目标横切成子任务，派几只临时分身分头跑「检索→实现→验证」，汇成一次派遣。

    任一分身/任一证据井缺席都从容跳过；只要还有一只分身干得了活，派遣照常成。
    """
    goal = (goal or "").strip() or "(未命名目标)"
    constraints = constraints or []
    subtasks = decompose(goal, roles)
    pool = _gather_evidence(goal)
    findings = [dispatch(st, pool, goal=goal, constraints=constraints) for st in subtasks]
    return Delegation(goal=goal, constraints=constraints,
                      subtasks=subtasks, findings=findings)


# ── 落地 / 回看 ─────────────────────────────────────────────────────
def save(d: Delegation) -> Delegation:
    """把一次派遣追加一份快照到 state/delegate/runs.jsonl；写入异常一律吞掉，绝不反噬。"""
    d.at = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        _DELEGATE_DIR.mkdir(parents=True, exist_ok=True)
        with _RUNS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(d.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass        # 派遣台是参谋，落档失败也绝不弄死这只生命
    return d


def run(goal: str, roles: list | None = None,
        constraints: list | None = None) -> Delegation:
    """开一次派遣并落档，供心跳动手前「把大事拆开、几个自己并行覆盖更多面」时调用。"""
    return save(delegate(goal, roles, constraints))


def recent(limit: int = 10) -> list[dict]:
    """读出最近落档的派遣快照(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _RUNS.exists():
        return []
    out: list[dict] = []
    for line in _RUNS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


def kickoff(goal: str, roles: list | None = None,
            constraints: list | None = None) -> dict:
    """把汇总后的最终方案(从稳收口的多步)直接交给 planner 落成一份计划。

    这是派遣台唯一一处「越过参谋身份去推一把」的动作，且仍只动 planner（不动手改代码、
    不替 judge 拍板）。没派出分身/planner 缺席时从容返回说明，绝不抛异常打断心跳。
    """
    d = save(delegate(goal, roles, constraints))
    if not d.findings:
        return {"ok": False, "reason": "没有派出任何分身，无从汇总"}
    steps = d.plan_steps()
    if steps is None:
        return {"ok": False, "reason": "planner 没接上，只出了方案没落计划"}
    try:
        import planner
        plan = planner.plan_goal(goal, steps)
        return {"ok": True, "goal": goal, "steps": len(plan.steps),
                "order": [s.role for s in d.order()]}
    except Exception as e:
        return {"ok": False, "reason": f"planner 没接上：{e}"}


# ── CLI ─────────────────────────────────────────────────────────────
_ROLES = ["scout", "maker", "guard", "navigator"]


def _cmd_recent(n: int = 10) -> None:
    rows = recent(n)
    if not rows:
        print("🐜  还没有落档的派遣（给我一个目标、或用 run(...) 后再来看）。")
        return
    print(f"🐜  最近 {len(rows)} 次派遣：")
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        goal = str(r.get("goal", ""))[:36]
        fs = r.get("findings") or []
        order = " → ".join(r.get("order") or []) or "—"
        print(f"  {ts}  {goal}  ({len(fs)} 只分身 → 次序 {order})")


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="delegate.py",
        description="🐜 分工协作派遣台：把目标拆成可并行子任务，派几只临时分身分头检索/实现/验证后汇总",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("goal", nargs="*", help="进化目标 / 要做的事")
    ap.add_argument("--roles", default="",
                    help=f"只派指定分身（逗号分隔，可选 {'/'.join(_ROLES)}；默认全派）")
    ap.add_argument("--constraint", action="append", default=[],
                    help="一条硬约束（可多次），如「纯标准库」「别碰 crab.py」")
    ap.add_argument("--kickoff", action="store_true",
                    help="把汇总方案直接交给 planner 起一份计划（把分工结果落成行动）")
    ap.add_argument("--recent", action="store_true", help="回看最近落档的派遣后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    goal = " ".join(args.goal)
    if not goal:
        ap.error("请给一个目标描述（或用 --recent）")

    names = [s.strip() for s in args.roles.split(",") if s.strip()] or None
    if names:
        bad = [s for s in names if s not in _ROLES]
        if bad:
            ap.error(f"未知分身 {bad}；可选：{'/'.join(_ROLES)}")

    if args.kickoff:
        out = kickoff(goal, names, args.constraint)
        if out.get("ok"):
            print(f"🐜  已汇总并发起：planner 就这份分工方案起了一份 {out['steps']} 步的计划"
                  f"（次序 {' → '.join(out['order'])}）。")
            print("    用 `python planner.py --show` 看路线。")
        else:
            print(f"🐜  没能发起：{out.get('reason', '未知原因')}")
        return

    print(run(goal, names, args.constraint).render())


if __name__ == "__main__":
    main()
