#!/usr/bin/env python3
"""外界进件层 📥 —— 把 issue / 用户反馈，归一成一条可执行的「进化需求」。

为什么要有它：compass 指方向、prioritizer 排先后、planner 排日程——可它们消费的候选
几乎全来自**自我循环**（读自己的模块、补自己的回归）。真正的外界声音（一条 issue、
一句用户反馈）过去只是散落在 journal 里的自然语言，没有结构、没有验收、没法被排序，
于是「从外界学」永远停在「我看到了」，落不到「我据此改了什么」。

这一层就补这一环：把一段**原始外界文本**收敛成一条结构化 `Requirement`，每条都带：

  · 🔗 **证据（evidence）**：这条反馈牵动哪些**真实存在**的模块/文件 + 它的出处引用，
                            让需求不悬空——能核对到代码，也能回溯到谁提的。
  · ✅ **验收（acceptance）**：一句**可核对**的达标判据（复现用例不再触发 / 有 golden 锁住
                            / 基线度量改善），逼着「回应反馈」最终要拿证据说话。
  · 🚦 **优先级（priority）**：P0/P1/P2 + 一行可核对的定级理由（命中了哪些严重信号、
                            牵动几个模块、来自真实用户还是自我臆想）。

归一靠朴素的关键词/路径匹配，不假装懂自然语言：宁可粗、不可玄，这样才测得动、
也解释得清。需求落地成 JSONL（state/intake.jsonl），按内容去重；导出的 JSON 直接喂给
prioritizer/planner，让外界的声音和自我候选**站在同一张排序表上**被公平对待。

用法：
    python intake.py                        # 列出当前进件队列（按优先级）
    python intake.py --capture "点 cap X 会崩" [--source feedback] [--ref 用户A]
                                            # 把一段反馈当场归一成需求并落盘
    python intake.py --pull                 # 把 state/intake_inbox.jsonl 里的原始信号排空成需求
    python intake.py --json                 # 机读：导出需求队列（给 prioritizer/planner 消费）
    python intake.py --selftest             # 跑归一自检样例（判据漂了立刻暴露）

退出码：0 = 正常 / 自检全过；1 = --selftest 有样例不达标。零第三方依赖，纯标准库。
与 compass.py（自我候选）互补——它把外界候选也铺到同一张桌上。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import append_jsonl, read_jsonl  # noqa: E402  共用的 JSONL 落地层

STORE = REPO_ROOT / "state" / "intake.jsonl"          # 归一后的需求（单一真相源）
INBOX = REPO_ROOT / "state" / "intake_inbox.jsonl"    # 外部胶水/工具丢进来的原始信号

# 三档优先级，从急到缓。定级只靠可核对的信号，不靠心情。
P0, P1, P2 = "P0", "P1", "P2"
_PRIO_ICON = {P0: "🔴", P1: "🟡", P2: "⚪"}
_PRIO_RANK = {P0: 0, P1: 1, P2: 2}  # 排序用：数字越小越靠前

# 来源权重：真实用户/issue 的声音 > 我自己写进 journal 的臆想。
SOURCE_ISSUE = "issue"
SOURCE_FEEDBACK = "feedback"
SOURCE_JOURNAL = "journal"
_SOURCE_ICON = {SOURCE_ISSUE: "🐛", SOURCE_FEEDBACK: "💬", SOURCE_JOURNAL: "📔"}

# 严重信号：命中即往上抬一档。崩溃/数据/安全是 P0 级，回归/退步是 P1 级。
_SEVERE = ("崩", "crash", "panic", "数据丢", "丢数据", "data loss", "安全", "security",
           "泄露", "leak", "无法启动", "起不来", "退出码 1", "traceback", "exception")
_REGRESS = ("变差", "退步", "regress", "回归失败", "比以前", "慢了", "不准", "漂了")

# 验收判据的关键词路由：吃反馈文本，选一句可核对的达标线。
_ACC_BUG = ("崩", "crash", "panic", "报错", "error", "traceback", "exception", "失败", "fail")
_ACC_FEATURE = ("希望", "能不能", "支持", "新增", "加个", "feature", "want", "add ", "缺")
_ACC_PERF = ("慢", "卡", "性能", "perf", "耗时", "latency", "内存", "memory")


@dataclasses.dataclass
class RawSignal:
    """一条未加工的外界信号：哪来的、出处引用、原文、可选时间戳。"""
    source: str          # SOURCE_* 之一（未知一律按 feedback 处理）
    ref: str             # 出处引用（issue #12 / 用户名 / journal 文件）
    text: str            # 原始文本
    ts: str = ""         # ISO 时间戳，缺省则归一时补当下

    @classmethod
    def from_dict(cls, d: dict) -> "RawSignal":
        src = str(d.get("source") or SOURCE_FEEDBACK).strip().lower()
        if src not in _SOURCE_ICON:
            src = SOURCE_FEEDBACK
        return cls(source=src, ref=str(d.get("ref") or "").strip(),
                   text=str(d.get("text") or ""), ts=str(d.get("ts") or ""))


@dataclasses.dataclass
class Requirement:
    """一条归一后的进化需求：结构化、带证据、带验收、带优先级，可被排序与回溯。"""
    id: str               # 稳定标识（source+归一标题的短哈希，用于去重）
    source: str           # 来自哪类外界
    ref: str              # 出处引用
    title: str            # 归一成一句话的需求
    evidence: list[str]   # 🔗 关联证据：命中的真实模块/文件 + 出处
    acceptance: str       # ✅ 一句可核对的验收判据
    priority: str         # 🚦 P0/P1/P2
    rationale: str        # 定级理由（可核对）
    raw: str              # 原文（截断保留，便于回溯）
    created: str          # 归一时间（ISO）

    def to_record(self) -> dict:
        """落 JSONL 的一行（全字段，可完整回放）。"""
        return dataclasses.asdict(self)

    def to_meta(self) -> dict:
        """给 prioritizer/planner 消费的轻量视图：对齐 compass 候选的字段约定。"""
        return {
            # 对齐 compass 候选：planner/prioritizer 用 title/lane/grounded_in 即可直接吃。
            "title": self.title,
            "lane": "协作",                       # 外界进件归到「协作」航道
            "grounded_in": " · ".join(self.evidence) or self.ref,
            # 进件特有字段：让排序层能加权「外界点名」与优先级。
            "id": self.id,
            "source": self.source,
            "ref": self.ref,
            "acceptance": self.acceptance,
            "priority": self.priority,
            "rationale": self.rationale,
        }


# ── 🔗 证据关联：反馈文本牵动哪些「真实存在」的模块/文件 ──────────────────
_PATH_RX = re.compile(r"[A-Za-z0-9_./-]+\.py\b|\bcap[ _]?[A-Za-z0-9_]+", re.IGNORECASE)


def _repo_files() -> set[str]:
    """仓库里真实存在的 .py 文件名（含 capabilities/ 下的），用于把反馈钉到代码上。"""
    names: set[str] = set()
    for p in REPO_ROOT.glob("*.py"):
        names.add(p.name)
    cap_dir = REPO_ROOT / "capabilities"
    if cap_dir.is_dir():
        for p in cap_dir.glob("*.py"):
            names.add(p.name)
    return names


def link_evidence(text: str, ref: str) -> list[str]:
    """从反馈里抽出它牵动的真实模块；一个都没命中时，至少留下出处引用。

    只认仓库里**真实存在**的文件——文本里写错的、臆想的路径不算证据，免得需求悬空。
    """
    files = _repo_files()
    found: list[str] = []
    for m in _PATH_RX.findall(text or ""):
        tok = m.strip().replace(" ", "_")
        # 「cap X」「cap_X」这类能力引用 → 归到 capabilities/cap_X.py
        norm = re.sub(r"(?i)^cap_?", "cap_", tok) if tok.lower().startswith("cap") else tok
        cand = norm if norm.endswith(".py") else f"{norm}.py"
        base = pathlib.PurePosixPath(cand).name
        for f in (base, base if "/" not in cand else cand):
            if f in files and f not in found:
                found.append(f)
        if base in files and base not in found:
            found.append(base)
    ev = [f"代码 `{f}`" for f in found]
    if ref:
        ev.append(f"出处 {ref}")
    return ev


# ── ✅ 验收判据：把「回应反馈」逼成一句可核对的达标线 ────────────────────
def _has(text: str, words) -> bool:
    low = (text or "").lower()
    return any(w.lower() in low for w in words)


def acceptance_for(text: str) -> str:
    """按反馈类型选一句可核对的验收判据——呼应使命「改动要被证据量出涨了什么」。"""
    if _has(text, _ACC_BUG):
        return "补一条复现该问题的用例，修复后它不再触发该错误（回归锁住）。"
    if _has(text, _ACC_PERF):
        return "用 perfbase 量出该路径的基线指标，改动后该指标可核对地改善。"
    if _has(text, _ACC_FEATURE):
        return "新增能力有 golden/回归样本锁住关键输出，且契约不被破坏。"
    return "改动留下可核对的证据，证明这条反馈被实际回应（而非只是读到）。"


# ── 🚦 优先级：只靠可核对的信号定级，附一行能复核的理由 ──────────────────
def priority_for(text: str, evidence: list[str], source: str) -> tuple[str, str]:
    """定级 + 理由：严重信号→P0，退步/真实用户→P1，其余 P2。理由逐项可核对。"""
    reasons: list[str] = []
    code_hits = sum(1 for e in evidence if e.startswith("代码 "))

    if _has(text, _SEVERE):
        reasons.append("命中严重信号（崩溃/数据/安全）")
        prio = P0
    elif _has(text, _REGRESS):
        reasons.append("提到能力退步/回归")
        prio = P1
    elif source == SOURCE_ISSUE:
        reasons.append("来自真实 issue（外界点名 > 自我臆想）")
        prio = P1
    else:
        reasons.append("无紧急信号")
        prio = P2

    if code_hits:
        reasons.append(f"钉到 {code_hits} 个真实模块")
        # 已钉到代码、又是真实用户来源的，从 P2 抬到 P1：有据可查更该回应。
        if prio == P2 and source in (SOURCE_ISSUE, SOURCE_FEEDBACK):
            prio = P1
            reasons.append("有据可查 → 抬一档")
    else:
        reasons.append("未钉到具体模块（证据偏空，先压一档）")

    return prio, "；".join(reasons) + "。"


# ── 把一句反馈归一成一句需求标题 ────────────────────────────────────────
def _summarize(text: str) -> str:
    """取首句、压平空白、截断，作为需求标题——粗即可，原文仍在 raw 里。"""
    flat = re.sub(r"\s+", " ", (text or "").strip())
    head = re.split(r"(?<=[。.!?！？\n])", flat, maxsplit=1)[0].strip() or flat
    return head[:80] + ("…" if len(head) > 80 else "")


def _req_id(source: str, title: str) -> str:
    """内容去重用的稳定短 id：同来源同标题永远算同一条需求。"""
    h = hashlib.sha1(f"{source}\n{title}".encode("utf-8")).hexdigest()
    return f"req-{h[:10]}"


def normalize(raw: RawSignal) -> Requirement:
    """RawSignal → Requirement：抽证据、定验收、判优先级，全程不联网、纯文本匹配。"""
    title = _summarize(raw.text)
    evidence = link_evidence(raw.text, raw.ref)
    acceptance = acceptance_for(raw.text)
    priority, rationale = priority_for(raw.text, evidence, raw.source)
    created = raw.ts or datetime.datetime.now().isoformat(timespec="seconds")
    return Requirement(
        id=_req_id(raw.source, title), source=raw.source, ref=raw.ref,
        title=title, evidence=evidence, acceptance=acceptance,
        priority=priority, rationale=rationale,
        raw=(raw.text or "").strip()[:500], created=created,
    )


# ── 落地 / 读取：JSONL 单一真相源，按 id 去重 ──────────────────────────────
def load() -> list[Requirement]:
    """读出当前需求队列；同 id 取最后一次（允许后写覆盖修订）。坏行/缺文件→空。"""
    by_id: dict[str, Requirement] = {}
    for rec in read_jsonl(STORE):
        try:
            req = Requirement(**rec)
        except Exception:
            continue  # 字段对不上的脏行直接跳过，进件不能成为新的故障源
        by_id[req.id] = req
    return list(by_id.values())


def capture(text: str, source: str = SOURCE_FEEDBACK, ref: str = "") -> tuple[Requirement, bool]:
    """归一一段反馈并落盘；返回 (需求, 是否新增)。已存在的 id 不重复落盘。"""
    req = normalize(RawSignal.from_dict({"source": source, "ref": ref, "text": text}))
    known = {r.id for r in load()}
    is_new = req.id not in known
    if is_new:
        append_jsonl(STORE, req.to_record())
    return req, is_new


def pull_inbox() -> list[Requirement]:
    """把 INBOX 里的原始信号排空成需求并落盘；返回本次**新增**的需求（已存在的跳过）。"""
    known = {r.id for r in load()}
    added: list[Requirement] = []
    for rec in read_jsonl(INBOX):
        req = normalize(RawSignal.from_dict(rec))
        if req.id in known:
            continue
        if append_jsonl(STORE, req.to_record()):
            known.add(req.id)
            added.append(req)
    return added


def queue() -> list[Requirement]:
    """当前需求队列，按优先级（P0→P2）、再按新→旧排好序，供展示/导出。"""
    reqs = load()
    return sorted(reqs, key=lambda r: (_PRIO_RANK.get(r.priority, 9), _neg_created(r.created)))


def _neg_created(s: str) -> str:
    """让 created 在同优先级内「新→旧」：取负不便，转成可逆排序键（越新越靠前）。"""
    return "".join(chr(0x10ffff - ord(c)) if ord(c) < 0x10ffff else c for c in (s or ""))


def manifest() -> dict:
    """机读导出：给 prioritizer/planner 消费的需求清单（轻量视图）。"""
    q = queue()
    return {"count": len(q),
            "by_priority": {p: sum(1 for r in q if r.priority == p) for p in (P0, P1, P2)},
            "requirements": [r.to_meta() for r in q]}


# ── 展示 ────────────────────────────────────────────────────────────────
def render(reqs: list[Requirement]) -> str:
    L = ["🦀📥 外界进件队列 · 把 issue/反馈变成可执行需求"]
    if not reqs:
        L.append("   （队列为空——还没有外界信号被归一。"
                 "用 --capture \"…\" 喂一条，或把原始信号写进 state/intake_inbox.jsonl 再 --pull。）")
        return "\n".join(L)
    counts = {p: sum(1 for r in reqs if r.priority == p) for p in (P0, P1, P2)}
    L.append(f"   共 {len(reqs)} 条　{_PRIO_ICON[P0]}P0×{counts[P0]}　"
             f"{_PRIO_ICON[P1]}P1×{counts[P1]}　{_PRIO_ICON[P2]}P2×{counts[P2]}")
    for r in reqs:
        L += ["",
              f"  {_PRIO_ICON.get(r.priority, '⚪')} {r.priority} "
              f"{_SOURCE_ICON.get(r.source, '💬')} {r.title}",
              f"        🔗 证据：{('；'.join(r.evidence)) or '—（未钉到代码，证据偏空）'}",
              f"        ✅ 验收：{r.acceptance}",
              f"        🚦 定级：{r.rationale}"]
    L += ["", "—— 进件只把外界声音铺到桌上并定个初判，先做哪个仍由 prioritizer/我拍板。"]
    return "\n".join(L)


# ── 归一自检：判据漂了立刻暴露（交给 health/CI 当一层守）──────────────────
def _selftest() -> int:
    """跑一组黄金样例，断言归一的优先级/验收路由没漂。返回退出码。"""
    cases = [
        # (text, source, 期望优先级, 验收里应出现的关键词)
        ("点 cap calibration 会直接崩，traceback 一大串", SOURCE_ISSUE, P0, "复现"),
        ("planner.py 跑起来好慢，性能能优化下吗", SOURCE_FEEDBACK, P1, "基线"),
        ("希望能新增一个导出 markdown 的能力", SOURCE_FEEDBACK, P2, "golden"),
        ("感觉最近 judge 的裁决比以前差了", SOURCE_FEEDBACK, P1, "证据"),
    ]
    fails: list[str] = []
    for text, src, want_prio, want_acc in cases:
        req = normalize(RawSignal.from_dict({"source": src, "ref": "selftest", "text": text}))
        if req.priority != want_prio:
            fails.append(f"  · 优先级漂了：{text!r} 期望 {want_prio} 实得 {req.priority}（{req.rationale}）")
        if want_acc not in req.acceptance:
            fails.append(f"  · 验收路由漂了：{text!r} 期望含 {want_acc!r} 实得 {req.acceptance!r}")
    if fails:
        print("🦀📥 进件归一自检 ❌ 有判据漂了：")
        print("\n".join(fails))
        return 1
    print(f"🦀📥 进件归一自检 ✅ {len(cases)} 条黄金样例全过——证据/验收/优先级判据未漂。")
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 外界进件层 📥 —— 把 issue/用户反馈归一成可执行的进化需求")
    ap.add_argument("--capture", metavar="TEXT", help="把一段反馈当场归一成需求并落盘")
    ap.add_argument("--source", default=SOURCE_FEEDBACK,
                    choices=sorted(_SOURCE_ICON), help="--capture 的来源类别（默认 feedback）")
    ap.add_argument("--ref", default="", metavar="REF", help="--capture 的出处引用（issue#/用户名）")
    ap.add_argument("--pull", action="store_true",
                    help="把 state/intake_inbox.jsonl 里的原始信号排空成需求")
    ap.add_argument("--json", action="store_true", help="机读：导出需求队列（给 prioritizer/planner）")
    ap.add_argument("--selftest", action="store_true", help="跑归一自检样例，漂了退出码 1")
    args = ap.parse_args(argv)

    if args.selftest:
        sys.exit(_selftest())

    if args.capture:
        req, is_new = capture(args.capture, source=args.source, ref=args.ref)
        tag = "新增并落盘" if is_new else "已存在（未重复落盘）"
        print(f"🦀📥 已归一一条需求（{tag}）：\n")
        print(render([req]))
        sys.exit(0)

    if args.pull:
        added = pull_inbox()
        print(f"🦀📥 从 inbox 排空：本次新增 {len(added)} 条需求。\n")
        print(render(queue()))
        sys.exit(0)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        sys.exit(0)

    print(render(queue()))
    sys.exit(0)  # 只读/落盘，正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
