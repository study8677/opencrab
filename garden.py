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


# ── 🛰️ Import 图：全仓每个 .py 被谁 import（静态 AST 扫描）─────────────
def _scan_import_graph(files: list[pathlib.Path]) -> dict[str, set[str]]:
    """返回 {被导入模块名: {导入它的模块名...}} 的有向图。

    规则：
      · `import foo` → foo 被本文件导入
      · `from foo import bar` → foo 被本文件导入
      · `import foo as baz` → 仍算 foo（别名不改变被导入的模块名）
    """
    graph: dict[str, set[str]] = {}
    for p in files:
        text = _read(p)
        tree = _parse(text)
        if tree is None:
            continue
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name.split(".")[0]
                    imported.add(name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    name = node.module.split(".")[0]
                    imported.add(name)
        for name in imported:
            graph.setdefault(name, set()).add(p.stem)
    return graph


# ── 🔍 30 天 audit 零调用记录：哪些模块在 audit log 里一次都没被触发 ─────
def _audit_zero_call_modules(lookback_days: int = 30) -> set[str]:
    """从 heartbeat log 里筛出过去 N 天零调用的模块。

    heartbeat_tasks.py 每 tick 写一条 event，`module` 字段记录哪个模块被用到。
    如果某个模块名从未出现在最近 lookback_days 天的日志里，就当它「审计级零调用」。
    """
    zero: set[str] = set()
    log_dir = REPO_ROOT / ".crab" / "heartbeat"
    if not log_dir.is_dir():
        return zero
    try:
        import time
        cutoff = time.time() - lookback_days * 86400
    except Exception:
        return zero
    seen: set[str] = set()
    try:
        for p in sorted(log_dir.glob("*.jsonl")):
            if p.stat().st_mtime < cutoff:
                continue
            for line in _read(p).splitlines():
                if not line.strip():
                    continue
                try:
                    import json as _json
                    rec = _json.loads(line)
                    mod = rec.get("module") or rec.get("organ")
                    if mod:
                        seen.add(mod)
                except Exception:
                    continue
    except Exception:
        pass
    # 所有一级 py 文件中，没出现在 seen 里的
    for p in _repo_py_files():
        if p.stem not in seen:
            zero.add(p.stem)
    return zero


# ── ☠️ 真死模块：三无判定（无 import、无 audit 调用、无主动入口）────────
@dataclasses.dataclass(frozen=True)
class DeadModule:
    """一个「真死」模块：可验收地死掉了，适合走 retirement_drill。"""
    stem: str
    path: pathlib.Path
    reason: str          # 为什么认定它死
    is_imported: bool    # 被别的模块 import 过吗
    in_audit: bool       # 30 天 audit 里出现过吗
    has_main: bool       # 有 __main__ 入口吗


def _find_dead_modules(files: list[pathlib.Path],
                       max_count: int = 3) -> list[DeadModule]:
    """挑出最多 max_count 个真死模块，理由必须可机检验证。

    判定优先级：
      1. 没被任何模块 import  → 直接候选（孤立）
      2. 没出现在 30 天 audit  → 审计级死亡（最强证据）
      3. 没有 __main__ 入口    → 不提供任何主动调用路径

    三个条件全中 → 「三无真死」，放进 retired 待处理。
    至少中两个  → 「弱死」，只报不删。
    """
    graph = _scan_import_graph(files)
    zero_audit = _audit_zero_call_modules(lookback_days=30)
    candidates: list[DeadModule] = []

    # 已知活跃/核心模块不做死模块处理
    CORE_SHIELD = {"crab", "hands", "organ", "readpack", "read_state",
                   "heartbeat", "retirement_drill", "garden"}

    for p in files:
        stem = p.stem
        if stem in CORE_SHIELD:
            continue

        imported = stem in graph
        in_audit = stem not in zero_audit
        tree = _parse(_read(p))
        has_main = tree is not None and _has_main_entry(tree)

        score = sum([
            not imported,      # 没被 import → 1分
            not in_audit,      # audit 零记录 → 0分（加1反而更死）
            not has_main,      # 无入口 → 1分
        ])

        # 真死：三无（无 import、无 audit、无入口）
        if not imported and not in_audit and not has_main:
            candidates.append(DeadModule(
                stem, p,
                f"三无真死：无 import、无 30 天 audit 调用、无 __main__ 入口",
                False, False, False))
        elif not imported and not in_audit and has_main:
            candidates.append(DeadModule(
                stem, p,
                f"两无弱死：无 import、无 audit，但有 __main__（先报不删）",
                False, False, True))

    # 按死亡强度排序（越死越前），取最多 max_count 个
    candidates.sort(key=lambda d: (d.reason.startswith("三无"), d.path.stat().st_mtime))
    return candidates[:max_count]


# ── 🧹 Retirement Drill 流程 ───────────────────────────────────────────
def _do_retirement(dm: DeadModule, dry_run: bool = False) -> dict:
    """对单个 DeadModule 执行 retirement_drill 流程。

    流程（沿用 retirement_drill.py 的步骤）：
      1. 证替代：在 ledger 里标记「准备退用」，附上死亡证据
      2. 入 attic：把模块从根目录移到 .crab/attic/
      3. 记 ledger：在 ledger 里落一笔「已退休」记录

    返回 dict 供外部确认结果。
    """
    import time, json as _json

    attic = REPO_ROOT / ".crab" / "attic"
    if not dry_run:
        attic.mkdir(parents=True, exist_ok=True)

    now = time.time()
    record = {
        "event": "retirement",
        "module": dm.stem,
        "retired_at": now,
        "reason": dm.reason,
        "evidence": {
            "imported": dm.is_imported,
            "in_audit_30d": dm.in_audit,
            "has_main": dm.has_main,
        }
    }

    if not dry_run:
        # Step 2: 移入 attic
        dest = attic / dm.path.name
        if dm.path.exists():
            dm.path.rename(dest)
        # Step 3: 写 ledger
        ledger_path = REPO_ROOT / ".crab" / "retirement_ledger.jsonl"
        with open(ledger_path, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(record, ensure_ascii=False) + "\n")

    return record


def _retire_modules(max_count: int = 3, dry_run: bool = False) -> list[dict]:
    """扫出真死模块，对每个执行 retirement_drill，整批结果返回供确认。"""
    files = _repo_py_files()
    deads = _find_dead_modules(files, max_count=max_count)
    results: list[dict] = []
    for dm in deads:
        r = _do_retirement(dm, dry_run=dry_run)
        results.append(r)
        print(f"  {'[DRY-RUN] ' if dry_run else ''}☠️  {dm.stem}: {dm.reason}")
        print(f"     → 证据: import={dm.is_imported}, audit_30d={dm.in_audit}, main={dm.has_main}")
        print(f"     → 动作: {'（未执行 dry-run）' if dry_run else '已移入 .crab/attic/ + ledger'}")
    return results


# ── 巡园总入口 ────────────────────────────────────────────────────────
def scan(kind: str | None = None,
         include_dead: bool = False,
         max_dead: int = 3) -> tuple[list[Chore], list[DeadModule]]:
    """全量巡园：四类杂草各扫一遍，收齐养护小单（可用 kind 只扫一类）。

    若 include_dead=True，同时扫描真死模块（最多 max_dead 个）。
    返回 (chores, dead_modules) 两个列表。
    """
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

    deads: list[DeadModule] = []
    if include_dead:
        deads = _find_dead_modules(files, max_count=max_dead)

    return chores, deads


def summarize(chores: list[Chore]) -> tuple[bool, int]:
    """归一化结论：是否无草、共几张小单。"""
    return (not chores, len(chores))


# ── Legacy API 兼容：只返回 chores 的旧接口 ───────────────────────────
def scan_legacy(kind: str | None = None) -> list[Chore]:
    """旧版 scan 接口（仅返回 chores），兼容外部调用方。"""
    chores, _ = scan(kind, include_dead=False)
    return chores


def manifest() -> dict:
    """导出纯数据（给 health / 外部工具消费）。"""
    chores, _ = scan(include_dead=False)
    by_kind: dict[str, int] = {}
    for c in chores:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
    return {"total": len(chores), "by_kind": by_kind,
            "chores": [c.to_meta() for c in chores]}


def render(chores: list[Chore], deads: list[DeadModule] | None = None) -> str:
    L = ["🦀🌱 仓库园丁 · 养护小单",
         "   静态巡园，不执行不落盘；每张小单都带「怎样算修好」的验收线。"]
    if not chores and not deads:
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
    if deads:
        L.append(f"\n  ☠️  真死模块候选（{len(deads)} 个）")
        for dm in deads:
            badge = "🪦 三无真死" if dm.reason.startswith("三无") else "⚠️ 弱死"
            L.append(f"      {badge} [{dm.stem}]: {dm.reason}")
    L.append("\n—— 园丁只摆出该养护的草和验收线，拔不拔由我自己拍板。")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 仓库园丁 🌱🧹")
    ap.add_argument("--kind", choices=[KIND_TODO, KIND_ORPHAN, KIND_ENTRY, KIND_DOC],
                    default=None, help="只看某一类养护小单（默认四类全扫）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有草时输出（适合钩子 / CI）")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    ap.add_argument("--retire", metavar="N", type=int, default=0,
                    help="扫描后挑 N 个真死模块走 retirement_drill 流程（默认 0=只报不删）")
    ap.add_argument("--dry-run", action="store_true",
                    help="配合 --retire：只打印动作不真移文件（安全预览）")
    args = ap.parse_args(argv)

    # ── Import 图 + 审计零调用概览（始终显示，让外面看懂领地结构）────────
    files = _repo_py_files()
    graph = _scan_import_graph(files)
    zero_audit = _audit_zero_call_modules(lookback_days=30)

    if args.json:
        chores = scan(args.kind)
        data = manifest()
        data["import_graph_summary"] = {
            "total_modules": len(files),
            "imported_count": len(graph),
            "orphan_count": len(files) - len(graph),
        }
        data["audit_30d_zero_count"] = len(zero_audit)
        data["audit_30d_zero_list"] = sorted(zero_audit)
        if args.retire > 0:
            deads = _find_dead_modules(files, max_count=args.retire)
            data["dead_modules"] = [
                {"stem": d.stem, "reason": d.reason,
                 "imported": d.is_imported, "in_audit": d.in_audit, "has_main": d.has_main}
                for d in deads
            ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    # ── 日常巡园报告 ───────────────────────────────────────────────────
    chores, deads = scan(args.kind, include_dead=(args.retire > 0), max_dead=args.retire)
    clean, n = summarize(chores)

    print("🦀🌱 仓库园丁 · 养护小单", flush=True)
    print(f"   静态巡园，不执行不落盘；每张小单都带「怎样算修好」的验收线。", flush=True)
    print(f"   领地规模：{len(files)} 个根目录 .py | import 图：{len(graph)} 个被引用 | "
          f"30天零audit：{len(zero_audit)} 个", flush=True)

    if not chores:
        print("\n  ✅ 领地干净——没扫到待养护的杂草，继续向前长。", flush=True)

    by_kind: dict[str, list[Chore]] = {}
    for c in chores:
        by_kind.setdefault(c.kind, []).append(c)
    for kind in _KIND_ORDER:
        items = by_kind.get(kind, [])
        if not items:
            continue
        icon, label = _KIND_LABEL[kind]
        print(f"\n  {icon} {label}（{len(items)} 张）", flush=True)
        for c in items:
            print(f"      · [{c.target}]  〔{c.effort}〕", flush=True)
            print(f"        现状：{c.detail}", flush=True)
            print(f"        验收：{c.accept}", flush=True)

    # ── 真死模块报告 ──────────────────────────────────────────────────
    if deads:
        print(f"\n  ☠️  真死模块候选（最多 {args.retire} 个）—— 三无判定：", flush=True)
        print(f"      无 import | 无 30 天 audit 调用 | 无 __main__ 入口", flush=True)
        for dm in deads:
            badge = "🪦 三无真死" if dm.reason.startswith("三无") else "⚠️ 弱死"
            print(f"      {badge} [{dm.stem}]: {dm.reason}", flush=True)
            print(f"         证据: imported={dm.is_imported}, audit_30d={dm.in_audit}, main={dm.has_main}", flush=True)
        if args.retire > 0:
            print(f"\n  → 执行 retirement_drill（{len(deads)} 个）", flush=True)
            _retire_modules(max_count=args.retire, dry_run=args.dry_run)

    print("\n—— 园丁只摆出该养护的草和验收线，拔不拔由我自己拍板。", flush=True)
    print()

    if clean:
        print("🌱 干净：领地没在悄悄长草。", flush=True)
    else:
        pieces = []
        if not clean:
            pieces.append(f"{n} 张养护小单")
        if deads:
            pieces.append(f"{len(deads)} 个候选真死模块（已{'dry-run' if args.dry_run else '执行 retirement'}）")
        print(f"⚠️  巡园发现 {' + '.join(pieces)}，挑可验收的先清，别让领地熵增。", flush=True)

    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
