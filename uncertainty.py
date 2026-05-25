#!/usr/bin/env python3
"""不确定账本 🎲 —— 给每个计划/判断当场打一个**置信度**、列清**未知项**；置信度太低的，
自动转成一张**求证清单**(该先去验的几件事)。逼自己从「自信地断言」进化到「诚实地标注我不知道」。

为什么要有它：领地里已有一排账本在事后校准我**做过**的判断——证据(evidence)问「这话
还跑得通吗」、反事实(counterfactual)问「当初没选的那条路其实更好吗」、价值(value)问
「这对谁有用」。它们都在**结果出来之后**复盘。可最贵的错，往往在拍板的**那一刻**就埋下了：
我把一个 60% 把握的判断当 100% 喊出去，既没标出心虚、也没列出那几个「我其实不知道」的点，
于是没人(包括我自己)会想到要去验它——直到它在下游炸开，才发现当初的笃定全是错觉。

本层把每个判断钉成一条**带置信度的记录**，拍板当场答清三件事：

  · 判断是什么(statement) —— 这次要赌的那句话 / 那个计划。
  · 有几成把握(confidence) —— 0–100 的整数。逼自己把「我觉得」翻译成一个数。
  · 哪些我其实不知道(unknown) —— 撑着这个判断、却还没验过的前提(可多个)。
                      列不出未知项的高置信判断，最该被怀疑——多半是没想透，不是真有把握。

置信度低于阈值(默认 60)的判断会被自动标成 🔍 **该求证**：它的未知项就是一张现成的
求证清单——别急着照这个判断行动，先把单子上的几件事验掉。`--probe` 把所有这类判断的
未知项汇成一页待验清单。

结果出来后用 `resolve` 给判断一个**事后真值**：

  · ✅ right(应验了)    —— 当初判断成立。
  · ❌ wrong(错了)      —— 当初判断不成立。
  · ➖ moot(没法验)     —— 情况变了 / 这判断已不可对错。

攒够真值，账本就能算出我的**置信度校准**(--calib):把判断按声称的把握分档,对照各档
里**真实的命中率**。声称 90% 的那批判断,真有 9 成应验吗?声称与现实的差距,就是我
「自信得过了头」还是「其实可以更笃定」的最诚实刻度——这正是「承认不知道」要照的那面镜子。

用法:
    python uncertainty.py claim "改用增量索引能把构建压到 5 分钟内" --conf 55 \\
        --unknown "没测过冷启动" --unknown "依赖的缓存命中率没数据"
                                       # 记一个判断(低于阈值会被标成🔍该求证)
    python uncertainty.py resolve ab12cd --truth wrong \\
        --note "冷启动下反而更慢——当初那个未知项就是答案"
                                       # 给一条判断补一个事后真值
    python uncertainty.py             # 判断清单 + 各自置信度 / 未知项 / 真值
    python uncertainty.py --probe     # 只列「该求证」的判断,汇成一张待验清单
    python uncertainty.py --calib     # 置信度校准:我声称的把握,对得上真实命中率吗
    python uncertainty.py --quiet     # 只在「有判断悬着没求证」时说话(钩子 / CI)
    python uncertainty.py --json      # 机读:导出全部判断 + 真值 + 校准

零第三方依赖,纯标准库。账本是观测者:写盘失败被吞、读不到就当空,绝不反噬生命。
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

LOG_PATH = REPO_ROOT / "state" / "uncertainty.jsonl"

# 低于这个把握就自动标「该求证」——别拿没验过的判断当确定的事用。
SHAKY_BELOW = 60

# 三种事后真值,只有 right / wrong 进校准——moot 是「已不可对错」,算进去只会污染那面镜子。
TRUTHS: dict[str, str] = {
    "right": "应验了",
    "wrong": "错了",
    "moot": "没法验",
}
_TRUTH_ICON = {"right": "✅", "wrong": "❌", "moot": "➖"}

# 置信度分档(左闭右开,顶档含 100)——校准就是看每一档里声称 vs. 真实命中。
_BANDS = [(0, 50), (50, 70), (70, 90), (90, 101)]


def _now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _short_id(statement: str, ts: str) -> str:
    """由 判断+时刻 派生一个稳定的 6 位短 id——便于 resolve 时回指这条判断。"""
    return hashlib.sha1(f"{statement}|{ts}".encode("utf-8")).hexdigest()[:6]


def _clamp_conf(raw: object) -> int:
    """把置信度规整到 0–100 的整数;非法值当 0(宁可记成「毫无把握」也不凭空抬高)。"""
    try:
        return max(0, min(100, int(round(float(raw)))))
    except (TypeError, ValueError):
        return 0


# ── 数据模型 ──────────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Truth:
    """一条事后真值:当初这个判断成立吗,以及一句复盘。"""
    truth: str       # TRUTHS 之一
    note: str        # 一句复盘(wrong 时最该写:当初哪个未知项才是答案)
    ts: str          # 裁定时刻

    def to_meta(self) -> dict:
        return {"truth": self.truth, "note": self.note, "ts": self.ts}


@dataclasses.dataclass(frozen=True)
class Claim:
    """一个带置信度的判断:赌的是什么、几成把握、哪些其实不知道、事后真值如何。"""
    id: str
    statement: str           # 这次要赌的那句话
    confidence: int          # 0–100 的把握
    unknowns: list[str]      # 撑着这个判断、却还没验过的前提
    ts: str                  # 拍板时刻
    truth: Truth | None      # 事后真值;None=还没裁定

    @property
    def resolved(self) -> bool:
        """是否已经裁定过真值。"""
        return self.truth is not None

    @property
    def shaky(self) -> bool:
        """把握太低、还没裁定——这就是该先去求证、别急着行动的判断。"""
        return not self.resolved and self.confidence < SHAKY_BELOW

    def to_meta(self) -> dict:
        return {
            "id": self.id, "statement": self.statement,
            "confidence": self.confidence, "unknowns": list(self.unknowns),
            "ts": self.ts, "shaky": self.shaky,
            "truth": self.truth.to_meta() if self.truth else None,
        }


# ── 存取:判断与真值都各写一行 JSONL,读时按 id 合并 ──────────────────────
def _parse_unknowns(raw: object) -> list[str]:
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            s = str(item).strip()
            if s:
                out.append(s)
    return out


def load() -> list[Claim]:
    """读出全部判断(拍板时间正序),并把后续 resolve 行合并到对应判断上。

    文件缺失/坏行都安全跳过;真值行若指向不存在的 id,直接忽略(宁可丢一条真值,
    也不凭空造一个判断)。同一 id 多条真值取最后一条——复盘可以改主意。
    """
    claims: dict[str, Claim] = {}
    truths: dict[str, Truth] = {}
    order: list[str] = []
    for rec in read_jsonl(LOG_PATH):
        kind = rec.get("kind")
        if kind == "claim":
            cid = str(rec.get("id", "")).strip()
            statement = str(rec.get("statement", "")).strip()
            if not cid or not statement:
                continue
            claims[cid] = Claim(
                id=cid, statement=statement,
                confidence=_clamp_conf(rec.get("confidence")),
                unknowns=_parse_unknowns(rec.get("unknowns")),
                ts=str(rec.get("ts", "")), truth=None,
            )
            if cid not in order:
                order.append(cid)
        elif kind == "truth":
            cid = str(rec.get("id", "")).strip()
            t = rec.get("truth")
            if cid and t in TRUTHS:
                truths[cid] = Truth(truth=t,
                                    note=str(rec.get("note", "")).strip(),
                                    ts=str(rec.get("ts", "")))
    out = []
    for cid in order:
        c = claims[cid]
        t = truths.get(cid)
        out.append(dataclasses.replace(c, truth=t) if t else c)
    return out


def record_claim(statement: str, confidence: int, unknowns: list[str]) -> tuple[str, bool, bool]:
    """记一个带置信度的判断;返回 (短id, 是否落盘成功, 是否被标为该求证)。

    写盘失败被吞,绝不反噬生命。空判断直接拒绝——没法事后回指的判断不算判断。
    """
    statement = statement.strip()
    if not statement:
        raise ValueError("判断得有内容——空话没法打置信度,也没法事后回头验。")
    conf = _clamp_conf(confidence)
    unknowns = [u.strip() for u in unknowns if u.strip()]
    ts = _now_iso()
    cid = _short_id(statement, ts)
    rec = {
        "kind": "claim", "id": cid, "statement": statement,
        "confidence": conf, "unknowns": unknowns, "ts": ts,
    }
    return cid, append_jsonl(LOG_PATH, rec), conf < SHAKY_BELOW


def record_truth(cid: str, truth: str, note: str) -> bool:
    """给一条判断补一个事后真值。truth 非法直接拒绝;写盘失败被吞。"""
    if truth not in TRUTHS:
        raise ValueError(f"真值须是 {'/'.join(TRUTHS)} 之一,收到 {truth!r}")
    note = note.strip()
    if truth == "wrong" and not note:
        raise ValueError("wrong 必须附一句复盘(--note)——当初哪个未知项才是答案?否则这一错白栽了。")
    rec = {"kind": "truth", "id": cid.strip(), "truth": truth,
           "note": note, "ts": _now_iso()}
    return append_jsonl(LOG_PATH, rec)


# ── 置信度校准:我声称的把握,对得上真实命中率吗 ────────────────────────────
@dataclasses.dataclass(frozen=True)
class Band:
    """一个置信度档位里的校准:声称的平均把握 vs. 真实命中率。"""
    lo: int
    hi: int                  # 右开区间 [lo, hi)
    right: int
    wrong: int

    @property
    def judged(self) -> int:
        """进校准的判断数(moot 不算——对错已不可比)。"""
        return self.right + self.wrong

    @property
    def hit_rate(self) -> float | None:
        """这一档真实命中率 = right ÷ judged;还没有可对错的真值时为 None。"""
        return self.right / self.judged if self.judged else None

    @property
    def label(self) -> str:
        return f"{self.lo}–{self.hi - 1 if self.hi <= 100 else 100}"

    def to_meta(self) -> dict:
        return {"band": self.label, "right": self.right, "wrong": self.wrong,
                "judged": self.judged,
                "hit_rate": round(self.hit_rate, 3) if self.hit_rate is not None else None}


def calibrate(claims: list[Claim]) -> list[Band]:
    """把已裁定真值的判断按声称把握分档,各档算真实命中率(moot 不计)。"""
    bins = {(lo, hi): {"right": 0, "wrong": 0} for lo, hi in _BANDS}
    for c in claims:
        if not c.truth or c.truth.truth == "moot":
            continue
        for lo, hi in _BANDS:
            if lo <= c.confidence < hi:
                bins[(lo, hi)][c.truth.truth] += 1
                break
    return [Band(lo=lo, hi=hi, right=bins[(lo, hi)]["right"],
                 wrong=bins[(lo, hi)]["wrong"]) for lo, hi in _BANDS]


def shaky(claims: list[Claim]) -> list[Claim]:
    """把握太低、还悬着没求证的判断——别急着照它们行动的那几条。"""
    return [c for c in claims if c.shaky]


# ── 展示 ──────────────────────────────────────────────────────────────
def _conf_bar(conf: int) -> str:
    """把置信度画成一根 10 格的把握条。"""
    filled = round(conf / 10)
    return "█" * filled + "░" * (10 - filled)


def _fmt_truth(c: Claim) -> str:
    if not c.truth:
        return "🔍 该求证" if c.shaky else "⏳ 待裁定"
    return f"{_TRUTH_ICON[c.truth.truth]} {TRUTHS[c.truth.truth]}"


def _print_claim(c: Claim) -> None:
    print(f"  ◆ [{c.id}] {c.statement}")
    print(f"      把握 {_conf_bar(c.confidence)} {c.confidence:>3}%   {_fmt_truth(c)}")
    for u in c.unknowns:
        print(f"      未知:{u}")
    if c.truth and c.truth.note:
        print(f"      复盘:{c.truth.note}")


def _print_list(claims: list[Claim]) -> None:
    if not claims:
        print("🎲 不确定账本还空着——用 `python uncertainty.py claim \"...\" --conf N` 记下第一个判断。")
        print("   每条只要答清:判断是什么、有几成把握、哪些其实还不知道。")
        return
    sh = shaky(claims)
    resolved = sum(1 for c in claims if c.resolved)
    print(f"🎲 opencrab 不确定账本({len(claims)} 个判断 / 已裁定 {resolved} / "
          f"该求证 {len(sh)})\n")
    for c in claims:
        _print_claim(c)
    if sh:
        ids = "、".join(c.id for c in sh)
        print(f"\n🔍 有 {len(sh)} 个判断把握不足、还没求证({ids})——跑 `--probe` 看该先验什么。")
    bands = [b for b in calibrate(claims) if b.judged]
    if bands:
        print("   跑 `--calib` 看:我声称的把握,对不对得上真实命中率。")


def _print_probe(claims: list[Claim]) -> None:
    sh = shaky(claims)
    if not sh:
        print("🎲 没有悬着的判断——要么把握都够,要么低置信的都已裁定真值。")
        return
    total = sum(len(c.unknowns) for c in sh)
    print(f"🔍 {len(sh)} 个判断把握不足({SHAKY_BELOW}% 以下)、还没求证——别照它们行动,"
          f"先把这 {total} 件未知验掉:\n")
    for c in sh:
        print(f"  ◆ [{c.id}] {c.statement}（把握 {c.confidence}%）")
        if c.unknowns:
            for u in c.unknowns:
                print(f"      ☐ 求证:{u}")
        else:
            print("      ☐ 求证:这条没列未知项——先想清「到底哪里没把握」,本身就是第一步。")
    print(f"\n  验完一条就给个真值:`uncertainty.py resolve <id> --truth right|wrong|moot [--note ...]`。")


def _print_calib(claims: list[Claim]) -> None:
    bands = calibrate(claims)
    judged = sum(b.judged for b in bands)
    print("🎲 置信度校准——我声称的把握,对得上真实命中率吗\n")
    if not judged:
        print("  还没有可对错的真值——多记几个判断、结果出来后 `resolve` 裁定,这面镜子才照得出东西。")
        return
    for b in bands:
        if not b.judged:
            print(f"  把握 {b.label:>6}% :  （还没有已裁定的判断）")
            continue
        gap = b.hit_rate - (b.lo + min(b.hi, 100)) / 2 / 100
        hint = "自信过头" if gap < -0.15 else ("其实可更笃定" if gap > 0.15 else "对得上")
        print(f"  把握 {b.label:>6}% :  真实命中 {b.hit_rate:.0%}"
              f"（{b.right}/{b.judged}）  → {hint}")
    print(f"\n  声称的把握落在某档,真实命中却掉到下一档,就是「自信地错」的信号——"
          f"那种判断,下次该多列几个未知项、先去求证。")


def manifest() -> dict:
    """导出纯数据:全部判断 + 真值 + 该求证清单 + 校准(给外部工具消费)。"""
    claims = load()
    return {
        "count": len(claims),
        "claims": [c.to_meta() for c in claims],
        "shaky": [c.id for c in shaky(claims)],
        "calibration": [b.to_meta() for b in calibrate(claims)],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 不确定账本 🎲")
    sub = ap.add_subparsers(dest="cmd")

    p_claim = sub.add_parser("claim", help="记一个判断(内容/把握/未知项)")
    p_claim.add_argument("statement", help="这次要赌的那句话 / 那个计划")
    p_claim.add_argument("--conf", "--confidence", dest="confidence", type=int,
                         required=True, metavar="0-100", help="有几成把握(0–100)")
    p_claim.add_argument("--unknown", action="append", default=[], metavar="WHAT",
                         help="一个撑着判断却没验过的前提(可重复)")

    p_res = sub.add_parser("resolve", help="给一条判断补一个事后真值")
    p_res.add_argument("id", help="判断的短 id(见清单 [xxxxxx])")
    p_res.add_argument("--truth", required=True, choices=list(TRUTHS),
                       help="right(应验了)/wrong(错了)/moot(没法验)")
    p_res.add_argument("--note", default="", help="一句复盘(wrong 必填)")

    ap.add_argument("--probe", action="store_true",
                    help="只列「该求证」的判断,汇成一张待验清单")
    ap.add_argument("--calib", action="store_true",
                    help="置信度校准:声称的把握对得上真实命中率吗")
    ap.add_argument("--quiet", action="store_true",
                    help="只在「有判断悬着没求证」时说话(钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出机读:判断 + 真值 + 校准")
    args = ap.parse_args(argv)

    if args.cmd == "claim":
        try:
            cid, ok, is_shaky = record_claim(args.statement, args.confidence, args.unknown)
        except ValueError as e:
            print(f"⚠️  {e}")
            sys.exit(2)
        tail = "，已标为🔍该求证——别急着照它行动" if is_shaky else ""
        if ok:
            print(f"🎲 记下判断 [{cid}]（把握 {_clamp_conf(args.confidence)}%）{tail}。")
        else:
            print(f"⚠️  这个判断没落盘(写盘失败已吞),但生命照常——[{cid}]。")
        return

    if args.cmd == "resolve":
        existing = {c.id for c in load()}
        if args.id not in existing:
            print(f"⚠️  没有 id 为 {args.id!r} 的判断;跑 `uncertainty.py` 看清单里的 [xxxxxx]。")
            sys.exit(2)
        try:
            ok = record_truth(args.id, args.truth, args.note)
        except ValueError as e:
            print(f"⚠️  {e}")
            sys.exit(2)
        icon = _TRUTH_ICON[args.truth]
        if ok:
            print(f"🎲 [{args.id}] 已裁定 {icon} {TRUTHS[args.truth]}。")
        else:
            print(f"⚠️  这条真值没落盘(写盘失败已吞),但生命照常——[{args.id}] {icon}。")
        return

    claims = load()

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        sys.exit(0)

    if args.probe:
        _print_probe(claims)
        sys.exit(1 if shaky(claims) else 0)

    if args.calib:
        _print_calib(claims)
        sys.exit(0)

    sh = shaky(claims)
    if args.quiet:
        if sh:
            ids = "、".join(c.id for c in sh)
            print(f"🎲 有 {len(sh)} 个判断把握不足、还没求证（{ids}）——跑 `uncertainty.py --probe`。")
            sys.exit(1)
        sys.exit(0)

    _print_list(claims)


if __name__ == "__main__":
    main()
