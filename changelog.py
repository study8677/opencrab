#!/usr/bin/env python3
"""变更日志 📜 —— 从提交、审计与证据账本生成面向人的变更日志，区分新增/修复/风险/验证命令。

为什么要有它：进化要被理解，才会赢得协作与信任。可这只螃蟹留下的痕迹是**给机器看的**——
提交主语千篇一律「🦀 evolve: 今天推进 X.py」、审计是一行行 JSONL、证据账本是验证流水。
一个想看懂「这阵子它到底变了什么、有没有变坏、我凭什么相信」的人，得同时翻三处互不相认
的原始记录，再自己脑补成一段人话。这道翻译的活儿不该每个想协作的人各干一遍。

changelog 就把那三处既有证据**译成一页人能读的变更日志**，且不只罗列「改了什么」，
而是按读者真正在意的四个问题分栏：

  · ✨ **新增**  —— 这阵子长出了哪些新能力 / 推进了哪个模块(提交派生)。
  · 🔧 **修复**  —— 修好了什么、回退了什么(提交主语里的修复/回退信号)。
  · ⚠️ **风险**  —— 有什么该警惕的：窗口内**真的跑挂过**的运行(审计)、
                    以及当前**证据失守/过期**的能力(证据账本)。自夸归自夸，这栏只认实据。
  · ✅ **验证命令** —— 别只听它说，**自己能复跑**的命令在此(证据账本里的 argv)，
                    连同「上次何时验过、还新不新鲜」一并交底——这是信任的锚点。

它是观测者：只读 git log / audit / evidence 三处既有证据派生，**不执行、不落盘、不改任何
文件**，读不到任何一处都跳过而非崩。结论永远只是「摆出一页变更日志」，怎么用由人自己定。

用法：
    python changelog.py                 # 近 7 天的变更日志(新增/修复/风险/验证命令)
    python changelog.py --since 30      # 把回看窗口拉到近 30 天
    python changelog.py --md            # 以 Markdown 输出(适合贴进 release notes / PR)
    python changelog.py --json          # 机读：导成 JSON(给 health / 外部工具消费)
    python changelog.py --quiet         # 只在「有风险」时说话(适合钩子 / CI 提个醒)

零第三方依赖，纯标准库。与 timeline.py 互补：timeline 答「长期看我在哪反复栽、又在哪
自说自话」(给自己复盘)，changelog 答「这阵子对外该怎么讲清我变了什么」(给协作者读)。
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import timeline  # noqa: E402  —— 复用 git log 派生与「从一句话抠主题模块」的单一真相源

# 变更的四个分栏（读者真正在意的四个问题）。
KIND_ADDED = "added"   # ✨ 新增：长出新能力 / 推进了哪个模块
KIND_FIXED = "fixed"   # 🔧 修复：修好了 / 回退了什么
KIND_RISK = "risk"     # ⚠️ 风险：真的跑挂过、或当前证据失守/过期

_KIND_ICON = {KIND_ADDED: "✨", KIND_FIXED: "🔧", KIND_RISK: "⚠️"}
_KIND_NAME = {KIND_ADDED: "新增", KIND_FIXED: "修复", KIND_RISK: "风险"}
_KIND_ORDER = [KIND_ADDED, KIND_FIXED, KIND_RISK]

# 从提交主语判分栏：修复信号优先于新增（一条提交可能既推进又修复，先归修复更诚实）。
_FIX_HINT = re.compile(
    r"修复|修正|改正|纠正|补漏|补全|回退|回滚|还原|rollback|revert|fix|bug|hotfix|patch",
    re.IGNORECASE)
# 安全/风险类主题：即便是「新增」一个红队/密钥扫描模块，读者也会想在风险栏先看到它。
_RISK_HINT = re.compile(
    r"风险|危险|安全|密钥|凭据|泄漏|泄露|漏洞|红队|攻击|越权|注入|redteam|secret|"
    r"vuln|exploit|attack|inject|cve|security",
    re.IGNORECASE)


def classify_commit(subject: str) -> str:
    """把一条提交主语判进某个分栏：修复 > 风险 > 新增（默认）。

    判据只看主语文字——这是提交作者**自己声称**的性质；风险栏里更硬的「真跑挂/证据失守」
    由审计与证据账本另行补充，不靠提交自夸。
    """
    if _FIX_HINT.search(subject):
        return KIND_FIXED
    if _RISK_HINT.search(subject):
        return KIND_RISK
    return KIND_ADDED


class Entry:
    """变更日志里的一行：某分栏、某时刻、一句人话，外加可溯源的句柄。"""

    __slots__ = ("kind", "at", "summary", "topic", "ref", "source")

    def __init__(self, kind: str, at: str, summary: str,
                 topic: str = "", ref: str = "", source: str = "commit") -> None:
        self.kind = kind          # 三个分栏之一
        self.at = at              # ISO 时间戳/日期，用于排序
        self.summary = summary    # 一行人话
        self.topic = topic        # 涉及的主题模块（抠不出则空串）
        self.ref = ref            # 溯源句柄：提交短哈希 / run_id / 声明名
        self.source = source      # 这行的证据来源：commit / audit / evidence

    @property
    def day(self) -> str:
        return self.at[:10]

    def to_meta(self) -> dict:
        return {"kind": self.kind, "at": self.at, "summary": self.summary,
                "topic": self.topic, "ref": self.ref, "source": self.source}


# ── 📝 提交 → ✨新增 / 🔧修复 / ⚠️风险 ────────────────────────────────────
def _commit_entries(since_days: int) -> list[Entry]:
    """近 N 天的提交，每条按主语判进一栏。复用 timeline 的 git 派生（已折叠 evolve 重复句）。"""
    entries: list[Entry] = []
    for ev in timeline._commit_events(since_days):
        kind = classify_commit(ev.summary)
        entries.append(Entry(kind=kind, at=ev.at, summary=ev.summary,
                             topic=ev.topic, ref=ev.ref, source="commit"))
    return entries


# ── 🧬 审计 → ⚠️风险：窗口内真的跑挂过的运行 ─────────────────────────────
def _audit_risk_entries(since_days: int) -> list[Entry]:
    """从审计轨迹里捞出**真的失败**的运行——这是比提交主语更硬的风险实据。"""
    try:
        import audit
    except Exception:
        return []
    entries: list[Entry] = []
    today = datetime.date.today()
    for delta in range(since_days + 1):
        day = (today - datetime.timedelta(days=delta)).isoformat()
        try:
            traces = audit.reconstruct(day)
        except Exception:
            continue
        for t in traces:
            if not t.failed:
                continue
            intent = (t.intent or "（无意图，可能只跑了能力）").strip()
            entries.append(Entry(
                kind=KIND_RISK, at=t.started_at,
                summary=f"运行跑挂：{t.outcome} · 意图：{intent[:60]}",
                topic=timeline._topic_of(intent),
                ref=t.run_id[-12:], source="audit"))
    return entries


# ── ✅ 证据账本 → 验证命令 + ⚠️证据失守/过期 ────────────────────────────
class Verify:
    """一条「读者能自己复跑」的验证命令，连同它当前新不新鲜。"""

    __slots__ = ("name", "asserts", "cmd", "state", "word", "mark", "fresh")

    def __init__(self, name: str, asserts: str, cmd: str,
                 state: str, word: str, mark: str, fresh: bool) -> None:
        self.name = name          # 声明名
        self.asserts = asserts    # 这条命令断言它会做什么
        self.cmd = cmd            # 能当场复跑的命令行
        self.state = state        # fresh / stale / broken / unproven
        self.word = word          # 中文状态词
        self.mark = mark          # 状态图标
        self.fresh = fresh        # 是否新鲜（有充分有效证据）

    def to_meta(self) -> dict:
        return {"name": self.name, "asserts": self.asserts, "cmd": self.cmd,
                "state": self.state, "fresh": self.fresh}


def _verify_section() -> tuple[list[Verify], list[Entry]]:
    """读证据账本，导出(可复跑的验证命令清单, 证据失守/过期 → 风险条目)。

    验证命令是信任的锚点：别只听它说，自己跑一条看退出码。失守/过期则反过来当风险报。
    """
    try:
        import evidence
    except Exception:
        return [], []
    try:
        statuses = {s.name: s for s in evidence.status()}
    except Exception:
        statuses = {}

    verifies: list[Verify] = []
    risks: list[Entry] = []
    for claim in getattr(evidence, "CLAIMS", []):
        s = statuses.get(claim.name)
        state = s.state if s else "unproven"
        word = s.word if s else "未证"
        mark = s.mark if s else "⚪"
        fresh = bool(s and s.settled)
        cmd = " ".join(claim.argv[1:]) or (claim.argv[0] if claim.argv else "")
        verifies.append(Verify(name=claim.name, asserts=claim.asserts, cmd=cmd,
                               state=state, word=word, mark=mark, fresh=fresh))
        # 证据失守(broken)/过期(stale)/未证(unproven) 都是该被读者看见的风险。
        if not fresh:
            at = ""
            if s and s.verified_at is not None:
                at = datetime.datetime.fromtimestamp(s.verified_at).isoformat()
            risks.append(Entry(
                kind=KIND_RISK, at=at or datetime.date.today().isoformat(),
                summary=f"能力证据{word}：{claim.asserts}",
                topic=claim.name, ref=claim.name, source="evidence"))
    return verifies, risks


# ── 缝合成一页变更日志 ───────────────────────────────────────────────────
def collect(since_days: int = 7) -> tuple[dict[str, list[Entry]], list[Verify]]:
    """把三处证据译成「分栏 → 条目」+ 验证命令清单。每栏内按时间倒序（新的在上）。"""
    verifies, evidence_risks = _verify_section()
    all_entries = _commit_entries(since_days) + _audit_risk_entries(since_days) + evidence_risks

    by_kind: dict[str, list[Entry]] = {k: [] for k in _KIND_ORDER}
    for e in all_entries:
        by_kind.setdefault(e.kind, []).append(e)
    for k in by_kind:
        by_kind[k].sort(key=lambda e: e.at, reverse=True)
    return by_kind, verifies


# ── 导出 / 渲染 ──────────────────────────────────────────────────────────
def manifest(since_days: int = 7) -> dict:
    """导出纯数据（给 health / 外部工具消费）。"""
    by_kind, verifies = collect(since_days)
    return {
        "since_days": since_days,
        "changes": {k: [e.to_meta() for e in by_kind.get(k, [])]
                    for k in _KIND_ORDER},
        "verify": [v.to_meta() for v in verifies],
        "has_risk": bool(by_kind.get(KIND_RISK)),
    }


def render(since_days: int, *, md: bool = False) -> str:
    """渲染成一页人能读的变更日志。md=True 时输出 Markdown（适合贴进 release notes）。"""
    by_kind, verifies = collect(since_days)
    n_changes = sum(len(by_kind.get(k, [])) for k in (KIND_ADDED, KIND_FIXED))
    n_risk = len(by_kind.get(KIND_RISK, []))

    if md:
        return _render_md(since_days, by_kind, verifies)

    L = [f"📜 opencrab 变更日志 · 近 {since_days} 天",
         f"   {n_changes} 项新增/修复，{n_risk} 项风险，"
         f"{len(verifies)} 条可复跑的验证命令。"]

    for kind in _KIND_ORDER:
        entries = by_kind.get(kind, [])
        L.append("")
        L.append(f"  {_KIND_ICON[kind]} {_KIND_NAME[kind]}（{len(entries)}）")
        if not entries:
            L.append("     —— 无")
            continue
        for e in entries:
            tag = {"audit": " 🧬实据", "evidence": " 🧾账本"}.get(e.source, "")
            L.append(f"     · {e.day} {e.ref} {e.summary}{tag}")

    L.append("")
    L.append("  ✅ 验证命令（别只听它说，自己复跑看退出码）")
    if not verifies:
        L.append("     —— 证据账本为空，暂无可复跑的验证命令")
    else:
        for v in verifies:
            L.append(f"     {v.mark} {v.name}（{v.word}）—— {v.asserts}")
            L.append(f"         $ {v.cmd}")

    L.append("")
    L.append("—— 变更日志只把痕迹译成人话，怎么对外讲、要不要发，仍由人自己拍板。")
    return "\n".join(L)


def _render_md(since_days: int, by_kind: dict[str, list[Entry]],
               verifies: list[Verify]) -> str:
    """Markdown 版：标题/小节/列表/代码块，直接可贴进 release notes 或 PR 描述。"""
    today = datetime.date.today().isoformat()
    L = [f"# 变更日志 · 近 {since_days} 天（{today}）", ""]
    for kind in _KIND_ORDER:
        entries = by_kind.get(kind, [])
        L.append(f"## {_KIND_ICON[kind]} {_KIND_NAME[kind]}")
        if not entries:
            L.append("- _无_")
        else:
            for e in entries:
                ref = f"`{e.ref}` " if e.ref else ""
                L.append(f"- {e.day} {ref}{e.summary}")
        L.append("")

    L.append("## ✅ 验证命令")
    if not verifies:
        L.append("- _证据账本为空_")
    else:
        for v in verifies:
            L.append(f"- {v.mark} **{v.name}**（{v.word}）—— {v.asserts}")
            L.append(f"  ```\n  $ {v.cmd}\n  ```")
    return "\n".join(L).rstrip() + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 变更日志 📜 —— 把提交/审计/证据译成面向人的变更日志")
    ap.add_argument("--since", type=int, default=7, metavar="N",
                    help="回看窗口：近 N 天（默认 7）")
    ap.add_argument("--md", action="store_true",
                    help="以 Markdown 输出（适合贴进 release notes / PR）")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    ap.add_argument("--quiet", action="store_true",
                    help="只在「有风险」时输出（适合钩子 / CI 提个醒）")
    args = ap.parse_args(argv)

    since = max(1, args.since)
    if args.json:
        print(json.dumps(manifest(since), ensure_ascii=False, indent=2))
        sys.exit(0)

    by_kind, _ = collect(since)
    has_risk = bool(by_kind.get(KIND_RISK))
    if args.quiet and not has_risk:
        sys.exit(0)
    print(render(since, md=args.md))
    sys.exit(0)   # 只读派生，永远正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
