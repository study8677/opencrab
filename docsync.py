#!/usr/bin/env python3
"""文档真伪层 🪞📄 —— 把「自我叙述」和「真实能力」逐字对一遍，揪出文档漂移。

为什么要有它：opencrab 每天自改一个模块，README / 能力清单 / 模块契约这些**对外的
自述**却很容易掉队——文件改了名、入口被重构、用法早已失效，文档却还在原地讲着
昨天的故事。这种漂移最阴险：它不报错、不崩，只是让「我说我能做的」和「我真能做的」
悄悄裂开缝，越裂越大。smoke 已经验「README 里的命令真能跑」；docsync 更进一步，
**不执行**任何东西，只做静态对账——把叙述里指到的每一处真实坐标，拿去和领地核对：

  · 失联引用 —— 文档里 `[文字](路径)` 指向的本地文件 / 目录，磁盘上还在不在？
  · 缺失入口 —— 文档里 `python crab.py <子命令>` 的子命令，解析器里真注册了吗？
  · 未验证用法 —— 文档里 `python X.py` 的脚本，根目录真有这个文件吗？
  · 契约漂移 —— `contracts.py` 立约的模块，根目录真存在同名 `.py` 吗？

发现的每一条都带「在哪份文档、哪个 token、怎么修」，让自我叙述贴回真实能力。

用法:
    python docsync.py            # 全量对账，列出每一处漂移
    python docsync.py --quiet    # 只在有漂移时说话(适合钩子 / CI)
    python docsync.py --json     # 导出纯数据(给外部工具消费)

退出码：0 = 文档与能力一致(无漂移)；1 = 发现漂移。零第三方依赖，纯标准库。
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

# 被对账的「自述型」文档：改一处能力，这些最容易掉队。
DOC_FILES = ["README.md", "README.en.md", "CONTRIBUTING.md", "CATALOG.md"]

# ── 漂移类型：每种都是「叙述指到的坐标」与「真实领地」对不上 ──────────────
KIND_BROKEN_LINK = "失联引用"
KIND_MISSING_ENTRY = "缺失入口"
KIND_UNVERIFIED_USAGE = "未验证用法"
KIND_CONTRACT_DRIFT = "契约漂移"


@dataclasses.dataclass(frozen=True)
class Drift:
    """一处文档漂移：在哪份来源、哪个 token 对不上真实能力、该怎么修。"""
    kind: str       # 漂移类型(上面四种之一)
    source: str     # 来源(文档名 / "contracts.py")
    token: str      # 对不上的那个具体 token(路径 / 子命令 / 脚本 / 模块名)
    hint: str       # 一句话修复建议

    def to_meta(self) -> dict:
        return {"kind": self.kind, "source": self.source,
                "token": self.token, "hint": self.hint}


# ── 从文档里抽取「指向真实坐标的引用」(纯正则，不执行任何东西) ────────────
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")          # [文字](目标)
_SCRIPT_RE = re.compile(r"python3?\s+([\w./-]+\.py)")      # python X.py
_CRABCMD_RE = re.compile(r"python3?\s+crab\.py\s+(\S+)")   # python crab.py <子命令>


def _local_link_targets(text: str) -> list[str]:
    """抽出指向本地路径的 markdown 链接目标(剔除外链 / 纯锚点 / 邮件)。"""
    out: list[str] = []
    for raw in _LINK_RE.findall(text):
        target = raw.split("#", 1)[0].strip()          # 去掉 #锚点
        if not target or target.startswith("#"):
            continue
        if re.match(r"[a-zA-Z][\w+.-]*:", target):     # http: / mailto: 等带 scheme 的外链
            continue
        out.append(target)
    return out


def _scripts_referenced(text: str) -> list[str]:
    """抽出文档里 `python X.py` 提到的脚本(原样保留相对写法)。"""
    return _SCRIPT_RE.findall(text)


def _crab_subcommands_referenced(text: str) -> list[str]:
    """抽出 `python crab.py <子命令>` 的子命令(剔除以 - 开头的选项，如 --once)。"""
    return [tok for tok in _CRABCMD_RE.findall(text) if not tok.startswith("-")]


# ── 真实领地的单一真相源 ──────────────────────────────────────────────
def _real_crab_subcommands() -> set[str] | None:
    """自省 crab.py 的子命令解析器；导入失败回 None(此项无法对账，跳过而非误报)。"""
    try:
        import argparse as _ap
        import crab
        parser = crab.build_parser()
    except Exception:
        return None
    names: set[str] = set()
    for action in parser._actions:
        if isinstance(action, _ap._SubParsersAction):
            names.update(action.choices)
    return names


def _module_exists(module: str) -> bool:
    """契约里声明的模块名，根目录有没有同名 .py 或包目录。"""
    return ((REPO_ROOT / f"{module}.py").exists()
            or (REPO_ROOT / module / "__init__.py").exists())


# ── 对账 ─────────────────────────────────────────────────────────────
def _scan_doc(name: str, text: str, subcmds: set[str] | None) -> list[Drift]:
    drifts: list[Drift] = []

    for target in _local_link_targets(text):
        if not (REPO_ROOT / target).exists():
            drifts.append(Drift(KIND_BROKEN_LINK, name, target,
                                 f"链接指向不存在的本地路径，改对路径或删掉这条引用"))

    for script in _scripts_referenced(text):
        if not (REPO_ROOT / script).exists():
            drifts.append(Drift(KIND_UNVERIFIED_USAGE, name, script,
                                 f"文档示例用到 `python {script}`，但根目录没这个脚本，改名或更新示例"))

    if subcmds is not None:
        for sub in _crab_subcommands_referenced(text):
            if sub not in subcmds:
                drifts.append(Drift(KIND_MISSING_ENTRY, name, sub,
                                     f"`python crab.py {sub}` 不是已注册子命令"
                                     f"(现有：{'、'.join(sorted(subcmds)) or '无'})"))
    return drifts


def _scan_contracts() -> list[Drift]:
    """契约立的约，模块得真在：揪出指向已消失模块的契约。"""
    try:
        import contracts
    except Exception:
        return []
    out: list[Drift] = []
    for c in getattr(contracts, "CONTRACTS", []):
        mod = getattr(c, "module", "")
        if mod and not _module_exists(mod):
            out.append(Drift(KIND_CONTRACT_DRIFT, "contracts.py", mod,
                             f"契约声明的模块 `{mod}` 已不在领地，更新契约或恢复模块"))
    return out


def scan(doc_files: list[str] | None = None) -> list[Drift]:
    """全量对账：扫所有自述文档 + 契约，收齐每一处漂移(任何一份读不到都跳过而非崩)。"""
    subcmds = _real_crab_subcommands()
    drifts: list[Drift] = []
    for name in (doc_files if doc_files is not None else DOC_FILES):
        p = REPO_ROOT / name
        if not p.exists():
            continue   # 文档不存在不算漂移(CATALOG.md 等是自动生成的可选产出)
        try:
            text = p.read_text("utf-8", errors="ignore")
        except Exception:
            continue
        drifts.extend(_scan_doc(name, text, subcmds))
    drifts.extend(_scan_contracts())
    return drifts


def summarize(drifts: list[Drift]) -> tuple[bool, int]:
    """归一化结论：是否无漂移、漂移几处。"""
    return (not drifts, len(drifts))


def manifest() -> dict:
    """导出纯数据(给 health / 外部工具消费)。"""
    return {"drifts": [d.to_meta() for d in scan()]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 文档真伪层 🪞📄")
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
        print("🪞 opencrab 文档真伪对账\n")
        if clean:
            print("  ✅ 自述文档与真实能力一致，未发现漂移。")
        else:
            by_kind: dict[str, list[Drift]] = {}
            for d in drifts:
                by_kind.setdefault(d.kind, []).append(d)
            for kind in (KIND_BROKEN_LINK, KIND_MISSING_ENTRY,
                         KIND_UNVERIFIED_USAGE, KIND_CONTRACT_DRIFT):
                items = by_kind.get(kind, [])
                if not items:
                    continue
                print(f"  ❌ {kind}（{len(items)} 处）")
                for d in items:
                    print(f"      · [{d.source}] `{d.token}`")
                    print(f"        ↳ {d.hint}")
        print()

    if clean:
        if not args.quiet:
            print("🪞 一致：自述贴着真实能力，没有文档漂移。")
    else:
        print(f"⚠️  发现 {n} 处文档漂移，把叙述改回贴近真实能力再蜕壳。")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
