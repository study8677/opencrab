#!/usr/bin/env python3
"""器官发生闸 🧬 —— 想长新器官前，先证明旧器官确实接不住这件事，再写清证据缺口与退役条件。

为什么要有它：领地里已经有人排「先做哪件」（opportunity / prioritizer），有人在事后回查
「这次改动是真收益还是泡沫」（harvest）。但没有一道闸守在**最前面**问那个最该问的问题：
**这件事，是不是已经有现成器官能干？** 自改最隐蔽的浪费，不是把一件事做砸，而是新长一个
和旧器官高度重叠的「增生」——它分走点名、稀释证据、让名册越来越长，却没带来旧器官给不了的
东西。增生不报错，所以从不被拦；越积越多，真正的长进反被淹没。这道闸就是要把「新增」从
默认动作变成**需要举证的例外**：先证明旧器官接不住，才允许长。

它怎么判：把你**打算新增的器官**（一句意图 + 可选名字）拆成关键词，去和领地里每一个现存
器官的自述做**带权重叠**比对——

  · 关键词用 idf 加权：满地都是的词（「器官」「证据」「自改」）几乎不计分，真正稀有、
    指向具体职能的词才抬高重叠度。这样浮上来的是**职能真撞车**的器官，不是凑巧用词相近的。
  · 重叠最高的几个旧器官，再叠上 usageheat 的体温：一个**高频在用**的旧器官和你撞车，
    是「它已经在替真实需求干这事」的强证据——拒得更硬；一个冰封旧器官撞车，则更像是
    「该把它修活 / 接管，而不是另起炉灶」。

闸门三种裁决，都不替你拍板，只决定**你得举多少证**才能往下走：

  · ⛔ 驳回：有高频在用的旧器官职能撞车 —— 默认结论是「别新长，去扩它 / 修它」。
  · ⚠️ 附条件：有旧器官部分覆盖 —— 必须写清两件事才放行（见下）。
  · ✅ 准入：没有旧器官接得住 —— 也仍要求登记退役条件，免得它日后变成新的增生。

放行的前提是把准入证明填满，这两栏正是日志/技能里反复要求、却最常被跳过的：
  1. **证据缺口**：旧器官**具体做不到**的那一项是什么？（不是「它不够好」，而是「它结构上
     给不了 X」）—— 这是新器官存在的唯一理由。
  2. **退役条件**：什么情况下就该把这个新器官删掉？（多少天没人点名 / 证据连续失守 /
     被某个旧器官吸收）—— 先写好它的死法，才配让它出生。

用法：
    python organogenesis.py "并行编排多个子任务并合并它们的产物"      # 给这个意图过闸
    python organogenesis.py "..." --name parallelpilot              # 连拟用的名字一起比
    python organogenesis.py "..." --top 5                           # 多看几个最近的旧器官
    python organogenesis.py "..." --days 14                         # 体温回看窗口（默认 7）
    python organogenesis.py "..." --json                            # 机读：裁决 + 撞车拆解

零第三方依赖，纯标准库。闸门只读领地（各器官 docstring + usageheat），不落盘、不拦动作——
它只把「新增的举证责任」摆到台面上，长不长，仍由我自己拍板。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 重叠分阈值（带 idf 权重、对自身归一后的 0~1）：撞车到什么程度算「旧器官接得住」。
REJECT_AT = 0.55   # ≥ 此值 + 旧器官在用 → ⛔ 驳回
CONDITIONAL_AT = 0.28  # ≥ 此值 → ⚠️ 附条件放行
# 取 docstring 前若干行做职能画像——再往后多是用法/实现细节，反成噪声。
DOC_HEAD_LINES = 28

# 满地都是的功能词：它们不指向具体职能，计分时直接剔掉（idf 之外的硬停用）。
_STOP = {
    "器官", "证据", "自改", "进化", "领地", "为什么", "要有", "用法", "依赖",
    "标准", "纯标准库", "零第三方", "不落盘", "只读", "副作用", "默认", "一行",
    "可核对", "拍板", "自己", "不替", "这件", "这事", "已经", "不是", "而是",
    "the", "and", "for", "you", "not", "but", "它", "我", "也", "再", "把",
    "python", "json", "days", "name", "top", "help", "argv", "none", "true",
}
# CJK 连续段切「字 bigram」用；英文按词切。两者都进同一个词袋。
_CJK = re.compile(r"[一-鿿]+")
_EN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{2,}")


def _tokenize(text: str) -> set[str]:
    """把一段自述/意图拆成词袋：CJK 取二字滑窗，英文取 ≥3 字词，去停用。"""
    toks: set[str] = set()
    for run in _CJK.findall(text):
        if len(run) == 1:
            continue
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg not in _STOP:
                toks.add(bg)
    for w in _EN.findall(text):
        w = w.lower()
        if w not in _STOP:
            toks.add(w)
    return toks


def _docstring(path: pathlib.Path) -> str:
    """取模块 docstring 的前几行做职能画像；读不到则空串。"""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    m = re.search(r'"""(.*?)"""', src, re.S)
    if not m:
        return ""
    return "\n".join(m.group(1).splitlines()[:DOC_HEAD_LINES])


def _corpus(exclude: str | None) -> dict[str, set[str]]:
    """全体器官的词袋：name → token 集合（排除拟用名自身，免得自撞）。"""
    out: dict[str, set[str]] = {}
    for p in sorted(REPO_ROOT.glob("*.py")):
        if p.stem.startswith("_") or p.stem == exclude:
            continue
        toks = _tokenize(_docstring(p))
        if toks:
            out[p.stem] = toks
    return out


def _idf(corpus: dict[str, set[str]]) -> dict[str, float]:
    """每个词的 idf：跨器官越罕见权重越高——稀有词才指向具体职能。"""
    n = max(1, len(corpus))
    df: dict[str, int] = {}
    for toks in corpus.values():
        for t in toks:
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


@dataclasses.dataclass
class Overlap:
    """一个旧器官与新意图的撞车度：归一重叠分 + 共享的关键词 + 体温。"""
    name: str
    score: float            # 0~1，对意图自身的 idf 总权归一
    shared: list[str]       # 真正撞上的关键词（按 idf 降序）
    temp: str = "?"         # usageheat 体温：🔥/🌡️/◽/🧊
    mentions: int = 0       # 近窗口被点名次数

    def to_meta(self) -> dict:
        return {"name": self.name, "score": round(self.score, 3),
                "shared": self.shared, "temp": self.temp, "mentions": self.mentions}


def _heat() -> dict[str, tuple[str, int]]:
    """从 usageheat 取每个器官的体温与点名次数；读不到则空。"""
    try:
        import usageheat
        return {h.name: (h.temp, h.mentions) for h in usageheat.build(days=7)}
    except Exception:
        return {}


def assess(intent: str, name: str | None = None, days: int = 7) -> list[Overlap]:
    """把意图和全体器官比对，按撞车度降序返回。"""
    want = _tokenize(intent + (" " + name if name else ""))
    corpus = _corpus(exclude=name)
    if not want or not corpus:
        return []
    idf = _idf(corpus)
    # 意图侧的自身权重总和——重叠分对它归一，得「意图被旧器官覆盖了几成」。
    want_mass = sum(idf.get(t, 1.0) for t in want) or 1.0
    heat = _heat()

    out: list[Overlap] = []
    for mod, toks in corpus.items():
        shared = want & toks
        if not shared:
            continue
        score = sum(idf.get(t, 1.0) for t in shared) / want_mass
        temp, men = heat.get(mod, ("?", 0))
        ranked_shared = sorted(shared, key=lambda t: idf.get(t, 1.0), reverse=True)
        out.append(Overlap(mod, min(1.0, score), ranked_shared[:8], temp, men))
    out.sort(key=lambda o: o.score, reverse=True)
    return out


# usageheat 里算「在用」的体温：高频/温活才构成「旧器官已在替真实需求干这事」。
_LIVE_TEMPS = {"🌡️", "🔥"}


def verdict(overlaps: list[Overlap]) -> tuple[str, str]:
    """据撞车度 + 旧器官是否在用，给三档裁决之一 + 一句依据。"""
    if not overlaps:
        return "✅ 准入", "没有任何旧器官的自述与这件事撞车——领地里确实缺这块。"
    top = overlaps[0]
    live = top.temp in _LIVE_TEMPS or top.mentions > 0
    if top.score >= REJECT_AT and live:
        return ("⛔ 驳回",
                f"`{top.name}.py` 与之高度撞车（{top.score:.0%}）且近窗口在用"
                f"（{top.temp} 被点名 {top.mentions} 次）——它已在替真实需求干这事，"
                "默认结论是去扩它 / 修它，而不是另起炉灶。")
    if top.score >= REJECT_AT:
        return ("⚠️ 附条件",
                f"`{top.name}.py` 职能高度撞车（{top.score:.0%}），但它此刻冷（{top.temp}）"
                "——更像该把它修活 / 接管，而非新长。要新长，必须举证它结构上接不住。")
    if top.score >= CONDITIONAL_AT:
        return ("⚠️ 附条件",
                f"`{top.name}.py` 部分覆盖（{top.score:.0%}）——有重叠但不致命。"
                "放行的前提是写清它具体做不到的那一项。")
    return ("✅ 准入",
            f"最近的旧器官也只 {top.score:.0%} 沾边（`{top.name}.py`）——"
            "覆盖不到这件事，确属领地缺口。")


def manifest(intent: str, name: str | None, days: int, top: int) -> dict:
    overlaps = assess(intent, name, days)
    v, why = verdict(overlaps)
    return {"intent": intent, "name": name, "verdict": v.split()[1], "rationale": why,
            "overlaps": [o.to_meta() for o in overlaps[:top]]}


def render(intent: str, name: str | None, overlaps: list[Overlap], top: int) -> str:
    v, why = verdict(overlaps)
    L = ["🦀🧬 器官发生闸 · 想长新器官？先证明旧器官接不住",
         f"   拟新增：{name + '.py — ' if name else ''}{intent}", "",
         f"   裁决：{v}", f"   依据：{why}"]
    if overlaps:
        L += ["", "  最近的旧器官（按撞车度）:"]
        for o in overlaps[:top]:
            bar = "█" * round(o.score * 10) + "·" * (10 - round(o.score * 10))
            L += [f"    {bar} {o.score:4.0%}  {o.name}.py  {o.temp}×{o.mentions}",
                  f"            撞上的关键词：{ '、'.join(o.shared) or '—' }"]
    else:
        L += ["", "  （没有旧器官与之沾边，或 docstring 读不到。）"]
    # 准入证明——无论哪档，放行前都得把这两栏填满；闸门只摆出来，不替你填。
    L += ["", "  ── 准入证明（放行前必须填满，否则视同未过闸）──",
          "  1. 证据缺口：上面最像的旧器官，结构上具体做不到的那一项是 ____",
          "             （写「它不够好」不算——要写「它给不了 X」）",
          "  2. 退役条件：这个新器官在 ____ 情况下就该删掉",
          "             （多少天没被点名 / 证据连续失守 / 被某旧器官吸收）",
          "", "—— 闸门只把举证责任摆上台面，长不长仍由我自己拍板。"]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 器官发生闸 🧬 —— 新增前先证明旧器官接不住，并登记证据缺口与退役条件")
    ap.add_argument("intent", help="拟新增器官的一句意图（它要解决什么）")
    ap.add_argument("--name", default=None, metavar="MOD", help="拟用的模块名（一并参与比对）")
    ap.add_argument("--top", type=int, default=3, metavar="N", help="列出最近的前 N 个旧器官（默认 3）")
    ap.add_argument("--days", type=int, default=7, metavar="N", help="体温回看窗口天数（默认 7）")
    ap.add_argument("--json", action="store_true", help="机读：导成 JSON")
    args = ap.parse_args(argv)

    if not args.intent.strip():
        print("❌ 需要一句意图说明拟新增器官要解决什么")
        sys.exit(2)
    top = args.top if args.top > 0 else 3
    if args.json:
        print(json.dumps(manifest(args.intent, args.name, args.days, top),
                         ensure_ascii=False, indent=2))
    else:
        print(render(args.intent, args.name, assess(args.intent, args.name, args.days), top))
    sys.exit(0)  # 只读裁决，永远正常退出，不据此拦任何动作


if __name__ == "__main__":
    main()
