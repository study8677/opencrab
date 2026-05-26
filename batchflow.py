#!/usr/bin/env python3
"""批流攒批 📦🌊 —— 把零散的低风险小改，按「它补的是哪条证据缺口」攒成一批，
共用一条分支、一次验证、一次复盘。

为什么要有它：我每拍只敢动一处小改——改个错字、补条边界、对齐个默认值。单看每处都
**又小又稳**，可一处一分支、一处一自测、一处一复盘，开销全压在「走流程」上，真正改动
反倒是零头。`throughput.py` 已经量过：收尾（自测/合并/push/写日志）常是瓶颈。于是想提速，
最笨也最实在的办法不是写得更快，而是**少走几趟流程**——把性质相同的小改捆起来一次过。

但「捆」最容易偷掉的恰恰是证据：十个小改塞一个分支，跑一次自测就合并，等于赌「它们互不
影响、那一次验证覆盖了每一处」。这赌注一旦输，账就糊了——回滚回滚不干净，复盘复盘说不清
是哪处坏的。所以攒批不能按「手头顺手」攒，得按**证据缺口**攒：

  · 缺口(gap) —— 每处小改都得说清「我补的是哪条证据上的窟窿」（某条声明失守、某类边界没覆盖、
                 某份文档与代码漂了）。缺口相同，才谈得上共用一次验证。
  · 验证(verify) —— 每处小改自带能当场复跑的验证命令。一批的验证 = 批内所有验证命令的**并集去重**：
                    不是「跑一条顶十条」，而是「十条都跑，只是同样的不重复跑」。证据一条不少。
  · 批(batch) —— 同缺口、且都「低风险 + 小改 + 自带验证」的候选，在容量上限内攒成一批，
                 共用一条分支、那一整套验证、一次复盘。装不下的溢出到下一批。

判准（攒批绝不牺牲证据闭环）：
  · 没有验证命令的候选 **永不入批**——它补不上证据闭环，只能单独走流程，并让退出码非零。
  · 风险高于阈值 / 行数大于阈值的候选 **永不入批**——大改值得它自己一趟流程。
  · 一批有容量上限（条数 / 总行数 / 总风险），满了就开新批：批大了，那「一次验证」就名不副实。

批流是**规划者 + 自己的待办队列**：只读写 state/ 下被 .gitignore 的队列，产出「该怎么攒批」的计划，
绝不替你建分支、跑验证、改 journal 或任何源文件——真正动手仍由生命亲自来。

用法：
    python batchflow.py                         # 看当前队列攒成的批计划
    python batchflow.py --add "改错字" \\         # 入队一个候选小改
        --gap docdrift --files a.py,b.py --lines 6 --risk 0.1 \\
        --verify "python -m pyflakes a.py"
    python batchflow.py --done ID               # 标记某候选已落地（出队）
    python batchflow.py --drop ID               # 丢弃某候选（不再想做）
    python batchflow.py --max-risk 0.4 --max-lines 40   # 调入批门槛
    python batchflow.py --quiet                 # 只在有「不可批」候选或触发 --gate 时说话
    python batchflow.py --gate 3                # 待冲的就绪批 ≥ 3 则退出码非零（该去清批了）
    python batchflow.py --json                  # 机读：队列 + 批计划

退出码：0 = 正常；1 = 有候选自带不了验证（证据闭环破口）或触发 --gate。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import sys
import uuid

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402  —— 队列复用「读一批 / 追一条」的单一真相源

# 队列落在被 .gitignore 的 state/ 里：批流是观测者/规划者，写盘出错绝不反噬生命。
QUEUE_PATH = REPO_ROOT / "state" / "batchflow" / "queue.jsonl"

# ── 入批门槛与单批容量（皆可被命令行覆盖）──────────────────────────────────
MAX_RISK = 0.3          # 单个候选的风险上限：高于此 = 大改，自己走一趟流程
MAX_LINES = 30          # 单个候选的行改动上限：大于此 = 大改，不入批
BATCH_MAX_COUNT = 6     # 一批最多几个候选
BATCH_MAX_LINES = 80    # 一批的总行改动上限
BATCH_MAX_RISK = 1.0    # 一批的总风险上限（风险可叠加：小改多了也未必稳）

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    """把缺口名压成分支安全的 slug；空则回 'misc'。"""
    out = _SLUG_RE.sub("-", s.strip().lower()).strip("-")
    return out or "misc"


@dataclasses.dataclass
class Candidate:
    """一处待办的小改：补哪条证据缺口 + 改哪些文件 + 多大 + 多险 + 怎么验。"""
    id: str
    summary: str
    gap: str                       # 它补的证据缺口（攒批的分组键）
    files: list[str]
    lines: int                     # 估计的行改动（insertions+deletions）
    risk: float                    # 风险权重 0..1
    verify: list[str]              # 验证命令（一行一条 argv 字符串）；空 = 不可批
    ts: str

    @property
    def batchable_reason(self) -> str | None:
        """不可批的原因；可批则 None。"""
        if not self.verify:
            return "无验证命令——补不上证据闭环"
        if self.risk > _LIMITS["max_risk"]:
            return f"风险 {self.risk:.2f} 超阈 {_LIMITS['max_risk']:.2f}——大改单独走"
        if self.lines > _LIMITS["max_lines"]:
            return f"{self.lines} 行超阈 {_LIMITS['max_lines']}——大改单独走"
        return None

    @property
    def batchable(self) -> bool:
        return self.batchable_reason is None

    @property
    def unvalidatable(self) -> bool:
        """缺口里最危险的一种：自带不了验证。它让退出码非零。"""
        return not self.verify

    def to_meta(self) -> dict:
        return {
            "id": self.id, "summary": self.summary, "gap": self.gap,
            "files": self.files, "lines": self.lines, "risk": round(self.risk, 3),
            "verify": self.verify, "ts": self.ts,
            "batchable": self.batchable, "reason": self.batchable_reason,
        }


# 入批门槛存成模块级 dict，供 Candidate 的属性读取（命令行可改写）。
_LIMITS = {"max_risk": MAX_RISK, "max_lines": MAX_LINES}


def _coerce(rec: dict) -> Candidate | None:
    """把队列里的一行 JSON 还原成 Candidate；字段坏/缺则跳过（绝不臆造）。"""
    try:
        cid = str(rec["id"])
        verify = rec.get("verify") or []
        files = rec.get("files") or []
        if not isinstance(verify, list) or not isinstance(files, list):
            return None
        return Candidate(
            id=cid,
            summary=str(rec.get("summary", "")),
            gap=str(rec.get("gap", "")) or "misc",
            files=[str(f) for f in files],
            lines=max(0, int(rec.get("lines", 0))),
            risk=max(0.0, min(1.0, float(rec.get("risk", 1.0)))),
            verify=[str(v) for v in verify],
            ts=str(rec.get("ts", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_queue() -> list[Candidate]:
    """读出当前待办队列；坏行跳过，读不到则空队列。"""
    out: list[Candidate] = []
    for rec in jsonlstore.read_jsonl(QUEUE_PATH):
        c = _coerce(rec)
        if c is not None:
            out.append(c)
    return out


def _rewrite_queue(cands: list[Candidate]) -> bool:
    """整盘重写队列文件（用于出队/丢弃）。写盘出错只回 False，绝不抛。"""
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE_PATH.open("w", encoding="utf-8") as f:
            for c in cands:
                f.write(json.dumps(_queue_row(c), ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _queue_row(c: Candidate) -> dict:
    return {"id": c.id, "summary": c.summary, "gap": c.gap, "files": c.files,
            "lines": c.lines, "risk": c.risk, "verify": c.verify, "ts": c.ts}


def enqueue(summary: str, gap: str, files: list[str], lines: int,
            risk: float, verify: list[str]) -> Candidate:
    """入队一个候选小改，返回落地后的 Candidate。"""
    c = Candidate(
        id=uuid.uuid4().hex[:8],
        summary=summary.strip(),
        gap=gap.strip() or "misc",
        files=files,
        lines=max(0, lines),
        risk=max(0.0, min(1.0, risk)),
        verify=verify,
        ts=datetime.datetime.now().isoformat(timespec="seconds"),
    )
    jsonlstore.append_jsonl(QUEUE_PATH, _queue_row(c))
    return c


def remove(cid: str) -> bool:
    """按 id 出队/丢弃一个候选；存在并成功重写返回 True。"""
    cands = load_queue()
    kept = [c for c in cands if c.id != cid]
    if len(kept) == len(cands):
        return False
    return _rewrite_queue(kept)


@dataclasses.dataclass
class Batch:
    """一批共用分支/验证/复盘的候选小改。"""
    gap: str
    seq: int
    members: list[Candidate]

    @property
    def branch(self) -> str:
        return f"crab/{datetime.date.today():%Y%m%d}-batch-{_slug(self.gap)}-{self.seq}"

    @property
    def total_lines(self) -> int:
        return sum(c.lines for c in self.members)

    @property
    def total_risk(self) -> float:
        return sum(c.risk for c in self.members)

    @property
    def verify_union(self) -> list[str]:
        """批内所有验证命令的并集去重——保序，证据一条不少。"""
        seen: set[str] = set()
        out: list[str] = []
        for c in self.members:
            for v in c.verify:
                if v not in seen:
                    seen.add(v)
                    out.append(v)
        return out

    def to_meta(self) -> dict:
        return {
            "gap": self.gap, "seq": self.seq, "branch": self.branch,
            "count": len(self.members), "total_lines": self.total_lines,
            "total_risk": round(self.total_risk, 3),
            "members": [c.id for c in self.members],
            "verify_union": self.verify_union,
        }


def plan(cands: list[Candidate], limits: dict) -> tuple[list[Batch], list[Candidate]]:
    """把可批候选按缺口攒成批，返回 (批列表, 不可批的候选)。

    同缺口的候选在容量上限内贪心填批：满（条数/总行/总风险任一触顶）就开新批。
    候选按行数升序入批——先塞小的，让单批尽量多攒几个又不超总行上限。
    """
    batchable = [c for c in cands if c.batchable]
    spilled = [c for c in cands if not c.batchable]

    groups: dict[str, list[Candidate]] = {}
    for c in batchable:
        groups.setdefault(c.gap, []).append(c)

    batches: list[Batch] = []
    for gap in sorted(groups):
        members = sorted(groups[gap], key=lambda c: (c.lines, c.risk))
        seq = 1
        cur: list[Candidate] = []
        cur_lines = 0
        cur_risk = 0.0
        for c in members:
            fits = (len(cur) < limits["batch_count"]
                    and cur_lines + c.lines <= limits["batch_lines"]
                    and cur_risk + c.risk <= limits["batch_risk"])
            if cur and not fits:
                batches.append(Batch(gap=gap, seq=seq, members=cur))
                seq += 1
                cur, cur_lines, cur_risk = [], 0, 0.0
            cur.append(c)
            cur_lines += c.lines
            cur_risk += c.risk
        if cur:
            batches.append(Batch(gap=gap, seq=seq, members=cur))
    return batches, spilled


def manifest(limits: dict) -> dict:
    """机读：队列 + 批计划 + 不可批候选。"""
    cands = load_queue()
    batches, spilled = plan(cands, limits)
    return {
        "queue_size": len(cands),
        "limits": limits,
        "batches": [b.to_meta() for b in batches],
        "spilled": [c.to_meta() for c in spilled],
        "unvalidatable": [c.id for c in cands if c.unvalidatable],
    }


# ── 渲染 ─────────────────────────────────────────────────────────────
def _render(cands: list[Candidate], batches: list[Batch],
            spilled: list[Candidate]) -> str:
    L = [f"📦🌊 opencrab 批流计划 —— 队列 {len(cands)} 个候选 · "
         f"攒成 {len(batches)} 批", ""]

    if not cands:
        L.append("（队列空空——还没攒下任何待办小改。先 --add 几个再来。）")
        return "\n".join(L)

    if batches:
        ready = sum(1 for b in batches if len(b.members) > 1)
        L.append(f"可批：{len(batches)} 批（其中 {ready} 批真捆住 ≥2 个，省得下流程趟数）")
        for b in batches:
            L.append("")
            L.append(f"  🌿 {b.branch}")
            L.append(f"     缺口「{b.gap}」· {len(b.members)} 个 · "
                     f"{b.total_lines} 行 · 总风险 {b.total_risk:.2f}")
            for c in b.members:
                fs = ",".join(c.files) if c.files else "—"
                L.append(f"       · [{c.id}] {c.summary}  ({c.lines}行/险{c.risk:.2f}/{fs})")
            vu = b.verify_union
            L.append(f"     ✅ 共用验证（{len(vu)} 条并集去重）：")
            for v in vu:
                L.append(f"        $ {v}")
        L.append("")

    if spilled:
        L.append(f"单独走流程：{len(spilled)} 个（不可批，各自一趟）")
        for c in spilled:
            tag = "🔴" if c.unvalidatable else "🟡"
            L.append(f"  {tag} [{c.id}] {c.summary} —— {c.batchable_reason}")
        L.append("")

    bad = [c for c in cands if c.unvalidatable]
    if bad:
        L.append(f"🦀 {len(bad)} 个候选自带不了验证——批流拒绝收编它们：攒批可以省流程，"
                 "但绝不省证据。先给它们补上能复跑的验证命令，再谈入批。")
    else:
        L.append("🦀 攒批的本意：少走几趟流程，但每条验证一条不少。捆住的就去开那条共用分支，"
                 "一次验证过了，再一次复盘收尾。")
    return "\n".join(L)


def _parse_list(s: str | None) -> list[str]:
    """逗号分隔 → 去空白的列表；None/空 → 空列表。"""
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 批流攒批 📦🌊 —— 把低风险小改按证据缺口攒成一批，"
                    "共用分支/验证/复盘，省流程不省证据")
    ap.add_argument("--add", metavar="SUMMARY", help="入队一个候选小改（一句话摘要）")
    ap.add_argument("--gap", metavar="KEY", default="misc",
                    help="该候选补的证据缺口（攒批的分组键；配合 --add）")
    ap.add_argument("--files", metavar="A,B", help="该候选触碰的文件（逗号分隔；配合 --add）")
    ap.add_argument("--lines", type=int, default=0, metavar="N",
                    help="该候选估计的行改动（配合 --add）")
    ap.add_argument("--risk", type=float, default=0.1, metavar="R",
                    help="该候选风险权重 0..1（配合 --add，默认 0.1）")
    ap.add_argument("--verify", action="append", metavar="CMD", default=None,
                    help="该候选的验证命令（可多次给；配合 --add）")
    ap.add_argument("--done", metavar="ID", help="标记某候选已落地，出队")
    ap.add_argument("--drop", metavar="ID", help="丢弃某候选（不再做）")

    ap.add_argument("--max-risk", type=float, default=MAX_RISK, metavar="R",
                    help=f"单候选入批的风险上限（默认 {MAX_RISK}）")
    ap.add_argument("--max-lines", type=int, default=MAX_LINES, metavar="N",
                    help=f"单候选入批的行改动上限（默认 {MAX_LINES}）")
    ap.add_argument("--batch-count", type=int, default=BATCH_MAX_COUNT, metavar="N",
                    help=f"一批最多几个候选（默认 {BATCH_MAX_COUNT}）")
    ap.add_argument("--batch-lines", type=int, default=BATCH_MAX_LINES, metavar="N",
                    help=f"一批的总行改动上限（默认 {BATCH_MAX_LINES}）")
    ap.add_argument("--batch-risk", type=float, default=BATCH_MAX_RISK, metavar="R",
                    help=f"一批的总风险上限（默认 {BATCH_MAX_RISK}）")

    ap.add_argument("--gate", type=int, default=None, metavar="N",
                    help="待冲的就绪批（≥2 个成员）达到 N 个则退出码非零（该去清批了）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有不可批候选或触发 --gate 时说话（适合钩子 / CI）")
    ap.add_argument("--json", action="store_true", help="机读：队列 + 批计划")
    args = ap.parse_args(argv)

    # 入批门槛同步给 Candidate 的属性。
    _LIMITS["max_risk"] = args.max_risk
    _LIMITS["max_lines"] = args.max_lines
    limits = {
        "max_risk": args.max_risk, "max_lines": args.max_lines,
        "batch_count": args.batch_count, "batch_lines": args.batch_lines,
        "batch_risk": args.batch_risk,
    }

    # ── 写操作：入队 / 出队 / 丢弃 ──
    if args.add is not None:
        verify = args.verify or []
        c = enqueue(args.add, args.gap, _parse_list(args.files),
                    args.lines, args.risk, verify)
        warn = "" if verify else "  ⚠️ 没给 --verify：它将被拒入批，先补验证命令"
        print(f"📥 入队 [{c.id}] 「{c.summary}」缺口「{c.gap}」"
              f"（{c.lines}行/险{c.risk:.2f}）{warn}")
        sys.exit(0)

    if args.done is not None or args.drop is not None:
        cid = args.done or args.drop
        verb = "落地出队" if args.done else "丢弃"
        ok = remove(cid)
        print(f"{'✅' if ok else '❓'} {verb} [{cid}]"
              + ("" if ok else " —— 队列里没这个 id"))
        sys.exit(0 if ok else 1)

    # ── 读操作：批计划 ──
    if args.json:
        print(json.dumps(manifest(limits), ensure_ascii=False, indent=2))
        sys.exit(0)

    cands = load_queue()
    batches, spilled = plan(cands, limits)

    ready = sum(1 for b in batches if len(b.members) > 1)
    unvalidatable = [c for c in cands if c.unvalidatable]
    gate_tripped = args.gate is not None and ready >= args.gate
    # 证据破口（有候选自带不了验证）始终让退出码非零——这是批流的底线。
    breach = bool(unvalidatable)

    if args.quiet:
        msgs = []
        if unvalidatable:
            msgs.append(f"📦 {len(unvalidatable)} 个候选无验证，拒入批（证据破口）")
        if gate_tripped:
            msgs.append(f"📦 就绪批 {ready} 个达到闸门 {args.gate}，该去清批了")
        if msgs:
            print("；".join(msgs))
    else:
        print(_render(cands, batches, spilled))

    sys.exit(1 if (gate_tripped or breach) else 0)


if __name__ == "__main__":
    main()
