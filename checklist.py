#!/usr/bin/env python3
"""自生手落爪前检查表 ✅🖐️ —— 改码前，把 readpack/moveset/handsdojo 的禁忌与边界汇成一页，看完再落爪。

为什么要有它：自生手已经长出三层各管一摊的认知，可它们各说各话、各在各的命令里——

  · `readpack.py` 围着下刀处汇**边界**：签名、调用方、契约红线、近邻测试。
  · `moveset.py`  撞上报错时荐**招**：哪一招真能对这段源码落地、实战可靠度多少。
  · `handsdojo.py` 把每次「修不动」封成**坑**：这道伤填没填平、还是个待还的死账。

三层都在，可 brain 真要落爪前，没有谁把它们**并到一张纸上**替它过一遍。于是同一个坑能
再摔一次（handsdojo 明明封过这道伤、还没填平，brain 照样盲修一遍）；明明无招可解，还在
自修上空耗一轮才降级；改了个有契约红线的目标，却没人在落爪前把那条线递到眼前。

本层就做那张「落爪前检查表」：给定一道要改的现场（哪个文件、什么源码、撞上什么异常、可选
的下刀目标），把三层的产出收成一串**检查项**，分三档：

  1) ⛔ **禁忌(blocking)**：劝退这一爪的硬信号。两条最要紧——
       · 同坑：handsdojo 里这道伤封过、且还没毕业（招式库没长新招）→ 盲修多半重蹈覆辙。
       · 无招可解：moveset 里没有招能对这段源码落地 → 自修白费，宜直接降级雇外援。
  2) ⚠️ **边界(boundary)**：不拦你落爪、但落爪时别越的线（契约红线 / 调用方 / 没有近邻测试兜着）。
  3) 💡 **提示(hint)**：助攻信息（首选招是哪招、同类坑曾封但已毕业可一试）。

汇总拿到一个 `Checklist`，`clear` 表态「有没有硬禁忌」（无禁忌才宜自己落爪）。和全家一脉相承：
零第三方依赖、纯标准库；检查表是参谋，三层里**任何一层读盘/解析失败都吞掉收敛成「这一节查不出」**，
绝不反噬动手主流程——给手递清单的层，自己绝不能成为新的伤口。

用法:
    python checklist.py              # 演示：给两类现场各过一页落爪前检查表
    python checklist.py --selfcheck  # 自检：同坑/无招两条禁忌判得准、边界/提示汇得对（供 evidence 复跑）
    python checklist.py --json       # 机读：检查表汇总的三档来源
    加 --quiet 静默，仅以退出码表态。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 三层认知都是「尽力而为」的参谋：缺席/出错都收敛成「这一节查不出」，绝不拖垮检查表
import handsdojo    # noqa: E402 —— 失败样本库：查「这道伤是不是个还没填平的旧坑」
import moveset      # noqa: E402 —— 招式库：查「撞上这报错，有没有招真能落地」
import readpack     # noqa: E402 —— 读码包：查「下刀处的契约/调用方/近邻测试边界」

KINDS = ("禁忌", "边界", "提示")
_MARK = {"禁忌": "⛔", "边界": "⚠️", "提示": "💡"}


@dataclasses.dataclass(frozen=True)
class CheckItem:
    """检查表上的一项：哪一档(禁忌/边界/提示)、出自哪层、一句人话、是否劝退落爪。"""
    kind: str           # "禁忌" | "边界" | "提示"
    source: str         # "handsdojo" | "moveset" | "readpack"
    text: str           # 一句人话：这一项在提醒什么
    blocking: bool      # 是不是该劝退这一爪的硬禁忌（只有禁忌档才可能为 True）

    def to_meta(self) -> dict:
        return {"kind": self.kind, "source": self.source,
                "text": self.text, "blocking": self.blocking}


@dataclasses.dataclass(frozen=True)
class Checklist:
    """落爪前过的一页清单：把 readpack/moveset/handsdojo 三层的禁忌与边界并到一处。"""
    ok: bool                    # 三层是否都顺利查完（不代表放行，只代表表没残）
    file: str                   # 要改的文件
    target: str | None          # 下刀目标（不给则略过读码边界一节）
    exc_type: str | None        # 撞上的异常类型（无异常则略过招/坑两节）
    items: list[CheckItem]      # 汇出的检查项（按禁忌→边界→提示排好）
    notes: list[str]            # 哪几节查不出（某层缺席/出错的留痕，不算检查项）

    @property
    def taboos(self) -> list[CheckItem]:
        return [i for i in self.items if i.kind == "禁忌"]

    @property
    def boundaries(self) -> list[CheckItem]:
        return [i for i in self.items if i.kind == "边界"]

    @property
    def hints(self) -> list[CheckItem]:
        return [i for i in self.items if i.kind == "提示"]

    @property
    def blockers(self) -> list[CheckItem]:
        """劝退这一爪的硬禁忌。"""
        return [i for i in self.items if i.blocking]

    @property
    def clear(self) -> bool:
        """没有硬禁忌 = 宜自己落爪（边界要守，但不拦手）。有禁忌则宜先排雷/降级。"""
        return not self.blockers

    def to_meta(self) -> dict:
        return {
            "ok": self.ok, "file": self.file, "target": self.target,
            "exc_type": self.exc_type, "clear": self.clear,
            "items": [i.to_meta() for i in self.items],
            "notes": list(self.notes),
        }


# ── 同坑：handsdojo 里这道伤是不是个还没填平的旧坑 ────────────────────────────
def _pit_items(file: str, exc_type: str | None,
               samples: list | None) -> tuple[list[CheckItem], list[str]]:
    """查失败样本库：这道伤(同文件 + 同异常类型)封过没、填平没。

    samples 给定则用它（自检注入用），不给则读真库（handsdojo.load() 自身永不抛，空库回 []）。
    匹配口径：同文件必须；exc_type 已知则还要同异常类型，未知(无异常)则只认同文件。
    · 有「还没毕业」的同坑 → ⛔ 禁忌：招式库没长新招，盲修多半重蹈覆辙。
    · 只有「已毕业」的同坑 → 💡 提示：招式库已长招，这类伤可一试。
    """
    items: list[CheckItem] = []
    notes: list[str] = []
    try:
        rows = handsdojo.load() if samples is None else samples
    except Exception:  # noqa: BLE001 —— 读库出任何错只当「这一节查不出」，绝不外溢
        return [], ["handsdojo 失败样本库读不出，同坑一节略过"]

    def hits(s) -> bool:
        if getattr(s, "file", None) != file:
            return False
        return exc_type is None or getattr(s, "exc_type", None) == exc_type

    matched = [s for s in rows if hits(s)]
    if not matched:
        return [], notes
    open_pits = [s for s in matched if not getattr(s, "solved", False)]
    solved_pits = [s for s in matched if getattr(s, "solved", False)]
    where = f"{file}" + (f" 上的 {exc_type}" if exc_type else "")
    if open_pits:
        ids = "、".join(s.id for s in open_pits[:3])
        items.append(CheckItem(
            "禁忌", "handsdojo",
            f"同坑：{where} 封过 {len(open_pits)} 道还没填平（{ids}）——招式库没长新招，"
            f"盲修多半重蹈覆辙；宜先 handsdojo --replay 看能否毕业、或补一招再落爪",
            blocking=True))
    elif solved_pits:
        items.append(CheckItem(
            "提示", "handsdojo",
            f"同类坑：{where} 曾封过 {len(solved_pits)} 道但都已毕业（招式库已长招）——这类伤可一试",
            blocking=False))
    return items, notes


# ── 招：moveset 里有没有招真能对这段源码落地 ──────────────────────────────────
def _move_items(src: str, exc: BaseException | None) -> tuple[list[CheckItem], list[str]]:
    """查招式库：撞上 exc，有没有招真能对 src 落地（产出候选且过补丁契约）。

    · 一招都使不上 → ⛔ 禁忌：自修白费，宜直接降级雇外援，别在自修上空耗一轮。
    · 有招使得上 → 💡 提示：首选招是哪招、凭什么（实战可靠度），落爪前就有谱。
    无异常(特性级改动，没有语法真伤)则这一节不适用，留一句 note。
    """
    if exc is None:
        return [], ["无异常(特性级改动)，招式库只治语法真伤，招/无招一节不适用"]
    try:
        sug = moveset.suggest(src, exc)
    except Exception:  # noqa: BLE001 —— 荐招出错只当「这一节查不出」
        return [], ["moveset 荐招出错，招一节略过"]

    if not sug:
        return [CheckItem(
            "禁忌", "moveset",
            f"无招可解：撞上 {type(exc).__name__}，招式库里没有招能对这段源码落地——"
            f"自修多半白费，宜直接降级雇外援，别耗在自修上",
            blocking=True)], []

    top = sug[0]
    items = [CheckItem("提示", "moveset",
                       f"首选招「{top.move_id}」：{top.rationale}", blocking=False)]
    if len(sug) > 1:
        rest = "、".join(s.move_id for s in sug[1:])
        items.append(CheckItem("提示", "moveset",
                               f"备选还有 {len(sug) - 1} 招：{rest}", blocking=False))
    return items, []


# ── 边界：readpack 围着下刀处汇的契约/调用方/近邻测试 ─────────────────────────
def _boundary_items(src: str, target: str | None,
                    module: str | None) -> tuple[list[CheckItem], list[str]]:
    """查读码包：下刀处的契约红线、调用方、近邻测试覆盖——落爪时别越的线。

    不给 target（如全文件级语法修复，没有单一下刀处）则这一节不适用，留一句 note。
    边界都是 ⚠️（提醒别越，但不拦手）：
      · 有契约 → 改签名前别跨入/出红线。
      · 有调用方 → 改语义会牵动按旧语义在用的它们。
      · 没有近邻测试覆盖 → 改完没有就近的网兜着，宜更谨慎。
    """
    if not target:
        return [], ["未指定下刀目标（全文件级修复无单一下刀处），读码边界一节略过"]
    try:
        p = readpack.pack(src, target, module=module)
    except Exception:  # noqa: BLE001 —— readpack 本就永不抛，这里再兜一层以防万一
        return [], [f"readpack 围读「{target}」出错，边界一节略过"]
    if not p.ok:
        return [], [f"读码边界查不出：{p.reason}"]

    items: list[CheckItem] = []
    if p.contract:
        items.append(CheckItem(
            "边界", "readpack",
            f"契约红线（{p.contract.module}）：入「{p.contract.inputs}」出「{p.contract.outputs}」"
            f"——改签名前别跨这条线", blocking=False))
    if p.callers:
        names = "、".join(c.caller for c in p.callers[:4])
        items.append(CheckItem(
            "边界", "readpack",
            f"有 {len(p.callers)} 个调用方按旧语义在用（{names}）——改语义会牵动它们", blocking=False))
    covering = [t for t in p.tests if t.covers_target]
    if not covering:
        items.append(CheckItem(
            "边界", "readpack",
            "下刀处无近邻测试正覆盖——改完没有就近的网兜着，宜更谨慎", blocking=False))
    else:
        items.append(CheckItem(
            "提示", "readpack",
            f"有 {len(covering)} 条近邻测试正覆盖此处——改完它们会立刻验你", blocking=False))
    return items, []


def _sort_key(item: CheckItem) -> tuple:
    """检查项排序：禁忌→边界→提示，同档内出禁忌的来源(handsdojo/moveset)先于读码。"""
    return (KINDS.index(item.kind), 0 if item.blocking else 1)


def assemble(*, file: str, src: str, exc: BaseException | None = None,
             target: str | None = None, module: str | None = None,
             samples: list | None = None) -> Checklist:
    """落爪前过一页检查表：把 readpack/moveset/handsdojo 的禁忌与边界并到一处。

    file/src：要改的文件名与源码。exc：撞上的异常（无则招/坑两节按「特性级改动」略过）。
    target/module：下刀目标与其所在模块名（不给则读码边界一节略过）。samples：注入失败样本
    （自检用，不给则读真库）。永不抛错——任何一层查不出都收敛成 note，绝不崩。
    """
    exc_type = type(exc).__name__ if exc is not None else None
    items: list[CheckItem] = []
    notes: list[str] = []

    for fn, args in (
        (_pit_items, (file, exc_type, samples)),
        (_move_items, (src, exc)),
        (_boundary_items, (src, target, module)),
    ):
        try:
            got, nt = fn(*args)
        except Exception as e:  # noqa: BLE001 —— 单层兜底再加一层，绝不让一节拖垮整表
            got, nt = [], [f"{fn.__name__} 出错({type(e).__name__})，该节略过"]
        items.extend(got)
        notes.extend(nt)

    items.sort(key=_sort_key)
    return Checklist(ok=True, file=file, target=target, exc_type=exc_type,
                     items=items, notes=notes)


def as_text(c: Checklist) -> str:
    """把检查表渲染成给手读的一页清单。"""
    where = c.file + (f"::{c.target}" if c.target else "")
    wound = f"撞上 {c.exc_type}" if c.exc_type else "特性级改动(无语法伤)"
    verdict = "✅ 无硬禁忌——宜自己落爪（守住下列边界）" if c.clear \
        else f"⛔ 有 {len(c.blockers)} 条禁忌——宜先排雷或直接降级，别硬落这一爪"
    lines = [f"✅🖐️ 落爪前检查表 ·「{where}」（{wound}）", f"  {verdict}", ""]
    for kind in KINDS:
        group = [i for i in c.items if i.kind == kind]
        if not group:
            continue
        lines.append(f"  {_MARK[kind]} {kind}（{len(group)}）")
        for i in group:
            lines.append(f"      · [{i.source}] {i.text}")
        lines.append("")
    if c.notes:
        lines.append("  📭 查不出的节（不计入禁忌/边界）：")
        for n in c.notes:
            lines.append(f"      · {n}")
    return "\n".join(lines).rstrip()


def manifest() -> dict:
    """机读：检查表汇总的三档来源（给 health / 外部消费）。"""
    return {
        "kinds": {
            "禁忌": "劝退这一爪的硬信号：同坑(handsdojo 未毕业旧伤) / 无招可解(moveset 无招落地)",
            "边界": "落爪别越的线：契约红线 / 调用方 / 没有近邻测试兜着(readpack)",
            "提示": "助攻信息：首选招(moveset) / 已毕业同类坑可一试(handsdojo) / 正覆盖的近邻测试",
        },
        "sources": ["handsdojo", "moveset", "readpack"],
        "verdict": "clear = 无硬禁忌才宜自己落爪；有禁忌宜先排雷或直接降级",
    }


# ── 自检：同坑/无招两条禁忌判得准，边界/提示汇得对 ──────────────────────────────
# 一份自给自足的样例源码：净价函数有契约(errors 模块在 contracts.py 立过约)、有调用方、有近邻样例。
# 围它过检查表能验读码边界一节；漏冒号/顶层 raise 两段源码分别验 moveset 的「有招/无招」两条路。
_SAMPLE_SRC = '''\
"""定价小工具(自检样例)。"""


def net_price(price, discount):
    """按折扣算净价。"""
    return price - discount


def receipt(price, discount):
    base = net_price(price, discount)
    return f"应付 {base}"


def _sample_net_price():
    assert net_price(100, 30) == 70
'''

_BROKEN_COLON = "def add(a, b)\n    return a + b\n"   # 漏冒号：moveset 有招可解
_DEAD_SRC = 'raise RuntimeError("无招可解")\n'           # 顶层 raise：谁都治不了


def _fake_sample(file: str, exc_type: str, *, solved: bool):
    """造一道注入用的失败样本（不写真库），用来验同坑禁忌/已毕业提示。"""
    return handsdojo.Sample(
        id=("solved-" if solved else "open-") + file, ts=1000.0, file=file,
        exc_type=exc_type, exc_msg="", lineno=0, reason="", trace=[],
        executor="claude", solved=solved)


def _selfcheck(quiet: bool = False) -> bool:
    """自检：同坑(未毕业)与无招两条禁忌判得准、已毕业同坑只给提示、读码边界汇得对、永不抛。

    全程纯内存：失败样本靠注入(不碰真库)，moveset/readpack 在隔离样例上跑。供 evidence 复跑。
    """
    import weaning_trial
    failures: list[str] = []

    colon_exc, _ = weaning_trial._self_test(_BROKEN_COLON)
    dead_exc, _ = weaning_trial._self_test(_DEAD_SRC)

    # ① 同坑禁忌：注入一道「未毕业」的同文件同异常旧伤 → 该出 ⛔ 禁忌且 clear=False
    open_pit = [_fake_sample("add.py", type(colon_exc).__name__, solved=False)]
    c1 = assemble(file="add.py", src=_BROKEN_COLON, exc=colon_exc, samples=open_pit)
    pit_taboos = [i for i in c1.taboos if i.source == "handsdojo"]
    if not pit_taboos or not pit_taboos[0].blocking:
        failures.append("未毕业同坑没被判成 ⛔ 禁忌")
    if c1.clear:
        failures.append("有未毕业同坑时 clear 仍为真——本该劝退这一爪")

    # ② 已毕业同坑：只该给 💡 提示，不该拦手（若无其他禁忌，clear 应为真）
    solved_pit = [_fake_sample("add.py", type(colon_exc).__name__, solved=True)]
    c2 = assemble(file="add.py", src=_BROKEN_COLON, exc=colon_exc, samples=solved_pit)
    if any(i.source == "handsdojo" and i.blocking for i in c2.items):
        failures.append("已毕业同坑不该被判成硬禁忌")
    if not any(i.source == "handsdojo" and i.kind == "提示" for i in c2.items):
        failures.append("已毕业同坑没给出 💡 提示")
    if not c2.clear:
        failures.append("只有已毕业同坑(且有招可解)时，clear 本该为真")

    # ③ 有招可解：漏冒号现场，moveset 该荐出首选招(💡 提示)
    if not any(i.source == "moveset" and i.kind == "提示" for i in c2.items):
        failures.append("漏冒号现场 moveset 没荐出首选招")

    # ④ 无招可解：顶层 raise，moveset 该出 ⛔ 禁忌且 clear=False（无同坑注入，禁忌只来自 moveset）
    c3 = assemble(file="x.py", src=_DEAD_SRC, exc=dead_exc, samples=[])
    move_taboos = [i for i in c3.taboos if i.source == "moveset"]
    if not move_taboos or not move_taboos[0].blocking:
        failures.append("无招可解的现场没被 moveset 判成 ⛔ 禁忌")
    if c3.clear:
        failures.append("无招可解时 clear 仍为真——本该劝退自修、直接降级")

    # ⑤ 读码边界：给 target=net_price(module=errors)，该汇出契约红线 + 调用方两条 ⚠️ 边界
    c4 = assemble(file="pricing.py", src=_SAMPLE_SRC, exc=None,
                  target="net_price", module="errors", samples=[])
    bsrc = {i.source for i in c4.boundaries}
    if "readpack" not in bsrc:
        failures.append("给了下刀目标却没汇出任何读码边界")
    texts = " ".join(i.text for i in c4.boundaries)
    if "契约红线" not in texts:
        failures.append("errors 模块明明有契约，边界里却没递出契约红线")
    if "调用方" not in texts:
        failures.append("net_price 明明有调用方 receipt，边界里却没递出调用方")
    # 无异常 → 招/坑两节该按「特性级改动」略过，留 note 而非凭空造禁忌
    if c4.taboos:
        failures.append("特性级改动(无异常)不该凭空冒出禁忌")
    if not any("特性级改动" in n for n in c4.notes):
        failures.append("无异常时没留下「招一节不适用」的 note")

    # ⑥ 不指定 target：读码边界一节该略过并留 note，不崩
    c5 = assemble(file="x.py", src=_BROKEN_COLON, exc=colon_exc, samples=[])
    if any(i.source == "readpack" and i.kind == "边界" for i in c5.items):
        failures.append("没给下刀目标却凭空汇出了读码边界")
    if not any("下刀目标" in n for n in c5.notes):
        failures.append("没给下刀目标时没留下略过读码边界的 note")

    # ⑦ 永不抛 + 可渲染：畸形输入也收敛成表，as_text 对任意表都出一页文字
    try:
        bad = assemble(file="b.py", src="def broken(:\n", exc=colon_exc, samples=[])
        if "落爪前检查表" not in as_text(bad) or "落爪前检查表" not in as_text(c1):
            failures.append("as_text 没能把检查表渲染成一页清单")
    except Exception as e:  # noqa: BLE001
        failures.append(f"assemble/as_text 竟抛了错 {type(e).__name__}: {e}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ checklist selfcheck：同坑/无招两条禁忌判得准、已毕业同坑只提示不拦手、"
                  "读码边界汇得对、特性级改动不凭空造禁忌——落爪前的检查表可信。")
        else:
            print("❌ checklist selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    import weaning_trial
    print("✅🖐️  自生手落爪前检查表 —— 给两类现场各过一页清单：\n")

    # 现场一：漏冒号 + 注入一道未毕业同坑 + 指定下刀目标，三档都现身
    colon_exc, _ = weaning_trial._self_test(_BROKEN_COLON)
    pit = [_fake_sample("pricing.py", type(colon_exc).__name__, solved=False)]
    c1 = assemble(file="pricing.py", src=_SAMPLE_SRC, exc=colon_exc,
                  target="net_price", module="errors", samples=pit)
    print(as_text(c1))
    print()

    # 现场二：顶层 raise，谁都治不了 → moveset 判无招可解的禁忌
    dead_exc, _ = weaning_trial._self_test(_DEAD_SRC)
    c2 = assemble(file="x.py", src=_DEAD_SRC, exc=dead_exc, samples=[])
    print(as_text(c2))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手落爪前检查表 ✅🖐️")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：同坑/无招两条禁忌判得准、边界/提示汇得对（供 evidence 复跑）")
    ap.add_argument("--json", action="store_true", help="机读：检查表汇总的三档来源")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if _selfcheck(quiet=args.quiet) else 1)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if not args.quiet:
        _demo()


if __name__ == "__main__":
    main()
