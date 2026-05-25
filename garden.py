#!/usr/bin/env python3
"""仓库园丁 🌱🧹 —— 在领地悄悄熵增之前，把杂草理成一张「可验收的养护小单」。

为什么要有它：opencrab 每天自改一个模块，向前长得很快——但「向前长」和「不腐烂」
是两件事。新写的 TODO 没人回头收，重构后没人调用的孤儿函数赖在文件里，新加的脚本
入口从没进过回归网，文档比它描述的代码还旧……这些都不报错、不崩，只是让领地一寸寸
长出杂草。日子久了，「我以为的整洁」和「真实的整洁」裂开缝，越裂越大。

园丁**不执行**任何东西，只做静态巡园（AST + 文本，零第三方依赖），把四类杂草各开一张
**养护小单**——每张都带「在哪、什么状况、怎样算修好（可机检的验收线）」，让养护不靠感觉：

  · 🏷️ **待办积压** —— 代码里的 TODO/FIXME/XXX/HACK 标记，逐条定位到文件:行。
                       验收：解决后该处不再出现此标记。
  · 🧟 **孤儿函数** —— 模块级 def，名字在全仓任何地方都没被引用过（连自己模块都没）。
                       验收：要么有人调用，要么删掉——别让死代码占地。
  · 🕸️ **裸入口**   —— 有 `__main__` 入口的模块，名字却没进 regression/smoke 的防退化网。
                       验收：在 regression.py 或 smoke.py 里给它织一条兜底。
  · 📜 **过期文档** —— markdown 文档的改动时间，早于它正文点名的某个 .py 文件。
                       验收：把文档刷新到不老于它描述的代码。

每张小单还估一个工时档（小/中），方便夹缝里顺手清。它只读、不落盘、不改任何文件——
**要不要拔这棵草，最终仍由我自己拍板。** 与 docsync(对账自述真伪) 互补：docsync 管
「说的和做的对不对得上」，garden 管「领地有没有在悄悄长草」。

用法:
    python garden.py            # 全量巡园，按类列出每一张养护小单
    python garden.py --kind todo  # 只看某一类(todo/orphan/entry/doc)
    python garden.py --quiet    # 只在有杂草时说话(适合钩子 / CI)
    python garden.py --json     # 导出纯数据(给 health / 外部工具消费)

退出码：0 = 领地干净(无养护小单)；1 = 有草待养护。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 防退化网：模块名出现在这两份里，就算被兜底了（沿用 prioritizer 的判定口径）。
COVERAGE_FILES = ("regression.py", "smoke.py")

# 自动产出 / 体量巨大的模块不当作「领地」巡园，免得满屏噪声。
SKIP_FILES = {pathlib.Path(__file__).name}

# 待办标记：行内注释里的这些词都算积压。
_TODO_RE = re.compile(r"#.*\b(TODO|FIXME|XXX|HACK)\b[:：]?\s*(.*)", re.IGNORECASE)

# 孤儿函数豁免名单：这些名字天生「不被显式引用也正常」。
_ORPHAN_EXEMPT = {"main"}

# ── 养护小单类型 ──────────────────────────────────────────────────────
KIND_TODO = "todo"
KIND_ORPHAN = "orphan"
KIND_ENTRY = "entry"
KIND_DOC = "doc"

_KIND_LABEL = {
    KIND_TODO: ("🏷️", "待办积压"),
    KIND_ORPHAN: ("🧟", "孤儿函数"),
    KIND_ENTRY: ("🕸️", "裸入口"),
    KIND_DOC: ("📜", "过期文档"),
}
_KIND_ORDER = (KIND_TODO, KIND_ENTRY, KIND_ORPHAN, KIND_DOC)


@dataclasses.dataclass(frozen=True)
class Chore:
    """一张养护小单：哪类草、长在哪、什么状况、怎样算修好、估多大工。"""
    kind: str       # 类型(上面四种之一)
    target: str     # 定位(文件:行 / 函数名 / 文档名)
    detail: str     # 现状一句话
    accept: str     # 验收线：一句可机检的「怎样算修好」
    effort: str     # 工时档：小 / 中

    def to_meta(self) -> dict:
        return {"kind": self.kind, "target": self.target, "detail": self.detail,
                "accept": self.accept, "effort": self.effort}


# ── 巡园所需的领地快照 ────────────────────────────────────────────────
def _repo_py_files() -> list[pathlib.Path]:
    """根目录下的一级 .py 文件（不递归子包，那是各自家族的事），剔除自身。"""
    return sorted(p for p in REPO_ROOT.glob("*.py") if p.name not in SKIP_FILES)


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text("utf-8", errors="ignore")
    except Exception:
        return ""


def _parse(text: str) -> ast.AST | None:
    """容错解析：语法不全的文件跳过而非崩（园丁不该被一处坏文件挡在门外）。"""
    try:
        return ast.parse(text)
    except Exception:
        return None


# ── 🏷️ 待办积压：逐条 TODO/FIXME 定位到文件:行 ───────────────────────
def _scan_todos(files: list[pathlib.Path]) -> list[Chore]:
    chores: list[Chore] = []
    for p in files:
        for lineno, line in enumerate(_read(p).splitlines(), 1):
            m = _TODO_RE.search(line)
            if not m:
                continue
            tag = m.group(1).upper()
            note = m.group(2).strip() or "（无说明）"
            note = note if len(note) <= 60 else note[:57] + "…"
            chores.append(Chore(
                KIND_TODO, f"{p.name}:{lineno}",
                f"{tag}：{note}",
                f"解决后 {p.name}:{lineno} 附近不再有 {tag} 标记",
                "小"))
    return chores


# ── 🧟 孤儿函数：全仓零引用的模块级 def ──────────────────────────────
def _module_level_defs(tree: ast.AST) -> list[tuple[str, int, bool]]:
    """模块顶层的 def/async def：返回 (名字, 行号, 是否带装饰器)。

    带装饰器的另眼相看——它可能被框架/注册表按名收走（如 @register），引用看不见。
    """
    out: list[tuple[str, int, bool]] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, node.lineno, bool(node.decorator_list)))
    return out


def _all_referenced_names(files: list[pathlib.Path]) -> dict[str, int]:
    """全仓每个标识符被「引用」的次数（Name 取值 + 属性访问的尾名）。

    只数引用、不数定义：def/class 的名字本身、形参名都不计，这样定义点不会自抵消。
    """
    counts: dict[str, int] = {}
    for p in files:
        tree = _parse(_read(p))
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                counts[node.id] = counts.get(node.id, 0) + 1
            elif isinstance(node, ast.Attribute):
                counts[node.attr] = counts.get(node.attr, 0) + 1
    return counts


def _scan_orphans(files: list[pathlib.Path]) -> list[Chore]:
    refs = _all_referenced_names(files)
    chores: list[Chore] = []
    for p in files:
        tree = _parse(_read(p))
        if tree is None:
            continue
        for name, lineno, decorated in _module_level_defs(tree):
            if name in _ORPHAN_EXEMPT or name.startswith("__"):
                continue
            if refs.get(name, 0) > 0:
                continue   # 全仓任何地方被引用过 → 不是孤儿
            note = "（带装饰器，可能被注册表按名收走，先核对再删）" if decorated else ""
            chores.append(Chore(
                KIND_ORPHAN, f"{p.name}::{name}",
                f"模块级函数 `{name}` 全仓零引用{note}",
                f"为 `{name}` 找到调用方，或从 {p.name} 删除",
                "中" if decorated else "小"))
    return chores


# ── 🕸️ 裸入口：有 __main__ 却没进防退化网的模块 ─────────────────────
def _has_main_entry(tree: ast.AST) -> bool:
    """模块里有没有 `if __name__ == "__main__":` 这种可执行入口。"""
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
                and t.left.id == "__name__"):
            return True
    return False


def _coverage_text() -> str:
    """防退化网的全文：模块名出现在里头就算被兜底（读不到的就当空网）。"""
    parts = []
    for name in COVERAGE_FILES:
        parts.append(_read(REPO_ROOT / name))
    return "\n".join(parts)


def _scan_entries(files: list[pathlib.Path]) -> list[Chore]:
    net = _coverage_text()
    chores: list[Chore] = []
    for p in files:
        if p.name in COVERAGE_FILES:
            continue   # 防退化网自己不必被自己兜底
        tree = _parse(_read(p))
        if tree is None or not _has_main_entry(tree):
            continue
        if p.stem in net:
            continue   # 名字已在 regression/smoke 里被点到 → 算织进网了
        chores.append(Chore(
            KIND_ENTRY, p.name,
            f"`{p.name}` 有 __main__ 入口，却没进 regression/smoke 的防退化网",
            f"在 {' 或 '.join(COVERAGE_FILES)} 里给 `{p.stem}` 织一条兜底",
            "中"))
    return chores


# ── 📜 过期文档：改动早于它点名的代码 ─────────────────────────────────
def _doc_files() -> list[pathlib.Path]:
    """根目录的 markdown 自述文档（docs/ 下的生成产物不在巡园范围）。"""
    return sorted(REPO_ROOT.glob("*.md"))


def _scan_docs(py_files: list[pathlib.Path]) -> list[Chore]:
    """文档正文里点名某个 .py，而那个 .py 的改动时间晚于文档 → 文档可能过期。"""
    stem_to_path = {p.stem: p for p in py_files}
    chores: list[Chore] = []
    for doc in _doc_files():
        text = _read(doc)
        try:
            doc_mtime = doc.stat().st_mtime
        except OSError:
            continue
        newest: tuple[float, str] | None = None
        for m in re.finditer(r"\b([a-zA-Z_][\w]*)\.py\b", text):
            mod = stem_to_path.get(m.group(1))
            if mod is None:
                continue
            try:
                mt = mod.stat().st_mtime
            except OSError:
                continue
            if mt > doc_mtime and (newest is None or mt > newest[0]):
                newest = (mt, mod.name)
        if newest is not None:
            chores.append(Chore(
                KIND_DOC, doc.name,
                f"`{doc.name}` 比它点名的 `{newest[1]}` 还旧，可能已讲昨天的故事",
                f"复核 {doc.name} 中关于 {newest[1]} 的描述并刷新到不老于代码",
                "中"))
    return chores


# ── 巡园总入口 ────────────────────────────────────────────────────────
def scan(kind: str | None = None) -> list[Chore]:
    """全量巡园：四类杂草各扫一遍，收齐养护小单（可用 kind 只扫一类）。"""
    files = _repo_py_files()
    chores: list[Chore] = []
    if kind in (None, KIND_TODO):
        chores += _scan_todos(files)
    if kind in (None, KIND_ENTRY):
        chores += _scan_entries(files)
    if kind in (None, KIND_ORPHAN):
        chores += _scan_orphans(files)
    if kind in (None, KIND_DOC):
        chores += _scan_docs(files)
    return chores


def summarize(chores: list[Chore]) -> tuple[bool, int]:
    """归一化结论：是否无草、共几张小单。"""
    return (not chores, len(chores))


def manifest() -> dict:
    """导出纯数据（给 health / 外部工具消费）。"""
    chores = scan()
    by_kind: dict[str, int] = {}
    for c in chores:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
    return {"total": len(chores), "by_kind": by_kind,
            "chores": [c.to_meta() for c in chores]}


def render(chores: list[Chore]) -> str:
    L = ["🦀🌱 仓库园丁 · 养护小单",
         "   静态巡园，不执行不落盘；每张小单都带「怎样算修好」的验收线。"]
    if not chores:
        L.append("\n  ✅ 领地干净——没扫到待养护的杂草，继续向前长。")
        return "\n".join(L)
    by_kind: dict[str, list[Chore]] = {}
    for c in chores:
        by_kind.setdefault(c.kind, []).append(c)
    for kind in _KIND_ORDER:
        items = by_kind.get(kind, [])
        if not items:
            continue
        icon, label = _KIND_LABEL[kind]
        L.append(f"\n  {icon} {label}（{len(items)} 张）")
        for c in items:
            L.append(f"      · [{c.target}]  〔{c.effort}〕")
            L.append(f"        现状：{c.detail}")
            L.append(f"        验收：{c.accept}")
    L.append("\n—— 园丁只摆出该养护的草和验收线，拔不拔由我自己拍板。")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 仓库园丁 🌱🧹")
    ap.add_argument("--kind", choices=[KIND_TODO, KIND_ORPHAN, KIND_ENTRY, KIND_DOC],
                    default=None, help="只看某一类养护小单（默认四类全扫）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有草时输出（适合钩子 / CI）")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    chores = scan(args.kind)
    clean, n = summarize(chores)

    if not (args.quiet and clean):
        print(render(chores))
        print()

    if clean:
        if not args.quiet:
            print("🌱 干净：领地没在悄悄长草。")
    else:
        print(f"⚠️  巡园发现 {n} 张养护小单，挑可验收的先清，别让领地熵增。")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
