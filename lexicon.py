#!/usr/bin/env python3
"""能力词典 📖 —— 给「本事」起一个统一的名，把同义技能归一、别名与来源都留住。

能力图谱(`skillgraph.py`)照出**我会什么、缺什么**，但它信任每个模块自报的措辞：
一个说「守着输出」、一个说「兜底」、一个说「锁住」——其实是同一件事。措辞一散，
我下次想找「有没有做过校验」时就查不全，于是**重复造已有的本事，绕了一圈又回原地**。

词典补的是这一环:**命名的纪律**。它不发明能力，只做三件事：

  · 归一(canonical) —— 一个能力概念定一个正名，把散落的同义说法收到它名下。
  · 别名(alias)     —— 同义的措辞不丢弃、不强改，原样登记成别名，保留语言的多样。
  · 来源(provenance)—— 每个别名是哪个模块、哪句本事里冒出来的，逐条记账可回溯。

它靠两样东西对照：

  1. 一份**人定的词表**(`LEXICON`)：正名 + 释义 + 已知别名，是命名的判准。
  2. 领地里**客观可读的本事**：各模块 docstring 首行(AST 解析，绝不执行代码)。

对照之后给出三类信号：

  · 已归一  —— 某正名在领地里被哪些模块、用哪些别名提及(来源清单)。
  · 待收编  —— 本事里冒出了词表已知的别名,提示「这其实就是那个正名」。
  · 新词    —— 本事里反复出现、词表却没收的能力词，是该添词条的候选(命名缺口)。

词典全程只读：不执行被测模块、不落盘、不改文件。收不收新词、改不改措辞，由我自己定。

用法：
    python lexicon.py              # 打印整本词典 + 领地用词体检
    python lexicon.py --term 验证   # 只看某个正名(及其别名/来源)
    python lexicon.py --gaps       # 只列「新词」候选(命名缺口)
    python lexicon.py --json       # 机读：导成 JSON

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# ── 人定的词表：正名 → (释义, 已知别名…) ────────────────────────────
# 这是命名的判准。别名收的是「领地里真出现过、确属同义」的措辞，宁缺毋滥：
# 收错一个别名，会把本不相干的两件本事错并到一起，比漏收更伤。
LEXICON: dict[str, dict] = {
    "验证": {
        "gloss": "用样本/命令真跑一遍，守住输出不悄悄漂",
        "aliases": ["守护", "守着", "兜底", "锁住", "回归", "烟雾", "校验", "自测"],
    },
    "自省": {
        "gloss": "对照领地里客观可读的事实，照出自己的轮廓",
        "aliases": ["体检", "自查", "审视", "照出", "盘点", "复盘"],
    },
    "方向": {
        "gloss": "判断下一步该往哪走、新不新、值不值",
        "aliases": ["罗盘", "导航", "航道", "选向", "优先级", "取舍"],
    },
    "风险": {
        "gloss": "高风险自改前后,把可能的坏处摆上台面",
        "aliases": ["安全", "红队", "混沌", "反作弊", "探针", "护栏", "闸门"],
    },
    "记忆": {
        "gloss": "把发生过的事、学到的本事留存下来可回溯",
        "aliases": ["日志", "档案", "留痕", "记账", "存证", "时间线"],
    },
    "证据": {
        "gloss": "一件事可被独立核对的客观凭据",
        "aliases": ["凭据", "佐证", "论证", "举证", "可核对"],
    },
    "归一": {
        "gloss": "把同义的多种说法收敛到一个正名",
        "aliases": ["统一", "收编", "去重", "对齐", "规范化"],
    },
}


# ── 读领地：模块清单 + 各自的本事 ──────────────────────────────────
def _modules() -> list[str]:
    """领地根目录受管的 .py 模块名(stem)，排除自己和私有文件。"""
    out = []
    for p in sorted(REPO_ROOT.glob("*.py")):
        stem = p.stem
        if stem == "lexicon" or stem.startswith("_"):
            continue
        out.append(stem)
    return out


def _skill(stem: str) -> str | None:
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


# ── 归一：别名 → 正名 的反查表 ─────────────────────────────────────
def _alias_index() -> dict[str, str]:
    """把词表摊平成「任一说法(正名或别名) → 正名」，正名本身也指向自己。

    若同一别名被两个正名争用，前者(词表里靠前的正名)优先——这是命名冲突，
    渲染时会单独示警，提醒我把别名归位到唯一一个正名下。
    """
    idx: dict[str, str] = {}
    for canon, entry in LEXICON.items():
        idx.setdefault(canon, canon)
        for a in entry["aliases"]:
            idx.setdefault(a, canon)
    return idx


def _conflicts() -> list[dict]:
    """词表里被多个正名同时收作别名的词——命名冲突,得归位到唯一一个正名。"""
    seen: dict[str, str] = {}
    bad: dict[str, set[str]] = {}
    for canon, entry in LEXICON.items():
        for a in entry["aliases"]:
            if a in seen and seen[a] != canon:
                bad.setdefault(a, {seen[a]}).add(canon)
            else:
                seen[a] = canon
    return [{"alias": a, "claimed_by": sorted(cs)} for a, cs in sorted(bad.items())]


# ── 对照领地用词 ───────────────────────────────────────────────────
def normalize(text: str) -> dict[str, list[str]]:
    """在一句本事里，找出命中了词表哪些说法，归到各自正名下。

    返回 {正名: [命中的原始说法…]}。同一正名命中多个别名会合并。纯子串匹配:
    中文无分词，能力词又短而稳定(验证/守护/罗盘…)，子串足够、且不漏。
    """
    idx = _alias_index()
    hits: dict[str, list[str]] = {}
    for term, canon in idx.items():
        if term in text:
            bucket = hits.setdefault(canon, [])
            if term not in bucket:
                bucket.append(term)
    return hits


def build(term: str | None = None) -> dict:
    """对照整个领地的本事，给每个正名结一笔来源账(纯数据)。"""
    by_canon: dict[str, dict] = {
        c: {"canonical": c, "gloss": e["gloss"], "aliases": e["aliases"], "uses": []}
        for c, e in LEXICON.items()
    }
    for stem in _modules():
        skill = _skill(stem)
        if not skill:
            continue
        for canon, said in normalize(skill).items():
            by_canon[canon]["uses"].append({
                "module": f"{stem}.py",
                "said": said,          # 这个模块实际用的说法(可能是别名)
                "skill": skill,        # 出处原句，可回溯
            })
    entries = list(by_canon.values())
    if term:
        entries = [e for e in entries if e["canonical"] == term]
    return {
        "terms": len(LEXICON),
        "entries": entries,
        "conflicts": _conflicts(),
        "candidates": _candidates(),
    }


# ── 新词候选:本事里反复出现、词表没收的能力词 ──────────────────────
# 一组「能力味」的常见用字，用来从本事里粗筛候选词；命中且未被词表收编、
# 且被≥2个模块用到的,才算「值得添词条」——一次性出现的不催。
_CAP_HINTS = (
    "评测", "评估", "模拟", "回放", "诊断", "迁移", "回滚", "发布", "权限",
    "预算", "校准", "契约", "依赖", "隐私", "影响", "意图", "成功", "信任",
    "画像", "剧本", "消融", "反事实", "委派", "对话", "教练", "引路",
)


def _candidates() -> list[dict]:
    """本事里高频出现、词表却没收的能力词——添词条的候选(命名缺口)。"""
    idx = _alias_index()
    tally: dict[str, list[str]] = {}
    for stem in _modules():
        skill = _skill(stem)
        if not skill:
            continue
        for w in _CAP_HINTS:
            if w in skill and w not in idx:
                tally.setdefault(w, []).append(f"{stem}.py")
    return [
        {"word": w, "modules": mods, "count": len(mods)}
        for w, mods in sorted(tally.items(), key=lambda kv: -len(kv[1]))
        if len(mods) >= 2
    ]


# ── 渲染 ───────────────────────────────────────────────────────────
def _alias_uses(entry: dict) -> list[dict]:
    """这个正名名下，有哪些模块其实用的是「别名」而非正名本身——待收编。"""
    return [u for u in entry["uses"]
            if all(s != entry["canonical"] for s in u["said"])]


def render(d: dict, only_gaps: bool = False) -> str:
    if only_gaps:
        L = ["🦀📖 能力词典 · 新词候选(命名缺口)"]
        if not d["candidates"]:
            L.append("    （没有反复出现却没收的能力词——词表暂时跟得上领地。）")
        for c in d["candidates"]:
            L.append(f"    • 「{c['word']}」被 {c['count']} 个模块用到，词表却没收")
            L.append(f"        出处：{', '.join(c['modules'])}")
        return "\n".join(L)

    pending = sum(len(_alias_uses(e)) for e in d["entries"])
    L = ["🦀📖 能力词典 · 正名 / 别名 / 来源",
         f"   正名 {d['terms']} 条 ｜ 待收编(用别名而非正名) {pending} 处 ｜ "
         f"新词候选 {len(d['candidates'])} ｜ 命名冲突 {len(d['conflicts'])}"]

    for e in d["entries"]:
        L += ["", f"● {e['canonical']} —— {e['gloss']}"]
        L.append(f"    别名：{'、'.join(e['aliases']) or '（无）'}")
        if not e["uses"]:
            L.append("    来源：（领地里还没有模块的本事提到它）")
            continue
        for u in e["uses"]:
            said = "、".join(u["said"])
            mark = "↪ 待收编" if all(s != e["canonical"] for s in u["said"]) else "·"
            L.append(f"    {mark} {u['module']}（说「{said}」）")

    if d["conflicts"]:
        L += ["", "⚠️ 命名冲突(同一别名被多个正名争用，得归位)："]
        for c in d["conflicts"]:
            L.append(f"    • 「{c['alias']}」← {' / '.join(c['claimed_by'])}")

    if d["candidates"]:
        L += ["", "🆕 新词候选(repeated 出现却没收的能力词)："]
        for c in d["candidates"]:
            L.append(f"    • 「{c['word']}」×{c['count']}：{', '.join(c['modules'])}")

    L += ["", "—— 词典只照出命名的松紧，收不收、改不改由我自己定。"]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 能力词典 📖 —— 把同义技能归一、保留别名与来源")
    ap.add_argument("--term", metavar="正名",
                    help="只看某个正名(传词表里的正名，如 验证)")
    ap.add_argument("--gaps", action="store_true",
                    help="只列新词候选(命名缺口)")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    args = ap.parse_args(argv)

    d = build(term=args.term)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(render(d, only_gaps=args.gaps))
    sys.exit(0)  # 只读词典，永远正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
