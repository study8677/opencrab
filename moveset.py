#!/usr/bin/env python3
"""自生手补丁招式库 🥋🖐️ —— 把已验收/拒收的 brain 补丁，提炼成「落爪前先查一眼」的直觉。

为什么要有它：`weaning_trial.py` 里那串 `TACTICS`（补冒号 / 括号 print / 名字纠偏）是 brain
亲手改码的**底层招式**——每招读懂一类报错、改一处源码。可 `brain_repair` 用它们时是**盲打**：
不管哪类伤，都按 `TACTICS` 写死的次序一招招试下去，试中算运气，试不中再换下一招。
试衣间(`patchfitroom`)把改坏的当场拦下、返工单(`fitrework`)把拒收封成案例——它们都在
**落爪之后**收拾残局。可一只成熟的手，不该只会事后复盘：**它该在落爪之前就有谱**——
「这类报错，哪一招最可能成、哪一招踩过哪道闸的坑」。

本层就把散落的经验收成那本谱。它**不重写任何一招**——招式的改写本体始终是 `weaning_trial`
里那几个 tactic 函数（单一真相源，那边一改这边自动跟着变）；本层只在它们之上**结一层认知**：

  1) 🗂️ **招式卡(Move)**：每招配一句「治什么伤、怎么改」+ 一段能当场跑的 worked example
     （直接取自 `weaning_trial.CHALLENGES` 的真实赛题），让「可复用的改写模板」看得见、摸得着。
  2) 📈 **实战可靠度**：从 `state/weaning_trial.jsonl` 的历次战报里采掘——这招在真赛题里
     赢过几次、上过几次场。没有战报也不慌：每张卡都能**当场自验**(拿它自己的 worked example
     重跑一遍，看还修不修得通)，于是「可靠」永远有一个不依赖历史数据的底。
  3) 🧭 **落爪前的直觉 `suggest(src, exc)`**：brain 撞上一个异常时，先来查这本谱——把**真能对这段
     源码落地**(tactic 产出候选、且过补丁契约)的招式，按实战可靠度排好序端上来。
     触发判定全权交给真 tactic（cand 非空且过契约才算「使得上」），**绝不另写一份会和招式漂移的猜测**。

设计原则与全家一致：零第三方依赖、纯标准库；招式库是观测者/参谋，读盘失败、tactic 抛错
一律吞掉收敛成「这招使不上」，绝不反噬动手主流程——给手长直觉的层，自己不能成为新的伤口。

用法:
    python moveset.py                 # 提炼并打印整本招式谱(每招:可靠度 + 自验 + worked example)
    python moveset.py --selfcheck     # 自检:每招都能自验修通 / suggest 按真触发与可靠度排序
    python moveset.py --json          # 机读:招式谱(招式卡 + 采掘到的实战统计)
    python moveset.py --suggest NAME  # 拿某张卡的 worked example 当现场，演示 suggest 端出什么

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
from typing import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore       # noqa: E402 —— 复用「读一批」的安全落地层
import patchcontract    # noqa: E402 —— 触发判定收尾要过补丁契约：使得上 = 产出候选且不越界
import weaning_trial    # noqa: E402 —— 招式与赛题的单一真相源；本层只在其上结认知，绝不重写招式

TRIAL_LOG = REPO_ROOT / "state" / "weaning_trial.jsonl"


@dataclasses.dataclass(frozen=True)
class Move:
    """一张招式卡：治什么伤、改写本体是哪个 tactic、配一段能当场跑的 worked example。"""
    move_id: str                       # 招式名(= tactic 函数名去掉 tactic_ 前缀)
    summary: str                       # 一句话：这招治什么、怎么改
    trigger: str                       # 触发签名(人话)：撞上什么报错该想起它
    tactic: Callable[[str, BaseException], str | None]  # 真正的改写函数(来自 weaning_trial)
    challenge: weaning_trial.Challenge  # 配套的真实赛题，既当 worked example 又当自验题

    def to_meta(self) -> dict:
        """导出纯数据(不含不可序列化的 tactic/challenge 本体)。"""
        return {"move_id": self.move_id, "summary": self.summary, "trigger": self.trigger,
                "example_broken": self.challenge.broken, "example_want": self.challenge.want}


# ── 招式谱：每招 = weaning 的一个 tactic + 它配套的赛题(单一真相源，绝不重写改写本体) ──
def _build_catalog() -> list[Move]:
    """把 weaning_trial 的 tactic 与 CHALLENGES 配对成招式卡。

    配对靠 tactic 名里的关键词命中赛题的 want/wound——赛题本就是「为这一招量身造的真伤」，
    于是招式卡的 worked example 永远是真能被这招修通的现场，不是手写的标本。
    """
    # 每招两句：summary=「治什么、怎么改」，trigger=「撞上什么报错该想起它」(落爪前查谱按它对号入座)
    metas = {
        "tactic_missing_colon": dict(
            summary="补冒号：给报错那一行末尾补上结尾冒号",
            trigger="SyntaxError 抱怨缺 ':'（def/if/for… 行尾漏了冒号）"),
        "tactic_print_parens": dict(
            summary="括号 print：把 Python2 的 `print X` 收成 `print(X)`",
            trigger="SyntaxError 抱怨 print 缺括号（Missing parentheses in call to 'print'）"),
        "tactic_name_typo": dict(
            summary="名字纠偏：把认不出的名字跟已知名字做最近匹配后整词改回",
            trigger="NameError 认不出某个名字（多半是拼错/手滑）"),
    }
    # 赛题按 name 索引，给每个 tactic 找它的 worked example
    by_name = {c.name: c for c in weaning_trial.CHALLENGES}
    pairing = {
        "tactic_missing_colon": "补冒号",
        "tactic_print_parens": "括号 print",
        "tactic_name_typo": "名字纠偏",
    }
    catalog: list[Move] = []
    for tactic in weaning_trial.TACTICS:
        name = getattr(tactic, "__name__", "")
        if name not in metas or pairing.get(name) not in by_name:
            continue  # 招式库只收「有配套赛题、能自验」的招——收不进谱的招不假装它在
        meta = metas[name]
        catalog.append(Move(
            move_id=name.removeprefix("tactic_"),
            summary=meta["summary"], trigger=meta["trigger"], tactic=tactic,
            challenge=by_name[pairing[name]]))
    return catalog


CATALOG: list[Move] = _build_catalog()


# ── 自验：拿招式卡自己的 worked example 重跑一遍，看这招今天还修不修得通 ────────────
def verify_move(move: Move) -> bool:
    """只用这一招去修它配套的赛题，过补丁契约 + 自测能启动 + oracle 判真修好，才算「这招还活着」。

    单招(而非 brain_repair 的全招轮试)地验：确认是**这一招**修通的，而非别的招捡了漏。
    永不抛错——任何意外都收敛成「没验通」，自验自己不能成为新伤口。
    """
    try:
        c = move.challenge
        src = c.broken
        for _ in range(6):  # 同一招可能要连补几处(如多行同类报错)，给几轮收敛余地
            exc, ns = weaning_trial._self_test(src)
            if exc is None:
                break
            cand = move.tactic(src, exc)
            if cand is None or cand == src or not patchcontract.accepts(src, cand):
                return False   # 这招对这道伤使不上(或产出越界候选) → 没验通
            src = cand
        exc, ns = weaning_trial._self_test(src)
        if exc is not None:
            return False
        return bool(c.oracle(ns))
    except Exception:  # noqa: BLE001 —— 自验是观测，崩了只当「没验通」，绝不外溢
        return False


# ── 实战可靠度：从历次断奶战报里采掘，这招赢过/上过几次场 ──────────────────────
def _mine_stats() -> dict[str, dict]:
    """读 weaning_trial.jsonl，按 tactic 名采掘 {move_id: {seen, wins}}。

    战报里每场 bout 的 detail 文案带着 brain 这次用过的 tactic 名(brain_repair 的 trace)，
    won 标着这场最终有没有真修好。据此数：这招在多少场里被用过(seen)、其中多少场赢了(wins)。
    读盘失败/格式异常一律当「没有历史数据」，绝不抛。
    """
    stats = {m.move_id: {"seen": 0, "wins": 0} for m in CATALOG}
    name_to_id = {m.tactic.__name__: m.move_id for m in CATALOG}
    try:
        rows = jsonlstore.read_jsonl(TRIAL_LOG)
    except Exception:  # noqa: BLE001
        return stats
    for row in rows:
        for bout in (row.get("bouts") or []):
            detail = bout.get("detail", "") or ""
            for tname, mid in name_to_id.items():
                if tname in detail:
                    stats[mid]["seen"] += 1
                    if bout.get("won"):
                        stats[mid]["wins"] += 1
    return stats


def reliability(move: Move, stats: dict[str, dict] | None = None) -> dict:
    """把一招的「可靠度」折成可读直觉：自验是否活着 + 历史胜场/上场。

    verified 是不依赖历史数据的底（每天都能当场重算）；wins/seen 是历史加成。
    rank 仅用于 suggest 排序：先看活没活(自验)，再看赢得多不多——经验越足，越早被想起。
    """
    st = (stats or _mine_stats()).get(move.move_id, {"seen": 0, "wins": 0})
    verified = verify_move(move)
    return {"move_id": move.move_id, "verified": verified,
            "wins": st["wins"], "seen": st["seen"],
            "rank": (1 if verified else 0, st["wins"], st["seen"])}


# ── 落爪前的直觉：撞上异常先查谱，把真能落地的招按可靠度端上来 ──────────────────
@dataclasses.dataclass(frozen=True)
class Suggestion:
    """一条落爪建议：哪招、它对这段源码产出的候选、为什么排在这、可靠度凭据。"""
    move_id: str
    summary: str
    candidate: str        # 这招对当前源码真产出的候选补丁(已过补丁契约)
    rationale: str        # 一句人话：凭什么推荐它、它的实战底气
    rank: tuple


def suggest(src: str, exc: BaseException) -> list[Suggestion]:
    """brain 撞上 exc 时，落爪前先查这本谱：返回**真能对 src 落地**的招，按实战可靠度排好序。

    「真能落地」= 这招的 tactic 对 (src, exc) 产出了一个非空、确有改动、且过补丁契约的候选——
    触发判定全权交给真 tactic，绝不另写一份会跟招式漂移的猜测。可靠度由 reliability 折算，
    排在前的：先是当场自验还活着的，再是历史赢得多的。永不抛错。
    """
    if exc is None:
        return []   # 没异常就没伤要修，自然无招可荐——把「永不抛错」钉在边界，不赖各招自己防 None
    stats = _mine_stats()
    out: list[Suggestion] = []
    for move in CATALOG:
        try:
            cand = move.tactic(src, exc)
        except Exception:  # noqa: BLE001 —— 某招探它使不使得上时抛了，只当它使不上
            cand = None
        if cand is None or cand == src or not patchcontract.accepts(src, cand):
            continue   # 这招对当前现场使不上(或产出越界候选)，不端上来
        rel = reliability(move, stats)
        verified = rel["verified"]
        if rel["seen"]:
            note = f"实战 {rel['wins']}/{rel['seen']} 胜" + ("、自验仍活" if verified else "、但自验已失")
        else:
            note = "自验仍能修通它的样例" if verified else "暂无战报、自验也未通过(慎用)"
        out.append(Suggestion(move.move_id, move.summary, cand,
                              f"{move.trigger}；{note}", rel["rank"]))
    out.sort(key=lambda s: s.rank, reverse=True)   # 可靠度高的排前面
    return out


def distill() -> dict:
    """提炼整本招式谱：每招的卡面 + 当场自验 + 采掘到的实战统计。这是「可复用改写模板」的成品。"""
    stats = _mine_stats()
    moves = []
    for m in CATALOG:
        rel = reliability(m, stats)
        moves.append({**m.to_meta(), "verified": rel["verified"],
                      "wins": rel["wins"], "seen": rel["seen"]})
    return {"moves": moves, "trial_log": str(TRIAL_LOG.relative_to(REPO_ROOT))}


def manifest() -> dict:
    """机读：招式谱(给 health / 外部消费)。"""
    return distill()


# ── 自检 ─────────────────────────────────────────────────────────────
def selfcheck(quiet: bool = False) -> bool:
    """自检：招式谱非空 / 每招都能自验修通 / suggest 只端真能落地的招且按可靠度排序。

    全程纯内存(自验在隔离命名空间里 exec 赛题源码、不碰真仓库)，确定性、无副作用。供 evidence 复跑。
    """
    failures: list[str] = []

    if not CATALOG:
        failures.append("招式谱竟为空——至少该从 weaning 的 TACTICS 提炼出几招")

    # 1) 每招都能拿自己的 worked example 自验修通(招式库收的就该是真修得通的招)
    for m in CATALOG:
        if not verify_move(m):
            failures.append(f"招式「{m.move_id}」自验没修通它自己的样例——这招进谱前就该先验活")

    # 2) suggest 对一段真伤，端出的招都真能落地(候选过补丁契约)，且补冒号该被想起
    broken = "def add(a, b)\n    return a + b\n"   # 漏冒号
    exc, _ = weaning_trial._self_test(broken)
    sug = suggest(broken, exc)
    if not sug:
        failures.append("漏冒号的现场，suggest 竟一招都没端出来")
    for s in sug:
        if not patchcontract.accepts(broken, s.candidate):
            failures.append(f"suggest 端出的「{s.move_id}」候选竟不过补丁契约")
    if sug and sug[0].move_id != "missing_colon":
        failures.append(f"漏冒号现场该首推 missing_colon，实得 {sug[0].move_id}")

    # 3) 排序单调：rank 必须降序(可靠度高的在前)
    ranks = [s.rank for s in sug]
    if ranks != sorted(ranks, reverse=True):
        failures.append(f"suggest 未按可靠度降序排列：{ranks}")

    # 4) 使不上的招不该被端出来：拿一个谁都治不了的伤(顶层 raise)，suggest 应为空
    dead = 'raise RuntimeError("无招可解")\n'
    exc2, _ = weaning_trial._self_test(dead)
    if suggest(dead, exc2):
        failures.append("无招可解的现场，suggest 不该硬端出招来")

    # 5) 观测者不反噬：采掘历史统计永不抛，字段齐全
    try:
        st = _mine_stats()
        for m in CATALOG:
            assert set(st[m.move_id]) == {"seen", "wins"}, "统计字段不全"
    except Exception as e:  # noqa: BLE001
        failures.append(f"采掘历史统计不该抛错：{e!r}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ moveset selfcheck：每招都能自验修通、suggest 只端真能落地的招并按实战可靠度排序"
                  "——招式库可信。")
        else:
            print("❌ moveset selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _print_book() -> None:
    book = distill()
    print("🥋🖐️  自生手补丁招式库 —— 从已验收/拒收的 brain 补丁提炼的可复用改写模板：\n")
    for m in book["moves"]:
        live = "🟢 自验仍活" if m["verified"] else "🔴 自验未通过"
        hist = f"实战 {m['wins']}/{m['seen']} 胜" if m["seen"] else "暂无战报"
        print(f"  · {m['move_id']} —— {m['summary']}")
        print(f"      触发：{m['trigger']}")
        print(f"      可靠：{live}；{hist}")
        print(f"      worked example：{m['example_broken']!r} → 验「{m['example_want']}」")
    print(f"\n  战报采掘自：{book['trial_log']}（没有也不慌，自验是不依赖历史的底）\n")


def _demo_suggest(move_id: str) -> int:
    """拿某张卡的 worked example 当现场，演示 suggest 在落爪前端出什么。"""
    m = next((x for x in CATALOG if x.move_id == move_id), None)
    if m is None:
        print(f"⛔ 招式库里没有「{move_id}」。现有：{', '.join(x.move_id for x in CATALOG)}")
        return 2
    broken = m.challenge.broken
    exc, _ = weaning_trial._self_test(broken)
    print(f"🧭 现场（{m.challenge.wound}）：\n{broken}")
    print(f"撞上：{type(exc).__name__ if exc else '无异常'}\n")
    sug = suggest(broken, exc)
    if not sug:
        print("（落爪前查谱：没有招使得上这个现场）")
        return 0
    print("落爪前查谱，按实战可靠度端出：")
    for i, s in enumerate(sug, 1):
        print(f"  {i}. {s.move_id} —— {s.rationale}")
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手补丁招式库 🥋🖐️")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：每招自验修通 / suggest 按真触发与可靠度排序(供 evidence 复跑)")
    ap.add_argument("--json", action="store_true", help="机读：招式谱(招式卡 + 实战统计)")
    ap.add_argument("--suggest", metavar="NAME",
                    help="拿某张卡的 worked example 当现场，演示 suggest 端出什么")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)
    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return
    if args.suggest:
        sys.exit(_demo_suggest(args.suggest))
    if not args.quiet:
        _print_book()


if __name__ == "__main__":
    main()
