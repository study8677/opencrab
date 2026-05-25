#!/usr/bin/env python3
"""最小权限闸 🔐 —— 在动手之前，先问一句「这一档自治，配做这件事吗？」越权就当场拒。

这只螃蟹已经会自己改代码、跑测试、合并、甚至 push 公开（见 `OPENCRAB_AUTONOMY`：
journal | propose | merge | publish）。能力越长越多，**边界**就越要紧：自主进化最怕的
不是不会做，而是「明明只该写日志的一档，却伸手去 push 公共远端」——一次越权，半夜
无人盯着的心跳就能把没自测过的改动推到所有人面前。守不住边界的自治，是隐患不是本事。

这道闸做的事很窄，却是 act() 之前缺的最后一道关：它把所有敏感动作收敛到**五种权限**，
再为每一档自治声明一张**最小授权清单**——能做的明写，没写的一律默认拒。

  · 🔍 read    —— 读领地文件（盘点、扫描，最无害，人人有）
  · ✍️  write   —— 改动代码 / 在分支上动手（越过「只写 journal」的基线）
  · 🌐 network —— 联网（调大脑想、git fetch，账号与流量都在这扇门后）
  · ⚙️  execute —— 跑子进程命令（自测、git、借 claude/codex 的手）
  · 🚀 publish —— 把改动推向公共（merge 进主干 / push 远端，最不可逆，只有顶档配）

最小授权清单（escalating；没列出的权限即未授予）：

    journal : read · network                          # 只读领地 + 联网想，写 journal 是呼吸不受管
    propose : read · network · write · execute        # 借手在分支上改、跑自测
    merge   : read · network · write · execute        # 同 propose——多的是「可信到敢合本地」，不是多一种权限
    publish : read · network · write · execute · publish   # 唯一配把改动推向公共的一档

用法的核心是 `guard(action)`：把一个具名动作（或一组所需权限）交给它，当前 autonomy
配得上就放行，配不上就抛 `PermissionDenied`——调用方在真正动手**之前**调它，越权动作连
跑都跑不起来。闸本身是纯判断：只读 env 取当前档，不写任何文件、不联网、不跑命令。

用法：
    python permission.py                       # 打印权限矩阵 + 动作清单，并按当前 autonomy 标出哪些被拒
    python permission.py --check push_public   # 判定单个具名动作在当前档能否放行（被拒退出码 1）
    python permission.py --needs write,publish # 判定「需要这些权限的动作」能否放行（临时组合）
    python permission.py --autonomy publish    # 假设处在某一档来看（不改 env，只为推演）
    python permission.py --json                # 机读：导出 scopes / 各档授权 / 动作清单 / 当前判定

零第三方依赖，纯标准库。与 `policy.py` 互补：策略官管「该用什么姿态去做」，
这道闸管「这一档，到底配不配做」——姿态再激进，也越不过没授予的权限。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

# ── 五种权限（按敏感度从低到高排序，便于「这一档最多到哪」一目了然）──────────
READ = "read"          # 🔍 读领地文件
WRITE = "write"        # ✍️  改动代码 / 在分支上动手
NETWORK = "network"    # 🌐 联网（调大脑、git fetch）
EXECUTE = "execute"    # ⚙️  跑子进程命令
PUBLISH = "publish"    # 🚀 推向公共（merge 主干 / push 远端）

# 排序仅用于稳定地展示矩阵；语义上权限之间并非线性包含
_SCOPE_ORDER = [READ, WRITE, NETWORK, EXECUTE, PUBLISH]
_SCOPE_ICON = {READ: "🔍", WRITE: "✍️", NETWORK: "🌐", EXECUTE: "⚙️", PUBLISH: "🚀"}
ALL_SCOPES = frozenset(_SCOPE_ORDER)

# ── 每一档自治的最小授权清单（没列出的权限 = 未授予 = 默认拒）──────────────────
# 顺序也是胆量从小到大；journal 是默认（与 crab.py 一致）。
_DEFAULT_AUTONOMY = "journal"
GRANTS: dict[str, frozenset[str]] = {
    "journal": frozenset({READ, NETWORK}),
    "propose": frozenset({READ, NETWORK, WRITE, EXECUTE}),
    # merge 与 propose 的权限面相同——区别在「可信到敢把分支合进本地主干」，
    # 那是一份信任而非一种新权限；唯独 push 公共仍被挡在 publish 之外。
    "merge": frozenset({READ, NETWORK, WRITE, EXECUTE}),
    "publish": frozenset({READ, NETWORK, WRITE, EXECUTE, PUBLISH}),
}

# ── 具名动作 → 所需权限（这只蟹在一次心跳里真正会做的那些敏感动作）──────────
# 写 journal 是它的呼吸（任何一档都得能写日志活下去），故所需权限为空集 = 永远放行。
ACTIONS: dict[str, frozenset[str]] = {
    "sense_territory": frozenset({READ}),                       # 盘点领地：只读
    "write_journal": frozenset(),                               # 写日志：基线，永远放行
    "think": frozenset({NETWORK}),                              # 调大脑想意图
    "run_tests": frozenset({READ, EXECUTE}),                    # 跑自测/验证命令
    "git_fetch": frozenset({NETWORK, EXECUTE}),                 # 拉远端（联网 + 跑 git）
    "propose_branch": frozenset({READ, WRITE, EXECUTE}),        # 借手在分支上改代码
    "merge_local": frozenset({WRITE, EXECUTE}),                 # 把分支合进本地主干
    "push_public": frozenset({PUBLISH, NETWORK, EXECUTE}),      # 推向公共远端：最敏感
}


class PermissionDenied(PermissionError):
    """越权：当前自治档没有某个动作所需的全部权限时抛出，让动作连跑都跑不起来。"""


@dataclasses.dataclass
class Verdict:
    """一次权限判定的结论：放行与否、缺哪几种权限、人话依据。"""
    action: str                 # 动作名（具名动作或 "<needs:...>" 临时组合）
    autonomy: str               # 判定所基于的自治档
    needed: frozenset[str]      # 这个动作所需的权限
    granted: frozenset[str]     # 这一档授予的权限
    allowed: bool               # 是否放行
    missing: frozenset[str]     # 越权缺口（needed - granted）

    @property
    def reason(self) -> str:
        if self.allowed:
            need = "、".join(sorted(self.needed)) or "无（基线动作）"
            return f"放行：{self.autonomy} 档已授予所需权限（{need}）"
        miss = "、".join(sorted(self.missing))
        return f"拒绝：{self.autonomy} 档未授予 {miss}——越权，先把 OPENCRAB_AUTONOMY 调到配得上的档"

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "autonomy": self.autonomy,
            "needed": sorted(self.needed),
            "granted": sorted(self.granted),
            "allowed": self.allowed,
            "missing": sorted(self.missing),
            "reason": self.reason,
        }


def current_autonomy() -> str:
    """读 OPENCRAB_AUTONOMY 取当前自治档；不认识的值一律退回最保守的 journal。"""
    raw = (os.environ.get("OPENCRAB_AUTONOMY") or _DEFAULT_AUTONOMY).strip().lower()
    return raw if raw in GRANTS else _DEFAULT_AUTONOMY


def granted(autonomy: str | None = None) -> frozenset[str]:
    """某一档授予的权限集合；autonomy=None 时取 env 里的当前档。"""
    level = autonomy if autonomy in GRANTS else current_autonomy()
    return GRANTS[level]


def _needed(action: str, needs: set[str] | frozenset[str] | None) -> frozenset[str]:
    """把「动作」解析成所需权限：优先用显式 needs，否则查具名动作表。"""
    if needs is not None:
        unknown = set(needs) - ALL_SCOPES
        if unknown:
            raise ValueError(f"未知权限：{sorted(unknown)}；只认 {sorted(ALL_SCOPES)}")
        return frozenset(needs)
    if action not in ACTIONS:
        raise KeyError(
            f"未知动作 {action!r}；已登记：{sorted(ACTIONS)}（或用 needs= 显式给所需权限）")
    return ACTIONS[action]


def check(action: str, autonomy: str | None = None,
          needs: set[str] | frozenset[str] | None = None) -> Verdict:
    """判定一个动作在某一档下能否放行——只出结论，不抛异常、不动手。"""
    level = autonomy if autonomy in GRANTS else current_autonomy()
    need = _needed(action, needs)
    have = GRANTS[level]
    missing = frozenset(need - have)
    return Verdict(action=action, autonomy=level, needed=need,
                   granted=have, allowed=not missing, missing=missing)


def guard(action: str, autonomy: str | None = None,
          needs: set[str] | frozenset[str] | None = None) -> Verdict:
    """动手前的最后一道关：放行则返回 Verdict，越权则抛 PermissionDenied。

    调用方在**真正执行**敏感动作之前调它，例如：
        permission.guard("push_public")   # 不是 publish 档 → 这里就抛，push 根本跑不到
    """
    v = check(action, autonomy=autonomy, needs=needs)
    if not v.allowed:
        raise PermissionDenied(v.reason)
    return v


# ── 展示 ─────────────────────────────────────────────────────────────
def _matrix_lines() -> list[str]:
    """权限矩阵：每一档 × 五种权限，✅=授予 ·=未授予。"""
    head = "权限矩阵　　" + "  ".join(f"{_SCOPE_ICON[s]}{s}" for s in _SCOPE_ORDER)
    lines = [head]
    for level in GRANTS:  # dict 保序：journal→propose→merge→publish
        have = GRANTS[level]
        cells = []
        for s in _SCOPE_ORDER:
            mark = "✅" if s in have else "·"
            cells.append(f"{mark}{'　' * len(s)}")  # 用全角空格对齐到列宽
        lines.append(f"  {level:<8}" + "  ".join(
            ("✅" if s in have else "·").center(len(s) + 1) for s in _SCOPE_ORDER))
    return lines


def _render(autonomy: str) -> str:
    L = ["🦀🔐 opencrab 最小权限闸 —— 「这一档自治，配做这件事吗？」", ""]
    # 矩阵
    L.append("权限矩阵（行=自治档，列=权限；✅授予 ·未授予）：")
    header = "    " + "".join(f"{_SCOPE_ICON[s]}{s:<8}" for s in _SCOPE_ORDER)
    L.append("    " + " " * 10 + "".join(f"{s:<9}" for s in _SCOPE_ORDER))
    for level in GRANTS:
        have = GRANTS[level]
        row = "".join(("  ✅   " if s in have else "  ·    ") for s in _SCOPE_ORDER)
        cur = " ← 当前" if level == autonomy else ""
        L.append(f"    {level:<9}{row}{cur}")
    L.append("")
    # 动作清单：在当前档下逐个判定
    L.append(f"动作清单（在 autonomy={autonomy} 下判定）：")
    for name in ACTIONS:
        v = check(name, autonomy=autonomy)
        mark = "✅" if v.allowed else "❌"
        need = "、".join(sorted(v.needed)) or "—（基线，永远放行）"
        line = f"  {mark} {name:<16} 需要：{need}"
        if not v.allowed:
            line += f"　▶ 缺 {'、'.join(sorted(v.missing))}"
        L.append(line)
    denied = [n for n in ACTIONS if not check(n, autonomy=autonomy).allowed]
    L.append("")
    if denied:
        L.append(f"⚠️  当前 {autonomy} 档下，{len(denied)} 个动作会被拒：{'、'.join(denied)}"
                 f"——要做得调高 OPENCRAB_AUTONOMY。")
    else:
        L.append(f"🦀 当前 {autonomy} 档下，所有已登记动作都在授权内。")
    return "\n".join(L)


def snapshot(autonomy: str | None = None) -> dict:
    """机读：scopes / 各档授权 / 动作清单 / 当前档下逐动作判定。"""
    level = autonomy if autonomy in GRANTS else current_autonomy()
    return {
        "scopes": _SCOPE_ORDER,
        "autonomy": level,
        "grants": {lv: sorted(g) for lv, g in GRANTS.items()},
        "actions": {n: sorted(s) for n, s in ACTIONS.items()},
        "verdicts": {n: check(n, autonomy=level).to_dict() for n in ACTIONS},
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 最小权限闸 🔐 —— 为读/写/联网/执行/发布建最小授权清单，运行前拒越权动作")
    ap.add_argument("--autonomy", choices=sorted(GRANTS),
                    help="假设处在某一档来看（不改 env，只为推演；默认读 OPENCRAB_AUTONOMY）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", metavar="ACTION",
                   help=f"判定单个具名动作能否放行（{'/'.join(ACTIONS)}）")
    g.add_argument("--needs", metavar="P1,P2",
                   help=f"判定「需要这些权限的动作」能否放行；逗号分隔，取自 {'/'.join(_SCOPE_ORDER)}")
    g.add_argument("--json", action="store_true",
                   help="机读：导出 scopes / 各档授权 / 动作清单 / 当前判定")
    args = ap.parse_args(argv)

    level = args.autonomy or current_autonomy()

    if args.json:
        print(json.dumps(snapshot(autonomy=level), ensure_ascii=False, indent=2))
        sys.exit(0)

    if args.check or args.needs:
        try:
            if args.needs:
                wants = {p.strip().lower() for p in args.needs.split(",") if p.strip()}
                v = check(f"<needs:{','.join(sorted(wants))}>", autonomy=level, needs=wants)
            else:
                v = check(args.check, autonomy=level)
        except (KeyError, ValueError) as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(2)
        mark = "✅" if v.allowed else "🚫"
        print(f"{mark} {v.reason}")
        print(f"   动作：{v.action} · 需要：{'、'.join(sorted(v.needed)) or '无'} · "
              f"{level} 档授予：{'、'.join(sorted(v.granted))}")
        sys.exit(0 if v.allowed else 1)

    print(_render(level))
    sys.exit(0)


if __name__ == "__main__":
    main()
