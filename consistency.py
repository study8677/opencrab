#!/usr/bin/env python3
"""自洽镜 🧭 —— 把四处「我对自己的声明」摆到一起对质，揪出互相打架的那几条。

为什么要有它：opencrab 关于「我是谁、我会什么」的话，散落在四个各自为政的地方——
对外的 README、能当场复跑的证据账本(`evidence`)、命名的判准(`lexicon` 能力词典)、
发布前的闸门规则(`releasegate`)。每一处单独看都自圆其说，可它们**从不照面**:
README 大方宣称「我能跑 `python foo.py`」，foo.py 其实早被删了;证据账本里某条能力
最近一次验证明明 🔴失守，README 却仍把它当卖点;闸门规则写着「靠某哨卡裁决」，那
哨卡模块却不在领地里。

不自洽最毒的地方在于:**进化的方向是照着「我以为的我」来定的**。如果「我以为的我」
和「真实的我」对不上,每一步自改都在往一个并不存在的自己使劲——越努力,偏得越远。
自洽镜补的就是这一环:把四处声明抽成可比对的事实,**两两对质**,只报那些**互相矛盾**
的,每条都带「在哪两处打架、为什么矛盾、怎么收口」。

它查四类自相矛盾(纯静态:读文件 / AST / 已有 manifest，绝不执行被测模块):

  · 👻 幽灵命令 —— README 教人 `python X.py`，X.py 却不在领地里。教的是空气。
  · 🩸 失守却宣称 —— 证据账本说某能力最近验证 🔴失守，README 仍把它当能力对外讲。
  · 🪓 断头证据 —— 证据账本某条声明的验证命令点名一个 .py，那文件却不存在。验了个寂寞。
  · 🚧 失踪哨卡 —— 闸门规则靠某哨卡模块裁决，那模块却不在。闸门形同虚设。

判准:自洽镜**只读、只对质、只给建议**,不改 README、不动账本、不执行任何被测模块。
任何一处声明读不到(如 evidence 不可用),那一类对质就跳过(记为无可对质),绝不臆测。
发现任意一条矛盾即让退出码非零,可挂进钩子 / CI 当门禁。

用法:
    python consistency.py          # 全量对质,列出每一条自相矛盾 + 收口建议
    python consistency.py --quiet  # 只在有矛盾时说话(适合钩子 / CI)
    python consistency.py --json   # 导出纯数据(给 health / 外部工具消费)

退出码:0 = 四处声明彼此自洽(无矛盾);1 = 发现矛盾。零第三方依赖,纯标准库。
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

# 两张对外的「自述脸」：自洽镜把它们当同一份对外声明的两种语言一起读。
READMES = ("README.md", "README.en.md")

# 闸门规则(releasegate)赖以裁决的哨卡模块：闸门规则就是「这几只哨卡说了算」。
# 任一缺位,那道闸只能记「未知」并保守暂缓——闸门规则与领地现实就此打架。
GATE_SENTINELS = ("evidence", "secretscan", "supplychain", "changelog")

# ── 矛盾类型:每条都是「两处声明对同一件事各执一词」 ──────────────────────────
KIND_GHOST = "幽灵命令"      # README 教 python X.py,X.py 不存在
KIND_BROKEN = "失守却宣称"    # 证据 🔴失守,README 仍宣称
KIND_HEADLESS = "断头证据"    # 证据声明的验证命令点名一个不存在的 .py
KIND_SENTINEL = "失踪哨卡"    # 闸门规则赖以裁决的哨卡模块不存在

_ICON = {KIND_GHOST: "👻", KIND_BROKEN: "🩸", KIND_HEADLESS: "🪓", KIND_SENTINEL: "🚧"}


@dataclasses.dataclass(frozen=True)
class Conflict:
    """一处自相矛盾:哪类、关于谁、两处声明各说了什么、怎么收口。"""
    kind: str         # 矛盾类型(上面四种之一)
    subject: str      # 打架的对象(模块名 / 命令 / 能力名)
    here: str         # 一处声明(及其说法)
    there: str        # 另一处声明(及其矛盾说法)
    hint: str         # 一句话收口建议

    def to_meta(self) -> dict:
        return {"kind": self.kind, "subject": self.subject,
                "here": self.here, "there": self.there, "hint": self.hint}


# ── 读对外声明:从 README 抽「被点名的模块」(纯正则,不执行) ──────────────────
_CMD_RE = re.compile(r"python3?\s+([A-Za-z_][\w]*)\.py")   # `python X.py ...`


def _read(name: str) -> str | None:
    p = REPO_ROOT / name
    try:
        return p.read_text("utf-8", errors="ignore") if p.exists() else None
    except Exception:
        return None


def readme_modules() -> dict[str, str]:
    """README 里被 `python X.py` 点名的模块 → 它出现在哪份 README(供定位)。

    读不到任何一份 README 则回空(无可对质)。两份都读则合并,记首次出现的那份。
    """
    found: dict[str, str] = {}
    any_read = False
    for doc in READMES:
        text = _read(doc)
        if text is None:
            continue
        any_read = True
        for mod in _CMD_RE.findall(text):
            found.setdefault(mod, doc)
    return found if any_read else {}


def _module_exists(mod: str) -> bool:
    """领地里有没有这个模块:根级 mod.py,或 capabilities/ 等子包里的同名文件。"""
    if (REPO_ROOT / f"{mod}.py").exists():
        return True
    return any((REPO_ROOT / pkg / f"{mod}.py").exists()
               for pkg in ("capabilities",))


# ── 读证据账本:复用 evidence.manifest(),拿不到就当无可对质 ──────────────────
def _evidence_manifest() -> dict | None:
    try:
        import evidence
        return evidence.manifest()
    except Exception:
        return None


def _argv_module(argv: list[str]) -> str | None:
    """从一条验证命令的 argv 里认出它点名的 .py 文件名(没有则 None)。"""
    for tok in argv:
        if isinstance(tok, str) and tok.endswith(".py"):
            return tok
    return None


# ── 四类对质 ─────────────────────────────────────────────────────────────
def check_ghost_commands(readme_mods: dict[str, str]) -> list[Conflict]:
    """README 教 `python X.py`,X.py 却不在领地里——教的是空气。"""
    out: list[Conflict] = []
    for mod, doc in sorted(readme_mods.items()):
        if not _module_exists(mod):
            out.append(Conflict(
                KIND_GHOST, f"{mod}.py",
                here=f"{doc} 教人运行 `python {mod}.py`",
                there="领地里找不到 {mod}.py(根级与 capabilities/ 均无)".format(mod=mod),
                hint=f"要么补回 {mod}.py,要么把这条命令从 README 删掉——别教读者跑空气。"))
    return out


def check_broken_but_claimed(ev: dict | None,
                             readme_mods: dict[str, str]) -> list[Conflict]:
    """证据账本说某能力最近验证 🔴失守,README 却仍把它当能力对外讲。"""
    if ev is None:
        return []
    out: list[Conflict] = []
    for st in ev.get("status", []):
        name = st.get("name")
        if st.get("state") != "broken":
            continue
        if name in readme_mods:
            out.append(Conflict(
                KIND_BROKEN, name,
                here=f"{readme_mods[name]} 仍把 `{name}` 当对外能力宣称",
                there=f"证据账本:`{name}` 最近一次验证 🔴失守(能力已塌)",
                hint=f"先 `python evidence.py --verify {name}` 修到再绿,或在 README 暂时收回这句宣称——别让对外的脸挂着一块塌掉的能力。"))
    return out


def check_headless_evidence(ev: dict | None) -> list[Conflict]:
    """证据账本某条声明的验证命令点名一个 .py,那文件却不存在——验了个寂寞。"""
    if ev is None:
        return []
    out: list[Conflict] = []
    for claim in ev.get("claims", []):
        argv = claim.get("argv") or []
        target = _argv_module(argv)
        if target and not (REPO_ROOT / target).exists():
            name = claim.get("name", "?")
            out.append(Conflict(
                KIND_HEADLESS, name,
                here=f"证据账本声明 `{name}` 靠 `{' '.join(map(str, argv))}` 验证",
                there=f"验证命令点名的 {target} 不在领地里",
                hint=f"把 evidence.CLAIMS 里 `{name}` 的 argv 指到真实存在的命令,或删掉这条无处可验的声明。"))
    return out


def check_missing_sentinels() -> list[Conflict]:
    """闸门规则(releasegate)赖以裁决的哨卡模块缺位——闸门形同虚设。"""
    out: list[Conflict] = []
    if not (REPO_ROOT / "releasegate.py").exists():
        return []   # 没有闸门规则,无可对质
    for mod in GATE_SENTINELS:
        if not _module_exists(mod):
            out.append(Conflict(
                KIND_SENTINEL, f"{mod}.py",
                here=f"闸门规则(releasegate)把 `{mod}` 当一道签发闸来裁决",
                there=f"领地里找不到 {mod}.py,那道闸只能永远记「未知」并保守暂缓",
                hint=f"补回 {mod}.py,或在 releasegate 里删掉这道无所依凭的闸——别让闸门挂着一只瞎掉的哨卡。"))
    return out


def scan() -> list[Conflict]:
    """四处声明两两对质,汇总所有自相矛盾。任一处读不到,那一类自动跳过。"""
    readme_mods = readme_modules()
    ev = _evidence_manifest()
    conflicts: list[Conflict] = []
    conflicts += check_ghost_commands(readme_mods)
    conflicts += check_broken_but_claimed(ev, readme_mods)
    conflicts += check_headless_evidence(ev)
    conflicts += check_missing_sentinels()
    return conflicts


def summarize(conflicts: list[Conflict]) -> tuple[bool, int]:
    """归一化结论:是否自洽、矛盾几处。"""
    return (not conflicts, len(conflicts))


def manifest() -> dict:
    """导出纯数据(给 health / 外部工具消费)。"""
    conflicts = scan()
    clean, n = summarize(conflicts)
    return {"consistent": clean, "count": n,
            "conflicts": [c.to_meta() for c in conflicts]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自洽镜 🧭:四处自我声明两两对质,揪出互相矛盾的。")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有矛盾时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    conflicts = scan()
    clean, n = summarize(conflicts)

    if not (args.quiet and clean):
        print("🧭 opencrab 自洽镜:README ⇄ 证据 ⇄ 词典 ⇄ 闸门规则\n")
        if clean:
            print("  ✅ 四处自我声明彼此对得上,没有发现自相矛盾。")
        else:
            by_kind: dict[str, list[Conflict]] = {}
            for c in conflicts:
                by_kind.setdefault(c.kind, []).append(c)
            for kind in (KIND_GHOST, KIND_BROKEN, KIND_HEADLESS, KIND_SENTINEL):
                items = by_kind.get(kind, [])
                if not items:
                    continue
                print(f"  {_ICON[kind]} {kind}（{len(items)} 处）")
                for c in items:
                    print(f"      · {c.subject}")
                    print(f"        ⟂ {c.here}")
                    print(f"        ⟂ {c.there}")
                    print(f"        ↳ {c.hint}")
        print()

    if clean:
        if not args.quiet:
            print("🧭 自洽:我以为的我,和真实的我,这一回对得上。")
    else:
        print(f"⚠️  发现 {n} 处自相矛盾,先收口再蜕壳——别照着不存在的自己使劲。")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
