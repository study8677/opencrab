#!/usr/bin/env python3
"""自生手读码上下文包 📖🖐️ —— 改码前，先把「这一段周围的事」自动汇总成一页，让手看懂边界再落笔。

为什么要有它：`astlocator.py` 已经让 brain 小修能「找准下刀处」——按函数/方法/CLI 入口精确定位、
只改那一段。可定位只解决了「刀往哪扎」，没解决「扎下去会牵动谁」。一只只会定位的手，照样可能
把净价函数的符号改对了、却忘了它有三个调用方按旧语义在用；或者动了某个底座方法、却没注意到
`contracts.py` 早给它立过「收什么、回什么」的红线；又或者改完不知道近邻就有一条自检在盯着它。

亲手写代码的第二步，是先读懂下刀处的**上下文**。本层在改写之前，围着定位到的那一段，自动汇总四样：

  1) 📌 **目标本体**：签名（参数 / 返回标注）+ docstring 首句 + 占多少行——先认清要改的是什么。
  2) 📞 **调用方**：本文件里哪些（非测试）函数/方法调用了它、调在第几行——改语义前先知道谁在用。
  3) 📜 **契约**：`contracts.py` 是否给这个模块立过「输入/输出」红线——改签名前先看清不许跨的线。
  4) 🧪 **近邻测试**：本文件里的自检/样例函数，并标出哪几条**正覆盖**着目标——改完谁会立刻验它。

汇总拿到一个 `ReadPack`，可一页渲染成给手读的「读码简报」。纯标准库 `ast`，零第三方依赖；
pack 永不抛错——解析不了 / 定不到位都返回「读不出」而非崩溃，读码包自己绝不能成为新的伤口。

用法:
    python readpack.py              # 演示：给两类目标各汇总一页读码简报
    python readpack.py --selfcheck  # 自检：目标/调用方/契约/近邻测试四样都汇准（供 evidence 复跑）
    python readpack.py --json       # 机读：读码包汇总的四个断面
    加 --quiet 静默，仅以退出码表态。
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import sys

import astlocator   # 复用「找准下刀处」：读码包围着 astlocator 定位到的那一段汇总上下文
from astlocator import CLI_GUARD, Locus


@dataclasses.dataclass(frozen=True)
class CallSite:
    """一处调用：谁（限定名，顶层调用记 "<module>"）在第几行调了目标。"""
    caller: str
    lineno: int

    def to_meta(self) -> dict:
        return {"caller": self.caller, "lineno": self.lineno}


@dataclasses.dataclass(frozen=True)
class NearbyTest:
    """一条近邻测试：自检/样例函数名、起始行，以及它是否正覆盖着目标。"""
    qualname: str
    lineno: int
    covers_target: bool

    def to_meta(self) -> dict:
        return {"qualname": self.qualname, "lineno": self.lineno,
                "covers_target": self.covers_target}


@dataclasses.dataclass(frozen=True)
class ContractRef:
    """目标所在模块在 contracts.py 立下的红线（没立则为 None）。"""
    module: str
    duty: str
    inputs: str
    outputs: str

    def to_meta(self) -> dict:
        return {"module": self.module, "duty": self.duty,
                "inputs": self.inputs, "outputs": self.outputs}


@dataclasses.dataclass(frozen=True)
class ReadPack:
    """改码前围着下刀处汇总的一页上下文：目标本体 + 调用方 + 契约 + 近邻测试。"""
    ok: bool
    reason: str                     # 一句人话：汇出来了/为什么没汇出
    target: str
    locus: Locus | None             # 定到的位（定不到则 None，且 ok=False）
    signature: str | None           # 目标签名（CLI 守卫块无签名 → None）
    doc: str | None                 # docstring 首句（无则 None）
    callers: list[CallSite]         # 本文件里的（非测试）调用方
    tests: list[NearbyTest]         # 本文件里的近邻测试
    contract: ContractRef | None    # 该模块的契约（未立约 → None）

    def to_meta(self) -> dict:
        return {
            "ok": self.ok, "reason": self.reason, "target": self.target,
            "locus": self.locus.to_meta() if self.locus else None,
            "signature": self.signature, "doc": self.doc,
            "callers": [c.to_meta() for c in self.callers],
            "tests": [t.to_meta() for t in self.tests],
            "contract": self.contract.to_meta() if self.contract else None,
        }


def _find_node(tree: ast.AST, target: str) -> ast.AST | None:
    """按 target 取出对应的 def 节点（函数/方法）；CLI 守卫块无 def 节点 → None。"""
    if target == CLI_GUARD:
        return None
    if "." in target:
        cls_name, _, meth_name = target.partition(".")
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                for sub in node.body:
                    if (isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and sub.name == meth_name):
                        return sub
        return None
    for node in tree.body:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == target):
            return node
    return None


def _signature(node: ast.AST) -> str:
    """从 def 节点拼出可读签名：`名字(参数) -> 返回标注`。"""
    args = ast.unparse(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{node.name}({args}){ret}"


def _doc_first_line(node: ast.AST) -> str | None:
    """docstring 首句（去空白）；没有则 None。"""
    doc = ast.get_docstring(node)
    if not doc:
        return None
    return doc.strip().split("\n", 1)[0].strip() or None


def _is_test_name(name: str) -> bool:
    """这个函数名看起来是不是一条测试/自检/样例（近邻测试 ≠ 调用方）。"""
    return (name in {"_selfcheck", "selfcheck", "_demo"}
            or name.startswith("_sample") or name.startswith("_test")
            or name.startswith("test"))


def _call_matches(func: ast.AST, name: str, is_method: bool) -> bool:
    """这个 Call 的 func 是不是在调名为 name 的目标。"""
    if is_method:                       # 方法：只认 `x.方法名(...)`
        return isinstance(func, ast.Attribute) and func.attr == name
    # 函数：`名字(...)` 或 `模块.名字(...)` 都算
    return ((isinstance(func, ast.Name) and func.id == name)
            or (isinstance(func, ast.Attribute) and func.attr == name))


def _references(node: ast.AST, name: str, is_method: bool) -> bool:
    """node 的子树里是否引用了名为 name 的目标（调用或具名引用），用于判近邻测试是否覆盖。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _call_matches(sub.func, name, is_method):
            return True
        if not is_method and isinstance(sub, ast.Name) and sub.id == name:
            return True
        if is_method and isinstance(sub, ast.Attribute) and sub.attr == name:
            return True
    return False


def _find_callers(tree: ast.AST, target: str) -> list[CallSite]:
    """汇总本文件里调用了 target 的（非测试）函数/方法，连同调用所在行。"""
    if target == CLI_GUARD:
        return []                       # CLI 入口不被「调用」，无调用方可言
    name = target.split(".")[-1]
    is_method = "." in target
    sites: list[CallSite] = []

    def walk(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk(child, scope + [child.name])   # 进入新作用域，调用归到它名下
            else:
                enclosing = scope[-1] if scope else None
                if enclosing and _is_test_name(enclosing):
                    continue            # 测试里的调用归「近邻测试」，不算调用方
                for sub in ast.walk(child):
                    if isinstance(sub, ast.Call) and _call_matches(sub.func, name, is_method):
                        sites.append(CallSite(".".join(scope) or "<module>", sub.lineno))

    walk(tree, [])
    return sites


def _find_tests(tree: ast.AST, target: str) -> list[NearbyTest]:
    """汇总本文件里的近邻测试（自检/样例函数），并标出哪几条正覆盖着目标。"""
    name = target.split(".")[-1]
    is_method = "." in target
    out: list[NearbyTest] = []
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _is_test_name(node.name)):
            out.append(NearbyTest(node.name, node.lineno,
                                  _references(node, name, is_method)))
    return out


def _lookup_contract(module: str | None) -> ContractRef | None:
    """查 contracts.py 是否给这个模块立过红线（尽力而为，查不到/出错都回 None）。"""
    if not module:
        return None
    try:
        import contracts
        for c in contracts.CONTRACTS:
            if c.module == module:
                return ContractRef(c.module, c.duty, c.inputs, c.outputs)
    except Exception:   # noqa: BLE001 —— 契约查询是锦上添花，缺席不该拖垮读码包
        pass
    return None


def pack(src: str, target: str, *, module: str | None = None) -> ReadPack:
    """改码前汇总下刀处的上下文：定位 target，围着它汇总目标本体/调用方/契约/近邻测试。

    module：目标所在模块名（如 "jsonlstore"），用于查 contracts.py 的红线；不给则跳过契约。
    永不抛错：定不到位 / 源码解析不了都收敛成 ok=False，绝不崩。
    """
    locus = astlocator.locate(src, target)
    if locus is None:
        return ReadPack(False, f"读不出：源码里定不到「{target}」这个函数/方法/CLI入口",
                        target, None, None, None, [], [], _lookup_contract(module))
    try:
        tree = ast.parse(src)
    except SyntaxError:     # locate 能定到却又解析失败极罕见，仍兜底不抛
        return ReadPack(False, f"读不出：源码解析不了，无法围读「{target}」",
                        target, locus, None, None, [], [], _lookup_contract(module))

    node = _find_node(tree, target)
    signature = _signature(node) if node is not None else None
    doc = _doc_first_line(node) if node is not None else None
    callers = _find_callers(tree, target)
    tests = _find_tests(tree, target)
    contract = _lookup_contract(module)

    bits = [f"调用方 {len(callers)}", f"近邻测试 {len(tests)}",
            "有契约" if contract else "未立约"]
    return ReadPack(True, f"已围「{target}」汇出读码简报（{('、'.join(bits))}）",
                    target, locus, signature, doc, callers, tests, contract)


def as_text(p: ReadPack) -> str:
    """把读码包渲染成给手读的一页简报。"""
    if not p.ok:
        return f"📖 读码简报 ·「{p.target}」\n  ⚠️ {p.reason}"
    lines = [f"📖 读码简报 ·「{p.target}」 —— {p.reason}", ""]
    lines.append("  📌 目标本体")
    lines.append(f"      位置：第 {p.locus.lineno}–{p.locus.end_lineno} 行（{p.locus.span} 行，{p.locus.kind}）")
    lines.append(f"      签名：{p.signature or '（CLI 守卫块，无签名）'}")
    lines.append(f"      职责：{p.doc or '（无 docstring）'}")
    lines.append("")
    lines.append(f"  📞 调用方（{len(p.callers)}）—— 改语义前先知道谁在用")
    if p.callers:
        for c in p.callers:
            lines.append(f"      · {c.caller}  调在第 {c.lineno} 行")
    else:
        lines.append("      （本文件里无人调用——改起来牵动面小）")
    lines.append("")
    lines.append("  📜 契约红线")
    if p.contract:
        lines.append(f"      模块 {p.contract.module}：{p.contract.duty}")
        lines.append(f"      入：{p.contract.inputs}")
        lines.append(f"      出：{p.contract.outputs}")
    else:
        lines.append("      （contracts.py 未给此模块立约——签名可改，但仍受补丁契约「局部有界」约束）")
    lines.append("")
    covering = [t for t in p.tests if t.covers_target]
    lines.append(f"  🧪 近邻测试（{len(p.tests)}，其中 {len(covering)} 条正覆盖目标）—— 改完谁会立刻验它")
    if p.tests:
        for t in p.tests:
            mark = "🎯 覆盖" if t.covers_target else "—"
            lines.append(f"      · {t.qualname}  第 {t.lineno} 行  {mark}")
    else:
        lines.append("      （本文件里无近邻测试——改完没有就近的网兜着，宜更谨慎）")
    return "\n".join(lines)


def manifest() -> dict:
    """机读：读码包汇总的四个断面（给 health / 外部消费）。"""
    return {
        "sections": {
            "target": "目标本体：签名（参数/返回标注）+ docstring 首句 + 行段跨度",
            "callers": "调用方：本文件里调用目标的（非测试）函数/方法及其调用行",
            "contract": "契约：contracts.py 给该模块立的输入/输出红线（未立约则空）",
            "tests": "近邻测试：本文件的自检/样例函数，并标出哪几条正覆盖目标",
        },
        "depends_on": ["astlocator", "contracts"],
        "cli_guard_token": CLI_GUARD,
    }


# ── 自检样例：两类真实目标，断言四个断面都汇准 ──────────────────────────────
# 一份自给自足的样例源码：净价函数有一个正经调用方(receipt)、一条近邻样例自检(_sample_net_price)，
# 外加一个购物车类(供方法目标用)。围这份源码汇总，能逐一验证四个断面是否汇对。
_SAMPLE_SRC = '''\
"""定价小工具(自检样例)。"""


def net_price(price, discount):
    """按折扣算净价。"""
    return price - discount


def receipt(price, discount):
    base = net_price(price, discount)
    return f"应付 {base}"


class Cart:
    def __init__(self, items):
        self.items = items

    def total(self):
        return sum(self.items)

    def summary(self):
        return f"合计 {self.total()}"


def _sample_net_price():
    assert net_price(100, 30) == 70
'''


def _selfcheck(quiet: bool = False) -> bool:
    """自检：函数目标与方法目标的四个断面都汇准、定不到位与畸形源码都老实回「读不出」。

    供 evidence 的 readpack 声明当复跑命令。无副作用、确定性、毫秒级。
    """
    failures: list[str] = []

    # ① 函数目标 net_price：签名/职责/调用方/近邻测试都该汇对
    p = pack(_SAMPLE_SRC, "net_price", module="errors")
    if not p.ok:
        failures.append(f"函数目标没汇出：{p.reason}")
    else:
        if p.signature != "net_price(price, discount)":
            failures.append(f"函数签名汇错：实得 {p.signature!r}")
        if p.doc != "按折扣算净价。":
            failures.append(f"职责(docstring 首句)汇错：实得 {p.doc!r}")
        callers = {c.caller for c in p.callers}
        if "receipt" not in callers:
            failures.append(f"调用方漏了 receipt：实得 {callers}")
        if "_sample_net_price" in callers:
            failures.append("调用方串味：近邻测试 _sample_net_price 被当成了调用方")
        covering = {t.qualname for t in p.tests if t.covers_target}
        if "_sample_net_price" not in covering:
            failures.append(f"近邻测试没认出覆盖目标的 _sample_net_price：实得 {covering}")
        if p.contract is None or p.contract.module != "errors":
            failures.append("契约查询失灵：errors 模块明明在 contracts.py 立过约")

    # ② 方法目标 Cart.total：调用方应只认 summary（兄弟方法），不串到无关处
    pm = pack(_SAMPLE_SRC, "Cart.total")
    if not pm.ok or pm.locus.kind != "method":
        failures.append(f"方法目标没汇成 method：{pm.reason}")
    else:
        callers = {c.caller for c in pm.callers}
        if "Cart.summary" not in callers:
            failures.append(f"方法调用方漏了 Cart.summary：实得 {callers}")
        if pm.signature != "total(self)":
            failures.append(f"方法签名汇错：实得 {pm.signature!r}")

    # ③ 未立约模块：contract 该为 None，但其余断面照常
    pn = pack(_SAMPLE_SRC, "net_price")   # 不传 module
    if pn.contract is not None:
        failures.append("没传 module 却凭空查出了契约")

    # ④ 定不到位探针：不存在的目标须老实回「读不出」而非硬汇
    miss = pack(_SAMPLE_SRC, "no_such_thing")
    if miss.ok or miss.locus is not None:
        failures.append("定不到位探针：不存在的目标竟汇出了读码包")

    # ⑤ 语法畸形探针：解析不了的源码须收敛回「读不出」而非抛错
    try:
        bad = pack("def broken(:\n", "broken")
        if bad.ok:
            failures.append("语法畸形探针：解析不了的源码竟汇成功了")
    except Exception as e:  # noqa: BLE001
        failures.append(f"语法畸形探针：pack 竟抛了错 {type(e).__name__}: {e}")

    # ⑥ 渲染探针：as_text 对成/败两种读码包都该出一页文字、不抛错
    if "读码简报" not in as_text(p) or "读码简报" not in as_text(miss):
        failures.append("渲染探针：as_text 没能把读码包渲染成简报")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ readpack selfcheck：目标本体/调用方/契约/近邻测试四样都汇准，"
                  "定不到位与畸形源码都老实回「读不出」——改码前的读码包可信。")
        else:
            print("❌ readpack selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    print("📖🖐️  自生手读码上下文包 —— 给两类目标各汇一页读码简报：\n")
    for target, module in [("net_price", "errors"), ("Cart.total", None)]:
        print(as_text(pack(_SAMPLE_SRC, target, module=module)))
        print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手读码上下文包 📖🖐️")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：四个断面都汇准、定不到位/畸形源码都回「读不出」（供 evidence 复跑）")
    ap.add_argument("--json", action="store_true", help="机读：读码包汇总的四个断面")
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
