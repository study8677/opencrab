#!/usr/bin/env python3
"""排序层 🧮 —— 在「该往哪走」和「这就去做」之间，补上「先做哪一个」。

罗盘（compass.py）每天指方向、给一堆候选；机会池（planner.py）把选好的事排进去。
中间一直缺一环：**当桌上同时摆着五六个候选，凭什么先动这一个？** 以前是我临场拍脑袋，
而拍脑袋最容易被「最显眼 / 最好做」牵着走，而不是「最该做」。prioritizer 就补这一环。

它不自己想候选——候选交给 compass。它只做一件事：把每个候选放到**四面镜子**前照一遍，
各给一个可核对的分数，再合成一个总分排序。四面镜子刻意覆盖「执行者」最容易忽略的维度：

  · 🧩 **能力缺口**：这块有没有 golden/回归兜底、是不是长期没人碰的冷模块？
                     缺口越大越该补——这是「最该做」的主心骨。
  · 🧠 **记忆**    ：过去在这块栽过跟头吗？记忆里若有未了的失败，说明它是真痛点，加权。
  · 📡 **外界反馈**：journal / 市场信号里，外界提到过这块吗？被外界点名 > 自我臆想。
  · ⚠️ **风险**    ：supplychain 在这个文件上有没有高危隐患？有就得优先堵，别让它带病发布。

每一分都附一行**可核对的依据**（召回了几条失败记忆、覆没覆盖回归、命中哪条隐患），
排序不靠感觉，靠这些数字说话。它只读、只排序、不落盘、不改任何文件——
**先做哪个，最终仍由我自己拍板。**

用法：
    python prioritizer.py              # 给今日候选排序，打印总分 + 四维拆解
    python prioritizer.py --top 3      # 只看最该先动的前 N 个（默认全列）
    python prioritizer.py --window 30  # 透传给 compass 的「近 N 次意图」回看窗口
    python prioritizer.py --json       # 机读：导成 JSON（给 planner / 外部消费）

零第三方依赖，纯标准库。与 compass.py（指方向）、planner.py（排日程）互补。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 四维权重：合计 1.0。能力缺口是主心骨给最重。
# 2026-05-26「边际收益雷达」复盘调权（calibration+value+harvest 视角）：把 0.10 从
# 「风险」挪给「外界反馈」。回看近 50 航次，高耗低收益的典型是防御性/照镜子航次
# （risk 驱动的供应链顺手清、纯 --check 跑一圈），harvest 多判 🫧泡沫、无真实受益者；
# 而 value.py 的核心判据正是「被外界点名 > 自我臆想」，feedback 才是「会结真收益而非
# 泡沫」最可靠的代理，却长期被压最低。本仓纯标准库自包含，high 危隐患极少真兑现。
# 故：feedback 0.15→0.25（升），risk 0.30→0.20（降）；gap/memory 不动。
WEIGHTS = {"gap": 0.35, "feedback": 0.25, "memory": 0.20, "risk": 0.20}


@dataclasses.dataclass
class Signal:
    """一面镜子照出的一个分量：0~1 强度 + 一行可核对的依据。"""
    score: float          # 归一化到 0~1
    basis: str            # 这个分怎么来的（可核对）

    def clamp(self) -> "Signal":
        self.score = max(0.0, min(1.0, self.score))
        return self


@dataclasses.dataclass
class Ranked:
    """一个候选的排序结果：原候选 + 四维信号 + 合成总分。"""
    candidate: dict
    signals: dict          # name -> Signal
    total: float           # 0~100，便于阅读

    def to_meta(self) -> dict:
        return {
            "title": self.candidate.get("title", ""),
            "lane": self.candidate.get("lane", ""),
            "grounded_in": self.candidate.get("grounded_in", ""),
            "total": round(self.total, 1),
            "signals": {k: {"score": round(s.score, 3), "basis": s.basis}
                        for k, s in self.signals.items()},
        }


# ── 把候选定位到一个「主文件」：四面镜子都围着这个文件照 ──────────────
def _primary_path(candidate: dict) -> str:
    """从候选的 grounded_in 里抽出第一个像文件路径的词（compass 用 `·`/空格分隔）。"""
    ground = str(candidate.get("grounded_in", ""))
    for tok in re.split(r"[·\s]+", ground):
        tok = tok.strip()
        if tok.endswith(".py") or "/" in tok:
            return tok.split()[0]
    return ground.split()[0] if ground else ""


def _stem(path: str) -> str:
    return pathlib.PurePosixPath(path).stem if path else ""


# ── 🧩 能力缺口：缺 golden/回归 + 是不是冷模块 ────────────────────────
def _gap_signal(candidate: dict) -> Signal:
    """compass 已把候选分到三航道：修炼=明确缺兜底，探索=长期冷落，协作=对外面。

    缺口分主要看：① 这块有没有被 regression 点名（没有=真空，最该补）；
    ② lane 本身的语义（修炼>探索>协作 地反映「补内功」的紧迫度）。
    """
    lane = candidate.get("lane", "")
    path = _primary_path(candidate)
    stem = _stem(path)
    covered = _has_regression(stem) if stem else True
    base = {"修炼": 0.7, "探索": 0.5, "协作": 0.35}.get(lane, 0.4)
    if not covered and stem:
        base += 0.3
        basis = f"`{path}` 未被 regression.py 点名（无回归兜底），lane=「{lane}」"
    else:
        basis = f"lane=「{lane}」；`{path or '—'}` 已有回归覆盖或非单一模块"
    return Signal(base, basis).clamp()


def _has_regression(stem: str) -> bool:
    p = REPO_ROOT / "regression.py"
    try:
        return bool(stem) and stem in p.read_text("utf-8", errors="ignore")
    except Exception:
        return True   # 读不到就别误判成「缺口」，保守给「已覆盖」


# ── 🧠 记忆：这块过去栽过跟头吗？未了的失败 = 真痛点 ─────────────────
def _memory_signal(candidate: dict) -> Signal:
    """召回与候选相关的历史经历：失败越多、越近，说明这是反复咬人的真痛点，加权。"""
    query = f"{candidate.get('title', '')} {candidate.get('grounded_in', '')}"
    try:
        import memory
        eps = memory.recall(query, k=5)
    except Exception:
        return Signal(0.0, "记忆层不可用或无相关召回").clamp()
    if not eps:
        return Signal(0.0, "记忆里 0 条相关经历（这块还没踩过坑）").clamp()
    fails = sum(1 for e in eps if not getattr(e, "ok", True))
    # 有失败：按失败占比给分（满是失败=强痛点）；全成功：轻微降温（做得差不多了）。
    if fails:
        score = 0.4 + 0.6 * (fails / len(eps))
        basis = f"召回 {len(eps)} 条相关经历，其中 {fails} 条失败——是反复咬人的痛点"
    else:
        score = 0.15
        basis = f"召回 {len(eps)} 条相关经历且全部成功——这块已较稳，不急"
    return Signal(score, basis).clamp()


# ── 📡 外界反馈：被外界点名 > 自我臆想 ────────────────────────────────
_FEEDBACK_FILES = ("journal/EVOLUTION.md",)


def _feedback_signal(candidate: dict) -> Signal:
    """journal / 市场信号里，外界提到过这块吗？被点名次数越多越该回应。"""
    stem = _stem(_primary_path(candidate))
    if not stem:
        return Signal(0.0, "候选未定位到具体模块，无法核对外界反馈").clamp()
    hits = 0
    for rel in _FEEDBACK_FILES:
        p = REPO_ROOT / rel
        try:
            text = p.read_text("utf-8", errors="ignore")
        except Exception:
            continue
        hits += len(re.findall(re.escape(stem), text))
    hits += _market_mentions(stem)
    if hits <= 0:
        return Signal(0.0, f"journal/市场信号里 0 次提及 `{stem}`").clamp()
    # 提及次数收敛到 0~1：1 次≈0.4，3 次封顶。
    score = min(1.0, 0.4 + 0.2 * (hits - 1))
    return Signal(score, f"journal/市场信号里 {hits} 次提及 `{stem}`").clamp()


def _market_mentions(stem: str) -> int:
    """外界市场信号（lookout 落盘的本地缓存）里提到这块几次；不可用则 0，不联网。"""
    try:
        import lookout
        market = lookout.market_load()
    except Exception:
        return 0
    try:
        blob = json.dumps(market, default=lambda o: getattr(o, "__dict__", str(o)),
                          ensure_ascii=False)
    except Exception:
        return 0
    return len(re.findall(re.escape(stem), blob))


# ── ⚠️ 风险：supplychain 在这个文件上有高危隐患吗？带病不能发 ──────────
def _risk_index() -> dict:
    """跑一次 supplychain 静态扫描，按文件聚合 (高危数, 低危数)。读不到则空。"""
    idx: dict[str, list[int]] = {}
    try:
        import supplychain
        data = supplychain.manifest()
    except Exception:
        return idx
    for f in data.get("findings", []):
        path = f.get("path", "")
        if not path:
            continue
        bucket = idx.setdefault(path, [0, 0])
        if f.get("severity") == "high":
            bucket[0] += 1
        else:
            bucket[1] += 1
    return idx


def _risk_signal(candidate: dict, risk_idx: dict) -> Signal:
    """候选主文件命中的供应链隐患：高危必须优先堵（带病发布最危险），低危轻微加权。"""
    path = _primary_path(candidate)
    high, low = risk_idx.get(path, [0, 0])
    if high:
        score = min(1.0, 0.7 + 0.15 * (high - 1))
        return Signal(score, f"`{path}` 有 {high} 处高危供应链隐患——带病不能发，先堵").clamp()
    if low:
        return Signal(0.3, f"`{path}` 有 {low} 处低危隐患，值得顺手清").clamp()
    return Signal(0.0, f"`{path or '—'}` 供应链扫描干净").clamp()


# ── 合成排序 ─────────────────────────────────────────────────────────
def _gather_candidates(window: int) -> list[dict]:
    """候选交给 compass：把三航道的候选摊平成一个列表。compass 不可用则空。"""
    try:
        import compass
        chart = compass.chart(window=window)
    except Exception:
        return []
    cands: list[dict] = []
    for lane_cands in chart.get("lanes", {}).values():
        cands.extend(lane_cands)
    return cands


def rank(window: int = 24) -> list[Ranked]:
    """给 compass 的今日候选排序：四维各打一分，加权合成总分，高分在前。"""
    candidates = _gather_candidates(window)
    risk_idx = _risk_index()
    ranked: list[Ranked] = []
    for c in candidates:
        signals = {
            "gap": _gap_signal(c),
            "risk": _risk_signal(c, risk_idx),
            "memory": _memory_signal(c),
            "feedback": _feedback_signal(c),
        }
        total = sum(WEIGHTS[k] * s.score for k, s in signals.items()) * 100
        ranked.append(Ranked(c, signals, total))
    ranked.sort(key=lambda r: r.total, reverse=True)
    return ranked


def manifest(window: int = 24, top: int | None = None) -> dict:
    """导出纯数据（给 planner / 外部工具消费）。"""
    ranked = rank(window)
    if top:
        ranked = ranked[:top]
    return {"window": window, "count": len(ranked),
            "ranked": [r.to_meta() for r in ranked]}


_SIG_ICON = {"gap": "🧩", "risk": "⚠️", "memory": "🧠", "feedback": "📡"}
_SIG_NAME = {"gap": "能力缺口", "risk": "风险", "memory": "记忆", "feedback": "外界反馈"}


def render(ranked: list[Ranked], top: int | None = None) -> str:
    shown = ranked[:top] if top else ranked
    L = ["🦀🧮 进化候选排序 · 先做哪一个",
         f"   罗盘端来 {len(ranked)} 个候选，按「最该做」从高到低排（满分 100）。"]
    if not shown:
        L.append("   （compass 暂无候选——领地这几面已被近期意图覆盖得很满。）")
        return "\n".join(L)
    for i, r in enumerate(shown, 1):
        L += ["", f"  #{i}  [{r.total:5.1f}] {r.candidate.get('title', '')}",
              f"        航道：{r.candidate.get('lane', '—')}  ·  "
              f"凭据：{r.candidate.get('grounded_in', '—')}"]
        # 四维按对总分的贡献从大到小列，让「为什么排这名」一眼可核对。
        contribs = sorted(r.signals.items(),
                          key=lambda kv: WEIGHTS[kv[0]] * kv[1].score, reverse=True)
        for name, sig in contribs:
            pts = WEIGHTS[name] * sig.score * 100
            L.append(f"        {_SIG_ICON[name]} {_SIG_NAME[name]} +{pts:4.1f}：{sig.basis}")
    L += ["", "—— 排序只摆出「先做哪个」的依据，拍板的是我自己。"]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 排序层 🧮 —— 给今日进化候选排个「先做哪一个」")
    ap.add_argument("--window", type=int, default=24, metavar="N",
                    help="透传给 compass 的「近 N 次意图」回看窗口（默认 24）")
    ap.add_argument("--top", type=int, default=None, metavar="N",
                    help="只看最该先动的前 N 个（默认全列）")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    args = ap.parse_args(argv)

    window = max(1, args.window)
    top = args.top if args.top and args.top > 0 else None
    if args.json:
        print(json.dumps(manifest(window, top), ensure_ascii=False, indent=2))
    else:
        print(render(rank(window), top))
    sys.exit(0)  # 只读排序，永远正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
