"""能力 · 版本与变更说明 📣 —— 把「我进化了」翻译成用户看得懂、用得上的话。

每次自我进化都在改代码、写航海日志、记演化快照，但这些都是「对自己说」的；
用户真正想知道的是三件事：**这次到底变了什么、会影响谁、该怎么用**。
这条能力就把提交记录、演化日志(EVOLUTION.md)和关键代码差异揉到一起，
提炼成一份面向外部的「变更说明草稿」，补上对外沟通这块短板。

它做四件事：
  1. 框定本次范围   —— 默认从最近一个 git tag(没有就回退到最近 N 个提交)到 HEAD，
     也可传 ctx={"base": "<ref>"} 指定基线、ctx={"since": N} 控制回退提交数。
  2. 提炼变了什么   —— 清洗提交标题(剥掉 🦀 evolve:/self-evolve: 前缀并按意图去重)、
     从 git diff 数出新增/修改/删除的文件，并标出本次**新增的能力**(新 cap_*.py)。
  3. 算清影响谁     —— 哪些用户入口(根级脚本/README/COMMANDS.md)动了、
     冒出哪些可直接调用的新命令(`python crab.py cap <NAME>`)。
  4. 给出怎么用     —— 为新能力捞出它 docstring 里的用法样例，照着就能跑。

默认把草稿写到 state/release/<时间>.md(落在被 .gitignore 的 state/ 里，
属「待人过目再对外发」的草稿，自动生成、可重跑覆盖)；
传 ctx={"write": False} 则只渲染不落盘。
ctx 选项：{"base": "<对比基线>", "since": N(无 tag 时回退的提交数,默认 12),
"write": bool}。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import ast
import datetime
import pathlib
import re
import subprocess

from . import Result, capability, get as _get_cap

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT_DIR = _REPO_ROOT / "state" / "release"     # 落在被 .gitignore 的 state/ 里
_EVOLUTION = _REPO_ROOT / "journal" / "EVOLUTION.md"

# 提交标题里那些「对自己说」的噪声前缀，对外说明里要剥掉。
_PREFIX_RE = re.compile(r"^\s*(?:🦀\s*)?(?:self-)?evolve\s*[:：]\s*", re.IGNORECASE)
# 用户能直接感知的入口：根级脚本 + 对外文档。
_USER_FACING = re.compile(r"^(README\.md|COMMANDS\.md|CHANGELOG\.md|[^/]+\.py)$")
# docstring 里像「能跑的命令」的行(python …)。
_CMD_RE = re.compile(r"^\s*(python[ \t]+\S+\.py[^\n#]*?)\s*(?:#.*)?$")


def _git(args: list[str]) -> str:
    """只读 git 命令；失败 → 空串。"""
    try:
        out = subprocess.run(["git", "-C", str(_REPO_ROOT), *args],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return ""


def _resolve_base(ctx: dict) -> tuple[str, str]:
    """框定对比基线，返回 (基线 ref, 一句来源说明)。"""
    given = ctx.get("base")
    if given:
        return given, f"由 ctx.base 指定：{given}"
    tag = _git(["describe", "--tags", "--abbrev=0"])
    if tag:
        return tag, f"最近的版本标签 {tag}"
    since = int(ctx.get("since", 12))
    ref = f"HEAD~{since}"
    # 提交数不够时 HEAD~N 会解析失败，回退到本仓第一个提交。
    if not _git(["rev-parse", "--verify", "--quiet", ref]):
        first = _git(["rev-list", "--max-parents=0", "HEAD"]).splitlines()
        ref = first[0] if first else "HEAD"
        return ref, "尚无版本标签，从仓库起点起算"
    return ref, f"尚无版本标签，回退到最近 {since} 个提交"


def _commit_subjects(base: str) -> list[str]:
    """base..HEAD 的提交标题，剥前缀 + 按意图去重保序。"""
    raw = _git(["log", f"{base}..HEAD", "--format=%s"])
    seen: set[str] = set()
    out: list[str] = []
    for line in raw.splitlines():
        s = _PREFIX_RE.sub("", line).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:                  # evolve/self-evolve 成对出现，去重
            continue
        seen.add(key)
        out.append(s)
    return out


def _name_status(base: str) -> dict[str, list[str]]:
    """base..HEAD 的文件变更，按 新增/修改/删除 归类(posix 相对路径)。"""
    buckets: dict[str, list[str]] = {"added": [], "modified": [], "deleted": []}
    raw = _git(["diff", "--name-status", f"{base}..HEAD"])
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code, path = parts[0].strip(), parts[-1].strip()
        if path.startswith(("state/", ".git/")):
            continue
        if code.startswith("A"):
            buckets["added"].append(path)
        elif code.startswith("D"):
            buckets["deleted"].append(path)
        else:                            # M / R / C 等都算「改了」
            buckets["modified"].append(path)
    return buckets


def _diffstat(base: str) -> str:
    """一行总量：N files changed, +X/-Y(尽力而为)。"""
    return _git(["diff", "--shortstat", f"{base}..HEAD"]).strip()


def _docstring(src: str) -> str:
    try:
        return ast.get_docstring(ast.parse(src)) or ""
    except Exception:
        return ""


def _cap_meta(rel: str) -> dict | None:
    """新增的 capabilities/cap_X.py → 它登记的能力名/摘要/用法样例。"""
    name = pathlib.Path(rel).name
    if not (rel.startswith("capabilities/") and name.startswith("cap_")):
        return None
    stem = name[len("cap_"):-len(".py")]
    cap = _get_cap(stem)
    src = ""
    p = _REPO_ROOT / rel
    if p.exists():
        src = p.read_text("utf-8", errors="ignore")
    doc = _docstring(src)
    usages = [m.group(1).strip() for line in doc.splitlines()
              if (m := _CMD_RE.match(line))]
    return {
        "name": stem,
        "summary": cap.summary if cap else _purpose(doc),
        "usages": usages or [f"python crab.py cap {stem}"],
    }


def _purpose(doc: str) -> str:
    for line in doc.splitlines():
        if line.strip():
            return line.strip()
    return "(无说明)"


def _latest_intent() -> str:
    """EVOLUTION.md 里最新一条的意图，作为本次升级的「主旨」。"""
    if not _EVOLUTION.exists():
        return ""
    text = _EVOLUTION.read_text("utf-8", errors="ignore")
    intents = re.findall(r"^- 意图：(.+)$", text, re.MULTILINE)
    return intents[-1].strip() if intents else ""


def analyze(ctx: dict) -> dict:
    """把「范围 → 变了什么 → 影响谁 → 怎么用」算成一份纯数据的变更说明。"""
    base, source = _resolve_base(ctx)
    version = _git(["describe", "--tags", "--always", "--dirty"]) or "HEAD"
    subjects = _commit_subjects(base)
    status = _name_status(base)
    shortstat = _diffstat(base)

    # 新增能力：本次 added 里的 cap_*.py
    new_caps: list[dict] = []
    for f in status["added"]:
        meta = _cap_meta(f)
        if meta:
            new_caps.append(meta)

    # 影响谁：用户能直接感知的入口动了哪些
    touched = status["added"] + status["modified"] + status["deleted"]
    user_facing = sorted({f for f in touched if _USER_FACING.match(f)})

    return {
        "version": version,
        "base": base,
        "source": source,
        "intent": _latest_intent(),
        "subjects": subjects,
        "status": status,
        "shortstat": shortstat,
        "new_caps": new_caps,
        "user_facing": user_facing,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def _render(a: dict) -> str:
    """渲染成一份面向用户的「变更说明草稿」(markdown)。"""
    L: list[str] = []
    L.append(f"# 🦀📣 opencrab 变更说明 · {a['version']}")
    L.append("")
    L.append("> 自动生成的**对外说明草稿**，发出前请人过目润色——"
             "重跑 `python crab.py cap release` 即可刷新。")
    L.append(f"> 对比范围：{a['source']} → HEAD。")
    L.append("")

    st = a["status"]
    if not a["subjects"] and not (st["added"] or st["modified"] or st["deleted"]):
        L.append("（这个范围内没有探测到变更——基线可能就是 HEAD。）")
        L.append("")
        return "\n".join(L).rstrip() + "\n"

    # TL;DR
    if a["intent"]:
        L.append(f"**这次主要在做**：{a['intent']}")
        L.append("")
    bits = []
    if a["new_caps"]:
        bits.append(f"{len(a['new_caps'])} 个新能力")
    bits.append(f"{len(st['added'])} 新增 / {len(st['modified'])} 修改 / "
                f"{len(st['deleted'])} 删除 文件")
    if a["shortstat"]:
        bits.append(a["shortstat"])
    L.append("**概览**：" + " · ".join(bits))
    L.append("")

    # 1) 变了什么
    L.append("## 📦 变了什么")
    L.append("")
    if a["subjects"]:
        for s in a["subjects"]:
            L.append(f"- {s}")
    else:
        L.append("- （区间内无提交标题）")
    L.append("")
    if a["new_caps"]:
        L.append("**新增能力：**")
        L.append("")
        for c in a["new_caps"]:
            L.append(f"- `{c['name']}` — {c['summary']}")
        L.append("")

    # 2) 影响谁
    L.append("## 👥 影响谁")
    L.append("")
    if a["user_facing"]:
        L.append("以下用户可直接感知的入口/文档发生了变化，升级后留意：")
        L.extend(f"- `{f}`" for f in a["user_facing"])
    else:
        L.append("- 没有用户直接可见的入口变化，多为内部实现调整。")
    L.append("")
    if a["new_caps"]:
        L.append("新冒出的可直接调用命令：")
        L.extend(f"- `python crab.py cap {c['name']}`" for c in a["new_caps"])
        L.append("")

    # 3) 怎么用
    L.append("## 🚀 怎么用")
    L.append("")
    if a["new_caps"]:
        for c in a["new_caps"]:
            L.append(f"### `{c['name']}`")
            L.append("")
            L.append("```bash")
            L.extend(c["usages"])
            L.append("```")
            L.append("")
    else:
        L.append("用法没变，照旧：")
        L.append("")
        L.append("```bash")
        L.append("python crab.py caps          # 看全部能力及启用状态")
        L.append("python crab.py cap <NAME>    # 单独跑一种能力")
        L.append("```")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


@capability("release", "版本与变更说明：从提交/演化日志/代码差异提炼「变了什么·影响谁·怎么用」对外说明草稿",
            category="自述", tags=("changelog", "release", "docs", "git", "communication"))
def run(ctx: dict) -> Result:
    ctx = ctx or {}
    a = analyze(ctx)
    report = _render(a)

    written = None
    if ctx.get("write", True):
        try:
            _OUT_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
            out = _OUT_DIR / f"{stamp}.md"
            out.write_text(report, "utf-8")
            written = out.relative_to(_REPO_ROOT).as_posix()
        except Exception as e:
            return Result(ok=False, summary=f"草稿已生成但落盘失败：{e}", detail=report)

    st = a["status"]
    n_changed = len(st["added"]) + len(st["modified"]) + len(st["deleted"])
    if not a["subjects"] and not n_changed:
        return Result(ok=True, summary=f"对比范围内没有变更（{a['source']}）。",
                      detail=report, data=a)

    summary = (f"{len(a['subjects'])} 条变更 · {len(a['new_caps'])} 个新能力 · "
               f"{n_changed} 个文件改动 · {len(a['user_facing'])} 处用户入口受影响"
               + (f" → 已写入 {written}" if written else "（未落盘）"))
    return Result(ok=True, summary=summary, detail=report, data=a)
