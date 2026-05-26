#!/usr/bin/env python3
"""自主依赖脱钩仪表 📉🦀 —— 把「每次自改到底靠不靠外援」钉成可观测的断奶趋势线。

一句话：**别再用一场比赛宣称「brain 能独立了」——把每次真实自改逐条点名:这一爪
调没调用外部 AI、有没有回滚、证据有没有回灌,再折成一条 7 日趋势线,让独立性被
持续观测,而不是被某次声称。**

为什么要有它：
  · `weaning_trial.py` 用一场实战赛证明「brain 此刻能不能独立修通几道真伤」——那是**快照**,
    赛赢了不代表日常自改就脱了外援。
  · `handsfeedback.py` 记下每只**外援爪子**(claude / codex)的可靠度——那是「外援多好用」,
    恰恰不是「我多不依赖外援」。
  · 独立性是个**趋势**,不是一次状态:今天少雇一次外援、明天 brain 自己多修一道、
    回滚率压下来、每一爪都把证据回灌……这些得连成线看,才知道断奶在不在真的发生。

本层不产生新数据,只**汇流**两本既有账本,把每条自改归一成一个「脱钩事件」：
  · 外援自改(external) —— `handsfeedback` 账本里每条 hands 记录:雇了 claude/codex 动手。
  · 独立自改(brain)   —— `weaning_trial` 账本里每道 bout:brain 不雇外援、单凭读报错自修。

三个被持续观测的量(都按天折叠成 7 日趋势)：
  · 脱钩率(decoupling) = 独立自改数 ÷ 全部自改数   —— 断奶的**主线**,越高越独立;
  · 回滚率(rollback)   = 回滚自改数 ÷ 全部自改数   —— 修不动就老实回滚,不硬塞坏补丁;
  · 回灌率(reflow)     = 落进证据账本的自改数 ÷ 全部 —— 每一爪都该沉淀成可复跑的证据。

趋势判读:把 7 日切成前后两段,比脱钩率均值——
  📈 断奶中(weaning)   后段比前段高:对外援的依赖在退;
  ➖ 持平(flat)        没明显变化;
  📉 回潮(regressing)  后段反而更依赖外援——该警觉。

当脱钩率低于达标线**且**趋势在回潮,退出码非零,可挂进钩子/CI 当「别躺平」的断奶告警;
数据不足(还没攒够自改)时只观望、不告警(退出码 0)——没数据不是退步。

用法：
    python autonomy_meter.py              # 仪表盘:总览 + 7 日趋势线
    python autonomy_meter.py --json       # 机读快照(给 health / 外部消费)
    python autonomy_meter.py --selfcheck  # 自检:汇流/折叠/趋势判读在合成数据上成立
    加 --quiet 静默,仅在「脱钩率不达标且回潮」时说话(适合钩子/CI)。

零第三方依赖,纯标准库。两本账本都落在被 .gitignore 的 state/ 里,读不到就当无数据,
绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402  —— 复用「读一批」的单一真相源

HANDS_LEDGER = REPO_ROOT / "state" / "handsfeedback" / "ledger.jsonl"
WEANING_LEDGER = REPO_ROOT / "state" / "weaning_trial.jsonl"

TREND_DAYS = 7            # 断奶趋势线的窗口:就看最近 7 天
DECOUPLE_GOAL = 0.5       # 脱钩率达标线:至少一半自改该由 brain 独立完成
MIN_EVENTS = 4            # 攒够这么多自改才开始判趋势/告警——样本太少不下结论


@dataclasses.dataclass(frozen=True)
class Event:
    """一次自改归一后的脱钩事件:它靠没靠外援、回没回滚、证据回没回灌。"""
    ts: float
    source: str            # "external"(雇了外援爪子) | "brain"(brain 独立自修)
    used_external_ai: bool
    rolled_back: bool      # 修不动→回滚保命(没硬塞坏补丁)
    evidence_fed: bool     # 这次判决有没有落进证据账本

    def to_meta(self) -> dict:
        return {"ts": self.ts, "source": self.source,
                "used_external_ai": self.used_external_ai,
                "rolled_back": self.rolled_back, "evidence_fed": self.evidence_fed}


# ── 汇流:两本既有账本 → 归一的脱钩事件 ────────────────────────────────
def _as_ts(v) -> float | None:
    """账本里的 ts 可能是 epoch 秒,也可能是 ISO 字符串;都归一成 epoch 秒。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(v, fmt).timestamp()
            except ValueError:
                continue
    return None


def hands_events(rows: list[dict]) -> list[Event]:
    """外援自改:`handsfeedback` 账本每条 = 一次雇外援爪子的自改。

    回滚 = 跑了自测却没过(hands 此时会断肢再生);回灌 = 跑了自测就会喂进证据账本
    (与 handsfeedback.feed 的口径一致:只有 self_tested 的那次才回灌)。
    """
    out: list[Event] = []
    for r in rows:
        ts = _as_ts(r.get("ts"))
        if ts is None:
            continue
        self_tested = bool(r.get("self_tested"))
        passed = bool(r.get("passed"))
        out.append(Event(
            ts=ts, source="external", used_external_ai=True,
            rolled_back=self_tested and not passed,
            evidence_fed=self_tested,
        ))
    return out


def brain_events(rows: list[dict]) -> list[Event]:
    """独立自改:`weaning_trial` 账本每次 run 里的每道 bout = brain 一次不雇外援的自修。

    回滚 = 这道 bout 触发了回滚(无招可解,老实吐回原样);回灌 = 战报已落进趋势账本,
    本身就是可复跑的证据,记 True。
    """
    out: list[Event] = []
    for r in rows:
        ts = _as_ts(r.get("ts"))
        if ts is None:
            continue
        bouts = r.get("bouts")
        if not isinstance(bouts, list) or not bouts:
            continue
        for b in bouts:
            if not isinstance(b, dict):
                continue
            out.append(Event(
                ts=ts, source="brain", used_external_ai=False,
                rolled_back=bool(b.get("rolled_back")),
                evidence_fed=True,
            ))
    return out


def load_events(*, now: float | None = None,
                hands_rows: list[dict] | None = None,
                brain_rows: list[dict] | None = None) -> list[Event]:
    """汇流两本账本成一串按时间正序的脱钩事件(只读,不落盘)。"""
    hands_rows = jsonlstore.read_jsonl(HANDS_LEDGER) if hands_rows is None else hands_rows
    brain_rows = jsonlstore.read_jsonl(WEANING_LEDGER) if brain_rows is None else brain_rows
    evs = hands_events(hands_rows) + brain_events(brain_rows)
    evs.sort(key=lambda e: e.ts)
    return evs


# ── 折叠:事件 → 总览 + 7 日趋势 ───────────────────────────────────────
def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def summarize(events: list[Event]) -> dict:
    """把一批事件折成总览三率:脱钩率 / 回滚率 / 回灌率。"""
    total = len(events)
    brain = sum(1 for e in events if not e.used_external_ai)
    rolled = sum(1 for e in events if e.rolled_back)
    fed = sum(1 for e in events if e.evidence_fed)
    return {
        "total": total,
        "brain": brain,
        "external": total - brain,
        "rolled_back": rolled,
        "evidence_fed": fed,
        "decoupling_rate": round(_rate(brain, total), 4),
        "rollback_rate": round(_rate(rolled, total), 4),
        "reflow_rate": round(_rate(fed, total), 4),
    }


@dataclasses.dataclass(frozen=True)
class DayStat:
    """某一天的脱钩切片。"""
    date: str               # YYYY-MM-DD
    total: int
    brain: int
    decoupling_rate: float | None   # 当天无自改→None(空白,不算 0)

    def to_meta(self) -> dict:
        return {"date": self.date, "total": self.total, "brain": self.brain,
                "decoupling_rate": self.decoupling_rate}


def daily_trend(events: list[Event], *, now: float | None = None,
                days: int = TREND_DAYS) -> list[DayStat]:
    """把事件按「自然日」折成最近 days 天的脱钩率序列(含无自改的空白日)。"""
    now = time.time() if now is None else now
    today = datetime.date.fromtimestamp(now)
    window = [today - datetime.timedelta(days=days - 1 - i) for i in range(days)]
    buckets: dict[str, list[Event]] = {d.isoformat(): [] for d in window}
    for e in events:
        key = datetime.date.fromtimestamp(e.ts).isoformat()
        if key in buckets:
            buckets[key].append(e)
    out: list[DayStat] = []
    for d in window:
        key = d.isoformat()
        evs = buckets[key]
        total = len(evs)
        brain = sum(1 for e in evs if not e.used_external_ai)
        rate = round(_rate(brain, total), 4) if total else None
        out.append(DayStat(date=key, total=total, brain=brain, decoupling_rate=rate))
    return out


def trend_verdict(trend: list[DayStat]) -> dict:
    """把趋势线判成断奶方向:比前后两段的脱钩率均值(只看有自改的天)。

    样本不足(有数据的天 < 2,或总自改 < MIN_EVENTS)→ "insufficient",不下结论。
    """
    active = [d for d in trend if d.decoupling_rate is not None]
    total = sum(d.total for d in trend)
    if len(active) < 2 or total < MIN_EVENTS:
        return {"direction": "insufficient", "early": None, "late": None,
                "delta": None, "active_days": len(active), "total": total}
    mid = len(active) // 2
    early = sum(d.decoupling_rate for d in active[:mid]) / mid
    late_part = active[mid:]
    late = sum(d.decoupling_rate for d in late_part) / len(late_part)
    delta = late - early
    if delta > 0.05:
        direction = "weaning"
    elif delta < -0.05:
        direction = "regressing"
    else:
        direction = "flat"
    return {"direction": direction, "early": round(early, 4), "late": round(late, 4),
            "delta": round(delta, 4), "active_days": len(active), "total": total}


def alarm(summary: dict, verdict: dict) -> bool:
    """该不该拉断奶告警:脱钩率低于达标线 **且** 趋势在回潮(且样本够)。

    样本不足时永不告警——没攒够自改不算退步。
    """
    if verdict["direction"] == "insufficient":
        return False
    return (summary["decoupling_rate"] < DECOUPLE_GOAL
            and verdict["direction"] == "regressing")


# ── 展示 ───────────────────────────────────────────────────────────────
_SPARK = "▁▂▃▄▅▆▇█"


def sparkline(rates: list[float | None]) -> str:
    """把 0~1 的脱钩率序列画成一行火花线;空白日(None)用「·」占位。"""
    cells = []
    for r in rates:
        if r is None:
            cells.append("·")
        else:
            idx = min(len(_SPARK) - 1, max(0, round(r * (len(_SPARK) - 1))))
            cells.append(_SPARK[idx])
    return "".join(cells)


_DIRECTION = {
    "weaning": "📈 断奶中(对外援的依赖在退)",
    "flat": "➖ 持平(脱钩率没明显变化)",
    "regressing": "📉 回潮(后段反而更依赖外援——该警觉)",
    "insufficient": "🌱 样本不足(还没攒够自改,先观望)",
}


def manifest(*, now: float | None = None,
             events: list[Event] | None = None) -> dict:
    """机读快照:总览三率 + 7 日趋势 + 断奶判读 + 是否告警。"""
    now = time.time() if now is None else now
    events = load_events(now=now) if events is None else events
    summary = summarize(events)
    trend = daily_trend(events, now=now)
    verdict = trend_verdict(trend)
    return {
        "event": "autonomy_meter",
        "summary": summary,
        "trend": [d.to_meta() for d in trend],
        "verdict": verdict,
        "alarm": alarm(summary, verdict),
        "params": {"trend_days": TREND_DAYS, "decouple_goal": DECOUPLE_GOAL,
                   "min_events": MIN_EVENTS},
    }


def _print(m: dict) -> None:
    s, v, trend = m["summary"], m["verdict"], m["trend"]
    print("📉🦀 自主依赖脱钩仪表（断奶被持续观测,不靠一次声称）\n")
    if s["total"] == 0:
        print("  （两本账本还空着——等真有几次自改落账,这里才长得出脱钩率与趋势线。）")
        print("    外援自改来自 handsfeedback 账本;独立自改来自 weaning_trial 账本。")
        return
    print(f"  全部自改 {s['total']} 次：独立 {s['brain']} · 外援 {s['external']}")
    print(f"    🔓 脱钩率 {s['decoupling_rate']:.0%}（独立自改占比，达标线 {DECOUPLE_GOAL:.0%}）")
    print(f"    🩹 回滚率 {s['rollback_rate']:.0%}（修不动就老实回滚的占比）")
    print(f"    🧾 回灌率 {s['reflow_rate']:.0%}（落进证据账本的占比）")

    rates = [d["decoupling_rate"] for d in trend]
    print(f"\n  最近 {TREND_DAYS} 天脱钩率趋势线：")
    print(f"    {sparkline(rates)}   {trend[0]['date'][5:]} → {trend[-1]['date'][5:]}")
    for d in trend:
        if d["total"]:
            bar = f"{d['decoupling_rate']:.0%}"
            print(f"      {d['date'][5:]}  独立 {d['brain']}/{d['total']}  脱钩 {bar}")

    print(f"\n  断奶趋势：{_DIRECTION[v['direction']]}")
    if v["direction"] not in ("insufficient",):
        print(f"      前段脱钩率 {v['early']:.0%} → 后段 {v['late']:.0%}"
              f"（{'+' if v['delta'] >= 0 else ''}{v['delta']:.0%}）")

    if m["alarm"]:
        print(f"\n⚠️  断奶告警：脱钩率 {s['decoupling_rate']:.0%} 低于达标线 {DECOUPLE_GOAL:.0%}"
              f"，且趋势回潮——别躺回外援，挑几道真伤让 brain 自己上。")
    elif v["direction"] == "weaning":
        print("\n🍼 断奶在真的发生：对外援的依赖正一天天退下去。")


# ── 自检:汇流/折叠/趋势判读都在合成数据上成立 ─────────────────────────
def _selfcheck() -> bool:
    """不读真账本,纯用合成数据验关键路径:归一、折叠三率、趋势判读、告警门槛。"""
    try:
        day = 86400.0
        base = datetime.datetime(2026, 5, 20, 12, 0, 0).timestamp()

        # 汇流:外援账本一条(自测过=未回滚、已回灌),brain 账本一次 run 两道 bout(一胜一回滚)
        hands = [{"ts": base, "self_tested": True, "passed": True, "executor": "claude"}]
        weaning = [{"ts": base, "bouts": [{"rolled_back": False}, {"rolled_back": True}]}]
        evs = load_events(hands_rows=hands, brain_rows=weaning)
        assert len(evs) == 3, evs
        assert sum(1 for e in evs if e.used_external_ai) == 1
        assert sum(1 for e in evs if e.rolled_back) == 1
        assert all(e.evidence_fed for e in evs)

        # 总览三率:3 次自改、2 独立 → 脱钩 2/3;回滚 1/3;回灌 3/3
        s = summarize(evs)
        assert s["total"] == 3 and s["brain"] == 2 and s["external"] == 1
        assert abs(s["decoupling_rate"] - 2 / 3) < 1e-9
        assert abs(s["rollback_rate"] - 1 / 3) < 1e-9
        assert s["reflow_rate"] == 1.0

        # 外援自测没过 → 该判回滚、且仍算回灌(self_tested)
        h2 = hands_events([{"ts": base, "self_tested": True, "passed": False}])
        assert h2[0].rolled_back and h2[0].evidence_fed
        # branch 模式(没自测)→ 不回滚也不回灌
        h3 = hands_events([{"ts": base, "self_tested": False, "passed": False}])
        assert not h3[0].rolled_back and not h3[0].evidence_fed

        # 趋势判读:前段全外援(脱钩 0),后段全独立(脱钩 1)→ 应判「断奶中」
        now = base + 2 * day
        rising_hands = [{"ts": base, "self_tested": True, "passed": True}] * 3
        rising_brain = [{"ts": base + day, "bouts": [{"rolled_back": False}]}] * 3
        rev = load_events(now=now, hands_rows=rising_hands, brain_rows=rising_brain)
        trend = daily_trend(rev, now=now, days=TREND_DAYS)
        assert len(trend) == TREND_DAYS
        v = trend_verdict(trend)
        assert v["direction"] == "weaning", v

        # 回潮 + 低脱钩 → 应告警;反过来断奶中不该告警。
        # 前段 brain 独立、后段全靠外援:脱钩率回落且总占比 2/6<达标线。
        falling_brain = [{"ts": base, "bouts": [{"rolled_back": False}]}] * 2
        falling_hands = [{"ts": base + day, "self_tested": True, "passed": True}] * 4
        fev = load_events(now=now, hands_rows=falling_hands, brain_rows=falling_brain)
        ftrend = daily_trend(fev, now=now, days=TREND_DAYS)
        fv = trend_verdict(ftrend)
        assert fv["direction"] == "regressing", fv
        assert alarm(summarize(fev), fv) is True
        assert alarm(summarize(rev), v) is False

        # 样本不足 → 不下结论、不告警
        tiny = load_events(now=now, hands_rows=[{"ts": base, "self_tested": True, "passed": True}],
                           brain_rows=[])
        tv = trend_verdict(daily_trend(tiny, now=now))
        assert tv["direction"] == "insufficient"
        assert alarm(summarize(tiny), tv) is False

        # 火花线:长度对齐,空白日占位
        line = sparkline([None, 0.0, 1.0])
        assert len(line) == 3 and line[0] == "·"

        # 空账本:全 0,不崩
        empty = manifest(now=now, events=[])
        assert empty["summary"]["total"] == 0 and empty["alarm"] is False
        return True
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自主依赖脱钩仪表 📉🦀")
    ap.add_argument("--json", action="store_true", help="导出机读快照")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检:汇流/折叠/趋势判读在合成数据上成立")
    ap.add_argument("--quiet", action="store_true",
                    help="只在脱钩率不达标且回潮时说话(适合钩子/CI)")
    args = ap.parse_args(argv)

    if args.selfcheck:
        ok = _selfcheck()
        if not args.quiet:
            print("📉🦀 自检" + ("通过：汇流/折叠/趋势判读都还稳。" if ok
                                  else "失败：脱钩仪表的某条路径出问题了。"))
        sys.exit(0 if ok else 1)

    m = manifest()
    if args.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
        sys.exit(1 if m["alarm"] else 0)

    if not (args.quiet and not m["alarm"]):
        _print(m)
    sys.exit(1 if m["alarm"] else 0)


if __name__ == "__main__":
    main()
