#!/usr/bin/env python3
"""成功复盘 🏆 —— 跨记忆 / 回放 / 审计挖出高收益成功，提炼可复用「招式」，反哺排序与剧本。

为什么要有它：`autopsy.py` 已经会把**失败**合并同类项、聚成根因、产出预防清单——
这只螃蟹学会了系统地「别再栽」。可它还缺一面镜子：**真正有效的进步，也该被复制。**
顺风的经历过去只是 memory 里一条 `ok=True` 的流水、replay 里一个被修好(`fixed`)的案例、
audit 里一次成功的 `evolve`——它们各自躺着，没人把「这次为什么赢」抽象成下次能照搬的招式。
于是好运无法沉淀成方法论，赢了一次还得靠下次重新摸索。

success 做的正是 autopsy 的镜像，方向相反：

  · **挖高收益**：不是所有成功都值得学。把一次自检通过和「把红的回归修回绿、把摔过的
    坑填平、安全并入主干」区分开——按**收益(yield)**给每条成功信号打分，高收益优先。
  · **提炼招式**：把高收益成功里反复出现的**动作模式**(先存快照再改、自测全绿才并、
    回放复证修复…)识别成一招招**可复用招式(Move)**，每招配「为什么有效 + 怎么照搬」。
  · **反哺排序**：哪条**航道(lane)**反复出赢面，就该在 prioritizer 里被正向加权——
    `lane_boosts()` 把「这块投入有回报」量化成可消费的信号(与 prioritizer 现有的
    「全成功=降温」互补：那条防过度自恋，这条认可真打出的复利)。
  · **反哺剧本**：每招都点名它印证/强化了 playbook 里的哪一本，让剧本不是凭空写的规矩，
    而是被一次次胜利反复验证过的套路。

它**不新增任何日志**，纯粹是 memory/replay/audit 的派生视图(单一真相源原则)；
读写一律吞异常，绝不反噬——复盘是观测者，不能成为新的故障源。

用法:
    python success.py                 # 复盘今天的高收益成功，按招式聚类
    python success.py --day 2026-05-25
    python success.py --all           # 纳入记忆+回放里的全部历史成功(不只今天)
    python success.py --boosts        # 只打印给排序层的航道加权(机读友好)
    python success.py --json          # 机读：把招式簇导成 JSON

零第三方依赖，纯标准库。和 autopsy.py（失败镜像）成对：一个教你别再栽，一个教你照着赢。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

import audit
import memory
import replay

_REPO_ROOT = pathlib.Path(__file__).resolve().parent


# ── 一条成功信号 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Signal:
    """从某个真相源抽出的一条成功：现场摘要 + 出处 + 收益分 + 命中的招式。"""
    source: str                  # 来自哪个源：memory / replay / audit
    where: str                   # 成功发生处(情境首句 / 案例命令 / 事件位置)
    detail: str                  # 一行现场摘要(做了什么 / 赢成什么样)
    ts: str                      # 时间戳(尽量 ISO)
    ref: str                     # 回指：episode 时间 / case_id / run_id
    yield_: float                # 收益分(越高越值得学；见 _YIELD_*）
    text: str                    # 用于招式识别的原始文本(情境+行动+结果拼接)
    move: str = ""               # 识别出的招式 id(认不出留空)


# ── 招式分类：高收益成功里反复出现的可复用动作模式 ──────────────────
# 每招由关键词命中识别(在信号的拼接文本里搜)，给出：标签、为什么有效、怎么照搬、
# 它强化了 playbook 里的哪一本、最该在哪条航道复用(反哺 prioritizer 的航道加权)。
@dataclasses.dataclass(frozen=True)
class Move:
    move_id: str
    label: str                   # 招式名(一句话)
    keywords: tuple[str, ...]    # 命中任一即判为用了这招
    why: str                     # 为什么这招有效
    reuse: str                   # 下次怎么照搬
    playbook: str                # 它印证/强化了哪本剧本(playbook.py 的 name)
    lane: str                    # 最该在哪条航道复用(给排序加权)


_MOVES: tuple[Move, ...] = (
    Move("snapshot-first", "先存快照再动手",
         ("快照", "snapshot", "回滚脚本", "退路"),
         "未经验证的改动并入前先有退路，搞砸也能确定地退回——这是 intent 的红线。",
         "动任何已有模块前先 `python rollback.py --snapshot`，再 `--rehearse` 验退路。",
         "safe-self-edit", "修炼"),
    Move("green-before-merge", "自测全绿才并主干",
         ("自测", "checkup", "health", "全绿", "绿了", "自检通过", "测试通过"),
         "红着并主干会把坏味道带进公开仓；门槛挡在合并前，复利才是干净的。",
         "并入前必跑 `python health.py --quiet`，非零就停在实验分支别推。",
         "add-module", "修炼"),
    Move("replay-cured", "把摔过的坑固化成回放并复证修复",
         ("回放", "replay", "复现", "复证", "fixed", "修回绿", "回归复跑"),
         "失败只活在日志里会复发；固化成可一键重放的案例，修好了能被确定地判定。",
         "修完用 `python replay.py --replay <id>` 判 fixed，让这个坑不再复发。",
         "fix-regression", "修炼"),
    Move("evidence-refreshed", "把「跑得通」追进证据账本",
         ("证据", "evidence", "声明", "复证账本", "claim"),
         "能力会过期失守；把验证命令真跑一遍追进账本，「我会什么」才重新算数。",
         "干完用 `python evidence.py --verify` 把声明刷回 🟢，别只口头宣称。",
         "refresh-evidence", "修炼"),
    Move("smallest-surface", "只改最小的面",
         ("最小", "最小的面", "单一职责", "收敛", "去重", "复用"),
         "面越小爆炸半径越小；把改动收敛到一处，回归与回滚都更可控。",
         "动手前问「能不能更小」，别顺手重构放大半径；优先抽公共逻辑去重。",
         "safe-self-edit", "修炼"),
    Move("outward-shipped", "把能力推向公开仓 / 对外协作",
         ("push", "已 push", "合并并 push", "公开仓", "对外", "协作", "embassy", "onboarding"),
         "对外交付 > 自我臆想；被外界用到、点名的进步才是真复利。",
         "完成内功后考虑把它经 embassy / onboarding 推向能被外界消费的面。",
         "add-module", "协作"),
)
_MOVE_BY_ID = {m.move_id: m for m in _MOVES}


def _detect_move(text: str) -> str:
    """在一条信号的拼接文本里识别它用了哪招(命中多招时取关键词命中最早的那招)。"""
    low = text.lower()
    best: tuple[int, str] = (1 << 30, "")
    for m in _MOVES:
        for kw in m.keywords:
            pos = low.find(kw.lower())
            if pos >= 0 and pos < best[0]:
                best = (pos, m.move_id)
                break
    return best[1]


# ── 收益评分：不是所有成功都值得学 ──────────────────────────────────
_YIELD_RECOVERED = 3.0     # 把摔过/红的修回来(replay fixed)：最高收益，反败为胜
_YIELD_SHIPPED = 2.0       # 安全并入主干 / 推向公开仓：复利落地
_YIELD_DISCIPLINED = 1.5   # 守住纪律(快照/自测/证据)的成功：方法论值钱
_YIELD_PLAIN = 0.5         # 普通一次成功(自检过了)：低收益，作背景


def _yield_of(text: str, *, recovered: bool, move: str) -> float:
    """给一条成功信号打收益分：反败为胜 > 落地交付 > 守纪律 > 普通通过。"""
    if recovered:
        return _YIELD_RECOVERED
    if move == "outward-shipped" or "push" in text.lower() or "合并" in text:
        return _YIELD_SHIPPED
    if move in ("snapshot-first", "green-before-merge", "evidence-refreshed", "replay-cured"):
        return _YIELD_DISCIPLINED
    return _YIELD_PLAIN


# ── 从三个真相源采集成功信号 ────────────────────────────────────────
def _from_memory(only_today: bool, day: str | None) -> list[Signal]:
    """从情境记忆抽成功：ok=True 的 episode，各成一条信号。"""
    out: list[Signal] = []
    try:
        eps = memory.load()
    except Exception:
        return out
    for ep in eps:
        if not ep.ok:
            continue
        if only_today and not ep.at.startswith(day or ""):
            continue
        where = ep.situation.split("\n")[0].strip()[:80] or "(无情境)"
        text = f"{ep.situation}\n{ep.action}\n{ep.result}"
        move = _detect_move(text)
        recovered = bool(ep.tags) and any(
            t in ("recovered", "fixed", "回放复证", "反败为胜") for t in ep.tags)
        out.append(Signal(
            source="memory", where=where,
            detail=(ep.action.split("\n")[0].strip()[:120]
                    or ep.result.split("\n")[0].strip()[:120] or "(无摘要)"),
            ts=ep.at, ref=ep.at, text=text, move=move,
            yield_=_yield_of(text, recovered=recovered, move=move)))
    return out


def _from_replay(only_today: bool, day: str | None) -> list[Signal]:
    """从回放索引抽成功：被判定为 fixed 的案例——一次确定的反败为胜，最高收益。"""
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
        if meta.get("verdict") != "fixed":    # 只学已经修好的案例
            continue
        created = str(meta.get("created_at", ""))
        if only_today and not created.startswith(day or ""):
            continue
        title = str(meta.get("title", "")).strip()
        cmd = str(meta.get("command", "?"))
        text = f"{title}\n{cmd}\n回放复证 fixed"
        out.append(Signal(
            source="replay", where=cmd[:80],
            detail=f"{title[:100] or '(无标题)'} —— 已复证修复(fixed)",
            ts=created, ref=str(cid), text=text, move="replay-cured",
            yield_=_YIELD_RECOVERED))
    return out


def _from_audit(day: str | None) -> list[Signal]:
    """从审计轨迹抽成功：跑完且无失败、且发生过 evolve/act 的运行，记为一次成功落地。"""
    out: list[Signal] = []
    try:
        traces = audit.reconstruct(day)
    except Exception:
        return out
    for t in traces:
        steps = t.steps
        if any(s.event == "failure" for s in steps):
            continue                          # 摔过的不算成功落地
        evolved = [s for s in steps if s.event in ("evolve", "act", "decision")]
        if not evolved:
            continue
        intent = next((s for s in steps if s.event == "intent"), None)
        where = ""
        if intent and intent.fields:
            where = str(intent.fields.get("text", "")
                        or intent.fields.get("goal", "")).split("\n")[0][:80]
        last = evolved[-1]
        detail = str((last.fields or {}).get("summary", "")
                     or (last.fields or {}).get("note", "") or last.event)[:120]
        text = f"{where}\n{detail}"
        move = _detect_move(text)
        out.append(Signal(
            source="audit", where=where or "(无意图记录)",
            detail=detail or "一次无失败的进化运行", ts=last.ts,
            ref=getattr(t, "run_id", "?"), text=text, move=move,
            yield_=_yield_of(text, recovered=False, move=move)))
    return out


def collect(day: str | None = None, *, only_today: bool = True) -> list[Signal]:
    """跨三源采集成功信号；day 默认今天，only_today=False 则纳入全部历史。"""
    day = day or datetime.date.today().isoformat()
    audit_day = day if only_today else None
    sigs: list[Signal] = []
    sigs += _from_memory(only_today, day)
    sigs += _from_replay(only_today, day)
    sigs += _from_audit(audit_day)
    return sigs


# ── 一簇招式：聚到同一可复用动作下的成功 ────────────────────────────
@dataclasses.dataclass
class Cluster:
    """聚到同一招式下的一组成功：招式 + 规模 + 总收益 + 代表现场 + 复用/剧本指引。"""
    move_id: str
    signals: list[Signal]

    @property
    def count(self) -> int:
        return len(self.signals)

    @property
    def total_yield(self) -> float:
        return round(sum(s.yield_ for s in self.signals), 1)

    @property
    def sources(self) -> list[str]:
        return sorted({s.source for s in self.signals})

    @property
    def latest(self) -> Signal:
        return max(self.signals, key=lambda s: s.ts)

    @property
    def move(self) -> Move | None:
        return _MOVE_BY_ID.get(self.move_id)

    def to_dict(self) -> dict:
        m = self.move
        return {
            "move": self.move_id or "(未归类)",
            "label": m.label if m else "未归类的成功(还没沉淀成招式)",
            "count": self.count,
            "yield": self.total_yield,
            "sources": self.sources,
            "why": m.why if m else "",
            "reuse": m.reuse if m else "把它抽象成一条可复用招式，补进 success.py 的 _MOVES。",
            "playbook": m.playbook if m else "",
            "lane": m.lane if m else "",
            "latest": dataclasses.asdict(self.latest),
        }


def cluster(signals: list[Signal]) -> list[Cluster]:
    """把成功信号按招式聚簇；先按总收益、再按条数排序(最值得学的在前)。"""
    by_move: dict[str, list[Signal]] = {}
    for s in signals:
        by_move.setdefault(s.move, []).append(s)
    clusters = [Cluster(move_id=mid, signals=sigs) for mid, sigs in by_move.items()]
    clusters.sort(key=lambda c: (c.total_yield, c.count), reverse=True)
    return clusters


def review(day: str | None = None, *, only_today: bool = True) -> list[Cluster]:
    return cluster(collect(day, only_today=only_today))


# ── 反哺排序：哪条航道反复出赢面，就正向加权 ────────────────────────
def lane_boosts(day: str | None = None, *, only_today: bool = False) -> dict[str, float]:
    """把各航道(lane)累计的成功收益归一化成 0~1 的加权，供 prioritizer 消费。

    与 prioritizer 现有「全成功=降温」互补：那条防过度自恋(同一块反复刷自检),
    这条认可真打出的复利(同一航道反复反败为胜/落地交付)。默认看全部历史(复利是长期的)。
    """
    boosts: dict[str, float] = {}
    for c in review(day, only_today=only_today):
        m = c.move
        if not m or not m.lane:
            continue
        boosts[m.lane] = boosts.get(m.lane, 0.0) + c.total_yield
    if not boosts:
        return {}
    top = max(boosts.values())
    return {lane: round(v / top, 3) for lane, v in boosts.items()} if top else {}


def winning_moves(day: str | None = None, *, only_today: bool = False) -> list[dict]:
    """导出已沉淀成招式、且确有成功印证的可复用招式(给 planner / 剧本层消费)。"""
    return [c.to_dict() for c in review(day, only_today=only_today) if c.move_id]


# ── 渲染 ────────────────────────────────────────────────────────────
def render(clusters: list[Cluster], scope: str) -> str:
    if not clusters:
        return f"🏆 成功复盘 · {scope}：没翻到值得学的成功信号——还没攒下赢面，去赢一把再来 🌊"
    total = sum(c.count for c in clusters)
    gain = round(sum(c.total_yield for c in clusters), 1)
    lines = [f"🏆 成功复盘 · {scope} · {len(clusters)} 招",
             f"   共 {total} 条成功信号，累计收益 {gain}（反败为胜 > 落地交付 > 守纪律 > 普通通过）\n"]
    for c in clusters:
        m = c.move
        label = m.label if m else "未归类的成功（还没沉淀成招式）"
        head = f"━━ {label}  ·  {c.count} 次 · 收益 {c.total_yield} · 跨 {'/'.join(c.sources)}"
        lines.append(head)
        lat = c.latest
        lines.append(f"   最近：[{lat.source}] {lat.where} — {lat.detail}")
        if m:
            lines.append(f"   为什么有效：{m.why}")
            lines.append(f"   怎么照搬　：{m.reuse}")
            lines.append(f"   强化剧本　：📖 {m.playbook}  ·  反哺航道：{m.lane}")
        else:
            lines.append("   → 这批成功还没被抽象成招式；若反复出现，补进 success.py 的 _MOVES。")
        lines.append("")
    boosts = {}
    for c in clusters:
        if c.move and c.move.lane:
            boosts[c.move.lane] = round(boosts.get(c.move.lane, 0.0) + c.total_yield, 1)
    if boosts:
        ordered = sorted(boosts.items(), key=lambda kv: kv[1], reverse=True)
        lines.append("▸ 反哺排序：本期赢面最大的航道（prioritizer 可正向加权）：")
        lines.append("   " + "  ·  ".join(f"{lane} +{v}" for lane, v in ordered))
    return "\n".join(lines).rstrip()


# ── CLI ─────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="成功复盘 🏆：跨源挖高收益成功，提炼可复用招式，反哺排序与剧本")
    ap.add_argument("--day", help="复盘哪一天(YYYY-MM-DD)，默认今天")
    ap.add_argument("--all", action="store_true",
                    help="纳入记忆+回放里的全部历史成功(不只今天)")
    ap.add_argument("--boosts", action="store_true",
                    help="只打印给排序层的航道加权(机读友好)")
    ap.add_argument("--json", action="store_true", help="机读：导出招式簇 JSON")
    args = ap.parse_args(argv)

    only_today = not args.all
    day = args.day or datetime.date.today().isoformat()
    scope = "全部历史" if args.all else day

    if args.boosts:
        print(json.dumps(lane_boosts(day, only_today=only_today),
                         ensure_ascii=False, indent=2))
        return

    clusters = review(day, only_today=only_today)
    if args.json:
        print(json.dumps(
            {"scope": scope,
             "clusters": [c.to_dict() for c in clusters],
             "lane_boosts": lane_boosts(day, only_today=only_today)},
            ensure_ascii=False, indent=2))
        return
    print(render(clusters, scope))


if __name__ == "__main__":
    main()
