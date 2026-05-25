#!/usr/bin/env python3
"""
opencrab 的瞭望塔 🔭 —— 「看外面」这件事的单一入口：借本机已登录的 gh CLI
看 GitHub，给进化找灵感。

它一直闭门造车、只盯着自己（自检/诊断/审计）。瞭望塔让它在决定
"今天做什么"之前，先看看 GitHub 上同类项目在做什么，从外部世界
汲取真正新颖的方向，而不是在自我维护里反复打磨。

外界学习是一条链路：瞭望塔(lookout)是最底层那只「眼睛」——所有对 gh 的
调用都收口到这里（`gh_json` 单一闸门 + `can_see` 单一探活）。上层的需求信号
市场(market 听 issue/PR)、师法者(mentor 提炼招式卡)不再各自 shell 一遍 gh，
而是软引入这里，缺 gh 就一处退化、绝不各崩各的。

零第三方依赖：借本机已登录的 gh CLI 搜 GitHub。
"""
from __future__ import annotations

import json
import shutil
import subprocess


def can_see() -> bool:
    """瞭望塔能不能用（gh CLI 在不在）。看外面的能力探活，全仓只此一处。"""
    return shutil.which("gh") is not None


def gh_json(args: list[str], timeout: int = 30) -> tuple[list, str]:
    """对 gh 的单一闸门：跑一条 `gh <args> --json …` 只读命令，返回 (行, 说明)。

    所有「看外面」的 gh 调用都收口到这里——没装/没登录/超时/坏档都从容返回
    `([], 一句人话说明)`，绝不抛异常，让任何上层调用方都能一处退化。
    """
    if not can_see():
        return [], "(瞭望塔失明：未找到 gh CLI)"
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
        if out.returncode != 0:
            return [], f"(gh 失败：{(out.stderr or '').strip()[:90]})"
        rows = json.loads(out.stdout or "[]")
        return (rows if isinstance(rows, list) else []), ""
    except Exception as e:
        return [], f"(gh 出错：{e})"


def scout(query: str, limit: int = 6) -> str:
    """搜 GitHub 仓库，返回 名字 ★star 简介 的摘要。失败不抛异常，返回说明。"""
    repos, note = gh_json(
        ["search", "repos", query, "--limit", str(limit), "--sort", "stars",
         "--json", "fullName,stargazersCount,description"])
    if note:
        return note
    if not repos:
        return "(外面没搜到相关项目)"
    lines = []
    for r in repos:
        desc = (r.get("description") or "").strip().replace("\n", " ")[:72]
        lines.append(f"    - {r.get('fullName','?')} ★{r.get('stargazersCount',0)} {desc}")
    return "\n".join(lines)


def search_code(query: str, limit: int = 5) -> str:
    """更深一层：搜 GitHub 上的代码片段（看别人具体怎么实现）。"""
    hits, note = gh_json(
        ["search", "code", query, "--limit", str(limit), "--json", "repository,path"])
    if note:
        return note
    lines = [f"    - {h.get('repository',{}).get('nameWithOwner','?')}/{h.get('path','?')}"
             for h in hits]
    return "\n".join(lines) or "(没搜到相关代码)"


def harvest(kind: str, limit: int = 40) -> list[dict]:
    """收一类外部声音的原始行：`gh <issue|pr> list`，返回 number/title/body/createdAt。

    这是市场(market)收 issue/PR 行情时的取水口——收口到瞭望塔，免得它再各 shell
    一遍 gh。没装/没登录/不是 GitHub 仓都从容返回空表。
    """
    if kind not in ("issue", "pr"):
        return []
    rows, _ = gh_json([kind, "list", "--state", "all", "--limit", str(limit),
                       "--json", "number,title,body,createdAt"])
    return rows


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "autonomous self-improving AI agent"
    print(f"🔭 眺望「{q}」:\n{scout(q)}")
