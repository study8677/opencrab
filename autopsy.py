#!/usr/bin/env python3
"""失败尸检 🔬 —— 跨审计 / 记忆 / 回放聚类失败根因，产出预防清单与验证命令。

为什么要有它：这只螃蟹已经会**记**失败(audit 写决策链、memory 沉淀教训、
replay 打包可复现案例)，但记下来的失败是**散的**：同一个根因可能在审计里是一条
`failure` 事件、在记忆里是一条 `ok=False` 的 episode、在回放里是一个还在摔的案例——
三处各记一笔，没人把它们**对齐到同一个病根**上。于是修起来只能一处一处救火，
今天补这个症状、明天补那个症状，复发源始终没被消灭。

autopsy 做的就是「合并同类项」：从三个真相源各自抽出**失败信号**，按 errors.py 的
错误码(都不中时退回错误域)聚成一簇簇**根因**，每簇告诉你：
  · 它在哪些来源、出现过多少次、最近一次什么样(代表性现场)；
  · errors 给的固定修复建议(hint)；
  · 一份**预防清单**——按错误域定制的「下次怎么不再栽进来」；
  · 一组**验证命令**——可直接复制去跑，确认这个根因到底消没消(回放案例尤其能一键判定)。

它**不新增任何日志**，纯粹是 audit/memory/replay 的派生视图(单一真相源原则);
读写一律吞异常，绝不反噬——尸检是观测者，不能成为新的故障源。

用法:
    python autopsy.py                 # 尸检今天的失败，按根因聚类
    python autopsy.py --day 2026-05-25
    python autopsy.py --all           # 把记忆+回放里的全部失败一并纳入(不只今天)
    python autopsy.py --json          # 机读：把根因簇导成 JSON

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

import audit
import errors
import memory
import replay

_REPO_ROOT = pathlib.Path(__file__).resolve().parent


# ── 一条失败信号 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Signal:
    """从某个真相源抽出的一条失败：归一化到错误码 + 现场摘要 + 出处。"""
    code: str                    # errors 错误码(分流不出时退回 E-UNKNOWN)
    source: str                  # 来自哪个源：audit / memory / replay
    where: str                   # 失败发生处(事件位置 / 情境首句 / 命令)
    message: str                 # 一行现场摘要
    ts: str                      # 时间戳(尽量 ISO)
    ref: str                     # 回指：run_id / episode 时间 / case_id
    live: bool = True            # 这条失败「仍在摔」吗(回放已修好的为 False)


# ── 从三个真相源采集失败信号 ────────────────────────────────────────
def _from_audit(day: str | None) -> list[Signal]:
    """从审计轨迹里抽失败：每条 failure 事件一条信号，并补一条非正常收场。"""
    out: list[Signal] = []
    try:
        traces = audit.reconstruct(day)
    except Exception:
        return out
    for t in traces:
        for s in t.steps:
            if s.event != "failure":
                continue
            f = s.fields or {}
            where = str(f.get("where", "?"))
            err = str(f.get("error", "")).strip()
            code = (f.get("code")
                    or errors.classify(message=err, note=where).code)
            out.append(Signal(
                code=code, source="audit", where=where,
                message=err[:160] or "(无错误文本)", ts=s.ts,
                ref=getattr(t, "run_id", "?")))
    return out


def _from_memory(only_today: bool, day: str | None) -> list[Signal]:
    """从情境记忆里抽失败：ok=False 的 episode，各成一条信号。"""
    out: list[Signal] = []
    try:
        eps = memory.load()
    except Exception:
        return out
    for ep in eps:
        if ep.ok:
            continue
        if only_today and not ep.at.startswith(day or ""):
            continue
        where = ep.situation.split("\n")[0].strip()[:80] or "(无情境)"
        code = ep.code or errors.classify(
            message=ep.result, note=ep.situation).code
        out.append(Signal(
            code=code, source="memory", where=where,
            message=ep.result.split("\n")[0].strip()[:160] or "(无结果)",
            ts=ep.at, ref=ep.at))
    return out


def _from_replay(only_today: bool, day: str | None) -> list[Signal]:
    """从回放索引里抽失败：每个案例一条信号(回放判定为 fixed 的标记为已愈)。"""
    out: list[Signal] = []
    try:
        idx = replay.load_index()
    except Exception:
        return out
    seen: dict[str, dict] = {}
    for meta in idx:                          # 索引时间正序，后写的覆盖同 id 旧条
        cid = meta.get("case_id")
        if cid:
            seen[cid] = meta
    for cid, meta in seen.items():
        created = str(meta.get("created_at", ""))
        if only_today and not created.startswith(day or ""):
            continue
        code = meta.get("error_code") or errors.UNKNOWN.code
        verdict = meta.get("verdict")          # 若索引里登记过最近一次重放判定
        out.append(Signal(
            code=str(code), source="replay",
            where=str(meta.get("command", "?"))[:80],
            message=str(meta.get("title", "")).strip()[:160] or "(无标题)",
            ts=created, ref=str(cid),
            live=(verdict != "fixed")))
    return out


def collect(day: str | None = None, *, only_today: bool = True) -> list[Signal]:
    """跨三源采集失败信号；day 默认今天，only_today=False 则纳入全部历史。"""
    day = day or datetime.date.today().isoformat()
    audit_day = day if only_today else None
    sigs: list[Signal] = []
    sigs += _from_audit(audit_day)
    sigs += _from_memory(only_today, day)
    sigs += _from_replay(only_today, day)
    return sigs


# ── 预防清单 / 验证命令：按错误域定制 ───────────────────────────────
# key 取错误码的「域」段(E-<DOMAIN>-… 里的 DOMAIN)，给一组通用的「别再栽」要点。
_PREVENT: dict[str, list[str]] = {
    "BRAIN": [
        "决策前用 health.py 体检大脑连通性，缺密钥/限流就主动降级而非硬撞。",
        "对大脑调用包退避重试，并把 http_status 喂给 errors.classify 精确分流。",
    ],
    "HANDS": [
        "动手前确认工作区干净、目标分支存在；改完先 diff 再提交。",
        "无改动就别走提交路径，让 hands 早返回 E-HANDS-NOCHANGE 而非空跑。",
    ],
    "EVOLVE": [
        "合并前必须自测通过(checkup.py)，红了就停在实验分支别并主干。",
        "push 失败先 fetch/rebase 再推，把冲突挡在合并门槛外。",
    ],
    "REPLAY": [
        "回放传入合法日期/案例号；空案例集时优雅退出而非报错。",
    ],
    "STARTUP": [
        "依赖只用标准库;新增 import 前先在干净环境验证可导入。",
    ],
    "CONFIG": [
        "配置项给默认值+范围校验，越界时退回安全默认并记一条审计。",
    ],
}
_PREVENT_DEFAULT = [
    "把这条失败用 replay.py --capture 固化成可复现案例，别让它只活在日志里。",
    "在 memory.py 里检索同类往事，确认是不是老坑复发。",
]

# 验证命令：先给该域通用的，再按来源补可一键判定的。
_VERIFY_BY_DOMAIN: dict[str, list[str]] = {
    "BRAIN": ["python health.py"],
    "HANDS": ["python checkup.py"],
    "EVOLVE": ["python checkup.py"],
    "REPLAY": ["python replay.py"],
    "STARTUP": ["python -c 'import crab'"],
    "CONFIG": ["python policy.py"],
}


def _domain_of(code: str) -> str:
    """从错误码切出域段：E-BRAIN-AUTH → BRAIN；切不出则 UNKNOWN。"""
    parts = code.split("-")
    return parts[1] if len(parts) >= 2 and parts[0] == "E" else "UNKNOWN"


# ── 一簇根因 ────────────────────────────────────────────────────────
@dataclasses.dataclass
class Cluster:
    """聚到同一错误码下的一组失败：根因 + 规模 + 代表现场 + 预防/验证。"""
    code: str
    signals: list[Signal]

    @property
    def count(self) -> int:
        return len(self.signals)

    @property
    def live_count(self) -> int:
        return sum(1 for s in self.signals if s.live)

    @property
    def sources(self) -> list[str]:
        return sorted({s.source for s in self.signals})

    @property
    def latest(self) -> Signal:
        return max(self.signals, key=lambda s: s.ts)

    @property
    def domain(self) -> str:
        return _domain_of(self.code)

    def spec(self):
        return errors.get(self.code) or errors.UNKNOWN

    def prevention(self) -> list[str]:
        """预防清单：该域定制要点 + errors 的固定修复 + 通用兜底。"""
        items = list(_PREVENT.get(self.domain, []))
        hint = self.spec().hint
        if hint:
            items.append(f"落实 errors 修复建议：{hint}")
        items += _PREVENT_DEFAULT
        return items

    def verification(self) -> list[str]:
        """验证命令：该域通用命令 + 每个回放案例的一键重放。"""
        cmds = list(_VERIFY_BY_DOMAIN.get(self.domain, []))
        for s in self.signals:
            if s.source == "replay":
                cmds.append(f"python replay.py --replay {replay._short(s.ref)}")
        # 去重保序
        seen: set[str] = set()
        out: list[str] = []
        for c in cmds:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def to_dict(self) -> dict:
        sp = self.spec()
        return {
            "code": self.code, "domain": self.domain, "title": sp.title,
            "count": self.count, "live": self.live_count,
            "sources": self.sources,
            "latest": dataclasses.asdict(self.latest),
            "prevention": self.prevention(),
            "verification": self.verification(),
        }


def cluster(signals: list[Signal]) -> list[Cluster]:
    """把失败信号按错误码聚成根因簇；先按「仍在摔的多」、再按总数排序。"""
    by_code: dict[str, list[Signal]] = {}
    for s in signals:
        by_code.setdefault(s.code, []).append(s)
    clusters = [Cluster(code=c, signals=sigs) for c, sigs in by_code.items()]
    clusters.sort(key=lambda c: (c.live_count, c.count), reverse=True)
    return clusters


def autopsy(day: str | None = None, *, only_today: bool = True) -> list[Cluster]:
    return cluster(collect(day, only_today=only_today))


# ── 立项前置闸：把一个目标匹配到历史根因，产出禁忌清单与验证命令 ──────
# 为什么：这只螃蟹已经会**记**根因(上面的聚类)，但立项时没人回头看——同一个坑
# 今天填了明天又踩。同坑复摔比新失败更伤进化(老病根明明记着却没拦住)。precheck
# 就是「立项闸」：拿要立的目标去比对全部历史根因，命中的簇把它们的预防清单合成
# 一份**禁忌清单**、把验证命令合成一组**自检命令**，让 planner 带着「别再栽这几处」
# 开工。仍在摔的根因优先——还没愈的坑最该先拦。
def _overlap(goal: str, text: str) -> float:
    """目标被某簇词汇覆盖的比例(0~1)：命中越多，这个根因越可能挡在路上。

    复用 memory 的中英混合切词(单字 + 相邻二字组近似词)；按「目标词被覆盖多少」
    而非 Jaccard——目标是一句短话、簇文本是多条现场拼起来的长文，用覆盖率才不会
    被簇这边的大词表稀释掉。memory 缺席就从容退回 0。
    """
    try:
        import memory
        g = memory._tokens(goal)
        if not g:
            return 0.0
        return len(g & memory._tokens(text)) / len(g)
    except Exception:
        return 0.0


def lessons_for(goal: str, *, k: int = 3, min_overlap: float = 0.12,
                only_today: bool = False) -> list[Cluster]:
    """检索与目标最相关的历史根因簇(默认翻全部历史)：仍在摔的优先、命中度次之。

    匹配不到 / 出错都从容返回空表——前置闸是参谋，绝不能反噬立项。
    """
    goal = (goal or "").strip()
    if not goal:
        return []
    try:
        clusters = autopsy(only_today=only_today)
    except Exception:
        return []
    scored: list[tuple[bool, float, int, Cluster]] = []
    for i, c in enumerate(clusters):
        text = f"{c.code} {c.spec().title} " + " ".join(
            f"{s.where} {s.message}" for s in c.signals)
        ov = _overlap(goal, text)
        if ov >= min_overlap:
            # 第三位放 -i 作平手裁决：避免落到不可比较的 Cluster 上(reverse 排序时)。
            scored.append((c.live_count > 0, ov, -i, c))
    scored.sort(key=lambda x: x[:3], reverse=True)
    return [c for *_, c in scored[:k]]


def precheck(goal: str, *, k: int = 3, taboo_cap: int = 6,
             verify_cap: int = 5) -> dict:
    """立项前置闸的成品：把命中的根因簇合并成禁忌清单 + 验证命令(都去重保序)。

    返回 {codes, taboos, verifies, live}：codes 是命中的根因码，live 是其中仍在摔
    的簇数。没命中则各字段为空——干净起步，无坑可避。
    """
    clusters = lessons_for(goal, k=k)
    taboos: list[str] = []
    verifies: list[str] = []
    seen_t: set[str] = set()
    seen_v: set[str] = set()
    for c in clusters:
        for it in c.prevention():
            if it not in seen_t:
                seen_t.add(it)
                taboos.append(it)
        for v in c.verification():
            if v not in seen_v:
                seen_v.add(v)
                verifies.append(v)
    return {
        "codes": [c.code for c in clusters],
        "live": sum(1 for c in clusters if c.live_count > 0),
        "taboos": taboos[:taboo_cap],
        "verifies": verifies[:verify_cap],
    }


def render_precheck(goal: str, gate: dict) -> str:
    codes = gate.get("codes") or []
    if not codes:
        return f"🚦 立项闸 · {goal[:40]}：历史尸检里没翻到同类根因——这是片新地，放手去 🌊"
    flag = f"，其中 {gate['live']} 个仍在摔" if gate.get("live") else ""
    lines = [f"🚦 立项闸 · {goal[:40]}",
             f"   命中 {len(codes)} 个历史根因（{'/'.join(codes)}）{flag}",
             "   禁忌清单（同坑勿踩）："]
    lines += [f"     □ {t}" for t in gate.get("taboos", [])]
    if gate.get("verifies"):
        lines.append("   验证命令（开工前后各跑一遍确认没复踩）：")
        lines += [f"     $ {v}" for v in gate["verifies"]]
    return "\n".join(lines)


# ── 渲染 ────────────────────────────────────────────────────────────
def render(clusters: list[Cluster], scope: str) -> str:
    if not clusters:
        return f"🔬 尸检{scope}：没翻到任何失败信号——干净利落，无尸可验 🌊"
    lines = [f"🔬 失败尸检 · {scope} · {len(clusters)} 个根因"]
    total = sum(c.count for c in clusters)
    live = sum(c.live_count for c in clusters)
    lines.append(f"   共 {total} 条失败信号，其中 {live} 条仍在摔\n")
    for c in clusters:
        sp = c.spec()
        flag = f"🔴{c.live_count}仍在摔" if c.live_count else "🟢已愈"
        lines.append(f"━━ {c.code} · {sp.title}")
        lines.append(f"   {c.count} 次 · 跨 {'/'.join(c.sources)} · {flag}")
        lat = c.latest
        lines.append(f"   最近：[{lat.source}] {lat.where} — {lat.message}")
        lines.append("   预防清单：")
        for it in c.prevention():
            lines.append(f"     □ {it}")
        lines.append("   验证命令：")
        for cmd in c.verification() or ["(无现成命令，建议补一个回放案例)"]:
            lines.append(f"     $ {cmd}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ── CLI ─────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="失败尸检：跨源聚类根因，产出预防清单与验证命令")
    ap.add_argument("--day", help="尸检哪一天(YYYY-MM-DD)，默认今天")
    ap.add_argument("--all", action="store_true",
                    help="纳入记忆+回放里的全部历史失败(不只今天)")
    ap.add_argument("--json", action="store_true", help="机读：导出根因簇 JSON")
    ap.add_argument("--for", dest="goal", metavar="目标",
                    help="立项前置闸：检索这个目标命中的历史根因，产出禁忌清单与验证命令")
    args = ap.parse_args(argv)

    if args.goal:
        gate = precheck(args.goal)
        if args.json:
            print(json.dumps({"goal": args.goal, **gate},
                             ensure_ascii=False, indent=2))
        else:
            print(render_precheck(args.goal, gate))
        return

    only_today = not args.all
    day = args.day or datetime.date.today().isoformat()
    clusters = autopsy(day, only_today=only_today)
    scope = "全部历史" if args.all else day

    if args.json:
        print(json.dumps(
            {"scope": scope, "clusters": [c.to_dict() for c in clusters]},
            ensure_ascii=False, indent=2))
        return
    print(render(clusters, scope))


if __name__ == "__main__":
    main()
