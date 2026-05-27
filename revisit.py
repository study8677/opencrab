#!/usr/bin/env python3
"""高分进化反作弊回访 🫧🌳 —— 翻出近 N 次「自称进化了」的自改，挨个问：这分是真挣的，还是吹的？

为什么要有它：领地里查 Goodhart 的器官已经有两个，但它们各盯一处——`metricguard`
盯**单个指标**的分/用两条时间序列，`usageheat` 盯**单个器官**此刻的冷热体温。可它们
都答不上另一问：**回头看，我最近这十次「合并即宣布进化了」的自改，到底有几次是真挣
的？** 每次自改在合并那一刻都默认拿了满分（自测过 → push → 「我今天又进化了」🌊），
这个满分谁来回访复核？没人回访，古德哈特就从这条缝里钻进来：分（合并数、绿灯数）一路
涨，真实世界里却没人多用它一次。

本层是**朝后看的回访员**：从 git 里捞出近 N 次真合并进主干的进化（带 `evolve:` 签名、
且确实改过顶层 `*.py`），给每一次的「我进化了」这句满分主张，叫来三个**互相独立、谁
也刷不动谁**的证人对质：

  · 💎 **价值卡**（value）—— 这次改的模块，当初有没有人逼它答清「对谁、在哪、真有用」？
    绑过受益者 = 改之前就朝外看过；没卡 = 多半只优化了内部流程（最弱的一票，因为按设计
    只有少数卡）。--deep 时还实跑它的反指标，红了 = 局部好看、别处被拖垮。
  · 🌱 **真实使用痕迹**（usageheat）—— 这模块在最近的心跳审计里，**出生之后**还有没有
    再被点名用过？只在出生那天被提一句、之后无人问津 = 写完即遗忘的壳。这票最重——
    「真有人在用」是唯一刷不出来的信号。
  · 🧾 **证据新鲜度**（evidence）—— 这能力上次被复验是多久以前、当时绿没绿？账本发凉
    或 🔴失守，都是「分还挂着、地气早断了」。

把三票按权重（使用 0.5 · 证据 0.3 · 价值 0.2）折成一个 0~1 的**实质分**——这就是给当初
那句满分主张做的「降权」：读不到的证人**直接弃权、权重重新归一**，绝不拿臆测补票。据
实质分给每次进化盖章：

  · 🌳 扎实   —— 实质分高。有人真在用、证据还新鲜，这分是挣的。
  · 🌫️ 存疑   —— 半挣半吹。某一两个证人没到场或投了弱票，盯着别让它凉成泡沫。
  · 🫧 泡沫   —— 实质分低。三个证人集体摇头：没人用、没证据、没受益者，唯独「合并了」这
                 一个内部数字漂亮。这种「进化」比没做更危险——它伪装成进步，骗的是未来的我。

判准（和领地里其它观测者同一种洁癖）：回访员**只读** git log / 审计 / evidence·value 的
manifest，绝不写 journal / state、不改任何文件、起不来只当「这次没回访成」、绝不反噬生命。
任一证人读不到，那一票记「未知」并弃权（权重归一），绝不臆测。发现任意 🫧泡沫 即让退出
码非零（可挂进钩子 / CI 当门禁）；存疑只是提醒，不致退出非零。

用法：
    python revisit.py                # 回访近 10 次进化：每次的三证人 + 实质分 + 盖章
    python revisit.py --n 20         # 回访窗口（默认近 10 次真合并的进化）
    python revisit.py --days 14      # 「真实使用痕迹」回溯审计的天数窗口（默认 7 天）
    python revisit.py --deep         # 实跑命中价值卡的反指标，把变红的算进降权
    python revisit.py --bubbles      # 只列被判 🫧泡沫 的进化（该降权的名单）
    python revisit.py --quiet        # 只在查出泡沫时说话（适合钩子 / CI）
    python revisit.py --json         # 机读：导出每次进化的三证人原始信号、实质分与盖章

退出码：0 = 没有泡沫进化；1 = 至少一次「高分进化」被三证人判为泡沫。零第三方依赖，纯标准库。
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

GIT_TIMEOUT = 20            # git 读命令墙钟上限(秒)：回访是观测者，不该把生命拖死
DEFAULT_N = 10              # 回访窗口：默认翻最近 10 次真合并进主干的进化
DEFAULT_DAYS = 7            # 「真实使用痕迹」回溯审计的天数窗口

# 顶层进化产物之外的路径：journal/docs/state/skills/… 改了它们不算「动了一项能力」。
_TOPLEVEL_PY = re.compile(r"^([a-z_][a-z0-9_]*)\.py$")

# 三证人在实质分里的权重——「真有人在用」刷不出来，给它最重的一票。
W_USAGE, W_EVIDENCE, W_VALUE = 0.5, 0.3, 0.2

# 盖章阈值（实质分 0~1）：高于扎实线=真挣的；低于泡沫线=三证人集体摇头的伪进步。
SOLID_AT = 0.66
BUBBLE_AT = 0.40

VERDICT_SOLID, VERDICT_SUSPECT, VERDICT_BUBBLE = "solid", "suspect", "bubble"
_MARKS = {VERDICT_SOLID: "🌳", VERDICT_SUSPECT: "🌫️", VERDICT_BUBBLE: "🫧"}
_WORDS = {VERDICT_SOLID: "扎实", VERDICT_SUSPECT: "存疑", VERDICT_BUBBLE: "泡沫"}


# ── git：捞出近 N 次真合并进主干的进化 ─────────────────────────────────────
def _git(args: list[str]) -> str:
    """跑一条 git 读命令，返回 stdout；起不来 / 非零 / 超时都回空串，绝不抛错。"""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=GIT_TIMEOUT,
        )
        return proc.stdout if proc.returncode == 0 else ""
    except Exception:  # noqa: BLE001 —— 回访是观测者，git 起不来只是「这次没回访成」
        return ""


@dataclasses.dataclass(frozen=True)
class Evolution:
    """一次「自称进化了」的自改：合并那一刻它默认拿了满分，等着被回访复核。"""
    sha: str                # 短哈希
    date: str               # 提交日(ISO，YYYY-MM-DD)：用来判「使用痕迹是不是出生之后才有的」
    subject: str            # 提交标题(那句「今天推进…」)
    modules: list[str]      # 这次真改过的顶层 .py 模块名(去掉 journal/docs/state 等)


def _touched_modules(sha: str) -> list[str]:
    """这次提交改过的顶层 .py 模块名(只认 `foo.py`，不含子目录里的)。"""
    out = _git(["show", "--name-only", "--format=", sha])
    mods: list[str] = []
    for line in out.splitlines():
        m = _TOPLEVEL_PY.match(line.strip())
        if m and m.group(1) not in mods:
            mods.append(m.group(1))
    return mods


def recent_evolutions(n: int = DEFAULT_N) -> list[Evolution]:
    """近 n 次「带 evolve: 签名、且确实改过顶层 .py」的真合并进化，最新在前。

    git 读不到则回空——没有进化流水就没什么可回访，绝不臆造历史。
    """
    # 多捞一些候选(有些 evolve: 提交只动了 journal，不算动了能力)，再筛够 n 个。
    raw = _git(["log", "--grep=evolve:", "--format=%h%x09%cI%x09%s", "-n", str(max(n * 4, 40))])
    out: list[Evolution] = []
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, cdate, subject = parts
        mods = _touched_modules(sha)
        if not mods:                       # 只动了 journal/docs 的，不是「动了一项能力」
            continue
        out.append(Evolution(sha=sha, date=cdate[:10], subject=subject.strip(), modules=mods))
        if len(out) >= n:
            break
    return out


# ── 三证人：互相独立、谁也刷不动谁 ─────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Witness:
    """一个证人对某次进化投的票：分(0~1) + 一句人话；known=False 表示读不到、本票弃权。"""
    score: float
    note: str
    known: bool = True

    @staticmethod
    def unknown(note: str) -> "Witness":
        return Witness(score=0.0, note=note, known=False)


def _date_after(later: str, earlier: str) -> bool:
    """later 这个 ISO 日是否严格晚于 earlier；任一个不是合法 ISO 日就保守判 False(不臆测)。"""
    try:
        return datetime.date.fromisoformat(later) > datetime.date.fromisoformat(earlier)
    except ValueError:
        return False


def _usage_witness(ev: Evolution, mentions: dict[str, tuple[int, str]]) -> Witness:
    """🌱 真实使用痕迹：这模块出生之后还有没有再被点名用过？这票最重、最刷不动。

    mentions 为 {模块: (近窗内被点名次数, 最近一次时间ts)}；审计读不到则本票弃权。
    """
    if not mentions:
        return Witness.unknown("审计读不到，使用痕迹未知")
    # 一次进化可能动了好几个模块——取其中「最活」的那个代表它(任一模块还在用就算有地气)。
    best = 0.0
    detail = "出生后再没被点名用过"
    for mod in ev.modules:
        n, last = mentions.get(mod, (0, ""))
        if n <= 0:
            continue
        used_after_birth = _date_after(last[:10], ev.date)   # 最近一次点名晚于出生日 = 出生后还在用
        s = 1.0 if used_after_birth else 0.45       # 只在出生那天被提一句 = 多半写完即遗忘
        if s > best:
            best = s
            detail = (f"`{mod}` 近窗被点名 {n} 次，出生后仍在用"
                      if used_after_birth else
                      f"`{mod}` 近窗被点名 {n} 次，但都在出生当天/之前——之后无人问津")
    return Witness(score=best, note=detail)


def _evidence_witness(ev: Evolution, fresh: dict[str, tuple[str, float | None]]) -> Witness:
    """🧾 证据新鲜度：这能力上次被复验多久了、当时绿没绿？读不到 evidence 则本票弃权。"""
    if not fresh:
        return Witness.unknown("evidence 读不到，证据新鲜度未知")
    covered = [(mod, fresh[mod]) for mod in ev.modules if mod in fresh]
    if not covered:
        return Witness(score=0.30, note="改过的模块都没有 evidence 声明——没人替这次进化兜过底")
    # 取覆盖到的模块里最新鲜/最绿的一条代表它。evidence 的 state 按设计只有这四种；
    # 真冒出没见过的 state，那一条跳过(不臆测打分)，全跳过 = 这票弃权。
    best: float | None = None
    detail = ""
    for mod, (state, age) in covered:
        if state == "fresh":            # 🟢 最近复验过、还在 TTL 内
            s, why = 1.0, f"`{mod}` 证据新鲜且绿"
        elif state == "stale":          # 🟡 验过但已过期(发凉)
            s, why = 0.5, f"`{mod}` 证据发凉（久未复验）"
        elif state == "broken":         # 🔴 最近一次复验失守
            s, why = 0.0, f"`{mod}` 证据 🔴失守"
        elif state == "unproven":       # ⚪ 声明在、却从没真验过一次
            s, why = 0.4, f"`{mod}` 证据未证"
        else:                           # 没见过的 state：不臆测，跳过这一条
            continue
        if age is not None and age > 14 and s > 0.5:   # 再绿，凉过两周也该打个折
            s, why = min(s, 0.6), why + f"（已 {age:.0f} 天没复验）"
        if best is None or s > best:
            best, detail = s, why
    if best is None:                    # 覆盖到的模块 state 全不认识 → 本票弃权
        return Witness.unknown("证据状态读不出可比口径，本票弃权")
    return Witness(score=best, note=detail)


def _value_witness(ev: Evolution, carded: set[str],
                   counter_red: dict[str, bool]) -> Witness:
    """💎 价值卡：改的模块当初有没有绑过受益者？--deep 时还把反指标变红算进来。

    价值卡是静态声明、永远「已知」(不会弃权)；按设计只有少数模块有卡，故这是最弱的一票。
    """
    hit = [m for m in ev.modules if m in carded]
    if not hit:
        return Witness(score=0.20, note="改的模块都没有价值卡——没人逼它答清「对谁、在哪、真有用」")
    # counter_red 只在 --deep 时有值；没测到 / 测时起不来都按「没红」算(乐观默认，不冤判)。
    red = [m for m in hit if counter_red.get(m)]
    if red:
        return Witness(score=0.0, note=f"价值卡反指标变红：{ '、'.join(red) }——局部好看、别处被拖垮")
    return Witness(score=0.9, note=f"绑过价值卡：{ '、'.join(hit) }")


# ── 把三票折成实质分 = 给「我进化了」这句满分主张做的降权 ──────────────────────
@dataclasses.dataclass(frozen=True)
class Revisit:
    """一次进化的回访结果：三证人 + 实质分(降权后的真分) + 盖章。"""
    ev: Evolution
    usage: Witness
    evidence: Witness
    value: Witness
    score: float            # 0~1：满分主张(1.0)被三证人降权后的实质分

    @property
    def verdict(self) -> str:
        if self.score >= SOLID_AT:
            return VERDICT_SOLID
        # 泡沫的指控全靠「真实使用」这根主柱——它弃权(审计读不到)时，剩下的弱票不配
        # 下「泡沫」这种重判，最多记存疑：没有使用信号就不臆测谁是泡沫，和领地同一种洁癖。
        if self.score < BUBBLE_AT and self.usage.known:
            return VERDICT_BUBBLE
        return VERDICT_SUSPECT

    @property
    def mark(self) -> str:
        return _MARKS[self.verdict]

    @property
    def word(self) -> str:
        return _WORDS[self.verdict]

    @property
    def is_bubble(self) -> bool:
        return self.verdict == VERDICT_BUBBLE

    def to_meta(self) -> dict:
        return {
            "sha": self.ev.sha, "date": self.ev.date, "subject": self.ev.subject,
            "modules": self.ev.modules, "score": round(self.score, 3),
            "verdict": self.verdict,
            "witnesses": {
                "usage": {"score": round(self.usage.score, 3), "known": self.usage.known, "note": self.usage.note},
                "evidence": {"score": round(self.evidence.score, 3), "known": self.evidence.known, "note": self.evidence.note},
                "value": {"score": round(self.value.score, 3), "known": self.value.known, "note": self.value.note},
            },
        }


def _deflate(usage: Witness, evidence: Witness, value: Witness) -> float:
    """三票按权重折成实质分；弃权(未知)的票剔出去、权重在到场者间重新归一——绝不臆测补票。

    全员弃权(罕见：审计 + evidence + 价值卡都读不到)时回 1.0：没有任何反对证据，
    回访员不替历史定罪，只是「这次没回访成」。
    """
    votes = [(usage, W_USAGE), (evidence, W_EVIDENCE), (value, W_VALUE)]
    present = [(w, wt) for (w, wt) in votes if w.known]
    total_wt = sum(wt for _, wt in present)
    if total_wt <= 0:
        return 1.0
    return sum(w.score * wt for w, wt in present) / total_wt


def _counter_red(carded_hit: set[str]) -> dict[str, bool]:
    """--deep：实跑命中价值卡的反指标，返回 {模块: 反指标是否变红}。不 deep 则回空。"""
    out: dict[str, bool] = {}
    try:
        import value as value_mod
    except Exception:
        return out
    cards = {c.name: c for c in value_mod.CARDS}
    for name in carded_hit:
        card = cards.get(name)
        if card is None:
            continue
        try:
            res = value_mod.check(card)
            out[name] = (not res.counter_ok)
        except Exception:  # noqa: BLE001 —— 跑不动只当「这条没测成」，不算变红
            continue
    return out


def revisit(n: int = DEFAULT_N, days: int = DEFAULT_DAYS, deep: bool = False) -> list[Revisit]:
    """回访近 n 次进化：给每次的满分主张叫来三证人对质，折成降权后的实质分。"""
    evolutions = recent_evolutions(n)
    if not evolutions:
        return []

    # 三证人的信号源各取一次，全程只读、各自读不到就让对应票弃权(绝不臆测)。
    mentions = _usage_mentions(days)
    fresh = _evidence_freshness()
    carded = _value_carded()

    counter_red: dict[str, bool] = {}
    if deep and carded:
        hit = {m for ev in evolutions for m in ev.modules if m in carded}
        counter_red = _counter_red(hit)

    out: list[Revisit] = []
    for ev in evolutions:
        u = _usage_witness(ev, mentions)
        e = _evidence_witness(ev, fresh)
        v = _value_witness(ev, carded, counter_red)
        out.append(Revisit(ev=ev, usage=u, evidence=e, value=v, score=_deflate(u, e, v)))
    return out


# ── 信号源：复用领地里既有的单一真相源，读不到就回空(对应票自行弃权) ────────────
def _usage_mentions(days: int) -> dict[str, tuple[int, str]]:
    """复用 usageheat 的审计点名统计：{模块: (次数, 最近ts)}；读不到则回空。"""
    try:
        import usageheat
        return usageheat._audit_mentions(days)   # 同一份审计真相源，不另起炉灶
    except Exception:
        return {}


def _evidence_freshness() -> dict[str, tuple[str, float | None]]:
    """复用 usageheat 对齐好的 evidence 新鲜度：{模块: (state, age_days)}；读不到则回空。"""
    try:
        import usageheat
        return usageheat._evidence_freshness()
    except Exception:
        return {}


def _value_carded() -> set[str]:
    """领地里绑过价值卡的模块名集合；读不到则回空集(价值票一律记「没卡」)。"""
    try:
        import value
        return {c.name for c in value.CARDS}
    except Exception:
        return set()


# ── 折叠 & 渲染 ───────────────────────────────────────────────────────────
def summarize(rows: list[Revisit]) -> dict[str, int]:
    counts = {VERDICT_SOLID: 0, VERDICT_SUSPECT: 0, VERDICT_BUBBLE: 0}
    for r in rows:
        counts[r.verdict] += 1
    return counts


def manifest(n: int = DEFAULT_N, days: int = DEFAULT_DAYS, deep: bool = False,
             rows: list[Revisit] | None = None) -> dict:
    """机读：每次进化的三证人原始信号、实质分与盖章 + 各档计数 + 泡沫名单。

    传入 rows 可复用已算好的回访结果，免得为 --json 又把 git / 审计全跑一遍。
    """
    if rows is None:
        rows = revisit(n=n, days=days, deep=deep)
    counts = summarize(rows)
    return {
        "n": n, "days": days, "deep": deep, "total": len(rows),
        "counts": counts,
        "bubbles": [r.ev.sha for r in rows if r.is_bubble],
        "revisits": [r.to_meta() for r in rows],
    }


def _render(rows: list[Revisit], days: int, bubbles_only: bool, want_n: int) -> str:
    counts = summarize(rows)
    short = f"（git 里只翻得出 {len(rows)} 次，不足 {want_n}）" if len(rows) < want_n else ""
    L = [f"🫧🌳 opencrab 高分进化反作弊回访 —— 近 {len(rows)} 次真合并的进化{short} "
         f"⨉ 使用痕迹(近 {days} 天)·证据·价值卡",
         f"   🌳 扎实 {counts[VERDICT_SOLID]} · 🌫️ 存疑 {counts[VERDICT_SUSPECT]} · "
         f"🫧 泡沫 {counts[VERDICT_BUBBLE]}", ""]
    shown = [r for r in rows if r.is_bubble] if bubbles_only else rows
    if bubbles_only and not shown:
        L.append("🌳 近窗没有被判泡沫的进化——这些满分主张暂时都还兜得住。")
        return "\n".join(L)
    for r in shown:
        L.append(f"{r.mark} {r.word}（实质分 {r.score:.2f}）· {r.ev.sha} {r.ev.date}")
        L.append(f"    意图：{r.ev.subject[:62]}")
        L.append(f"    动了：{ '、'.join(r.ev.modules) }")
        L.append(f"    🌱 使用：{r.usage.note}" + ("" if r.usage.known else "（弃权）"))
        L.append(f"    🧾 证据：{r.evidence.note}" + ("" if r.evidence.known else "（弃权）"))
        L.append(f"    💎 价值：{r.value.note}" + ("" if r.value.known else "（弃权）"))
        L.append("")
    if counts[VERDICT_BUBBLE]:
        L.append(f"⚠️  {counts[VERDICT_BUBBLE]} 次「进化」被三证人判为泡沫：合并数涨了，地气没跟上。"
                 "该给这份收益降权，别拿它当真进步的证据。")
    else:
        L.append("🌳 近窗每次进化的满分主张，都至少有一个证人替它兜得住——没有纯泡沫。")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="高分进化反作弊回访：翻近 N 次自改，给吹出来的分降权",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--n", type=int, default=DEFAULT_N, help=f"回访窗口(默认近 {DEFAULT_N} 次真合并进化)")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"使用痕迹回溯审计天数(默认 {DEFAULT_DAYS})")
    ap.add_argument("--deep", action="store_true", help="实跑命中价值卡的反指标，把变红的算进降权")
    ap.add_argument("--bubbles", action="store_true", help="只列被判泡沫的进化(该降权的名单)")
    ap.add_argument("--quiet", action="store_true", help="只在查出泡沫时说话(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="机读：导出全部回访结果")
    args = ap.parse_args(argv)

    rows = revisit(n=max(1, args.n), days=max(1, args.days), deep=args.deep)

    if args.json:
        print(json.dumps(manifest(n=max(1, args.n), days=max(1, args.days), deep=args.deep, rows=rows),
                         ensure_ascii=False, indent=2))
    elif not rows:
        if not args.quiet:
            print("🫧🌳 git 里捞不到可回访的进化(没有改过顶层 .py 的 evolve: 提交)——这次没回访成。")
    else:
        has_bubble = any(r.is_bubble for r in rows)
        if not (args.quiet and not has_bubble):
            print(_render(rows, days=max(1, args.days), bubbles_only=args.bubbles, want_n=max(1, args.n)))

    sys.exit(1 if any(r.is_bubble for r in rows) else 0)


if __name__ == "__main__":
    main()
