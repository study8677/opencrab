#!/usr/bin/env python3
"""能力图谱 🕸️ —— 把「模块 → 本事 → 验证证据 → 缺口」串成一张可核对的图。

罗盘(`compass.py`)负责「今天往哪走」，但它判断一个方向新不新，靠的是「近 N 次
意图里提没提过」——那是**记忆视角**：我最近碰没碰过它。这条图谱补的是另一只眼：
**能力视角**——我**到底会什么、缺什么**，跟我最近想没想它无关。

它不靠印象，靠领地里客观可读的四样东西，逐个模块自省：

  · 模块(module)    —— 领地根目录受管的 `*.py`。
  · 本事(skill)     —— 这个模块自称会做什么：取它的 docstring 首行(AST 解析，
                       不执行代码)。没有 docstring = 它连自己会啥都说不清。
  · 验证证据(proof) —— 有没有东西**真的跑过它、守着它的输出**：
                         回归(regression.CASES / SAMPLES 点名了它的命令)、
                         烟雾(smoke.py 的用例点名了它)、
                         文档(README 的命令块出现过它)、
                         能力(capabilities/cap_<名>.py 把它封装成可插拔能力)。
  · 缺口(gap)       —— 上面缺哪样就记哪样。最要命的一类是**有本事、没验证**：
                       它会做事，却没有任何样本兜底——它悄悄漂了我都不会知道。

图谱只**自省、给证据**，全程只读：不执行任何被测模块、不落盘、不改文件。
读完哪块能力是空的，仍由我自己决定补不补。

供 `compass.py` 取用：`skillgraph.gaps()` 直接给出「有本事却没验证证据」的模块
清单，让罗盘的「🥋 修炼」航道不再泛泛说「补 golden」，而是精确指到哪个模块。

用法：
    python skillgraph.py            # 打印整张能力图谱 + 缺口小结
    python skillgraph.py --gaps     # 只列缺口(有本事没验证的优先)
    python skillgraph.py --module X # 只看某个模块的能力档案
    python skillgraph.py --json     # 机读：导成 JSON

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# 验证证据的五个来源(显示名 → 实际文件)。顺序即渲染顺序。
_PROOF_LABELS = {
    "回归": "regression.py",
    "烟雾": "smoke.py",
    "亲验": "handsfeedback(回灌)",
    "文档": "README.md",
    "能力": "capabilities/",
}
# 「真跑过、守着输出」的硬证据：回归/烟雾是预置样本守着，亲验是「我刚亲手改过且
# 改完自测真跑通」的最新鲜实证——三者都算「有东西真验过它」；文档/能力只是「露过面」。
_HARD_PROOF = ("回归", "烟雾", "亲验")


# ── 读领地：模块清单 + 各自的本事 ──────────────────────────────────
def _modules() -> list[str]:
    """领地根目录受管的 .py 模块名(stem)，排除自己和私有文件。"""
    out = []
    for p in sorted(REPO_ROOT.glob("*.py")):
        stem = p.stem
        if stem == "skillgraph" or stem.startswith("_"):
            continue
        out.append(stem)
    return out


def _docstring_first_line(stem: str) -> str | None:
    """取模块 docstring 首行作为「本事」——用 AST 解析，绝不执行模块。"""
    p = REPO_ROOT / f"{stem}.py"
    try:
        tree = ast.parse(p.read_text("utf-8", errors="ignore"))
    except Exception:
        return None
    doc = ast.get_docstring(tree)
    if not doc:
        return None
    first = doc.strip().splitlines()[0].strip()
    return first or None


# ── 读领地：四样验证证据 ───────────────────────────────────────────
def _literal_strings(path: pathlib.Path, names: tuple[str, ...]) -> str:
    """把某文件里指定模块级赋值(如 CASES/SAMPLES)的所有字符串字面量拼成一锅。

    用 AST 精确锁定「验证用例清单」那几个变量，避免把模块 docstring 里顺口提到的
    名字误当成「被用例守着」——证据要硬，就不能靠全文 substring。
    """
    try:
        tree = ast.parse(path.read_text("utf-8", errors="ignore"))
    except Exception:
        return ""
    chunks: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if not (targets & set(names)):
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                chunks.append(sub.value)
    return "\n".join(chunks)


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text("utf-8", errors="ignore")
    except Exception:
        return ""


def _proven_modules() -> dict[str, dict]:
    """最近被亲手改过且自测跑通的模块(来自 handsfeedback 回灌)。

    尽力而为：回灌层缺席 / 账本空 / 出错，都退回空字典——图谱照旧静态自省，
    「亲验」只是有就锦上添花，绝不因它缺席而崩。
    """
    try:
        import handsfeedback
        return handsfeedback.proven_modules()
    except Exception:   # noqa: BLE001
        return {}


def _proof(stem: str, proven: dict[str, dict] | None = None) -> dict[str, str]:
    """这个模块有哪些验证证据？返回 {证据名: 具体凭据}，缺的不收。"""
    found: dict[str, str] = {}
    needle = f"{stem}.py"

    # 回归：只认 regression.CASES / SAMPLES 这两份用例清单里点名的命令
    reg_cases = _literal_strings(REPO_ROOT / "regression.py", ("CASES", "SAMPLES"))
    if needle in reg_cases:
        found["回归"] = "regression.py 的回归用例点名了它"

    # 烟雾：smoke.py 的 SAMPLES 用例清单
    smoke_cases = _literal_strings(REPO_ROOT / "smoke.py", ("SAMPLES",))
    if needle in smoke_cases:
        found["烟雾"] = "smoke.py 的烟雾用例点名了它"

    # 文档：README 命令块(整文件 substring 足够——README 里出现即视为露过面)
    if needle in _read(REPO_ROOT / "README.md"):
        found["文档"] = "README.md 提到了它的命令"

    # 能力：封装成可插拔能力
    if (REPO_ROOT / "capabilities" / f"cap_{stem}.py").exists():
        found["能力"] = f"capabilities/cap_{stem}.py"

    # 亲验：最近被亲手改过、且那次改动自测真跑通(最新鲜的实证)
    proven = _proven_modules() if proven is None else proven
    if stem in proven:
        hand = proven[stem].get("hand", "?")
        found["亲验"] = f"{hand} 刚亲手改过它且改完自测跑通"

    return found


def _gaps_for(skill: str | None, proof: dict[str, str]) -> list[str]:
    """这个模块缺哪几样。最要命的「有本事没验证」单列一条最显眼的。"""
    gaps: list[str] = []
    if skill is None:
        gaps.append("无本事描述：连 docstring 首行都没有，它会做什么全靠猜")
    has_hard = any(k in proof for k in _HARD_PROOF)
    if skill is not None and not has_hard:
        gaps.append("有本事·没验证：会做事却无回归/烟雾守着，它悄悄漂了都不会知道")
    if "文档" not in proof:
        gaps.append("没露面：README 里查不到它，外人(和未来的我)很难发现它")
    return gaps


# ── 组装整张图 ─────────────────────────────────────────────────────
def build(module: str | None = None) -> dict:
    """自省整个领地，算出每个模块的「本事/证据/缺口」档案(纯数据)。"""
    nodes: list[dict] = []
    proven = _proven_modules()   # 回灌账本只读一次，按模块分发，省得每模块都读盘
    for stem in _modules():
        if module and stem != module:
            continue
        skill = _docstring_first_line(stem)
        proof = _proof(stem, proven)
        nodes.append({
            "module": f"{stem}.py",
            "skill": skill,
            "proof": proof,
            "gaps": _gaps_for(skill, proof),
        })
    return {
        "modules": len(nodes),
        "nodes": nodes,
        "summary": _summary(nodes),
    }


def _summary(nodes: list[dict]) -> dict:
    unverified = [n["module"] for n in nodes
                  if n["skill"] and not any(k in n["proof"] for k in _HARD_PROOF)]
    undocumented = [n["module"] for n in nodes if "文档" not in n["proof"]]
    nameless = [n["module"] for n in nodes if n["skill"] is None]
    return {
        "unverified": unverified,        # 有本事却没硬验证——修炼航道的精确靶子
        "undocumented": undocumented,
        "nameless": nameless,
    }


def gaps() -> list[dict]:
    """供 compass 取用：当前「有本事却没验证证据」的模块，按缺口给方向。

    每条形如 {"module","skill","reason"}，reason 直接可写进罗盘的「为何」。
    """
    out: list[dict] = []
    for n in build()["nodes"]:
        if n["skill"] and not any(k in n["proof"] for k in _HARD_PROOF):
            out.append({
                "module": n["module"],
                "skill": n["skill"],
                "reason": "有本事却没有回归/烟雾守着——补一组样本，锁住它的输出",
            })
    return out


# ── 渲染 ───────────────────────────────────────────────────────────
def render(g: dict, only_gaps: bool = False) -> str:
    s = g["summary"]
    L = ["🦀🕸️ 能力图谱 · 我会什么 / 缺什么",
         f"   自省 {g['modules']} 个模块 ｜ "
         f"有本事没验证 {len(s['unverified'])} ｜ "
         f"没露面 {len(s['undocumented'])} ｜ "
         f"没本事描述 {len(s['nameless'])}"]

    if only_gaps:
        gg = gaps()
        L += ["", "🥋 有本事·没验证(修炼航道的精确靶子)："]
        if not gg:
            L.append("    （每个有本事的模块都被回归或烟雾守着——难得的扎实。）")
        for item in gg:
            L.append(f"    • {item['module']} —— {item['skill']}")
            L.append(f"        {item['reason']}")
        return "\n".join(L)

    for n in g["nodes"]:
        L += ["", f"● {n['module']}"]
        L.append(f"    本事：{n['skill'] or '（无 docstring，说不清自己会什么）'}")
        if n["proof"]:
            for label in _PROOF_LABELS:
                if label in n["proof"]:
                    mark = "✅" if label in _HARD_PROOF else "·"
                    L.append(f"    {mark} 验证·{label}：{n['proof'][label]}")
        else:
            L.append("    ⚠️ 验证：无——没有任何东西在守着它")
        for gp in n["gaps"]:
            L.append(f"    ✗ 缺口：{gp}")
    L += ["", "—— 图谱只照出能力的轮廓，补不补由我自己定。"]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 能力图谱 🕸️ —— 把模块/本事/验证证据/缺口串成一张可核对的图")
    ap.add_argument("--gaps", action="store_true",
                    help="只列缺口(有本事却没验证的优先)")
    ap.add_argument("--module", metavar="STEM",
                    help="只看某个模块(传 stem，如 compass)")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    args = ap.parse_args(argv)

    g = build(module=args.module)
    if args.json:
        print(json.dumps(g, ensure_ascii=False, indent=2))
    else:
        print(render(g, only_gaps=args.gaps))
    sys.exit(0)  # 只读图谱，永远正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
