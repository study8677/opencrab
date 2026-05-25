#!/usr/bin/env python3
"""进化时间线 🧭🕰️ —— 把审计、记忆、提交串成一条可查询的成长轨迹，标出反复卡点与证据空洞。

为什么要有它：这只螃蟹每天自改一个模块，证据散落在三处互不相认的地方——
**提交**(`git log`)记下「我宣称推进了什么」、**审计**(audit)记下「某次进程真的跑了、
分支怎么走、是否失败」、**记忆**(memory)记下「这次情境-行动-结果，栽没栽跟头」。
单看任何一处都只是当天的碎片：提交只会自夸、审计只活一天、记忆只记教训。
于是我容易**凭当天直觉**判断「最近是不是在变强」，却看不见**长期轨迹**——
哪个坑反复摔、哪句「我推进了 X」其实从没被任何一次运行或记忆佐证过。

timeline 就把这三股证据按时间缝成一条线，再在线上标两类最该被看见的东西：

  · 🔁 **反复卡点**：同一个错误码 / 同一个模块，在窗口里**失败 ≥2 次**——
                     不是偶发，是反复咬人的真痛点，该停下来正面解决，而非又绕路。
  · 🕳️ **证据空洞**：某条提交宣称推进了某模块，可那一天既没有审计轨迹、
                     也没有记忆佐证，连模块名都没在任何运行/记忆里出现过——
                     「我说我改了」与「有证据它真被跑过/学到过」之间裂开的缝。

它是观测者：只读三处既有证据派生，**不执行、不落盘、不改任何文件**，
读不到任何一处都跳过而非崩。结论永远只是「摆出轨迹与缝隙」，拍板的是我自己。

用法:
    python timeline.py                 # 近 7 天的进化时间线 + 反复卡点 + 证据空洞
    python timeline.py --since 30      # 把回看窗口拉到近 30 天
    python timeline.py --grep hands    # 只看与某主题/模块相关的轨迹(子串匹配)
    python timeline.py --gaps          # 只盯证据空洞(宣称推进却无佐证的提交)
    python timeline.py --json          # 机读：导成 JSON(给 health / 外部工具消费)

零第三方依赖，纯标准库。与 audit.py(单次回放)、memory.py(情境检索)互补：
那两者答「这一次怎么了」，timeline 答「长期看，我到底在反复栽哪、又在哪自说自话」。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 三类证据在时间线上的来源标记。
KIND_COMMIT = "commit"   # 提交：我宣称推进了什么
KIND_RUN = "run"         # 审计轨迹：某次进程真的跑了、走到哪、是否失败
KIND_MEMORY = "memory"   # 情境记忆：一次情境-行动-结果，栽没栽跟头

_KIND_ICON = {KIND_COMMIT: "📝", KIND_RUN: "🧬", KIND_MEMORY: "🧠"}
_KIND_NAME = {KIND_COMMIT: "提交", KIND_RUN: "运行", KIND_MEMORY: "记忆"}

# 从一句话里抠出「主题模块」：优先反引号里的 X.py，退而求其次第一个 .py 词。
_TOPIC_BACKTICK = re.compile(r"`([\w./-]+\.py)`")
_TOPIC_BARE = re.compile(r"([\w./-]+\.py)")
# 提交主语里的自夸前缀(evolve / self-evolve / emoji)，归一化去重时剥掉。
_COMMIT_PREFIX = re.compile(r"^[^\w`]*(self-evolve|evolve)\s*[:：]\s*", re.IGNORECASE)


@dataclasses.dataclass
class Event:
    """时间线上的一个节点：某时刻、来自某类证据、关于某主题、成没成。"""
    at: str            # ISO 时间戳(或日期)，用于排序与按天归并
    kind: str          # 三类来源之一
    topic: str         # 涉及的主题模块(抠不出则空串)
    summary: str       # 一行人话摘要
    ok: bool | None    # True 成 / False 栽 / None 不适用(如纯提交)
    code: str = ""     # 失败时的错误码(若有)
    ref: str = ""      # 溯源句柄(commit 短哈希 / run_id / 记忆时刻)

    @property
    def day(self) -> str:
        return self.at[:10]

    def to_meta(self) -> dict:
        return {"at": self.at, "kind": self.kind, "topic": self.topic,
                "summary": self.summary, "ok": self.ok, "code": self.code,
                "ref": self.ref}


def _topic_of(text: str) -> str:
    """从文本里抠出主题模块名(stem)：优先反引号 `X.py`，否则第一个裸 .py 词。"""
    m = _TOPIC_BACKTICK.search(text) or _TOPIC_BARE.search(text)
    return pathlib.PurePosixPath(m.group(1)).stem if m else ""


# ── 📝 提交：我宣称推进了什么(git log 派生，单一真相源，不新增日志) ──────
def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return ""


def _commit_events(since_days: int) -> list[Event]:
    """近 N 天的提交，每条一个节点。连续重复主语(self-evolve / evolve 同句)折叠成一条。"""
    raw = _git(["log", f"--since={since_days} days ago",
                "--pretty=format:%h\x1f%cI\x1f%s"])
    events: list[Event] = []
    last_norm = None
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        short, iso, subject = parts
        # 这仓库惯例是 self-evolve / evolve 一句话连提两遍，折叠掉冗余的那条。
        norm = _COMMIT_PREFIX.sub("", subject).strip()
        if norm == last_norm:
            continue
        last_norm = norm
        events.append(Event(at=iso, kind=KIND_COMMIT, topic=_topic_of(subject),
                            summary=subject.strip()[:90], ok=None, ref=short))
    return events


# ── 🧬 审计轨迹：某次进程真的跑了、走到哪、是否失败 ──────────────────────
def _run_events(since_days: int) -> list[Event]:
    """近 N 天每天的审计轨迹，每次运行一个节点(失败的最该被看见)。"""
    try:
        import audit
    except Exception:
        return []
    events: list[Event] = []
    today = datetime.date.today()
    for delta in range(since_days + 1):
        day = (today - datetime.timedelta(days=delta)).isoformat()
        try:
            traces = audit.reconstruct(day)
        except Exception:
            continue
        for t in traces:
            intent = (t.intent or "（无意图，可能只跑了能力）").strip()
            events.append(Event(at=t.started_at, kind=KIND_RUN,
                                topic=_topic_of(intent),
                                summary=f"{t.outcome} · 意图：{intent[:60]}",
                                ok=not t.failed, ref=t.run_id[-12:]))
    return events


# ── 🧠 情境记忆：一次情境-行动-结果，栽没栽跟头 ─────────────────────────
def _memory_events(since_days: int) -> list[Event]:
    """窗口内的情境记忆，每条一个节点；带错误码的失败是反复卡点的主料。"""
    try:
        import memory
        eps = memory.load()
    except Exception:
        return []
    cutoff = (datetime.date.today() - datetime.timedelta(days=since_days)).isoformat()
    events: list[Event] = []
    for ep in eps:
        if ep.at[:10] < cutoff:
            continue
        topic = _topic_of(ep.situation) or _topic_of(ep.action)
        events.append(Event(at=ep.at, kind=KIND_MEMORY, topic=topic,
                            summary=ep.headline(), ok=ep.ok, code=ep.code,
                            ref=ep.at[-8:]))
    return events


# ── 缝合成线 ─────────────────────────────────────────────────────────
def collect(since_days: int = 7, grep: str = "") -> list[Event]:
    """把三股证据缝成一条按时间正序的线；grep 非空时按子串过滤(主题/摘要任一命中)。"""
    events = (_commit_events(since_days) + _run_events(since_days)
              + _memory_events(since_days))
    if grep:
        g = grep.lower()
        events = [e for e in events
                  if g in e.topic.lower() or g in e.summary.lower()]
    events.sort(key=lambda e: e.at)
    return events


# ── 🔁 反复卡点：同一个码 / 同一个模块，失败 ≥2 次 ─────────────────────
@dataclasses.dataclass
class StickingPoint:
    """一个反复咬人的卡点：按什么聚的、栽了几次、最近一次在何时。"""
    key: str           # 聚类键(错误码，或没码时退回模块名)
    by: str            # 「错误码」或「模块」
    count: int         # 失败次数
    last_at: str       # 最近一次失败时刻
    sample: str        # 一条代表性摘要

    def to_meta(self) -> dict:
        return {"key": self.key, "by": self.by, "count": self.count,
                "last_at": self.last_at, "sample": self.sample}


def sticking_points(events: list[Event]) -> list[StickingPoint]:
    """从失败节点里找反复卡点：优先按错误码聚，无码则按模块聚，留下次数 ≥2 的。"""
    groups: dict[tuple[str, str], list[Event]] = {}
    for e in events:
        if e.ok is not False:        # 只看明确栽过的(None=不适用，True=成了)
            continue
        if e.code:
            key = (e.code, "错误码")
        elif e.topic:
            key = (e.topic, "模块")
        else:
            continue                 # 既无码又无模块，无法归类成「反复」
        groups.setdefault(key, []).append(e)

    points: list[StickingPoint] = []
    for (key, by), evs in groups.items():
        if len(evs) < 2:
            continue
        evs.sort(key=lambda e: e.at)
        points.append(StickingPoint(key=key, by=by, count=len(evs),
                                    last_at=evs[-1].at, sample=evs[-1].summary))
    points.sort(key=lambda p: (p.count, p.last_at), reverse=True)
    return points


# ── 🕳️ 证据空洞：宣称推进却无任何运行/记忆佐证的提交 ───────────────────
@dataclasses.dataclass
class EvidenceGap:
    """一条自说自话的提交：宣称推进，却找不到佐证它真被跑过/学到过的证据。"""
    at: str
    ref: str           # 提交短哈希
    topic: str         # 它宣称推进的模块
    summary: str
    reason: str        # 为什么判为空洞(给人核对)

    def to_meta(self) -> dict:
        return {"at": self.at, "ref": self.ref, "topic": self.topic,
                "summary": self.summary, "reason": self.reason}


def evidence_gaps(events: list[Event]) -> list[EvidenceGap]:
    """为每条提交找佐证：同一天有没有运行/记忆？该模块在窗口里被运行/记忆碰过没？

    两者皆无 = 证据空洞——「我说我改了」却没有任何它真被跑过或学到过的痕迹。
    """
    runs_mem = [e for e in events if e.kind in (KIND_RUN, KIND_MEMORY)]
    days_with_evidence = {e.day for e in runs_mem}
    topics_with_evidence = {e.topic for e in runs_mem if e.topic}

    gaps: list[EvidenceGap] = []
    for e in events:
        if e.kind != KIND_COMMIT:
            continue
        same_day = e.day in days_with_evidence
        topic_seen = bool(e.topic) and e.topic in topics_with_evidence
        if same_day or topic_seen:
            continue
        if e.topic:
            reason = (f"宣称推进 `{e.topic}`，但 {e.day} 无审计轨迹、"
                      f"且窗口内无任何运行/记忆碰过 `{e.topic}`")
        else:
            reason = f"{e.day} 既无审计轨迹也无记忆佐证这条提交"
        gaps.append(EvidenceGap(at=e.at, ref=e.ref, topic=e.topic,
                                summary=e.summary, reason=reason))
    return gaps


# ── 导出 / 渲染 ──────────────────────────────────────────────────────
def manifest(since_days: int = 7, grep: str = "") -> dict:
    """导出纯数据(给 health / 外部工具消费)。"""
    events = collect(since_days, grep)
    return {
        "since_days": since_days,
        "grep": grep,
        "count": len(events),
        "events": [e.to_meta() for e in events],
        "sticking_points": [p.to_meta() for p in sticking_points(events)],
        "evidence_gaps": [g.to_meta() for g in evidence_gaps(events)],
    }


def _render_timeline(events: list[Event]) -> list[str]:
    """按天分组、天内按时间正序，逐条印出谁在何时留下了什么证据。"""
    L: list[str] = []
    by_day: dict[str, list[Event]] = {}
    for e in events:
        by_day.setdefault(e.day, []).append(e)
    for day in sorted(by_day):
        L.append(f"\n  ── {day} ──")
        for e in by_day[day]:
            mark = "  " if e.ok is None else ("✅" if e.ok else "❌")
            code = f" [{e.code}]" if e.code else ""
            L.append(f"    {e.at[11:19] or '  ':>8} {_KIND_ICON[e.kind]}{mark} "
                     f"{e.summary}{code}")
    return L


def render(since_days: int, grep: str, gaps_only: bool = False) -> str:
    events = collect(since_days, grep)
    points = sticking_points(events)
    gaps = evidence_gaps(events)

    scope = f"近 {since_days} 天" + (f"·主题含「{grep}」" if grep else "")
    L = [f"🧭🕰️ opencrab 进化时间线 · {scope}",
         f"   缝合了 {len(events)} 个证据节点（📝提交 / 🧬运行 / 🧠记忆）。"]

    if gaps_only:
        L.append("")
        L += _render_gaps_block(gaps)
        return "\n".join(L)

    if not events:
        L.append("   （这个窗口内没有任何证据——把 --since 拉大些，或先让它跑几跳。）")
        return "\n".join(L)

    L += _render_timeline(events)

    # 🔁 反复卡点
    L += ["", "  🔁 反复卡点（同一个码/模块在窗口里失败 ≥2 次，该正面解决而非绕路）："]
    if not points:
        L.append("     ✅ 没有反复栽的卡点——失败要么没复发，要么记忆/审计里没留痕。")
    else:
        for p in points:
            L.append(f"     · 按{p.by} 聚：「{p.key}」失败 {p.count} 次，"
                     f"最近 {p.last_at[:16]}")
            L.append(f"         代表：{p.sample}")

    # 🕳️ 证据空洞
    L += [""]
    L += _render_gaps_block(gaps)

    L += ["", "—— 时间线只摆出轨迹与缝隙，怎么补、先补哪个，仍由我自己拍板。"]
    return "\n".join(L)


def _render_gaps_block(gaps: list[EvidenceGap]) -> list[str]:
    L = ["  🕳️ 证据空洞（宣称推进却无任何运行/记忆佐证的提交，警惕自说自话）："]
    if not gaps:
        L.append("     ✅ 每条提交在当天或窗口内都有运行/记忆佐证，没有自说自话。")
    else:
        for g in gaps:
            L.append(f"     · {g.ref} {g.at[:10]} {g.summary}")
            L.append(f"         ↳ {g.reason}")
    return L


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 进化时间线 🧭🕰️ —— 把审计/记忆/提交缝成可查询的成长轨迹")
    ap.add_argument("--since", type=int, default=7, metavar="N",
                    help="回看窗口：近 N 天（默认 7）")
    ap.add_argument("--grep", default="", metavar="TEXT",
                    help="只看主题/摘要里含此子串的节点")
    ap.add_argument("--gaps", action="store_true",
                    help="只盯证据空洞（宣称推进却无佐证的提交）")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    args = ap.parse_args(argv)

    since = max(1, args.since)
    grep = args.grep.strip()
    if args.json:
        print(json.dumps(manifest(since, grep), ensure_ascii=False, indent=2))
    else:
        print(render(since, grep, gaps_only=args.gaps))
    sys.exit(0)   # 只读派生，永远正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
