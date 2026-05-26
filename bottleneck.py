#!/usr/bin/env python3
"""进化瓶颈体检 🩺⏱️ —— 回放近 N 次「真落地的自改」，把吞吐(时间)与摩擦(卡点)对齐到
同一根「需求→落地」的轴上，定位最慢的那一拍与最低收益的那个环节，开一张提速处方。

为什么要有它：领地里已经有两个各看一半的器官——
  · `throughput.py` 量**时间**：每拍的 想/做/收/等 各花多久、瓶颈段在哪。
  · `friction.py`   记**卡点**：哪段反复卡点/干等/返工，最磨人的是哪一簇。
它们各自成账，却从不照面：吞吐说「收尾段最久」，摩擦说「落地段老返工」，可没人把这两句
话拼成同一个诊断——**到底是哪一拍、慢在哪、为什么慢、先治哪一刀**。于是提速永远停在
「感觉慢」，加器官全凭直觉。

本层不新量任何东西，只做**对齐与回放**：先诊断机器本身，再决定要不要长器官。

  1. **回放**：从审计里取最近 N 次「真改了文件、且落地有行数」的拍(默认 30)——只看
     自改本身，做梦拍/半截拍不算数。
  2. **最慢拍**：按整拍墙上耗时排序，点出最慢的几拍，并标出每拍是慢在 想/做/收 哪一段。
  3. **低收益环节**：把 想/做/收 三段各自的「花掉的时间 ÷ 换来的行数」算出来——时间吃
     得多、行数换得少的那段，就是单位产出最贵的环节(未必是最慢段，但最不划算)。
  4. **摩擦对齐**：把摩擦账本最磨人的那一簇，按阶段映射回三段(intent/plan→想，build→做，
     verify/land→收)，看「最贵的段」和「最磨人的簇」是否指向同一处——指同一处，处方
     就有两路证据;指不同处，就两刀分开开。
  5. **提速处方**：综合上面四项，给出一两条**可验证**的提速动作——治哪一段、怎么治、
     下个窗口怎么量它真变快了。处方不替我拍板，只把「这里慢」变成「我打算这样让它快」。

判准：体检是**观测者**——只读审计 JSONL、journal diffstat 与摩擦账本，绝不写 state /
journal、不改任何文件。某拍缺段就只算能算的，缺的跳过，绝不拿默认值蒙混;样本不足就
明说「先跑几拍再来」，绝不在三五拍上硬开处方。

用法:
    python bottleneck.py                # 体检报告:回放近 30 次自改 + 最慢拍 + 低收益段 + 处方
    python bottleneck.py --last 50      # 把回放窗口放到近 50 次自改
    python bottleneck.py --days 14      # 最多往回扫 14 天审计来凑够样本(默认 30)
    python bottleneck.py --slow 5       # 多列最慢的 5 拍
    python bottleneck.py --gate 0.6     # 「最贵段」吃掉的有效时间占比超 0.6 则退出码非零(挂 CI)
    python bottleneck.py --quiet        # 只在触发 --gate 时说话(钩子 / CI)
    python bottleneck.py --json         # 机读:回放样本 + 三段单位成本 + 摩擦对齐 + 处方

退出码:0 = 正常 / 未触发闸门;1 = 触发 --gate。零第三方依赖,纯标准库。
体检是观测者:读不到审计或样本不足就明说,绝不臆造、绝不反噬生命。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import throughput  # noqa: E402  —— 复用「拍」的重建与四段切分
import friction    # noqa: E402  —— 复用摩擦账本的聚类与磨人指数

# 攒够这么多次自改才敢开处方——样本太少时，「最慢段」多半是偶然，不是规律。
MIN_SAMPLES = 5
# 默认回放窗口：近 N 次真落地的自改。
DEFAULT_LAST = 30
# 默认最多往回扫的审计天数（凑够样本就停）。
DEFAULT_MAX_DAYS = 30

# 把吞吐的三段对齐到摩擦账本的阶段——好让「最贵段」与「最磨人簇」能照面。
_SEG_STAGES = {"think": ("intent", "plan"), "act": ("build",), "wrap": ("verify", "land")}
_STAGE_SEG = {st: seg for seg, sts in _SEG_STAGES.items() for st in sts}
_SEG_LABEL = throughput._SEG_LABEL  # 复用「🧠 想 / 🔨 做 / 📦 收」


# ── 回放：取最近 N 次「真落地的自改」 ─────────────────────────────────────
def _is_self_change(t: throughput.Tick) -> bool:
    """真落地的自改 = 这一拍动手改了文件、且 journal 里有行数可量。

    做梦拍(没改文件)、半截拍(没写出 journal / 量不到行数)都不算——它们不是一次完整的
    蜕壳，拿来排「最慢自改」会把诊断带偏。
    """
    return bool(t.changed) and bool(t.lines)


def replay(last: int = DEFAULT_LAST, max_days: int = DEFAULT_MAX_DAYS) -> list[throughput.Tick]:
    """往回扫审计，按时间正序取最近 last 次真落地的自改。

    审计读不到则回空——无从体检，绝不臆造。逐步放宽天数窗口直到凑够 last 次自改或扫到头。
    """
    selfs: list[throughput.Tick] = []
    # throughput.build 已按 (run, seq) 稳定排序；它内部按「天」回溯，扫满 max_days 即可。
    ticks = throughput.build(days=max(1, max_days))
    selfs = [t for t in ticks if _is_self_change(t)]
    return selfs[-last:] if last > 0 else selfs


# ── 三段单位成本：花掉的时间 ÷ 换来的行数 ─────────────────────────────────
def _seg_unit_cost(ticks: list[throughput.Tick]) -> dict[str, dict | None]:
    """对 想/做/收 三段，各自汇总「该段总秒数」与「这些拍换来的总行数」，算单位成本。

    单位成本 = 段总秒数 ÷ 段所在拍的总行数(秒/行)：越大越不划算——时间吃得多、行数换得少。
    某段在某拍缺端点就跳过那拍(不拿它的行数也不拿它的时间)，缺数据绝不蒙混。
    """
    out: dict[str, dict | None] = {}
    for seg in ("think", "act", "wrap"):
        sec = 0.0
        lines = 0
        n = 0
        for t in ticks:
            s = getattr(t, f"{seg}_s")
            if s is None or t.lines is None:
                continue
            sec += s
            lines += t.lines
            n += 1
        if n == 0:
            out[seg] = None
            continue
        out[seg] = {
            "n": n, "sec": round(sec, 1), "lines": lines,
            "sec_per_line": round(sec / lines, 2) if lines else None,
        }
    return out


def diagnose(ticks: list[throughput.Tick], friction_since: int | None = None) -> dict:
    """把一批回放出来的自改汇成体检结论：吞吐汇总 + 三段单位成本 + 最慢拍 + 摩擦对齐 + 处方。"""
    thru = throughput.summarize(ticks)
    unit = _seg_unit_cost(ticks)

    # 最贵段：在有单位成本的三段里，秒/行最大者——单位产出最贵的环节。
    priced = {s: u["sec_per_line"] for s, u in unit.items()
              if u and u["sec_per_line"] is not None}
    costliest = max(priced, key=priced.get) if priced else None

    # 最慢拍：按整拍墙上耗时降序。
    ranked = sorted([t for t in ticks if t.elapsed_s is not None],
                    key=lambda t: t.elapsed_s, reverse=True)

    # 摩擦对齐：取最磨人的那一簇，映射回它落在哪一段。
    clusters = friction.cluster(friction.load(since_days=friction_since))
    top_fric = clusters[0] if clusters else None
    fric_seg = _STAGE_SEG.get(top_fric.stage) if top_fric else None

    prescription = _prescribe(thru.get("bottleneck"), costliest, top_fric, fric_seg, unit)

    return {
        "samples": len(ticks),
        "enough": len(ticks) >= MIN_SAMPLES,
        "throughput": thru,
        "unit_cost": unit,
        "costliest_seg": costliest,
        "slowest": [t.to_meta() for t in ranked[:5]],
        "friction": {
            "cluster": top_fric.to_meta() if top_fric else None,
            "maps_to_seg": fric_seg,
        },
        "prescription": prescription,
    }


# ── 提速处方：把「这里慢」变成「我打算这样让它快，并这样验证」 ──────────────
_SPEEDUP_BY_SEG = {
    "think": (
        "想得久——意图阶段把时间耗在「读领地 + 生成今天的意图」上。",
        "给意图阶段瘦上下文：把盘点收敛成一份预算过的摘要(只喂当下要决策的那几项)，"
        "或缓存上一拍的领地快照，只增量更新变化的部分。",
        "下个窗口再体检：想段的「秒/行」应下降，或想段占比从最贵段退下来。",
    ),
    "act": (
        "做得久——动手写码这段最吃时间。这常是真在产出，未必是坏事，但每拍可拆得更小。",
        "把单拍的改动切小：一拍只推进一个最小可验证的增量(一个函数 / 一段契约)，"
        "别在一拍里既起新器官又改三处旧的。",
        "下个窗口再体检：做段的「秒/行」应趋稳或下降，最慢拍的整拍耗时回落。",
    ),
    "wrap": (
        "收尾拖沓——自测 / 合并 / push / 写日志这段在漏时间。",
        "把收尾里最久的一步先量出来再治：自测慢就缩到「金丝雀子集」先跑(见 canary.py)，"
        "合并慢就把全量回归挪到后台异步跑，腾出手进下一拍。",
        "下个窗口再体检：收段的「秒/行」与占比都应下降。",
    ),
}


def _prescribe(bottleneck: str | None, costliest: str | None,
               top_fric, fric_seg: str | None, unit: dict) -> dict | None:
    """综合「最慢段(占时间)」「最贵段(单位成本)」「最磨人簇(摩擦)」开处方。

    优先治「最贵段」——单位产出最贵的环节，提速收益最实;若它同时被摩擦账本指认(最磨人簇
    也映射到这段)，则两路证据合流，先治它最稳。无任何可定位的段则不硬开处方。
    """
    # 先选要治的段：最贵段优先(单位成本看的是划算与否)，没有则退而用最慢瓶颈段。
    target = costliest or bottleneck
    if target is None or target not in _SPEEDUP_BY_SEG:
        return None
    hypo, action, verify = _SPEEDUP_BY_SEG[target]

    corroborated = fric_seg == target and top_fric is not None
    note = None
    if corroborated:
        note = (f"摩擦账本也把最磨人的一簇(「{friction.STAGES.get(top_fric.stage, top_fric.stage)}」"
                f"·{friction.KINDS.get(top_fric.kind, top_fric.kind)}，磨人指数 {top_fric.pain:.0f})"
                f"指向同一段——两路证据合流，先治这一刀最稳。")
    elif top_fric is not None and fric_seg is not None and fric_seg != target:
        note = (f"注意：最贵段是「{_SEG_LABEL[target]}」，但摩擦账本最磨人的一簇落在"
                f"「{_SEG_LABEL[fric_seg]}」——时间与卡点指向两处，这刀治完再单独看那处。")
    return {
        "target_seg": target,
        "by": "unit_cost" if target == costliest else "bottleneck",
        "corroborated": corroborated,
        "hypothesis": hypo,
        "action": action,
        "verify": verify,
        "note": note,
    }


def manifest(last: int = DEFAULT_LAST, max_days: int = DEFAULT_MAX_DAYS,
             friction_since: int | None = None) -> dict:
    """机读：回放样本 + 三段单位成本 + 摩擦对齐 + 处方。"""
    ticks = replay(last=last, max_days=max_days)
    m = diagnose(ticks, friction_since=friction_since)
    m["window"] = {"last": last, "max_days": max_days}
    m["replayed"] = [t.to_meta() for t in ticks]
    return m


# ── 渲染 ─────────────────────────────────────────────────────────────
def _fmt_s(v: float | None) -> str:
    return f"{v:.0f}s" if v is not None else "—"


def _render(ticks: list[throughput.Tick], slow: int, friction_since: int | None) -> str:
    d = diagnose(ticks, friction_since=friction_since)
    n = d["samples"]
    L = [f"🩺⏱️ opencrab 进化瓶颈体检 —— 回放近 {n} 次真落地的自改", ""]

    if n == 0:
        L.append("（审计里读不到任何一次落地的自改——无从体检。先让生命跑几拍、落地几次再来。）")
        return "\n".join(L)
    if not d["enough"]:
        L.append(f"（只回放到 {n} 次自改，不足 {MIN_SAMPLES} 次——样本太少，"
                 "「最慢段」多半是偶然。先多落地几次再来体检。）")

    # 三段单位成本：花掉的时间 ÷ 换来的行数
    L.append("三段单位成本（该段总秒数 ÷ 换来行数，越大越不划算）：")
    L.append("  段位      拍数   总秒   行数   秒/行")
    for seg in ("think", "act", "wrap"):
        u = d["unit_cost"][seg]
        if not u:
            L.append(f"  {_SEG_LABEL[seg]:<8}  （无数据）")
            continue
        spl = f"{u['sec_per_line']:.2f}" if u["sec_per_line"] is not None else "—"
        flag = "  ⟵ 最贵" if seg == d["costliest_seg"] else ""
        L.append(f"  {_SEG_LABEL[seg]:<8}  {u['n']:>4}  {u['sec']:>6.0f} "
                 f"{u['lines']:>6} {spl:>7}{flag}")
    L.append("")

    # 吞吐侧的瓶颈段（占时间）
    thru = d["throughput"]
    if thru.get("bottleneck"):
        sh = thru["share"]
        parts = "  ".join(f"{_SEG_LABEL[k]} {sh[k]*100:.0f}%" for k in ("think", "act", "wrap"))
        L.append(f"🔍 占时间：{parts} → 最慢段「{_SEG_LABEL[thru['bottleneck']]}」")
        L.append("")

    # 最慢拍
    if slow > 0 and d["slowest"]:
        ranked = d["slowest"][:slow]
        L.append(f"🐢 最慢的 {len(ranked)} 次自改：")
        for t in ranked:
            seg = (f"想{_fmt_s(t['think_s'])}/做{_fmt_s(t['act_s'])}/收{_fmt_s(t['wrap_s'])}")
            L.append(f"   #{t['tick']} 整拍 {_fmt_s(t['elapsed_s'])}（{seg}）· {t['lines']}行"
                     + (f" · {t['journal']}" if t.get("journal") else ""))
        L.append("")

    # 摩擦对齐
    fc = d["friction"]["cluster"]
    if fc:
        seg = d["friction"]["maps_to_seg"]
        seg_txt = f"映射到「{_SEG_LABEL[seg]}」" if seg else "（无对应段）"
        L.append(f"🧱 摩擦最磨人的一簇：「{friction.STAGES.get(fc['stage'], fc['stage'])}」"
                 f"·{friction.KINDS.get(fc['kind'], fc['kind'])} "
                 f"× {fc['count']} 次，磨人指数 {fc['pain']:.0f} {seg_txt}")
        L.append("")

    # 处方
    rx = d["prescription"]
    if rx:
        L.append(f"💊 提速处方 —— 先治「{_SEG_LABEL[rx['target_seg']]}」"
                 f"（依据：{'单位成本最贵' if rx['by'] == 'unit_cost' else '占时间最多'}）")
        L.append(f"   假设：{rx['hypothesis']}")
        L.append(f"   动作：{rx['action']}")
        L.append(f"   验证：{rx['verify']}")
        if rx["note"]:
            L.append(f"   ⟡ {rx['note']}")
    else:
        L.append("💊 暂不开处方：定位不到可治的段（样本缺段或数据不足）。先把审计跑全再来。")
    L.append("")
    L.append("🦀 先诊断机器本身，才不会盲目加器官。")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 进化瓶颈体检 🩺⏱️ —— 回放近 N 次自改，定位最慢拍与低收益环节，开提速处方")
    ap.add_argument("--last", type=int, default=DEFAULT_LAST, metavar="N",
                    help=f"回放最近 N 次真落地的自改（默认 {DEFAULT_LAST}）")
    ap.add_argument("--days", type=int, default=DEFAULT_MAX_DAYS, metavar="D",
                    help=f"最多往回扫 D 天审计来凑样本（默认 {DEFAULT_MAX_DAYS}）")
    ap.add_argument("--slow", type=int, default=3, metavar="K",
                    help="列出最慢的 K 次自改（默认 3）")
    ap.add_argument("--since", type=int, default=None, metavar="DAYS",
                    help="摩擦账本只看近 DAYS 天（默认全部）")
    ap.add_argument("--gate", type=float, default=None, metavar="RATIO",
                    help="最贵段吃掉的有效时间占比超 RATIO 则退出码非零（挂钩子 / CI）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在触发 --gate 时说话（适合钩子 / CI）")
    ap.add_argument("--json", action="store_true",
                    help="机读：回放样本 + 三段单位成本 + 摩擦对齐 + 处方")
    args = ap.parse_args(argv)

    if args.last < 1:
        print(f"❌ --last 需为正整数，收到 {args.last}")
        sys.exit(2)
    if args.days < 1:
        print(f"❌ --days 需为正整数，收到 {args.days}")
        sys.exit(2)

    if args.json:
        print(json.dumps(manifest(last=args.last, max_days=args.days,
                                   friction_since=args.since),
                          ensure_ascii=False, indent=2))
        sys.exit(0)

    ticks = replay(last=args.last, max_days=args.days)
    d = diagnose(ticks, friction_since=args.since)

    # 闸门：最贵段在「想/做/收」三段总时间里的占比。
    gate_tripped = False
    if args.gate is not None and d["costliest_seg"]:
        share = d["throughput"].get("share", {}).get(d["costliest_seg"])
        gate_tripped = share is not None and share > args.gate

    if args.quiet:
        if gate_tripped:
            seg = d["costliest_seg"]
            share = d["throughput"]["share"][seg]
            print(f"🩺 瓶颈体检：最贵段「{_SEG_LABEL[seg]}」吃掉 {share*100:.0f}% 有效时间"
                  f"，超过闸门 {args.gate*100:.0f}%")
    else:
        print(_render(ticks, args.slow, args.since))

    sys.exit(1 if gate_tripped else 0)


if __name__ == "__main__":
    main()
