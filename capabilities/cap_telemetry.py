"""能力 · 运行遥测摘要 📊 —— 把审计日志汇总成「每日小报告」。

`audit.py` 把每次启动、心跳、失败、退出都固化成一行行 JSON(JSONL)，但原始
事件多而散：要看清「自己到底哪里慢、哪里脆、哪里最值得先改」，得有人把它们
归纳起来。这正是这条能力做的事——读一天(或最近几天)的审计，算出三件事：

  1. 启动/存活耗时 —— 每次进程从 startup 到收场活了多久、启动到首跳的延迟、
     单次心跳(tick_start→tick_done)耗时的 min/中位/p90/max，看「哪里慢」。
  2. 失败分布     —— failure 事件按 `where` 归类计数 + 采样一条 error，看「哪里脆」。
  3. 常见退出原因 —— exit 事件按 `reason` 计数；没留下 exit 的进程算「未收场」
     (被杀/崩溃/仍在跑)，看「怎么收的场」。

默认把报告写到 state/telemetry/<日期>.md(落在被 .gitignore 的 state/ 里，
自动生成、可重跑覆盖)；传 ctx={"write": False} 则只渲染不落盘。
ctx 选项：{"day": "YYYY-MM-DD"(默认今天), "days": N(往回多看几天合并), "write": bool}。
零第三方依赖，纯标准库。
"""
from __future__ import annotations

import datetime
import pathlib
import sys

from . import Result, capability

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT_DIR = _REPO_ROOT / "state" / "telemetry"      # 落在被 .gitignore 的 state/ 里


def _audit():
    """惰性导入仓库根的 audit 模块(和 cap_diag 一样的接法)。"""
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import audit
    return audit


def _days_back(day: str, n: int) -> list[str]:
    """从 day 往回数 n 天(含 day)的日期串，正序。"""
    d0 = datetime.date.fromisoformat(day)
    return [(d0 - datetime.timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _ts(rec: dict) -> datetime.datetime | None:
    """把一条记录的 ts 解析成 datetime；坏值返回 None,绝不抛错。"""
    try:
        return datetime.datetime.fromisoformat(rec["ts"])
    except (KeyError, ValueError, TypeError):
        return None


def _secs(a: datetime.datetime | None, b: datetime.datetime | None) -> float | None:
    """b - a 的秒数(非负)；任一为空或时序倒置返回 None。"""
    if a is None or b is None:
        return None
    s = (b - a).total_seconds()
    return s if s >= 0 else None


def _stats(xs: list[float]) -> dict | None:
    """一组耗时的 min/中位/p90/max/均值(秒)；空集返回 None。"""
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    def pct(p: float) -> float:                 # 最近秩百分位,够用且无依赖
        return s[min(n - 1, max(0, round(p * (n - 1))))]
    return {"n": n, "min": s[0], "p50": pct(0.5), "p90": pct(0.9),
            "max": s[-1], "avg": sum(s) / n}


def _fmt(sec: float) -> str:
    """把秒数格式化成人话：<1s 给毫秒,>=60s 给分秒。"""
    if sec < 1:
        return f"{sec * 1000:.0f}ms"
    if sec < 60:
        return f"{sec:.1f}s"
    m, s = divmod(int(round(sec)), 60)
    return f"{m}m{s:02d}s"


def analyze(records: list[dict]) -> dict:
    """把一批审计记录归纳成遥测摘要(纯数据,不落盘)。"""
    # 按 run_id 分组,组内按 seq 排序,还原每次「活着」的时间线
    runs: dict[str, list[dict]] = {}
    for r in records:
        runs.setdefault(r.get("run_id", "?"), []).append(r)
    for rid in runs:
        runs[rid].sort(key=lambda r: r.get("seq", 0))

    lifespans: list[float] = []        # 进程从首条到末条活了多久
    startup_lat: list[float] = []      # startup → 首个 tick_start 的延迟
    tick_durs: list[float] = []        # 单次 tick_start → tick_done 的耗时
    incomplete = 0                     # 没留下 exit 的进程数(未收场)

    for rid, recs in runs.items():
        ts_all = [t for t in (_ts(r) for r in recs) if t]
        if len(ts_all) >= 2:
            d = _secs(ts_all[0], ts_all[-1])
            if d is not None:
                lifespans.append(d)
        # 启动延迟:startup 到第一个 tick_start
        su = next((r for r in recs if r.get("event") == "startup"), None)
        t0 = next((r for r in recs if r.get("event") == "tick_start"), None)
        if su and t0:
            lat = _secs(_ts(su), _ts(t0))
            if lat is not None:
                startup_lat.append(lat)
        # 单跳耗时:按 tick 号配对 tick_start / tick_done
        starts = {r.get("tick"): _ts(r) for r in recs if r.get("event") == "tick_start"}
        for r in recs:
            if r.get("event") == "tick_done":
                d = _secs(starts.get(r.get("tick")), _ts(r))
                if d is not None:
                    tick_durs.append(d)
        if not any(r.get("event") == "exit" for r in recs):
            incomplete += 1

    # 失败分布:按 where 计数 + 采样一条 error
    failures: dict[str, dict] = {}
    for r in records:
        if r.get("event") != "failure":
            continue
        where = str(r.get("where", "?"))
        slot = failures.setdefault(where, {"count": 0, "sample": ""})
        slot["count"] += 1
        if not slot["sample"] and r.get("error"):
            slot["sample"] = str(r["error"])[:160]

    # 退出原因:按 reason 计数
    exits: dict[str, int] = {}
    for r in records:
        if r.get("event") == "exit":
            reason = str(r.get("reason", "?"))
            exits[reason] = exits.get(reason, 0) + 1

    return {
        "total": len(records),
        "runs": len(runs),
        "incomplete_runs": incomplete,
        "lifespan": _stats(lifespans),
        "startup_latency": _stats(startup_lat),
        "tick_duration": _stats(tick_durs),
        "failures": failures,
        "failure_total": sum(f["count"] for f in failures.values()),
        "exits": exits,
    }


def _render(label: str, a: dict) -> str:
    """把摘要渲染成一份每日小报告(markdown)。"""
    L: list[str] = []
    L.append(f"# 🦀📊 opencrab 运行遥测 · {label}")
    L.append("")
    L.append("> 自动生成,请勿手改——重跑 `python crab.py cap telemetry` 即可刷新。")
    L.append("> 由审计日志(state/audit/*.jsonl)汇总:看自己哪里慢、哪里脆、哪里该先改。")
    L.append("")

    if not a["total"]:
        L.append("（这段时间没有审计记录,无可汇总。）")
        L.append("")
        return "\n".join(L)

    L.append(f"**概览**：{a['total']} 条记录 · {a['runs']} 次进程 · "
             f"{a['failure_total']} 次失败 · {a['incomplete_runs']} 次未正常收场")
    L.append("")

    # 1) 启动/存活耗时
    L.append("## ⏱️ 启动与耗时")
    L.append("")
    L.append("| 指标 | 次数 | min | 中位 | p90 | max | 均值 |")
    L.append("|---|--:|--:|--:|--:|--:|--:|")
    for key, name in (("startup_latency", "启动→首跳延迟"),
                      ("tick_duration", "单次心跳耗时"),
                      ("lifespan", "进程存活时长")):
        s = a[key]
        if s:
            L.append(f"| {name} | {s['n']} | {_fmt(s['min'])} | {_fmt(s['p50'])} | "
                     f"{_fmt(s['p90'])} | {_fmt(s['max'])} | {_fmt(s['avg'])} |")
        else:
            L.append(f"| {name} | 0 | — | — | — | — | — |")
    L.append("")

    # 2) 失败分布
    L.append("## 🩹 失败分布")
    L.append("")
    if a["failures"]:
        L.append("| 出错处(where) | 次数 | 采样 error |")
        L.append("|---|--:|---|")
        for where, f in sorted(a["failures"].items(), key=lambda kv: -kv[1]["count"]):
            sample = (f["sample"] or "—").replace("|", "\\|").replace("\n", " ")
            L.append(f"| `{where}` | {f['count']} | {sample} |")
    else:
        L.append("✅ 这段时间没有 failure 事件。")
    L.append("")

    # 3) 退出原因
    L.append("## 🚪 退出原因")
    L.append("")
    if a["exits"]:
        for reason, n in sorted(a["exits"].items(), key=lambda kv: -kv[1]):
            L.append(f"- `{reason}` × {n}")
    else:
        L.append("- （没有 exit 事件——可能进程都未正常收场）")
    if a["incomplete_runs"]:
        L.append(f"- ⚠️ 另有 {a['incomplete_runs']} 次进程未留下 exit(被杀/崩溃/仍在跑)")
    L.append("")
    return "\n".join(L).rstrip() + "\n"


@capability("telemetry", "运行遥测摘要:从审计日志汇总启动耗时/失败分布/退出原因,生成每日小报告",
            category="感知", tags=("telemetry", "audit", "report", "metrics"))
def run(ctx: dict) -> Result:
    ctx = ctx or {}
    audit = _audit()
    day = ctx.get("day") or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        return Result(ok=False, summary=f"day 需要 YYYY-MM-DD 格式,收到 {day!r}")
    days = int(ctx.get("days", 1) or 1)
    if days < 1:
        days = 1

    span = _days_back(day, days)
    records: list[dict] = []
    for d in span:
        records.extend(audit.read_records(d))

    a = analyze(records)
    label = day if days == 1 else f"{span[0]} … {span[-1]}（{days}天）"
    report = _render(label, a)

    written = None
    if ctx.get("write", True):
        try:
            _OUT_DIR.mkdir(parents=True, exist_ok=True)
            out = _OUT_DIR / (f"{day}.md" if days == 1 else f"{span[0]}_{span[-1]}.md")
            out.write_text(report, "utf-8")
            written = out.relative_to(_REPO_ROOT).as_posix()
        except Exception as e:
            return Result(ok=False, summary=f"报告已生成但落盘失败：{e}", detail=report)

    if not a["total"]:
        return Result(ok=True, summary=f"{label}:没有审计记录,无可汇总。",
                      detail=report, data=a)

    tick = a["tick_duration"]
    pace = f" · 单跳中位 {_fmt(tick['p50'])}" if tick else ""
    summary = (f"{label}:{a['runs']} 次进程 · {a['failure_total']} 次失败 · "
               f"{a['incomplete_runs']} 次未收场{pace}"
               + (f" → 已写入 {written}" if written else "（未落盘）"))
    return Result(ok=True, summary=summary, detail=report, data=a)
