"""能力 · 统一能力注册表 🗂️ —— 把散落的资产登记成一份可发现、可组合的清单。

helpdex 已经把「脚本 + 可插拔能力」串成目录；catalog 更进一步，把领地里**所有
类型的资产**统一登记进一张表，并回答那个最朴素的问题：「我现在到底能做什么？」

它靠**真实自省**而非硬编码来发现资产，五类各登其位：
  1. 入口   —— 自省 `crab.py` 的子命令解析器，列出可直接敲的命令(单一真相源)。
  2. 能力   —— 从能力注册中心读已登记的可插拔能力(名/说明/归类/标签/启用)。
  3. 脚本   —— 根级 `*.py` 的用途(模块 docstring 首行)。
  4. 回归   —— 复用 `regression.CASES`，看每条关键行为有没有黄金样本守着。
  5. 资产   —— README / 航海日志 / 技能 / 黄金样本这些「沉淀型」产出的存量。

可组合：按标签把能力反向索引成「标签 → 能力」，让能力能按主题被检索、被搭配。
可发现：交叉核对哪些能力被回归用例守着(有测试)、哪些脚本没写用途(失联风险)。

默认把渲染结果写到仓库根的 `CATALOG.md`(自动生成、可重跑覆盖)；
传 ctx={"write": False} 则只渲染不落盘。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import ast
import pathlib

from . import Result, all_capabilities, capability, enabled_capabilities

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT = _REPO_ROOT / "CATALOG.md"


def _entries() -> list[dict]:
    """自省 crab.py 的子命令解析器，得到「可直接敲的入口」(单一真相源)。"""
    import sys
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    try:
        import argparse
        import crab
        parser = crab.build_parser()
    except Exception:
        return []
    out: list[dict] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            # action.choices 保序：子命令名 -> 子解析器；help 在 _choices_actions 里
            helps = {a.dest: (a.help or "") for a in action._choices_actions}
            for name in action.choices:
                out.append({"cmd": f"python crab.py {name}",
                            "help": helps.get(name, "")})
    return out


def _scripts() -> list[dict]:
    """根级 *.py 的用途(模块 docstring 首行)；没写 docstring 的标记为失联风险。"""
    out: list[dict] = []
    for p in sorted(_REPO_ROOT.glob("*.py")):
        try:
            doc = ast.get_docstring(ast.parse(p.read_text("utf-8", errors="ignore")))
        except Exception:
            doc = None
        purpose = ""
        for line in (doc or "").splitlines():
            if line.strip():
                purpose = line.strip()
                break
        out.append({"file": p.name, "purpose": purpose, "documented": bool(purpose)})
    return out


def _goldens() -> list[dict]:
    """复用 regression.CASES：每条关键行为用例，连同「有没有黄金样本守着」。"""
    import sys
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    try:
        import regression
    except Exception:
        return []
    out: list[dict] = []
    for c in regression.CASES:
        recorded = regression.snapshot_golden_path(c).exists()
        out.append({"name": c.name, "summary": c.summary,
                    "argv": " ".join(c.argv[1:]), "recorded": recorded})
    return out


def _assets() -> list[dict]:
    """沉淀型产出的存量：README / 航海日志 / 技能 / 黄金样本。"""
    def count(rel: str, pat: str) -> int:
        d = _REPO_ROOT / rel if rel else _REPO_ROOT
        return len(list(d.glob(pat))) if d.exists() else 0
    out = [{"name": "README.md", "kind": "对外说明",
            "present": (_REPO_ROOT / "README.md").exists(), "count": None}]
    out.append({"name": "journal/", "kind": "航海日志(经营产出)",
                "present": (_REPO_ROOT / "journal").exists(),
                "count": count("journal", "*.md")})
    out.append({"name": "skills/", "kind": "已学技能(资产)",
                "present": (_REPO_ROOT / "skills").exists(),
                "count": count("skills", "*.md")})
    out.append({"name": "goldens/", "kind": "黄金样本(回归资产)",
                "present": (_REPO_ROOT / "goldens").exists(),
                "count": count("goldens", "*.json")})
    return out


def _tag_index(caps) -> dict[str, list[str]]:
    """标签 → 能力名 的反向索引：让能力能按主题被检索、被组合。"""
    idx: dict[str, list[str]] = {}
    for c in caps:
        for t in c.tags:
            idx.setdefault(t, []).append(c.name)
    return {t: sorted(idx[t]) for t in sorted(idx)}


def _tested_caps(caps, goldens_: list[dict]) -> set[str]:
    """哪些能力被某条回归用例守着：用例命令里出现 `cap <name>` 即视为有测试。"""
    blob = " ".join(g["argv"] for g in goldens_)
    return {c.name for c in caps if f"cap {c.name}" in blob or f"--cap {c.name}" in blob}


def _render(entries, caps, scripts, goldens_, assets) -> str:
    enabled = {c.name for c in enabled_capabilities()}
    tags = _tag_index(caps)
    tested = _tested_caps(caps, goldens_)
    by_cat: dict[str, list] = {}
    for c in caps:
        by_cat.setdefault(c.category, []).append(c)

    L: list[str] = []
    L.append("# 🦀 opencrab 能力注册表")
    L.append("")
    L.append("> 自动生成，请勿手改——重跑 `python crab.py cap catalog` 即可刷新。")
    L.append("> 把领地里所有类型的资产登记成一份可发现、可组合的清单，"
             "回答：「我现在能做什么？」")
    L.append("")

    # —— 我现在能做什么：可直接敲的入口 + 可单跑的能力 ——
    L.append("## 🚀 我现在能做什么")
    L.append("")
    L.append("**命令入口**（直接敲）：")
    L.append("")
    L.append("```bash")
    for e in entries:
        pad = " " * max(2, 26 - len(e["cmd"]))
        L.append(f"{e['cmd']}{pad}# {e['help']}" if e["help"] else e["cmd"])
    L.append("```")
    L.append("")
    L.append(f"**可单跑的能力**（{len(enabled)}/{len(caps)} 默认启用）：")
    L.append("")
    L.append("```bash")
    for c in caps:
        mark = "" if c.name in enabled else "   # ⚪ 默认未启用"
        L.append(f"python crab.py cap {c.name}{mark}")
    L.append("```")
    L.append("")

    # —— 能力清单：按归类分组，标注启用 / 有无回归守护 ——
    L.append("## 🧩 能力清单")
    L.append("")
    L.append("> 🟢 已启用 · ⚪ 未启用 · 🧪 有回归用例守着")
    L.append("")
    for cat in sorted(by_cat):
        L.append(f"**{cat}**")
        L.append("")
        for c in by_cat[cat]:
            on = "🟢" if c.name in enabled else "⚪"
            test = " 🧪" if c.name in tested else ""
            tagtxt = f" · _{', '.join(c.tags)}_" if c.tags else ""
            L.append(f"- {on} `{c.name}`{test} — {c.summary}{tagtxt}")
        L.append("")

    # —— 可组合：标签反向索引 ——
    L.append("## 🔗 按标签组合")
    L.append("")
    L.append("> 同一标签下的能力可按主题搭配使用。")
    L.append("")
    if tags:
        for t, names in tags.items():
            L.append(f"- `{t}`：" + "、".join(f"`{n}`" for n in names))
    else:
        L.append("- （还没有能力声明标签）")
    L.append("")

    # —— 脚本入口 ——
    L.append("## 📜 脚本")
    L.append("")
    L.append("| 脚本 | 用途 |")
    L.append("|---|---|")
    for s in scripts:
        purpose = s["purpose"] or "⚠️ 未写 docstring（失联风险）"
        L.append(f"| `{s['file']}` | {purpose} |")
    L.append("")

    # —— 回归守护 ——
    L.append("## 🧪 回归守护")
    L.append("")
    L.append("> 关键行为的黄金样本；未录的先跑 `python regression.py snapshot --update`。")
    L.append("")
    if goldens_:
        for g in goldens_:
            mark = "✅ 已录" if g["recorded"] else "⚪ 未录"
            L.append(f"- [{mark}] `{g['name']}` — {g['summary']}")
    else:
        L.append("- （未发现回归用例）")
    L.append("")

    # —— 沉淀型资产 ——
    L.append("## 📦 沉淀资产")
    L.append("")
    for a in assets:
        if not a["present"]:
            L.append(f"- `{a['name']}`（{a['kind']}）：⚠️ 缺失")
        elif a["count"] is None:
            L.append(f"- `{a['name']}`（{a['kind']}）：在位")
        else:
            L.append(f"- `{a['name']}`（{a['kind']}）：{a['count']} 项")
    L.append("")
    return "\n".join(L).rstrip() + "\n"


@capability("catalog", "统一能力注册表：登记入口/能力/脚本/回归/资产，生成「我现在能做什么」索引",
            category="自述", tags=("docs", "discovery", "manifest", "compose"))
def run(ctx: dict) -> Result:
    entries = _entries()
    caps = all_capabilities()
    scripts = _scripts()
    goldens_ = _goldens()
    assets = _assets()
    doc = _render(entries, caps, scripts, goldens_, assets)

    write = (ctx or {}).get("write", True)
    n_undoc = sum(1 for s in scripts if not s["documented"])
    n_tested = len(_tested_caps(caps, goldens_))

    written = None
    if write:
        try:
            _OUT.write_text(doc, "utf-8")
            written = _OUT.relative_to(_REPO_ROOT).as_posix()
        except Exception as e:
            return Result(ok=False, summary=f"注册表已生成但落盘失败：{e}", detail=doc)

    summary = (f"登记 {len(entries)} 入口 · {len(caps)} 能力（{n_tested} 有回归守护）· "
               f"{len(scripts)} 脚本（{n_undoc} 缺说明）· {len(goldens_)} 回归用例"
               + (f" → 已写入 {written}" if written else "（未落盘）"))
    return Result(ok=True, summary=summary, detail=doc,
                  data={"entries": len(entries), "capabilities": len(caps),
                        "tested_capabilities": n_tested, "scripts": len(scripts),
                        "undocumented_scripts": n_undoc, "goldens": len(goldens_),
                        "written": written})
