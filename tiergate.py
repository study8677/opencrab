#!/usr/bin/env python3
"""自生手升阶闸 🪜🚪 —— 把 brain-only 可接的活编成一架阶梯，凭真实证据判定此刻能登到第几级。

为什么要有它：`hands_immunity_drill.py` / `patchfitroom.py` 证明 brain **会拒坏补丁、改坏了能回滚**——
那是「不伤到自己」的底线。可底线之上还缺一个问题没人答：**「我此刻能安全接多难的活？」**
`weaning_trial.py`(语法真伤)、`purefix_trial.py`(纯函数小修)各自是一级真本事，但它们彼此孤立——
没有谁把它们排成「从易到难的阶梯」，更没有谁守着「下一级的资格，得拿下一级**还活着的证据**来换」。
于是 brain 要么畏手畏脚永远只敢补冒号，要么头脑一热去接它根本没练稳的活——两头都危险。

本层就是那道升阶闸：

  1) 🪜 **阶梯(LADDER)**：把可接的活由易到难排成三级，每级写明
       · 接什么活(accepts)、驱动力是什么(oracle_kind:异常 / 失败判据 / schema 兼容)
       · 「这级算掌握了」的证据来自哪条 evidence 声明(proven_by)——单一真相源,不另立宣言。
     T1 语法真伤   ← weaning_trial：报错指向下刀处,改一处让它能启动。
     T2 纯函数小修 ← purefix_trial：能跑但算错,凭失败的判据撞对那一处逻辑。
     T3 CLI 输出兼容改 ← 本层新立的顶级：改一处 CLI 代码、**保持对外 `--json` schema 向后兼容**——
                         驱动力既不是异常也不是单函数判据,而是 `compat.py` 那套「删键/改类型=破坏」的 schema 判据。

  2) 🚪 **升阶闸(clearance)**：读 `evidence.py` 折出的当前证据,给出**此刻的资格上限**——
     某级解锁,当且仅当它**及其以下每一级**的证据都还**新鲜**(🟢)。任一低级证据过期/失守/未证,
     资格当场跌回那道坎之下:「地基松了,先别去够更高的梁」。资格随证据涨落,不靠一次宣称定终身。

  3) ✅ **单补丁升阶判据(grade_compat_edit / accept)**：给 T3 落一把真尺子——
     拿「改前/改后」两份 CLI 源码,跑 `compat.shape`+`compat.diff` 看对外 schema 有没有被破坏(删键/改类型),
     **只新增键**才放行。再把改后源码当作针对真文件的补丁**真送进 `patchfitroom` 过闸**——
     证明一笔 T3 级的改动不只「schema 兼容」,还扛得住形状/语法/触觉/import 那几道针对真文件的闸,过了才落盘。

设计原则与全家一致:零第三方依赖、纯标准库;升阶闸是参谋/守门,读证据失败一律收敛成「保守降级」(资格判到最低),
绝不反噬动手主流程——给手定升阶资格的层,自己不能成为新的伤口。

用法:
    python tiergate.py                 # 打印阶梯三级 + 此刻的资格上限(凭真实证据)
    python tiergate.py --json          # 机读:阶梯 + 当前资格 + 各级证据态
    python tiergate.py --selfcheck     # 自检:阶梯成形 / 资格随证据单调 / 一例 T3 真补丁过 schema 判据+试衣间
    加 --quiet 静默,仅以退出码表态。
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import pathlib
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import compat   # noqa: E402 —— T3 的升阶判据复用兼容守门层:schema 取形/比对的单一真相源


# ── 阶梯:可接的活由易到难排成三级,每级证据来自哪条声明是单一真相源 ────────────────
@dataclasses.dataclass(frozen=True)
class Tier:
    """阶梯上的一级:接什么活、驱动力是什么、「算掌握了」的证据来自哪条 evidence 声明。"""
    level: int                    # 级数(1 最易,数越大越难)
    name: str                     # 这级的名字(人话)
    accepts: str                  # 一句话:这级能接什么活
    oracle_kind: str              # 驱动力:撞对那一处靠什么信号
    proven_by: tuple[str, ...]    # evidence 声明名:这级「已掌握」的证据从哪来(全 🟢 才算这级稳)
    example: str                  # 一句 worked example:这级的活长什么样

    def to_meta(self) -> dict:
        return {"level": self.level, "name": self.name, "accepts": self.accepts,
                "oracle_kind": self.oracle_kind, "proven_by": list(self.proven_by),
                "example": self.example}


LADDER: list[Tier] = [
    Tier(
        level=1,
        name="语法真伤",
        accepts="编译/加载就崩的语法伤:补冒号 / 括号 print / 名字纠偏——改一处让它能启动",
        oracle_kind="异常(报错本身指向下刀处)",
        proven_by=("weaning_trial",),
        example="def add(a, b)  ← 漏冒号,SyntaxError 直指那一行",
    ),
    Tier(
        level=2,
        name="纯函数小修",
        accepts="能编译能跑但算错的纯函数:差一/去空白/边界——凭失败的判据撞对那一处逻辑",
        oracle_kind="失败的判据(一组输入→期望输出)",
        proven_by=("purefix_trial",),
        example="valid_port 把合法的 65535 误判非法(< 写成该是 <=)",
    ),
    Tier(
        level=3,
        name="CLI 输出兼容改",
        accepts="改一处 CLI 代码,且保持对外 `--json` schema 向后兼容(只新增键、不删键/改类型)",
        oracle_kind="schema 兼容判据(compat:删键/改类型=破坏,新增键=兼容)",
        proven_by=("tiergate",),   # 本层自检证明这级的活能过 schema 判据 + 试衣间,即「这级可达」
        example="给某命令 `--json` 输出补一个新字段——下游照旧取得到老字段,才算兼容",
    ),
]


# ── 升阶闸:读 evidence 折出的证据,给出此刻的资格上限 ──────────────────────────
@dataclasses.dataclass(frozen=True)
class Clearance:
    """此刻 brain 能安全接到第几级的裁决。"""
    ceiling: int                  # 资格上限级数(0 = 连最易那级都没证据撑着)
    ceiling_tier: Tier | None     # 上限对应那一级(0 时为 None)
    blocked_at: Tier | None       # 第一道够不着的坎(资格已封顶则为 None)
    missing: tuple[str, ...]      # 卡住那道坎的、证据不新鲜的声明名
    fresh: tuple[str, ...]        # 当前判定时认作「新鲜」的声明名(便于账本翻查)

    def to_meta(self) -> dict:
        return {"ceiling": self.ceiling,
                "ceiling_tier": self.ceiling_tier.name if self.ceiling_tier else None,
                "blocked_at": self.blocked_at.name if self.blocked_at else None,
                "missing": list(self.missing), "fresh": list(self.fresh)}


def _fresh_claim_names() -> set[str]:
    """从 evidence 折出当前**新鲜(🟢)**的声明名集合。读不到一律回空——保守降级,绝不臆测谁稳。"""
    try:
        import evidence
        return {s.name for s in evidence.status() if s.settled}
    except Exception:  # noqa: BLE001 —— 升阶闸是守门者,读证据崩了只当「啥都没证」,资格判到最低
        return set()


def clearance(fresh: set[str] | None = None) -> Clearance:
    """凭新鲜证据判此刻的资格上限:某级解锁 ⟺ 它及以下每一级的 proven_by 都还新鲜。

    从最易一级往上走,一旦某级的证据不全新鲜就停——资格封在它之下那一级。
    fresh 缺省时自动从 evidence 取;传入显式集合便于自检确定性地造各种证据态。永不抛错。
    """
    names = _fresh_claim_names() if fresh is None else set(fresh)
    ceiling = 0
    ceiling_tier: Tier | None = None
    for tier in sorted(LADDER, key=lambda t: t.level):
        missing = tuple(c for c in tier.proven_by if c not in names)
        if missing:
            return Clearance(ceiling, ceiling_tier, tier, missing, tuple(sorted(names)))
        ceiling, ceiling_tier = tier.level, tier
    return Clearance(ceiling, ceiling_tier, None, (), tuple(sorted(names)))


# ── T3 的升阶判据:一笔「CLI 输出兼容改」过 schema 兼容 + 真送试衣间 ────────────────
@dataclasses.dataclass(frozen=True)
class Verdict:
    """一笔 T3 改动的升阶裁决:对外 schema 破没破、试衣间收没收。"""
    accepted: bool                # 兼容(无破坏)且过了试衣间,才算这笔 T3 改动可接
    breaks: list[dict]            # compat 判出的破坏(删键/改类型);空 = schema 兼容
    adds: list[dict]              # 向后兼容的新增键
    fit_written: bool             # 改后源码当补丁,真送 patchfitroom 过没过闸写回
    detail: str                   # 一句现场

    def to_meta(self) -> dict:
        return {"accepted": self.accepted, "breaks": self.breaks, "adds": self.adds,
                "fit_written": self.fit_written, "detail": self.detail}


def _json_shape(src: str, *, fname: str = "report") -> object:
    """exec 一份 CLI 源码、取出 fname() 的返回值(它就是该命令 `--json` 吐的对象),抽成 schema 骨架。

    跑的是自检里自造的隔离纯函数,无外部输入;stdout 重定向掉别污染战报。解析/调用崩了抛给上层判没过。
    ns 预置非 "__main__" 的 __name__:源码里的 `if __name__ == "__main__"` 守卫据此为假,
    main() 不会被触发(等同「模块被 import 而非当主程序跑」),也不会因裸 ns 缺 __name__ 抛 NameError。
    """
    ns: dict = {"__name__": "tiergate-cli"}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(src, "<tiergate-cli>", "exec"), ns)  # noqa: S102 —— 隔离自造源码
    fn = ns.get(fname)
    if not callable(fn):
        raise ValueError(f"源码里没有可调用的 {fname}()")
    return compat.shape(fn())


def grade_compat_edit(before: str, after: str, *, fname: str = "report") -> tuple[list[dict], list[dict]]:
    """T3 的 schema 兼容尺子:拿改前/改后两份 CLI 源码的 `--json` 骨架对照,返回 (破坏, 新增)。

    复用 compat 的取形/比对:删键、改类型、标量↔容器互换 = 破坏(下游会崩);多一个键 = 向后兼容的新增。
    """
    base, cur = _json_shape(before, fname=fname), _json_shape(after, fname=fname)
    changes = compat.diff(base, cur)
    breaks = [c for c in changes if c["kind"] == "break"]
    adds = [c for c in changes if c["kind"] == "add"]
    return breaks, adds


def _through_fitroom(before: str, after: str) -> tuple[bool, str]:
    """把 before→after 这笔 CLI 改动当作针对真文件的补丁,送进 patchfitroom 过闸。

    在隔离临时仓库里跑,绝不碰真仓库;无 contracts.py 故跳过契约闸,验形状/语法/触觉/import 四闸。
    patchfitroom 缺席/出意外都收敛为「没过」,绝不反噬。
    """
    try:
        import patchfitroom
    except Exception as e:  # noqa: BLE001
        return False, f"patchfitroom 缺席({type(e).__name__}),跳过试衣间这一验"
    try:
        with tempfile.TemporaryDirectory(prefix="tiergate-") as d:
            dp = pathlib.Path(d)
            target = dp / "cli_sample.py"
            target.write_text(before, encoding="utf-8")
            r = patchfitroom.fit(target, after, repo=dp, check_contracts=False)
            return r.written, r.detail
    except Exception as e:  # noqa: BLE001
        return False, f"送试衣间时出意外:{type(e).__name__}: {e}"


def accept(before: str, after: str, *, fname: str = "report") -> Verdict:
    """T3 升阶闸:一笔「CLI 输出兼容改」可接 ⟺ 对外 schema 无破坏(只许新增键) **且** 改后源码过试衣间。

    两道都过才收:schema 判据守「下游取得到老字段」,试衣间守「这笔改动落到真文件也不割伤身体」。
    """
    try:
        breaks, adds = grade_compat_edit(before, after, fname=fname)
    except Exception as e:  # noqa: BLE001 —— 源码跑不起来/取不到输出:当作不可接,不硬塞
        return Verdict(False, [], [], False, f"取 schema 失败,保守拒收:{type(e).__name__}: {e}")
    if breaks:
        paths = "、".join(c["path"] for c in breaks)
        return Verdict(False, breaks, adds, False, f"对外 schema 被破坏(删键/改类型):{paths}——下游会崩,拒")
    written, fit_detail = _through_fitroom(before, after)
    if not written:
        return Verdict(False, breaks, adds, False, f"schema 兼容,但没过试衣间:{fit_detail}")
    note = f"新增 {len(adds)} 个键(向后兼容)" if adds else "形状一字未动"
    return Verdict(True, breaks, adds, True, f"schema 兼容（{note}）且过了试衣间 → 这笔 T3 改动可接")


# ── T3 的 worked example:一个最小 CLI + 一笔兼容改 / 一笔破坏改 ─────────────────────
# 一个最小命令:report() 即它 `--json` 吐的对象,main() 把它打出来。改它的输出来验升阶判据。
_CLI_BEFORE = (
    "import json\n"
    "import sys\n"
    "\n"
    "def report():\n"
    '    return {"name": "demo", "count": 3}\n'
    "\n"
    "def main():\n"
    "    print(json.dumps(report()))\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    main()\n"
)

# 兼容改:给输出补一个新字段 ok(老调用方照旧取得到 name/count)——只新增键,向后兼容。
_CLI_COMPATIBLE = _CLI_BEFORE.replace(
    '    return {"name": "demo", "count": 3}\n',
    '    return {"name": "demo", "count": 3, "ok": True}\n',
)

# 破坏改:把 count 改名成 total(老调用方取 count 会 KeyError)——删键,schema 破坏,该被拒。
_CLI_BREAKING = _CLI_BEFORE.replace(
    '    return {"name": "demo", "count": 3}\n',
    '    return {"name": "demo", "total": 3}\n',
)


def manifest() -> dict:
    """机读:阶梯 + 此刻资格上限 + 各级证据态(给 health / 外部消费)。"""
    cl = clearance()
    return {"ladder": [t.to_meta() for t in LADDER], "clearance": cl.to_meta()}


# ── 自检 ─────────────────────────────────────────────────────────────
def selfcheck(quiet: bool = False) -> bool:
    """自检:阶梯成形 / 资格随证据单调升降 / 一例 T3 真补丁过 schema 判据 + 试衣间 / 破坏改被拒。

    全程纯内存(资格用显式注入的证据态算、T3 例在隔离临时仓库里过试衣间),确定性、无副作用。供 evidence 复跑。
    """
    failures: list[str] = []

    # 1) 阶梯成形:级数从 1 连续递增,每级名字/接什么活/证据来源都非空
    levels = [t.level for t in LADDER]
    if levels != list(range(1, len(LADDER) + 1)):
        failures.append(f"阶梯级数该是 1..N 连续,实得 {levels}")
    for t in LADDER:
        if not (t.name and t.accepts and t.proven_by):
            failures.append(f"第 {t.level} 级卡面不全(名字/接什么活/证据来源有空)")

    all_claims = {c for t in LADDER for c in t.proven_by}

    # 2) 资格单调:全证据新鲜 → 资格登顶;抽掉中间一级(T2)的证据 → 资格跌回它之下(到 T1)
    top = clearance(fresh=all_claims)
    if top.ceiling != len(LADDER):
        failures.append(f"证据全新鲜时资格该登顶({len(LADDER)}),实得 {top.ceiling}")
    drop = clearance(fresh=all_claims - {"purefix_trial"})
    if drop.ceiling != 1:
        failures.append(f"抽掉 T2 证据,资格该跌回 T1(1),实得 {drop.ceiling}")
    if drop.blocked_at is None or drop.blocked_at.level != 2:
        failures.append("抽掉 T2 证据,该点名卡在第 2 级这道坎")
    if "purefix_trial" not in drop.missing:
        failures.append(f"卡住 T2 的缺证该点名 purefix_trial,实得 {drop.missing}")
    # 地基(T1)塌了 → 连最易那级都够不着,资格为 0
    none = clearance(fresh=set())
    if none.ceiling != 0:
        failures.append(f"无任何新鲜证据时资格该为 0,实得 {none.ceiling}")

    # 3) T3 一例兼容改:过 schema 判据(只新增、无破坏) 且 真过试衣间——这就是「跑一例试衣验收」
    v = accept(_CLI_BEFORE, _CLI_COMPATIBLE)
    if not v.accepted:
        failures.append(f"T3 兼容改(补 ok 字段)该可接,实得拒:{v.detail}")
    if v.breaks:
        failures.append(f"T3 兼容改不该判出 schema 破坏,实得 {v.breaks}")
    if not any(c["path"] == "ok" for c in v.adds):
        failures.append(f"T3 兼容改该判出新增键 ok,实得 {v.adds}")
    if not v.fit_written:
        failures.append("T3 兼容改该真过试衣间写回,实得没过")

    # 4) T3 一例破坏改:删键(count→total) → schema 判出破坏,升阶闸当场拒、绝不送试衣间
    vb = accept(_CLI_BEFORE, _CLI_BREAKING)
    if vb.accepted:
        failures.append("T3 破坏改(count 改名 total)该被拒,实得可接——升阶闸漏了 schema 破坏")
    if not vb.breaks:
        failures.append("T3 破坏改该判出 schema 破坏(删了 count),实得没判出")
    if vb.fit_written:
        failures.append("T3 破坏改 schema 已破,不该再送试衣间写回")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ tiergate selfcheck：阶梯三级成形、资格随证据单调升降、一例 T3 兼容改过 schema 判据 + 试衣间、"
                  "破坏改被当场拒——升阶闸可信。")
        else:
            print("❌ tiergate selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 展示 ─────────────────────────────────────────────────────────────
def _print_ladder() -> None:
    cl = clearance()
    print("🪜🚪 自生手升阶闸 —— brain-only 可接的活,由易到难排成阶梯,凭真实证据定资格：\n")
    for t in LADDER:
        reachable = t.level <= cl.ceiling
        mark = "🟢 已解锁" if reachable else "🔒 未解锁"
        print(f"  T{t.level} {t.name}（{mark}）")
        print(f"      接什么活：{t.accepts}")
        print(f"      驱动力  ：{t.oracle_kind}")
        print(f"      证据来自：{'、'.join(t.proven_by)}")
        print(f"      例：{t.example}")
    if cl.ceiling_tier:
        print(f"\n  此刻资格上限：T{cl.ceiling}「{cl.ceiling_tier.name}」"
              "——它及以下每一级的证据都还新鲜。")
    else:
        print("\n  此刻资格上限：T0 —— 连最易那级的证据都不新鲜，先把地基验回来。")
    if cl.blocked_at:
        print(f"  够不着的坎：T{cl.blocked_at.level}「{cl.blocked_at.name}」,"
              f"卡在证据不足：{'、'.join(cl.missing)}（跑 `python evidence.py --verify` 补证）")
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手升阶闸 🪜🚪")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检:阶梯成形 / 资格随证据单调 / 一例 T3 真补丁过 schema 判据 + 试衣间(供 evidence 复跑)")
    ap.add_argument("--json", action="store_true", help="机读:阶梯 + 当前资格 + 各级证据态")
    ap.add_argument("--quiet", action="store_true", help="静默,仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)
    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return
    if not args.quiet:
        _print_ladder()


if __name__ == "__main__":
    main()
