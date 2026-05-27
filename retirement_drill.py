#!/usr/bin/env python3
"""低热低信任退役演练 ⚰️🧪 —— 替每个退役候选**真去证一遍替代路径**，证不出就不许删/并/降级。

为什么要有它：代谢和长大一样重要——变强若只会往身上加壳，迟早被堆积的器官拖垮。可
「该退役谁」这一步，领地里已有三层观测和一道闸：

  · `usageheat` 标出谁冰封（冷 + 证据过期）；
  · `trustscore`/`evidence` 标出谁低信任（无声明 / 分低）；
  · `retirementgate` 把二者对齐，给冰封器官开「复验单 / 退役单」；
  · `lifecycle` 在真退役那一步设硬闸：进入 retired 必须带 before/after 证据对照。

但中间塌着一个洞：**没有谁真去证明「这器官的活，别处接得住」**。`retirementgate` 的退役单
只是把 `lifecycle` 的闸门文字**原样抄一遍**（「指明继任者、补 before/after」）——它不查继任者
到底登记没、那扇门今天推不推得开、它的证据可不可信。于是 before/after 仍可能是**临到删才
现编的两句话**，闸门看着齐备，实则没人真证过替代路径活着。结果要么不敢删（壳越积越厚），
要么凭感觉删（裸奔退役，删了才发现没人接）。

退役演练补的就是这一步：把「证明替代路径」从一句口号变成**一次真探测**。它只观测、只编排，
**绝不删一个字节、绝不改 lifecycle 账本**——它做三件事：

  1) 🎯 **挑候选**：拿 `retirementgate` 的候选单，取最该代谢的前 N 个（默认 3）——
        冰封（低热）且无可复跑证据 / 信任分低（低信任）的器官最先上演练台。
  2) 🧪 **证替代路径**：对每个候选，从 `lifecycle` 账本读它**登记过的继任者**（successor），
        再逐项**真去证**这条替代路径活着：
          · 📁 继任者文件**在不在**领地里；
          · 🚪 继任者入口**推不推得开**（navigator 实跑 `--help`，--probe 时）；
          · 🎚️ 继任者证据**可不可信**（trustscore 的合成信任分）。
        三项全绿 = 替代路径**已证**；缺继任者 / 文件没了 / 门推不开 = **证不出**。
  3) ⚖️ **据证定夺**：只有替代路径**证到位**才给得出动作，且区分删 / 并 / 降级：
          · ⚰️ **退役（删）**：替代已证，且候选**自己没有独有的可复跑证据**——活已被接走、
                删不留窟窿，可走 `lifecycle` 退役流程；
          · 🔀 **归并（并）**：替代已证，但候选**有自己的独有验证行为**——别直接删，把这块
                行为折进继任者再退，免得丢掉一份真在跑的证据；
          · 🪫 **降级**：继任者在、门也开，但它**证据还不可信**——替代只证了一半，先把候选
                降到 `deprecated`（指明继任者、宣告将退），等继任者证据转绿再全退；
          · 🚧 **不许动（block）**：没登记继任者 / 继任者文件没了 / 门推不开——替代路径**证不出**，
                故**留人**，并点名「要动它，先补上哪一步」。

每个候选都附一份**据真信号起草的 before/after**：before 取自它退役前的真实活计（usageheat
自述 + 近窗点名 + 自有证据状态），after 取自这次替代探测的实证（继任者存活 + 证据状态）。
这正是 `lifecycle` 退役闸要的那两份——但**不是临删现编，而是这次演练真探出来的**。
关键纪律（与 degrade 同源）：**证不出替代路径的候选，after 一栏一律留空**，绝不编一句
「已被接管」来骗过闸门——演练最忌讳的就是给人虚假的安心。

判准：退役演练是**观测者 / 编排者**——只读 retirementgate/lifecycle/navigator/trustscore 的
manifest，绝不写 lifecycle 账本、不改任何源文件、不执行删除、不替谁决定删留。任一处信号读不到，
那一维记「未知」并据此保守降级判断（宁可 block，绝不臆测一条替代路径成立）。动作是**建议**，
默认不让退出码非零；`--gate` 下仅当存在「替代已证、可净删」的退役候选才轻推非零（清账提醒）。

用法：
    python retirement_drill.py            # 演练前 3 个候选：逐个证替代路径 + 给出删/并/降级/不许动
    python retirement_drill.py --top 5    # 改演练候选数（默认 3）
    python retirement_drill.py --probe    # 真去推继任者入口的 --help（替代路径证得更实）
    python retirement_drill.py --days 14  # retirementgate/usageheat 的回溯窗口（默认 7）
    python retirement_drill.py --quiet    # 只在有候选时说话（适合钩子 / CI）
    python retirement_drill.py --gate     # 有「替代已证、可净删」的候选即退出码非零（清账轻推）
    python retirement_drill.py --json     # 机读：每个候选的替代探测、定夺与 before/after 草稿
    python retirement_drill.py --selfcheck # 自检：替代闸/定夺逻辑/「证不出不填 after」都成立（供 evidence）

退出码：默认恒 0（动作只是建议）。仅 --gate 时，存在可净删候选→1，否则 0；--selfcheck 失败→1。
演练快照落在被 .gitignore 的 state/ 下（每次重写），写盘失败绝不反噬。零第三方依赖，纯标准库。
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

REPORT_PATH = REPO_ROOT / "state" / "retirement_drill" / "report.jsonl"

# ── 四种定夺 ──────────────────────────────────────────────────────────
DISPOSITION_RETIRE = "retire"     # ⚰️ 删：替代已证 + 候选无独有证据 → 可净删
DISPOSITION_MERGE = "merge"       # 🔀 并：替代已证 + 候选有独有证据 → 折进继任者再退
DISPOSITION_DEGRADE = "degrade"   # 🪫 降级：继任者在但证据未转绿 → 先降到 deprecated
DISPOSITION_BLOCK = "block"       # 🚧 不许动：替代路径证不出 → 留人，先补缺口

_DISP_ICON = {DISPOSITION_RETIRE: "⚰️", DISPOSITION_MERGE: "🔀",
              DISPOSITION_DEGRADE: "🪫", DISPOSITION_BLOCK: "🚧"}
_DISP_WORD = {DISPOSITION_RETIRE: "退役(删)", DISPOSITION_MERGE: "归并(并)",
              DISPOSITION_DEGRADE: "降级", DISPOSITION_BLOCK: "不许动"}
# 排序：最该看的（证不出/有阻力的）在前，可净删的在后（动作明确、风险低）。
_ORDER = (DISPOSITION_BLOCK, DISPOSITION_DEGRADE, DISPOSITION_MERGE, DISPOSITION_RETIRE)

DEFAULT_TOP = 3


def _stem(name: str) -> str:
    """把 'foo.py' / 'foo' 统一成 'foo'，好让各处信号对齐到同一个器官。"""
    return name[:-3] if name.endswith(".py") else name


# ── 替代路径探测：把「别处接得住」从口号变成一次真探测 ──────────────────────
@dataclasses.dataclass
class SubstituteProof:
    """一条替代路径的探测结果：继任者是谁、它活着没、证据信不信得过。"""
    successor: str = ""               # 登记过的继任者 stem（未登记→空）
    exists: bool = False              # 继任者文件在不在领地里
    alive: bool | None = None         # 入口推不推得开（None=未探测）
    trust_state: str | None = None    # 继任者证据状态 fresh/stale/broken/unproven/None
    trust_score: float | None = None  # 继任者合成信任分
    trusted: bool = False             # 信任分是否到「可信」档
    reasons: list[str] = dataclasses.field(default_factory=list)

    @property
    def proven(self) -> bool:
        """替代路径**完全证到位**：继任者登记了、文件在、门开着、证据可信。"""
        return bool(self.successor) and self.exists and (self.alive is not False) and self.trusted

    @property
    def partial(self) -> bool:
        """只证了一半：继任者在、门也没塌，但证据还不可信。"""
        return (bool(self.successor) and self.exists
                and (self.alive is not False) and not self.trusted)

    def to_meta(self) -> dict:
        return {
            "successor": self.successor, "exists": self.exists, "alive": self.alive,
            "trust_state": self.trust_state,
            "trust_score": round(self.trust_score, 4) if self.trust_score is not None else None,
            "trusted": self.trusted, "proven": self.proven, "partial": self.partial,
            "reasons": self.reasons,
        }


@dataclasses.dataclass
class Drill:
    """一个候选跑完整场演练：候选画像 + 替代探测 + 定夺 + before/after 草稿。"""
    name: str
    summary: str
    mentions: int
    has_claim: bool                 # 候选自己有没有可复跑的独有证据
    stage: str | None
    proof: SubstituteProof
    disposition: str
    reasons: list[str]
    before: str                     # 退役前它的真实活计（lifecycle 退役闸要的 before）
    after: str                      # 这次替代探测的实证；证不出则留空（绝不现编）

    def to_meta(self) -> dict:
        return {
            "name": self.name, "summary": self.summary, "mentions": self.mentions,
            "has_claim": self.has_claim, "stage": self.stage,
            "proof": self.proof.to_meta(),
            "disposition": self.disposition,
            "disposition_word": _DISP_WORD[self.disposition],
            "reasons": self.reasons,
            "evidence_draft": {"before": self.before, "after": self.after},
        }


# ── 三处信号：各自尽力而为，读不到就降级，绝不臆测 ──────────────────────────
def _candidates(top: int, days: int, probe: bool) -> list:
    """从 retirementgate 取最该代谢的前 top 个候选（冰封 × 低信任，退役单优先）。读不到回空。"""
    try:
        import retirementgate
        cands = retirementgate.build(days=days, probe=probe)
    except Exception:
        return []
    # retirementgate 已按 退役单→复验单→悬而未决 排好序（退役/复验单正是低信任候选，悬而未决排末），
    # 直接取前 top 个即「最该代谢」的——上游排序变了这里会跟着变，不另立一套口径。
    return cands[:max(0, top)]


def _successors() -> dict[str, str]:
    """从 lifecycle 账本折出「每个器官登记过的继任者」（stem→stem）。读不到回空。

    一个器官可能多次迁移，取最后一次非空 successor 为准（与 current_stages 折叠同源）。
    """
    try:
        import lifecycle
        caps = lifecycle.current_stages()
    except Exception:
        return {}
    out: dict[str, str] = {}
    for cap in caps:
        try:
            recs = lifecycle.history(cap)
        except Exception:
            continue
        for rec in recs:
            succ = (rec.get("successor") or "").strip()
            if succ:
                out[_stem(cap)] = _stem(succ)
    return out


def _roster_and_alive(probe: bool) -> tuple[set[str], dict[str, bool | None]]:
    """从 navigator 取器官名册（存活探测可选）；缺席则退回扫根目录 *.py，存活记未知。"""
    try:
        import navigator
        entries = navigator.survey(probe=probe)
        roster = {e.name for e in entries}
        alive = {e.name: e.alive for e in entries}
        return roster, alive
    except Exception:
        roster = {p.stem for p in REPO_ROOT.glob("*.py") if not p.stem.startswith("_")}
        return roster, {}


def _trust_by_name() -> dict[str, object]:
    """从 trustscore 取每条声明的信任画像。读不到回空。"""
    try:
        import trustscore
        return {t.name: t for t in trustscore.assess()}
    except Exception:
        return {}


# ── 证一条替代路径（纯函数：吃信号、吐判定，好被自检喂合成数据）──────────────
def prove_substitute(successor: str, *, roster: set[str],
                     alive: dict[str, bool | None],
                     trusts: dict[str, object]) -> SubstituteProof:
    """对一个登记过的继任者，逐项证它的替代路径是否活着。

    successor 为空 = 候选根本没登记继任者 → 替代路径无从证起（exists=False，必 block）。
    """
    p = SubstituteProof(successor=successor)
    if not successor:
        p.reasons.append("候选没在 lifecycle 登记继任者——无处可证「别处接得住」")
        return p

    p.exists = successor in roster
    if not p.exists:
        p.reasons.append(f"登记的继任者 {successor}.py 在领地里找不到——替代路径已断")
        return p

    p.alive = alive.get(successor)  # True/False/None(未探测)
    if p.alive is False:
        p.reasons.append(f"继任者 {successor}.py 入口推不开——这扇门今天就是坏的，接不住活")
        return p

    t = trusts.get(successor)
    if t is not None:
        p.trust_state = getattr(t, "state", None)
        p.trust_score = getattr(t, "score", None)
        p.trusted = bool(getattr(t, "trusted", False))
    if p.trusted:
        score = f"{p.trust_score:.2f}" if p.trust_score is not None else "?"
        p.reasons.append(f"继任者 {successor}.py 入口可达、证据🟢可信(信任分 {score})——替代路径已证")
    elif t is not None:
        score = f"{p.trust_score:.2f}" if p.trust_score is not None else "?"
        p.reasons.append(f"继任者 {successor}.py 入口可达，但证据还不可信(信任分 {score}/{p.trust_state})"
                         "——替代只证了一半")
    else:
        p.reasons.append(f"继任者 {successor}.py 入口可达，但它自己没有可复跑证据声明"
                         "——接得住活这点尚无证据，替代只证了一半")
    return p


# ── 据证定夺：只有替代证到位才给得出动作，且区分删/并/降级 ──────────────────
def decide(*, has_claim: bool, proof: SubstituteProof) -> tuple[str, list[str]]:
    """据替代探测结果定夺这个候选该怎么代谢，并记下「为什么是这个动作」。"""
    reasons: list[str] = []
    if proof.proven:
        if not has_claim:
            reasons.append("替代路径已证 + 候选自己没有独有的可复跑证据 → 活已被接走，删不留窟窿")
            return DISPOSITION_RETIRE, reasons
        reasons.append("替代路径已证，但候选有自己的独有验证行为 → 别直接删，"
                       "把这块行为折进继任者再退，免得丢一份真在跑的证据")
        return DISPOSITION_MERGE, reasons
    if proof.partial:
        reasons.append("继任者在、门也开，但它证据还不可信 → 替代只证一半，"
                       "先把候选降到 deprecated（指明继任者、宣告将退），待继任者证据转绿再全退")
        return DISPOSITION_DEGRADE, reasons
    # 证不出：留人。把缺在哪原样带出（来自 proof.reasons）。
    reasons.append("替代路径证不出 → 留人；要动它，先补上替代路径的这道缺口：")
    reasons.extend(f"· {r}" for r in proof.reasons)
    return DISPOSITION_BLOCK, reasons


# ── before/after 草稿：before 据退役前真实活计，after 据这次替代实证（证不出则留空）──
def _draft_evidence(cand, proof: SubstituteProof, disposition: str) -> tuple[str, str]:
    """起草 lifecycle 退役闸要的 before/after。

    纪律：证不出替代路径（block）→ after **一律留空**，绝不编一句「已被接管」骗过闸门。
    """
    claim = "有自己的独有可复跑证据" if cand.has_claim else "没有独有的可复跑证据"
    before = (f"退役前它的活：{cand.summary}；近窗口被点名 {cand.mentions} 次，{claim}。")

    if disposition == DISPOSITION_BLOCK:
        return before, ""  # 证不出替代 → after 留空，让 lifecycle 闸门当场拦下（这正是想要的）

    succ = proof.successor
    if disposition == DISPOSITION_RETIRE:
        score = f"，信任分 {proof.trust_score:.2f}" if proof.trust_score is not None else ""
        after = (f"这活已由 {succ}.py 接管：入口存活✅、证据🟢可信{score}；"
                 f"候选自身无独有证据，删不留窟窿。")
    elif disposition == DISPOSITION_MERGE:
        after = (f"这活由 {succ}.py 接管：入口存活✅、证据🟢可信；但候选有独有验证行为，"
                 f"应先把这块行为折进 {succ}.py（并附回归），再退候选——别丢这份证据。")
    else:  # DEGRADE
        after = (f"继任者 {succ}.py 入口存活，但其证据尚未转绿({proof.trust_state})；"
                 f"故只降级到 deprecated、指明继任者 {succ}.py，待继任者证据可信后再补全 after 退役。")
    return before, after


# ── 合成：把候选 × 替代探测 × 定夺 串成一场演练 ──────────────────────────
def build(top: int = DEFAULT_TOP, days: int = 7, probe: bool = False) -> list[Drill]:
    """演练前 top 个退役候选：逐个证替代路径、定夺、起草 before/after（按定夺排序）。"""
    cands = _candidates(top, days, probe)
    if not cands:
        return []
    successors = _successors()
    roster, alive = _roster_and_alive(probe)
    trusts = _trust_by_name()

    drills: list[Drill] = []
    for c in cands:
        proof = prove_substitute(successors.get(c.name, ""),
                                 roster=roster, alive=alive, trusts=trusts)
        disposition, reasons = decide(has_claim=c.has_claim, proof=proof)
        before, after = _draft_evidence(c, proof, disposition)
        drills.append(Drill(
            name=c.name, summary=c.summary, mentions=c.mentions,
            has_claim=c.has_claim, stage=c.stage, proof=proof,
            disposition=disposition, reasons=reasons, before=before, after=after))

    rank = {d: i for i, d in enumerate(_ORDER)}
    drills.sort(key=lambda d: (rank[d.disposition], d.name))
    return drills


def summarize(drills: list[Drill]) -> dict[str, int]:
    out = {d: 0 for d in _ORDER}
    for dr in drills:
        out[dr.disposition] += 1
    return out


def manifest(top: int = DEFAULT_TOP, days: int = 7, probe: bool = False) -> dict:
    """机读：全演练画像 + 各定夺计数。"""
    drills = build(top=top, days=days, probe=probe)
    return {
        "top": top, "days": days, "probed": probe, "total": len(drills),
        "counts": summarize(drills),
        "drills": [d.to_meta() for d in drills],
    }


# ── 演练快照：落在 gitignore 的 state/ 下，每次重写 ─────────────────────────
def write_report(drills: list[Drill]) -> bool:
    """把演练报告写成快照（整文件重写）。写盘尽力而为，失败被吞，绝不反噬。"""
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REPORT_PATH.open("w", encoding="utf-8") as f:
            for d in drills:
                f.write(json.dumps(d.to_meta(), ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001 —— 快照是副产物，写不出也不该拖垮演练
        return False


# ── 渲染 ─────────────────────────────────────────────────────────────
def _render(drills: list[Drill], top: int, probed: bool) -> str:
    L = [f"⚰️🧪 opencrab 低热低信任退役演练 —— 证明替代路径后才删/并/降级"
         f"（取前 {top} 个候选{'，已实跑继任者入口' if probed else ''}）", ""]
    if not drills:
        L.append("🦀 没有退役候选：在用的器官要么不冷，要么证据还新鲜——无需代谢。")
        return "\n".join(L)

    for d in drills:
        stage = f"，生命周期 {d.stage}" if d.stage else ""
        L.append(f"{_DISP_ICON[d.disposition]} {_DISP_WORD[d.disposition]}："
                 f"{d.name}.py — {d.summary}（点名 {d.mentions} 次{stage}）")
        # 替代探测过程（这次真探出来的，不是抄闸门文字）
        for r in d.proof.reasons:
            L.append(f"      🧪 {r}")
        for why in d.reasons:
            L.append(f"      · {why}")
        # before/after 草稿
        L.append(f"      📋 before：{d.before}")
        if d.after:
            L.append(f"      📋 after ：{d.after}")
        else:
            L.append(f"      📋 after ：（空——替代路径证不出，绝不现编『已被接管』骗过 lifecycle 闸门）")
        L.append("")

    counts = summarize(drills)
    bar = "  ".join(f"{_DISP_ICON[d]}{_DISP_WORD[d]} {counts[d]}" for d in _ORDER)
    L.append(f"分布：{bar}")
    if counts[DISPOSITION_RETIRE] or counts[DISPOSITION_MERGE] or counts[DISPOSITION_DEGRADE]:
        L.append("⚖️  动作只是建议：真要删/并/降级，仍须走 lifecycle.record_transition，"
                 "把上面这次演练探出的 before/after 摆上桌——演练负责证替代，落账仍归生命周期闸门。")
    if counts[DISPOSITION_BLOCK]:
        L.append("🚧 证不出替代路径的，一律留人——先补上各自缺口（登记继任者 / 修活入口 / 让继任者证据转绿）。")
    return "\n".join(L)


# ── 自检（供 evidence 复跑；全程合成数据，确定性、无副作用）──────────────────
def selfcheck(quiet: bool = False) -> bool:
    """自检：替代闸/定夺逻辑/「证不出不填 after」都成立，且 build/manifest 不反噬。"""
    failures: list[str] = []

    def check(cond: bool, why: str) -> None:
        if not cond:
            failures.append(why)

    class _T:  # 合成一条 trustscore.Trust 替身
        def __init__(self, trusted, score=0.9, state="fresh"):
            self.trusted, self.score, self.state = trusted, score, state

    roster = {"succ_ok", "succ_dead", "succ_untrusted"}
    alive = {"succ_ok": True, "succ_dead": False, "succ_untrusted": True}
    trusts = {"succ_ok": _T(True), "succ_untrusted": _T(False, 0.3, "stale")}

    # 1) 替代路径探测：四种处境各归各位
    p_none = prove_substitute("", roster=roster, alive=alive, trusts=trusts)
    check(not p_none.proven and not p_none.partial, "没登记继任者不该算证到位/半证")
    p_missing = prove_substitute("ghost", roster=roster, alive=alive, trusts=trusts)
    check(not p_missing.exists and not p_missing.proven, "继任者文件不存在该判证不出")
    p_dead = prove_substitute("succ_dead", roster=roster, alive=alive, trusts=trusts)
    check(p_dead.exists and p_dead.alive is False and not p_dead.proven,
          "继任者门推不开该判证不出")
    p_untrust = prove_substitute("succ_untrusted", roster=roster, alive=alive, trusts=trusts)
    check(p_untrust.partial and not p_untrust.proven, "继任者在但证据不可信该判半证(partial)")
    p_ok = prove_substitute("succ_ok", roster=roster, alive=alive, trusts=trusts)
    check(p_ok.proven, "继任者在+门开+证据可信该判证到位(proven)")

    # 2) 定夺逻辑：证到位才给动作，且删/并/降级分得清
    disp, _ = decide(has_claim=False, proof=p_ok)
    check(disp == DISPOSITION_RETIRE, f"替代已证+无独有证据该判退役(删)，实得 {disp}")
    disp, _ = decide(has_claim=True, proof=p_ok)
    check(disp == DISPOSITION_MERGE, f"替代已证+有独有证据该判归并(并)，实得 {disp}")
    disp, _ = decide(has_claim=False, proof=p_untrust)
    check(disp == DISPOSITION_DEGRADE, f"替代半证该判降级，实得 {disp}")
    for bad in (p_none, p_missing, p_dead):
        disp, _ = decide(has_claim=False, proof=bad)
        check(disp == DISPOSITION_BLOCK, f"替代证不出该判不许动(block)，实得 {disp}")

    # 3) 关键纪律：证不出 → after 必须留空，绝不现编「已被接管」
    class _C:  # 合成 retirementgate.Candidate 替身
        def __init__(self, has_claim):
            self.name, self.summary, self.mentions = "victim", "一句自述", 0
            self.has_claim, self.stage = has_claim, "stable"
    before, after = _draft_evidence(_C(False), p_none, DISPOSITION_BLOCK)
    check(bool(before) and after == "", "证不出替代时 after 必须留空(不许现编)")
    _, after_ok = _draft_evidence(_C(False), p_ok, DISPOSITION_RETIRE)
    check("接管" in after_ok and "succ_ok" in after_ok, "证到位时 after 该写清谁接管")

    # 4) 排序：可净删的退役候选排在不许动之后（最该看的在前）
    drills = [
        Drill("a", "", 0, False, "stable", p_ok, DISPOSITION_RETIRE, [], "b", "a"),
        Drill("b", "", 0, False, "stable", p_none, DISPOSITION_BLOCK, [], "b", ""),
    ]
    drills.sort(key=lambda d: ({d2: i for i, d2 in enumerate(_ORDER)}[d.disposition], d.name))
    check(drills[0].disposition == DISPOSITION_BLOCK, "不许动该排在退役之前(最该看的在前)")

    # 5) 观测者不反噬：build/manifest 结构完整、不抛（probe=False 不实跑子进程）
    try:
        m = manifest(top=1, probe=False)
        check(set(m) >= {"counts", "drills", "total"}, "manifest 字段不全")
    except Exception as e:  # noqa: BLE001
        failures.append(f"manifest 不该抛错（演练本身成了伤口）：{type(e).__name__}: {e}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ retirement_drill selfcheck：替代闸四态分明、删/并/降级/不许动判得清、"
                  "证不出绝不现编 after、观测不反噬——退役演练可信。")
        else:
            print("❌ retirement_drill selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 低热低信任退役演练 ⚰️🧪 —— 证明替代路径后才删/并/降级（不删）")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP, metavar="N",
                    help=f"演练候选数（默认 {DEFAULT_TOP}）")
    ap.add_argument("--days", type=int, default=7, metavar="N",
                    help="retirementgate/usageheat 回溯窗口天数（默认 7）")
    ap.add_argument("--probe", action="store_true",
                    help="真去推继任者入口的 --help（替代路径证得更实）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quiet", action="store_true", help="只在有候选时说话（适合钩子 / CI）")
    g.add_argument("--json", action="store_true",
                   help="机读：每个候选的替代探测、定夺与 before/after 草稿")
    g.add_argument("--selfcheck", action="store_true",
                   help="自检：替代闸/定夺逻辑/『证不出不填 after』都成立（供 evidence）")
    ap.add_argument("--gate", action="store_true",
                    help="有『替代已证、可净删』的候选即退出码非零（清账轻推）")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    if args.top < 1:
        print(f"❌ --top 需为正整数，收到 {args.top}")
        sys.exit(2)
    if args.days < 1:
        print(f"❌ --days 需为正整数，收到 {args.days}")
        sys.exit(2)

    if args.json:
        print(json.dumps(manifest(top=args.top, days=args.days, probe=args.probe),
                         ensure_ascii=False, indent=2))
        sys.exit(0)

    drills = build(top=args.top, days=args.days, probe=args.probe)
    write_report(drills)
    counts = summarize(drills)

    if args.quiet:
        if drills:
            print(f"⚰️🧪 退役演练：{counts[DISPOSITION_RETIRE]} 可净删、"
                  f"{counts[DISPOSITION_MERGE]} 待归并、{counts[DISPOSITION_DEGRADE]} 降级、"
                  f"{counts[DISPOSITION_BLOCK]} 证不出留人")
    else:
        print(_render(drills, args.top, args.probe))

    # 默认恒 0（动作只是建议）；仅 --gate 时，存在可净删候选才轻推非零。
    sys.exit(1 if (args.gate and counts[DISPOSITION_RETIRE]) else 0)


if __name__ == "__main__":
    main()
