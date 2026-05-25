#!/usr/bin/env python3
"""决策策略官 🧭 —— 把「什么时候该自改、什么时候该先观察、什么时候该停手求证」
沉淀成一套可执行的策略，并能对同一目标比较多条行动路线、给出保守/激进两档建议。

为什么要有它：这只螃蟹已经会诊断(errors)、会记忆(memory)、会动手(hands)、
会裁决(judge)、会加练(coach)——**它会做事了，却还缺一个稳定的「怎么选做什么」的脑子**。
面对一个目标，它常常一头扎进去就改，既没掂量「我到底看懂了没」，也没比较
「除了直接改，是不是该先观察一轮、或先补一道验证再动」。裁决官(judge)是事后才说
「这次值不值」，等它开口，主干可能已经脏了。策略官补的是事前那一脚：在动手之前
先决定**该用哪种姿态**——

  - 🔴 停手求证(verify)：还没看懂。把握不足时，先弄清楚再说，凭感觉自改最危险。
  - 🟡 先观察(observe)：看懂了，但这步难撤回 / 动了要害又没兜底，先看信号、补验证。
  - 🟢 自改(act)：看懂了，且撤得回或有验证兜底，可以放手动手。

并且对同一个目标，它接受**多条候选行动路线**(直接改 / 先加守卫再改 / 先观察一轮…)，
沿收益、把握、可逆性、影响面、验证兜底五个角度给每条打分，最后给出两档建议：

  - 保守档：风险厌恶，优先「站得稳的小步」，宁可先观察/求证也不冒进。
  - 激进档：在不鲁莽的前提下追最大收益，可逆的步子敢于把姿态再放大一档。

策略官只出主意、不动手，更不替 judge 拍板合并；它读 memory「上次这么干栽过没」来校准
胆量——若相似往事曾翻车，激进档自动收敛。判断落进被 .gitignore 的
state/policy/calls.jsonl，可回溯但绝不反噬：读写出错统统吞掉，策略官不能成为新故障源。

零第三方依赖，纯标准库。

用法:
    python policy.py "<目标描述>"                      # 用内置示意路线演示两档建议
    python policy.py "<目标>" --route "直接改,3,0.85,0.9,y,2,n" --route "先加守卫再改,3,0.85,0.95,y,3,n"
        # --route 规格：名字,收益(1~3),把握(0~1),可逆(0~1),验证(y/n/?),影响文件数,是否动要害(y/n)
    python policy.py --recent                          # 回看最近几次决策
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_POLICY_DIR = _REPO_ROOT / "state" / "policy"      # 落在被 .gitignore 的 state/ 里
_CALLS = _POLICY_DIR / "calls.jsonl"

# 三种行动姿态（按胆量从小到大排序，便于激进档「放大一档」/保守档「收一档」）
VERIFY = "verify"     # 🔴 停手求证：还没看懂，先弄清楚
OBSERVE = "observe"   # 🟡 先观察：看懂了但还没站稳，看信号/补验证
ACT = "act"           # 🟢 自改：看懂了又撑得住，放手动手
_BOLDNESS = {VERIFY: 0, OBSERVE: 1, ACT: 2}
_BY_BOLDNESS = {v: k for k, v in _BOLDNESS.items()}
_STANCE_LABELS = {VERIFY: "🔴 停手求证", OBSERVE: "🟡 先观察", ACT: "🟢 自改"}

# 决策阈值（都从经验出发，宁可保守）
CONF_LOW = 0.45       # 把握低于此：根本没看懂，只能先求证
CONF_OK = 0.70        # 把握高于此：才算「心里有底」
REV_LOW = 0.45        # 可逆性低于此：这步难撤回，得当心
WIDE_BLAST = 8        # 影响这么多文件：面太宽，风险加码


# ── 一条候选行动路线 ────────────────────────────────────────────────
@dataclasses.dataclass
class Route:
    """达成同一目标的一条候选路线：要害是「收益多大、我多有把握、翻车好不好撤」。"""
    name: str                       # 路线短名（也用作建议里的指代）
    gain: int = 2                   # 预期收益 1~3（越高越想要）
    confidence: float = 0.6         # 我对「这么做能行 / 已看懂」的把握 0~1
    reversibility: float = 0.7      # 翻车了能多轻松撤回 0~1（越高越敢试）
    verified: bool | None = None    # 有没有验证/守卫兜底（None=没声明）
    blast: int = 1                  # 影响面：大概碰几个文件
    touches_vital: bool = False     # 是否动到要害器官（crab/hands/checkup…）

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 对一条路线的判断 ────────────────────────────────────────────────
@dataclasses.dataclass
class Decision:
    """对单条路线的判断：该用什么姿态 + 风险/收益评分 + 人话依据。"""
    route: str                      # 路线名
    stance: str                     # VERIFY / OBSERVE / ACT
    risk: int                       # 风险点（越高越危险）
    gain: int                       # 预期收益（沿用 Route.gain）
    reasons: list                   # 评分背后的人话理由

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _risk_of(r: Route) -> tuple[int, list[str]]:
    """把一条路线的风险量成整数点 + 人话理由：把握、可逆、要害、面宽、兜底。"""
    risk = 0
    reasons: list[str] = []
    if r.confidence < CONF_LOW:
        risk += 3
        reasons.append(f"把握仅 {r.confidence:.0%}，其实还没看懂（风险 +3）")
    elif r.confidence < CONF_OK:
        risk += 1
        reasons.append(f"把握 {r.confidence:.0%}，心里没完全有底（风险 +1）")
    if r.reversibility < REV_LOW:
        risk += 2
        reasons.append(f"可逆性仅 {r.reversibility:.0%}，翻车难撤回（风险 +2）")
    elif r.reversibility < 0.7:
        risk += 1
        reasons.append(f"可逆性 {r.reversibility:.0%}，撤回有点费劲（风险 +1）")
    if r.touches_vital:
        risk += 2
        reasons.append("动到要害器官（风险 +2）")
        if r.verified is not True:
            risk += 1
            reasons.append("动要害却没验证兜底（风险 +1）")
    if r.blast >= WIDE_BLAST:
        risk += 2
        reasons.append(f"一次碰 {r.blast} 个文件，面太宽（风险 +2）")
    elif r.blast >= 4:
        risk += 1
        reasons.append(f"碰 {r.blast} 个文件，面偏宽（风险 +1）")
    if r.verified is False:
        risk += 1
        reasons.append("明知没验证兜底（风险 +1）")
    return risk, reasons


def decide(r: Route) -> Decision:
    """对单条路线定姿态：没看懂先求证，难撤回/动要害没兜底先观察，否则放手自改。"""
    risk, reasons = _risk_of(r)
    if r.confidence < CONF_LOW:
        stance = VERIFY
        reasons.append("→ 把握不足，先停手求证：凭感觉自改最危险")
    elif (r.reversibility < REV_LOW or r.touches_vital) and r.verified is not True:
        stance = OBSERVE
        reasons.append("→ 看懂了但难撤回/动要害又没兜底，先观察信号、补验证再动")
    else:
        stance = ACT
        reasons.append("→ 看懂了，且撤得回或有兜底，可以自改")
    return Decision(route=r.name, stance=stance, risk=risk,
                    gain=r.gain, reasons=reasons)


# ── 两档建议 ────────────────────────────────────────────────────────
@dataclasses.dataclass
class Recommendation:
    """一档建议：选哪条路线、用什么姿态、为什么。"""
    tier: str                       # "conservative" / "aggressive"
    route: str                      # 选中的路线名
    stance: str                     # 建议姿态（可能比该路线原生姿态收/放一档）
    why: str                        # 一句话理由

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _bolder(stance: str) -> str:
    """把姿态放大一档（求证→观察→自改），已是最大档则不变。"""
    return _BY_BOLDNESS.get(min(_BOLDNESS[stance] + 1, ACT and _BOLDNESS[ACT]), stance)


def _safer(stance: str) -> str:
    """把姿态收一档（自改→观察→求证），已是最小档则不变。"""
    return _BY_BOLDNESS.get(max(_BOLDNESS[stance] - 1, _BOLDNESS[VERIFY]), stance)


def _pick_conservative(decs: list[Decision]) -> Recommendation:
    """保守档：风险厌恶。挑「收益减两倍风险」最高者，且原生自改但风险偏高时收一档。"""
    best = max(decs, key=lambda d: (d.gain - 2 * d.risk, -d.risk))
    stance = best.stance
    why = "站得最稳的一步：收益够用而代价最小。"
    if stance == ACT and best.risk >= 3:
        stance = _safer(stance)  # 风险不低，先观察一轮稳一手
        why = "本可直接改，但风险不低——保守起见先观察一轮、补验证再动手。"
    elif stance == VERIFY:
        why = "最稳的路线本身就没看透——先停手求证，别急着选其他更险的。"
    return Recommendation("conservative", best.route, stance, why)


def _pick_aggressive(decs: list[Decision], *, burned: bool) -> Recommendation:
    """激进档：在不鲁莽前提下追最大收益。挑「两倍收益减风险」最高者；
    若该路线可逆性足够且没踩过同类坑，把姿态放大一档抢进度。"""
    routes_by_name = {d.route: d for d in decs}
    best = max(decs, key=lambda d: (2 * d.gain - d.risk, d.gain))
    stance = best.stance
    why = "收益最高、代价可接受的一步，值得一搏。"
    if burned:
        why = "本想更激进，但记忆里同类干法栽过——保持原姿态，别二次踩坑。"
    elif stance != ACT and best.risk <= 2:
        bolder = _bolder(stance)
        if bolder != stance:
            stance = bolder
            why = "代价可控，激进起见把姿态放大一档、直接推进抢进度。"
    return Recommendation("aggressive", best.route, stance, why)


# ── 一次完整的决策 ──────────────────────────────────────────────────
@dataclasses.dataclass
class Advice:
    """对一个目标、一组候选路线的完整决策：逐条判断 + 保守/激进两档建议。"""
    goal: str
    decisions: list                 # list[Decision]
    conservative: Recommendation
    aggressive: Recommendation
    seeds: list = dataclasses.field(default_factory=list)  # 相似往事提示行
    at: str = ""

    def to_dict(self) -> dict:
        return {"at": self.at, "goal": self.goal,
                "decisions": [d.to_dict() for d in self.decisions],
                "conservative": self.conservative.to_dict(),
                "aggressive": self.aggressive.to_dict(),
                "seeds": list(self.seeds)}

    def render(self) -> str:
        """把决策摊成给人看的多行报告。"""
        lines = [f"🧭  决策 · 目标：{self.goal[:60]}", ""]
        lines.append("   候选路线逐条判断：")
        for d in self.decisions:
            lines.append(f"     · {d.route}：{_STANCE_LABELS.get(d.stance, d.stance)}"
                         f"（收益 {d.gain} / 风险 {d.risk}）")
        lines.append("")
        for rec in (self.conservative, self.aggressive):
            tag = "🛡️ 保守档" if rec.tier == "conservative" else "⚔️ 激进档"
            lines.append(f"   {tag}：走「{rec.route}」，"
                         f"{_STANCE_LABELS.get(rec.stance, rec.stance)}")
            lines.append(f"      {rec.why}")
        if self.seeds:
            lines.append("   带着记忆选：")
            lines += [f"     {s}" for s in self.seeds]
        return "\n".join(lines)


def advise(goal: str, routes: list[Route], *, use_memory: bool = True) -> Advice:
    """对一个目标比较多条行动路线，给出保守/激进两档建议。

    会软引入 memory：捞相似往事，若同类干法曾翻车，则激进档自动收敛（不放大姿态）。
    无候选路线时，退化为「先停手求证：连怎么做都没想清楚」。
    """
    goal = (goal or "").strip() or "(未命名目标)"
    if not routes:
        only = Recommendation("conservative", "(无路线)", VERIFY,
                              "连一条可比的行动路线都没列出来——先停手把选项想清楚。")
        return Advice(goal=goal, decisions=[], conservative=only,
                      aggressive=dataclasses.replace(only, tier="aggressive"))

    decisions = [decide(r) for r in routes]
    seeds, burned = _recall_seeds(goal) if use_memory else ([], False)
    return Advice(
        goal=goal, decisions=decisions,
        conservative=_pick_conservative(decisions),
        aggressive=_pick_aggressive(decisions, burned=burned),
        seeds=seeds)


def _recall_seeds(text: str, k: int = 2) -> tuple[list[str], bool]:
    """软引入 memory：捞相似往事拼成提示行，并判断「同类干法是否栽过」。

    返回 (提示行, burned)；缺/错则返回 ([], False)，让上层照常给激进建议。
    """
    try:
        import memory
        lines: list[str] = []
        burned = False
        for s, ep in memory.recall(text, k=k):
            if not ep.ok and s >= 0.5:
                burned = True
            warn = "⚠️ 上次栽过 — " if not ep.ok else ""
            lines.append(f"{warn}{ep.headline()}（相似 {s:.0%}）")
        return lines, burned
    except Exception:
        return [], False


# ── 落地 / 回看 ─────────────────────────────────────────────────────
def record(advice: Advice) -> Advice:
    """把一次决策落进 state/policy/calls.jsonl；任何写入异常都吞掉，绝不反噬。"""
    advice.at = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        _POLICY_DIR.mkdir(parents=True, exist_ok=True)
        with _CALLS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(advice.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass   # 策略官是参谋，落档失败也绝不弄死这只生命
    return advice


def recent(limit: int = 10) -> list[dict]:
    """读出最近落档的决策(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _CALLS.exists():
        return []
    out: list[dict] = []
    for line in _CALLS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


# ── 给 crab 调用的便捷入口：一个目标 + 几条路线 → 两档建议并落档 ────────
def weigh(goal: str, routes: list[Route]) -> Advice:
    """从一个目标与一组候选路线直接出两档建议并落档，供心跳在动手前调用。"""
    return record(advise(goal, routes))


# ── CLI ─────────────────────────────────────────────────────────────
def _parse_route(spec: str) -> Route:
    """解析 --route 规格：名字,收益,把握,可逆,验证(y/n/?),影响文件数,要害(y/n)。

    后面的字段都可省，省了就用 Route 的默认值；解析不动的字段从容跳过。
    """
    parts = [p.strip() for p in (spec or "").split(",")]
    kw: dict = {}
    if parts and parts[0]:
        kw["name"] = parts[0]

    def _num(idx, cast, key):
        if len(parts) > idx and parts[idx]:
            try:
                kw[key] = cast(parts[idx])
            except ValueError:
                pass

    _num(1, int, "gain")
    _num(2, float, "confidence")
    _num(3, float, "reversibility")
    if len(parts) > 4 and parts[4]:
        v = parts[4].lower()
        kw["verified"] = True if v in ("y", "yes", "true", "1") else \
            (False if v in ("n", "no", "false", "0") else None)
    _num(5, int, "blast")
    if len(parts) > 6 and parts[6]:
        kw["touches_vital"] = parts[6].lower() in ("y", "yes", "true", "1")
    return Route(**kw) if kw.get("name") else Route(name=spec[:20] or "(路线)")


def _demo_routes() -> list[Route]:
    """没给 --route 时的内置示意路线：直接改 / 先加守卫再改 / 先观察一轮。"""
    return [
        Route("直接改", gain=3, confidence=0.55, reversibility=0.6, verified=None, blast=2),
        Route("先加守卫再改", gain=3, confidence=0.85, reversibility=0.95, verified=True, blast=3),
        Route("先观察一轮", gain=1, confidence=0.4, reversibility=1.0, verified=None, blast=0),
    ]


def _cmd_recent(n: int = 10) -> None:
    rows = recent(n)
    if not rows:
        print("🧭  还没有落档的决策（给我一个目标、或用 weigh(...) 后再来看）。")
        return
    print(f"🧭  最近 {len(rows)} 次决策：")
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        goal = str(r.get("goal", ""))[:36]
        cons = (r.get("conservative") or {}).get("stance", "?")
        agg = (r.get("aggressive") or {}).get("stance", "?")
        mark = {VERIFY: "🔴", OBSERVE: "🟡", ACT: "🟢"}
        print(f"  {ts}  {goal}  🛡️{mark.get(cons, '?')} ⚔️{mark.get(agg, '?')}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="policy.py",
        description="🧭 决策策略官：该自改 / 先观察 / 停手求证，并给保守与激进两档建议",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("goal", nargs="*", help="目标描述")
    ap.add_argument("--route", action="append", default=[],
                    help="一条候选路线规格：名字,收益,把握,可逆,验证(y/n/?),影响文件数,要害(y/n)")
    ap.add_argument("--recent", action="store_true", help="回看最近落档的决策后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    goal = " ".join(args.goal)
    if not goal:
        ap.error("请给一个目标描述（或用 --recent 回看历史）")

    routes = [_parse_route(s) for s in args.route] or _demo_routes()
    if not args.route:
        print("（未给 --route，用内置示意路线演示；真用时请用 --route 列出你的选项）\n")
    adv = advise(goal, routes)
    print(adv.render())
    record(adv)


if __name__ == "__main__":
    main()
