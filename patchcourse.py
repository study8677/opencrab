#!/usr/bin/env python3
"""自生手补丁课程表 📒🖐️ —— 把已验收的小修，抽成「招式骨架」并 replay 验一例，练成肌肉。

为什么要有它：`handsdojo.py` 收的是**失败**——brain 修不动的真伤，封成到期重考的训练题。
可断奶不只靠补窟窿，还得把**成功经验练成肌肉**：`weaning_trial.py` 里那 3 类小修
(补冒号 / 括号 print / 名字纠偏)早已是**实战全过**的招式，却散在赛题与招式库两处，既没被
显式认领成「这是一门可教的课」，也没人定期回炉确认它还修得动。手要长稳，得把每一类「会修」
的成功，写成一张**课程表**：

  · 📒 **抽取(extract)**：从 `weaning_trial` 的**活**招式库 + 赛题里，逐类把「已验收的小修」
    认领出来——认领的判据不是写在题面里，而是当场把赛题坏源码丢回 brain 跑一遍、oracle 过了
    才算「已验收」。课程是从**真能修通的成功**里长出来的，不是手抄一份副本。
  · 🦴 **招式骨架(skeleton)**：每门课摊出这类小修的通用形状——认什么报错(trigger)、
    在哪下手(locate)、怎么最小地改一处(edit)、落笔前过哪道拒收闸(guard)，外加一对
    坏源码→修好的样例。骨架是给「下次撞上同类伤」的肌肉记忆，绝不内嵌某道题的标准答案。
  · 🔁 **replay 验一例**：把课程样例的坏源码丢回**真**brain 管子(`weaning_trial.brain_repair`
    + 这门课的 oracle)跑一遍，确认如今仍修得通、且真修对了(不只是「能启动」)。哪门课
    replay 不过，就是这身肌肉松了——该回炉，而不是继续宣称「我会修」。

于是「会修」不再是一句口号，而是一张**到期会自动回炉重练**的课程表：招式库每改一次，
`--replay-all` 就能一眼看出哪几门课还稳、哪门松了。它与 `handsdojo` 正好互补——一个把
失败练成下次会，一个把成功钉成肌肉。每场回炉结论追加进 state/patchcourse.jsonl，供复盘。

用法:
    python patchcourse.py                 # 列出课程表：每门已验收小修的招式骨架
    python patchcourse.py --show <id>     # 摊开一门课(骨架 + 坏源码→修好样例)
    python patchcourse.py --replay <id>   # 回炉一门：brain 如今仍修得通这门课吗
    python patchcourse.py --replay-all    # 全表回炉：哪几门课还稳、哪门松了
    python patchcourse.py --json          # 机读：课程表 + 回炉通过率
    python patchcourse.py --selfcheck [--quiet]  # 自检关键路径(供 evidence 复跑)

退出码：0 = 抽取齐全且回炉全过；1 = 有课抽不出或回炉没过。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore   # noqa: E402 —— 复用「读一批 / 追一条」的安全落地层
import weaning_trial  # noqa: E402 —— 活招式库 + 已验收赛题 + 真 brain 管子，课程从这里长出来

COURSE_LOG = REPO_ROOT / "state" / "patchcourse.jsonl"


# ── 招式骨架登记表：每类小修的通用形状(认报错→在哪下手→怎么改一处→过哪道闸) ────
# 键是 weaning_trial 招式函数名；抽取时会断言它确在活招式库里，骨架才长得出来。
# 骨架是「形状」而非「答案」——绝不内嵌某道赛题的标准修法，只描述这一类伤的通用治法。
_SKELETONS: dict[str, dict] = {
    "tactic_missing_colon": {
        "course": "补冒号",
        "emoji": "🔧",
        "trigger": "SyntaxError 且报错信息里含 \"':'\"(expected ':')",
        "locate": "exc.lineno 指向的那一行",
        "edit": "若该行非空、结尾还不是冒号 → 只在行尾补一个 ':'(单行单点改)",
        "guard": "候选先过 patchcontract：非空、确有改动、仅一处小改；畸形/重写式越界当场拒",
    },
    "tactic_print_parens": {
        "course": "括号 print",
        "emoji": "🔧",
        "trigger": "SyntaxError 且信息含「Missing parentheses in call to 'print'」",
        "locate": "exc.lineno 指向的那一行，匹配 `print <表达式>` 形态",
        "edit": "把 `print X` 收成 `print(X)`，保留原缩进(单行单点改)",
        "guard": "候选先过 patchcontract：仅一处小改；整段重写式越界当场拒",
    },
    "tactic_name_typo": {
        "course": "名字纠偏",
        "emoji": "🔧",
        "trigger": "NameError(认不出某个名字)",
        "locate": "异常携带的 name；跟「内建 + 本模块定义过的名字」做最近匹配",
        "edit": "difflib 取最近名字(cutoff≥0.6)，整词改回，只改这一个名(改不动则不出招)",
        "guard": "候选先过 patchcontract：整词替换不得演变成重写式越界，越界当场拒",
    },
}


# ── 一门课 ────────────────────────────────────────────────────────────────
@dataclasses.dataclass
class Course:
    """一门从已验收小修里抽出的课：招式骨架 + 一对坏源码→修好的样例。"""
    id: str                      # 课程号(招式函数名)
    name: str                    # 这门课治哪类伤(人话)
    emoji: str
    trigger: str                 # 认什么报错
    locate: str                  # 在哪下手
    edit: str                    # 怎么最小地改一处
    guard: str                   # 落笔前过哪道拒收闸
    wound: str                   # 样例那道伤是什么(来自赛题)
    broken: str                  # 样例坏源码(来自赛题，答案不写在题面里)
    want: str                    # oracle 想验的事(来自赛题)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _tactic_of(challenge: weaning_trial.Challenge) -> str | None:
    """把一道已验收赛题对应到它**实际**触发的招式：丢回真 brain 跑一遍，从轨迹里认领。

    认领的判据不靠下标对齐(脆)，而靠实跑——既确认这道小修「如今真修得通且 oracle 过」
    (= 已验收)，又从 trace 里读出是哪一招治好的。任一不成立都返回 None：抽不出课。
    """
    bout = weaning_trial.fight(challenge)
    if not bout.won:                     # oracle 没过 → 不是「已验收」，不认领
        return None
    rep = weaning_trial.brain_repair(challenge.broken)
    for t in rep.trace:                  # 轨迹形如 "tactic_missing_colon ⮕ SyntaxError"
        head = t.split(" ", 1)[0]
        if head in _SKELETONS:
            return head
    return None


# ── 抽取：从活招式库 + 已验收赛题里长出课程表 ───────────────────────────────
def extract() -> list[Course]:
    """逐类把「已验收的小修」抽成课。

    课程从**真能修通**里长出来：每道赛题先丢回 brain 实跑、oracle 过了才认领；再据触发的
    招式名挂上骨架登记表里的形状。招式不在活招式库、或这道伤如今修不通了 → 这门课抽不出，
    extract 返回的列表就缺它，selfcheck 会因此报警(肌肉松了)。
    """
    live = {f.__name__ for f in weaning_trial.TACTICS}
    courses: list[Course] = []
    seen: set[str] = set()
    for ch in weaning_trial.CHALLENGES:
        tac = _tactic_of(ch)
        if not tac or tac not in live or tac not in _SKELETONS or tac in seen:
            continue
        seen.add(tac)
        sk = _SKELETONS[tac]
        courses.append(Course(
            id=tac, name=sk["course"], emoji=sk["emoji"],
            trigger=sk["trigger"], locate=sk["locate"], edit=sk["edit"],
            guard=sk["guard"], wound=ch.wound, broken=ch.broken, want=ch.want))
    return courses


def _challenge_of(course_id: str) -> weaning_trial.Challenge | None:
    """回炉时取回这门课对应的赛题(带 oracle)——按实际触发招式认领，与 extract 同源。"""
    for ch in weaning_trial.CHALLENGES:
        if _tactic_of(ch) == course_id:
            return ch
    return None


def _get(courses: list[Course], cid: str) -> Course | None:
    for c in courses:
        if c.id == cid or c.id.startswith(cid) or c.name == cid:
            return c
    return None


# ── replay 验一例：把课程样例丢回真 brain 管子，确认仍修得通且真修对 ──────────
def replay(course: Course) -> dict:
    """回炉一门课：把样例坏源码丢回 `brain_repair` + 这门课的 oracle，验它如今仍修得通。

    判据是最严的「真修对」——不只是「能启动」(survived)，还得 oracle 过(won)；这正是
    `weaning_trial.fight` 的裁决。返回 {id, verdict, survived, won, rolled_back, trace}：
    verdict ∈ passed(肌肉还在) / regressed(松了，修出来 oracle 没过) /
    cannot_fix(彻底修不动了) / source_lost(赛题没了，无从回炉)。
    """
    ch = _challenge_of(course.id)
    if ch is None:
        return {"id": course.id, "verdict": "source_lost",
                "survived": False, "won": False, "rolled_back": False, "trace": []}
    bout = weaning_trial.fight(ch)
    rep = weaning_trial.brain_repair(ch.broken)
    if bout.won:
        verdict = "passed"
    elif bout.survived:
        verdict = "regressed"        # 改出来能启动，但 oracle 没过——修歪了
    else:
        verdict = "cannot_fix"       # 彻底修不动(回滚了)
    return {"id": course.id, "verdict": verdict, "survived": bout.survived,
            "won": bout.won, "rolled_back": bout.rolled_back, "trace": rep.trace}


def replay_all() -> list[dict]:
    """全表回炉：对每门课跑一遍 replay，看招式库改动后哪几门还稳、哪门松了。"""
    return [replay(c) for c in extract()]


# ── 折叠：课程表健康度 ──────────────────────────────────────────────────────
def summary(courses: list[Course] | None = None) -> dict:
    """课程表概览：应抽出的课数、实抽出数、回炉通过数与通过率。"""
    courses = extract() if courses is None else courses
    expected = len(_SKELETONS)
    results = [replay(c) for c in courses]
    passed = sum(1 for r in results if r["verdict"] == "passed")
    total = len(courses)
    return {"expected": expected, "extracted": total, "passed": passed,
            "open": total - passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "all_extracted": total == expected}


# ── 展示 ────────────────────────────────────────────────────────────────
def _print_skeleton(c: Course) -> None:
    print(f"  [{c.id}] {c.emoji} {c.name}")
    print(f"      认报错：{c.trigger}")
    print(f"      下手处：{c.locate}")
    print(f"      改一处：{c.edit}")
    print(f"      过闸　：{c.guard}")


def _print_table() -> None:
    courses = extract()
    s = summary(courses)
    print("📒🖐️  自生手补丁课程表（已验收小修 → 招式骨架，到期回炉重练）\n")
    if not courses:
        print("  （课程表空着——活招式库里还没有任何「实战修通且 oracle 过」的小修可抽。）")
        return
    print(f"  应抽 {s['expected']} 门 · 实抽 {s['extracted']} 门 · 回炉通过 {s['passed']} "
          f"· 通过率 {s['pass_rate']:.0%}")
    if not s["all_extracted"]:
        print(f"  ⚠️ 有 {s['expected'] - s['extracted']} 门课抽不出——对应小修可能已修不通(肌肉松了)。")
    print()
    for c in courses:
        _print_skeleton(c)


def _print_course(c: Course) -> None:
    print(f"📒  课程 [{c.id}] {c.emoji} {c.name}\n")
    print("   ── 招式骨架（形状，非答案）──")
    print(f"   认报错：{c.trigger}")
    print(f"   下手处：{c.locate}")
    print(f"   改一处：{c.edit}")
    print(f"   过闸　：{c.guard}\n")
    print(f"   ── 样例（{c.wound}）──")
    print("   坏源码：")
    for line in c.broken.splitlines():
        print(f"     | {line}")
    print(f"   要修到：{c.want}")
    r = replay(c)
    verds = {"passed": "🎓 回炉通过——这身肌肉还在。",
             "regressed": "⚠️ 回炉松了——改出来能启动，但 oracle 没过(修歪了)。",
             "cannot_fix": "❌ 回炉修不动了——招式库可能退化。",
             "source_lost": "⚠️ 赛题没了，无从回炉。"}
    print(f"\n   回炉：{verds.get(r['verdict'], r['verdict'])}")
    for t in r["trace"]:
        print(f"     · {t}")


def _record(results: list[dict]) -> None:
    """把整场回炉结论追加进流水账(写盘失败被吞，绝不反噬)。"""
    try:
        jsonlstore.append_jsonl(COURSE_LOG, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "patchcourse_replay_all",
            "ok": bool(results) and all(r["verdict"] == "passed" for r in results),
            "results": results,
        })
    except Exception:  # noqa: BLE001
        pass


# ── 自检 ────────────────────────────────────────────────────────────────
def _selfcheck() -> bool:
    """自检关键路径(供 evidence 复跑)：3 门课全抽得出、各挂对骨架，且 replay 至少一例通过。"""
    try:
        courses = extract()
        # ① 3 类已验收小修都抽得出来(对应活招式库的 3 招)
        assert len(courses) == len(_SKELETONS), \
            f"应抽 {len(_SKELETONS)} 门，实抽 {len(courses)} 门"
        ids = {c.id for c in courses}
        assert ids == set(_SKELETONS), f"课程号不齐：{ids}"
        # ② 每门课的骨架字段都长齐(不是空壳)
        for c in courses:
            assert c.trigger and c.locate and c.edit and c.guard and c.broken
        # ③ replay 验一例：补冒号那门课，丢回真 brain 必须修通且 oracle 过(肌肉还在)
        colon = _get(courses, "tactic_missing_colon")
        assert colon is not None
        r = replay(colon)
        assert r["verdict"] == "passed" and r["won"], f"补冒号回炉未通过：{r}"
        # ④ 全表回炉：每门都该通过(已验收的小修，如今仍修得通)
        all_r = replay_all()
        assert all_r and all(x["verdict"] == "passed" for x in all_r), \
            f"有课回炉没过：{[x for x in all_r if x['verdict'] != 'passed']}"
        # ⑤ 缺课能被认出来：抽一门不存在的课返回 None；source_lost 判得出
        assert _get(courses, "__no_such_course__") is None
        ghost = Course(id="__ghost__", name="x", emoji="?", trigger="t", locate="l",
                       edit="e", guard="g", wound="w", broken="x=1\n", want="w")
        assert replay(ghost)["verdict"] == "source_lost"
        # ⑥ summary 折叠不崩、通过率可算
        s = summary(courses)
        assert s["all_extracted"] and s["pass_rate"] == 1.0
        return True
    except Exception:  # noqa: BLE001
        return False


# ── CLI ─────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手补丁课程表 📒🖐️")
    ap.add_argument("--show", metavar="ID", help="摊开一门课(骨架 + 坏源码→修好样例)")
    ap.add_argument("--replay", metavar="ID", help="回炉一门：brain 如今仍修得通吗")
    ap.add_argument("--replay-all", action="store_true", help="全表回炉：哪几门还稳、哪门松了")
    ap.add_argument("--json", action="store_true", help="机读：课程表 + 回炉通过率")
    ap.add_argument("--selfcheck", action="store_true", help="自检关键路径不抛错(供 evidence 复跑)")
    ap.add_argument("--quiet", action="store_true", help="自检静默：只用退出码说话")
    args = ap.parse_args(argv)

    if args.selfcheck:
        ok = _selfcheck()
        if not args.quiet:
            print("📒🖐️  自检" + ("通过：3 门已验收小修都抽得出、骨架齐全，且回炉全过——肌肉还在。"
                                  if ok else "失败：课程抽取/回炉路径出问题了。"))
        sys.exit(0 if ok else 1)

    if args.json:
        courses = extract()
        out = {"summary": summary(courses),
               "courses": [c.to_dict() for c in courses],
               "replay": replay_all()}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if args.show:
        c = _get(extract(), args.show)
        if not c:
            print(f"📒  没找到课程 {args.show}。")
            sys.exit(1)
        _print_course(c)
        return

    if args.replay:
        c = _get(extract(), args.replay)
        if not c:
            print(f"📒  没找到课程 {args.replay}。")
            sys.exit(1)
        r = replay(c)
        verds = {"passed": "🎓 回炉通过——这身肌肉还在！",
                 "regressed": "⚠️ 回炉松了——能启动但 oracle 没过(修歪了)。",
                 "cannot_fix": "❌ 回炉修不动了——招式库可能退化。",
                 "source_lost": "⚠️ 赛题没了，无从回炉。"}
        print(f"📒  回炉 [{c.id}]（{c.name}）：{verds.get(r['verdict'], r['verdict'])}")
        for t in r["trace"]:
            print(f"     · {t}")
        sys.exit(0 if r["verdict"] == "passed" else 1)

    if args.replay_all:
        results = replay_all()
        _record(results)
        if not results:
            print("📒  课程表空着，没有可回炉的课。")
            sys.exit(1)
        passed = sum(1 for r in results if r["verdict"] == "passed")
        print(f"📒  全表回炉 {len(results)} 门课：通过 {passed} 门。")
        courses = {c.id: c for c in extract()}
        for r in results:
            c = courses.get(r["id"])
            tag = {"passed": "🎓", "regressed": "⚠️", "cannot_fix": "❌"}.get(r["verdict"], "⚠️")
            print(f"  {tag} [{r['id']}] {c.name if c else '?'} · {r['verdict']}")
        sys.exit(0 if passed == len(results) else 1)

    _print_table()


if __name__ == "__main__":
    main()
