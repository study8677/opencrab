#!/usr/bin/env python3
"""发布前闸门 🚦📦 —— 蜕壳推出去之前的最后一次「能不能签发」总决。

为什么要有它：opencrab 每天自改、自提交、自推送到**公开仓库**。它身上已经长出
好几只各管一段的哨卡——evidence 管「能力声明有没有活证据」、secretscan 管「这次
暂存的改动会不会泄密」、supplychain 管「对外暴露面守不守得住」、changelog 管「这
轮蜕壳到底改了什么、有没有挂过的风险」。但它们各说各话：单看任何一只，都答不上
那个**真正要拍板的问题**——

  **现在这个状态，到底能不能安全地签发出去？不能的话，差哪几件？**

releasegate 不重复造扫描，它做**汇聚与裁决**：把四道哨卡的结论收拢成统一的「闸门」，
每道闸门给一个红黄绿灯，再合成一个总决——🟢 可签发 / 🔴 暂缓——并落成一份**可签发
清单**(放行的理由)与**暂缓清单**(到底卡在哪、下一步动什么)。进化要能安全交付，
就得有这么一道说「现在别推」的闸。

四道闸门（缺一只哨卡不致命，那道闸记为「未知」并按保守口径处理）：
  · 🧾 证据闸  —— 能力声明是否都有新鲜有效证据（broken/unproven 卡门）。
  · 🔑 密钥闸  —— 本次暂存改动是否新引入密钥/隐私（高危泄漏卡门）。
  · 🔗 供应链  —— 对外暴露面是否守得住（高危供应链隐患卡门）。
  · 📋 变更闸  —— 这轮是否有可发布的变更、且无未结的已知风险。

用法:
    python releasegate.py            # 跑总决，打印可签发/暂缓清单
    python releasegate.py --quiet    # 只在暂缓(有阻断)时说话，适合钩子 / CI
    python releasegate.py --json      # 导出纯数据（给 health / 外部工具消费）

退出码：0 = 可签发；1 = 暂缓（至少一道闸阻断）。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── 闸门裁决：三档红黄绿，外加哨卡缺位时的「未知」 ────────────────────────
VERDICT_PASS = "pass"      # 🟢 这道闸放行
VERDICT_WARN = "warn"      # 🟡 有提醒，不阻断签发
VERDICT_BLOCK = "block"    # 🔴 阻断签发，必须先处理
VERDICT_UNKNOWN = "unknown"  # ⬜ 哨卡不可用：保守起见计入暂缓

_VERDICT_ICON = {
    VERDICT_PASS: "🟢", VERDICT_WARN: "🟡",
    VERDICT_BLOCK: "🔴", VERDICT_UNKNOWN: "⬜",
}
# 哪些裁决会按下「暂缓」：阻断当然，未知也保守地拦下（哨卡瞎了不等于安全）。
_HOLDING = {VERDICT_BLOCK, VERDICT_UNKNOWN}


@dataclasses.dataclass(frozen=True)
class Gate:
    """一道发布闸门：哪只哨卡、亮什么灯、一句结论、阻断项与提醒项。"""
    key: str
    icon: str
    name: str
    verdict: str
    headline: str               # 一句话结论，可直接打印
    blockers: tuple[str, ...] = ()   # 卡门的具体原因（暂缓清单的素材）
    warnings: tuple[str, ...] = ()   # 不阻断但值得看一眼

    @property
    def holds(self) -> bool:
        return self.verdict in _HOLDING

    def to_meta(self) -> dict:
        return {"key": self.key, "name": self.name, "verdict": self.verdict,
                "headline": self.headline,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings)}


def _unavailable(key: str, icon: str, name: str, err: Exception) -> Gate:
    """某只哨卡导入/执行失败：记为未知闸，保守计入暂缓。"""
    return Gate(key=key, icon=icon, name=name, verdict=VERDICT_UNKNOWN,
                headline=f"哨卡不可用，无法判定（{type(err).__name__}: {err}）",
                blockers=(f"修复 {key} 哨卡后重跑闸门，或人工确认该项安全。",))


# ── 四道闸门：各自只调对应哨卡的 manifest()，把结论翻成红黄绿 ──────────────
def gate_evidence() -> Gate:
    """证据闸：能力声明是否都有新鲜有效证据。broken/unproven 卡门，stale 提醒。"""
    key, icon, name = "evidence", "🧾", "证据闸"
    try:
        import evidence
        m = evidence.manifest()
    except Exception as e:  # noqa: BLE001 —— 哨卡瞎了按未知处理，绝不放行
        return _unavailable(key, icon, name, e)

    counts: dict[str, int] = {"fresh": 0, "stale": 0, "broken": 0, "unproven": 0}
    for s in m.get("status", []):
        st = s.get("state")
        if st in counts:
            counts[st] += 1

    blockers: list[str] = []
    warnings: list[str] = []
    if counts["broken"]:
        blockers.append(f"{counts['broken']} 条能力声明证据失守（broken），先复验或撤回声明。")
    if counts["unproven"]:
        blockers.append(f"{counts['unproven']} 条声明从无活证据（unproven），补一次可复现验证。")
    if counts["stale"]:
        warnings.append(f"{counts['stale']} 条证据已过期（stale），建议本轮顺手复验。")

    if blockers:
        verdict = VERDICT_BLOCK
        headline = f"证据不足以签发：broken {counts['broken']} · unproven {counts['unproven']}。"
    elif warnings:
        verdict = VERDICT_WARN
        headline = f"证据可放行，但有 {counts['stale']} 条过期待复验。"
    else:
        verdict = VERDICT_PASS
        headline = f"全部能力声明证据新鲜有效（fresh {counts['fresh']}）。"
    return Gate(key, icon, name, verdict, headline,
                tuple(blockers), tuple(warnings))


def gate_secrets() -> Gate:
    """密钥闸：本次暂存改动的新增行有没有引入密钥/隐私。高危卡门，低危提醒。"""
    key, icon, name = "secretscan", "🔑", "密钥闸"
    try:
        import secretscan
        m = secretscan.manifest()  # 默认只看 git diff --cached 的新增行
    except Exception as e:  # noqa: BLE001
        return _unavailable(key, icon, name, e)

    high, low = int(m.get("high", 0)), int(m.get("low", 0))
    scope = m.get("scope", "staged")
    blockers: list[str] = []
    warnings: list[str] = []
    for leak in m.get("leaks", []):
        loc = f"{leak.get('path', '?')}:{leak.get('line', '?')}"
        line = f"[{loc}] {leak.get('kind', '')} —— {leak.get('hint', '')}"
        (blockers if leak.get("severity") == "high" else warnings).append(line)

    if high:
        verdict = VERDICT_BLOCK
        headline = f"暂存改动里有 {high} 处高危泄漏，脱敏后才能提交/发布（scope={scope}）。"
    elif low:
        verdict = VERDICT_WARN
        headline = f"暂存改动无高危泄漏，{low} 处低危值得脱敏（scope={scope}）。"
    else:
        verdict = VERDICT_PASS
        headline = f"暂存改动未引入密钥/隐私（scope={scope}）。"
    return Gate(key, icon, name, verdict, headline,
                tuple(blockers), tuple(warnings))


def gate_supplychain() -> Gate:
    """供应链闸：对外暴露面是否守得住。高危隐患卡门，低危提醒。"""
    key, icon, name = "supplychain", "🔗", "供应链闸"
    try:
        import supplychain
        m = supplychain.manifest()
    except Exception as e:  # noqa: BLE001
        return _unavailable(key, icon, name, e)

    high, low = int(m.get("high", 0)), int(m.get("low", 0))
    blockers: list[str] = []
    warnings: list[str] = []
    for f in m.get("findings", []):
        loc = f.get("path", "") + (f":{f.get('line')}" if f.get("line") else "") or "（仓库级）"
        line = f"[{loc}] {f.get('kind', '')} —— {f.get('hint', '')}"
        (blockers if f.get("severity") == "high" else warnings).append(line)

    if high:
        verdict = VERDICT_BLOCK
        headline = f"对外暴露面有 {high} 处高危隐患，堵住再签发。"
    elif low:
        verdict = VERDICT_WARN
        headline = f"暴露面无高危隐患，{low} 处低危待清。"
    else:
        verdict = VERDICT_PASS
        headline = "对外暴露面守得住：无高危供应链隐患。"
    return Gate(key, icon, name, verdict, headline,
                tuple(blockers), tuple(warnings))


def gate_changelog(since_days: int = 7) -> Gate:
    """变更闸：这轮是否真有可发布的变更，且没有未结的已知风险。"""
    key, icon, name = "changelog", "📋", "变更闸"
    try:
        import changelog
        m = changelog.manifest(since_days)
    except Exception as e:  # noqa: BLE001
        return _unavailable(key, icon, name, e)

    changes = m.get("changes", {})
    n_added = len(changes.get("added", []))
    n_fixed = len(changes.get("fixed", []))
    risks = changes.get("risk", [])
    n_total = n_added + n_fixed + len(risks)

    blockers: list[str] = []
    warnings: list[str] = []
    if m.get("has_risk") or risks:
        for r in risks:
            blockers.append(f"未结风险：{r.get('summary', r.get('title', '（见 changelog）'))}")
        if not risks:
            blockers.append("changelog 标记本轮存在风险，签发前先确认已收口。")
    if n_total == 0:
        blockers.append(f"近 {since_days} 天没有可发布的变更，没有要签发的东西。")

    if blockers:
        verdict = VERDICT_BLOCK
        headline = f"变更闸暂缓：{'有未结风险' if (risks or m.get('has_risk')) else '无可发布变更'}。"
    else:
        verdict = VERDICT_PASS
        headline = f"近 {since_days} 天有 {n_added} 新增 / {n_fixed} 修复，且无未结风险。"
    return Gate(key, icon, name, verdict, headline,
                tuple(blockers), tuple(warnings))


# ── 总决：四道闸合成一个签发/暂缓裁定 ──────────────────────────────────────
def assess(since_days: int = 7) -> list[Gate]:
    """跑齐四道闸门，返回有序的闸门列表（顺序即清单展示顺序）。"""
    return [
        gate_evidence(),
        gate_secrets(),
        gate_supplychain(),
        gate_changelog(since_days),
    ]


def decide(gates: list[Gate]) -> tuple[bool, str]:
    """合成总决：只要有一道闸暂缓（阻断/未知），整体就暂缓。返回 (可签发?, 一句话)。"""
    holding = [g for g in gates if g.holds]
    if not holding:
        warned = sum(1 for g in gates if g.verdict == VERDICT_WARN)
        tail = f"（{warned} 道闸有低危提醒）" if warned else ""
        return True, f"✅ 可签发：四道闸全部放行{tail}。"
    names = "、".join(g.name for g in holding)
    return False, f"🛑 暂缓：{len(holding)} 道闸未过——{names}。"


def manifest(since_days: int = 7) -> dict:
    """导出纯数据（给 health / 外部工具消费）。"""
    gates = assess(since_days)
    shippable, verdict_line = decide(gates)
    return {
        "shippable": shippable,
        "verdict": verdict_line,
        "since_days": since_days,
        "gates": [g.to_meta() for g in gates],
        "blockers": [b for g in gates for b in g.blockers],
        "warnings": [w for g in gates for w in g.warnings],
    }


# ── 渲染：签发清单（绿灯理由）+ 暂缓清单（卡在哪、动什么）────────────────────
def _render(gates: list[Gate]) -> None:
    print("🚦 opencrab 发布前闸门\n")
    for g in gates:
        print(f"  {_VERDICT_ICON[g.verdict]} {g.icon} {g.name}：{g.headline}")
        for b in g.blockers:
            print(f"        🔴 {b}")
        for w in g.warnings:
            print(f"        🟡 {w}")
    print()

    shippable, verdict_line = decide(gates)
    if shippable:
        passes = [g for g in gates if g.verdict == VERDICT_PASS]
        print("📦 可签发清单（放行理由）")
        for g in passes:
            print(f"  · {g.icon} {g.name} — {g.headline}")
    else:
        print("⏸️  暂缓清单（先动这些再签发）")
        n = 0
        for g in gates:
            if not g.holds:
                continue
            for b in (g.blockers or (g.headline,)):
                n += 1
                print(f"  {n}. {g.icon} {g.name}：{b}")
    print()
    print(verdict_line)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 发布前闸门 🚦📦")
    ap.add_argument("--since-days", type=int, default=7,
                    help="变更闸回看的天数（默认 7）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在暂缓（有阻断）时输出，适合钩子 / CI")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(args.since_days), ensure_ascii=False, indent=2))
        return

    gates = assess(args.since_days)
    shippable, _ = decide(gates)

    if not (args.quiet and shippable):
        _render(gates)

    sys.exit(0 if shippable else 1)


if __name__ == "__main__":
    main()
