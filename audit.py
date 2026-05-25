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

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
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
