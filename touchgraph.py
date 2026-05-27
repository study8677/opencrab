#!/usr/bin/env python3
"""多文件触点闸 🕸️🚦 —— 跨边界动手前先画文件依赖触点图，只放行低耦合的两文件内原子补丁。

为什么要有它：到今天为止，brain-only 自生手已会稳稳落**单点爪**——`intentpatch` 编一处
受限改值、`astrewriter` 按函数节点最小替换、`patchcontract`/`touch` 把畸形/越界/新副作用
拦在门外。可它们都默认**一爪只动一个文件**：一旦一处小修的影响顺着 import 漫到第二个文件，
现有的闸全摸不到——它们各自只看一份候选源码，看不见「这两个文件之间到底有多缠」。断奶的下一步
不是改得更狠，而是先学会**安全地跨边界**：在动手之前，先把这批要碰的文件之间的依赖**触点**摊开
画一张图，凭这张图判一句更朴素的话——**「这一爪跨的边界，浅到可以原子地一起改吗？」**

本层就是那道闸。它纯静态、纯内存地（只 `ast.parse`，**绝不执行**任何候选）把一批目标文件
之间的 import 触点采成一张有向带权图，再据图判「放行 / 拒收」：

  1) 🎯 **文件数闸(fan-out)**：一次原子补丁最多碰 **2 个文件**。碰 3 个及以上，触面太散、
     边界太多，brain-only 此刻担不起——当场拒，留给以后（或降级外援）。
  2) 🕸️ **触点图(graph)**：对这 2 个文件，数清彼此之间的 import 触点——f1 从 f2 引了几个名字
     （`import f2` 记 1，`from f2 import a, b` 记 2），反向同理。只认**仓内**模块的边，
     标准库/第三方不算耦合。
  3) 🔗 **耦合闸(coupling)**：
     · **双向依赖(环)** —— 两文件互相 import，是最危险的缠：原子地一起改极易顾此失彼，当场拒。
     · **耦合过深** —— 单向触点的权重之和越过阈值（默认 3），说明一个文件密集依赖另一个，
       不是「浅浅搭一根线」，拒。
     · 其余（无边 / 一根细线）才算**低耦合**，放行——两文件内的原子补丁可以安全地一起落。

设计与全家一致：零第三方依赖、纯标准库；**默认收紧**——除非证到「≤2 文件且低耦合」，
否则一律不放行。读不出（.py 解析失败/文件不存在）就**保守拒收**而非弃权：跨边界的事，
摸不清就不许过——这道闸自己绝不能成为蒙眼跨界的第一道伤口；validate 永不抛错，
任何意外形态都收敛成「拒收」。

用法:
    python touchgraph.py                      # 演示：几组目标各判一遍（单文件/低耦合/深耦合/环/太散）
    python touchgraph.py --selfcheck          # 自检：文件数/耦合/环/读不出各闸都判得对
    python touchgraph.py --json               # 机读：阈值 + 规则码清单
    python touchgraph.py --gate A.py B.py     # 对真仓库内这批文件判放行/拒收，并打印触点图
    python touchgraph.py --graph A.py B.py    # 只画触点图（含各文件的仓内依赖邻居），不判闸
    加 --quiet 静默，仅以退出码表态。
"""
from __future__ import annotations

import argparse
import ast
import collections
import dataclasses
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# ── 阈值：一爪最多碰几个文件、单向触点深到哪算「不再低耦合」 ──────────────────────
DEFAULT_MAX_FILES = 2        # 一次原子补丁最多碰的文件数（碰更多 → 触面太散，拒）
DEFAULT_MAX_COUPLING = 3     # 两文件间单向 import 触点权重之和的上限（越线 → 耦合过深，拒）

# 规则码 → 一句话含义（账本/外部消费同一份真相源）
RULE_CODES: dict[str, str] = {
    "empty": "没给任何目标文件 —— 无从判这一爪跨不跨边界",
    "fan-out": "一爪碰了 >2 个文件 —— 触面太散、边界太多，brain-only 此刻担不起",
    "unreadable": "目标文件读不到 —— 摸不清触点，跨边界的事保守拒收",
    "parse-error": "某个 .py 目标语法坏、解析不出 —— 触点摸不清，保守拒收（先单文件修语法）",
    "circular-coupling": "两文件互相 import（环）—— 最危险的缠，原子地一起改极易顾此失彼，拒",
    "high-coupling": "两文件单向触点过深 —— 不是浅浅一根线，超出「低耦合」可担的面，拒",
}


@dataclasses.dataclass(frozen=True)
class TouchVerdict:
    """一次多文件触点闸裁决：放行还是拒收，凭触点图判在哪条规则上。"""
    ok: bool
    code: str                       # 放行 → ""；拒 → 点名规则码
    reason: str                     # 一句人话
    files: list[str]                # 这一爪要碰的文件（模块名，已去重排序）
    edges: list[tuple[str, str, int]]  # 触点边：(from, to, 权重) —— 仅目标文件之间
    coupling: int                   # 目标文件之间触点权重之和（单文件/无边 → 0）

    def to_meta(self) -> dict:
        return {"ok": self.ok, "code": self.code, "reason": self.reason,
                "files": self.files, "edges": [list(e) for e in self.edges],
                "coupling": self.coupling}


def repo_modules(repo: pathlib.Path) -> set[str]:
    """仓内可被 import 的顶层模块名：根目录每个 *.py 的 stem + 每个含 __init__.py 的包目录名。"""
    mods: set[str] = set()
    try:
        for p in repo.glob("*.py"):
            mods.add(p.stem)
        for d in repo.iterdir():
            if d.is_dir() and (d / "__init__.py").exists():
                mods.add(d.name)
    except OSError:
        pass
    return mods


def _imports_of(src: str, repo_mods: set[str]) -> collections.Counter:
    """摸出一份源码对**仓内**模块的 import 触点：模块名 → 引用权重。

    `import foo` / `import foo.bar` 记 foo 一次；`from foo import a, b` 记 foo 两次（按引入的名字数）。
    只认 `repo_mods` 里的顶层名（标准库/第三方不算耦合）；解析不出则抛 SyntaxError 交上层处置。
    """
    refs: collections.Counter = collections.Counter()
    tree = ast.parse(src)   # 故意不吞 SyntaxError：解析不出是「摸不清」，由上层判 parse-error
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in repo_mods:
                    refs[top] += 1
        elif isinstance(node, ast.ImportFrom):
            # 只认绝对 import（level==0）的仓内顶层模块；相对 import 不跨根目录边界，按内部处理略过
            if node.level == 0 and node.module:
                top = node.module.split(".")[0]
                if top in repo_mods:
                    refs[top] += len(node.names)
    return refs


def _resolve(repo: pathlib.Path, raw: str) -> pathlib.Path:
    """把一个文件实参解析成绝对路径（绝对路径原样用，否则按仓根拼）。"""
    p = pathlib.Path(raw)
    return p if p.is_absolute() else (repo / p)


@dataclasses.dataclass(frozen=True)
class TouchGraph:
    """一批目标文件的依赖触点图：节点、目标间的边、各文件的仓内依赖邻居。"""
    nodes: list[str]                          # 目标文件模块名
    inner_edges: list[tuple[str, str, int]]   # 仅目标文件**之间**的触点边 (from, to, w)
    neighbors: dict[str, list[str]]           # 每个目标文件 import 的其它仓内模块（含目标外的）

    def to_meta(self) -> dict:
        return {"nodes": self.nodes,
                "inner_edges": [list(e) for e in self.inner_edges],
                "neighbors": {k: sorted(v) for k, v in self.neighbors.items()}}


def build_graph(files, *, repo: pathlib.Path | None = None) -> TouchGraph:
    """对一批文件画触点图：目标文件之间的边 + 各自的仓内依赖邻居。

    永不抛错——读不到/.py 解析不出的文件，按「无可见依赖」收（neighbors 空），
    判闸的保守拒收交给 gate()，画图本身只如实呈现摸得到的部分。
    """
    repo = pathlib.Path(repo) if repo else REPO_ROOT
    mods = repo_modules(repo)
    # 去重并保序：同一文件给两遍只算一个节点
    seen: list[str] = []
    paths: dict[str, pathlib.Path] = {}
    for raw in files:
        path = _resolve(repo, raw)
        name = path.stem
        if name not in paths:
            seen.append(name)
            paths[name] = path

    refs_by_file: dict[str, collections.Counter] = {}
    for name, path in paths.items():
        try:
            if path.suffix != ".py" or not path.exists():
                refs_by_file[name] = collections.Counter()   # 非 .py / 不存在：无 import 触点
                continue
            refs_by_file[name] = _imports_of(path.read_text(encoding="utf-8"), mods)
        except (OSError, SyntaxError):
            refs_by_file[name] = collections.Counter()        # 读不出/解析坏：画图按空收，判闸另算

    target_set = set(seen)
    inner_edges: list[tuple[str, str, int]] = []
    neighbors: dict[str, list[str]] = {}
    for name in seen:
        refs = refs_by_file[name]
        neighbors[name] = sorted(m for m in refs if m != name)
        for dst, w in refs.items():
            if dst != name and dst in target_set:
                inner_edges.append((name, dst, w))
    return TouchGraph(seen, inner_edges, neighbors)


def gate(files, *, repo: pathlib.Path | None = None,
         max_files: int = DEFAULT_MAX_FILES,
         max_coupling: int = DEFAULT_MAX_COUPLING) -> TouchVerdict:
    """凭触点图判这一爪跨的边界：≤2 文件且低耦合才放行，否则拒。

    默认收紧——读不出/解析坏/碰太多文件/缠得太深，一律不放行。永不抛错。
    """
    try:
        repo = pathlib.Path(repo) if repo else REPO_ROOT
        # 去重保序：同一文件重复给只算一次
        names: list[str] = []
        paths: dict[str, pathlib.Path] = {}
        for raw in files or []:
            path = _resolve(repo, raw)
            name = path.stem
            if name not in paths:
                names.append(name)
                paths[name] = path

        if not names:
            return TouchVerdict(False, "empty", RULE_CODES["empty"], [], [], 0)

        # ── 闸 1) 文件数：碰太多文件，触面太散，当场拒（先报触面，最直观） ──
        if len(names) > max_files:
            return TouchVerdict(False, "fan-out",
                                f"{RULE_CODES['fan-out']}（碰了 {len(names)} 个 > {max_files}）",
                                names, [], 0)

        # ── 摸触点：每个 .py 目标都得读得到、解析得出，否则保守拒（跨界摸不清不许过） ──
        mods = repo_modules(repo)
        refs_by_file: dict[str, collections.Counter] = {}
        for name in names:
            path = paths[name]
            if path.suffix != ".py":
                refs_by_file[name] = collections.Counter()    # 非 .py（文档/JSON）：无 import 触点，记空
                continue
            if not path.exists():
                return TouchVerdict(False, "unreadable",
                                    f"{RULE_CODES['unreadable']}（{name}）", names, [], 0)
            try:
                src = path.read_text(encoding="utf-8")
            except OSError:
                return TouchVerdict(False, "unreadable",
                                    f"{RULE_CODES['unreadable']}（{name}）", names, [], 0)
            try:
                refs_by_file[name] = _imports_of(src, mods)
            except SyntaxError:
                return TouchVerdict(False, "parse-error",
                                    f"{RULE_CODES['parse-error']}（{name}）", names, [], 0)

        # ── 单文件：本就是已会稳落的单点爪，无跨界可言，直接放行 ──
        if len(names) == 1:
            return TouchVerdict(True, "", f"单文件 {names[0]} —— 单点爪无跨界，放行",
                                names, [], 0)

        # ── 两文件：数清彼此之间的触点，判环 / 判深 / 判低耦合 ──
        f1, f2 = names
        w12 = refs_by_file[f1].get(f2, 0)   # f1 引 f2 的权重
        w21 = refs_by_file[f2].get(f1, 0)   # f2 引 f1 的权重
        edges: list[tuple[str, str, int]] = []
        if w12:
            edges.append((f1, f2, w12))
        if w21:
            edges.append((f2, f1, w21))
        coupling = w12 + w21

        if w12 and w21:    # 双向依赖（环）：最危险的缠，原子地一起改极易顾此失彼
            return TouchVerdict(False, "circular-coupling",
                                f"{RULE_CODES['circular-coupling']}（{f1}↔{f2}）",
                                names, edges, coupling)
        if coupling > max_coupling:
            return TouchVerdict(False, "high-coupling",
                                f"{RULE_CODES['high-coupling']}（触点权重 {coupling} > {max_coupling}）",
                                names, edges, coupling)

        if coupling == 0:
            why = f"两文件 {f1}、{f2} 之间无 import 触点 —— 互不依赖，原子同改安全，放行"
        else:
            why = f"两文件单向触点浅（权重 {coupling} ≤ {max_coupling}）—— 低耦合，原子同改安全，放行"
        return TouchVerdict(True, "", why, names, edges, coupling)
    except Exception as e:  # noqa: BLE001 —— 闸绝不能崩，意外即收敛为保守拒收
        return TouchVerdict(False, "parse-error",
                            f"判触点时出意外，保守拒收：{type(e).__name__}: {e}",
                            [], [], 0)


def allows(files, **kw) -> bool:
    """便捷断言：这一爪跨的边界，触点闸放行吗（供调用方一行判放/拒）。"""
    return gate(files, **kw).ok


def manifest() -> dict:
    """机读：阈值 + 规则码清单（给 health / 外部消费）。"""
    return {
        "max_files": DEFAULT_MAX_FILES,
        "max_coupling": DEFAULT_MAX_COUPLING,
        "coupling_unit": "目标文件之间单向 import 触点权重之和（import 记 1，from-import 按引入名字数记）",
        "scope": "只认仓内顶层模块（绝对 import，level==0）的边；标准库/第三方/相对 import 不算耦合",
        "default": "收紧——除非证到 ≤2 文件且低耦合，否则一律拒；读不出/解析坏 → 保守拒收（非弃权）",
        "gates": ["fan-out", "unreadable/parse-error", "circular-coupling", "high-coupling"],
        "rules": RULE_CODES,
    }


# ── 自检：文件数/耦合/环/读不出各闸都判得对，低耦合该放的放 ──────────────────────
def _selfcheck(quiet: bool = False) -> bool:
    """自检：在隔离临时仓里搭出各种触点形态，逐一断言触点闸判得对。

    供 evidence 复跑。无副作用、确定性、毫秒级（只 ast.parse 内存里的假仓，绝不执行）。
    """
    import tempfile
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        # 搭一个假仓：a 无依赖；b 浅依赖 a（引 1 个名）；c 深依赖 a（引 4 个名）；
        # d 与 e 互相 import（环）；solo 谁也不碰；doc.md 非 .py
        (repo / "a.py").write_text("X = 1\nY = 2\nZ = 3\nW = 4\n", encoding="utf-8")
        (repo / "b.py").write_text("from a import X\n\ndef f():\n    return X\n", encoding="utf-8")
        (repo / "c.py").write_text("from a import X, Y, Z, W\n\ndef g():\n    return X + Y + Z + W\n", encoding="utf-8")
        (repo / "d.py").write_text("import e\n\ndef h():\n    return e\n", encoding="utf-8")
        (repo / "e.py").write_text("import d\n\ndef k():\n    return d\n", encoding="utf-8")
        (repo / "solo.py").write_text("VALUE = 42\n", encoding="utf-8")
        (repo / "doc.md").write_text("# just a doc\n", encoding="utf-8")
        (repo / "broken.py").write_text("def oops(:\n    pass\n", encoding="utf-8")

        def expect(files, ok, code, label):
            v = gate(files, repo=repo)
            if v.ok != ok:
                failures.append(f"「{label}」应判 ok={ok}，实得 ok={v.ok}（{v.code}/{v.reason}）")
            elif not ok and v.code != code:
                failures.append(f"「{label}」拒收码应为 {code}，实得 {v.code}")

        # —— 单文件：单点爪无跨界，放行 ——
        expect(["a.py"], True, "", "单文件")
        # —— 两文件无触点：互不依赖，放行 ——
        expect(["a.py", "solo.py"], True, "", "两文件无触点")
        # —— 两文件浅触点（b 引 a 一个名，权重 1 ≤ 3）：低耦合，放行 ——
        expect(["a.py", "b.py"], True, "", "两文件浅触点")
        # —— py + 非 py（文档）：无 import 触点，放行 ——
        expect(["a.py", "doc.md"], True, "", "py + 文档")
        # —— 两文件深触点（c 引 a 四个名，权重 4 > 3）：耦合过深，拒 ——
        expect(["a.py", "c.py"], False, "high-coupling", "两文件深触点")
        # —— 两文件互相 import（环）：最危险的缠，拒 ——
        expect(["d.py", "e.py"], False, "circular-coupling", "两文件成环")
        # —— 碰三个文件：触面太散，拒 ——
        expect(["a.py", "b.py", "solo.py"], False, "fan-out", "碰三个文件")
        # —— 文件不存在：摸不清触点，保守拒 ——
        expect(["a.py", "ghost.py"], False, "unreadable", "文件不存在")
        # —— .py 语法坏、解析不出：保守拒（先单文件修语法）——
        expect(["a.py", "broken.py"], False, "parse-error", "目标语法坏")
        # —— 没给文件：拒 ——
        expect([], False, "empty", "空目标")

        # —— 触点图本身：边与耦合数对不对 ——
        v_shallow = gate(["a.py", "b.py"], repo=repo)
        if v_shallow.edges != [("b", "a", 1)] or v_shallow.coupling != 1:
            failures.append(f"浅触点的边应为 [('b','a',1)]、coupling=1，实得 {v_shallow.edges}/{v_shallow.coupling}")
        v_deep = gate(["a.py", "c.py"], repo=repo)
        if v_deep.coupling != 4:
            failures.append(f"深触点 coupling 应为 4，实得 {v_deep.coupling}")

        # —— 去重：同一文件给两遍只算一个节点（仍是单文件放行，不误判成 fan-out）——
        v_dup = gate(["a.py", "a.py"], repo=repo)
        if not v_dup.ok or v_dup.files != ["a"]:
            failures.append(f"重复给同一文件应去重为单文件放行，实得 ok={v_dup.ok} files={v_dup.files}")

        # —— build_graph：邻居与内部边如实呈现，且永不抛错（含坏文件）——
        g = build_graph(["b.py", "c.py", "broken.py"], repo=repo)
        if g.neighbors.get("b") != ["a"] or g.neighbors.get("c") != ["a"]:
            failures.append(f"build_graph 邻居不对：{g.neighbors}")
        if g.neighbors.get("broken") != []:
            failures.append(f"坏文件应按空邻居收，实得 {g.neighbors.get('broken')}")

    # —— validate 永不抛错：怪异输入都收敛成拒收 ——
    for weird in [None, [None], [123], "a.py"]:
        try:
            v = gate(weird)
            if v.ok:
                failures.append(f"怪异输入 {weird!r} 竟被放行，危险")
        except Exception as e:  # noqa: BLE001
            failures.append(f"怪异输入 {weird!r} 竟抛错 {type(e).__name__}，闸不该崩")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ touchgraph selfcheck：单文件放行、低耦合两文件放行、深耦合/环/太散/读不出各被拒在该拦的闸上——多文件触点闸可信。")
        else:
            print("❌ touchgraph selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    print("🕸️🚦  多文件触点闸 —— 凭文件依赖触点图判这一爪跨不跨得起边界：\n")
    print(f"   阈值：一爪 ≤ {DEFAULT_MAX_FILES} 文件、两文件间单向触点权重 ≤ {DEFAULT_MAX_COUPLING}；默认收紧，证到低耦合才放行\n")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        (repo / "a.py").write_text("X = 1\nY = 2\nZ = 3\nW = 4\n", encoding="utf-8")
        (repo / "b.py").write_text("from a import X\n", encoding="utf-8")
        (repo / "c.py").write_text("from a import X, Y, Z, W\n", encoding="utf-8")
        (repo / "d.py").write_text("import e\n", encoding="utf-8")
        (repo / "e.py").write_text("import d\n", encoding="utf-8")
        (repo / "solo.py").write_text("V = 0\n", encoding="utf-8")
        samples = [
            ("单文件（单点爪）", ["a.py"]),
            ("两文件浅触点（低耦合）", ["a.py", "b.py"]),
            ("两文件深触点（耦合过深）", ["a.py", "c.py"]),
            ("两文件成环（互相 import）", ["d.py", "e.py"]),
            ("碰三个文件（触面太散）", ["a.py", "b.py", "solo.py"]),
        ]
        for label, files in samples:
            v = gate(files, repo=repo)
            mark = "🟢 放行" if v.ok else f"🔴 拒（{v.code}）"
            edges = "  ".join(f"{a}→{b}×{w}" for a, b, w in v.edges) or "（无内部触点）"
            print(f"  {label}\n      {mark} —— {v.reason}\n      触点：{edges}")
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 多文件触点闸 🕸️🚦")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：文件数/耦合/环/读不出各闸都判得对（供 evidence 复跑）")
    ap.add_argument("--json", action="store_true", help="机读：阈值 + 规则码清单")
    ap.add_argument("--gate", nargs="+", metavar="FILE",
                    help="对这批真仓库内文件判放行/拒收，并打印触点图")
    ap.add_argument("--graph", nargs="+", metavar="FILE",
                    help="只画触点图（含各文件的仓内依赖邻居），不判闸")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if _selfcheck(quiet=args.quiet) else 1)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if args.graph is not None:
        g = build_graph(args.graph)
        if not args.quiet:
            print(json.dumps(g.to_meta(), ensure_ascii=False, indent=2))
        return

    if args.gate is not None:
        v = gate(args.gate)
        if not args.quiet:
            mark = "🟢 放行" if v.ok else f"🔴 拒（{v.code}）"
            print(f"{mark} —— {v.reason}")
            print(f"   文件：{v.files}")
            edges = "  ".join(f"{a}→{b}×{w}" for a, b, w in v.edges) or "（无内部触点）"
            print(f"   触点：{edges}    耦合权重：{v.coupling}")
        sys.exit(0 if v.ok else 1)

    if not args.quiet:
        _demo()


if __name__ == "__main__":
    main()
