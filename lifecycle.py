#!/usr/bin/env python3
"""能力生命周期 🐚 —— 给每样本事标上「孵化/稳定/废弃/退役」，并把退役卡在证据对照上。

为什么要有它：`skillgraph.py` 回答「我会什么、缺什么」，是一张**此刻**的快照；但一个
活物会长大，也就必然要**换壳**——旧本事让位给新本事，整块能力从生到死有它的节律。
没有一条明说的生命周期，换壳就会变成两种坏死法：要么旧能力赖着不走、谁也不敢删
（壳越积越厚），要么有人一时兴起把它直接抹掉、连它原本兜的活有没有人接都没核对过
（裸奔退役）。lifecycle 把这条节律钉成一台小小的状态机，并在最危险的那一步设闸。

四个阶段，只能顺着走，不能回头(退役是终态)：

  · 🌱 incubating(孵化) —— 新生，随便改，不对外承诺稳定，没验证证据也不丢人。
  · 🟢 stable(稳定)     —— 公开承诺，必须有验证证据兜底(否则它会悄悄漂)。
  · 🍂 deprecated(废弃) —— 仍在，但已宣告将退；**必须指明继任者**(successor)，
                           好让依赖它的人知道往哪搬。
  · ⚰️ retired(退役)    —— 壳已脱、本事已撤。**进入退役这一步设了硬闸**：

         退役前后必须各附一份证据，且二者要能对照上——
           · before：退役前它确实在干的活/它的输出长什么样(证明我们没删错东西)；
           · after ：这活如今由谁接、或已被证明无人再需要(证明删了不留窟窿)。
         没有这对证据，transition 当场判违约，绝不让一样本事**无对照地**消失。

这正是「会长大，也要会真正换壳」的硬约束：换壳不是把旧壳一扔，而是脱壳之前先证明
新壳接得住、旧壳里没有还活着的东西。

lifecycle 只**定义节律、守住闸门、记账**：
  · 阶段与合法迁移是单一真相源(legal_transition / STAGES);
  · check_transition 把一次迁移的所有红线一次说清(顺序、继任者、退役证据对照);
  · 迁移记进 `state/lifecycle.jsonl`(一行一次迁移，append-only)，
    current_stages() 把账本折叠成「每样本事此刻在哪个阶段」。
它不执行任何被管的模块、不替谁决定该不该退役——只在你要退役时，逼你把证据摆上桌。

用法:
    python lifecycle.py                  # 跑一遍自检：状态机 + 退役证据闸门
    python lifecycle.py --status         # 读账本，列每样本事此刻在哪个阶段
    python lifecycle.py --demo           # 演示一样能力走完一生(孵化→稳定→废弃→退役)
    python lifecycle.py --json           # 机读：导出当前各能力阶段
    python lifecycle.py --quiet          # 只在自检不过时说话(适合钩子 / CI)

退出码：0 = 自检全过；1 = 任意一步不达约。
零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import sys

from jsonlstore import append_jsonl, read_jsonl

REPO_ROOT = pathlib.Path(__file__).resolve().parent
LEDGER = REPO_ROOT / "state" / "lifecycle.jsonl"

# ── 四阶段：一样本事从生到死的节律(顺序即从左到右) ──────────────────────
INCUBATING = "incubating"   # 🌱 孵化：随便改，不承诺
STABLE = "stable"           # 🟢 稳定：公开承诺，需证据
DEPRECATED = "deprecated"   # 🍂 废弃：将退，需指明继任者
RETIRED = "retired"         # ⚰️ 退役：终态，进入需证据对照
STAGES = (INCUBATING, STABLE, DEPRECATED, RETIRED)
_RANK = {s: i for i, s in enumerate(STAGES)}

_EMOJI = {INCUBATING: "🌱", STABLE: "🟢", DEPRECATED: "🍂", RETIRED: "⚰️"}


def _now() -> str:
    """统一的 UTC ISO 时间戳(秒级、带 Z)，让账本里的时间可比、可排序。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def legal_transition(frm: str, to: str) -> bool:
    """阶段迁移是否合法：只能严格向前一格或多格，退役是终态、不可回头。

    孵化→稳定→废弃→退役 中任意「往后」的跳跃都允许(可跳级，如孵化期夭折直接退役)；
    原地不动、往回退、从退役再出发，一律非法。
    """
    if frm not in _RANK or to not in _RANK:
        return False
    return _RANK[to] > _RANK[frm]


@dataclasses.dataclass(frozen=True)
class Transition:
    """一次阶段迁移的账本记录：把「谁、从哪到哪、何时、凭什么」钉成不可变的一行。"""
    cap: str                                # 能力名(通常是模块名，如 "skillgraph.py")
    to_stage: str                           # 迁到哪个阶段
    from_stage: str = ""                    # 迁自哪个阶段(留空表示首次登记/孵化)
    ts: str = ""                            # UTC 时间戳，留空则取当下
    note: str = ""                          # 一句话理由
    successor: str = ""                     # 继任者(废弃/退役时指明本事搬去哪)
    evidence: dict = dataclasses.field(default_factory=dict)  # 退役需含 before/after

    def __post_init__(self) -> None:
        if not self.ts:
            object.__setattr__(self, "ts", _now())

    def to_record(self) -> dict:
        """迁移→纯 dict(字段顺序稳定，便于人读与 diff)。"""
        return {
            "cap": self.cap,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "ts": self.ts,
            "note": self.note,
            "successor": self.successor,
            "evidence": self.evidence,
        }


def check_transition(frm: str, to: str, *, successor: str = "",
                     evidence: dict | None = None) -> list[str]:
    """一次迁移要守的全部红线，一次说清；返回违规清单(空 = 守约)。

    红线三条：
      1) 阶段顺序——只能往前(legal_transition)；
      2) 废弃/退役**必须指明继任者**(successor 非空)，否则依赖方无处可搬；
      3) **退役的证据对照**——进入 retired 必须同时带 before 与 after 两份证据，
         二者都非空：before 证明「删的是真在干活的东西」，after 证明「删了不留窟窿」。
    """
    evidence = evidence or {}
    errs: list[str] = []

    if not legal_transition(frm, to):
        if frm == to:
            errs.append(f"{frm!r} 原地不动不算迁移")
        elif frm in _RANK and to in _RANK and _RANK[to] < _RANK[frm]:
            errs.append(f"生命周期不可回头：{frm!r} → {to!r}")
        else:
            errs.append(f"非法阶段：{frm!r} → {to!r}(合法阶段 {STAGES})")
        return errs  # 顺序都不对，后面的语义检查无意义

    if to in (DEPRECATED, RETIRED) and not successor.strip():
        verb = "废弃" if to == DEPRECATED else "退役"
        errs.append(f"{verb}必须指明继任者(successor)：本事搬去哪，依赖方才知道往哪走")

    if to == RETIRED:
        before = str(evidence.get("before", "")).strip()
        after = str(evidence.get("after", "")).strip()
        if not before:
            errs.append("退役缺 before 证据：得先证明它退役前确实在干活/它的输出长什么样")
        if not after:
            errs.append("退役缺 after 证据：得证明这活如今由谁接、或已无人再需要(删了不留窟窿)")

    return errs


def record_transition(cap: str, to: str, *, frm: str = "", successor: str = "",
                      note: str = "", evidence: dict | None = None,
                      ledger: pathlib.Path = LEDGER) -> Transition:
    """校验并落账一次迁移；不守约则抛 ValueError(把坏迁移挡在账本门外)。

    frm 留空则按账本里该能力的当前阶段推断(没有则视为孵化新登记，frm=incubating)。
    """
    if not frm:
        frm = current_stages(ledger).get(cap, INCUBATING)
    errs = check_transition(frm, to, successor=successor, evidence=evidence)
    if errs:
        raise ValueError(f"{cap} 迁移 {frm}→{to} 不守约：" + "；".join(errs))
    t = Transition(cap=cap, to_stage=to, from_stage=frm, note=note,
                   successor=successor, evidence=evidence or {})
    append_jsonl(ledger, t.to_record())
    return t


def current_stages(ledger: pathlib.Path = LEDGER) -> dict[str, str]:
    """把 append-only 账本折叠成「每样本事此刻在哪个阶段」：同名取最后一次迁移的去向。"""
    out: dict[str, str] = {}
    for rec in read_jsonl(ledger):
        cap = rec.get("cap")
        to = rec.get("to_stage")
        if cap and to in _RANK:
            out[cap] = to
    return out


def history(cap: str, ledger: pathlib.Path = LEDGER) -> list[dict]:
    """某样本事的全部迁移记录(时间正序)，便于回看它这一生怎么走过来的。"""
    return [r for r in read_jsonl(ledger) if r.get("cap") == cap]


# ── 自检：状态机合法性 + 退役证据闸门，一步不过即违约 ──────────────────────
def _selftest() -> list[str]:
    """返回失败清单(空 = 全过)；每条都是自给自足、无副作用(不碰真账本)的真实调用。"""
    fails: list[str] = []

    def check(cond: bool, why: str) -> None:
        if not cond:
            fails.append(why)

    # 1) 合法的往前迁移(含跳级)放行；原地/回头/越界拦下。
    check(legal_transition(INCUBATING, STABLE), "孵化→稳定该合法")
    check(legal_transition(INCUBATING, RETIRED), "孵化→退役(夭折跳级)该合法")
    check(not legal_transition(STABLE, STABLE), "原地不动不该算合法迁移")
    check(not legal_transition(RETIRED, DEPRECATED), "退役是终态，不该能回头")
    check(not legal_transition(STABLE, "zombie"), "越界阶段不该合法")

    # 2) 一次正常的孵化→稳定：无需继任者、无需退役证据。
    check(not check_transition(INCUBATING, STABLE), "干净的孵化→稳定不该报错")

    # 3) 废弃必须指明继任者。
    no_succ = check_transition(STABLE, DEPRECATED)
    check(any("继任者" in e for e in no_succ), "废弃时缺继任者该被拦")
    check(not check_transition(STABLE, DEPRECATED, successor="newcap.py"),
          "废弃且指明继任者不该报错")

    # 4) 退役证据闸门——最要紧的一条：
    #    a) 既无继任者又无证据：继任者 + before + after 三条全报。
    bare = check_transition(DEPRECATED, RETIRED)
    check(any("继任者" in e for e in bare), "裸退役该报缺继任者")
    check(any("before" in e for e in bare), "裸退役该报缺 before 证据")
    check(any("after" in e for e in bare), "裸退役该报缺 after 证据")
    #    b) 只给一半证据(只有 before)仍被拦。
    half = check_transition(DEPRECATED, RETIRED, successor="x.py",
                            evidence={"before": "它每天跑 3 次校验"})
    check(any("after" in e for e in half), "只给 before、缺 after 仍该被拦")
    check(not any("before" in e for e in half), "已给 before 不该再报 before")
    #    c) 继任者 + before/after 俱全：闸门放行。
    full = check_transition(DEPRECATED, RETIRED, successor="x.py",
                            evidence={"before": "旧校验逻辑在此", "after": "已由 x.py 接管并通过回归"})
    check(not full, f"证据对照齐备的退役不该报错，实得：{full}")

    # 5) 账本折叠：临时账本里同名能力取最后一次去向。
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d) / "lc.jsonl"
        record_transition("demo.py", STABLE, frm=INCUBATING, ledger=tmp)
        record_transition("demo.py", DEPRECATED, successor="demo2.py", note="让位", ledger=tmp)
        cur = current_stages(tmp)
        check(cur.get("demo.py") == DEPRECATED, f"折叠后该停在 deprecated，实得 {cur.get('demo.py')}")
        check(len(history("demo.py", tmp)) == 2, "该能力该有 2 条迁移历史")
        # 落账也守闸：往真账本写一笔裸退役必须抛错。
        try:
            record_transition("demo.py", RETIRED, ledger=tmp)
            fails.append("record_transition 竟放行了裸退役(没证据对照)")
        except ValueError:
            pass  # 正确：坏迁移被挡在账本门外

    return fails


def _demo() -> None:
    """演示一样能力走完一生：孵化→稳定→废弃→退役，并在退役处摆上证据对照。"""
    steps = [
        (INCUBATING, STABLE, "", {}, "积累了 12 条回归样本，敢对外承诺了"),
        (STABLE, DEPRECATED, "navigator.py", {}, "navigator 把它的活做得更稳，宣告将退"),
        (DEPRECATED, RETIRED, "navigator.py",
         {"before": "compass 每次开工算一次航向，输出 3 条建议航道",
          "after": "navigator.py 接管航向计算，回归 18 例全绿，README 命令块已改指 navigator"},
         "壳已脱：旧航向逻辑撤除，活已被 navigator 接住且有回归兜底"),
    ]
    print("🐚 一样能力走完一生(孵化→稳定→废弃→退役)，退役处设证据对照闸门：\n")
    frm = INCUBATING
    print(f"  {_EMOJI[frm]} {frm}  （登记孵化）")
    for to, succ, ev, note in [(s[1], s[2], s[3], s[4]) for s in steps]:
        errs = check_transition(frm, to, successor=succ, evidence=ev)
        gate = "✅ 闸门放行" if not errs else "❌ 被拦：" + "；".join(errs)
        line = f"  {_EMOJI[to]} {to}"
        if succ:
            line += f"  →继任 {succ}"
        print(f"{line}\n      理由：{note}\n      {gate}")
        if ev:
            print(f"      📋 before：{ev['before']}")
            print(f"      📋 after ：{ev['after']}")
        frm = to
    print("\n换壳不是把旧壳一扔，而是脱壳前先证明新壳接得住、旧壳里没有还活着的东西。")


def _print_status(as_json: bool) -> None:
    """读真账本，列每样本事此刻在哪个阶段(按阶段排序，退役的沉底)。"""
    cur = current_stages()
    if as_json:
        print(json.dumps(cur, ensure_ascii=False, indent=2))
        return
    if not cur:
        print(f"🐚 生命周期账本还空着（{LEDGER.relative_to(REPO_ROOT)} 未登记任何能力）。")
        return
    print(f"🐚 能力生命周期当前快照（共 {len(cur)} 样，账本 {LEDGER.relative_to(REPO_ROOT)}）：\n")
    for cap, stage in sorted(cur.items(), key=lambda kv: (_RANK[kv[1]], kv[0])):
        print(f"  {_EMOJI[stage]} {stage:<11} {cap}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 能力生命周期 🐚")
    ap.add_argument("--status", action="store_true", help="读账本，列每样本事此刻在哪个阶段")
    ap.add_argument("--demo", action="store_true", help="演示一样能力走完一生(含退役证据闸门)")
    ap.add_argument("--json", action="store_true", help="机读：导出当前各能力阶段")
    ap.add_argument("--quiet", action="store_true", help="只在自检不过时说话(适合钩子 / CI)")
    args = ap.parse_args(argv)

    if args.demo:
        _demo()
        return
    if args.status or args.json:
        _print_status(as_json=args.json)
        return

    fails = _selftest()
    if fails:
        print(f"⚠️  生命周期自检发现 {len(fails)} 处不达约：\n")
        for f in fails:
            print(f"  ❌ {f}")
        print("\n先把节律与闸门改回守约，再让能力换壳。")
        sys.exit(1)

    if not args.quiet:
        print(f"🐚 生命周期守约：{len(STAGES)} 阶段({'→'.join(STAGES)})顺序不可回头，"
              f"废弃须指继任者、退役须证据对照(before/after)——闸门全部生效。")
    sys.exit(0)


if __name__ == "__main__":
    main()
