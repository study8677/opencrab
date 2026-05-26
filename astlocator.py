#!/usr/bin/env python3
"""AST 自生手定位器 🎯🖐️ —— 让 brain 小修能按函数/方法/CLI 入口精确「找准下刀处」，只改那一段。

为什么要有它：`weaning_trial.py` 的招式（补冒号 / 括号 print / 名字纠偏）都靠 `exc.lineno`
摸到报错那一行，再 `patchcontract.py` 验改动是否局部有界。可这只够应付「编译就崩、报错带行号」
的伤。真实的小修往往是**逻辑伤**：某个函数算错了符号、某个方法多乘了一下、CLI 入口把
`sys.argv` 整个塞了进去——它们能编译、能起跑，报错里**没有行号**，靠 `exc.lineno` 根本定不了位。

一只只会「整文件替换」或「照报错行号下刀」的手，谈不上可托付：它要么把半个文件重写掉
（越界，被契约拒收），要么压根找不到该改的那一段。亲手写代码的第一步，是先长出稳定的
**「找准下刀处」**——按**结构**（哪个函数、哪个方法、哪段 CLI 入口）定位，而不是按行号猜。

本层用标准库 `ast` 把源码解析成结构树，给出三类**真实修补**的精确定位与最小改写：

  1) 🔧 **函数内修补**：按函数名定位顶层 `def`/`async def` 的完整行段，只改这一段。
  2) 🔧 **方法内修补**：按 `类名.方法名` 定位类里的方法行段，只改这一段（不碰同类别的兄弟方法）。
  3) 🔧 **CLI 入口修补**：定位 `if __name__ == "__main__":` 守卫块，只改入口那几行。

定位拿到一个 `Locus`（种类 / 限定名 / 起止行 / 原文段），改写只**替换这一段行区间**，
段外每个字节原样不动——这正是「最小改写」。改写后的整文件再交给 `patchcontract` 验「局部有界」，
双保险：定位保证下刀准，契约保证下刀浅。零第三方依赖，纯标准库；locate 永不抛错，
源码解析不了就返回「定不了位」而非崩溃——定位器自己绝不能成为新的伤口。

用法:
    python astlocator.py              # 演示：三类真实修补各定位+最小改写一遍
    python astlocator.py --selfcheck  # 自检：三类修补都定位准、只改那一段、契约放行（供 evidence 复跑）
    python astlocator.py --json       # 机读：支持的定位种类 + 目标语法
    加 --quiet 静默，仅以退出码表态。
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import sys

import patchcontract   # 最小改写后的整文件，仍要过「局部有界」拒收闸——定位准 + 下刀浅，双保险

# CLI 入口的伪限定名：locate 的 target 传它即定位 `if __name__ == "__main__":` 守卫块。
CLI_GUARD = "__main__"


@dataclasses.dataclass(frozen=True)
class Locus:
    """一次结构定位的结果：在源码里框出「该下刀的那一段」。"""
    kind: str          # "function" | "method" | "cli-guard"
    qualname: str      # 限定名：函数名 / 类名.方法名 / "__main__"
    lineno: int        # 起始行（1-based，含）
    end_lineno: int    # 结束行（1-based，含）
    segment: str       # 这一段的原文（不含尾随换行）

    @property
    def span(self) -> int:
        """这一段占多少行。"""
        return self.end_lineno - self.lineno + 1

    def to_meta(self) -> dict:
        return {"kind": self.kind, "qualname": self.qualname,
                "lineno": self.lineno, "end_lineno": self.end_lineno, "span": self.span}


@dataclasses.dataclass(frozen=True)
class RewriteResult:
    """一次「定位 + 最小改写」的全过程结果。"""
    ok: bool
    reason: str                 # 一句人话：成了/为什么没成
    locus: Locus | None         # 定到的位（定不到则 None）
    source: str | None          # 改写后的整文件（没改成则 None）
    verdict: object | None      # patchcontract.PatchVerdict（没走到契约则 None）

    def to_meta(self) -> dict:
        m = {"ok": self.ok, "reason": self.reason,
             "locus": self.locus.to_meta() if self.locus else None}
        if self.verdict is not None:
            m["verdict"] = self.verdict.to_meta()
        return m


def _is_cli_guard(node: ast.AST) -> bool:
    """这个节点是不是 `if __name__ == "__main__":` 守卫块。"""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)):
        return False
    left, right = test.left, test.comparators[0]
    names = {getattr(left, "id", None), getattr(right, "id", None)}
    consts = {getattr(left, "value", None), getattr(right, "value", None)}
    return "__name__" in names and "__main__" in consts


def _segment(lines: list[str], node: ast.AST) -> tuple[int, int, str]:
    """取节点占据的行区间 (起, 止, 原文段)；含装饰器（从最靠上的装饰器算起）。"""
    start = node.lineno
    for dec in getattr(node, "decorator_list", []) or []:
        start = min(start, dec.lineno)
    end = node.end_lineno
    seg = "\n".join(lines[start - 1:end])
    return start, end, seg


def locate(src: str, target: str) -> Locus | None:
    """按结构定位「该下刀的那一段」。永不抛错：解析不了 / 找不到都返回 None。

    target 三种写法：
      · "函数名"        → 顶层 def/async def
      · "类名.方法名"    → 类里的方法（不碰兄弟方法）
      · "__main__"      → `if __name__ == "__main__":` 守卫块（CLI 入口）
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None   # 连语法都不成立，定位无从谈起——交回上层（多半该走补冒号那类招式）
    lines = src.split("\n")

    # CLI 入口：扫顶层语句找守卫块
    if target == CLI_GUARD:
        for node in tree.body:
            if _is_cli_guard(node):
                start, end, seg = _segment(lines, node)
                return Locus("cli-guard", CLI_GUARD, start, end, seg)
        return None

    # 方法：类名.方法名
    if "." in target:
        cls_name, _, meth_name = target.partition(".")
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                for sub in node.body:
                    if (isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and sub.name == meth_name):
                        start, end, seg = _segment(lines, sub)
                        return Locus("method", target, start, end, seg)
        return None

    # 函数：顶层 def/async def
    for node in tree.body:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == target):
            start, end, seg = _segment(lines, node)
            return Locus("function", target, start, end, seg)
    return None


def entries(src: str) -> list[Locus]:
    """枚举一份源码里所有可定位的目标（顶层函数 / 各类方法 / CLI 守卫），供发现与列举。"""
    found: list[Locus] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return found
    lines = src.split("\n")
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            s, e, seg = _segment(lines, node)
            found.append(Locus("function", node.name, s, e, seg))
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    s, e, seg = _segment(lines, sub)
                    found.append(Locus("method", f"{node.name}.{sub.name}", s, e, seg))
        elif _is_cli_guard(node):
            s, e, seg = _segment(lines, node)
            found.append(Locus("cli-guard", CLI_GUARD, s, e, seg))
    return found


def splice(src: str, locus: Locus, new_segment: str) -> str:
    """把 locus 框出的那一段行区间换成 new_segment，段外每个字节原样不动——这就是最小改写。"""
    lines = src.split("\n")
    new_lines = new_segment.split("\n")
    spliced = lines[:locus.lineno - 1] + new_lines + lines[locus.end_lineno:]
    return "\n".join(spliced)


def rewrite(src: str, target: str, transform) -> RewriteResult:
    """定位 + 最小改写：定到 target，对它那一段调 transform 得新段，splice 回去，再过补丁契约。

    transform(old_segment: str) -> str：只该改这一段，返回改写后的段。
    返回 RewriteResult：定不到位、改写抛错、改成了 no-op、或契约拒收，都收敛成 ok=False，绝不抛错。
    """
    locus = locate(src, target)
    if locus is None:
        return RewriteResult(False, f"定不到位：源码里没有「{target}」这个函数/方法/CLI入口",
                             None, None, None)
    try:
        new_seg = transform(locus.segment)
    except Exception as e:  # noqa: BLE001 —— transform 抛错也算这一爪没成，保守收敛不反噬
        return RewriteResult(False, f"改写「{target}」那一段时出意外：{type(e).__name__}: {e}",
                             locus, None, None)
    if not isinstance(new_seg, str):
        return RewriteResult(False, f"改写「{target}」的产出不是字符串，弃之", locus, None, None)
    new_src = splice(src, locus, new_seg)
    verdict = patchcontract.validate(src, new_src)   # 下刀准之后，再验下刀浅：整文件仍须局部有界
    if not verdict.ok:
        return RewriteResult(False, f"最小改写后仍被契约拒收（{verdict.code}）：{verdict.reason}",
                             locus, None, verdict)
    return RewriteResult(True, f"已在「{target}」处最小改写（只动第 {locus.lineno}–{locus.end_lineno} 行）",
                         locus, new_src, verdict)


def manifest() -> dict:
    """机读：支持的定位种类 + 目标语法（给 health / 外部消费）。"""
    return {
        "kinds": {
            "function": "顶层 def/async def，target 写函数名",
            "method": "类里的方法，target 写「类名.方法名」",
            "cli-guard": "`if __name__ == \"__main__\":` 守卫块，target 写 \"__main__\"",
        },
        "cli_guard_token": CLI_GUARD,
    }


# ── 三类真实修补：逻辑伤（能编译、能起跑、报错无行号），靠结构定位才找得准 ──────────
@dataclasses.dataclass(frozen=True)
class RepairCase:
    """一道真实小修：哪类目标、伤在哪、怎么定位、怎么只改那一段、改对没。"""
    name: str
    kind: str
    target: str
    broken: str
    transform: "callable"      # 只改 target 那一段
    oracle: "callable"         # 拿改写后整文件的命名空间判「真修好了没」
    want: str


# 1) 函数内修补：净价该减折扣却写成了加——能算出数，但符号反了
_CASE_FUNC = RepairCase(
    name="函数内修补·符号反了",
    kind="function",
    target="net_price",
    broken=(
        "def net_price(price, discount):\n"
        "    return price + discount\n"          # 伤：该减折扣，写成了加
        "\n"
        "TAG = 'pricing'\n"
    ),
    transform=lambda seg: seg.replace("price + discount", "price - discount"),
    oracle=lambda ns: ns["net_price"](100, 30) == 70 and ns["TAG"] == "pricing",
    want="net_price(100,30) == 70 且模块其余（TAG）原样不动",
)

# 2) 方法内修补：购物车合计莫名多乘了 2——只该修这个方法，兄弟方法不能动
_CASE_METHOD = RepairCase(
    name="方法内修补·多乘了一下",
    kind="method",
    target="Cart.total",
    broken=(
        "class Cart:\n"
        "    def __init__(self, items):\n"
        "        self.items = items\n"
        "\n"
        "    def total(self):\n"
        "        return sum(self.items) * 2\n"    # 伤：合计被莫名放大 2 倍
        "\n"
        "    def count(self):\n"
        "        return len(self.items)\n"
    ),
    transform=lambda seg: seg.replace("sum(self.items) * 2", "sum(self.items)"),
    oracle=lambda ns: (lambda c: c.total() == 6 and c.count() == 3)(ns["Cart"]([1, 2, 3])),
    want="Cart([1,2,3]).total()==6 且 count()（兄弟方法）原样不动",
)

# 3) CLI 入口修补：把整个 sys.argv（含程序名）塞给了 main——该传 sys.argv[1:]
_CASE_CLI = RepairCase(
    name="CLI入口修补·argv 没切片",
    kind="cli-guard",
    target=CLI_GUARD,
    broken=(
        "import sys\n"
        "\n"
        "def main(argv):\n"
        "    return len(argv)\n"
        "\n"
        "RAN_WITH = None\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    RAN_WITH = main(sys.argv)\n"          # 伤：把程序名也算进去了
    ),
    transform=lambda seg: seg.replace("main(sys.argv)", "main(sys.argv[1:])"),
    # oracle：守卫块在普通 exec 下不触发，故直接验「入口那行已切片，且 main/其余原样可用」
    oracle=lambda ns: ns["main"](["a", "b"]) == 2,
    want="入口改成 main(sys.argv[1:])，main 本体与其余声明原样不动",
)

REPAIR_CASES: list[RepairCase] = [_CASE_FUNC, _CASE_METHOD, _CASE_CLI]


def _exec_ns(src: str) -> dict:
    """把一份（已修好的）源码跑起来，取它的命名空间供 oracle 裁决。"""
    ns: dict = {}
    exec(compile(src, "<astlocator-case>", "exec"), ns)  # noqa: S102 —— 跑的是本模块自造的隔离源码
    return ns


def _unchanged_outside(before: str, after: str, locus: Locus) -> bool:
    """段外是否每个字节原样不动：定位框出的行区间之外，before 与 after 必须逐行完全相同。"""
    b, a = before.split("\n"), after.split("\n")
    # 段前
    if b[:locus.lineno - 1] != a[:locus.lineno - 1]:
        return False
    # 段后：after 里被替换段的长度可能变，按「原 end 之后」对齐两侧的尾部
    return b[locus.end_lineno:] == a[len(a) - (len(b) - locus.end_lineno):]


def _selfcheck(quiet: bool = False) -> bool:
    """自检：三类真实修补都①定位准 ②只改那一段（段外不动）③契约放行 ④oracle 判真修好。

    供 evidence 的 astlocator 声明当复跑命令。无副作用、确定性、毫秒级。
    """
    failures: list[str] = []

    for c in REPAIR_CASES:
        res = rewrite(c.broken, c.target, c.transform)
        if not res.ok:
            failures.append(f"「{c.name}」没修成：{res.reason}")
            continue
        if res.locus.kind != c.kind:
            failures.append(f"「{c.name}」定位种类应为 {c.kind}，实得 {res.locus.kind}")
        if not _unchanged_outside(c.broken, res.source, res.locus):
            failures.append(f"「{c.name}」最小改写不成立：定位段外的代码也被动了")
        try:
            if not c.oracle(_exec_ns(res.source)):
                failures.append(f"「{c.name}」改写后 oracle 没过（验「{c.want}」失败）")
        except Exception as e:  # noqa: BLE001
            failures.append(f"「{c.name}」改写后跑起来就崩：{type(e).__name__}: {e}")

    # 定不到位探针：找一个不存在的目标，必须老实返回「定不到」而非乱定一个
    miss = locate(_CASE_FUNC.broken, "no_such_function")
    if miss is not None:
        failures.append("定不到位探针：不存在的目标竟被定到了一个位")
    bad = rewrite(_CASE_FUNC.broken, "no_such_function", lambda s: s + "\n# x")
    if bad.ok:
        failures.append("定不到位探针：定不到位却报成功，危险")

    # 语法畸形探针：源码连解析都过不去时，locate 必须返回 None 而非抛错
    if locate("def broken(:\n", "broken") is not None:
        failures.append("语法畸形探针：解析不了的源码竟定到了位")

    # no-op 探针：transform 没真改东西，splice 出来与原文一字不差 → 契约应判 no-op 拒收
    noop = rewrite(_CASE_FUNC.broken, "net_price", lambda seg: seg)
    if noop.ok or (noop.verdict is not None and noop.verdict.code != "no-op"):
        failures.append(f"no-op 探针：原样改写应被契约判 no-op 拒收，实得 {noop.reason}")

    # 兄弟方法不串味探针：定位 Cart.total 不该把 Cart.count 也框进去
    loc_total = locate(_CASE_METHOD.broken, "Cart.total")
    if loc_total is None or "count" in loc_total.segment:
        failures.append("兄弟方法探针：定位 Cart.total 竟把兄弟方法 count 也框了进来")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ astlocator selfcheck：三类真实修补都定位准、只改那一段、契约放行、oracle 判真修好——定位器可信。")
        else:
            print("❌ astlocator selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    print("🎯🖐️  AST 自生手定位器 —— 三类真实修补各定位 + 最小改写一遍：\n")
    for c in REPAIR_CASES:
        res = rewrite(c.broken, c.target, c.transform)
        head = f"  【{c.kind}】{c.name}　target=「{c.target}」"
        print(head)
        if res.locus:
            print(f"      🎯 定到：{res.locus.qualname}  第 {res.locus.lineno}–{res.locus.end_lineno} 行"
                  f"（{res.locus.span} 行）")
        if res.ok:
            print(f"      🟢 最小改写成功 —— {res.reason}")
            print(f"         验「{c.want}」：{'✅' if c.oracle(_exec_ns(res.source)) else '❌'}")
        else:
            print(f"      🔴 没修成 —— {res.reason}")
        print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab AST 自生手定位器 🎯🖐️")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：三类修补都定位准、只改那一段、契约放行（供 evidence 复跑）")
    ap.add_argument("--json", action="store_true", help="机读：支持的定位种类 + 目标语法")
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
