#!/usr/bin/env python3
"""brain 意图→补丁编译器 🧭🩹 —— 把一句自然语言小修编译成一条**受限 JSON Patch**，只在试衣间穿一遍。

为什么要有它：到今天为止，brain 亲手产补丁这件事，要么是 `weaning_trial`/`purefix_trial`
那样**先有一处坏掉的源码**当起点、再去补；要么是 `shadowscribe` 那样对一份好端端的文件做
**全文确定性重排**(规范化/去尾空白)——它们都不接受「人话指令」当输入。可断奶的下一步不是
改得更狠，而是先证明一件更朴素的事：**「我说一句『把 version 改成 2.0』，brain 能不能把它
稳定地编译成一处可落地、可拒收的改动，而且全程不碰真身？」** 自然语言千变万化、最不可托付，
所以这里不假装懂语义——而是把它**收窄成一份可执行的受限语法**，编出来的东西每一步都看得见、
拒得掉。

本层就是那台「意图→补丁」的编译器，加一间只在影子上验收的试衣间：

  1) 🧭 **编译闸(compile)**：拿朴素正则把指令匹进一份**封闭的意图文法**——只认
     「把/将 <点路径> 改成/设为 <值>」这一族「改一处已有值」的说法。文法外的任何说法
     (新增字段、删字段、移动、看不懂的话)，当场弃权——宁可不接，绝不瞎猜。
  2) 🩹 **受限补丁**：编译产物是一条 **RFC 6902 风格的 JSON Patch**，但只许 `replace`
     一种操作、且只许一条 op。`add/remove/move/copy` 一律不生成——「改一处已有值」是
     断奶第一课能担的最小风险面，结构性改动留给以后。
  3) 🎯 **靶点闸(target)**：`replace` 按定义只能改**已存在**的路径。点路径解析成 JSON
     Pointer 后，目标若不在原文档里(打错字段名/路径不存在)，当场拒——绝不顺手新建。
  4) 🧪 **保型闸(type)**：新值的 JSON 类型必须与原值**同类**(数对数、串对串、真假对真假)。
     把数字字段悄悄改成字符串这类「低置信变型」一律拒——受限的第一要义是不偷偷扩大改动面。
  5) 🪞 **试衣间(fit)**：全闸过了，才把这条 patch 穿到一份**深拷贝的内存文档**上落地，
     复验：结果仍是合法 JSON、**恰好那一条路径的值变了、其余路径一字不差**。复验过才把
     誊本写进隔离的临时**影子副本**(`{name}.shadow`)，并回一份 unified diff 供人验收。
  6) 🔒 **不碰真身闸(untouched)**：全程结束，断言真文件 sha256 与落笔前一字节不差——
     brain 可以照着人话亲手改，但只能改在影子上，真身永远只读。

设计与全家一致：零第三方依赖、纯标准库；编译/解析/落地任一步出意外，一律收敛成
「不编译、不落影子、真身不动」，绝不抛错、绝不反噬——一台只敢在影子上落笔的编译器，
自己绝不能成为真身的第一道伤口。

用法:
    python intentpatch.py                    # 演示:几句人话各编一条 patch(改值/打错字段/变型/看不懂)
    python intentpatch.py --selfcheck        # 自检:编得对 / 三道闸各拦住该拦的 / 全程真身字节不变
    python intentpatch.py --json             # 机读:意图文法 + 受限规则
    python intentpatch.py --compile "把 a.b 改成 2"   # 只编译,打印 JSON Patch(不碰任何文件)
    python intentpatch.py --fit PATH "把 version 改成 2.0"   # 对真仓库内 JSON 文件试穿,只写影子(真身不动)
    加 --quiet 静默,仅以退出码表态。
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import difflib
import hashlib
import json
import pathlib
import re
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── 封闭的意图文法:只认「把/将 <点路径> 改成/设为 <值>」这一族「改一处已有值」 ──────
# 朴素正则,不假装懂自然语言——只回「这句话是不是在说『把某个已有字段改成某个值』」。
# 点路径:形如 a / a.b / server.port,只许字母数字/下划线/连字符 + 点分隔(不接数组下标,
# 那是结构性改动,留给以后)。值:抓到行尾,交给受限值解析器定夺类型。
_PATH = r"[A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_][A-Za-z0-9_\-]*)*"
_INTENT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(rf"^\s*(?:把|将)\s*(?P<path>{_PATH})\s*(?:改成|设为|设置为|改为)\s*(?P<value>.+?)\s*$"),
    re.compile(rf"^\s*set\s+(?P<path>{_PATH})\s+to\s+(?P<value>.+?)\s*$", re.IGNORECASE),
)

# 受限补丁:只生成这一种 op,且只许一条。其余 RFC 6902 操作一律不编译。
ALLOWED_OP = "replace"

# 拒收/弃权规则码 → 一句话含义(账本/外部消费同一份真相源)
RULE_CODES: dict[str, str] = {
    "no-match": "这句话不在意图文法里 —— 不认「改一处已有值」之外的说法,弃权",
    "bad-base": "原文档不是合法 JSON 对象 —— 无从据此定位字段",
    "target-missing": "目标路径在原文档里不存在 —— replace 只改已有值,绝不顺手新建",
    "target-not-container": "路径中途撞到非对象 —— 没法再往下钻,弃权",
    "type-mismatch": "新值与原值类型不同 —— 受限补丁不做低置信变型(数↔串↔真假)",
    "apply-drift": "落地后不止那一条路径变了 —— 编译产物与意图不符,拒",
    "shadow-write-error": "影子副本落盘失败 —— 写不进隔离临时目录,保守拒(真身仍未碰)",
    "real-touched": "真文件在落笔后被动过 —— 命根子破了,拒",
    "internal-error": "试穿时出意外 —— 收敛成拒,绝不抛错、绝不碰真身",
}


@dataclasses.dataclass(frozen=True)
class CompileResult:
    """一次「意图→补丁」编译的结论:编出来没、补丁是什么、为什么。"""
    compiled: bool          # 是否成功编出一条受限 JSON Patch
    patch: list             # 编译产物:RFC 6902 风格 JSON Patch(未编出 → [])
    pointer: str            # 目标 JSON Pointer(未编出 → "")
    value: object           # 解析出的新值(未编出 → None)
    code: str               # 编出 → "";否则点名的规则码
    detail: str             # 一句人话

    def to_meta(self) -> dict:
        return {"compiled": self.compiled, "patch": self.patch,
                "pointer": self.pointer, "code": self.code, "detail": self.detail}


def _parse_value(raw: str) -> object:
    """受限值解析:先按 JSON 字面量解(数/真假/null/带引号的串),解不动就当作一个裸字符串。

    于是 `8080`→int、`true`→bool、`1.5`→float、`"x"`→str、`crab`→str("crab")。
    """
    raw = raw.strip()
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def _pointer_of(dotted: str) -> str:
    """点路径 → JSON Pointer:a.b.c → /a/b/c(按 RFC 6901 转义 ~ 和 /,虽然本文法里不会出现)。"""
    parts = [p.replace("~", "~0").replace("/", "~1") for p in dotted.split(".")]
    return "/" + "/".join(parts)


def compile_intent(text) -> CompileResult:
    """把一句人话编译成一条受限 JSON Patch(只 replace、只一条);不在文法里则弃权。

    永不抛错——任何意外形态都收敛成「编不出」而非崩溃。
    """
    try:
        if not isinstance(text, str):
            return CompileResult(False, [], "", None, "no-match", RULE_CODES["no-match"])
        m = None
        for pat in _INTENT_PATTERNS:
            m = pat.match(text)
            if m:
                break
        if not m:
            return CompileResult(False, [], "", None, "no-match", RULE_CODES["no-match"])
        pointer = _pointer_of(m.group("path"))
        value = _parse_value(m.group("value"))
        patch = [{"op": ALLOWED_OP, "path": pointer, "value": value}]
        return CompileResult(True, patch, pointer, value, "",
                             f"编出受限补丁:replace {pointer} ← {json.dumps(value, ensure_ascii=False)}")
    except Exception as e:  # noqa: BLE001 —— 编译器绝不能崩,意外即收敛为「编不出」
        return CompileResult(False, [], "", None, "no-match",
                             f"编译时出意外,保守弃权:{type(e).__name__}: {e}")


def _resolve(doc, pointer: str) -> tuple[bool, object, str]:
    """沿 JSON Pointer 走到目标的**父容器**并取出现值。

    回 (找到没, 现值, 规则码)。找不到/中途撞非对象 → (False, None, 规则码)。
    """
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/") if p != ""]
    cur = doc
    for key in parts[:-1]:
        if not isinstance(cur, dict) or key not in cur:
            return False, None, "target-missing"
        cur = cur[key]
        if not isinstance(cur, dict):
            return False, None, "target-not-container"
    leaf = parts[-1]
    if not isinstance(cur, dict) or leaf not in cur:
        return False, None, "target-missing"
    return True, cur[leaf], ""


def _same_json_kind(a, b) -> bool:
    """两个值是不是同一 JSON 类型(数对数含 int/float、真假独立于数、其余按 type 比)。"""
    # bool 是 int 的子类,得先单独判,免得 True 被当成数
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return True
    return type(a) is type(b)


@dataclasses.dataclass(frozen=True)
class FitResult:
    """一次试衣间穿戴的结论:穿上了没(落影子)、被哪道闸决定、为什么、真身碰没碰。"""
    applied: bool           # 是否过全闸并把誊本落了影子副本
    gate: str               # 决定结果的闸:全过→"";否则点名失败处(compile/target/type/apply/untouched)
    code: str               # 对应规则码(全过 → "")
    detail: str             # 一句现场
    target: str             # 试穿的目标 JSON 文件
    patch: list             # 编译出的受限补丁(没编出 → [])
    shadow: str             # 影子副本路径(只写它,绝不写真身);未落影子 → ""
    real_untouched: bool    # 命根子:全程结束真文件 sha256 是否与落笔前一字节不差
    diff: str               # unified diff:brain 这一爪到底改了什么,供人验收

    def to_meta(self) -> dict:
        return {"applied": self.applied, "gate": self.gate, "code": self.code,
                "detail": self.detail, "target": self.target, "patch": self.patch,
                "shadow": self.shadow, "real_untouched": self.real_untouched}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dump(data) -> str:
    """统一的 JSON 落盘格式(与 shadowscribe 的 json-canonicalize 对齐:indent=2/sort_keys/末尾单换行)。"""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _changed_pointers(before, after, prefix: str = "") -> list[str]:
    """列出两份 JSON 数据里**值不同**的所有叶子路径(供「恰好一处变」复验)。"""
    diffs: list[str] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for k in set(before) | set(after):
            child = f"{prefix}/{k}"
            if k not in before or k not in after:
                diffs.append(child)
            else:
                diffs.extend(_changed_pointers(before[k], after[k], child))
    elif before != after:
        diffs.append(prefix or "/")
    return diffs


def fit(target, intent_text, *, write_shadow: bool = True,
        shadow_dir: pathlib.Path | None = None) -> FitResult:
    """把一句人话编译成受限补丁,只在影子上穿一遍并验收,真身永远不碰。

    target      : 真仓库内的 JSON 文件(其当前内容当 before;只读,绝不写它)。
    intent_text : 一句自然语言小修(「把 version 改成 2.0」之类)。
    write_shadow: False = 只验收看效果、连影子都不写(供 replay 零副作用重跑)。
    返回 FitResult。永不抛错——任何意外都收敛成「不落影子、真身不动」。
    """
    target = pathlib.Path(target)
    try:
        before = target.read_text(encoding="utf-8") if target.exists() else ""
    except OSError as e:
        return FitResult(False, "compile", "no-match", f"读不到目标文件,弃权:{type(e).__name__}: {e}",
                         str(target), [], "", True, "")
    before_sha = _sha256(before)

    def _untouched() -> bool:
        try:
            now = target.read_text(encoding="utf-8") if target.exists() else ""
        except OSError:
            return False
        return _sha256(now) == before_sha

    def _fail(gate: str, code: str, detail: str, patch=None, diff: str = "") -> FitResult:
        return FitResult(False, gate, code, detail, str(target), patch or [], "", _untouched(), diff)

    try:
        # ── 闸 1) 编译闸:人话 → 受限补丁,不在文法里则弃权 ──
        comp = compile_intent(intent_text)
        if not comp.compiled:
            return _fail("compile", comp.code, comp.detail)

        # ── 原文档必须是合法 JSON 对象,否则没法定位字段 ──
        try:
            doc = json.loads(before) if before.strip() else None
        except ValueError as e:
            return _fail("target", "bad-base", f"{RULE_CODES['bad-base']}:{e}", comp.patch)
        if not isinstance(doc, dict):
            return _fail("target", "bad-base", RULE_CODES["bad-base"], comp.patch)

        # ── 闸 2) 靶点闸:replace 只改已有值,目标不存在则拒 ──
        found, old_value, code = _resolve(doc, comp.pointer)
        if not found:
            return _fail("target", code, RULE_CODES[code], comp.patch)

        # ── 闸 3) 保型闸:新值须与原值同 JSON 类型,不做低置信变型 ──
        if not _same_json_kind(old_value, comp.value):
            return _fail("type", "type-mismatch",
                         f"{RULE_CODES['type-mismatch']}(原 {type(old_value).__name__} ← 新 {type(comp.value).__name__})",
                         comp.patch)

        # ── 闸 4) 试衣间:把补丁穿到深拷贝上落地,复验「恰好那一条路径变了」 ──
        after_doc = copy.deepcopy(doc)
        cur = after_doc
        parts = [p.replace("~1", "/").replace("~0", "~") for p in comp.pointer.split("/") if p != ""]
        for key in parts[:-1]:
            cur = cur[key]
        cur[parts[-1]] = comp.value

        changed = _changed_pointers(doc, after_doc)
        if changed != [comp.pointer]:
            return _fail("apply", "apply-drift",
                         f"{RULE_CODES['apply-drift']}(应只改 {comp.pointer},实变 {changed})", comp.patch)

        after = _dump(after_doc)
        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{target.name}", tofile=f"b/{target.name} (shadow)"))

        # ── 闸 5) 影子落盘:只写隔离的临时影子副本,真身永远不碰 ──
        shadow_path = ""
        if write_shadow:
            sd = pathlib.Path(shadow_dir) if shadow_dir else pathlib.Path(tempfile.gettempdir())
            try:
                sd.mkdir(parents=True, exist_ok=True)
                sp = sd / f"{target.name}.shadow"
                sp.write_text(after, encoding="utf-8")
                shadow_path = str(sp)
            except OSError as e:
                return _fail("apply", "shadow-write-error", f"{RULE_CODES['shadow-write-error']}:{type(e).__name__}: {e}", comp.patch, diff)

        # ── 闸 6) 不碰真身闸:命根子,真文件字节必须分毫不差 ──
        if not _untouched():
            return FitResult(False, "untouched", "real-touched", RULE_CODES["real-touched"],
                             str(target), comp.patch, shadow_path, False, diff)

        return FitResult(True, "", "",
                         f"按「{intent_text.strip()}」编出受限补丁并在影子上验收通过,真身字节不变",
                         str(target), comp.patch, shadow_path, True, diff)
    except Exception as e:  # noqa: BLE001 —— 试衣间绝不能崩:意外即收敛成「不落影子、真身不动」
        return _fail("apply", "internal-error", f"{RULE_CODES['internal-error']}:{type(e).__name__}: {e}")


def manifest() -> dict:
    """机读:意图文法 + 受限规则(给 health / 外部消费)。"""
    return {
        "allowed_op": ALLOWED_OP,
        "max_ops": 1,
        "intent_grammar": [
            "把/将 <点路径> 改成/设为/设置为/改为 <值>",
            "set <dotted.path> to <value>",
        ],
        "path_syntax": "点分隔的字段名(a.b.c);不接数组下标,结构性改动留给以后",
        "value_parsing": "先按 JSON 字面量解(数/真假/null/带引号串),解不动当裸字符串",
        "gates": ["compile", "target", "type", "apply", "untouched"],
        "rules": RULE_CODES,
    }


# ── 自检:编得对 / 三道闸各拦住该拦的 / 全程真身字节不变 ──────────────────────────
def _selfcheck(quiet: bool = False) -> bool:
    """自检:意图编译 + 试衣间验收今天仍稳。无副作用、确定性、毫秒级(影子写隔离临时目录)。"""
    failures: list[str] = []

    # —— 编译闸:文法内编得出、文法外老实弃权 ——
    c1 = compile_intent("把 version 改成 2.0")
    if not (c1.compiled and c1.pointer == "/version" and c1.patch == [{"op": "replace", "path": "/version", "value": 2.0}]):
        failures.append(f"「把 version 改成 2.0」应编出 replace /version ← 2.0,实得 {c1.patch}")
    c2 = compile_intent("把 server.port 设为 9090")
    if not (c2.compiled and c2.pointer == "/server/port" and c2.value == 9090):
        failures.append(f"嵌套点路径应编成 /server/port ← 9090,实得 {c2.to_meta()}")
    c3 = compile_intent("set name to crab")
    if not (c3.compiled and c3.pointer == "/name" and c3.value == "crab"):
        failures.append(f"英文 set 文法应编成 /name ← 'crab',实得 {c3.to_meta()}")
    for bad in ["删掉 version 字段", "新增一个 debug 字段", "随便说点什么", "", None, 123]:
        cb = compile_intent(bad)
        if cb.compiled:
            failures.append(f"文法外的「{bad}」竟被编出补丁,危险:{cb.patch}")
        elif cb.code != "no-match":
            failures.append(f"文法外的「{bad}」应判 no-match,实得 {cb.code}")

    # —— 试衣间:在隔离临时目录里对一份固定 JSON 各试一爪 ——
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        target = tdp / "config.json"
        base = _dump({"version": 1.0, "server": {"port": 8080, "host": "local"}, "debug": False})
        target.write_text(base, encoding="utf-8")
        base_sha = _sha256(base)

        def real_intact(label):
            now = target.read_text(encoding="utf-8")
            if _sha256(now) != base_sha:
                failures.append(f"「{label}」之后真文件竟被改动了——命根子破了")

        # 正当:改一处已有同型值 → 过全闸、落影子、真身不变、恰好一处变
        r_ok = fit(target, "把 version 改成 2.0", shadow_dir=tdp)
        if not r_ok.applied:
            failures.append(f"正当改值竟没过试衣间:{r_ok.gate}/{r_ok.code} {r_ok.detail}")
        elif r_ok.patch != [{"op": "replace", "path": "/version", "value": 2.0}]:
            failures.append(f"过闸补丁不对:{r_ok.patch}")
        elif not (r_ok.shadow and pathlib.Path(r_ok.shadow).exists()):
            failures.append("过闸却没落影子副本")
        else:
            sh = json.loads(pathlib.Path(r_ok.shadow).read_text(encoding="utf-8"))
            if sh.get("version") != 2.0 or sh.get("server") != {"port": 8080, "host": "local"}:
                failures.append(f"影子副本没有恰好只改 version:{sh}")
        real_intact("正当改值")

        # 嵌套字段改值也要过
        r_nested = fit(target, "把 server.port 改成 9090", shadow_dir=tdp)
        if not r_nested.applied:
            failures.append(f"嵌套改值竟没过试衣间:{r_nested.gate}/{r_nested.code}")
        real_intact("嵌套改值")

        # 靶点闸:字段不存在 → 拒(绝不顺手新建)
        r_missing = fit(target, "把 timeout 改成 30", shadow_dir=tdp)
        if r_missing.applied or r_missing.gate != "target" or r_missing.code != "target-missing":
            failures.append(f"改不存在字段应判 target/target-missing,实得 {r_missing.gate}/{r_missing.code}")
        real_intact("改不存在字段")

        # 靶点闸:路径中途撞非对象 → 拒
        r_thru = fit(target, "把 version.major 改成 2", shadow_dir=tdp)
        if r_thru.applied or r_thru.code not in ("target-missing", "target-not-container"):
            failures.append(f"穿过标量字段应被靶点闸拒,实得 {r_thru.gate}/{r_thru.code}")
        real_intact("穿过标量字段")

        # 保型闸:把数字字段改成字符串 → 拒
        r_type = fit(target, "把 server.port 改成 high", shadow_dir=tdp)
        if r_type.applied or r_type.gate != "type" or r_type.code != "type-mismatch":
            failures.append(f"数→串变型应判 type/type-mismatch,实得 {r_type.gate}/{r_type.code}")
        real_intact("数→串变型")

        # 保型闸:把布尔字段改成数字 → 拒(bool 不当数)
        r_bool = fit(target, "把 debug 改成 1", shadow_dir=tdp)
        if r_bool.applied or r_bool.code != "type-mismatch":
            failures.append(f"真假→数变型应判 type-mismatch,实得 {r_bool.gate}/{r_bool.code}")
        real_intact("真假→数变型")

        # 同型布尔改值要过(true ← false)
        r_bool_ok = fit(target, "把 debug 改成 true", shadow_dir=tdp)
        if not r_bool_ok.applied:
            failures.append(f"同型布尔改值竟没过:{r_bool_ok.gate}/{r_bool_ok.code}")
        real_intact("同型布尔改值")

        # write_shadow=False:验收看效果但连影子都不写(供 replay 零副作用)
        r_dry = fit(target, "把 version 改成 3.0", write_shadow=False, shadow_dir=tdp)
        if not r_dry.applied or r_dry.shadow != "":
            failures.append(f"dry 应过闸但不落影子,实得 applied={r_dry.applied} shadow={r_dry.shadow!r}")
        real_intact("dry 验收")

        # 原文档不是合法 JSON → bad-base(绝不抛错)
        broken = tdp / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        r_broken = fit(broken, "把 a 改成 1", shadow_dir=tdp)
        if r_broken.applied or r_broken.code != "bad-base":
            failures.append(f"坏 JSON 应判 bad-base,实得 {r_broken.gate}/{r_broken.code}")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ intentpatch selfcheck:人话编出受限补丁、靶点/保型/编译三闸各拦住该拦的、全程真身字节不变——意图编译器可信。")
        else:
            print("❌ intentpatch selfcheck 失败:")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    print("🧭🩹  brain 意图→补丁编译器 —— 几句人话各编一条受限 JSON Patch:\n")
    print(f"   只生成 {ALLOWED_OP} 一种操作、只一条;文法外/新增/删除一律弃权\n")
    samples = [
        "把 version 改成 2.0",
        "把 server.port 设为 9090",
        "set name to crab",
        "删掉 debug 字段",
        "新增一个 timeout 字段",
    ]
    for s in samples:
        c = compile_intent(s)
        if c.compiled:
            print(f"  🟢 「{s}」\n      → {json.dumps(c.patch, ensure_ascii=False)}")
        else:
            print(f"  ⚪ 「{s}」\n      → 弃权（{c.code}）：{RULE_CODES.get(c.code, c.detail)}")
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab brain 意图→补丁编译器 🧭🩹")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检:人话编出受限补丁 / 三道闸各拦住该拦的 / 全程真身字节不变(供 evidence 复跑)")
    ap.add_argument("--json", action="store_true", help="机读:意图文法 + 受限规则")
    ap.add_argument("--compile", metavar="TEXT", help="只编译一句人话,打印 JSON Patch(不碰任何文件)")
    ap.add_argument("--fit", nargs=2, metavar=("PATH", "TEXT"),
                    help="对 PATH(真仓库内 JSON)按 TEXT 试穿,只写影子(真身不动)")
    ap.add_argument("--quiet", action="store_true", help="静默,仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if _selfcheck(quiet=args.quiet) else 1)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if args.compile is not None:
        c = compile_intent(args.compile)
        if not args.quiet:
            if c.compiled:
                print(json.dumps(c.patch, ensure_ascii=False, indent=2))
            else:
                print(f"弃权（{c.code}）：{c.detail}")
        sys.exit(0 if c.compiled else 1)

    if args.fit is not None:
        path, text = args.fit
        r = fit(path, text)
        if not args.quiet:
            mark = "🟢 过闸落影子" if r.applied else f"🔴 拒（{r.gate}/{r.code}）"
            print(f"{mark} —— {r.detail}")
            if r.applied:
                print(f"   补丁: {json.dumps(r.patch, ensure_ascii=False)}")
                print(f"   影子: {r.shadow}")
                if r.diff:
                    print(r.diff)
        sys.exit(0 if r.applied else 1)

    if not args.quiet:
        _demo()


if __name__ == "__main__":
    main()
