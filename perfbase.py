#!/usr/bin/env python3
"""命令级性能基线与回归告警 ⏱️🚨 —— 看「变强了，是不是也悄悄变慢了」。

为什么要有它：checkup 看「器官还在不在」，goldens 看「行为有没有变味」，
但还有一条防线没人守——**性能退化**。功能越加越多，核心命令可能在不知不觉
里越跑越慢、越吃越多内存。这只螃蟹得能感知到这种「慢性变胖」。

它做的事：跑一组核心命令，量出每条的**耗时 / 峰值内存 / 退出码**，和本机
历史基线逐条对比；谁比基线慢得超过阈值，就判为回归——既写进审计(state/audit)
留痕，也在结果里明确提示，让人/螃蟹自己决定是优化还是重新 bless 基线。

怎么不误报：
- 耗时取多次采样的**最小值**(min)——最小值最接近「纯计算成本」,受调度抖动最小。
- 双重门槛:既要慢过 `threshold_pct`(百分比),又要慢过 `min_delta_ms`(绝对毫秒)
  才告警——挡住「几十毫秒的小命令在百分比上疯狂跳变」这类假阳性。
- 退出码变化(尤其 0→非0)单独判为回归——命令跑挂了比慢更严重。

基线是**本机资产**,不进仓库:性能强烈依赖机器(CPU/磁盘/负载),跨机器比对
没有意义。基线落在被 .gitignore 的 state/perf/baseline.json,每台机器各自校准。

内存为尽力而为:用标准库 resource(RUSAGE_CHILDREN.ru_maxrss)估子进程峰值,
仅 POSIX 可用、且因系统语义只能取「最大的那个子进程」,故标注为近似值。
耗时与退出码才是强信号。零第三方依赖,纯标准库。

用法:
    python perfbase.py             # 采样并与基线比对,报告回归(退出码 0=无回归 / 1=有回归)
    python perfbase.py --update    # 确认当前性能可接受后,(重新)录制基线
    python perfbase.py --list      # 只列出有哪些被测命令
    python perfbase.py --repeat N  # 每条命令采样 N 次取最小(默认 3)
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import pathlib
import subprocess
import sys
import time

try:
    import resource   # POSIX only;缺了就降级为「不量内存」
except ImportError:    # pragma: no cover - Windows 等无 resource
    resource = None

REPO_ROOT = pathlib.Path(__file__).resolve().parent
PERF_DIR = REPO_ROOT / "state" / "perf"        # 落在被 .gitignore 的 state/ 里
BASELINE_PATH = PERF_DIR / "baseline.json"

# 默认阈值:慢过基线 25% 且 绝对增量超过 80ms 才告警(双重门槛,挡抖动)
DEFAULT_THRESHOLD_PCT = 25.0
DEFAULT_MIN_DELTA_MS = 80.0
DEFAULT_REPEAT = 3

_PY = sys.executable

# 录制/采样时强制的环境:让耗时只取决于代码本身,不被本机 .env / 白名单 / 真打大脑干扰
_STABLE_ENV = {
    "OPENCRAB_CAPABILITIES": "",   # 空 -> 默认能力集
    "OPENCRAB_API_KEY": "",        # 空 -> 梦境模式,绝不在采样时真打大脑
    "PYTHONIOENCODING": "utf-8",
}


@dataclasses.dataclass
class Bench:
    """一条被测命令:跑什么、是给人看的可读名。"""
    name: str
    argv: list[str]            # 在仓库根下执行的命令(含解释器)
    summary: str


# 核心命令:启动/能力清单/自检/单跑能力——这些是日常最常走的路径,最值得守住速度。
BENCHES = [
    Bench("crab-help", [_PY, "crab.py", "--help"],
          "crab.py 启动与参数解析的基础开销"),
    Bench("crab-caps", [_PY, "crab.py", "caps"],
          "能力发现+清单渲染(能力越加越多,这里最先变慢)"),
    Bench("checkup", [_PY, "checkup.py", "--quiet"],
          "整套健康自检的耗时"),
    Bench("cap-snapshot", [_PY, "crab.py", "cap", "snapshot"],
          "单跑 snapshot 能力(扫仓库,规模越大越慢)"),
]


def _maxrss_kb() -> float | None:
    """读当前已回收子进程的峰值 RSS(KB);无 resource 则 None。

    注意系统语义:RUSAGE_CHILDREN.ru_maxrss 是「最大的那个子进程」的峰值,
    且单位随平台不同(Linux=KB, macOS=字节),这里统一归一到 KB。
    """
    if resource is None:
        return None
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    if rss <= 0:
        return None
    # macOS 上 ru_maxrss 是字节,Linux 上是 KB——按平台归一到 KB
    return rss / 1024.0 if sys.platform == "darwin" else float(rss)


def _measure_once(bench: Bench) -> dict:
    """跑一次,返回 {duration_ms, exit, mem_kb}(mem 为近似/可能 None)。"""
    env = {**os.environ, **_STABLE_ENV}
    mem_before = _maxrss_kb()
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(bench.argv, cwd=str(REPO_ROOT), env=env,
                              capture_output=True, text=True, timeout=120)
        exit_code = proc.returncode
    except Exception:     # 起不来/超时也是一种「性能」——记为失败退出码
        exit_code = -1
    duration_ms = (time.perf_counter() - t0) * 1000.0
    mem_after = _maxrss_kb()
    mem_kb = None
    if mem_before is not None and mem_after is not None:
        delta = mem_after - mem_before
        mem_kb = delta if delta > 0 else None    # 因 maxrss 是单调最大值,只在抬升时记
    return {"duration_ms": duration_ms, "exit": exit_code, "mem_kb": mem_kb}


def sample(bench: Bench, repeat: int = DEFAULT_REPEAT) -> dict:
    """对一条命令采样 repeat 次,取最小耗时(最接近纯计算成本)。"""
    runs = [_measure_once(bench) for _ in range(max(1, repeat))]
    best = min(runs, key=lambda r: r["duration_ms"])
    mems = [r["mem_kb"] for r in runs if r["mem_kb"] is not None]
    return {
        "duration_ms": round(best["duration_ms"], 1),
        "exit": best["exit"],
        "mem_kb": round(max(mems), 1) if mems else None,
        "repeat": len(runs),
    }


def _load_baseline() -> dict:
    """读本机基线;不存在或坏了都退化成空 dict(视作未录)。"""
    if not BASELINE_PATH.exists():
        return {}
    try:
        return json.loads(BASELINE_PATH.read_text("utf-8"))
    except Exception:
        return {}


def update(repeat: int = DEFAULT_REPEAT) -> dict:
    """(重新)录制所有命令为本机基线,返回写入的基线数据。"""
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    samples = {b.name: sample(b, repeat) for b in BENCHES}
    data = {
        "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "platform": sys.platform,
        "repeat": repeat,
        "benches": samples,
    }
    BASELINE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return data


@dataclasses.dataclass
class Verdict:
    """一次性能比对的结论。"""
    ok: bool
    total: int
    measured: dict              # name -> 本次采样
    baseline: dict              # name -> 基线采样
    regressed: list[dict]       # 每条:{name, kind, baseline_ms, current_ms, delta_pct, ...}
    missing: list[str]          # 还没录过基线的命令
    has_baseline: bool


def verify(repeat: int = DEFAULT_REPEAT,
           threshold_pct: float = DEFAULT_THRESHOLD_PCT,
           min_delta_ms: float = DEFAULT_MIN_DELTA_MS) -> Verdict:
    """采样当前性能并与本机基线逐条比对,给出回归结论(不改基线)。"""
    base = _load_baseline()
    base_benches = base.get("benches", {})
    has_baseline = bool(base_benches)

    measured: dict[str, dict] = {}
    regressed: list[dict] = []
    missing: list[str] = []

    for bench in BENCHES:
        cur = sample(bench, repeat)
        measured[bench.name] = cur
        b = base_benches.get(bench.name)
        if not has_baseline or b is None:
            missing.append(bench.name)
            continue
        base_ms = float(b.get("duration_ms", 0) or 0)
        cur_ms = cur["duration_ms"]
        # 1) 退出码回归:命令跑挂了,比慢更严重
        if b.get("exit") == 0 and cur["exit"] != 0:
            regressed.append({
                "name": bench.name, "kind": "exit",
                "baseline_exit": b.get("exit"), "current_exit": cur["exit"],
                "baseline_ms": base_ms, "current_ms": cur_ms, "delta_pct": None,
            })
            continue
        # 2) 耗时回归:双重门槛——百分比 + 绝对毫秒,都超才告警
        if base_ms > 0:
            delta_ms = cur_ms - base_ms
            delta_pct = delta_ms / base_ms * 100.0
            if delta_pct > threshold_pct and delta_ms > min_delta_ms:
                regressed.append({
                    "name": bench.name, "kind": "slower",
                    "baseline_ms": base_ms, "current_ms": cur_ms,
                    "delta_ms": round(delta_ms, 1),
                    "delta_pct": round(delta_pct, 1),
                })

    ok = has_baseline and not regressed and not missing
    return Verdict(ok=ok, total=len(BENCHES), measured=measured,
                   baseline=base_benches, regressed=regressed,
                   missing=missing, has_baseline=has_baseline)


def _audit():
    """惰性导入仓库根的 audit 模块(和能力里一样的接法)。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import audit
    return audit


def audit_verdict(v: Verdict) -> None:
    """把本次比对留痕到审计:每条采样一条 perf_sample,每条回归一条 perf_regression。

    审计是观测者,绝不反噬——任何异常都吞掉,不让留痕本身弄死调用方。
    """
    try:
        audit = _audit()
        for name, m in v.measured.items():
            audit.record("perf_sample", bench=name, duration_ms=m["duration_ms"],
                         exit=m["exit"], mem_kb=m["mem_kb"], repeat=m.get("repeat"))
        for r in v.regressed:
            audit.record("perf_regression", **r)
    except Exception:
        pass


def _fmt_ms(ms: float | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def main() -> None:
    ap = argparse.ArgumentParser(description="opencrab 命令级性能基线与回归告警 ⏱️🚨")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--update", action="store_true",
                   help="确认当前性能可接受后,(重新)录制本机基线")
    g.add_argument("--list", action="store_true", help="只列出有哪些被测命令")
    ap.add_argument("--repeat", type=int, default=DEFAULT_REPEAT,
                    help=f"每条命令采样次数,取最小(默认 {DEFAULT_REPEAT})")
    ap.add_argument("--threshold-pct", type=float, default=DEFAULT_THRESHOLD_PCT,
                    help=f"耗时慢过基线多少%%才告警(默认 {DEFAULT_THRESHOLD_PCT})")
    args = ap.parse_args()

    if args.list:
        print("⏱️  被测命令:")
        base = _load_baseline().get("benches", {})
        for b in BENCHES:
            tag = "已录" if b.name in base else "未录"
            base_ms = _fmt_ms(base.get(b.name, {}).get("duration_ms")) if b.name in base else "—"
            print(f"  [{tag}] {b.name}（基线 {base_ms}）— {b.summary}")
        return

    if args.update:
        data = update(args.repeat)
        print(f"⏱️  已录制 {len(data['benches'])} 条本机性能基线 → "
              f"{BASELINE_PATH.relative_to(REPO_ROOT)}（平台 {data['platform']}）")
        for name, s in data["benches"].items():
            print(f"     {name}: {_fmt_ms(s['duration_ms'])}"
                  + (f" · {s['mem_kb']:.0f}KB" if s["mem_kb"] else ""))
        print("   基线是本机资产,不进仓库——换机器请重新 --update。")
        return

    v = verify(args.repeat, args.threshold_pct)
    audit_verdict(v)

    print("⏱️  opencrab 命令级性能比对\n")
    if not v.has_baseline:
        print("  ⚪ 本机还没有性能基线——先跑 python perfbase.py --update 校准。\n")
        sys.exit(1)

    for b in BENCHES:
        m = v.measured.get(b.name, {})
        base_ms = v.baseline.get(b.name, {}).get("duration_ms")
        reg = next((r for r in v.regressed if r["name"] == b.name), None)
        if b.name in v.missing:
            print(f"  ⚪ {b.name} — 未录基线（本次 {_fmt_ms(m.get('duration_ms'))}）")
        elif reg and reg["kind"] == "exit":
            print(f"  ❌ {b.name} — 退出码回归 {reg['baseline_exit']}→{reg['current_exit']}")
        elif reg:
            print(f"  ❌ {b.name} — 变慢 {reg['delta_pct']}%："
                  f"{_fmt_ms(reg['baseline_ms'])} → {_fmt_ms(reg['current_ms'])}")
        else:
            print(f"  ✅ {b.name} — {_fmt_ms(base_ms)} → {_fmt_ms(m.get('duration_ms'))}")
    print()

    if v.ok:
        print(f"🦀 无性能回归：{v.total} 条命令均未慢过基线。")
        sys.exit(0)
    parts = []
    if v.regressed:
        parts.append(f"{len(v.regressed)} 条回归")
    if v.missing:
        parts.append(f"{len(v.missing)} 条未录基线")
    print(f"⚠️  {'、'.join(parts)}——若是有意为之(如换了机器/接受了新成本),"
          f"确认后 python perfbase.py --update 重录基线。回归已写入审计(state/audit)。")
    sys.exit(1)


if __name__ == "__main__":
    main()
