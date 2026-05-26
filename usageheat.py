#!/usr/bin/env python3
"""能力使用热力图 🔥🧊 —— 把每个器官「最近有没有真在工作」摊成一张冷热分布图。

为什么要有它：领地里躺着八十多个 `*.py`，每一个都自称一项能力。可进化是有方向的——
它默认「我身上的器官都还活着、都还在用」，于是一遍遍往上加新壳。但真相往往是：
有些器官上次被验证已是很久以前（账本早凉），有些连 `--help` 都推不开（壳烂在那），
还有些自打写下就再没在任何一次心跳里被提起（写完即遗忘）。**盲目加壳的前提，是先
看清哪些旧壳其实已经不工作了。**

热力图不新增能力，只把三处既有痕迹按「模块」对齐，算出每个器官的「体温」：

  · 🩸 **审计痕迹**（audit）——最近 N 天的心跳里，哪些模块在意图/动手记录里被点过名。
    被反复提起 = 仍在进化的热区；从没出现 = 久无人问津的冷宫。
  · 🧾 **证据账本**（evidence）——这项能力上次被复验是多久以前、当时绿没绿。
    久未验证（账本发凉）或最近 🔴失守，都是该亲自去摸一摸的信号。
  · 🚪 **入口存活**（navigator，可选 --probe）——真去推一遍这扇门的 `--help`。
    推不开的（import 炸 / argparse 错 / 卡死）就是当场失败的高频热点。

每个器官据此落到一档体温：
  🔥 发烫   —— 入口推不开，或证据账本 🔴失守。当场就在失败，最该先修。
  🌡️ 温活   —— 近期被提起且账本还算新鲜。这是真在工作的器官。
  🧊 冰封   —— 久未被提起，且账本发凉 / 从未验证。写完即遗忘的旧壳，加新壳前先问它还要不要。
  ◽ 常温   —— 介于之间，无明显冷热信号。

判准：热力图是**观测者**——只读审计、只调 evidence/navigator 的 manifest，绝不写
journal / state、不改任何文件。任一处痕迹读不到，那一维信号记为「未知」并跳过，绝不臆测。
发现任意「🔥 发烫」器官即让退出码非零（可挂进钩子 / CI 当门禁）；冰封只是提醒，不致退出非零。

用法：
    python usageheat.py             # 打印全器官冷热分布（不实跑入口，最快）
    python usageheat.py --probe     # 额外实跑每扇门的 --help，把推不开的标为发烫
    python usageheat.py --days 14   # 审计回溯窗口（默认 7 天）
    python usageheat.py --cold      # 只列冰封器官（久未问津的旧壳）
    python usageheat.py --quiet     # 只在有发烫器官时说话（适合钩子 / CI）
    python usageheat.py --json      # 机读：导出每个器官的体温、各维信号与最近痕迹

退出码：0 = 没有发烫器官；1 = 有器官当场失败（入口推不开 / 证据失守）。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 审计里点名一个模块的写法：意图/动手记录中出现的 `foo.py` 或 `foo`（带反引号）。
_MOD_RE = re.compile(r"`?([a-z_][a-z0-9_]*)\.py`?")

# 账本发凉的门槛：上次验证超过这么多天，就算「久未验证」。
_STALE_DAYS = 7.0

# ── 体温分档 ──────────────────────────────────────────────────────────
TEMP_HOT = "发烫"     # 当场失败：入口推不开 / 证据失守
TEMP_WARM = "温活"    # 近期被提起 + 账本新鲜
TEMP_COLD = "冰封"    # 久未问津 + 账本发凉 / 从未验证
TEMP_MILD = "常温"    # 无明显冷热

_ICON = {TEMP_HOT: "🔥", TEMP_WARM: "🌡️", TEMP_COLD: "🧊", TEMP_MILD: "◽"}
_ORDER = (TEMP_HOT, TEMP_COLD, TEMP_WARM, TEMP_MILD)


@dataclasses.dataclass
class Heat:
    """一个器官的冷热画像：三维信号 + 归一化体温。"""
    name: str                       # 模块名，如 "evidence"
    summary: str                    # 一句自述（取自模块 docstring 首行）

    # 🩸 审计维：最近窗口里被点名的心跳次数 + 最近一次被提起的时间
    mentions: int = 0
    last_seen: str | None = None    # ISO 时间戳（被点名）

    # 🧾 证据维：上次复验距今天数 + 当时状态（None=该模块没有对应证据声明）
    verify_state: str | None = None  # fresh / stale / broken / unproven
    age_days: float | None = None

    # 🚪 入口维：实跑 --help 的存活（None=未探测）
    alive: bool | None = None
    dead_detail: str = ""

    temp: str = TEMP_MILD           # 归档后的体温
    reasons: list[str] = dataclasses.field(default_factory=list)

    def to_meta(self) -> dict:
        return {
            "name": self.name, "summary": self.summary, "temp": self.temp,
            "mentions": self.mentions, "last_seen": self.last_seen,
            "verify_state": self.verify_state, "age_days": self.age_days,
            "alive": self.alive, "dead_detail": self.dead_detail if self.alive is False else "",
            "reasons": self.reasons,
        }


# ── 🩸 审计维：最近 N 天里每个模块被点名多少次、最后一次何时 ─────────────────
def _audit_mentions(days: int) -> dict[str, tuple[int, str]]:
    """扫最近 days 天审计，统计每个模块在意图/动手记录里被点名的次数与最近时间。

    审计读不到（目录缺失 / 全为空）则回空——审计维记为「未知」，绝不臆测。
    """
    try:
        import audit
    except Exception:
        return {}

    today = datetime.date.today()
    out: dict[str, tuple[int, str]] = {}
    for back in range(days):
        day = (today - datetime.timedelta(days=back)).isoformat()
        try:
            recs = audit.read_records(day)
        except Exception:
            continue
        for r in recs:
            if r.get("event") not in ("intent", "act"):
                continue
            # 把这条记录里所有字符串字段拼起来找模块名（意图文本、journal 名等）
            blob = " ".join(str(v) for v in r.values() if isinstance(v, str))
            ts = r.get("ts", "")
            for mod in set(_MOD_RE.findall(blob)):
                n, last = out.get(mod, (0, ""))
                out[mod] = (n + 1, max(last, ts))
    return out


# ── 🧾 证据维：每个模块对应证据声明的复验新鲜度 ────────────────────────────
def _evidence_freshness() -> dict[str, tuple[str, float | None]]:
    """复用 evidence.manifest()，取每条声明的 state 与距今天数；拿不到则回空。"""
    try:
        import evidence
        m = evidence.manifest()
    except Exception:
        return {}
    out: dict[str, tuple[str, float | None]] = {}
    for st in m.get("status", []):
        name = st.get("name")
        if name:
            out[name] = (st.get("state"), st.get("age_days"))
    return out


# ── 🚪 入口维：实跑 --help 的存活（可选） ──────────────────────────────────
def _navigator_liveness(probe: bool) -> tuple[dict[str, "object"], dict[str, str]]:
    """从 navigator 取器官名册与（可选）存活探测。

    返回 (名册 name→summary, 失效 name→detail)。probe=False 时只取名册，不实跑。
    navigator 不可用则回空名册——退回扫根目录 *.py。
    """
    try:
        import navigator
        entries = navigator.survey(probe=probe)
    except Exception:
        return {}, {}
    roster = {e.name: e.summary for e in entries}
    dead = {e.name: e.detail for e in entries if getattr(e, "alive", None) is False}
    return roster, dead


def _fallback_roster() -> dict[str, str]:
    """navigator 不可用时的兜底名册：根目录所有 *.py（无自述）。"""
    return {p.stem: "（无自述）" for p in sorted(REPO_ROOT.glob("*.py"))
            if not p.stem.startswith("_")}


# ── 归档体温 ─────────────────────────────────────────────────────────
def _classify(h: Heat, audit_known: bool) -> None:
    """据三维信号给器官定档，并记下「为什么是这个温度」。"""
    reasons: list[str] = []

    # 🔥 发烫：当场就在失败——最高优先级
    if h.alive is False:
        reasons.append(f"入口推不开：{h.dead_detail}")
    if h.verify_state == "broken":
        reasons.append("证据账本最近一次验证 🔴失守")
    if reasons:
        h.temp, h.reasons = TEMP_HOT, reasons
        return

    # 各维的冷信号
    never_mentioned = audit_known and h.mentions == 0
    stale_verify = (h.verify_state == "stale"
                    or (h.age_days is not None and h.age_days >= _STALE_DAYS))
    unproven = h.verify_state == "unproven"

    # 🧊 冰封：久无人问津，且账本发凉 / 从未验证
    if never_mentioned and (stale_verify or unproven or h.verify_state is None):
        if never_mentioned:
            reasons.append(f"最近窗口里没在任何心跳被提起")
        if stale_verify:
            age = f"{h.age_days:.0f} 天前" if h.age_days is not None else "已久"
            reasons.append(f"证据账本上次复验在 {age}（已发凉）")
        elif unproven:
            reasons.append("从未被证据账本验证过")
        elif h.verify_state is None:
            reasons.append("没有对应的证据声明可复验")
        h.temp, h.reasons = TEMP_COLD, reasons
        return

    # 🌡️ 温活：近期被提起 + 账本还算新鲜
    fresh_verify = h.verify_state == "fresh" or (
        h.age_days is not None and h.age_days < _STALE_DAYS)
    if h.mentions > 0 and (fresh_verify or h.verify_state is None):
        if h.mentions > 0:
            reasons.append(f"最近窗口里被提起 {h.mentions} 次")
        if fresh_verify:
            reasons.append("证据账本近期复验仍 ✅绿")
        h.temp, h.reasons = TEMP_WARM, reasons
        return

    # ◽ 常温：信号互相抵消 / 不足
    if stale_verify:
        reasons.append("账本发凉但近期仍被提起")
    elif h.mentions == 0 and not audit_known:
        reasons.append("审计不可读，仅凭证据维判断")
    h.temp, h.reasons = TEMP_MILD, reasons or ["无明显冷热信号"]


def build(days: int = 7, probe: bool = False) -> list[Heat]:
    """对齐三处痕迹，产出每个器官的冷热画像（按体温→模块名排序）。"""
    roster, dead = _navigator_liveness(probe)
    if not roster:
        roster = _fallback_roster()
    mentions = _audit_mentions(days)
    audit_known = bool(mentions)
    fresh = _evidence_freshness()

    heats: list[Heat] = []
    for name in sorted(roster):
        n, last = mentions.get(name, (0, None))
        vstate, age = fresh.get(name, (None, None))
        h = Heat(
            name=name, summary=roster[name],
            mentions=n, last_seen=last or None,
            verify_state=vstate, age_days=age,
            alive=(False if name in dead else (True if probe else None)),
            dead_detail=dead.get(name, ""),
        )
        _classify(h, audit_known)
        heats.append(h)

    rank = {t: i for i, t in enumerate(_ORDER)}
    heats.sort(key=lambda h: (rank[h.temp], h.name))
    return heats


def summarize(heats: list[Heat]) -> dict[str, int]:
    """各档体温的器官计数。"""
    out = {t: 0 for t in _ORDER}
    for h in heats:
        out[h.temp] += 1
    return out


def manifest(days: int = 7, probe: bool = False) -> dict:
    """机读：全器官画像 + 各档计数 + 发烫名单。"""
    heats = build(days=days, probe=probe)
    counts = summarize(heats)
    hot = [h.name for h in heats if h.temp == TEMP_HOT]
    return {
        "days": days, "probed": probe, "total": len(heats),
        "counts": counts, "hot": hot,
        "cold": [h.name for h in heats if h.temp == TEMP_COLD],
        "heats": [h.to_meta() for h in heats],
    }


# ── 渲染 ─────────────────────────────────────────────────────────────
def _render(heats: list[Heat], days: int, probed: bool, cold_only: bool) -> str:
    counts = summarize(heats)
    L = [f"🔥🧊 opencrab 能力使用热力图 —— 近 {days} 天审计 ⨉ 证据 ⨉ "
         f"入口{'（已实跑）' if probed else '（未实跑，加 --probe 测活）'}", ""]

    shown = [h for h in heats if h.temp == TEMP_COLD] if cold_only else heats
    by_temp: dict[str, list[Heat]] = {}
    for h in shown:
        by_temp.setdefault(h.temp, []).append(h)

    for temp in _ORDER:
        items = by_temp.get(temp, [])
        if not items:
            continue
        L.append(f"{_ICON[temp]} {temp}（{len(items)} 个）")
        for h in items:
            L.append(f"   {h.name}.py — {h.summary}")
            for why in h.reasons:
                L.append(f"      · {why}")
        L.append("")

    bar = "  ".join(f"{_ICON[t]}{t} {counts[t]}" for t in _ORDER)
    L.append(f"分布：{bar}")
    if counts[TEMP_HOT]:
        L.append(f"⚠️  有 {counts[TEMP_HOT]} 个器官当场在失败（发烫），加新壳前先修好这几个。")
    elif counts[TEMP_COLD]:
        L.append(f"🧊 没有发烫器官，但有 {counts[TEMP_COLD]} 个冰封——加新壳前先问问它们还要不要。")
    else:
        L.append("🦀 没有发烫器官，在用的器官大多温活。")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 能力使用热力图 🔥🧊 —— 从审计/证据/入口痕迹标出久未验证、高频失败的器官")
    ap.add_argument("--days", type=int, default=7, metavar="N",
                    help="审计回溯窗口天数（默认 7）")
    ap.add_argument("--probe", action="store_true",
                    help="额外实跑每扇门的 --help，把推不开的标为发烫")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--cold", action="store_true", help="只列冰封器官（久未问津的旧壳）")
    g.add_argument("--quiet", action="store_true",
                   help="只在有发烫器官时说话（适合钩子 / CI）")
    g.add_argument("--json", action="store_true",
                   help="机读：导出每个器官的体温、各维信号与最近痕迹")
    args = ap.parse_args(argv)

    if args.days < 1:
        print(f"❌ --days 需为正整数，收到 {args.days}")
        sys.exit(2)

    if args.json:
        print(json.dumps(manifest(days=args.days, probe=args.probe),
                         ensure_ascii=False, indent=2))
        sys.exit(0)

    heats = build(days=args.days, probe=args.probe)
    counts = summarize(heats)
    hot = counts[TEMP_HOT]

    if args.quiet:
        if hot:
            names = "、".join(h.name for h in heats if h.temp == TEMP_HOT)
            print(f"🔥 热力图：{hot} 个器官当场在失败 —— {names}")
            for h in heats:
                if h.temp == TEMP_HOT:
                    print(f"   {_ICON[TEMP_HOT]} {h.name}.py：{'；'.join(h.reasons)}")
    else:
        print(_render(heats, args.days, args.probe, args.cold))

    sys.exit(1 if hot else 0)


if __name__ == "__main__":
    main()
