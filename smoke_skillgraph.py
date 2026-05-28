#!/usr/bin/env python3
"""smoke · skillgraph —— 跑通能力图谱的自省机制，证明它能正确扫描领地。

技能图谱(skillgraph.py)是「能力视角」的核心：它自省所有模块、提取本事描述、
扫描验证证据、识别能力缺口。如果这个机制本身不验证，它就成了最讽刺的空洞——
一个没有证据的能力探测器。

本 smoke 直接 import skillgraph，调用 build()/gaps()，断言关键结构：
  · 返回值结构正确（modules/nodes/summary）
  · 每个 node 有 module/skill/proof/gaps
  · 技能描述提取能正确定位 docstring 首行
  · 缺口识别逻辑正确——有本事的模块出现在 unverified 列表里

通过 = 能力图谱的自省引擎可信任。
"""
from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── 核心：断言 skillgraph 的结构化输出正确 ──────────────────────────
def _run():
    import skillgraph

    # 1) build() 返回结构正确的图谱
    g = skillgraph.build()
    assert isinstance(g, dict), "build() 应返回 dict"
    assert "modules" in g and "nodes" in g and "summary" in g, \
        "build() 缺少 modules/nodes/summary 键"

    total = g["modules"]
    nodes = g["nodes"]
    summary = g["summary"]
    assert total >= 200, f"领地至少 200+ 模块，但 build() 只看到 {total}"
    assert len(nodes) == total, \
        f"modules 数({total}) != nodes 列表长度({len(nodes)})"

    # 2) 每个 node 结构完整
    for n in nodes:
        assert "module" in n and "skill" in n and "proof" in n and "gaps" in n, \
            f"node {n.get('module','?')} 缺少 skill/proof/gaps 键"

    # 3) skillgraph.py 自己能被正确识别
    sg = [n for n in nodes if n["module"] == "skillgraph.py"]
    assert sg, "build() 应该扫到 skillgraph.py 自己"
    sg_node = sg[0]
    assert sg_node["skill"] is not None, "skillgraph.py 应该有本事描述"
    assert "自省" in sg_node["skill"], \
        f"skillgraph.py 的本事描述应包含'自省'，实际: {sg_node['skill']}"

    # 4) module 过滤功能正确
    g_one = skillgraph.build(module="skillgraph")
    assert len(g_one["nodes"]) == 1, \
        f"module='skillgraph' 应只返回 1 个 node，实际 {len(g_one['nodes'])}"
    assert g_one["nodes"][0]["module"] == "skillgraph.py"

    # 5) 缺口逻辑：无证明的有本事模块必须出现在 gaps() 结果中
    gg = skillgraph.gaps()
    assert isinstance(gg, list), "gaps() 应返回 list"
    sg_gaps = [x for x in gg if x["module"] == "skillgraph.py"]
    # skillgraph 目前自身没有硬验证证据，必须出现在缺口列表
    assert sg_gaps, \
        "skillgraph.py 自己没有硬验证，必须出现在 gaps() 结果里"
    assert "有本事" in sg_gaps[0]["reason"], \
        f"gap reason 应含'有本事'，实际: {sg_gaps[0]['reason']}"

    # 6) summary 里的 unverified 与 gaps() 基本一致（后者是前者的子集）
    unverified = summary.get("unverified", [])
    gaps_modules = {x["module"] for x in gg}
    for m in list(gaps_modules)[:5]:
        assert m in unverified, \
            f"gaps() 里的 {m} 不在 summary.unverified 中，逻辑不一致"

    # 7) 证实 unverified 列表里的模块确实缺少硬证据
    import skillgraph as _sg
    hard = set(_sg._HARD_PROOF)
    for m in unverified[:10]:
        stem = m.replace(".py", "")
        pf = _sg._proof(stem)
        assert not (hard & set(pf)), \
            f"{m} 出现在 unverified 但有硬证据 {hard & set(pf)}，检测有误"

    print(f"smoke skillgraph ✅ — 图谱自省引擎可信任：{total} 模块，"
          f"{len(unverified)} 有本事·没验证，{len(gg)} 条缺口")


if __name__ == "__main__":
    _run()
    sys.exit(0)
