#!/usr/bin/env python3
"""自生补丁契约 🧬🖐️ —— 钉死 brain 自改补丁的格式，畸形/越界的当场拒收。

为什么要有它：`weaning_trial.py` 让 brain 拔掉外援自己产补丁（招式吐出一段候选源码），
`hands.py` 让 brain 雇爪子改文件。可「候选源码」过去是**裸字符串**：招式吐什么就吃什么，
没人验它是不是一个**正当的补丁**。一个会动手的爪子若连「这一爪能不能收」都判不了，
就谈不上可托付——它可能吐回 None、吐回空文件、或一口气把半个文件重写掉（哪怕侥幸还能编译），
而 brain 照单全收。补丁可靠的第一步，是先让每一爪**可验证、可拒绝**。

本层把「什么样的改动才算一个合法的 brain 补丁」钉成可执行的契约，并给出一道**拒收闸**：

  1) 🧱 **非畸形（well-formed）**：补丁后的源码必须是非空字符串、确有改动。
     None / 非字符串 / 空白 / 原样没动 —— 都是畸形，当场拒收。
  2) 📏 **不越界（bounded）**：一招只修一处，改动必须**局部有界**——改动行数与
     文件行数增减都不得越线。重写式大改（哪怕能编译）越界即拒：它不是「修一处伤」，
     是「换一个文件」，brain 收不得。

通过闸的才算一个可收的补丁；没过的当场拒收，理由点名到**具体规则码**，
让账本翻得出「这爪为什么不收」。零第三方依赖，纯标准库；validate 永不抛错，
任何意外形态都收敛成「拒收」而非崩溃——拒收闸自己绝不能成为新的伤口。

用法:
    python patchcontract.py             # 演示：正/畸/越几个例子各判一遍
    python patchcontract.py --selfcheck # 自检：畸形/越界各类补丁都被正确拒收
    python patchcontract.py --json      # 机读：契约阈值 + 规则码清单
    加 --quiet 静默，仅以退出码表态。
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import difflib
import json
import sys

# ── 契约阈值：一招只修一处，越线即「越界」 ──────────────────────────────
# brain 的招式（补冒号 / 括号 print / 名字纠偏）本质都是「定位一处、改一处」。
# 留一点余量给「同一个错名在几行里重复」这类正当的多点同改，但绝不容忍重写式大改。
DEFAULT_MAX_CHANGED_LINES = 5    # 改动行数上限（替换/增/删的行数之和）
DEFAULT_MAX_LINE_DELTA = 4       # 文件总行数增减的绝对值上限


@dataclasses.dataclass(frozen=True)
class PatchVerdict:
    """一次补丁契约裁决：收还是拒，拒在哪条规则上。"""
    ok: bool
    code: str      # 收 → ""；拒 → 点名的规则码（malformed-* / out-of-bounds-*）
    reason: str    # 一句人话：为什么这么判

    def to_meta(self) -> dict:
        return {"ok": self.ok, "code": self.code, "reason": self.reason}


# 规则码 → 一句话含义（账本/外部消费用同一份真相源）
RULE_CODES: dict[str, str] = {
    "malformed-none": "补丁为 None —— 招式没产出任何候选",
    "malformed-type": "补丁不是字符串 —— 不是一段可落盘的源码",
    "malformed-empty": "补丁清成了空白 —— 把文件改没了，绝不是「修一处伤」",
    "malformed-base": "原文不是字符串 —— 无从据此判断改动边界",
    "no-op": "补丁与原文一字不差 —— 没有改动，不构成一个补丁",
    "signature-changed": "函数签名发生变化 —— brain-only 小修不得伤到调用接口",
    "out-of-bounds-span": "改动行数越界 —— 一招只该修一处，这是重写式大改",
    "out-of-bounds-growth": "文件行数增减越界 —— 大段增删，超出「局部修一处」",
}

_OK = PatchVerdict(True, "", "局部有界、确有改动 —— 可收的补丁")


def changed_line_count(before: str, after: str) -> int:
    """补丁改了多少行：替换/新增/删除的行数之和（按行做最长公共子序列比对）。"""
    sm = difflib.SequenceMatcher(a=before.split("\n"), b=after.split("\n"), autojunk=False)
    n = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        n += max(i2 - i1, j2 - j1)
    return n


def _function_signatures(source: str) -> dict[str, str]:
    """抽取模块内函数/方法的签名指纹；语法错误交给调用方决定是否放行到 syntax 闸。"""
    tree = ast.parse(source)
    sigs: dict[str, str] = {}
    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            stack.append(node.name)
            for item in node.body:
                self.visit(item)
            stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            qn = ".".join(stack + [node.name])
            args = ast.dump(node.args, include_attributes=False)
            returns = ast.dump(node.returns, include_attributes=False) if node.returns else ""
            sigs[qn] = f"{args} -> {returns}"

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            self.visit_FunctionDef(node)  # 同一套签名规则：名字/参数/返回注解都不得漂

    Visitor().visit(tree)
    return sigs


def validate_signatures_unchanged(before, after) -> PatchVerdict:
    """契约闸：函数/方法签名必须不变；语法残段不在这里判，继续交给 syntax 闸。"""
    try:
        if not isinstance(before, str) or not isinstance(after, str):
            return PatchVerdict(False, "malformed-type", RULE_CODES["malformed-type"])
        try:
            before_sigs = _function_signatures(before)
            after_sigs = _function_signatures(after)
        except SyntaxError:
            return _OK
        if before_sigs != after_sigs:
            missing = sorted(set(before_sigs) - set(after_sigs))
            added = sorted(set(after_sigs) - set(before_sigs))
            changed = sorted(k for k in set(before_sigs) & set(after_sigs)
                             if before_sigs[k] != after_sigs[k])
            bits = []
            if changed:
                bits.append("变更 " + ", ".join(changed[:3]))
            if missing:
                bits.append("删除 " + ", ".join(missing[:3]))
            if added:
                bits.append("新增 " + ", ".join(added[:3]))
            detail = "；".join(bits) if bits else "签名集合不一致"
            return PatchVerdict(False, "signature-changed",
                                f"{RULE_CODES['signature-changed']}（{detail}）")
        return _OK
    except Exception as e:  # noqa: BLE001 —— 签名闸自身也要可拒不可崩
        return PatchVerdict(False, "signature-changed",
                            f"判定函数签名时出意外，保守拒收：{type(e).__name__}: {e}")


def validate(before, after, *,
             max_changed_lines: int = DEFAULT_MAX_CHANGED_LINES,
             max_line_delta: int = DEFAULT_MAX_LINE_DELTA) -> PatchVerdict:
    """把一个候选补丁（原文 before → 候选 after）按契约判「收 / 拒」。

    先验畸形（连「是不是一段确有改动的源码」都不成立），再验越界（改动是否局部有界）。
    永不抛错：任何意外形态都收敛成一条拒收裁决——拒收闸自己绝不能成为新伤口。
    """
    try:
        # ── 1) 非畸形 ──────────────────────────────────────────────
        if after is None:
            return PatchVerdict(False, "malformed-none", RULE_CODES["malformed-none"])
        if not isinstance(after, str):
            return PatchVerdict(False, "malformed-type", RULE_CODES["malformed-type"])
        if after.strip() == "":
            return PatchVerdict(False, "malformed-empty", RULE_CODES["malformed-empty"])
        if not isinstance(before, str):
            return PatchVerdict(False, "malformed-base", RULE_CODES["malformed-base"])
        if after == before:
            return PatchVerdict(False, "no-op", RULE_CODES["no-op"])

        # ── 2) 不越界 ──────────────────────────────────────────────
        delta = abs(after.count("\n") - before.count("\n"))
        if delta > max_line_delta:
            return PatchVerdict(False, "out-of-bounds-growth",
                                f"{RULE_CODES['out-of-bounds-growth']}（增减 {delta} 行 > {max_line_delta}）")
        changed = changed_line_count(before, after)
        if changed > max_changed_lines:
            return PatchVerdict(False, "out-of-bounds-span",
                                f"{RULE_CODES['out-of-bounds-span']}（改动 {changed} 行 > {max_changed_lines}）")
        return _OK
    except Exception as e:  # noqa: BLE001 —— 拒收闸绝不能崩，意外即收敛为拒收
        return PatchVerdict(False, "malformed-type", f"判定补丁时出意外，保守拒收：{type(e).__name__}: {e}")


def accepts(before, after, **kw) -> bool:
    """便捷断言：这个候选补丁会被契约接收吗（供调用方一行判收/拒）。"""
    return validate(before, after, **kw).ok


def manifest() -> dict:
    """机读：契约阈值 + 规则码清单（给 health / 外部消费）。"""
    return {
        "max_changed_lines": DEFAULT_MAX_CHANGED_LINES,
        "max_line_delta": DEFAULT_MAX_LINE_DELTA,
        "rules": RULE_CODES,
    }


# ── 自检：畸形/越界各类补丁都必须被正确拒收，正当补丁必须被接收 ──────────────
def expect_accept_with(before, after, label, failures: list[str]) -> None:
    """断言一个正当补丁会被接收；不被接收就记一条失败（供自检复用）。"""
    v = validate(before, after)
    if not v.ok:
        failures.append(f"正当补丁「{label}」竟被拒收：{v.code} / {v.reason}")


def _selfcheck(quiet: bool = False) -> bool:
    """自检：固化下来的补丁契约今天仍把畸形/越界拒在门外、把正当补丁放进来。

    供 evidence 的 patchcontract 声明当复跑命令。无副作用、确定性、毫秒级。
    """
    base = "def add(a, b)\n    return a + b\n"          # 一段原文（3 行）
    failures: list[str] = []

    def expect_reject(after, code, label):
        v = validate(base, after)
        if v.ok:
            failures.append(f"畸形/越界用例「{label}」竟被接收了，危险")
        elif v.code != code:
            failures.append(f"「{label}」拒收码应为 {code}，实得 {v.code}")

    def expect_accept(after, label):
        v = validate(base, after)
        if not v.ok:
            failures.append(f"正当补丁「{label}」竟被拒收：{v.code} / {v.reason}")

    # —— 畸形：连「确有改动的源码」都不成立 ——
    expect_reject(None, "malformed-none", "招式吐回 None")
    expect_reject(123, "malformed-type", "补丁不是字符串")
    expect_reject(["def add(a, b):"], "malformed-type", "补丁是列表不是串")
    expect_reject("   \n\n  ", "malformed-empty", "把文件改成空白")
    expect_reject("", "malformed-empty", "把文件改没了")
    expect_reject(base, "no-op", "原样没动")

    # 原文本身畸形（非字符串）也要稳稳拒收，绝不抛错
    if validate(None, "def add(a, b):\n    return a + b\n").code != "malformed-base":
        failures.append("原文为 None 时应判 malformed-base")

    # —— 函数签名契约：brain-only 小修不得伤到调用接口 ——
    sig_before = "def add(a, b):\n    return a + b\n"
    sig_after = "def add(a, b=0):\n    return a + b\n"
    v_sig = validate_signatures_unchanged(sig_before, sig_after)
    if v_sig.ok or v_sig.code != "signature-changed":
        failures.append(f"破坏默认参数的补丁应判 signature-changed，实得 {v_sig.code}")
    if not validate_signatures_unchanged(sig_before, sig_before.replace("a + b", "a - b")).ok:
        failures.append("只改函数体、不改签名的小修不应被签名闸拒收")

    # —— 越界：能编译也算大改，brain 收不得 ——
    expect_reject("\n".join(f"line{i}" for i in range(40)), "out-of-bounds-growth", "重写成 40 行的新文件")
    # 行数几乎不变，但逐行都被替换 → 改动行数越界（这一类 growth 拦不住，靠 span 兜住）
    eight = "\n".join(f"keep{i}" for i in range(8))            # 8 行原文
    rewrite8 = "\n".join(f"changed{i}" for i in range(8))      # 同样 8 行，但每行都换了
    v_span = validate(eight, rewrite8)
    if v_span.ok or v_span.code != "out-of-bounds-span":
        failures.append(f"逐行重写应判 out-of-bounds-span，实得 {v_span.code}")

    # —— 正当：brain 三招产出的「修一处」补丁都必须被接收 ——
    expect_accept("def add(a, b):\n    return a + b\n", "补冒号：只改报错那一行")
    # 括号 print：基于一段有 print 语句的原文，只把那一行收成 print(...)
    print_before = 'def add(a, b):\n    print a\n    return a + b\n'
    expect_accept_with(print_before, print_before.replace("print a", "print(a)"),
                       "括号 print：只改 print 那一行", failures)
    # 名字纠偏：把一处拼错名改回，仅动一行
    typo_before = "def double(x):\n    return x * 2\n\nRESULT = doubel(21)\n"
    expect_accept_with(typo_before, typo_before.replace("doubel", "double"),
                       "名字纠偏：单处改名", failures)

    # —— 阈值边界：恰好压线的多点同改要放行，越一行就拒 ——
    src5 = "\n".join(["a", "b", "c", "d", "e", "f"])     # 6 行
    # 改动正好 5 行（前 5 行各换内容，末行不变）→ 压线放行
    edit5 = "\n".join(["A", "B", "C", "D", "E", "f"])
    if changed_line_count(src5, edit5) != 5:
        failures.append(f"压线用例改动行数应为 5，实得 {changed_line_count(src5, edit5)}")
    expect_accept_with(src5, edit5, "恰好 5 行改动（压线）", failures)
    edit6 = "\n".join(["A", "B", "C", "D", "E", "F"])     # 改动 6 行 → 越界
    v6 = validate(src5, edit6)
    if v6.ok or v6.code != "out-of-bounds-span":
        failures.append(f"超线一行应判 out-of-bounds-span，实得 {v6.code}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ patchcontract selfcheck：畸形/越界补丁全被拒收，正当补丁全被接收——补丁契约可信。")
        else:
            print("❌ patchcontract selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    base = "def add(a, b)\n    return a + b\n"
    samples = [
        ("✅ 正当：补冒号（修一处）", "def add(a, b):\n    return a + b\n"),
        ("🧱 畸形：吐回 None", None),
        ("🧱 畸形：改成空白", "   \n"),
        ("📏 越界：重写成 40 行新文件", "\n".join(f"line{i}" for i in range(40))),
    ]
    print("🧬🖐️  自生补丁契约 —— 几个候选各判一遍：\n")
    print(f"   阈值：改动 ≤ {DEFAULT_MAX_CHANGED_LINES} 行、行数增减 ≤ {DEFAULT_MAX_LINE_DELTA}\n")
    for label, after in samples:
        v = validate(base, after)
        mark = "🟢 收" if v.ok else f"🔴 拒（{v.code}）"
        print(f"  {label}\n      {mark} —— {v.reason}")
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生补丁契约 🧬🖐️")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：畸形/越界补丁都被正确拒收（供 evidence 复跑）")
    ap.add_argument("--json", action="store_true", help="机读：阈值 + 规则码清单")
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
