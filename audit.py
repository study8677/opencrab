#!/usr/bin/env python3
"""结构化运行审计 🧾 —— 把每次启动、决策、失败、退出都写成统一 JSON 记录。

为什么要有它：让这只螃蟹更容易「看见自己怎么思考、怎么出错」。
心跳循环里散落的 print 日志转瞬即逝、也难以机读；审计把关键节点
固化成一行行 JSON(JSONL)，事后能回放整段生命、定位问题出在哪一步。

设计原则：
- 统一格式：每条记录都有 `ts / run_id / seq / event`，外加该事件的字段。
- 一次进程一个 `run_id`：同一次「活着」的所有记录能被串起来回放。
- 按天分文件：`state/audit/<日期>.jsonl`，落在被 .gitignore 的 state/ 里。
- 绝不反噬：写审计本身永不抛错——审计是观测者，不能成为新的故障源。

记录之外，本模块还内置「轨迹回放」🧬：从既有审计派生(单一真相源，不新增
任何日志)，按 run_id 把一次进程还原成一条「为什么会这样」的因果链，并给出
「怎么把它再跑一遍」的最小重放配方。命令行：
    python audit.py                 # 列出今天的各次运行(轨迹)及其结局
    python audit.py --day 2026-05-25
    python audit.py --last          # 摊开最近一次运行的完整链 + 重放配方
    python audit.py --run <RUN_ID>  # 摊开指定一次运行
    python audit.py --json          # 机读：把轨迹导成 JSON(配合 --run/--last)

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import pathlib
import sys
import threading

import jsonlstore

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
AUDIT_DIR = _REPO_ROOT / "state" / "audit"


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="milliseconds")


class Auditor:
    """一次进程内的审计员：把事件按统一格式追加进当天的 JSONL。"""

    def __init__(self, audit_dir: pathlib.Path = AUDIT_DIR) -> None:
        self.audit_dir = audit_dir
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_id = f"{stamp}-{os.getpid()}"
        self._seq = 0
        self._lock = threading.Lock()

    def _path(self) -> pathlib.Path:
        return self.audit_dir / f"{datetime.date.today().isoformat()}.jsonl"

    def record(self, event: str, **fields) -> dict:
        """写下一条审计记录并返回它；任何写入异常都被吞掉，绝不弄死生命。

        `event` 是事件名(startup / tick_start / intent / decision /
        act / failure / molt / exit ……)；其余关键信息用关键字传入。
        """
        with self._lock:
            self._seq += 1
            rec = {"ts": _now_iso(), "run_id": self.run_id,
                   "seq": self._seq, "event": event}
            # 把字段塞进去；不可 JSON 序列化的值退化成字符串，绝不因此失败
            for k, v in fields.items():
                rec[k] = v if _json_safe(v) else str(v)
            jsonlstore.append_jsonl(self._path(), rec)   # 写盘出错被吞，审计绝不反噬
            return rec


def _json_safe(v) -> bool:
    try:
        json.dumps(v, ensure_ascii=False)
        return True
    except (TypeError, ValueError):
        return False


# ── 读取 / 回放：给审计能力(cap_audit)与人类复用 ─────────────────────
def read_records(day: str | None = None, limit: int | None = None) -> list[dict]:
    """读出某天(默认今天)的审计记录；坏行直接跳过，返回时间正序列表。"""
    day = day or datetime.date.today().isoformat()
    recs = jsonlstore.read_jsonl(AUDIT_DIR / f"{day}.jsonl")
    return recs[-limit:] if limit else recs


def summarize(records: list[dict]) -> dict:
    """把一批记录归纳成「各事件计数 + 失败条数 + 涉及的进程数」。"""
    events: dict[str, int] = {}
    failures = 0
    runs: set[str] = set()
    for r in records:
        ev = r.get("event", "?")
        events[ev] = events.get(ev, 0) + 1
        if ev == "failure":
            failures += 1
        if r.get("run_id"):
            runs.add(r["run_id"])
    return {"total": len(records), "events": events,
            "failures": failures, "runs": len(runs)}


# 一个进程级默认审计员：crab.py 直接 import 用，省得到处传实例。
default = Auditor()


def record(event: str, **fields) -> dict:
    """便捷入口：写进进程级默认审计员。"""
    return default.record(event, **fields)


# ══ 轨迹回放 🧬 ═════════════════════════════════════════════════════════
# 把单独一次进程还原成一条「为什么会这样」的因果链，并给出最小重放配方。
# 全部从上面的审计记录派生——单一真相源，不新增任何日志。
@dataclasses.dataclass
class Step:
    """轨迹里的一步：一条被挑出来、对「因果链」有意义的事件。"""
    seq: int
    ts: str
    event: str
    note: str                 # 一句人话：这一步发生了什么
    fields: dict              # 该事件的原始字段(去掉公共头)


@dataclasses.dataclass
class Trace:
    """一次进程的可重放轨迹：输入→环境→分支→结局，外加重放配方。"""
    run_id: str
    started_at: str
    ended_at: str
    n_events: int
    intent: str | None        # 输入：这次形成的意图(首行)
    env: dict                 # 环境：autonomy/executor/dreaming/once/tick_seconds
    steps: list[Step]         # 决策分支链(按时间正序)
    outcome: str              # 结局：人话一句
    failed: bool

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["replay"] = replay_recipe(self)
        return d


def _strip(rec: dict) -> dict:
    """去掉公共头(ts/run_id/seq/event)，只留该事件自己的字段。"""
    return {k: v for k, v in rec.items()
            if k not in ("ts", "run_id", "seq", "event")}


# 哪些事件构成「决策分支链」，以及怎么把它说成人话。
def _note(rec: dict) -> str | None:
    ev = rec.get("event")
    f = rec
    if ev == "decision":
        gate, ok = f.get("gate", "?"), f.get("pass_")
        if gate == "energy":
            return (f"体力闸门通过(已用 {f.get('spent')}/{f.get('budget')})"
                    if ok else f"体力耗尽，本跳跳过({f.get('spent')}/{f.get('budget')})")
        return f"决策 {gate}：{'通过' if ok else '未通过'}"
    if ev == "intent":
        tag = "（梦境）" if f.get("dreaming") else ""
        return f"形成意图{tag}：{str(f.get('text', '')).strip()[:60]}"
    if ev == "act":
        if f.get("dry_run"):
            return f"预演(未改动) · 自治={f.get('autonomy')}"
        if f.get("changed"):
            return f"动手改动 · 分支 {f.get('branch')} · 自治={f.get('autonomy')}"
        return f"写下日志(未改代码) · 自治={f.get('autonomy')}"
    if ev == "tick_skip":
        return f"跳过这次心跳(原因：{f.get('reason')})"
    if ev == "failure":
        return f"💥 失败于 {f.get('where', '?')}：{str(f.get('error', '')).strip()[:80]}"
    if ev == "exit":
        return f"收场(原因：{f.get('reason')})"
    return None   # 其余事件(tick_start/tick_done/startup…)不进分支链,只计入总数


def _derive_env(recs: list[dict]) -> dict:
    """从 startup / intent 事件里抽出复现所需的环境。"""
    env: dict = {}
    su = next((r for r in recs if r.get("event") == "startup"), None)
    if su:
        for k in ("autonomy", "executor", "dreaming", "once", "tick_seconds"):
            if k in su:
                env[k] = su[k]
    # startup 没记 dreaming 时(如只跑了能力)，退回看 intent
    if "dreaming" not in env:
        it = next((r for r in recs if r.get("event") == "intent"), None)
        if it and "dreaming" in it:
            env["dreaming"] = it["dreaming"]
    return env


def _outcome(recs: list[dict]) -> tuple[str, bool]:
    """归纳这次运行的结局(人话, 是否失败)。"""
    failed = any(r.get("event") == "failure" for r in recs)
    ex = next((r for r in reversed(recs) if r.get("event") == "exit"), None)
    if ex:
        base = f"正常收场(原因：{ex.get('reason')})"
        return (base + "，但中途有失败" if failed else base), failed
    if failed:
        return "中途失败且未正常收场", True
    return "未留下 exit(被杀/崩溃/仍在跑)", failed


def build_traces(records: list[dict]) -> list[Trace]:
    """把一批审计记录(可能含多次运行)拆成一条条轨迹，按开始时间正序。"""
    runs: dict[str, list[dict]] = {}
    for r in records:
        runs.setdefault(r.get("run_id", "?"), []).append(r)

    traces: list[Trace] = []
    for rid, recs in runs.items():
        recs.sort(key=lambda r: r.get("seq", 0))
        it = next((r for r in recs if r.get("event") == "intent"), None)
        intent = str(it.get("text", "")).strip() if it else None
        steps = [Step(seq=r.get("seq", 0), ts=r.get("ts", "?"),
                      event=r.get("event", "?"), note=note, fields=_strip(r))
                 for r in recs if (note := _note(r))]
        outcome, failed = _outcome(recs)
        traces.append(Trace(
            run_id=rid,
            started_at=recs[0].get("ts", "?") if recs else "?",
            ended_at=recs[-1].get("ts", "?") if recs else "?",
            n_events=len(recs),
            intent=intent.split("\n")[0][:120] if intent else None,
            env=_derive_env(recs),
            steps=steps,
            outcome=outcome,
            failed=failed,
        ))
    traces.sort(key=lambda t: t.started_at)
    return traces


def reconstruct(day: str | None = None) -> list[Trace]:
    """读某天(默认今天)的审计，重建出当天所有运行的轨迹。"""
    return build_traces(read_records(day))


def replay_recipe(trace: Trace) -> dict:
    """从轨迹的环境派生出复现它所需的最小「环境变量 + 命令行」。

    目的不是字节级复刻(意图来自大脑，本就不确定)，而是把**决策路径**
    放回同一组前置条件下重跑：同样的自治模式、执行器、梦境与否、once 与否。
    """
    env = trace.env
    envvars: dict[str, str] = {}
    if env.get("autonomy"):
        envvars["OPENCRAB_AUTONOMY"] = str(env["autonomy"])
    if env.get("executor"):
        envvars["OPENCRAB_EXECUTOR"] = str(env["executor"])
    if env.get("dreaming"):
        # 梦境模式 = 没有 key；清空它就能离线复跑这条决策路径
        envvars["OPENCRAB_API_KEY"] = ""
    # 这次若动手是预演，复跑也用预演，避免真改代码
    if any(s.event == "act" and s.fields.get("dry_run") for s in trace.steps):
        envvars["OPENCRAB_DRY_RUN"] = "1"

    subcmd = "once" if env.get("once") else "live"
    argv = ["python", "crab.py", subcmd]
    prefix = " ".join(f"{k}={v!r}" if v == "" else f"{k}={v}"
                      for k, v in envvars.items())
    cmd = (prefix + " " if prefix else "") + " ".join(argv)
    return {"env": envvars, "argv": argv, "command": cmd}


# ── 渲染(给 CLI / 能力复用)─────────────────────────────────────────────
def _short(rid: str) -> str:
    return rid[-12:] if len(rid) > 12 else rid


def render_list(traces: list[Trace], day: str) -> str:
    """一行一条运行的概览清单。"""
    L = [f"🧬 {day} · 共 {len(traces)} 次运行(轨迹)"]
    if not traces:
        L.append(f"   没有审计记录(state/audit/{day}.jsonl 不存在或为空)。")
        return "\n".join(L)
    for t in traces:
        mark = "❌" if t.failed else "✅"
        intent = t.intent or "（无意图，可能只跑了能力）"
        L.append(f"  {mark} {_short(t.run_id)} · {len(t.steps)} 步 · "
                 f"{t.outcome}\n        意图：{intent}")
    L.append("\n  用 `--run <RUN_ID>` 或 `--last` 摊开某次运行的完整链与重放配方。")
    return "\n".join(L)


def render_trace(t: Trace) -> str:
    """把一条轨迹摊开成「输入→环境→分支链→结局→重放配方」。"""
    L = [f"🧬 运行轨迹 · {t.run_id}",
         f"   时间：{t.started_at} → {t.ended_at} · 共 {t.n_events} 条事件",
         "",
         f"▸ 输入(意图)：{t.intent or '（无）'}",
         "▸ 环境：" + ("、".join(f"{k}={v}" for k, v in t.env.items()) or "（未记录）"),
         "",
         "▸ 决策分支链："]
    if t.steps:
        for s in t.steps:
            L.append(f"    #{s.seq:>3} {s.ts[-12:]}  {s.note}")
    else:
        L.append("    （没有可识别的决策步——这次运行可能没真正进入心跳）")
    L += ["", f"▸ 结局：{'❌ ' if t.failed else '✅ '}{t.outcome}", ""]

    recipe = replay_recipe(t)
    L += ["▸ 重放配方(把这条决策路径放回同样前置条件下重跑)：",
          "    " + recipe["command"]]
    return "\n".join(L)


# ── CLI ─────────────────────────────────────────────────────────────
def _pick(traces: list[Trace], run_id: str | None, last: bool) -> Trace | None:
    if last:
        return traces[-1] if traces else None
    if run_id:
        # 支持用尾段(短 id)匹配，省得敲全名
        for t in traces:
            if t.run_id == run_id or t.run_id.endswith(run_id):
                return t
    return None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 结构化运行轨迹回放 🧬 —— 把一次运行串成可重放的最小事件链")
    ap.add_argument("--day", metavar="YYYY-MM-DD", help="回放哪一天(默认今天)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--run", metavar="RUN_ID", help="摊开指定一次运行(可用尾段短 id)")
    g.add_argument("--last", action="store_true", help="摊开最近一次运行")
    ap.add_argument("--json", action="store_true",
                    help="机读：把选中的轨迹(或全部)导成 JSON")
    args = ap.parse_args(argv)

    day = args.day or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        print(f"❌ --day 需要 YYYY-MM-DD 格式，收到 {day!r}")
        sys.exit(2)

    traces = reconstruct(day)
    picked = _pick(traces, args.run, args.last)

    if args.run and picked is None:
        print(f"❌ {day} 没有匹配 {args.run!r} 的运行。")
        sys.exit(1)

    if args.json:
        out = picked.to_dict() if picked else [t.to_dict() for t in traces]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if picked:
        print(render_trace(picked))
    else:
        print(render_list(traces, day))


if __name__ == "__main__":
    main()
