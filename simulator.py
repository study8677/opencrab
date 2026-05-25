#!/usr/bin/env python3
"""演化沙盘 🧪 —— 在真正动手自改之前，先用目标、约束、历史记忆与计划，
预演 2~3 条「演化方案」各自的收益、风险、成本，以及可能的失败链。

为什么要有它：这只螃蟹已经会判断「这一步值不值」(judge)、会把长期目标摊成
多步路线(planner)、会听懂别人(dialogue)、会定姿态(policy)——**可它一旦决定要做
某件事，就直接冲上去动手了，行动前从不在脑子里把几种做法各跑一遍**。于是它只会
「单方案直执行」：选了一条路就埋头走，撞了南墙才知道还有别的走法，或者本可以预见
的失败链(动要害→自测挂→回归→回滚)非要真摔一跤才学会。

裁决官(judge)是**事后**复盘「这次值不值」，沙盘补的是**事前**那一层——拿同一个
目标，捏出几条不同的演化方案(保守照搬 / 稳健新模块 / 激进大改)，对每条都先在
纸面上推演一遍：

  - 收益(benefit)：这条路若走通，能长出多少新本事？(新模块 / 新技能 / 打磨)
  - 风险(risk)：它要碰要害器官吗？改动面会不会失控？可逆吗？记忆里栽过吗？
  - 成本(cost)：预计要写多少行、碰多少文件——复审与回归的代价。
  - 失败链(failure chain)：把「哪一环先松、会连环带塌成什么样」预先推演出来，
    让最坏情形在动手前就摊在台面上，而不是真摔了才知道。

它只推演、不动手，更不替 judge 拍板——沙盘给的是「先走哪条、躲开哪条」的事前建议，
真做完还得交给裁决官事后判。它软引入 memory「这类目标以前怎么栽的」给高风险方案
加码预警，也能吃 planner 的「下一步」当默认推演对象。沙盘与每次推演都落进被
.gitignore 的 state/simulator/ 下，可回溯但绝不反噬：读写出错统统吞掉，
推演官不能成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python simulator.py "<要做的事 / 目标>"          # 自动捏 3 条方案并推演、排序
    python simulator.py "<目标>" \\
        --sandbox "照搬|抄最近的同类模块改名|1|80|y|y" \\
        --sandbox "新写|从零写一个新模块|1|260|y|y" \\
        --sandbox "大改|顺手重构 crab.py 主循环|0|520|n|n"
        # --sandbox 规格：名号|做法|新模块数|预计行数|有自测(y/n)|可逆(y/n)
    python simulator.py "<目标>" --constraint "纯标准库" --constraint "别碰 crab.py"
    python simulator.py --recent                      # 回看最近落档的推演
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_SIM_DIR = _REPO_ROOT / "state" / "simulator"       # 落在被 .gitignore 的 state/ 里
_RUNS = _SIM_DIR / "runs.jsonl"                      # 每次单脑预演的快照(可回看)
_ROUNDS = _SIM_DIR / "arena.jsonl"                   # 每场多策略竞技的快照(可回看)

# 领地的要害器官：方案要碰它们，风险与失败链都天然更重。
# 软对齐 judge 的同名清单，拿不到就用本地兜底，绝不因 import 失败而崩。
try:
    from judge import _VITAL as _VITAL          # type: ignore
except Exception:                               # pragma: no cover
    _VITAL = {"crab.py", "hands.py", "checkup.py", "audit.py",
              "capabilities/__init__.py"}

_BIG_LINES = 400        # 单方案「巨改」阈值：超过就按高复审成本+回归面算
_WIDE_FILES = 12        # 改动面「失控」阈值：碰这么多文件多半一次想干太多

_EVIDENCE_CAP = 2       # 竞技场单份方案证据加减分的封顶，免得证据压过沙盘本身的净收益
_CLOSE_MARGIN = 1       # 竞技场冠亚军预期收益差 ≤ 此值即判「势均力敌」


# ── 一条演化方案（一格沙盘） ────────────────────────────────────────
@dataclasses.dataclass
class Sandbox:
    """一条可推演的演化方案：先描述「打算怎么改」，再据此推出收益/风险/成本/失败链。"""
    name: str                                   # 方案名号(保守/稳健/激进…)
    approach: str = ""                          # 这条路具体怎么做(人话)
    new_modules: int = 0                        # 预计新长出几个模块
    est_lines: int = 0                          # 预计写/改多少行
    touches: list = dataclasses.field(default_factory=list)  # 预计要碰的文件
    has_selftest: bool = True                   # 这条路打算补自测吗
    reversible: bool = True                     # 翻车了好不好退回(可逆性)

    # —— 推演产物(由 appraise 填) ——
    benefit: int = 0
    risk: int = 0
    cost: int = 0
    failure_chain: list = dataclasses.field(default_factory=list)
    reasons: list = dataclasses.field(default_factory=list)
    violations: list = dataclasses.field(default_factory=list)

    @property
    def net(self) -> int:
        """净收益 = 收益 − 风险 − 成本。沙盘据此排「先走哪条」。"""
        return self.benefit - self.risk - self.cost

    def touches_vital(self) -> list:
        """这条路预计碰到的要害器官(规范成正斜杠路径再比对)。"""
        return sorted(f for f in self.touches
                      if f.replace("\\", "/") in _VITAL)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["net"] = self.net
        return d


# ── 核心：给一条方案做事前推演 ──────────────────────────────────────
def appraise(sb: Sandbox, *, goal: str = "", constraints: list | None = None,
             memory_warn: str = "") -> Sandbox:
    """对一条方案沿收益/风险/成本三维推演，并把可能的失败链摊出来。

    保守倾向：信息不足(没自测、不可逆、记忆里栽过)时宁可把风险算重，也绝不在
    事前替一条没兜底的路打包票。就地改写 sb 的推演字段并返回它，便于链式调用。
    """
    constraints = constraints or []
    benefit = risk = cost = 0
    reasons: list = []
    chain: list = []

    # ① 收益：长出新本事最值钱，纯打磨给半分认可
    if sb.new_modules > 0:
        benefit += 2 * sb.new_modules
        reasons.append(f"预计长出 {sb.new_modules} 个新模块（收益 +{2 * sb.new_modules}）")
    elif sb.est_lines > 0:
        benefit += 1
        reasons.append("没有新模块，算打磨现有能力（收益 +1）")

    # ② 成本：行数与改动面——复审与回归的代价
    cost += sb.est_lines // 150
    if sb.est_lines >= _BIG_LINES:
        cost += 1
        reasons.append(f"预计 {sb.est_lines} 行，巨改、复审成本高（成本 +{sb.est_lines // 150 + 1}）")
    elif sb.est_lines:
        reasons.append(f"预计 {sb.est_lines} 行（成本 +{sb.est_lines // 150}）")
    if len(sb.touches) >= _WIDE_FILES:
        cost += 1
        reasons.append(f"要碰 {len(sb.touches)} 个文件，面太宽（成本 +1）")

    # ③ 风险：碰要害 / 不可逆 / 没自测 / 记忆里栽过——逐项加码，并接进失败链
    vital = sb.touches_vital()
    if vital:
        risk += 2
        reasons.append(f"要动要害器官 {', '.join(vital)}（风险 +2）")
        chain.append(f"动了要害器官 {', '.join(vital)}")
    if not sb.has_selftest:
        risk += 2
        reasons.append("不打算补自测，改动没人兜（风险 +2）")
        chain.append("没有自测兜底 → 回归不会被当场发现")
    if not sb.reversible:
        risk += 1
        reasons.append("这条路不易回退，翻车代价大（风险 +1）")
    if sb.est_lines >= _BIG_LINES:
        risk += 1
        chain.append(f"一口气 {sb.est_lines} 行 → 复审遗漏 → 藏着隐患进主干")
    if memory_warn:
        risk += 1
        reasons.append(f"记忆预警：{memory_warn}（风险 +1）")
        chain.append(f"重蹈覆辙：{memory_warn}")

    # 失败链收尾：把上面的「松动环」串成一句最坏情形
    if chain:
        tail = ("难回退、只能硬扛" if not sb.reversible else "退回分支重来")
        chain.append(f"最坏：净亏被裁决官打回 → {tail}")
    else:
        chain.append("没有明显的连环失败点——这条路就算栽也栽得轻。")

    # ④ 约束体检：逐条对照硬约束，违反的拎出来(违约本身不改分，但会压低建议)
    violations = _check_constraints(sb, constraints)
    if violations:
        reasons.append(f"踩了 {len(violations)} 条硬约束（见下）")

    sb.benefit, sb.risk, sb.cost = benefit, risk, cost
    sb.failure_chain = chain
    sb.reasons = reasons
    sb.violations = violations
    return sb


def _check_constraints(sb: Sandbox, constraints: list) -> list:
    """把方案对照每条硬约束体检，返回被踩中的约束(人话)；纯字符串启发式，宁缺毋滥。"""
    hits: list = []
    blob = f"{sb.name} {sb.approach} {' '.join(sb.touches)}".lower()
    for c in constraints:
        c = (c or "").strip()
        if not c:
            continue
        low = c.lower()
        # 「别碰 X / 不要改 X / 禁止 X」式禁令：方案若正打算碰 X，就算踩线
        for kw in ("别碰", "不要碰", "不要改", "不准", "禁止", "勿动", "don't touch", "no "):
            if kw in low:
                target = low.split(kw, 1)[1].strip(" 　：:。.")
                if target and (target in blob
                               or any(target in t.lower() for t in sb.touches)):
                    hits.append(f"违反「{c}」：方案正打算碰它")
                break
        else:
            # 「纯标准库 / 零依赖」式戒律：方案若自述要引第三方就算踩线
            if ("标准库" in low or "零依赖" in low or "no dep" in low) and \
               any(w in blob for w in ("pip", "依赖", "第三方", "install", "requirements")):
                hits.append(f"违反「{c}」：方案似乎要引第三方依赖")
    return hits


# ── 一次推演：同一目标下多条方案的对照 ──────────────────────────────
@dataclasses.dataclass
class Simulation:
    """一次事前推演：同一目标/约束下，几条方案各自的推演结果 + 一句「先走哪条」。"""
    goal: str
    constraints: list = dataclasses.field(default_factory=list)
    sandboxes: list = dataclasses.field(default_factory=list)   # list[Sandbox]
    at: str = ""

    def best(self) -> Sandbox | None:
        """挑「先走哪条」：净收益最高者优先；同分时风险更低、可逆者先走。
        踩了硬约束的方案一律压到最后——再香也不能违约。
        """
        if not self.sandboxes:
            return None
        return sorted(
            self.sandboxes,
            key=lambda s: (bool(s.violations), -s.net, s.risk, not s.reversible),
        )[0]

    def to_dict(self) -> dict:
        return {"at": self.at, "goal": self.goal,
                "constraints": list(self.constraints),
                "sandboxes": [s.to_dict() for s in self.sandboxes]}

    def render(self) -> str:
        """把推演摊成给人看的多行报告：各方案三维 + 失败链 + 事前建议。"""
        lines = [f"🧪  演化沙盘 · 目标：{self.goal[:60]}"]
        if self.constraints:
            lines.append("   约束：" + " ｜ ".join(self.constraints))
        lines.append("")
        best = self.best()
        for sb in sorted(self.sandboxes, key=lambda s: (bool(s.violations), -s.net)):
            star = " 👈 建议先走" if sb is best and not sb.violations else ""
            warn = " ⛔违约" if sb.violations else ""
            lines.append(f"   【{sb.name}】净{sb.net:+d}"
                         f"（收益+{sb.benefit} 风险-{sb.risk} 成本-{sb.cost}）{star}{warn}")
            if sb.approach:
                lines.append(f"      做法：{sb.approach}")
            for r in sb.reasons:
                lines.append(f"        · {r}")
            if sb.failure_chain:
                lines.append("      失败链：" + " → ".join(sb.failure_chain))
            for v in sb.violations:
                lines.append(f"      ⛔ {v}")
            lines.append("")

        if best is None:
            lines.append("   （没有任何方案可推演——先捏几条 --sandbox 出来。）")
        elif best.violations:
            lines.append("   ⚠️ 净收益最高的方案踩了硬约束——别走它，回去重捏一条不违约的。")
        elif best.net <= 0:
            lines.append(f"   ⚠️ 连最好的「{best.name}」净收益也不正——这事现在不值得动手，先放放。")
        else:
            lines.append(f"   👉 事前建议：先走「{best.name}」，"
                         f"动手前盯紧它的失败链头一环。")
        return "\n".join(lines)


# ── 从一句目标自动捏 2~3 条方案（给个起手式） ───────────────────────
def draft(goal: str) -> Simulation:
    """把一个目标自动摊成三条典型方案：保守照搬 / 稳健新写 / 激进大改。

    这是「起手式」而非定制——三条方案覆盖了「省事但长不出新本事」到「长得多但
    风险大」的光谱，调用方该按真实目标改写各方案的行数/碰的文件。
    会软引入 memory：这类目标以前栽过，就把预警喂给每条方案的风险维度。
    """
    goal = (goal or "").strip() or "(未命名目标)"
    warn = _recall_warning(goal)
    sandboxes = [
        Sandbox("保守·照搬", "抄领地里最接近的同类模块、改名微调，先有再好",
                new_modules=1, est_lines=90, has_selftest=True, reversible=True),
        Sandbox("稳健·新写", "从零写一个聚焦的新模块，纯标准库、补自测、对齐风格",
                new_modules=1, est_lines=300, has_selftest=True, reversible=True),
        Sandbox("激进·大改", "顺手把相关主循环一起重构，一步到位",
                new_modules=1, est_lines=560,
                touches=["crab.py"], has_selftest=False, reversible=False),
    ]
    for sb in sandboxes:
        appraise(sb, goal=goal, memory_warn=warn)
    return Simulation(goal=goal, sandboxes=sandboxes)


def _recall_warning(text: str, k: int = 2) -> str:
    """软引入 memory：这类目标以前若栽过，返回一句预警；缺/错则返回空串。"""
    try:
        import memory
        for s, ep in memory.recall(text, k=k):
            if not ep.ok and s >= 0.5:
                return f"记忆里同类目标栽过：{ep.headline()}"
    except Exception:
        pass
    return ""


# ── 落地 / 回看 ─────────────────────────────────────────────────────
def simulate(goal: str, sandboxes: list | None = None,
             constraints: list | None = None) -> Simulation:
    """从一个目标(可选自带方案/约束)做一次推演并落档，供心跳动手前调用。"""
    constraints = constraints or []
    if sandboxes:
        for sb in sandboxes:
            appraise(sb, goal=goal, constraints=constraints,
                     memory_warn=_recall_warning(goal))
        sim = Simulation(goal=goal, constraints=constraints, sandboxes=sandboxes)
    else:
        sim = draft(goal)
        sim.constraints = constraints
        if constraints:                         # 起手式也得过一遍约束体检
            for sb in sim.sandboxes:
                sb.violations = _check_constraints(sb, constraints)
    return save(sim)


# ── 共享的快照落地/回看（沙盘与竞技场同用一套，绝不各写一份） ───────
# 演化试验场是一条链：沙盘(simulator)是评估「脑子」，竞技场(arena)在其上做多方案竞争。
# 两者的「追加一份 jsonl 快照 / 读回最近 N 条」逻辑曾各写一份、字字雷同；现收敛到此处
# 由沙盘单一提供，arena 直接复用——读写出错统统吞掉，参谋落档失败绝不弄死这只生命。
def append_snapshot(path: pathlib.Path, payload: dict) -> None:
    """把一份快照追加到 path（自动建父目录）；写入异常一律吞掉，绝不反噬。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_snapshots(path: pathlib.Path, limit: int = 10) -> list:
    """读出 path 里最近 limit 条快照(时间正序)；文件缺失或坏行都从容跳过。"""
    if not path.exists():
        return []
    out: list = []
    for line in path.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


def save(sim: Simulation) -> Simulation:
    """把推演追加一份快照到 state/simulator/runs.jsonl；写入异常一律吞掉，绝不反噬。"""
    sim.at = datetime.datetime.now().isoformat(timespec="seconds")
    append_snapshot(_RUNS, sim.to_dict())
    return sim


def recent(limit: int = 10) -> list:
    """读出最近落档的推演快照(时间正序)；文件缺失或坏行都从容跳过。"""
    return read_snapshots(_RUNS, limit)


# ╔══ 多策略竞技场 🥊 ════════════════════════════════════════════════╗
# 沙盘(上半)是「单脑预演」的评估脑子；竞技场(下半)在其上做多策略竞争：把同一目标交给
# 2~3 派进化策略各出一份方案，过沙盘 appraise 打分、据各派引用的证据加减，再择优。两者
# 共用同一套要害清单/阈值/jsonl 落地——原是 arena.py 独立一模块，并入沙盘后少一层重叠、
# 评估链更直。竞技场只裁「先做哪条」，不动手、更不替 judge 拍板。
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
def _mk_steady(goal: str, pool: list) -> Proposal:
    """🐢 稳健派：先有再好。抄最近的同类模块、小步改名、补全自测、保证可逆。
    引用记忆里同类的**失败**当作「别浪」的证据——栽过的地方更该收着走。"""
    cites = [e for e in pool if e.kind == "failure"][:2]
    return Proposal(
        strategy="steady", title="🐢 稳健派",
        stance="先有再好，宁可少长一点也别翻车",
        approach="抄领地里最接近的同类模块、改名微调，补全自测、保证可逆",
        new_modules=1, est_lines=90, has_selftest=True, reversible=True, cites=cites)


def _mk_builder(goal: str, pool: list) -> Proposal:
    """🧱 营造派：从零写一个聚焦的新模块，纯标准库、补自测、对齐风格。
    引用 mentor 里可借的招式当作「有现成路子」的证据——既稳又能长出新本事。"""
    cites = ([e for e in pool if e.kind == "move"][:1]
             + [e for e in pool if e.kind == "success"][:1])
    return Proposal(
        strategy="builder", title="🧱 营造派",
        stance="稳扎稳打长出一个新本事，既不照抄也不冒进",
        approach="从零写一个聚焦的新模块，纯标准库、补自测、对齐既有风格",
        new_modules=1, est_lines=300, has_selftest=True, reversible=True, cites=cites)


def _mk_pioneer(goal: str, pool: list) -> Proposal:
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
def _gather_evidence(goal: str) -> list:
    """汇一池证据供各派引用：memory 里同类的成/败往事 + mentor 里高迁移的可借招式。
    任一口井缺席/出错都从容跳过，返回能打上来的部分。"""
    pool: list = []
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


# ── 给一份方案过沙盘 + 据证据加减 ───────────────────────────────────
def weigh(p: Proposal, *, goal: str = "", constraints: list | None = None) -> Proposal:
    """先过沙盘(本模块的 appraise)算收益/风险/成本，
    再据这一派**引用了哪些证据**给预期收益加减——就地改写 p 并返回。"""
    constraints = constraints or []
    warn = next((e.text for e in p.cites if e.kind == "failure"), "")
    sb = Sandbox(
        name=p.title, approach=p.approach, new_modules=p.new_modules,
        est_lines=p.est_lines, touches=list(p.touches),
        has_selftest=p.has_selftest, reversible=p.reversible)
    appraise(sb, goal=goal, constraints=constraints, memory_warn=warn)
    p.benefit, p.risk, p.cost = sb.benefit, sb.risk, sb.cost
    p.failure_chain, p.reasons, p.violations = sb.failure_chain, sb.reasons, sb.violations

    # 证据加减：被成功/招式背书的进取加分；冒进(碰要害或省自测)却握着失败证据则扣分。
    adj = 0
    for ev in p.cites:
        if ev.kind in ("success", "move"):
            adj += 1
        elif ev.kind == "failure" and (p.touches_vital() or not p.has_selftest):
            adj -= 1                            # 明知栽过还冒进，证据反过来压它
    p.evidence_adj = max(-_EVIDENCE_CAP, min(_EVIDENCE_CAP, adj))
    return p


# ── 一场比赛：同一目标下各派的竞争 ──────────────────────────────────
@dataclasses.dataclass
class Match:
    """一场策略竞技：同一目标/约束下各派的方案 + 分歧 + 共识 + 一句「先做哪条」。"""
    goal: str
    constraints: list = dataclasses.field(default_factory=list)
    proposals: list = dataclasses.field(default_factory=list)    # list[Proposal]
    at: str = ""

    def ranked(self) -> list:
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

    def divergence(self) -> list:
        """摊出各派吵得最凶的轴：规模 / 碰要害 / 补自测 / 可逆 / 新模块数。"""
        ps = self.proposals
        if len(ps) < 2:
            return []
        out: list = []

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

    def consensus(self) -> list:
        """摊出各派都同意的点——共识是最强的事前信号。"""
        ps = self.proposals
        if len(ps) < 2:
            return []
        out: list = []
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

    proposals: list = []
    for name in names:
        mk = _STRATEGIES.get(name)
        if mk is None:
            continue
        p = mk(goal, pool)
        weigh(p, goal=goal, constraints=constraints)
        proposals.append(p)
    return Match(goal=goal, constraints=constraints, proposals=proposals)


def save_match(match: Match) -> Match:
    """把一场比赛追加一份快照到 state/simulator/arena.jsonl；写入异常一律吞掉，绝不反噬。"""
    match.at = datetime.datetime.now().isoformat(timespec="seconds")
    append_snapshot(_ROUNDS, match.to_dict())       # 与单脑预演同用一套落地逻辑
    return match


def arena(goal: str, strategies: list | None = None,
          constraints: list | None = None) -> Match:
    """开一场比赛并落档，供心跳动手前「让几个自己先吵一架再择优」时调用。"""
    return save_match(compete(goal, strategies, constraints))


def recent_rounds(limit: int = 10) -> list:
    """读出最近落档的比赛快照(时间正序)；文件缺失或坏行都从容跳过。"""
    return read_snapshots(_ROUNDS, limit)


def kickoff(goal: str, strategies: list | None = None,
            constraints: list | None = None) -> dict:
    """择优后把胜出方案当目标直接交给 planner 起一份计划（主动把竞技结果落成行动）。

    这是竞技场唯一一处「越过参谋身份去推一把」的动作，且仍只动 planner（不动手改代码、
    不替 judge 拍板）。胜者违约/预期不正/planner 缺席时从容返回说明，绝不抛异常打断心跳。
    """
    m = save_match(compete(goal, strategies, constraints))
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
def _parse_sandbox(spec: str) -> Sandbox:
    """解析 --sandbox 规格：名号|做法|新模块数|预计行数|有自测(y/n)|可逆(y/n)。

    后面的字段都可省，省了就用默认；做法里若提到某 .py 文件，自动当作要碰它。
    """
    parts = [p.strip() for p in (spec or "").split("|")]
    name = parts[0] if parts and parts[0] else "(方案)"
    approach = parts[1] if len(parts) > 1 else ""

    def _int(i: int, default: int = 0) -> int:
        try:
            return int(parts[i])
        except (IndexError, ValueError):
            return default

    def _bool(i: int, default: bool = True) -> bool:
        if len(parts) <= i or not parts[i]:
            return default
        return parts[i].lower() in ("y", "yes", "true", "1", "是")

    # 从做法文字里捞出提到的 .py，当作这条路要碰的文件(给要害体检用)
    touches = [w.strip(" ，,。.") for w in approach.replace("，", " ").split()
               if w.strip(" ，,。.").endswith(".py")]
    return Sandbox(name=name, approach=approach,
                   new_modules=_int(2), est_lines=_int(3),
                   touches=touches, has_selftest=_bool(4), reversible=_bool(5))


def _cmd_recent(n: int = 10) -> None:
    rows = recent(n)
    if not rows:
        print("🧪  还没有落档的推演（给我一个目标、或用 simulate(...) 后再来看）。")
        return
    print(f"🧪  最近 {len(rows)} 次推演：")
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        goal = str(r.get("goal", ""))[:36]
        sbs = r.get("sandboxes") or []
        best = max(sbs, key=lambda s: s.get("net", 0), default=None)
        tag = f"  → 建议「{best.get('name', '')}」净{best.get('net', 0):+d}" if best else ""
        print(f"  {ts}  {goal}  ({len(sbs)} 条方案){tag}")


def _cmd_recent_rounds(n: int = 10) -> None:
    rows = recent_rounds(n)
    if not rows:
        print("🥊  还没有落档的比赛（给我一个目标加 --arena、或用 arena(...) 后再来看）。")
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
        prog="simulator.py",
        description="🧪 演化沙盘：动手自改前，先推演 2~3 条方案的收益/风险/成本/失败链",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("goal", nargs="*", help="要做的事 / 目标描述")
    ap.add_argument("--sandbox", action="append", default=[],
                    help="一条方案：名号|做法|新模块数|预计行数|有自测(y/n)|可逆(y/n)")
    ap.add_argument("--constraint", action="append", default=[],
                    help="一条硬约束（可多次），如「纯标准库」「别碰 crab.py」")
    ap.add_argument("--arena", action="store_true",
                    help="🥊 多策略竞技：把同一目标交给 2~3 派进化策略并行出方案后择优（原 arena.py）")
    ap.add_argument("--strategy", default="",
                    help=f"竞技场里只让指定派上场（逗号分隔，可选 {'/'.join(_STRATEGIES)}；默认全上）")
    ap.add_argument("--kickoff", action="store_true",
                    help="竞技场择优后把胜出方案直接交给 planner 起一份计划（把竞技结果落成行动）")
    ap.add_argument("--recent", action="store_true", help="回看最近落档的推演后退出")
    ap.add_argument("--recent-rounds", action="store_true",
                    help="回看最近落档的竞技比赛后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return
    if args.recent_rounds:
        _cmd_recent_rounds()
        return

    goal = " ".join(args.goal)
    if not goal:
        ap.error("请给一个目标描述（或用 --recent / --recent-rounds）")

    # 竞技场分支：多策略并行出方案、对比证据/分歧/预期收益后择优（原 arena.py 的入口）。
    if args.arena or args.strategy or args.kickoff:
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
        return

    sandboxes = [_parse_sandbox(s) for s in args.sandbox] or None
    if not sandboxes:
        print("（未给 --sandbox，用保守/稳健/激进三条起手式推演；真用时请用 --sandbox 列你的方案）\n")
    sim = simulate(goal, sandboxes, args.constraint)
    print(sim.render())


if __name__ == "__main__":
    main()
