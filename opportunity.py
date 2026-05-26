#!/usr/bin/env python3
"""机会成本台 🎯 —— 用「需求热度 × 证据缺口 × 摩擦耗时」给下一步排个收益序，逼自己少做低收益事。

为什么要有它：领地里已经有人指方向（compass）、有人排「先做哪个」（prioritizer）。
但 prioritizer 照的四面镜子里，没有一面正对「这件事到底值不值得做」——它会让「最该补内功」
的事浮上来，却答不上：**如果我把今天这段时间花在它身上，相比花在别处，亏不亏？** 这正是
机会成本要问的。提速的第一步从来不是「做得更快」，而是「先别做那些做了也没人受益的事」。

它把每个**真实器官**放进一道三因子的收益估计里，三个因子都来自已经在跑的痕迹，不臆测：

  · 🔥 **需求热度**：usageheat 里这个器官近窗口被点名多少次。被反复用到 = 真有人靠它，
                    在它身上花时间才有人受益；从没被提起的，修得再好也是自娱自乐。
  · 🧾 **证据缺口**：evidence 里它的复验状态——失守/从未验证 = 缺口最大，最值得补；
                    新鲜复验过的 = 没缺口，再投入是边际递减。
  · 🧱 **摩擦耗时**：friction 账本里，事由提到这个器官的摩擦合计磨了多少分钟。它在反复
                    偷我的时间——治掉它的回报是持续的，不是一次性的。

合成方式刻意**不是**四平八稳的加权和，而是「缺口 × 需求」：

    收益 = (证据缺口·权 + 摩擦·权) × (需求放大系数)

——缺口和摩擦决定「这件事有多少待补的空间」，需求决定「补了到底有没有人受益」。一个没人
用的器官就算证据全失守，需求系数也会把它的收益压到很低（先别做）；一个高频被用、又缺兜底、
又反复磨人的器官，三因子叠满，自然冲到最前。每一分都附一行**可核对的依据**。

「机会成本」体现在排序的**落差**上：榜首是此刻回报最高的一步；选任何靠后的去做，就等于
主动放弃榜首那份回报——那个差值，就是你这次选择的机会成本。它只读、不落盘、不替你拍板。

用法：
    python opportunity.py              # 给全部器官按「下一步收益」排序 + 每名的机会成本落差
    python opportunity.py --top 5      # 只看最值得先动的前 N 个
    python opportunity.py --days 7     # 需求热度/摩擦的回看窗口（默认 7 天）
    python opportunity.py --json       # 机读：导出排序与三因子拆解

零第三方依赖，纯标准库。台子只读领地（usageheat / evidence / friction），无副作用。
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

# 两个内因子的权重（合计 1.0）：缺口是主体（待补的空间），摩擦是放大器（持续偷时间）。
# 需求不在这里——它是乘在外面的「有没有人受益」系数，单独决定收益要不要被压低。
WEIGHTS = {"gap": 0.6, "friction": 0.4}
# 需求放大系数的下限：哪怕从没被提起，缺口/摩擦本身也还留一点收益（别把冷器官一刀切到 0）。
DEMAND_FLOOR = 0.3
# 摩擦耗时归一化的封顶分钟数：超过这个量级就当「满格痛」，再多不额外加权。
FRICTION_CAP = 60.0

_MOD_RE = re.compile(r"`?([a-z_][a-z0-9_]*)\.py`?")

# 证据复验状态 → 缺口强度（0~1）：缺口越大越值得补。
_GAP_BY_STATE = {
    "broken": 1.0,     # 最近一次复验失守——缺口最深
    "unproven": 0.85,  # 立了声明却从未验证过
    "stale": 0.55,     # 验过但已发凉
    None: 0.45,        # 压根没有对应证据声明（无从复验，亦是一种缺口）
    "fresh": 0.05,     # 近期复验仍绿——几乎无缺口，再投入边际递减
}


@dataclasses.dataclass
class Factor:
    """一个因子的分量：0~1 强度 + 一行可核对的依据。"""
    score: float
    basis: str

    def clamp(self) -> "Factor":
        self.score = max(0.0, min(1.0, self.score))
        return self


@dataclasses.dataclass
class Opportunity:
    """一个器官的下一步机会：三因子 + 合成收益分（0~100）。"""
    name: str
    summary: str
    demand: Factor
    gap: Factor
    friction: Factor
    payoff: float          # 合成收益（0~100），越高越值得先动

    def to_meta(self) -> dict:
        return {
            "name": self.name, "summary": self.summary,
            "payoff": round(self.payoff, 1),
            "factors": {
                "demand": {"score": round(self.demand.score, 3), "basis": self.demand.basis},
                "gap": {"score": round(self.gap.score, 3), "basis": self.gap.basis},
                "friction": {"score": round(self.friction.score, 3), "basis": self.friction.basis},
            },
        }


# ── 🔥 需求热度：usageheat 里近窗口被点名多少次 ──────────────────────────
def _heat_index(days: int) -> dict[str, dict]:
    """复用 usageheat.build()，取每个器官的 mentions / verify_state / age_days / summary。"""
    try:
        import usageheat
        heats = usageheat.build(days=days)
    except Exception:
        return {}
    return {h.name: {"summary": h.summary, "mentions": h.mentions,
                     "verify_state": h.verify_state, "age_days": h.age_days,
                     "temp": h.temp}
            for h in heats}


def _demand_factor(mentions: int, max_mentions: int) -> Factor:
    """被点名次数对榜内最高值归一化：被用得越多，在它身上花时间越有人受益。"""
    if max_mentions <= 0:
        return Factor(0.0, "近窗口里全员都没被点名——需求信号缺失").clamp()
    score = mentions / max_mentions
    if mentions == 0:
        return Factor(0.0, "近窗口里 0 次被点名（没人用 → 修得再好也没人受益）").clamp()
    return Factor(score, f"近窗口里被点名 {mentions} 次（榜内最高 {max_mentions}）").clamp()


# ── 🧾 证据缺口：evidence 复验状态 ────────────────────────────────────────
def _gap_factor(verify_state: str | None, age_days: float | None) -> Factor:
    """复验状态映射到缺口强度：失守/未验 缺口最大，新鲜则几乎无缺口。"""
    score = _GAP_BY_STATE.get(verify_state, 0.45)
    label = {"broken": "证据最近一次复验失守 🔴", "unproven": "立了证据声明却从未验证",
             "stale": "证据验过但已发凉", "fresh": "证据近期复验仍 ✅绿",
             None: "没有对应的证据声明可复验"}.get(verify_state, f"证据状态：{verify_state}")
    if age_days is not None and verify_state in ("stale", "fresh"):
        label += f"（距今 {age_days:.0f} 天）"
    return Factor(score, label).clamp()


# ── 🧱 摩擦耗时：friction 账本里事由提到这个器官的合计分钟 ──────────────────
def _friction_index(days: int) -> dict[str, float]:
    """扫 friction 账本，把每条摩擦按事由里点名的器官摊分到分钟数上。

    一条事由可能点到多个器官 → 把这条的耗时均分给它们，不重复计满。读不到则空。
    """
    try:
        import friction
        items = friction.load(since_days=days)
    except Exception:
        return {}
    minutes: dict[str, float] = {}
    for f in items:
        mods = set(_MOD_RE.findall(f.topic or ""))
        if not mods:
            continue
        share = f.cost / len(mods)
        for mod in mods:
            minutes[mod] = minutes.get(mod, 0.0) + share
    return minutes


def _friction_factor(mins: float) -> Factor:
    """摊到这个器官的摩擦分钟，对封顶值归一化：反复偷时间的，治掉回报是持续的。"""
    if mins <= 0:
        return Factor(0.0, "摩擦账本里没有事由点到它（没在偷时间）").clamp()
    score = min(1.0, mins / FRICTION_CAP)
    return Factor(score, f"摩擦账本里相关事由合计磨了 ≈{mins:.0f} 分钟").clamp()


# ── 合成排序 ─────────────────────────────────────────────────────────────
def rank(days: int = 7) -> list[Opportunity]:
    """给全部器官按下一步收益排序：缺口×摩擦决定空间，需求决定有没有人受益。"""
    heat = _heat_index(days)
    if not heat:
        return []
    fric = _friction_index(days)
    max_mentions = max((v["mentions"] for v in heat.values()), default=0)

    out: list[Opportunity] = []
    for name, v in heat.items():
        demand = _demand_factor(v["mentions"], max_mentions)
        gap = _gap_factor(v["verify_state"], v["age_days"])
        friction = _friction_factor(fric.get(name, 0.0))
        # 内因子：待补的空间。需求系数：补了有没有人受益（下限 DEMAND_FLOOR）。
        deficiency = WEIGHTS["gap"] * gap.score + WEIGHTS["friction"] * friction.score
        demand_mult = DEMAND_FLOOR + (1.0 - DEMAND_FLOOR) * demand.score
        payoff = 100.0 * deficiency * demand_mult
        out.append(Opportunity(name, v["summary"], demand, gap, friction, payoff))
    out.sort(key=lambda o: o.payoff, reverse=True)
    return out


def manifest(days: int = 7, top: int | None = None) -> dict:
    """机读：排序 + 三因子拆解 + 每名相对榜首的机会成本落差。"""
    ranked = rank(days)
    best = ranked[0].payoff if ranked else 0.0
    shown = ranked[:top] if top else ranked
    rows = []
    for o in shown:
        meta = o.to_meta()
        meta["opportunity_cost"] = round(best - o.payoff, 1)
        rows.append(meta)
    return {"days": days, "count": len(ranked), "ranked": rows}


# ── 展示 ─────────────────────────────────────────────────────────────────
def render(ranked: list[Opportunity], top: int | None = None) -> str:
    L = ["🦀🎯 下一步机会成本台 · 先做收益最高的那件",
         f"   把 {len(ranked)} 个器官放进「需求 × 缺口 × 摩擦」算收益，越靠前越值得先动。"]
    if not ranked:
        L.append("   （usageheat 端不来器官画像——它或它依赖的痕迹此刻读不到。）")
        return "\n".join(L)
    best = ranked[0].payoff
    shown = ranked[:top] if top else ranked
    for i, o in enumerate(shown, 1):
        cost = best - o.payoff
        tail = "← 此刻回报最高的一步" if i == 1 else f"机会成本 -{cost:4.1f}（选它=放弃榜首这份回报）"
        L += ["", f"  #{i}  [{o.payoff:5.1f}] {o.name}.py  {tail}",
              f"        {o.summary}",
              f"        🔥 需求 {o.demand.score:.2f}：{o.demand.basis}",
              f"        🧾 缺口 {o.gap.score:.2f}：{o.gap.basis}",
              f"        🧱 摩擦 {o.friction.score:.2f}：{o.friction.basis}"]
    low = [o for o in ranked if o.payoff < 5.0]
    if low:
        names = "、".join(o.name for o in low[:6]) + ("…" if len(low) > 6 else "")
        L += ["", f"  低收益区（<5 分，先别做）：{names}",
              "  —— 它们多半没人在用、或没缺口可补；现在动它们，是在花时间换不来受益。"]
    L += ["", "—— 台子只摆出收益落差，做哪件、要不要做，仍由我自己拍板。"]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 机会成本台 🎯 —— 用需求/缺口/摩擦给下一步排收益序，少做低收益事")
    ap.add_argument("--days", type=int, default=7, metavar="N",
                    help="需求热度 / 摩擦的回看窗口天数（默认 7）")
    ap.add_argument("--top", type=int, default=None, metavar="N",
                    help="只看最值得先动的前 N 个（默认全列）")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    args = ap.parse_args(argv)

    if args.days < 1:
        print(f"❌ --days 需为正整数，收到 {args.days}")
        sys.exit(2)
    top = args.top if args.top and args.top > 0 else None
    if args.json:
        print(json.dumps(manifest(args.days, top), ensure_ascii=False, indent=2))
    else:
        print(render(rank(args.days), top))
    sys.exit(0)  # 只读排序，永远正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
