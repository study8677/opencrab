#!/usr/bin/env python3
"""自改细粒度耗时埋点 + 实时瀑布仪表盘 ⏱️🌊 —— 把一拍的墙上时间摊成一条
「等待 → 思考 → 执行 → 验证」的轨迹，每段画成一根可比的甘特条，让瓶颈在你眼前现形。

为什么要有它：`throughput.py` 已把每拍切成四段、`bottleneck.py` 已开出提速处方，可它们
都是**事后汇总**——拿几十拍的中位/占比说话。要真把「这一拍慢在哪」看清楚，得有一张
**单拍的瀑布图**：哪段先发生、各占多长、有没有某个子步骤偷偷吃掉了大半光阴。汇总报告
回答「最近普遍慢在收尾」，瀑布图回答「**就是刚才这一拍**，验证段里 push 卡了 40s」。

这一层做两件互补的事，都恪守生命的本分：

  1. **埋点原语**（`span()` 上下文管理器）—— 给任意子步骤套一层计时，退出时把
     `span` 事件写进审计。**写盘由调用方发起**：spantrace 只提供尺子，crab.py 用
     `with spantrace.span("push", "verify"):` 把执行/验证里的子步骤量出来，spantrace
     自己绝不主动往审计里塞东西。审计不可用时原语退化成零开销空操作，绝不弄死生命。

  2. **瀑布仪表盘**（观测者）—— 只读审计 JSONL 与 journal diffstat，把每拍重建成
     四段轨迹（复用 `throughput` 的拍重建），再把同拍的细粒度子 span 叠在对应段下，
     渲染成 ASCII 甘特瀑布。支持 `--watch` 定时刷新，看在飞的那一拍实时长出来。

四段（沿用审计现成的四个事件，缺端点的段记「未知」并跳过，绝不拿默认值蒙混）：
  · 💤 **等待** wait   —— 上一拍 tick_done → 本拍 tick_start（同 run 才算的心跳空等）。
  · 🧠 **思考** think  —— tick_start → intent（盘点领地 + 大脑生成意图）。
  · 🔨 **执行** exec   —— intent → act（真正动手改文件那段）。
  · ✅ **验证** verify —— act → tick_done（自测 / 合并 / push / 写日志的收尾）。

判准：仪表盘是**观测者**——绝不写 state / journal、不改任何文件；某拍缺段就只画能画的，
读不到审计或一拍都没有就明说，绝不臆造时间。零第三方依赖，纯标准库。

用法：
    python spantrace.py                 # 最近一拍的瀑布轨迹（含在飞的半截拍）
    python spantrace.py --tick 128      # 指定某一拍的瀑布
    python spantrace.py --last 5        # 最近 5 拍各画一张瀑布
    python spantrace.py --days 3        # 审计回溯窗口（默认 1=今天）
    python spantrace.py --watch 5       # 每 5s 刷新最近一拍（实时仪表盘；Ctrl-C 退出）
    python spantrace.py --gate 0.6      # 最近窗口里「最贵段」占有效时间超 0.6 则退出码非零
    python spantrace.py --quiet         # 只在触发 --gate 时说话（钩子 / CI）
    python spantrace.py --json          # 机读：每拍四段耗时 + 子 span + 汇总

退出码：0 = 正常 / 未触发闸门；1 = 触发 --gate。
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import throughput  # noqa: E402  —— 复用「拍」的重建与四段切分

# 四段：审计字段名 → (emoji 标签, 取自 Tick 的属性)。顺序即时间顺序，瀑布按此从上到下排。
PHASES: list[tuple[str, str, str]] = [
    ("wait", "💤 等待", "wait_s"),
    ("think", "🧠 思考", "think_s"),
    ("exec", "🔨 执行", "act_s"),
    ("verify", "✅ 验证", "wrap_s"),
]
_PHASE_LABEL = {k: lbl for k, lbl, _ in PHASES}
_PHASE_ATTR = {k: attr for k, _, attr in PHASES}
# 子 span 归属哪一段——埋点时 phase 只认这四个，别的归到「其它」桶里照画但不计闸门。
_VALID_PHASES = set(_PHASE_LABEL)

# 有效干活段（不含等待）——「最贵段」与闸门只在这三段里比，空等不是干活。
_ACTIVE_PHASES = ("think", "exec", "verify")

_BAR_COLS = 40  # 甘特条最长宽度（字符）


# ══ 一、埋点原语：给子步骤套计时，退出时写 span 事件（写盘由调用方发起）═══════════
@contextlib.contextmanager
def span(name: str, phase: str = "exec", *, tick: int | None = None):
    """把一段子步骤的墙上耗时量出来，退出时写一条 `span` 审计事件。

    用法：`with spantrace.span("push", "verify"): git_push()`。
    `phase` 标明这段归属哪一阶段（wait/think/exec/verify），好让瀑布把它叠到对应段下；
    传了别的值也照写，仪表盘会归到「其它」桶。审计不可用时退化成零开销空操作——
    埋点绝不因写盘失败而弄死生命，也绝不吞掉被包裹代码自己抛出的异常。
    """
    t0 = time.perf_counter()
    started = datetime.datetime.now()
    try:
        yield
    finally:
        dur = round(time.perf_counter() - t0, 3)
        try:
            import audit
            audit.record("span", name=str(name)[:80], phase=str(phase),
                         tick=tick, dur_s=dur, start=started.isoformat(timespec="milliseconds"))
        except Exception:
            pass  # 审计不可用 / 写盘出错：埋点静默退化，绝不反噬生命


# ══ 二、重建：把一拍摊成四段轨迹，并叠上同拍的细粒度子 span ═══════════════════
class TickTrace:
    """一拍的瀑布轨迹：四段（标签/耗时/是否在飞）+ 落在各段下的子 span。"""

    def __init__(self, tk: throughput.Tick, subspans: list[dict]):
        self.tick = tk.tick
        self.run_id = tk.run_id
        self.journal = tk.journal
        self.lines = tk.lines
        self.in_flight = tk.t_done is None  # 没等到 tick_done = 还在飞的半截拍
        # 四段耗时（缺端点为 None=未知，绝不补 0）
        self.durs: dict[str, float | None] = {k: getattr(tk, attr) for k, attr in _PHASE_ATTR.items()}
        # 子 span 按段归桶；非法 phase 归「其它」
        self.subs: dict[str, list[dict]] = {k: [] for k in _VALID_PHASES}
        self.subs["其它"] = []
        for s in subspans:
            ph = s.get("phase")
            self.subs.setdefault(ph if ph in _VALID_PHASES else "其它", []).append(s)

    @property
    def active_s(self) -> float:
        """有效干活时间（想+做+验，缺段算 0 仅用于占比分母）。"""
        return sum(self.durs[k] or 0.0 for k in _ACTIVE_PHASES)

    def shares(self) -> dict[str, float]:
        """三段有效干活段各自占比；无有效时间则全 0。"""
        a = self.active_s
        return {k: ((self.durs[k] or 0.0) / a if a else 0.0) for k in _ACTIVE_PHASES}

    def bottleneck(self) -> str | None:
        """最贵段：有效干活段里占比最高的那个；无有效时间则 None。"""
        if self.active_s <= 0:
            return None
        sh = self.shares()
        return max(sh, key=sh.get)

    def to_dict(self) -> dict:
        return {
            "tick": self.tick, "run_id": self.run_id, "journal": self.journal,
            "lines": self.lines, "in_flight": self.in_flight,
            "durations": {k: throughput._round(v) for k, v in self.durs.items()},
            "active_s": round(self.active_s, 1),
            "shares": {k: round(v, 3) for k, v in self.shares().items()},
            "bottleneck": self.bottleneck(),
            "subspans": {k: v for k, v in self.subs.items() if v},
        }


def _span_records(days: int) -> list[dict]:
    """读最近 days 天审计里的 `span` 事件；读不到则空（无子 span 照样画四段）。"""
    try:
        import audit
    except Exception:
        return []
    today = datetime.date.today()
    out: list[dict] = []
    for back in range(max(1, days)):
        day = (today - datetime.timedelta(days=back)).isoformat()
        try:
            out.extend(r for r in audit.read_records(day) if r.get("event") == "span")
        except Exception:
            continue
    return out


def build_traces(days: int = 1) -> list[TickTrace]:
    """重建最近 days 天每一拍的瀑布轨迹（含在飞的半截拍），按时间正序。"""
    ticks = throughput.build(days=days)
    spans = _span_records(days)
    # 子 span 按 (run_id, tick) 归到对应拍
    by_tick: dict[tuple[str, object], list[dict]] = {}
    for s in spans:
        by_tick.setdefault((s.get("run_id", ""), s.get("tick")), []).append(s)
    return [TickTrace(tk, by_tick.get((tk.run_id, tk.tick), [])) for tk in ticks]


# ══ 三、渲染：单拍 ASCII 甘特瀑布 ═══════════════════════════════════════════
def _fmt_s(v: float | None) -> str:
    return f"{v:.1f}s" if v is not None else "—"


def _bar(dur: float | None, scale: float) -> str:
    """把耗时画成甘特条；未知段画虚线，零长段留空。"""
    if dur is None:
        return "┄┄ 未知"
    if scale <= 0 or dur <= 0:
        return ""
    n = max(1, round(dur / scale * _BAR_COLS))
    return "█" * n


def render_trace(tr: TickTrace) -> str:
    knowns = [tr.durs[k] for k in _PHASE_LABEL if tr.durs[k] is not None]
    scale = max(knowns) if knowns else 0.0

    head = f"⏱️🌊 拍 #{tr.tick}"
    if tr.in_flight:
        head += " · ⏳在飞"
    if tr.journal:
        head += f" · {tr.journal}"
    if tr.lines:
        head += f" · {tr.lines} 行落地"
    L = [head, ""]

    for key, label, _ in PHASES:
        dur = tr.durs[key]
        bar = _bar(dur, scale)
        L.append(f"  {label}  {_fmt_s(dur):>7}  {bar}")
        # 把这段下的子 span 缩进列出（按耗时降序，量得出的在前）
        subs = sorted(tr.subs.get(key, []),
                      key=lambda s: s.get("dur_s") or -1, reverse=True)
        for s in subs:
            sd = s.get("dur_s")
            sbar = _bar(sd if isinstance(sd, (int, float)) else None, scale)
            L.append(f"        └ {str(s.get('name', '?'))[:24]:<24} "
                     f"{_fmt_s(sd if isinstance(sd, (int, float)) else None):>7}  {sbar}")

    other = tr.subs.get("其它", [])
    if other:
        L.append(f"  📎 其它（未归段的 {len(other)} 个 span）：")
        for s in sorted(other, key=lambda s: s.get("dur_s") or -1, reverse=True):
            sd = s.get("dur_s")
            L.append(f"        └ {str(s.get('name', '?'))[:24]:<24} "
                     f"{_fmt_s(sd if isinstance(sd, (int, float)) else None):>7}")

    bn = tr.bottleneck()
    if bn is not None:
        sh = tr.shares()
        parts = "  ".join(f"{_PHASE_LABEL[k]} {sh[k]*100:.0f}%" for k in _ACTIVE_PHASES)
        L.append("")
        L.append(f"  🔍 有效干活占比：{parts}")
        L.append(f"     最贵段在「{_PHASE_LABEL[bn]}」——它吃掉了 {sh[bn]*100:.0f}% 的干活时间。")
    elif not tr.in_flight:
        L.append("")
        L.append("  （这一拍量不到有效干活时间——多半是做梦拍或半截被打断。）")
    return "\n".join(L)


def _render(traces: list[TickTrace], last: int) -> str:
    if not traces:
        return ("⏱️🌊 opencrab 自改瀑布仪表盘\n\n"
                "（审计里读不到任何一拍——无从作图。先让生命跑几拍再来。）")
    shown = traces[-last:] if last > 0 else traces[-1:]
    blocks = [render_trace(tr) for tr in shown]
    header = (f"⏱️🌊 opencrab 自改瀑布仪表盘 —— 共 {len(traces)} 拍，"
              f"展开最近 {len(shown)} 拍\n")
    return header + "\n\n".join(blocks)


def _find_tick(traces: list[TickTrace], tick: int) -> TickTrace | None:
    # 同一拍号可能跨 run 重复出现，取最后一个（最近那次）。
    hit = [tr for tr in traces if tr.tick == tick]
    return hit[-1] if hit else None


# ══ 四、闸门：最近窗口里「最贵段」吃掉的有效时间占比 ═══════════════════════════
def _window_bottleneck(traces: list[TickTrace]) -> tuple[str | None, float]:
    """把最近窗口的三段有效时间各自累加，找占比最高的那段及其占比。"""
    agg = {k: 0.0 for k in _ACTIVE_PHASES}
    for tr in traces:
        for k in _ACTIVE_PHASES:
            agg[k] += tr.durs[k] or 0.0
    total = sum(agg.values())
    if total <= 0:
        return None, 0.0
    bn = max(agg, key=agg.get)
    return bn, agg[bn] / total


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 自改瀑布仪表盘 ⏱️🌊 —— 单拍 等待/思考/执行/验证 甘特轨迹")
    ap.add_argument("--days", type=int, default=1, metavar="N",
                    help="审计回溯窗口天数（默认 1=今天）")
    ap.add_argument("--tick", type=int, default=None, metavar="N",
                    help="只画指定拍号的瀑布")
    ap.add_argument("--last", type=int, default=1, metavar="K",
                    help="展开最近 K 拍各一张瀑布（默认 1）")
    ap.add_argument("--watch", type=float, default=None, metavar="SEC",
                    help="每 SEC 秒刷新一次最近一拍（实时仪表盘；Ctrl-C 退出）")
    ap.add_argument("--gate", type=float, default=None, metavar="RATIO",
                    help="最近窗口里最贵段占有效时间超 RATIO 则退出码非零（钩子 / CI）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在触发 --gate 时说话（适合钩子 / CI）")
    ap.add_argument("--json", action="store_true",
                    help="机读：每拍四段耗时 + 子 span + 汇总")
    args = ap.parse_args(argv)

    if args.days < 1:
        print(f"❌ --days 需为正整数，收到 {args.days}")
        sys.exit(2)

    # 实时仪表盘：循环刷新最近一拍，直到 Ctrl-C。
    if args.watch is not None:
        if args.watch <= 0:
            print(f"❌ --watch 需为正秒数，收到 {args.watch}")
            sys.exit(2)
        try:
            while True:
                traces = build_traces(days=args.days)
                sys.stdout.write("\033[2J\033[H")  # 清屏 + 光标归位
                stamp = datetime.datetime.now().strftime("%H:%M:%S")
                print(f"🔄 {stamp} · 每 {args.watch:g}s 刷新 · Ctrl-C 退出\n")
                print(_render(traces, last=max(1, args.last)))
                sys.stdout.flush()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n👋 仪表盘已退出。")
            sys.exit(0)

    traces = build_traces(days=args.days)

    if args.json:
        if args.tick is not None:
            tr = _find_tick(traces, args.tick)
            payload = {"tick": args.tick, "found": tr is not None,
                       "trace": tr.to_dict() if tr else None}
        else:
            bn, share = _window_bottleneck(traces)
            payload = {"days": args.days, "ticks": len(traces),
                       "window_bottleneck": bn, "window_share": round(share, 3),
                       "traces": [tr.to_dict() for tr in traces]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(0)

    # 闸门判定：最近窗口最贵段占比
    gate_tripped = False
    if args.gate is not None:
        _, share = _window_bottleneck(traces)
        gate_tripped = share > args.gate

    if args.quiet:
        if gate_tripped:
            bn, share = _window_bottleneck(traces)
            print(f"⏱️🌊 瀑布：最贵段「{_PHASE_LABEL.get(bn, bn)}」"
                  f"占 {share*100:.0f}% 有效时间，超过闸门 {args.gate*100:.0f}%")
        sys.exit(1 if gate_tripped else 0)

    if args.tick is not None:
        tr = _find_tick(traces, args.tick)
        if tr is None:
            print(f"（近 {args.days} 天审计里找不到拍 #{args.tick}。）")
            sys.exit(0)
        print(render_trace(tr))
    else:
        print(_render(traces, last=max(1, args.last)))

    sys.exit(1 if gate_tripped else 0)


if __name__ == "__main__":
    main()
