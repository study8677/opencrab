#!/usr/bin/env python3
"""古德哈特探针 🛡️ —— 给评测分/价值分/信任分配一道反作弊闸:盯住「分」和它本该
代理的「真实被用」，一旦只涨分不增用，当场亮红灯。守住「别被漂亮数字骗」这条底线。

为什么要有它：这只螃蟹身上已经挂了一排打分的器官——`evalbench` 量整体强不强、
`value` 算每样本事值不值、`trustscore` 给证据打信任分。打分一多,就埋下一个最阴的坑:
**古德哈特定律**——「一个指标一旦成了目标,它就不再是好指标」。一旦开始冲分,最省力的
路从来不是「把活真做好」,而是「把分刷上去」:挑软柿子任务、对着验收集过拟合、把口径
往好看了改。于是仪表盘一片飘红向上,而**真实世界里没人多用它一次**。

这正是最该怕的骗局:分涨了,用没涨。本层只认一件事——**分的涨,得有真实使用的涨给它兜底**。
每个被守护的指标,都要同时报两条时间序列:

  · 📈 score —— 被优化的那个分(评测/价值/信任,都归一到 0~1,跨指标可比)。
  · 🌱 usage —— 它本该代理的**真实被用**信号(被采纳率/真实调用量/复用次数,同样归一)。
                这条才是地气:分可以刷,但「真有人在用」刷不出来。

闸门(和 ablation 同一种洁癖):序列太短(< MIN_POINTS)→ 证据不足,一个趋势点都凑不齐,
不配下判决。点够了,把序列切成**前段 / 后段**比均值(比单点首尾稳,抗噪声),量两个涨幅:

  · score_rise —— 后段比前段,分涨了多少。
  · usage_rise —— 后段比前段,真实被用涨了多少。
  · gap = score_rise − usage_rise —— 分**超出**真实使用的那一截。这就是古德哈特信号本体。

据 gap 下裁决:

  · 🟢 grounded(扎实)   —— 分没怎么涨(< MIN_RISE,没在冲分,无可疑),或分涨了但使用跟得上
                          (gap < 观察线)。涨得有地气,真进步。
  · 🟡 diverging(背离)  —— 分跑赢了使用一截(gap 在观察线与告警线之间)。还不至于报警,但
                          盯紧:再这么涨下去就是刷分。
  · 🔴 goodhart(刷分)   —— 分窜上去了,真实被用却没跟上(gap ≥ 告警线)。漂亮数字在骗你,
                          这个分已经不可信——别拿它当进步的证据。

metricguard 只**定义这道对照、守住闸门、记账、下裁决**:你把每个指标的 score/usage 两条
序列喂进来,它只负责诚实地比、诚实地亮灯。它不替你采集任何数、不替你改任何分——
它存在的唯一意义,就是当你（或未来的自己）开始为数字而活时,有一个东西敢说「这分是刷的」。

探针记进 `state/metricguard.jsonl`(一行一次探测,append-only),--status 折叠成「每个指标
最近一次探成了啥」,--alerts 单列出所有亮红/亮黄、正在背离真实使用的指标。

用法:
    python metricguard.py                 # 自检:闸门 + 趋势对照 + 三色裁决
    python metricguard.py --demo          # 演示三种结局(扎实/背离/刷分)各一例
    python metricguard.py --status        # 读账本,列每个指标最近一次探测裁决
    python metricguard.py --alerts        # 只列亮红/亮黄、正在背离真实使用的指标
    python metricguard.py --json          # 机读:导出当前各指标最近裁决
    python metricguard.py --quiet         # 只在自检不过时说话(适合钩子 / CI)

退出码:0 = 自检全过;1 = 任意一步不达约。
零第三方依赖,纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import sys

from jsonlstore import append_jsonl, read_jsonl

REPO_ROOT = pathlib.Path(__file__).resolve().parent
LEDGER = REPO_ROOT / "state" / "metricguard.jsonl"

# ── 三色裁决:分的涨,有没有真实使用给它兜底 ──────────────────────────────
GROUNDED = "grounded"          # 🟢 扎实:涨得有地气(或没在冲分)
DIVERGING = "diverging"        # 🟡 背离:分跑赢了使用一截,盯紧
GOODHART = "goodhart"          # 🔴 刷分:分窜上去,真实被用没跟上
INCONCLUSIVE = "inconclusive"  # ⬜ 证据不足:序列太短,凑不齐趋势

_EMOJI = {GROUNDED: "🟢", DIVERGING: "🟡", GOODHART: "🔴", INCONCLUSIVE: "⬜"}

# 裁决阈值(都以归一到 0~1 的涨幅为单位,跨指标可比):
MIN_POINTS = 4        # 少于这么多读数,一个前后段都切不出,不配下判决
MIN_RISE = 0.03       # 分涨幅低于此 → 没在冲分,无可疑(扎实)
WATCH_GAP = 0.05      # gap 低于此 → 使用跟得上(扎实)
ALERT_GAP = 0.15      # gap 高于此 → 分严重跑赢使用(刷分)


def _now() -> str:
    """统一的 UTC ISO 时间戳(秒级、带 Z),让账本里的时间可比、可排序。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trend(values: list[float]) -> float:
    """一条序列的「涨幅」:后段均值 − 前段均值。

    用前后两段比均值,而不是首尾两点相减——单点易被一次噪声带偏,分两半各取均值更稳。
    序列为奇数时,中点同时算进前段与后段(让两段都不至于太空),无伤大局。
    """
    n = len(values)
    half = n // 2
    first = values[:half] or values        # 兜底:极短序列时退化为全段
    second = values[n - half:] or values
    return sum(second) / len(second) - sum(first) / len(first)


@dataclasses.dataclass(frozen=True)
class Series:
    """一个被守护指标的两条时间序列:被优化的分,和它本该代理的真实被用。

    两条序列**按同一时间轴对齐**、等长——同一时刻的 score 与 usage 配成一对,
    才比得出「这一截分的涨,有没有使用给它兜底」。都归一到 0~1,跨指标可比。
    """
    metric: str                 # 指标名(如 "evalbench.overall" / "value.coach.py")
    scores: tuple[float, ...]   # 被优化的分,按时间先后(归一 0~1)
    usages: tuple[float, ...]   # 同时刻的真实被用信号,按时间先后(归一 0~1)

    def __post_init__(self) -> None:
        # 坏数据当场拦,别污染裁决:两条等长、非空、都落在 0~1。
        if len(self.scores) != len(self.usages):
            raise ValueError("score 与 usage 两条序列必须等长(按同一时间轴对齐)")
        for v in (*self.scores, *self.usages):
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"序列值须归一到 0~1,实见 {v}")

    @property
    def n(self) -> int:
        return len(self.scores)

    @property
    def score_rise(self) -> float:
        return _trend(list(self.scores))

    @property
    def usage_rise(self) -> float:
        return _trend(list(self.usages))

    @property
    def gap(self) -> float:
        """分超出真实使用的那一截——古德哈特信号本体。"""
        return self.score_rise - self.usage_rise

    def to_record(self) -> dict:
        return {"scores": list(self.scores), "usages": list(self.usages)}

    @staticmethod
    def from_record(metric: str, rec: dict) -> "Series":
        return Series(metric=metric,
                      scores=tuple(float(x) for x in rec.get("scores", [])),
                      usages=tuple(float(x) for x in rec.get("usages", [])))


def check_series(s: Series) -> list[str]:
    """探测前要守的红线;返回违规清单(空 = 闸门通过)。

    红线一条:序列至少要 MIN_POINTS 个读数,否则前后段切不出趋势,差异是噪声,
    不配判一个指标是不是在刷分。
    """
    errs: list[str] = []
    if s.n < MIN_POINTS:
        errs.append(f"证据不足:只有 {s.n} 个读数(< {MIN_POINTS}),凑不齐前后段趋势")
    return errs


@dataclasses.dataclass(frozen=True)
class Probe:
    """一次古德哈特探测的账本记录:守的哪个指标、两条序列、何时、凭什么。"""
    series: Series
    ts: str = ""                # UTC 时间戳,留空则取当下
    note: str = ""              # 一句话备注

    def __post_init__(self) -> None:
        if not self.ts:
            object.__setattr__(self, "ts", _now())

    def verdict(self) -> str:
        """据 score/usage 趋势对照下裁决(闸门不过 → inconclusive)。"""
        if check_series(self.series):
            return INCONCLUSIVE
        if self.series.score_rise < MIN_RISE:
            return GROUNDED                 # 没在冲分,无可疑
        gap = self.series.gap
        if gap >= ALERT_GAP:
            return GOODHART
        if gap >= WATCH_GAP:
            return DIVERGING
        return GROUNDED

    def to_record(self) -> dict:
        s = self.series
        return {
            "metric": s.metric,
            "verdict": self.verdict(),
            "score_rise": round(s.score_rise, 4),
            "usage_rise": round(s.usage_rise, 4),
            "gap": round(s.gap, 4),
            "series": s.to_record(),
            "ts": self.ts,
            "note": self.note,
        }


def record_probe(metric: str, scores, usages, *, note: str = "",
                 ledger: pathlib.Path = LEDGER) -> Probe:
    """落账一次古德哈特探测,返回该探测(含裁决)。

    序列太短也照记——一次证据不足的探测本身就是值得留痕的事实(提醒多攒几轮读数),
    但裁决会诚实地标成 inconclusive,绝不冒充判决。
    """
    p = Probe(series=Series(metric=metric, scores=tuple(scores), usages=tuple(usages)),
              note=note)
    append_jsonl(ledger, p.to_record())
    return p


def current_verdicts(ledger: pathlib.Path = LEDGER) -> dict[str, dict]:
    """把 append-only 账本折叠成「每个指标最近一次探成了啥」:同名取最后一条。"""
    out: dict[str, dict] = {}
    for rec in read_jsonl(ledger):
        metric = rec.get("metric")
        if metric:
            out[metric] = rec
    return out


def alerting(ledger: pathlib.Path = LEDGER) -> list[dict]:
    """最近一次亮红/亮黄、正在背离真实使用的指标(按 gap 降序——背离最狠的先看)。"""
    bad = [r for r in current_verdicts(ledger).values()
           if r.get("verdict") in (GOODHART, DIVERGING)]
    return sorted(bad, key=lambda r: r.get("gap", 0.0), reverse=True)


# ── 自检:闸门 + 趋势对照 + 三色裁决,一步不过即违约 ──────────────────────
def _selftest() -> list[str]:
    """返回失败清单(空 = 全过);每条都是自给自足、无副作用(不碰真账本)的真实调用。"""
    fails: list[str] = []

    def check(cond: bool, why: str) -> None:
        if not cond:
            fails.append(why)

    # 0) Series 坏数据当场拦:不等长 / 越界。
    try:
        Series("x", (0.1, 0.2), (0.1,))
        fails.append("两条序列不等长竟没被拦")
    except ValueError:
        pass
    try:
        Series("x", (0.1, 1.5), (0.1, 0.2))
        fails.append("越界值(>1)竟没被拦")
    except ValueError:
        pass

    # 1) _trend 算对:[0,0,1,1] 后段均值 1 − 前段均值 0 = 1.0。
    check(abs(_trend([0.0, 0.0, 1.0, 1.0]) - 1.0) < 1e-9, "_trend 该是 1.0")
    check(abs(_trend([0.5, 0.5, 0.5, 0.5])) < 1e-9, "平序列 _trend 该是 0")

    # 2) 闸门:序列太短判证据不足,够长才放行。
    short = Series("m", (0.1, 0.5), (0.1, 0.1))
    check(any("证据不足" in e for e in check_series(short)), "序列太短该被拦")
    check(not check_series(Series("m", (0.1, 0.2, 0.3, 0.4), (0.1, 0.2, 0.3, 0.4))),
          "够长的序列该让闸门通过")

    # 3) 裁决三结局:
    #    a) 刷分——分从 ~0.3 窜到 ~0.9,真实被用纹丝不动 ~0.2(gap 大 ≥ 告警线)。
    gh = Probe(Series("evalbench.overall",
                      (0.30, 0.35, 0.85, 0.90), (0.20, 0.20, 0.21, 0.19)))
    check(gh.verdict() == GOODHART, f"分窜升而使用不动该判刷分,实得 {gh.verdict()}")
    #    b) 背离——分涨得比使用快一截(gap 落在观察线与告警线之间)。
    dv = Probe(Series("value.coach.py",
                      (0.40, 0.42, 0.58, 0.62), (0.40, 0.41, 0.48, 0.50)))
    check(dv.verdict() == DIVERGING, f"分小幅跑赢使用该判背离,实得 {dv.verdict()}")
    #    c) 扎实——分和使用一块涨(gap < 观察线)。
    gd = Probe(Series("trustscore.contracts.py",
                      (0.40, 0.45, 0.70, 0.75), (0.38, 0.44, 0.69, 0.78)))
    check(gd.verdict() == GROUNDED, f"分与使用同涨该判扎实,实得 {gd.verdict()}")
    #    d) 分没怎么涨 → 无可疑,判扎实(哪怕使用也没动)。
    flat = Probe(Series("m", (0.50, 0.50, 0.51, 0.50), (0.30, 0.30, 0.30, 0.30)))
    check(flat.verdict() == GROUNDED, f"分没涨该判扎实,实得 {flat.verdict()}")
    #    e) 序列太短 → inconclusive,绝不冒充判决。
    inc = Probe(Series("m", (0.1, 0.9), (0.1, 0.1)))
    check(inc.verdict() == INCONCLUSIVE, f"序列太短该判 inconclusive,实得 {inc.verdict()}")

    # 4) 账本折叠 + 告警清单:临时账本里同名取最后一条,亮红/亮黄单列且按 gap 降序。
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d) / "mg.jsonl"
        record_probe("a", (0.3, 0.35, 0.85, 0.9), (0.2, 0.2, 0.21, 0.19), ledger=tmp)
        record_probe("b", (0.4, 0.45, 0.7, 0.75), (0.38, 0.44, 0.69, 0.78), ledger=tmp)
        # a 后再探一次仍刷分,同名应覆盖(且 gap 仍大)。
        record_probe("a", (0.2, 0.25, 0.9, 0.95), (0.2, 0.2, 0.2, 0.2), ledger=tmp)
        cur = current_verdicts(tmp)
        check(cur.get("a", {}).get("verdict") == GOODHART, "a 该判刷分")
        check(cur.get("b", {}).get("verdict") == GROUNDED, "b 该判扎实")
        check(cur.get("a", {}).get("series", {}).get("scores", [None])[0] == 0.2,
              "同名指标该取最后一条(0.2 起跳那次)")
        al = alerting(tmp)
        check([r["metric"] for r in al] == ["a"], f"告警清单该只含 a,实得 {al}")

    return fails


def _fmt_series(s: Series) -> str:
    return (f"分 {s.scores[0]:.2f}→{s.scores[-1]:.2f}(涨 {s.score_rise:+.2f}) · "
            f"用 {s.usages[0]:.2f}→{s.usages[-1]:.2f}(涨 {s.usage_rise:+.2f}) · "
            f"gap {s.gap:+.2f}")


def _demo() -> None:
    """演示三种结局各一例:扎实放行、背离盯紧、刷分亮红。"""
    cases = [
        ("evalbench.overall",
         (0.30, 0.34, 0.86, 0.91), (0.21, 0.20, 0.22, 0.20),
         "分从 30% 窜到 90%,真实被用死活停在 20%——漂亮数字在骗你,别拿它当进步"),
        ("value.coach.py",
         (0.40, 0.43, 0.58, 0.63), (0.40, 0.41, 0.47, 0.50),
         "分跑赢使用一截,还没到报警,但盯紧:再这么涨就是刷分"),
        ("trustscore.contracts.py",
         (0.40, 0.46, 0.70, 0.76), (0.38, 0.45, 0.69, 0.79),
         "分和真实被用手拉手一块涨——这分涨得有地气,真进步"),
    ]
    print("🛡️ 古德哈特探针:分的涨,得有真实使用给它兜底——只涨分不增用,当场亮红：\n")
    for metric, scores, usages, why in cases:
        p = Probe(Series(metric, scores, usages))
        v = p.verdict()
        print(f"  {_EMOJI[v]} {metric}  [{v}]")
        print(f"      {_fmt_series(p.series)}")
        print(f"      判语：{why}\n")
    print("分可以刷,但「真有人在用」刷不出来——守住这条,才不会被自己的仪表盘骗。")


def _print_status(as_json: bool, only_alerts: bool) -> None:
    """读真账本,列每个指标最近一次探测裁决(或只列亮红/亮黄)。"""
    cur = current_verdicts()
    if as_json:
        print(json.dumps(cur, ensure_ascii=False, indent=2))
        return
    if only_alerts:
        al = alerting()
        if not al:
            print("🛡️ 暂无背离真实使用的指标——要么都涨得有地气,要么还没探过。")
            return
        print(f"🔴 正在背离真实使用的指标(共 {len(al)},按 gap 降序):\n")
        for r in al:
            v = r.get("verdict")
            print(f"  {_EMOJI.get(v, '⬜')} {r['metric']:<28} gap {r.get('gap', 0):+.2f}  "
                  f"(分涨 {r.get('score_rise', 0):+.2f} · 用涨 {r.get('usage_rise', 0):+.2f})")
        print("\n下一步:别再拿这些分当进步的证据,先回去查是不是在刷分(过拟合验收集/挑软任务/改口径)。")
        return
    if not cur:
        print(f"🛡️ 探针账本还空着（{LEDGER.relative_to(REPO_ROOT)} 未记录任何探测）。")
        return
    order = {GOODHART: 0, DIVERGING: 1, INCONCLUSIVE: 2, GROUNDED: 3}
    print(f"🛡️ 各指标最近一次古德哈特探测(共 {len(cur)} 个,账本 {LEDGER.relative_to(REPO_ROOT)})：\n")
    for metric, r in sorted(cur.items(), key=lambda kv: (order.get(kv[1].get("verdict"), 9), kv[0])):
        v = r.get("verdict", INCONCLUSIVE)
        print(f"  {_EMOJI.get(v, '⬜')} {v:<12} gap {r.get('gap', 0):+.2f}  {metric}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 古德哈特探针 🛡️")
    ap.add_argument("--demo", action="store_true", help="演示三种结局(扎实/背离/刷分)各一例")
    ap.add_argument("--status", action="store_true", help="读账本,列每个指标最近一次探测裁决")
    ap.add_argument("--alerts", action="store_true", help="只列亮红/亮黄、正在背离真实使用的指标")
    ap.add_argument("--json", action="store_true", help="机读:导出当前各指标最近裁决")
    ap.add_argument("--quiet", action="store_true", help="只在自检不过时说话(适合钩子 / CI)")
    args = ap.parse_args(argv)

    if args.demo:
        _demo()
        return
    if args.status or args.alerts or args.json:
        _print_status(as_json=args.json, only_alerts=args.alerts)
        return

    fails = _selftest()
    if fails:
        print(f"⚠️  探针自检发现 {len(fails)} 处不达约：\n")
        for f in fails:
            print(f"  ❌ {f}")
        print("\n先把闸门与裁决改回守约,再拿它去抓刷分。")
        sys.exit(1)

    if not args.quiet:
        print(f"🛡️ 探针守约:序列须 ≥ {MIN_POINTS} 个读数,据 score/usage 趋势对照裁决"
              f"(扎实/背离/刷分),证据不足绝不冒充判决——只涨分不增用,当场亮红。")
    sys.exit(0)


if __name__ == "__main__":
    main()
