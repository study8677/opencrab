#!/usr/bin/env python3
"""进化吞吐报告 ⏱️📈 —— 把每一拍的耗时拆开看：到底慢在想、慢在做，还是耗在等。

为什么要有它：我每 30s 醒来一拍（tick），盘点领地→生成意图→动手→自测合并。日子久了
总觉得「慢」，可「慢」是个糊涂账——是脑子想得久？是动手写得久？是自测合并拖沓？还是
大半光阴都耗在心跳之间的空等里？**不先量出时间花在哪儿，谈提速就是凭感觉拍脑袋。**

吞吐报告不改任何东西，只把审计账本里现成的时间戳对齐成「拍」，再把每拍的墙上时间切成
四段，让瓶颈自己现形：

  · 🧠 **想**（think）—— tick_start → intent：盘点领地 + 让大脑生成今天的意图。
  · 🔨 **做**（act）—— intent → act：真正动手写码 / 改文件的那段。
  · 📦 **收**（wrap）—— act → tick_done：自测、合并、push、写日志的收尾。
  · 💤 **等**（wait）—— 上一拍 tick_done → 下一拍 tick_start：心跳之间的空闲沉睡。

收益侧对齐两个量：意图消耗的 **tokens**（脑力开销）与该拍 journal 里的 **行改动**
（insertions+deletions，真落地的产出）。于是「值不值」有了分母：每分钟产出多少行、
每千 token 换来几行、有效干活时间占整段日子的几成。

判准：吞吐报告是**观测者**——只读审计 JSONL 与 journal 的 diffstat，绝不写 state /
journal、不改任何文件。某拍缺事件（闸门未过 / 做梦拍 / 跑了一半被打断）就只算能算的
那几段，缺的记为「未知」并跳过，绝不拿默认值蒙混。

用法：
    python throughput.py                # 今天的吞吐报告：四段分布 + 瓶颈 + 收益
    python throughput.py --days 3       # 跨最近 3 天汇总
    python throughput.py --slow 5       # 额外列出最慢的 5 拍（按墙上耗时）
    python throughput.py --gate 180     # 中位每拍耗时超过 180s 则退出码非零（挂 CI）
    python throughput.py --quiet        # 只在触发 --gate 时说话
    python throughput.py --json         # 机读：每拍分段耗时、收益与汇总

退出码：0 = 正常 / 未触发闸门；1 = 触发 --gate（中位耗时超阈）。零第三方依赖，纯标准库。
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
JOURNAL_DIR = REPO_ROOT / "journal"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# diffstat 汇总行：「3 files changed, 364 insertions(+), 12 deletions(-)」
_INS_RE = re.compile(r"(\d+)\s+insertions?\(\+\)")
_DEL_RE = re.compile(r"(\d+)\s+deletions?\(-\)")

_ISO_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def _parse_ts(ts: str) -> datetime.datetime | None:
    """审计时间戳→datetime；毫秒可有可无，解析不了则回 None（绝不臆造时间）。"""
    if not ts:
        return None
    for fmt in (_ISO_FMT, "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


@dataclasses.dataclass
class Tick:
    """一拍的时间画像：四段耗时 + 收益。任一段缺事件则该段为 None。"""
    tick: int | None
    run_id: str
    t_start: datetime.datetime
    t_intent: datetime.datetime | None = None
    t_act: datetime.datetime | None = None
    t_done: datetime.datetime | None = None

    tokens: int | None = None        # 意图消耗的 token
    changed: bool | None = None       # act 是否真改了文件
    journal: str | None = None        # 该拍写下的 journal 名
    lines: int | None = None          # journal diffstat 的 ins+del

    wait_s: float | None = None       # 与「上一拍收尾」之间的空等（同 run 才算）

    # ── 四段墙上时间（秒）——缺端点则为 None ──
    @property
    def think_s(self) -> float | None:
        return _gap(self.t_start, self.t_intent)

    @property
    def act_s(self) -> float | None:
        return _gap(self.t_intent, self.t_act)

    @property
    def wrap_s(self) -> float | None:
        return _gap(self.t_act, self.t_done)

    @property
    def elapsed_s(self) -> float | None:
        return _gap(self.t_start, self.t_done)

    @property
    def complete(self) -> bool:
        """四段端点齐全（想/做/收都能算）的「完整拍」。"""
        return None not in (self.t_intent, self.t_act, self.t_done)

    def to_meta(self) -> dict:
        return {
            "tick": self.tick, "run_id": self.run_id,
            "start": self.t_start.isoformat(),
            "think_s": _round(self.think_s), "act_s": _round(self.act_s),
            "wrap_s": _round(self.wrap_s), "elapsed_s": _round(self.elapsed_s),
            "wait_s": _round(self.wait_s),
            "tokens": self.tokens, "lines": self.lines,
            "changed": self.changed, "journal": self.journal,
            "complete": self.complete,
        }


def _gap(a: datetime.datetime | None, b: datetime.datetime | None) -> float | None:
    if a is None or b is None:
        return None
    d = (b - a).total_seconds()
    return d if d >= 0 else None


def _round(v: float | None) -> float | None:
    return round(v, 1) if v is not None else None


# ── 收益：从 journal diffstat 取行改动 ───────────────────────────────────
def _journal_lines(name: str | None) -> int | None:
    """读某篇 journal 的 diffstat，返回 insertions+deletions；读不到则 None。"""
    if not name:
        return None
    path = JOURNAL_DIR / name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    ins = sum(int(m) for m in _INS_RE.findall(text))
    dele = sum(int(m) for m in _DEL_RE.findall(text))
    total = ins + dele
    return total if total else None


# ── 重建：把审计记录对齐成「拍」 ─────────────────────────────────────────
def build(days: int = 1) -> list[Tick]:
    """扫最近 days 天审计，按 run 把事件流切成 Tick（含四段耗时与收益）。

    审计读不到则回空列表——无从诊断，绝不臆造。同一 run 内相邻拍才算 wait（空等）；
    跨 run / 跨重启不计 wait（那是停机，不是心跳间隙）。
    """
    try:
        import audit
    except Exception:
        return []

    today = datetime.date.today()
    recs: list[dict] = []
    for back in range(days):
        day = (today - datetime.timedelta(days=back)).isoformat()
        try:
            recs.extend(audit.read_records(day))
        except Exception:
            continue
    # 审计本就按 (run, seq) 时间正序写入；按 ts 稳定排序以防跨天拼接错位。
    recs.sort(key=lambda r: (r.get("run_id", ""), r.get("seq", 0)))

    ticks: list[Tick] = []
    cur: Tick | None = None
    for r in recs:
        ev = r.get("event")
        ts = _parse_ts(r.get("ts", ""))
        if ts is None:
            continue
        if ev == "tick_start":
            if cur is not None:           # 上一拍没等到 tick_done 就被打断——照样收下
                ticks.append(cur)
            cur = Tick(tick=r.get("tick"), run_id=r.get("run_id", ""), t_start=ts)
        elif cur is None:
            continue                       # 落在任何 tick_start 之前的孤儿事件，跳过
        elif ev == "intent":
            cur.t_intent = ts
            tok = r.get("tokens")
            cur.tokens = tok if isinstance(tok, int) else cur.tokens
        elif ev == "act":
            cur.t_act = ts
            cur.changed = r.get("changed")
            cur.journal = r.get("journal")
        elif ev == "tick_done":
            cur.t_done = ts
            ticks.append(cur)
            cur = None
    if cur is not None:
        ticks.append(cur)

    # 回填收益（行改动）与同 run 相邻拍的空等。
    last_done: dict[str, datetime.datetime] = {}
    for t in ticks:
        t.lines = _journal_lines(t.journal)
        prev = last_done.get(t.run_id)
        if prev is not None:
            t.wait_s = _gap(prev, t.t_start)
        if t.t_done is not None:
            last_done[t.run_id] = t.t_done
    return ticks


# ── 统计小工具 ───────────────────────────────────────────────────────
def _stats(vals: list[float]) -> dict | None:
    """非空数列的 总和/中位/p90/最大；空则 None。"""
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    return {
        "n": n, "sum": round(sum(s), 1),
        "median": round(s[n // 2], 1),
        "p90": round(s[min(n - 1, int(n * 0.9))], 1),
        "max": round(s[-1], 1),
    }


def _collect(ticks: list[Tick], attr: str) -> list[float]:
    out = []
    for t in ticks:
        v = getattr(t, attr)
        if v is not None:
            out.append(v)
    return out


# ── 汇总：四段分布 + 瓶颈 + 收益 ─────────────────────────────────────────
def summarize(ticks: list[Tick]) -> dict:
    """把一批拍汇成吞吐报告：各段耗时统计、瓶颈段、收益与效率。"""
    complete = [t for t in ticks if t.complete]
    seg = {name: _stats(_collect(ticks, f"{name}_s"))
           for name in ("think", "act", "wrap", "elapsed", "wait")}

    # 瓶颈：在「完整拍」上比较想/做/收三段的总耗时占比（只有完整拍才公平可比）。
    seg_sum = {k: 0.0 for k in ("think", "act", "wrap")}
    for t in complete:
        seg_sum["think"] += t.think_s or 0.0
        seg_sum["act"] += t.act_s or 0.0
        seg_sum["wrap"] += t.wrap_s or 0.0
    active = sum(seg_sum.values())
    share = {k: (v / active if active else 0.0) for k, v in seg_sum.items()}
    bottleneck = max(share, key=share.get) if active else None

    # 收益与效率
    total_lines = sum(t.lines for t in ticks if t.lines)
    total_tokens = sum(t.tokens for t in ticks if t.tokens)
    active_min = active / 60.0
    wait_sum = sum(t.wait_s for t in ticks if t.wait_s) or 0.0

    return {
        "ticks": len(ticks), "complete": len(complete),
        "segments": seg, "seg_sum": {k: round(v, 1) for k, v in seg_sum.items()},
        "share": {k: round(v, 3) for k, v in share.items()},
        "bottleneck": bottleneck,
        "total_lines": total_lines, "total_tokens": total_tokens,
        "lines_per_active_min": round(total_lines / active_min, 1) if active_min else None,
        "lines_per_ktok": round(total_lines / (total_tokens / 1000), 1) if total_tokens else None,
        "active_s": round(active, 1), "wait_s": round(wait_sum, 1),
        "active_ratio": round(active / (active + wait_sum), 3) if (active + wait_sum) else None,
    }


def manifest(days: int = 1) -> dict:
    """机读：汇总 + 每拍画像。"""
    ticks = build(days=days)
    m = summarize(ticks)
    m["days"] = days
    m["per_tick"] = [t.to_meta() for t in ticks]
    return m


# ── 渲染 ─────────────────────────────────────────────────────────────
_SEG_LABEL = {"think": "🧠 想", "act": "🔨 做", "wrap": "📦 收",
              "elapsed": "⏱️ 整拍", "wait": "💤 等"}


def _fmt_s(v: float | None) -> str:
    return f"{v:.0f}s" if v is not None else "—"


def _render(ticks: list[Tick], days: int, slow: int) -> str:
    m = summarize(ticks)
    L = [f"⏱️📈 opencrab 进化吞吐报告 —— 近 {days} 天 · "
         f"{m['ticks']} 拍（{m['complete']} 完整）", ""]

    if not ticks:
        L.append("（审计里读不到任何一拍——无从诊断。先让生命跑几拍再来。）")
        return "\n".join(L)

    # 四段分布表
    L.append("每拍耗时分段（秒，按完整拍可比）：")
    L.append("  段位      拍数   总和    中位    p90     最大")
    for name in ("think", "act", "wrap", "elapsed", "wait"):
        s = m["segments"][name]
        if not s:
            L.append(f"  {_SEG_LABEL[name]:<8}  （无数据）")
            continue
        L.append(f"  {_SEG_LABEL[name]:<8}  {s['n']:>4}  {s['sum']:>7.0f} "
                 f"{s['median']:>7.0f} {s['p90']:>7.0f} {s['max']:>7.0f}")
    L.append("")

    # 瓶颈
    if m["bottleneck"]:
        sh = m["share"]
        parts = "  ".join(f"{_SEG_LABEL[k]} {sh[k]*100:.0f}%"
                          for k in ("think", "act", "wrap"))
        L.append(f"🔍 想/做/收占比：{parts}")
        bn = m["bottleneck"]
        L.append(f"   瓶颈在「{_SEG_LABEL[bn]}」——它吃掉了 {sh[bn]*100:.0f}% 的有效干活时间。")
    L.append("")

    # 收益与效率
    L.append(f"📈 产出：{m['total_lines']} 行改动 · {m['total_tokens']} tokens")
    if m["lines_per_active_min"] is not None:
        L.append(f"   每有效分钟 {m['lines_per_active_min']} 行"
                 + (f" · 每千 token {m['lines_per_ktok']} 行" if m["lines_per_ktok"] else ""))
    if m["active_ratio"] is not None:
        L.append(f"   有效干活 {_fmt_s(m['active_s'])} vs 心跳空等 {_fmt_s(m['wait_s'])}"
                 f" → 有效占比 {m['active_ratio']*100:.0f}%")
    L.append("")

    # 最慢的几拍
    if slow > 0:
        ranked = sorted([t for t in ticks if t.elapsed_s is not None],
                        key=lambda t: t.elapsed_s, reverse=True)[:slow]
        if ranked:
            L.append(f"🐢 最慢的 {len(ranked)} 拍：")
            for t in ranked:
                seg = f"想{_fmt_s(t.think_s)}/做{_fmt_s(t.act_s)}/收{_fmt_s(t.wrap_s)}"
                yld = f"{t.lines}行" if t.lines else "无落地"
                L.append(f"   #{t.tick} 整拍 {_fmt_s(t.elapsed_s)}（{seg}）· {yld}"
                         + (f" · {t.journal}" if t.journal else ""))
            L.append("")

    if m["bottleneck"]:
        bn = m["bottleneck"]
        tip = {"think": "脑子想得久——意图阶段慢，看是上下文太重还是大脑延迟高。",
               "act": "动手写得久——这是真在产出，未必是坏事，但可拆小步。",
               "wrap": "收尾拖沓——自测/合并/push 慢，先量这几步谁最久。"}[bn]
        L.append(f"🦀 先诊断后提速：{tip}")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 进化吞吐报告 ⏱️📈 —— 把每拍耗时拆成想/做/收/等，先量瓶颈再谈提速")
    ap.add_argument("--days", type=int, default=1, metavar="N",
                    help="审计回溯窗口天数（默认 1，即今天）")
    ap.add_argument("--slow", type=int, default=0, metavar="K",
                    help="额外列出最慢的 K 拍（按整拍墙上耗时）")
    ap.add_argument("--gate", type=float, default=None, metavar="SEC",
                    help="中位每拍耗时超过 SEC 秒则退出码非零（挂钩子 / CI）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在触发 --gate 时说话（适合钩子 / CI）")
    ap.add_argument("--json", action="store_true", help="机读：每拍分段耗时、收益与汇总")
    args = ap.parse_args(argv)

    if args.days < 1:
        print(f"❌ --days 需为正整数，收到 {args.days}")
        sys.exit(2)

    if args.json:
        print(json.dumps(manifest(days=args.days), ensure_ascii=False, indent=2))
        sys.exit(0)

    ticks = build(days=args.days)
    m = summarize(ticks)

    # 闸门判定：中位整拍耗时
    gate_tripped = False
    if args.gate is not None:
        med = (m["segments"]["elapsed"] or {}).get("median")
        gate_tripped = med is not None and med > args.gate

    if args.quiet:
        if gate_tripped:
            med = m["segments"]["elapsed"]["median"]
            print(f"⏱️ 吞吐：中位整拍 {med:.0f}s 超过闸门 {args.gate:.0f}s"
                  + (f"，瓶颈在「{_SEG_LABEL[m['bottleneck']]}」" if m["bottleneck"] else ""))
    else:
        print(_render(ticks, args.days, args.slow))

    sys.exit(1 if gate_tripped else 0)


if __name__ == "__main__":
    main()
