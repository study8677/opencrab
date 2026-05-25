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
_RUNS = _SIM_DIR / "runs.jsonl"                      # 每次推演的快照(可回看)

# 领地的要害器官：方案要碰它们，风险与失败链都天然更重。
# 软对齐 judge 的同名清单，拿不到就用本地兜底，绝不因 import 失败而崩。
try:
    from judge import _VITAL as _VITAL          # type: ignore
except Exception:                               # pragma: no cover
    _VITAL = {"crab.py", "hands.py", "checkup.py", "audit.py",
              "capabilities/__init__.py"}

_BIG_LINES = 400        # 单方案「巨改」阈值：超过就按高复审成本+回归面算
_WIDE_FILES = 12        # 改动面「失控」阈值：碰这么多文件多半一次想干太多


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


def save(sim: Simulation) -> Simulation:
    """把推演追加一份快照到 state/simulator/runs.jsonl；写入异常一律吞掉，绝不反噬。"""
    sim.at = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        _SIM_DIR.mkdir(parents=True, exist_ok=True)
        with _RUNS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sim.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass        # 推演官是参谋，落档失败也绝不弄死这只生命
    return sim


def recent(limit: int = 10) -> list:
    """读出最近落档的推演快照(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _RUNS.exists():
        return []
    out: list = []
    for line in _RUNS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


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
    ap.add_argument("--recent", action="store_true", help="回看最近落档的推演后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    goal = " ".join(args.goal)
    if not goal:
        ap.error("请给一个目标描述（或用 --recent）")

    sandboxes = [_parse_sandbox(s) for s in args.sandbox] or None
    if not sandboxes:
        print("（未给 --sandbox，用保守/稳健/激进三条起手式推演；真用时请用 --sandbox 列你的方案）\n")
    sim = simulate(goal, sandboxes, args.constraint)
    print(sim.render())


if __name__ == "__main__":
    main()
