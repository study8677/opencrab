#!/usr/bin/env python3
"""并行领航 🛟🌀 —— 把互不依赖的验证/调研/草案任务，编进「同波并发、异波串行」的航次，
真并发跑出来，量「省了多少时间」与「多少对任务在抢同一份文件」。

为什么要有它：我每拍想提速，最诱人的就是「一起跑」——自测、查资料、起草几份候选稿，
看着彼此不相干，凑一块儿并发，墙上时间立省一截。可「看着不相干」最会骗人：两个任务
若都往同一份文件里写，并发就是在制造竞态——谁后落盘谁赢，证据从此说不清是哪次跑的结果。
**提速若靠赌「它们大概不打架」，省下的那点时间迟早连本带利赔进糊涂账里。**

所以并行不能按「手头几条命令」凑，得按**读写足迹**判独立：

  · 足迹(footprint) —— 每个任务都得报清「我读哪些文件、写哪些文件」。只读任务（验证、调研）
                       彼此永不冲突，天然可并发；一旦有人要写，写集就是它和别人之间的雷区。
  · 冲突(conflict) —— 两任务冲突 ⟺ 一方的写集，碰上了另一方的读集或写集。
                      （读∩读 不算——都只看不动，并发安全。）
  · 航次(wave) —— 把任务贪心染色成若干波：**同一波内两两无冲突**，故可并发；冲突的被推到后一波，
                  于是它和它的冲突者之间退回串行。同波并发、异波串行——并发只发生在被证明安全处。

省时与冲突率（量化「值不值」与「乱不乱」）：
  · 串行墙上时间 = 所有任务耗时之和；并行墙上时间 = 各波「波内最慢任务」之和。
    省时 = 串行 − 并行；并发度 = 串行 / 并行。
  · 冲突率 = 有冲突的任务对数 / 任务对总数。率高，说明这批任务足迹太缠，本就不该硬并；
    率低，才是安全并行真正能提速的地方。

判准（并行绝不牺牲证据闭环）：
  · 默认只**规划**：算航次、估省时与冲突率，绝不擅自执行。要真跑得显式 `--run`。
  · 真跑时，同波并发由「波内无冲突」保证——绝不让两个写同一文件的任务同时落盘。
  · 任一任务退出码非零，如实记下并让总退出码非零：并发提速，但失败一条都不许吞。
  · 队列与跑批结果落在被 .gitignore 的 state/ 里：领航是规划者/观测者，写盘出错绝不反噬生命。

航次模板（预置的成套并行验证航次）：
  · 我每次自改前，总要回头跑三件互不依赖的事——证据账本回查、变更影响分析、文档真伪对账。
    它们都只读、彼此无冲突，串着跑纯属白等。`--template selfmod` 把这趟「自改前体检」
    钉成一个**可复跑的固定航次**：一波并发跑完，省的是等待，验的一项不少。
  · 模板任务不入持久队列（队列是攒散活的，模板是固定配方）——它当场编航次、当场跑，不留残渣。

用法：
    python parallelpilot.py                       # 看当前队列编成的航次 + 估省时/冲突率
    python parallelpilot.py --template selfmod    # 看「自改前体检」航次（证据/影响/文档并发）
    python parallelpilot.py --template selfmod --run   # 真并发跑这趟体检，量实测省时
    python parallelpilot.py --add "跑自测" \\       # 入队一个任务（默认只读：不写文件）
        --kind verify --cmd "python -m pyflakes x.py" \\
        --reads x.py --est 4
    python parallelpilot.py --add "起草README段" --kind draft \\
        --cmd "python gen.py" --writes draft.md --est 8
    python parallelpilot.py --done ID             # 任务已落地，出队
    python parallelpilot.py --drop ID             # 丢弃任务
    python parallelpilot.py --run                 # 真并发执行：同波并发跑，量真实省时
    python parallelpilot.py --run --timeout 60    # 每个任务最多跑 60s
    python parallelpilot.py --gate 0.5            # 冲突率 ≥ 0.5 则退出码非零（太缠，别硬并）
    python parallelpilot.py --quiet               # 只在冲突过高 / 跑批失败 / 触发闸门时说话
    python parallelpilot.py --json                # 机读：队列 + 航次 + 省时/冲突率

退出码：0 = 正常；1 = 触发 --gate / --run 有任务失败。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import json
import pathlib
import shlex
import subprocess
import sys
import time
import uuid

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402  —— 队列/跑批结果复用「读一批 / 追一条」的单一真相源

# 队列与跑批结果落在被 .gitignore 的 state/ 里：领航不污染版本库。
QUEUE_PATH = REPO_ROOT / "state" / "parallelpilot" / "queue.jsonl"
RUNS_PATH = REPO_ROOT / "state" / "parallelpilot" / "runs.jsonl"

# 任务种类——只是给人看的标签；判独立靠的是读写足迹，不是种类。
KINDS = ("verify", "research", "draft")
DEFAULT_EST = 5.0   # 没报耗时估计时的兜底（秒）——只用于规划期估省时，真跑以实测为准


@dataclasses.dataclass
class Task:
    """一个待并发的任务：跑什么命令 + 读写哪些文件 + 估计多久。"""
    id: str
    summary: str
    kind: str
    cmd: str                  # 要执行的命令（argv 字符串，shlex 切分，不过 shell）
    reads: list[str]          # 读取的文件
    writes: list[str]         # 写入的文件（写集——冲突判定的核心）
    est: float                # 估计耗时（秒），仅规划期用
    ts: str

    @property
    def read_set(self) -> set[str]:
        return set(self.reads)

    @property
    def write_set(self) -> set[str]:
        return set(self.writes)

    @property
    def read_only(self) -> bool:
        """只读任务（不写任何文件）——天然可与任何只读任务并发。"""
        return not self.writes

    @property
    def runnable_reason(self) -> str | None:
        """不可执行的原因；可执行则 None。"""
        if not self.cmd.strip():
            return "无命令——没法试跑"
        try:
            if not shlex.split(self.cmd):
                return "命令空白——没法试跑"
        except ValueError as e:
            return f"命令无法解析：{e}"
        return None

    def to_meta(self) -> dict:
        return {
            "id": self.id, "summary": self.summary, "kind": self.kind,
            "cmd": self.cmd, "reads": self.reads, "writes": self.writes,
            "est": round(self.est, 1), "ts": self.ts,
            "read_only": self.read_only, "reason": self.runnable_reason,
        }


def conflicts(a: Task, b: Task) -> bool:
    """两任务是否冲突：一方写集碰上另一方的读集或写集。读∩读不算。"""
    aw, bw = a.write_set, b.write_set
    if aw & bw:                       # 都要写同一文件——最硬的竞态
        return True
    if aw & b.read_set:               # a 写 b 读——并发则 b 读到半截
        return True
    if bw & a.read_set:               # b 写 a 读——对称
        return True
    return False


def _coerce(rec: dict) -> Task | None:
    """队列一行 JSON → Task；字段坏/缺则跳过（绝不臆造）。"""
    try:
        reads = rec.get("reads") or []
        writes = rec.get("writes") or []
        if not isinstance(reads, list) or not isinstance(writes, list):
            return None
        kind = str(rec.get("kind", "verify"))
        return Task(
            id=str(rec["id"]),
            summary=str(rec.get("summary", "")),
            kind=kind if kind in KINDS else "verify",
            cmd=str(rec.get("cmd", "")),
            reads=[str(f) for f in reads],
            writes=[str(f) for f in writes],
            est=max(0.0, float(rec.get("est", DEFAULT_EST))),
            ts=str(rec.get("ts", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_queue() -> list[Task]:
    """读出当前任务队列；坏行跳过，读不到则空队列。"""
    out: list[Task] = []
    for rec in jsonlstore.read_jsonl(QUEUE_PATH):
        t = _coerce(rec)
        if t is not None:
            out.append(t)
    return out


def _task_row(t: Task) -> dict:
    return {"id": t.id, "summary": t.summary, "kind": t.kind, "cmd": t.cmd,
            "reads": t.reads, "writes": t.writes, "est": t.est, "ts": t.ts}


def enqueue(summary: str, kind: str, cmd: str, reads: list[str],
            writes: list[str], est: float) -> Task:
    """入队一个任务，返回落地后的 Task。"""
    t = Task(
        id=uuid.uuid4().hex[:8],
        summary=summary.strip(),
        kind=kind if kind in KINDS else "verify",
        cmd=cmd.strip(),
        reads=reads,
        writes=writes,
        est=max(0.0, est),
        ts=datetime.datetime.now().isoformat(timespec="seconds"),
    )
    jsonlstore.append_jsonl(QUEUE_PATH, _task_row(t))
    return t


# ── 航次模板：预置的成套任务（自改前的标准并行验证航次）──────────────────
# 模板是固定配方，不入持久队列：当场编航次、当场跑，可复跑、不留残渣。
# 「自改前体检」三件事都只读、彼此无冲突，故必然编进同一波并发——这正是
# 「提速靠减少等待、不靠削弱验证」最干净的样例：一项不少，只是不再串着白等。
TEMPLATES: dict[str, list[dict]] = {
    "selfmod": [
        {"id": "ev", "summary": "证据账本回查：能力声明是否仍跑得通",
         "kind": "verify", "cmd": "python evidence.py --quiet",
         "reads": ["evidence.py"], "writes": [], "est": 6.0},
        {"id": "im", "summary": "变更影响分析：动了什么、最少该验哪些",
         "kind": "research", "cmd": "python impact.py",
         "reads": ["impact.py"], "writes": [], "est": 5.0},
        {"id": "ds", "summary": "文档真伪对账：自述与真实能力是否漂移",
         "kind": "verify", "cmd": "python docsync.py --quiet",
         "reads": ["docsync.py"], "writes": [], "est": 4.0},
    ],
}


def build_template(name: str) -> list[Task]:
    """把一个航次模板展开成成套 Task（id 稳定，便于跑批账本对照）。

    模板任务的 id 用模板名+短码拼成（如 selfmod-ev），不走 uuid——
    同一模板每次展开都是同一批 id，跑批记录因此可纵向比对。
    未知模板名返回空列表（调用方负责拦截）。
    """
    specs = TEMPLATES.get(name)
    if not specs:
        return []
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    out: list[Task] = []
    for spec in specs:
        out.append(Task(
            id=f"{name}-{spec['id']}",
            summary=spec["summary"],
            kind=spec.get("kind", "verify"),
            cmd=spec.get("cmd", ""),
            reads=list(spec.get("reads", [])),
            writes=list(spec.get("writes", [])),
            est=float(spec.get("est", DEFAULT_EST)),
            ts=ts,
        ))
    return out


def remove(tid: str) -> bool:
    """按 id 出队/丢弃；存在并成功重写返回 True。写盘出错只回 False。"""
    tasks = load_queue()
    kept = [t for t in tasks if t.id != tid]
    if len(kept) == len(tasks):
        return False
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE_PATH.open("w", encoding="utf-8") as f:
            for t in kept:
                f.write(json.dumps(_task_row(t), ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


# ── 编航次：贪心染色，同波内两两无冲突 ───────────────────────────────────
def schedule(tasks: list[Task]) -> list[list[Task]]:
    """把任务贪心染色成若干波，保证同一波内任意两任务都不冲突。

    每个任务挑「最早的、与波内全员都不冲突」的波放入；都冲突则新开一波。
    这是图染色的贪心近似——不求最少波数，只求每一波都被证明可安全并发。
    """
    waves: list[list[Task]] = []
    for t in tasks:
        placed = False
        for wave in waves:
            if all(not conflicts(t, other) for other in wave):
                wave.append(t)
                placed = True
                break
        if not placed:
            waves.append([t])
    return waves


def conflict_rate(tasks: list[Task]) -> tuple[int, int, float]:
    """返回 (冲突对数, 任务对总数, 冲突率)。任务 < 2 个则率为 0。"""
    n = len(tasks)
    total = n * (n - 1) // 2
    if total == 0:
        return 0, 0, 0.0
    clashes = sum(
        1
        for i in range(n)
        for j in range(i + 1, n)
        if conflicts(tasks[i], tasks[j])
    )
    return clashes, total, clashes / total


def project(tasks: list[Task], waves: list[list[Task]]) -> dict:
    """规划期估算：用各任务的 est 估串行/并行墙上时间、省时与并发度。"""
    serial = sum(t.est for t in tasks)
    parallel = sum(max((t.est for t in w), default=0.0) for w in waves)
    saved = serial - parallel
    clashes, pairs, rate = conflict_rate(tasks)
    return {
        "tasks": len(tasks), "waves": len(waves),
        "serial_s": round(serial, 1), "parallel_s": round(parallel, 1),
        "saved_s": round(saved, 1),
        "speedup": round(serial / parallel, 2) if parallel else None,
        "conflict_pairs": clashes, "total_pairs": pairs,
        "conflict_rate": round(rate, 3),
    }


# ── 真跑：同波并发执行，量真实墙上时间 ───────────────────────────────────
@dataclasses.dataclass
class RunResult:
    """一个任务一次执行的实测结果。"""
    id: str
    summary: str
    wave: int
    rc: int | None         # 退出码；超时 / 起不来则 None
    dur_s: float
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def to_meta(self) -> dict:
        return {"id": self.id, "summary": self.summary, "wave": self.wave,
                "rc": self.rc, "dur_s": round(self.dur_s, 2), "note": self.note}


def _run_one(t: Task, timeout: float | None) -> RunResult:
    """跑单个任务：实测墙上耗时与退出码。异常一律转成结果，绝不抛。"""
    t0 = time.monotonic()
    try:
        argv = shlex.split(t.cmd)
        proc = subprocess.run(
            argv, cwd=str(REPO_ROOT), timeout=timeout,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return RunResult(t.id, t.summary, -1, proc.returncode,
                         time.monotonic() - t0)
    except subprocess.TimeoutExpired:
        return RunResult(t.id, t.summary, -1, None,
                         time.monotonic() - t0, note=f"超时 >{timeout}s")
    except Exception as e:
        return RunResult(t.id, t.summary, -1, None,
                         time.monotonic() - t0, note=f"起不来：{e}")


def execute(waves: list[list[Task]], timeout: float | None) -> tuple[list[RunResult], dict]:
    """逐波执行：波内并发（线程池），波间串行。返回 (实测结果, 实测汇总)。

    同波并发的安全性由 schedule() 的「波内无冲突」保证；这里只管把它跑出来、量出来。
    """
    results: list[RunResult] = []
    parallel_s = 0.0
    serial_s = 0.0
    for wi, wave in enumerate(waves):
        runnable = [t for t in wave if t.runnable_reason is None]
        skipped = [t for t in wave if t.runnable_reason is not None]
        for t in skipped:
            results.append(RunResult(t.id, t.summary, wi, None, 0.0,
                                     note=t.runnable_reason or "不可执行"))
        wave_wall = 0.0
        if runnable:
            wt0 = time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(runnable)) as ex:
                futs = {ex.submit(_run_one, t, timeout): t for t in runnable}
                for fut in concurrent.futures.as_completed(futs):
                    r = fut.result()
                    r.wave = wi
                    results.append(r)
                    serial_s += r.dur_s     # 串行口径 = 各任务实测耗时之和
            wave_wall = time.monotonic() - wt0   # 并行口径 = 波的真实墙上时间
        parallel_s += wave_wall

    saved = serial_s - parallel_s
    failed = [r for r in results if not r.ok]
    summary = {
        "waves": len(waves),
        "serial_s": round(serial_s, 1), "parallel_s": round(parallel_s, 1),
        "saved_s": round(saved, 1),
        "speedup": round(serial_s / parallel_s, 2) if parallel_s else None,
        "failed": len(failed),
    }
    return results, summary


def manifest(tasks: list[Task]) -> dict:
    """机读：队列 + 航次 + 估省时/冲突率。"""
    waves = schedule(tasks)
    m = project(tasks, waves)
    m["queue"] = [t.to_meta() for t in tasks]
    m["wave_plan"] = [[t.id for t in w] for w in waves]
    return m


# ── 渲染 ─────────────────────────────────────────────────────────────
_KIND_ICON = {"verify": "✅", "research": "🔎", "draft": "✍️"}


def _fmt_s(v: float | None) -> str:
    return f"{v:.0f}s" if v is not None else "—"


def _render_plan(tasks: list[Task], waves: list[list[Task]]) -> str:
    p = project(tasks, waves)
    L = [f"🛟🌀 opencrab 并行领航 —— 队列 {len(tasks)} 个任务 · "
         f"编成 {len(waves)} 个航次", ""]

    if not tasks:
        L.append("（队列空空——还没攒下任何待并发任务。先 --add 几个再来。）")
        return "\n".join(L)

    for wi, wave in enumerate(waves):
        wall = max((t.est for t in wave), default=0.0)
        tag = "并发" if len(wave) > 1 else "单跑"
        L.append(f"  🌀 航次 {wi + 1}（{tag} {len(wave)} 个 · 波内最慢 {_fmt_s(wall)}）")
        for t in wave:
            icon = _KIND_ICON.get(t.kind, "•")
            fp = []
            if t.reads:
                fp.append(f"读{','.join(t.reads)}")
            if t.writes:
                fp.append(f"写{','.join(t.writes)}")
            foot = " · ".join(fp) if fp else "无足迹"
            bad = f"  ⚠️ {t.runnable_reason}" if t.runnable_reason else ""
            L.append(f"     {icon} [{t.id}] {t.summary}  (~{_fmt_s(t.est)} · {foot}){bad}")
        L.append("")

    L.append(f"⏱️ 估算：串行 {_fmt_s(p['serial_s'])} → 并行 {_fmt_s(p['parallel_s'])}"
             f" · 省 {_fmt_s(p['saved_s'])}"
             + (f" · 提速 {p['speedup']}×" if p["speedup"] else ""))
    L.append(f"💥 冲突率：{p['conflict_pairs']}/{p['total_pairs']} 对"
             f" = {p['conflict_rate'] * 100:.0f}%")
    L.append("")

    if p["conflict_rate"] >= 0.5:
        L.append("🦀 冲突率过半——这批任务足迹太缠，硬并只是把竞态藏进波次里。"
                 "先拆开写集（让谁少写一份共享文件），再谈并发。")
    elif p["waves"] == 1:
        L.append("🦀 全员互不依赖，一波并发到底——这正是安全并行最划算的局面。"
                 "确认足迹报全了，就 --run 真跑一次量省时。")
    else:
        L.append("🦀 同波并发、异波串行：并发只发生在被证明无冲突处，"
                 "省时是真省，证据一条不少。--run 真跑一次看实测。")
    return "\n".join(L)


def _render_run(results: list[RunResult], summary: dict) -> str:
    L = [f"🛟🌀 opencrab 并行领航 · 实跑 —— {summary['waves']} 个航次", ""]
    by_wave: dict[int, list[RunResult]] = {}
    for r in results:
        by_wave.setdefault(r.wave, []).append(r)
    for wi in sorted(by_wave):
        L.append(f"  🌀 航次 {wi + 1}：")
        for r in by_wave[wi]:
            if r.rc is None:
                mark, tail = "⏸️", f" —— {r.note}"
            elif r.ok:
                mark, tail = "✅", ""
            else:
                mark, tail = "❌", f" —— 退出码 {r.rc}"
            L.append(f"     {mark} [{r.id}] {r.summary}  ({_fmt_s(r.dur_s)}){tail}")
        L.append("")
    L.append(f"⏱️ 实测：串行口径 {_fmt_s(summary['serial_s'])} → "
             f"并行墙上 {_fmt_s(summary['parallel_s'])} · 省 {_fmt_s(summary['saved_s'])}"
             + (f" · 提速 {summary['speedup']}×" if summary["speedup"] else ""))
    if summary["failed"]:
        L.append(f"🦀 {summary['failed']} 个任务失败——并发提速，但失败一条都不吞。"
                 "先修好它们，再谈这次省时算不算数。")
    else:
        L.append("🦀 全员通过 · 同波并发安全跑完——省下的时间是干净的，没赊证据的账。")
    return "\n".join(L)


def _parse_list(s: str | None) -> list[str]:
    """逗号分隔 → 去空白列表；None/空 → 空列表。"""
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 并行领航 🛟🌀 —— 把互不依赖的任务编成同波并发的航次，"
                    "真并发量省时与冲突率，安全提速不牺牲证据")
    ap.add_argument("--add", metavar="SUMMARY", help="入队一个任务（一句话摘要）")
    ap.add_argument("--kind", choices=KINDS, default="verify",
                    help=f"任务种类 {KINDS}（配合 --add，默认 verify）")
    ap.add_argument("--cmd", metavar="CMD", default="",
                    help="该任务要执行的命令（argv 字符串；配合 --add）")
    ap.add_argument("--reads", metavar="A,B", help="该任务读取的文件（逗号分隔；配合 --add）")
    ap.add_argument("--writes", metavar="A,B", help="该任务写入的文件（逗号分隔；配合 --add）")
    ap.add_argument("--est", type=float, default=DEFAULT_EST, metavar="SEC",
                    help=f"该任务估计耗时秒（配合 --add，默认 {DEFAULT_EST}）")
    ap.add_argument("--template", choices=tuple(TEMPLATES), metavar="NAME",
                    help=f"编一个预置航次模板而非读队列 {tuple(TEMPLATES)}"
                         "（模板不入队、可复跑；配合 --run / --json / --gate）")
    ap.add_argument("--done", metavar="ID", help="标记某任务已落地，出队")
    ap.add_argument("--drop", metavar="ID", help="丢弃某任务")

    ap.add_argument("--run", action="store_true",
                    help="真并发执行：逐波跑（波内并发），量实测省时")
    ap.add_argument("--timeout", type=float, default=120.0, metavar="SEC",
                    help="--run 时每个任务的超时秒数（默认 120）")
    ap.add_argument("--gate", type=float, default=None, metavar="RATE",
                    help="冲突率 ≥ RATE（0..1）则退出码非零（太缠，别硬并）")
    ap.add_argument("--quiet", action="store_true",
                    help="只在冲突过高 / 跑批失败 / 触发闸门时说话（适合钩子 / CI）")
    ap.add_argument("--json", action="store_true", help="机读：队列 + 航次 + 省时/冲突率")
    args = ap.parse_args(argv)

    # ── 写操作：入队 / 出队 / 丢弃 ──
    if args.add is not None:
        writes = _parse_list(args.writes)
        t = enqueue(args.add, args.kind, args.cmd, _parse_list(args.reads),
                    writes, args.est)
        warn = ""
        if t.runnable_reason:
            warn = f"  ⚠️ {t.runnable_reason}"
        elif not writes:
            warn = "  （只读：天然可并发）"
        print(f"📥 入队 [{t.id}] 「{t.summary}」{_KIND_ICON.get(t.kind, '')}{args.kind}"
              f"（~{_fmt_s(t.est)}）{warn}")
        sys.exit(0)

    if args.done is not None or args.drop is not None:
        tid = args.done or args.drop
        verb = "落地出队" if args.done else "丢弃"
        ok = remove(tid)
        print(f"{'✅' if ok else '❓'} {verb} [{tid}]"
              + ("" if ok else " —— 队列里没这个 id"))
        sys.exit(0 if ok else 1)

    # 任务来源：给了 --template 就编模板（固定配方、不入队），否则读持久队列。
    tasks = build_template(args.template) if args.template else load_queue()
    waves = schedule(tasks)
    _, _, rate = conflict_rate(tasks)
    gate_tripped = args.gate is not None and rate >= args.gate

    # ── 真跑 ──
    if args.run:
        results, summary = execute(waves, args.timeout if args.timeout > 0 else None)
        # 把这次跑批记进 state/ 跑批账本（观测者落盘，出错不反噬）。
        jsonlstore.append_jsonl(RUNS_PATH, {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "summary": summary, "conflict_rate": round(rate, 3),
            "results": [r.to_meta() for r in results],
        })
        run_failed = summary["failed"] > 0
        if args.quiet:
            msgs = []
            if run_failed:
                msgs.append(f"🌀 {summary['failed']} 个任务失败")
            if gate_tripped:
                msgs.append(f"🌀 冲突率 {rate * 100:.0f}% 达到闸门 {args.gate * 100:.0f}%")
            if msgs:
                print("；".join(msgs))
        else:
            print(_render_run(results, summary))
        sys.exit(1 if (run_failed or gate_tripped) else 0)

    # ── 规划（默认）──
    if args.json:
        print(json.dumps(manifest(tasks), ensure_ascii=False, indent=2))
        sys.exit(1 if gate_tripped else 0)

    if args.quiet:
        if gate_tripped:
            print(f"🌀 冲突率 {rate * 100:.0f}% 达到闸门 {args.gate * 100:.0f}%——"
                  "这批任务足迹太缠，别硬并")
    else:
        print(_render_plan(tasks, waves))

    sys.exit(1 if gate_tripped else 0)


if __name__ == "__main__":
    main()
