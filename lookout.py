#!/usr/bin/env python3
"""
opencrab 的瞭望塔 🔭 —— 用 GitHub 搜索看外面的世界，给进化找灵感。

它一直闭门造车、只盯着自己（自检/诊断/审计）。瞭望塔让它在决定
"今天做什么"之前，先看看 GitHub 上同类项目在做什么，从外部世界
汲取真正新颖的方向，而不是在自我维护里反复打磨。

零第三方依赖：借本机已登录的 gh CLI 搜 GitHub。
"""
from __future__ import annotations

import json
import shutil
import subprocess


def can_see() -> bool:
    """瞭望塔能不能用（gh CLI 在不在）。"""
    return shutil.which("gh") is not None


def scout(query: str, limit: int = 6) -> str:
    """搜 GitHub 仓库，返回 名字 ★star 简介 的摘要。失败不抛异常，返回说明。"""
    if not can_see():
        return "(瞭望塔失明：未找到 gh CLI)"
    try:
        out = subprocess.run(
            ["gh", "search", "repos", query, "--limit", str(limit),
             "--sort", "stars", "--json", "fullName,stargazersCount,description"],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return f"(瞭望失败：{(out.stderr or '').strip()[:90]})"
        repos = json.loads(out.stdout or "[]")
        if not repos:
            return "(外面没搜到相关项目)"
        lines = []
        for r in repos:
            desc = (r.get("description") or "").strip().replace("\n", " ")[:72]
            lines.append(f"    - {r.get('fullName','?')} ★{r.get('stargazersCount',0)} {desc}")
        return "\n".join(lines)
    except Exception as e:
        return f"(瞭望出错：{e})"


def search_code(query: str, limit: int = 5) -> str:
    """更深一层：搜 GitHub 上的代码片段（看别人具体怎么实现）。"""
    if not can_see():
        return "(瞭望塔失明：未找到 gh CLI)"
    try:
        out = subprocess.run(
            ["gh", "search", "code", query, "--limit", str(limit),
             "--json", "repository,path"],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return f"(代码搜索失败：{(out.stderr or '').strip()[:90]})"
        hits = json.loads(out.stdout or "[]")
        lines = [f"    - {h.get('repository',{}).get('nameWithOwner','?')}/{h.get('path','?')}"
                 for h in hits]
        return "\n".join(lines) or "(没搜到相关代码)"
    except Exception as e:
        return f"(代码搜索出错：{e})"


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "autonomous self-improving AI agent"
    print(f"🔭 眺望「{q}」:\n{scout(q)}")
