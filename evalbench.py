#!/usr/bin/env python3
"""真实任务黄金集 · 质量评测台 📊🎓 —— 证明「我在变强」，而不只是「我没退化」。

为什么要有它：领地里已经有两条「别退步」的防线——perfbase 守住**速度别变慢**、
goldens/regression 守住**行为别变味**。可这两条都只在回答同一个问题：「和过去相比，
我有没有坏掉？」它们的最好结局是**持平**。但这只螃蟹每天自改一个模块，真正想知道的
是另一个更难、也更要紧的问题：**我做真实任务的质量，到底有没有越做越好？**

光看「自检全绿」「提交+1」证明不了变强——那只是没崩。要谈变强，得先有一把**尺**，
而且这把尺得量在**真实任务**上，不是造出来的玩具用例。于是 evalbench 做两件事：

  1. 🎓 **沉淀黄金集**：从情境记忆(memory)里挑出**真实发生过的任务**，bless 成一份
     冻结的、进仓库的黄金集(`state/eval/goldens.json` 之外另存进仓库的 `evalbench_goldens.json`)。
     它是基准锚点——不随心情漂移，换机器也一致(这点和 perfbase 的本机基线相反：
     质量是代码资产，不是机器资产，所以进仓库)。
  2. 📊 **评三个维度的变化**：对每个黄金任务，捞出**当前最近一次**处理它的经历，
     按三把尺打分(各 0~3)，再和**上一次评测**逐维对比，给出「↑变强 / →持平 / ↓退步」：

       · 🔎 **清晰度 (clarity)**：回答有没有结构、是不是该长则长该短则短、有没有混入
                                  失败噪声——读的人能不能一眼看懂「做了什么、结果如何」。
       · 🛠️ **有用性 (usefulness)**：真把事做成了没？结果具体不具体(点到文件/数字/diff)，
                                    还是空泛地「我看了看」。成了且具体才算有用。
       · 🤖 **自主性 (autonomy)**：是自己把活干完了，还是卡住、绕路、反复栽同一个码？
                                  栽跟头、半途而废、「我无法/需要确认」都拉低自主性。

打分有两条路：接了真大脑(OPENCRAB_API_KEY)时用**大脑当评委**按 rubric 逐维评分，
更贴近人的判断；梦境模式下降级为**零依赖启发式代理**(结构/具体度/成败信号)，仍能给出
可复现的相对分。两条路都把每次评测的聚合分追加进 `state/eval/history.jsonl`(被 .gitignore，
本机轨迹)，于是「这周比上周强了多少」有了可查的曲线。

它是观测者：只读记忆派生、把结论摆出来，**不执行任务、不改黄金集**(bless 是显式动作)。
读不到记忆就跳过而非崩。结论永远只是「这把尺现在读数多少、比上次升还是降」，
要不要据此改进、先改哪维，仍由我自己拍板。

零第三方依赖，纯标准库。和 perfbase(快不快) / goldens(变没变味) 三足而立：
那两者守「别退步」，evalbench 答「到底在不在变强」。

用法:
    python evalbench.py                 # 评测当前质量，与上次对比，给三维变化
    python evalbench.py --bless         # 从真实记忆挑任务、(重新)冻结黄金集
    python evalbench.py --bless -n 12   # bless 时挑 12 条(默认 8)
    python evalbench.py --list          # 只列出黄金集里有哪些真实任务
    python evalbench.py --history        # 看历次评测的聚合分轨迹(在不在变强)
    python evalbench.py --json           # 机读：导成 JSON(给 health / 外部消费)
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 黄金集进仓库：质量是代码资产、跨机器一致，故不放被 .gitignore 的 state/ 里。
GOLDENS_PATH = REPO_ROOT / "evalbench_goldens.json"
# 历次评测的聚合分轨迹是本机产物，落在被 .gitignore 的 state/eval/ 里。
EVAL_DIR = REPO_ROOT / "state" / "eval"
HISTORY_PATH = EVAL_DIR / "history.jsonl"

DEFAULT_BLESS_N = 8       # bless 默认从记忆里挑多少条真实任务
MAX_SCORE = 3             # 每个维度满分(0~3)

# 三把尺。键是机读名，值是给人看的(图标, 中文名, 一句话量什么)。
DIMENSIONS = {
    "clarity":    ("🔎", "清晰度", "结构清楚、详略得当、不混失败噪声"),
    "usefulness": ("🛠️", "有用性", "真做成了、结果具体(点到文件/数字/diff)"),
    "autonomy":   ("🤖", "自主性", "自己干完、没卡住/绕路/反复栽同一个码"),
}

# 启发式打分用到的信号词(梦境模式下的代理评委)。
_CONCRETE_RE = re.compile(
    r"`[^`]+`|\b\w+\.py\b|\b\d+\s*(?:行|条|个|次|处|%|ms|KB)|diff|commit|[0-9a-f]{7,}")
_STUCK_RE = re.compile(
    r"无法|放弃|卡住|需要确认|不确定|没法|失败|报错|超时|绕(过|开)|稍后再", re.IGNORECASE)


# ── 一个黄金任务 / 一次评分 ──────────────────────────────────────────
@dataclasses.dataclass
class Golden:
    """黄金集里的一条真实任务：从哪条记忆 bless 来的、任务文本、blessed 时刻。"""
    id: str            # 稳定标识(bless 时按序号生成)
    task: str          # 任务/情境文本(真实发生过，不是造的)
    blessed_at: str    # 冻结进黄金集的时刻
    source_at: str = ""  # 源记忆的时间戳(溯源)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Golden":
        return cls(id=str(d.get("id", "")), task=str(d.get("task", "")),
                   blessed_at=str(d.get("blessed_at", "")),
                   source_at=str(d.get("source_at", "")))


@dataclasses.dataclass
class Score:
    """对某个黄金任务「当前最近一次处理」的三维打分(各 0~MAX_SCORE)。"""
    gid: str
    matched: bool                 # 有没有捞到一条够像的近期经历来评
    clarity: int = 0
    usefulness: int = 0
    autonomy: int = 0
    judge: str = "heuristic"      # 评委来源：heuristic(梦境代理) / brain(真大脑)
    evidence: str = ""            # 一行溯源/依据(给人核对)

    @property
    def total(self) -> int:
        return self.clarity + self.usefulness + self.autonomy

    def dims(self) -> dict[str, int]:
        return {"clarity": self.clarity, "usefulness": self.usefulness,
                "autonomy": self.autonomy}

    def to_dict(self) -> dict:
        return {"gid": self.gid, "matched": self.matched,
                **self.dims(), "judge": self.judge, "evidence": self.evidence}


# ── 黄金集：读 / bless ───────────────────────────────────────────────
def load_goldens() -> list[Golden]:
    """读黄金集；不存在或坏了都退化成空(视作还没 bless 过)。"""
    if not GOLDENS_PATH.exists():
        return []
    try:
        data = json.loads(GOLDENS_PATH.read_text("utf-8"))
        return [Golden.from_dict(d) for d in data.get("goldens", [])]
    except Exception:
        return []


def bless(n: int = DEFAULT_BLESS_N) -> list[Golden]:
    """从真实情境记忆里挑出有代表性的任务，冻结成黄金集并落盘(进仓库)。

    挑选偏好：优先**有具体结果**(动作/结果非空)、且任务文本够长(不是一句口号)的经历;
    成功与失败都要(失败任务正是最该被持续盯着「下次有没有处理得更好」的)。去重相近任务,
    免得黄金集里塞满几乎一样的情境。
    """
    try:
        import memory
        eps = memory.load()
    except Exception:
        eps = []

    # 候选：任务文本够实、动作或结果非空。新近在前(更代表「我现在面对的任务」)。
    cands = [ep for ep in reversed(eps)
             if len(ep.situation.strip()) >= 12 and (ep.action or ep.result)]

    picked: list = []
    for ep in cands:
        if len(picked) >= n:
            break
        # 去重：和已选任务太像就跳过(同一类情境只留一条代表)。
        if any(_similar(ep.situation, p.situation) >= 0.6 for p in picked):
            continue
        picked.append(ep)

    now = datetime.datetime.now().isoformat(timespec="seconds")
    goldens = [Golden(id=f"g{i:02d}", task=ep.situation.strip(),
                      blessed_at=now, source_at=ep.at)
               for i, ep in enumerate(picked, 1)]
    _write_goldens(goldens, now)
    return goldens


def _write_goldens(goldens: list[Golden], blessed_at: str) -> None:
    data = {
        "blessed_at": blessed_at,
        "count": len(goldens),
        "note": "真实任务黄金集——质量评测的基准锚点。由 evalbench.py --bless 冻结。",
        "goldens": [g.to_dict() for g in goldens],
    }
    GOLDENS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _similar(a: str, b: str) -> float:
    """复用 memory 的零依赖中英词袋相似度；memory 缺失则退回粗糙比例。"""
    try:
        import memory
        return memory.similarity(a, b)
    except Exception:
        ta, tb = set(a.lower().split()), set(b.lower().split())
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)


# ── 找「当前最近一次处理」：给每个黄金任务捞最像的近期经历 ───────────────
def _latest_attempt(task: str):
    """从记忆里捞出**最近、且够像**这个黄金任务的一条经历(Episode 或 None)。

    「最近」很关键：黄金集是冻结的旧任务，但我们要评的是**现在**处理同类任务的水平,
    所以在够像(相似度达标)的候选里，取时间最新的那条。
    """
    try:
        import memory
        eps = memory.load()
    except Exception:
        return None
    best = None
    for ep in eps:
        if memory.similarity(task, ep.situation) < memory.MIN_SIMILARITY:
            continue
        if best is None or ep.at > best.at:   # 同样够像，取更近的
            best = ep
    return best


# ── 启发式评委(梦境模式)：零依赖代理打分 ───────────────────────────────
def _heuristic_score(gid: str, ep) -> Score:
    """没接大脑时的代理评委：用结构/具体度/成败信号近似三个维度(各 0~3)。

    这是**相对**尺，不号称等于人的判断；但它可复现、零成本，足以看出趋势。
    """
    text = f"{ep.action}\n{ep.result}".strip()
    low = text.lower()

    # 🔎 清晰度：有换行/分点的结构 +1；长度落在「不过短也不啰嗦」区间 +1；不含失败噪声 +1。
    clarity = 0
    if "\n" in text or "·" in text or "- " in text:
        clarity += 1
    if 30 <= len(text) <= 600:
        clarity += 1
    if ep.ok and not _STUCK_RE.search(low):
        clarity += 1

    # 🛠️ 有用性：成了 +1；结果具体(点到文件/数字/diff/反引号) +1；动作与结果都非空 +1。
    useful = 0
    if ep.ok:
        useful += 1
    if _CONCRETE_RE.search(text):
        useful += 1
    if ep.action.strip() and ep.result.strip():
        useful += 1

    # 🤖 自主性：成了 +1；没有「卡住/绕路/需确认」信号 +1；不带错误码(没栽进已知坑) +1。
    autonomy = 0
    if ep.ok:
        autonomy += 1
    if not _STUCK_RE.search(low):
        autonomy += 1
    if not ep.code:
        autonomy += 1

    mark = "✅" if ep.ok else "❌"
    return Score(gid=gid, matched=True, clarity=clarity, usefulness=useful,
                 autonomy=autonomy, judge="heuristic",
                 evidence=f"{mark} {ep.at[-8:]} {ep.result.strip()[:50] or ep.action.strip()[:50]}")


# ── 大脑评委(接了真大脑时)：按 rubric 逐维评分 ─────────────────────────
_JUDGE_SYSTEM = (
    "你是一个严格的评测员。给定一个真实任务，以及智能体对它的处理记录(动作+结果)，"
    "按三个维度各打 0~3 的整数分：clarity(清晰度：结构清楚、详略得当、不混失败噪声)、"
    "usefulness(有用性：真把事做成了、结果具体可核验)、autonomy(自主性：自己干完、没卡住"
    "或绕路或反复栽)。只输出一行 JSON，形如 "
    '{"clarity":2,"usefulness":3,"autonomy":2}，不要任何多余文字。')


def _brain_score(gid: str, ep) -> Score:
    """接了真大脑时让它当评委按 rubric 评分；任何异常都降级回启发式，绝不反噬。"""
    try:
        import crab
        if not getattr(crab, "API_KEY", None):
            return _heuristic_score(gid, ep)
        prompt = (f"任务：{ep.situation.strip()[:400]}\n\n"
                  f"动作：{ep.action.strip()[:400]}\n\n"
                  f"结果：{ep.result.strip()[:400]}\n\n"
                  f"成功：{'是' if ep.ok else '否'}"
                  + (f"（错误码 {ep.code}）" if ep.code else ""))
        text, _ = crab.brain(_JUDGE_SYSTEM, prompt)
        if crab._brain_failed(text):
            return _heuristic_score(gid, ep)
        m = re.search(r"\{[^{}]*\}", text)
        d = json.loads(m.group(0)) if m else {}
        clip = lambda v: max(0, min(MAX_SCORE, int(v)))
        return Score(gid=gid, matched=True,
                     clarity=clip(d.get("clarity", 0)),
                     usefulness=clip(d.get("usefulness", 0)),
                     autonomy=clip(d.get("autonomy", 0)),
                     judge="brain",
                     evidence=f"大脑评 · {ep.at[-8:]} {ep.result.strip()[:40]}")
    except Exception:
        return _heuristic_score(gid, ep)


# ── 一次完整评测 ─────────────────────────────────────────────────────
@dataclasses.dataclass
class EvalRun:
    """一次评测的结论：每条黄金任务的分、聚合均分、用了哪个评委。"""
    at: str
    judge: str                       # 主用评委(brain / heuristic)
    scores: list[Score]
    matched: int                     # 有近期经历可评的任务数
    total: int                       # 黄金任务总数

    def averages(self) -> dict[str, float]:
        """三维 + 总分的均值(只在「评得上」的任务里算，避免没经历的拉低成 0)。"""
        rated = [s for s in self.scores if s.matched]
        if not rated:
            return {k: 0.0 for k in (*DIMENSIONS, "total")}
        avg = {dim: round(sum(getattr(s, dim) for s in rated) / len(rated), 2)
               for dim in DIMENSIONS}
        avg["total"] = round(sum(s.total for s in rated) / len(rated), 2)
        return avg

    def to_meta(self) -> dict:
        return {"at": self.at, "judge": self.judge, "matched": self.matched,
                "total": self.total, "averages": self.averages(),
                "scores": [s.to_dict() for s in self.scores]}


def evaluate(use_brain: bool = True) -> EvalRun:
    """对黄金集逐条评测：捞当前最近经历 → 三维打分 → 聚合。不改黄金集、不跑任务。"""
    goldens = load_goldens()
    scorer = _brain_score if use_brain else _heuristic_score
    scores: list[Score] = []
    judges: set[str] = set()
    for g in goldens:
        ep = _latest_attempt(g.task)
        if ep is None:
            scores.append(Score(gid=g.id, matched=False,
                                evidence="（黄金集里有此任务，但近期没有够像的经历可评）"))
            continue
        s = scorer(g.id, ep)
        judges.add(s.judge)
        scores.append(s)
    matched = sum(1 for s in scores if s.matched)
    judge = "brain" if "brain" in judges else "heuristic"
    return EvalRun(at=datetime.datetime.now().isoformat(timespec="seconds"),
                   judge=judge, scores=scores, matched=matched,
                   total=len(goldens))


# ── 轨迹：和上次比，到底在不在变强 ────────────────────────────────────
def _read_history() -> list[dict]:
    """读历次评测的聚合分轨迹(时间正序)；坏行/缺失都退化成空。"""
    if not HISTORY_PATH.exists():
        return []
    out = []
    for ln in HISTORY_PATH.read_text("utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _append_history(run: EvalRun) -> None:
    """把本次聚合分追加进本机轨迹；写盘异常都吞掉，评测是观测者不反噬。"""
    try:
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"at": run.at, "judge": run.judge, "matched": run.matched,
               "total": run.total, "averages": run.averages()}
        with HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _audit_run(run: EvalRun) -> None:
    """把本次评测留痕到审计；任何异常都吞掉，绝不让留痕弄死调用方。"""
    try:
        import audit
        avg = run.averages()
        audit.record("evalbench", judge=run.judge, matched=run.matched,
                     total=run.total, **{f"avg_{k}": v for k, v in avg.items()})
    except Exception:
        pass


def _delta_arrow(cur: float, prev: float | None) -> str:
    """和上次比的方向标记：↑变强 / ↓退步 / →持平 / ·首次。"""
    if prev is None:
        return "·"
    d = round(cur - prev, 2)
    if d > 0.0:
        return f"↑+{d}"
    if d < 0.0:
        return f"↓{d}"
    return "→0"


# ── 导出 / 渲染 ──────────────────────────────────────────────────────
def manifest(use_brain: bool = True) -> dict:
    """导出纯数据(给 health / 外部工具消费)：本次评测 + 与上次的逐维 delta。"""
    run = evaluate(use_brain)
    history = _read_history()
    prev = history[-1]["averages"] if history else None
    avg = run.averages()
    deltas = {k: (None if prev is None else round(avg[k] - prev.get(k, 0), 2))
              for k in avg}
    return {
        "goldens": len(load_goldens()),
        "judge": run.judge,
        "matched": run.matched,
        "total": run.total,
        "averages": avg,
        "previous": prev,
        "deltas": deltas,
        "scores": [s.to_dict() for s in run.scores],
    }


def render(use_brain: bool = True) -> tuple[str, EvalRun | None]:
    """评测当前质量并渲染：每维分 + 和上次的升降。返回 (文本, 本次 run 供落盘)。"""
    goldens = load_goldens()
    L = ["📊🎓 opencrab 真实任务质量评测"]
    if not goldens:
        L.append("   （还没 bless 黄金集——先跑 python evalbench.py --bless 从真实记忆挑任务。）")
        return "\n".join(L), None

    run = evaluate(use_brain)
    history = _read_history()
    prev = history[-1]["averages"] if history else None
    avg = run.averages()
    judge_name = "🧠真大脑评委" if run.judge == "brain" else "启发式代理评委(梦境)"

    L.append(f"   黄金任务 {run.total} 条 · 评得上 {run.matched} 条 · {judge_name}")
    if run.matched == 0:
        L.append("   （黄金集里的任务，近期都没有够像的经历可评——先让它多跑几跳积累经历。）")
        return "\n".join(L), run

    L += ["", "  ── 三维均分（满分各 3；箭头=与上次评测比）──"]
    for dim, (icon, name, what) in DIMENSIONS.items():
        cur = avg[dim]
        arrow = _delta_arrow(cur, None if prev is None else prev.get(dim))
        L.append(f"    {icon} {name:<4} {cur:>4}/3  {arrow:<7} — {what}")
    tot_arrow = _delta_arrow(avg["total"], None if prev is None else prev.get("total"))
    L.append(f"    🎯 总分   {avg['total']:>4}/9  {tot_arrow:<7} — 三维之和")

    # 逐条：哪些任务评得上、各几分；没评上的点出来(经历还没攒够)
    L += ["", "  ── 逐条黄金任务 ──"]
    by_id = {g.id: g for g in goldens}
    for s in run.scores:
        g = by_id.get(s.gid)
        head = (g.task.split("\n")[0].strip()[:42] if g else s.gid)
        if not s.matched:
            L.append(f"    ⚪ {s.gid} {head} — {s.evidence}")
        else:
            L.append(f"    · {s.gid} {head}")
            L.append(f"        🔎{s.clarity} 🛠️{s.usefulness} 🤖{s.autonomy} "
                     f"= {s.total}/9 · {s.evidence}")

    # 一句趋势结论
    L += [""]
    if prev is None:
        L.append("  📈 这是首次评测——记下基准。下次再评就能看出在不在变强。")
    else:
        dt = round(avg["total"] - prev.get("total", 0), 2)
        if dt > 0:
            L.append(f"  📈 比上次**变强** +{dt}/9——真实任务上的质量在升，不只是没退化。")
        elif dt < 0:
            L.append(f"  📉 比上次**退步** {dt}/9——别只盯着自检全绿，这里掉了，该正面看为什么。")
        else:
            L.append("  ➖ 与上次**持平**——没退步，但也还没拿出变强的证据。")

    L += ["", "—— 评测只摆出读数与升降；要不要据此改进、先改哪维，仍由我自己拍板。"]
    return "\n".join(L), run


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 真实任务黄金集 · 质量评测台 📊🎓 —— 证明在变强而非只是没退化")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bless", action="store_true",
                   help="从真实记忆挑任务、(重新)冻结黄金集(进仓库)")
    g.add_argument("--list", action="store_true", help="只列出黄金集里有哪些真实任务")
    g.add_argument("--history", action="store_true",
                   help="看历次评测的聚合分轨迹(在不在变强)")
    ap.add_argument("-n", type=int, default=DEFAULT_BLESS_N, metavar="N",
                    help=f"bless 时挑多少条(默认 {DEFAULT_BLESS_N})")
    ap.add_argument("--heuristic", action="store_true",
                    help="强制用启发式代理评委(即便接了大脑)")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    args = ap.parse_args(argv)

    if args.bless:
        goldens = bless(max(1, args.n))
        if not goldens:
            print("📊🎓 没能从记忆里挑到够格的任务——记忆还太少，"
                  "先让它多跑几跳(心跳/演化)积累真实经历，再来 --bless。")
            sys.exit(0)
        print(f"📊🎓 已冻结 {len(goldens)} 条真实任务为黄金集 → "
              f"{GOLDENS_PATH.relative_to(REPO_ROOT)}")
        for g_ in goldens:
            print(f"     {g_.id} {g_.task.splitlines()[0].strip()[:56]}")
        print("   黄金集进仓库(质量是代码资产)；接着 python evalbench.py 就能评。")
        sys.exit(0)

    if args.list:
        goldens = load_goldens()
        if not goldens:
            print("📊🎓 黄金集还是空的——先 python evalbench.py --bless。")
            sys.exit(0)
        print(f"📊🎓 黄金集 · {len(goldens)} 条真实任务：")
        for g_ in goldens:
            print(f"  {g_.id} （源 {g_.source_at[:10]}）"
                  f"{g_.task.splitlines()[0].strip()[:56]}")
        sys.exit(0)

    if args.history:
        hist = _read_history()
        if not hist:
            print("📊🎓 还没有评测轨迹——先 python evalbench.py 跑一次。")
            sys.exit(0)
        print("📊🎓 历次评测聚合分轨迹（看总分在不在往上走）：")
        prev = None
        for rec in hist:
            avg = rec.get("averages", {})
            tot = avg.get("total", 0)
            arrow = _delta_arrow(tot, prev)
            print(f"  {rec.get('at', '')[:16]} 总分 {tot}/9 {arrow:<7} "
                  f"(🔎{avg.get('clarity',0)} 🛠️{avg.get('usefulness',0)} "
                  f"🤖{avg.get('autonomy',0)}) · {rec.get('judge','')}")
            prev = tot
        sys.exit(0)

    use_brain = not args.heuristic
    if args.json:
        print(json.dumps(manifest(use_brain), ensure_ascii=False, indent=2))
        # JSON 路径也落一次轨迹，保持「每评必留痕」一致
        run = evaluate(use_brain)
        _append_history(run)
        _audit_run(run)
        sys.exit(0)

    text, run = render(use_brain)
    print(text)
    if run is not None and run.matched > 0:
        _append_history(run)   # 评得上才记轨迹，免得 0 分拉脏曲线
        _audit_run(run)
    sys.exit(0)   # 只读派生，永远正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
