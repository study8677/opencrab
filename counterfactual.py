#!/usr/bin/env python3
"""反事实账本 🔀 —— 把每个岔路口「选了什么、放弃了什么、为什么放弃」记下来，到点回头
对照一次，沉淀「若重来」的取舍教训。逼自己从「更会预估」进化到「更会取舍」。

为什么要有它：领地里已经有一排账本在校准我的**预估**——价值(value)问「这对谁有用」、
摩擦(friction)问「哪里最磨人」、证据(evidence)问「这话还跑得通吗」。它们都盯着我
**做了**的那条路，跑得好不好。可一个决定真正的代价，往往藏在我**没选**的那几条路里：
当时为什么把 B 和 C 划掉？那个理由，事后看站得住脚吗？没人记下被放弃的方案，我就只能
反复在同一种岔路上、用同一种似是而非的理由、栽同一种跟头——因为被否掉的选项连同它的
否决理由，一拍板就蒸发了，根本没机会被验证对错。

本层把每个岔路口钉成一条**反事实记录**，逼自己当场答清三件事：

  · 选了什么(chosen) —— 这次实际走的那条路。
  · 放弃了什么(rejected) —— 当场被划掉的那几个方案，**每个都要附一句放弃理由**。
                      说不出备选、或备选没有理由，多半说明这根本没经过取舍。
  · 几时回头看(revisit) —— 一个未来的日子。到那天，这条路的结果该露面了，该回来对照。

到点之后用 `revisit` 给这条记录一个**事后裁决**：

  · ✅ held(当初选对了)   —— 复盘无悔，被放弃的方案确实更差。
  · 🔁 regret(该选别的)   —— 事后看，当初划掉的某个方案其实更好；附一句「若重来」的教训。
  · ➖ moot(无所谓了)     —— 后来情况变了 / 这选择根本不重要，对错已不可比。

攒够裁决，账本就能算出我的**取舍命中率**(held ÷ 真正可对错的裁决)——这是「我有多会取
舍」最诚实的一面镜子；并把所有 regret 的「若重来」教训汇成一页，让同一种误判别再来第二次。

另有一问朝向**欠的债**：哪些决定**早该回头对照、却一直没裁决**(--due)？那些就是我嘴上
说要复盘、身体却假装岔路口从没存在过的地方——不裁决，就永远学不到那一课。

用法:
    python counterfactual.py decide --topic "存储选型" --chose "用 JSONL" \\
        --reject "上 SQLite=怕引依赖" --reject "纯内存=重启即丢" --revisit 14
                                       # 记一个岔路口(其余子命令都只读，不落盘)
    python counterfactual.py revisit ab12cd --verdict regret \\
        --lesson "当时高估了依赖成本，SQLite 其实零配置"
                                       # 给一条记录补一个事后裁决
    python counterfactual.py           # 决定清单 + 每条的放弃方案与裁决
    python counterfactual.py --due     # 只列「早该回头、却还没裁决」的决定(欠的债)
    python counterfactual.py --lessons # 汇总所有 regret 的「若重来」教训
    python counterfactual.py --score   # 取舍命中率：我到底有多会取舍
    python counterfactual.py --quiet   # 只在「有决定该回头对照了」时说话(钩子 / CI)
    python counterfactual.py --json    # 机读：导出全部决定 + 裁决 + 命中率

零第三方依赖，纯标准库。账本是观测者：写盘失败被吞、读不到就当空，绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import append_jsonl, read_jsonl  # noqa: E402  —— 复用领地统一的 JSONL 存取

LOG_PATH = REPO_ROOT / "state" / "counterfactual.jsonl"

# 三种事后裁决，每种配一个图标与一句「它意味着什么」。
# 只有 held / regret 进命中率分母——moot 是「对错已不可比」，算进去只会污染那面镜子。
VERDICTS: dict[str, str] = {
    "held": "选对了",
    "regret": "该选别的",
    "moot": "无所谓了",
}
_VERDICT_ICON = {"held": "✅", "regret": "🔁", "moot": "➖"}


def _now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _short_id(topic: str, ts: str) -> str:
    """由 主题+时刻 派生一个稳定的 6 位短 id——便于 revisit 时回指这条决定。"""
    return hashlib.sha1(f"{topic}|{ts}".encode("utf-8")).hexdigest()[:6]


# ── 数据模型 ──────────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Option:
    """一个被放弃的备选方案：是什么、当初为什么划掉它。"""
    what: str        # 这个备选方案是什么
    why: str         # 当场放弃它的理由(事后要拿这句来对质)

    def to_meta(self) -> dict:
        return {"what": self.what, "why": self.why}


@dataclasses.dataclass(frozen=True)
class Verdict:
    """一条事后裁决：当初这步选对了吗，以及「若重来」的教训。"""
    verdict: str     # VERDICTS 之一
    lesson: str      # 一句「若重来」的教训(regret 时最该写)
    ts: str          # 裁决时刻

    def to_meta(self) -> dict:
        return {"verdict": self.verdict, "lesson": self.lesson, "ts": self.ts}


@dataclasses.dataclass(frozen=True)
class Decision:
    """一个岔路口：选了什么、放弃了什么(各附理由)、几时回头看、事后裁决如何。"""
    id: str
    topic: str               # 这个决定是关于什么的
    chosen: str              # 实际走的那条路
    rejected: list[Option]   # 被划掉的备选(每个都带放弃理由)
    revisit_on: str          # 该回头对照的日期(YYYY-MM-DD)；空=没定
    ts: str                  # 拍板时刻
    verdict: Verdict | None  # 事后裁决；None=还没回头看

    @property
    def decided(self) -> bool:
        """是否已经下过裁决。"""
        return self.verdict is not None

    def is_due(self, today: datetime.date) -> bool:
        """到点该回头、却还没裁决——这就是欠着的一课。"""
        if self.decided or not self.revisit_on:
            return False
        try:
            due = datetime.date.fromisoformat(self.revisit_on)
        except ValueError:
            return False
        return due <= today

    def to_meta(self) -> dict:
        return {
            "id": self.id, "topic": self.topic, "chosen": self.chosen,
            "rejected": [o.to_meta() for o in self.rejected],
            "revisit_on": self.revisit_on, "ts": self.ts,
            "verdict": self.verdict.to_meta() if self.verdict else None,
        }


# ── 存取：决定与裁决都各写一行 JSONL，读时按 id 合并 ──────────────────────
def _parse_options(raw: object) -> list[Option]:
    out: list[Option] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                what = str(item.get("what", "")).strip()
                if what:
                    out.append(Option(what=what, why=str(item.get("why", "")).strip()))
    return out


def load() -> list[Decision]:
    """读出全部决定(拍板时间正序)，并把后续 revisit 行合并到对应决定上。

    文件缺失/坏行都安全跳过；裁决行若指向不存在的 id，直接忽略(宁可丢一条裁决，
    也不凭空造一个决定)。同一 id 多条裁决取最后一条——复盘可以改主意。
    """
    decisions: dict[str, Decision] = {}
    verdicts: dict[str, Verdict] = {}
    order: list[str] = []
    for rec in read_jsonl(LOG_PATH):
        kind = rec.get("kind")
        if kind == "decision":
            did = str(rec.get("id", "")).strip()
            topic = str(rec.get("topic", "")).strip()
            if not did or not topic:
                continue
            decisions[did] = Decision(
                id=did, topic=topic,
                chosen=str(rec.get("chosen", "")).strip(),
                rejected=_parse_options(rec.get("rejected")),
                revisit_on=str(rec.get("revisit_on", "")).strip(),
                ts=str(rec.get("ts", "")), verdict=None,
            )
            if did not in order:
                order.append(did)
        elif kind == "verdict":
            did = str(rec.get("id", "")).strip()
            v = rec.get("verdict")
            if did and v in VERDICTS:
                verdicts[did] = Verdict(verdict=v,
                                        lesson=str(rec.get("lesson", "")).strip(),
                                        ts=str(rec.get("ts", "")))
    out = []
    for did in order:
        d = decisions[did]
        v = verdicts.get(did)
        out.append(dataclasses.replace(d, verdict=v) if v else d)
    return out


def _parse_revisit_on(revisit_in: int | str | None) -> str:
    """把 --revisit 入参规整成 YYYY-MM-DD：整数=N 天后，日期串=原样，None/空=不定。"""
    if revisit_in is None or revisit_in == "":
        return ""
    if isinstance(revisit_in, int):
        return (_now().date() + datetime.timedelta(days=revisit_in)).isoformat()
    s = str(revisit_in).strip()
    try:  # 纯数字串也当作「N 天后」
        return (_now().date() + datetime.timedelta(days=int(s))).isoformat()
    except ValueError:
        pass
    datetime.date.fromisoformat(s)  # 校验格式，非法直接抛给调用方
    return s


def record_decision(topic: str, chosen: str, rejected: list[Option],
                    revisit_in: int | str | None) -> tuple[str, bool]:
    """记一个岔路口；返回 (短id, 是否落盘成功)。写盘失败被吞，绝不反噬生命。"""
    topic = topic.strip()
    if not topic:
        raise ValueError("决定得有个主题(--topic)，不然事后回看认不出它是哪个岔路口。")
    if not chosen.strip():
        raise ValueError("得说清实际选了什么(--chose)。")
    if not rejected:
        raise ValueError("至少要记下一个被放弃的方案(--reject)——没有备选，就谈不上取舍。")
    ts = _now_iso()
    did = _short_id(topic, ts)
    rec = {
        "kind": "decision", "id": did, "topic": topic, "chosen": chosen.strip(),
        "rejected": [o.to_meta() for o in rejected],
        "revisit_on": _parse_revisit_on(revisit_in), "ts": ts,
    }
    return did, append_jsonl(LOG_PATH, rec)


def record_verdict(did: str, verdict: str, lesson: str) -> bool:
    """给一条决定补一个事后裁决。verdict 非法直接拒绝；写盘失败被吞。"""
    if verdict not in VERDICTS:
        raise ValueError(f"裁决须是 {'/'.join(VERDICTS)} 之一，收到 {verdict!r}")
    lesson = lesson.strip()
    if verdict == "regret" and not lesson:
        raise ValueError("regret 必须附一句「若重来」的教训(--lesson)——否则这一课白栽了。")
    rec = {"kind": "verdict", "id": did.strip(), "verdict": verdict,
           "lesson": lesson, "ts": _now_iso()}
    return append_jsonl(LOG_PATH, rec)


# ── 取舍命中率：我到底有多会取舍 ──────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Score:
    """取舍命中率：在所有「可对错」的裁决里，当初选对的占多少。"""
    held: int
    regret: int
    moot: int
    pending: int     # 还没裁决的决定数

    @property
    def judged(self) -> int:
        """进命中率分母的裁决数(moot 不算——对错已不可比)。"""
        return self.held + self.regret

    @property
    def hit_rate(self) -> float | None:
        """命中率 = held ÷ judged；还没有可对错的裁决时为 None。"""
        return self.held / self.judged if self.judged else None

    def to_meta(self) -> dict:
        return {"held": self.held, "regret": self.regret, "moot": self.moot,
                "pending": self.pending, "judged": self.judged,
                "hit_rate": round(self.hit_rate, 3) if self.hit_rate is not None else None}


def score(decisions: list[Decision]) -> Score:
    counts = {"held": 0, "regret": 0, "moot": 0}
    pending = 0
    for d in decisions:
        if d.verdict is None:
            pending += 1
        else:
            counts[d.verdict.verdict] += 1
    return Score(held=counts["held"], regret=counts["regret"],
                 moot=counts["moot"], pending=pending)


def due(decisions: list[Decision], today: datetime.date | None = None) -> list[Decision]:
    """早该回头对照、却还没裁决的决定——欠着的那几课。"""
    today = today or _now().date()
    return [d for d in decisions if d.is_due(today)]


def lessons(decisions: list[Decision]) -> list[tuple[Decision, str]]:
    """所有 regret 的「若重来」教训(决定, 教训)，按裁决时间倒序——新近的栽得最痛。"""
    out = [(d, d.verdict.lesson) for d in decisions
           if d.verdict and d.verdict.verdict == "regret" and d.verdict.lesson]
    out.sort(key=lambda t: t[0].verdict.ts, reverse=True)
    return out


# ── 展示 ──────────────────────────────────────────────────────────────
def _fmt_verdict(d: Decision) -> str:
    if not d.verdict:
        tail = f"（{d.revisit_on} 回头看）" if d.revisit_on else "（未定回看日）"
        return f"⏳ 待裁决{tail}"
    v = d.verdict
    return f"{_VERDICT_ICON[v.verdict]} {VERDICTS[v.verdict]}"


def _print_decision(d: Decision, today: datetime.date) -> None:
    flag = "🔔 " if d.is_due(today) else ""
    print(f"  ◆ [{d.id}] {d.topic}  {flag}{_fmt_verdict(d)}")
    print(f"      选了：{d.chosen}")
    for o in d.rejected:
        why = f"（{o.why}）" if o.why else ""
        print(f"      放弃：{o.what}{why}")
    if d.verdict and d.verdict.lesson:
        print(f"      若重来：{d.verdict.lesson}")


def _print_list(decisions: list[Decision]) -> None:
    today = _now().date()
    if not decisions:
        print("🔀 反事实账本还空着——用 `python counterfactual.py decide ...` 记下第一个岔路口。")
        print("   每条只要答清：选了什么、放弃了哪些(各附理由)、几时回头对照。")
        return
    sc = score(decisions)
    print(f"🔀 opencrab 反事实账本（{len(decisions)} 个岔路口 / 已裁决 "
          f"{sc.judged + sc.moot} / 待裁决 {sc.pending}）\n")
    for d in decisions:
        _print_decision(d, today)
    overdue = due(decisions, today)
    if overdue:
        ids = "、".join(d.id for d in overdue)
        print(f"\n🔔 有 {len(overdue)} 个决定早该回头对照了（{ids}）——跑 `--due` 看欠的债。")
    if sc.hit_rate is not None:
        print(f"   取舍命中率 {sc.hit_rate:.0%}（{sc.held}/{sc.judged}）——跑 `--score` 看这面镜子。")


def _print_due(decisions: list[Decision]) -> None:
    today = _now().date()
    overdue = due(decisions, today)
    if not overdue:
        print("🔀 没有欠着的复盘——该回头的决定都裁决过了，或都还没到日子。")
        return
    print(f"🔔 {len(overdue)} 个决定早该回头对照、却还没裁决——这是嘴上说要复盘、身体却没做的债：\n")
    for d in overdue:
        _print_decision(d, today)
    print(f"\n  到点了就给它一个裁决：`counterfactual.py revisit <id> "
          f"--verdict held|regret|moot [--lesson ...]`。")


def _print_lessons(decisions: list[Decision]) -> None:
    ls = lessons(decisions)
    if not ls:
        print("🔀 还没有 regret 的教训——要么取舍都对，要么还没回头裁决过。")
        return
    print(f"🔁 {len(ls)} 条「若重来」教训——别让同一种误判来第二次：\n")
    for d, lesson in ls:
        print(f"  🔁 [{d.id}] {d.topic}")
        print(f"      当初选了：{d.chosen}")
        print(f"      若重来：{lesson}")


def _print_score(decisions: list[Decision]) -> None:
    sc = score(decisions)
    print("🔀 取舍命中率——我到底有多会取舍\n")
    print(f"  ✅ 选对了 held    : {sc.held}")
    print(f"  🔁 该选别的 regret: {sc.regret}")
    print(f"  ➖ 无所谓了 moot  : {sc.moot}（不进命中率，对错已不可比）")
    print(f"  ⏳ 待裁决 pending : {sc.pending}")
    if sc.hit_rate is None:
        print("\n  还没有可对错的裁决——多记几个岔路口、到点回头裁决，这面镜子才照得出东西。")
    else:
        print(f"\n  命中率 = {sc.held}/{sc.judged} = {sc.hit_rate:.0%}")
        if sc.regret:
            print("  跑 `--lessons` 看那 %d 次「该选别的」栽出了什么教训。" % sc.regret)


def manifest() -> dict:
    """导出纯数据：全部决定 + 裁决 + 命中率 + 欠的债(给外部工具消费)。"""
    decisions = load()
    sc = score(decisions)
    today = _now().date()
    return {
        "count": len(decisions),
        "decisions": [d.to_meta() for d in decisions],
        "score": sc.to_meta(),
        "due": [d.id for d in due(decisions, today)],
        "lessons": [{"id": d.id, "topic": d.topic, "lesson": lesson}
                    for d, lesson in lessons(decisions)],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 反事实账本 🔀")
    sub = ap.add_subparsers(dest="cmd")

    p_dec = sub.add_parser("decide", help="记一个岔路口(选了什么/放弃了什么/几时回头看)")
    p_dec.add_argument("--topic", required=True, help="这个决定是关于什么的")
    p_dec.add_argument("--chose", "--chosen", dest="chosen", required=True,
                       help="实际走的那条路")
    p_dec.add_argument("--reject", action="append", default=[], metavar="WHAT=WHY",
                       help="一个被放弃的方案，格式 `方案=放弃理由`(可重复)")
    p_dec.add_argument("--revisit", default=None, metavar="N|DATE",
                       help="几时回头对照：N 天后，或 YYYY-MM-DD(默认:不定)")

    p_rev = sub.add_parser("revisit", help="给一条决定补一个事后裁决")
    p_rev.add_argument("id", help="决定的短 id(见清单 [xxxxxx])")
    p_rev.add_argument("--verdict", required=True, choices=list(VERDICTS),
                       help="held(选对了)/regret(该选别的)/moot(无所谓了)")
    p_rev.add_argument("--lesson", default="", help="一句「若重来」的教训(regret 必填)")

    ap.add_argument("--due", action="store_true",
                    help="只列「早该回头、却还没裁决」的决定(欠的债)")
    ap.add_argument("--lessons", action="store_true",
                    help="汇总所有 regret 的「若重来」教训")
    ap.add_argument("--score", action="store_true", help="取舍命中率：我到底有多会取舍")
    ap.add_argument("--quiet", action="store_true",
                    help="只在「有决定该回头对照了」时说话(钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出机读:决定 + 裁决 + 命中率")
    args = ap.parse_args(argv)

    if args.cmd == "decide":
        rejected: list[Option] = []
        for raw in args.reject:
            what, sep, why = raw.partition("=")
            rejected.append(Option(what=what.strip(), why=why.strip() if sep else ""))
        rejected = [o for o in rejected if o.what]
        try:
            did, ok = record_decision(args.topic, args.chosen, rejected, args.revisit)
        except ValueError as e:
            print(f"⚠️  {e}")
            sys.exit(2)
        if ok:
            when = _parse_revisit_on(args.revisit)
            tail = f"，{when} 回头对照" if when else ""
            print(f"🔀 记下岔路口 [{did}] {args.topic.strip()}{tail}。")
        else:
            print(f"⚠️  这个决定没落盘(写盘失败已吞)，但生命照常——[{did}] {args.topic.strip()}。")
        return

    if args.cmd == "revisit":
        existing = {d.id for d in load()}
        if args.id not in existing:
            print(f"⚠️  没有 id 为 {args.id!r} 的决定；跑 `counterfactual.py` 看清单里的 [xxxxxx]。")
            sys.exit(2)
        try:
            ok = record_verdict(args.id, args.verdict, args.lesson)
        except ValueError as e:
            print(f"⚠️  {e}")
            sys.exit(2)
        icon = _VERDICT_ICON[args.verdict]
        if ok:
            print(f"🔀 [{args.id}] 已裁决 {icon} {VERDICTS[args.verdict]}。")
        else:
            print(f"⚠️  这条裁决没落盘(写盘失败已吞)，但生命照常——[{args.id}] {icon}。")
        return

    decisions = load()

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        sys.exit(0)

    if args.due:
        _print_due(decisions)
        sys.exit(1 if due(decisions) else 0)

    if args.lessons:
        _print_lessons(decisions)
        sys.exit(0)

    if args.score:
        _print_score(decisions)
        sys.exit(0)

    overdue = due(decisions)
    if args.quiet:
        if overdue:
            ids = "、".join(d.id for d in overdue)
            print(f"🔀 有 {len(overdue)} 个决定该回头对照了（{ids}）——跑 `counterfactual.py --due`。")
            sys.exit(1)
        sys.exit(0)

    _print_list(decisions)
    sys.exit(0)


if __name__ == "__main__":
    main()
