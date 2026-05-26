#!/usr/bin/env python3
"""双语镜 🪞🌐 —— 把 README.md 与 README.en.md 逐项对一遍，揪出双语漂移。

为什么要有它：opencrab 对外有两张脸——中文 README.md 和英文 README.en.md。
对外协作不能只让一种语言看见真实的我：能力清单、命令、证据这些**与语言无关的
硬事实**，两份必须字字相同。可每天自改一个模块时，往往只顺手改了一边——中文加
了个 `python newtool.py`、换了条徽章、补了个章节，英文那边却原地不动。这种漂移
最阴险：每份单独看都通顺，只有并排照镜子才看得见缝——一种语言的读者看到的「我」，
和另一种语言的读者看到的「我」，悄悄裂成了两个。

docsync 管的是「叙述 vs 真实能力」；bilinguallens 管的是「中文叙述 vs 英文叙述」。
它**不执行**任何东西，只把两份文档里与语言无关的字面量各自抽成集合，做对称差：

  · 命令漂移 —— 代码块里的命令(`python crab.py --once` / `cp .env.example .env`)
                只在一份 README 里出现。
  · 链接漂移 —— 指向本地文件 / 目录的 `[文字](路径)`，只在一份里出现。
  · 徽章漂移 —— 顶部 shields.io 徽章，两份对不齐。
  · 结构漂移 —— `##` 章节数量不等(一种语言多 / 少讲了一块能力)。

正文措辞本就该不同，所以只对账语言无关的字面量，绝不拿译文去比中英文本身。
发现的每一条都带「在哪份有、哪份缺、怎么修」，让两张脸照见同一个真实的我。

用法:
    python bilinguallens.py          # 全量对照，列出每一处双语漂移
    python bilinguallens.py --quiet  # 只在有漂移时说话(适合钩子 / CI)
    python bilinguallens.py --json   # 导出纯数据(给外部工具消费)

退出码：0 = 两份 README 对齐(无漂移)；1 = 发现漂移。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 对照的一对「自述脸」：同一个我，两种语言。
DOC_ZH = "README.md"
DOC_EN = "README.en.md"

# ── 漂移类型：每种都是「一份 README 有、另一份没有」的语言无关字面量 ──────────
KIND_COMMAND = "命令漂移"
KIND_LINK = "链接漂移"
KIND_BADGE = "徽章漂移"
KIND_STRUCTURE = "结构漂移"


@dataclasses.dataclass(frozen=True)
class Drift:
    """一处双语漂移：哪类、对不上的字面量、哪份有 / 哪份缺、怎么修。"""
    kind: str         # 漂移类型(上面四种之一)
    token: str        # 对不上的那个具体字面量(命令 / 路径 / 徽章 / 数量说明)
    present_in: str   # 出现在哪份 README
    missing_in: str   # 哪份 README 缺它
    hint: str         # 一句话修复建议

    def to_meta(self) -> dict:
        return {"kind": self.kind, "token": self.token,
                "present_in": self.present_in, "missing_in": self.missing_in,
                "hint": self.hint}


# ── 从文档里抽「与语言无关的字面量」(纯正则，不执行、不比译文) ────────────────
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)   # ``` 代码块体
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")           # [文字](目标)
_BADGE_RE = re.compile(r"img\.shields\.io/badge/[^)\s]+")   # shields.io 徽章
_HEADING_RE = re.compile(r"^##\s", re.MULTILINE)            # ## 章节


def _commands(text: str) -> set[str]:
    """抽代码块里的命令行，剥掉行内注释——注释本就该按语言不同，命令不该。"""
    out: set[str] = set()
    for body in _FENCE_RE.findall(text):
        for raw in body.splitlines():
            line = raw.split("#", 1)[0].strip()   # 去掉 # 注释 与缩进
            # 只收真正的命令调用，跳过裸文字 / 生命循环示意图那类非命令行
            if re.match(r"(python3?|cp|echo|git|bash|sh|pip3?)\b", line):
                out.add(line)
    return out


def _local_links(text: str) -> set[str]:
    """抽指向本地路径的链接目标(剔除外链 / 纯锚点)，去掉 #锚点只留路径。"""
    out: set[str] = set()
    for raw in _LINK_RE.findall(text):
        target = raw.split("#", 1)[0].strip()
        if not target or target.startswith("#"):
            continue
        if re.match(r"[a-zA-Z][\w+.-]*:", target):   # http: / mailto: 等外链
            continue
        out.add(target)
    return out


def _badges(text: str) -> set[str]:
    """抽顶部 shields.io 徽章 URL——徽章是对外的「证据」，两份必须一致。"""
    return set(_BADGE_RE.findall(text))


def _heading_count(text: str) -> int:
    """数 `##` 二级章节——每一节大致对应一块对外宣称的能力。"""
    return len(_HEADING_RE.findall(text))


# ── 对照：把两份各抽一份集合，做对称差 ────────────────────────────────────
def _diff_set(kind: str, zh: set[str], en: set[str],
              hint_only_zh: str, hint_only_en: str) -> list[Drift]:
    """同一类字面量的双向对账：中文独有 + 英文独有，各成漂移。"""
    drifts: list[Drift] = []
    for token in sorted(zh - en):
        drifts.append(Drift(kind, token, DOC_ZH, DOC_EN, hint_only_zh))
    for token in sorted(en - zh):
        drifts.append(Drift(kind, token, DOC_EN, DOC_ZH, hint_only_en))
    return drifts


def scan(zh_text: str | None = None, en_text: str | None = None) -> list[Drift]:
    """全量对照：两份都读得到才对账，任何一份缺失则视作无可对照(交给 docsync 管缺失)。"""
    if zh_text is None:
        zh_text = _read(DOC_ZH)
    if en_text is None:
        en_text = _read(DOC_EN)
    if zh_text is None or en_text is None:
        return []

    drifts: list[Drift] = []
    drifts += _diff_set(KIND_COMMAND, _commands(zh_text), _commands(en_text),
                        f"该命令只在 {DOC_ZH} 出现，补进 {DOC_EN} 或两份都删",
                        f"该命令只在 {DOC_EN} 出现，补进 {DOC_ZH} 或两份都删")
    drifts += _diff_set(KIND_LINK, _local_links(zh_text), _local_links(en_text),
                        f"该本地链接只在 {DOC_ZH} 出现，补进 {DOC_EN} 或两份都删",
                        f"该本地链接只在 {DOC_EN} 出现，补进 {DOC_ZH} 或两份都删")
    drifts += _diff_set(KIND_BADGE, _badges(zh_text), _badges(en_text),
                        f"该徽章只在 {DOC_ZH} 出现，补进 {DOC_EN} 或两份都删",
                        f"该徽章只在 {DOC_EN} 出现，补进 {DOC_ZH} 或两份都删")

    zh_n, en_n = _heading_count(zh_text), _heading_count(en_text)
    if zh_n != en_n:
        more, less = (DOC_ZH, DOC_EN) if zh_n > en_n else (DOC_EN, DOC_ZH)
        drifts.append(Drift(KIND_STRUCTURE, f"## 章节数 {zh_n} ≠ {en_n}",
                            more, less,
                            f"{more} 比 {less} 多讲了一块能力，对齐章节让两份覆盖一致"))
    return drifts


def _read(name: str) -> str | None:
    p = REPO_ROOT / name
    if not p.exists():
        return None
    try:
        return p.read_text("utf-8", errors="ignore")
    except Exception:
        return None


def summarize(drifts: list[Drift]) -> tuple[bool, int]:
    """归一化结论：是否无漂移、漂移几处。"""
    return (not drifts, len(drifts))


def manifest() -> dict:
    """导出纯数据(给 health / 外部工具消费)。"""
    return {"drifts": [d.to_meta() for d in scan()]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 双语镜 🪞🌐")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有漂移时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    drifts = scan()
    clean, n = summarize(drifts)

    if not (args.quiet and clean):
        print(f"🪞 opencrab 双语镜：{DOC_ZH} ⇄ {DOC_EN}\n")
        if clean:
            print("  ✅ 两份 README 的命令、链接、徽章、章节全部对齐，未发现双语漂移。")
        else:
            by_kind: dict[str, list[Drift]] = {}
            for d in drifts:
                by_kind.setdefault(d.kind, []).append(d)
            for kind in (KIND_COMMAND, KIND_LINK, KIND_BADGE, KIND_STRUCTURE):
                items = by_kind.get(kind, [])
                if not items:
                    continue
                print(f"  ❌ {kind}（{len(items)} 处）")
                for d in items:
                    print(f"      · `{d.token}`")
                    print(f"        仅见于 {d.present_in}，{d.missing_in} 缺失")
                    print(f"        ↳ {d.hint}")
        print()

    if clean:
        if not args.quiet:
            print("🪞 对齐：两张脸照见同一个真实的我，没有双语漂移。")
    else:
        print(f"⚠️  发现 {n} 处双语漂移，让两种语言看见同一个我再蜕壳。")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
