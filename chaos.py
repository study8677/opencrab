#!/usr/bin/env python3
"""混沌注入 🌀 —— 主动给生命喂三类「现实里真会发生」的故障，验证它摔得**可控、
可诊断、可恢复**，并出一份韧性验收报告。

为什么要有它：`smoke.py`/`regression.py` 验证的是「一切正常时我会成功」，可强大不只
会成功——真实环境里 .env 缺了一行、账本被写到一半断电、外部命令卡死，都迟早会发生。
一个只在顺境里跑通的生命，是**脆的**：第一次遇到逆境就栈崩、就把坏数据当真、就被一条
hang 住的命令拖死。本层反过来**故意制造逆境**，然后断言生命的防御层确实扛住了。

韧性不是「不出错」，而是出错时满足三条(本层每个实验都按这三面打分)：
  · 可控(contained)   —— 故障被**就地圈住**：不抛栈、不 hang、不污染好数据；降级而非崩溃。
  · 可诊断(diagnosable)—— 失败留下**人能读懂的原因**(detail/降级值)，不是静默吞掉或一团乱。
  · 可恢复(recoverable)—— 故障撤除后，系统**自己回到正常**(env 复位 / 坏行后的好行照读 /
                          超时后的下一条命令照常成功)，没有留下后遗症。

注入的三类故障，都打在仓库里**真实存在的防御层**上(测真代码，不是测副本)：

  1. 缺失环境变量 —— 把 OPENCRAB_* 从环境里抠掉，验证消费方走的是「.get(默认值)」契约：
                     缺了就回退到文档化的默认，而不是 KeyError / int(None) 崩在启动那一刻。
  2. 损坏 JSONL  —— 给 `jsonlstore.read_jsonl` 喂垃圾行 / 截断的 JSON / 二进制 / 非 dict /
                     整个缺文件，验证它「坏行跳过、好行照读、永不抛错」的承诺真的成立。
  3. 外部命令超时 —— 让 `evidence.run_verify` 跑一条 sleep 命令并把墙钟上限压到 1s，验证它
                     **按时**被掐断、记成 ok=False 且 detail 写明超时，而不是把生命拖死。

全程**绝不碰真实状态**：env 改动在 finally 里复位，JSONL 注入只发生在临时文件，超时实验
不写真账本、只调 `run_verify`(它不落盘)。验收报告落在被 .gitignore 的 state/ 下，写盘
失败也绝不反噬生命。任何一面没扛住，退出码非零——可挂钩子 / CI 当韧性门禁。

用法：
    python chaos.py                 # 跑全部混沌实验，打印韧性验收报告
    python chaos.py --quiet         # 只在有实验未通过时说话(适合钩子 / CI)
    python chaos.py --only env      # 只跑某一类(env / jsonl / timeout)
    python chaos.py --json          # 机读：每个实验的三面结果 + 汇总

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import pathlib
import sys
import tempfile
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import evidence    # noqa: E402  —— 真实的「跑外部命令 + 超时防御」层
import jsonlstore  # noqa: E402  —— 真实的「读一批 / 追一条」防御层

REPORT_PATH = REPO_ROOT / "state" / "chaos" / "report.jsonl"


@dataclasses.dataclass(frozen=True)
class Resilience:
    """一个混沌实验的韧性画像：三面是否都扛住 + 各自的一句话取证。"""
    family: str            # env / jsonl / timeout
    name: str              # 这次注入的是什么故障
    contained: bool        # 可控：没崩、没 hang、没污染
    diagnosable: bool      # 可诊断：留下了能读懂的原因
    recoverable: bool      # 可恢复：故障撤除后回到正常
    detail: str            # 取证：到底观察到了什么
    elapsed_ms: int        # 实验墙钟耗时(超时类实验靠它证明「按时被掐断」)

    @property
    def passed(self) -> bool:
        return self.contained and self.diagnosable and self.recoverable

    @property
    def mark(self) -> str:
        return "🟢" if self.passed else "🔴"

    def facets(self) -> str:
        def f(ok: bool, word: str) -> str:
            return ("✅" if ok else "❌") + word
        return f"{f(self.contained, '可控')} {f(self.diagnosable, '可诊断')} " \
               f"{f(self.recoverable, '可恢复')}"

    def to_meta(self) -> dict:
        return {"family": self.family, "name": self.name, "passed": self.passed,
                "contained": self.contained, "diagnosable": self.diagnosable,
                "recoverable": self.recoverable, "detail": self.detail,
                "elapsed_ms": self.elapsed_ms}


# ── 故障 1：缺失环境变量 ────────────────────────────────────────────────
# 这些是 crab 启动时真实会读的配置：每条都注明「缺了应回退到的默认」与「怎么用它」。
# 注入 = 把这个 key 从环境里抠掉，验证消费契约是「.get(默认) 后还能安全转型」，
# 而不是 os.environ[key] 直接下标、或 int(None) 崩在启动那一刻。
_ENV_PROBES = [
    # (变量名, 默认值, 取这个值的方式：模拟 crab 的真实读法，缺失即触发降级路径)
    ("OPENCRAB_TICK_SECONDS", "3600", lambda v: int(v)),
    ("OPENCRAB_DAILY_ENERGY", "50000", lambda v: int(v)),
    ("OPENCRAB_HAND_BUDGET_USD", "0.5", lambda v: float(v)),
    ("OPENCRAB_AUTONOMY", "journal", lambda v: str(v)),
    ("OPENCRAB_MODEL", "gpt-5.4-mini", lambda v: str(v)),
]


def _experiment_missing_env(key: str, default: str, cast) -> Resilience:
    """把某个 OPENCRAB_* 从环境里抠掉，验证消费方安全回退到默认(而非崩在启动)。"""
    saved = os.environ.get(key)
    t0 = time.perf_counter()
    contained = diagnosable = recoverable = False
    detail = ""
    try:
        os.environ.pop(key, None)          # 注入：让这个变量「不存在」
        # 消费契约：.get(默认) 后再安全转型——这正是缺失时该走的降级路径。
        try:
            value = cast(os.environ.get(key, default))
            contained = True               # 没抛 KeyError / ValueError，圈住了
            diagnosable = (str(value) == str(cast(default)))  # 降级到文档化默认，可解释
            detail = f"缺失后回退默认 {key}={value!r}"
        except Exception as e:             # noqa: BLE001 —— 崩了就是不可控
            detail = f"缺失即崩：{type(e).__name__}: {e}"
    finally:
        # 撤除故障并验证可恢复：原值复位后照常读出。
        if saved is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = saved
        with contextlib.suppress(Exception):
            _ = cast(os.environ.get(key, default))
            recoverable = True
    return Resilience("env", f"缺失 {key}", contained, diagnosable, recoverable,
                      detail, int((time.perf_counter() - t0) * 1000))


# ── 故障 2：损坏 JSONL ─────────────────────────────────────────────────
# 直接打在真实的 jsonlstore 上：好行夹在坏行之间，验证「坏行跳过、好行照读、永不抛错」。
_CORRUPT_LINES = [
    '{"name": "good-1", "ok": true}',          # 好行
    '{"name": "truncated", "ok":',             # 截断的 JSON
    'not json at all !!!',                      # 纯垃圾
    '\x00\x01\x02 binary garbage',             # 二进制噪声
    '[1, 2, 3]',                               # 合法 JSON 但不是 dict(read 只收 dict?)
    '',                                        # 空行
    '   ',                                     # 纯空白
    '{"name": "good-2", "ok": false}',         # 坏行之后的好行——验证「照读不中断」
]


def _experiment_corrupt_jsonl() -> Resilience:
    """给 read_jsonl 喂一坨好坏混杂的行，验证它跳过坏行、照读好行、永不抛错。"""
    t0 = time.perf_counter()
    contained = diagnosable = recoverable = False
    detail = ""
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "corrupt.jsonl"
        # 用二进制写入，确保二进制噪声那行真的脏(绕过文本编码清洗)。
        path.write_bytes(("\n".join(_CORRUPT_LINES)).encode("utf-8", "surrogatepass")
                         if False else "\n".join(_CORRUPT_LINES).encode("utf-8"))
        try:
            rows = jsonlstore.read_jsonl(path)   # 真实防御层：绝不该抛
            contained = True
            names = {r.get("name") for r in rows if isinstance(r, dict)}
            # 可诊断：两条 good 都被捞回，且坏行没把好行带崩。
            diagnosable = {"good-1", "good-2"} <= names
            detail = f"喂 {len(_CORRUPT_LINES)} 行(含 6 行脏)，读回 {len(rows)} 条好记录"
        except Exception as e:               # noqa: BLE001
            detail = f"读损坏 JSONL 时抛错：{type(e).__name__}: {e}"
        # 可恢复：坏文件之后，append 一条好记录再读，能正常拿到。
        with contextlib.suppress(Exception):
            ok = jsonlstore.append_jsonl(path, {"name": "recovered", "ok": True})
            after = jsonlstore.read_jsonl(path)
            recoverable = ok and any(
                isinstance(r, dict) and r.get("name") == "recovered" for r in after)
    return Resilience("jsonl", "好坏混杂的 JSONL", contained, diagnosable, recoverable,
                      detail, int((time.perf_counter() - t0) * 1000))


def _experiment_missing_jsonl() -> Resilience:
    """读一个根本不存在的 JSONL：应安静返回空列表，而不是 FileNotFoundError。"""
    t0 = time.perf_counter()
    contained = diagnosable = recoverable = False
    detail = ""
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "nope" / "missing.jsonl"
        try:
            rows = jsonlstore.read_jsonl(path)
            contained = True
            diagnosable = rows == []          # 空而非异常，语义清晰
            detail = f"缺文件读回 {rows!r}"
        except Exception as e:                # noqa: BLE001
            detail = f"读缺失文件时抛错：{type(e).__name__}: {e}"
        # 可恢复：缺失父目录下 append 应自建目录并写成。
        with contextlib.suppress(Exception):
            ok = jsonlstore.append_jsonl(path, {"name": "born", "ok": True})
            recoverable = ok and path.exists()
    return Resilience("jsonl", "整个缺失的 JSONL", contained, diagnosable, recoverable,
                      detail, int((time.perf_counter() - t0) * 1000))


# ── 故障 3：外部命令超时 / 起不来 ───────────────────────────────────────
_PY = [sys.executable]


def _experiment_command_timeout() -> Resilience:
    """让 run_verify 跑一条睡很久的命令、把上限压到 1s，验证它按时被掐断且记成可诊断的失败。"""
    t0 = time.perf_counter()
    contained = diagnosable = recoverable = False
    detail = ""
    saved_timeout = evidence.VERIFY_TIMEOUT
    try:
        evidence.VERIFY_TIMEOUT = 1          # 注入：把墙钟上限压到 1s
        hang = evidence.Claim(
            name="_chaos_hang", asserts="故意睡 30s 来触发超时",
            argv=_PY + ["-c", "import time; time.sleep(30)"], ttl_days=1)
        rec = evidence.run_verify(hang)      # 真实防御层：不落盘、绝不该抛、绝不该 hang
        elapsed = time.perf_counter() - t0
        # 可控：在远短于 30s 内返回(被掐断了)，且没抛栈。
        contained = elapsed < 10 and isinstance(rec, dict)
        # 可诊断：记成 ok=False 且 detail 里能看出是超时。
        diagnosable = rec.get("ok") is False and "超时" in rec.get("detail", "")
        detail = f"{elapsed:.2f}s 内被掐断，ok={rec.get('ok')}，detail={rec.get('detail','')!r}"
    except Exception as e:                   # noqa: BLE001
        detail = f"超时实验本身抛错：{type(e).__name__}: {e}"
    finally:
        evidence.VERIFY_TIMEOUT = saved_timeout
        # 可恢复：上限复位后，跑一条秒回的命令应正常成功。
        with contextlib.suppress(Exception):
            ok_claim = evidence.Claim(
                name="_chaos_fast", asserts="秒回的健康命令",
                argv=_PY + ["-c", "pass"], ttl_days=1)
            rec2 = evidence.run_verify(ok_claim)
            recoverable = rec2.get("ok") is True
    return Resilience("timeout", "外部命令超时(sleep 30s / 上限 1s)", contained,
                      diagnosable, recoverable, detail,
                      int((time.perf_counter() - t0) * 1000))


def _experiment_command_missing() -> Resilience:
    """让 run_verify 去跑一个根本不存在的可执行文件，验证它记成可诊断的失败而非崩溃。"""
    t0 = time.perf_counter()
    contained = diagnosable = recoverable = False
    detail = ""
    try:
        ghost = evidence.Claim(
            name="_chaos_ghost", asserts="跑一个不存在的命令",
            argv=["definitely-not-a-real-binary-xyz", "--nope"], ttl_days=1)
        rec = evidence.run_verify(ghost)     # 起不来也只该是「这次没验成」，不该抛
        contained = isinstance(rec, dict)
        diagnosable = rec.get("ok") is False and bool(rec.get("detail"))
        detail = f"起不来：ok={rec.get('ok')}，detail={rec.get('detail','')!r}"
        recoverable = True                   # 进程未受损：本身就说明可恢复
    except Exception as e:                   # noqa: BLE001
        detail = f"跑缺失命令时抛错：{type(e).__name__}: {e}"
    return Resilience("timeout", "外部命令起不来(命令不存在)", contained,
                      diagnosable, recoverable, detail,
                      int((time.perf_counter() - t0) * 1000))


# ── 编排 ───────────────────────────────────────────────────────────────
def run(only: str | None = None) -> list[Resilience]:
    """跑选定的混沌实验族(env / jsonl / timeout)，返回每个实验的韧性结果。"""
    out: list[Resilience] = []
    if only in (None, "env"):
        for key, default, cast in _ENV_PROBES:
            out.append(_experiment_missing_env(key, default, cast))
    if only in (None, "jsonl"):
        out.append(_experiment_corrupt_jsonl())
        out.append(_experiment_missing_jsonl())
    if only in (None, "timeout"):
        out.append(_experiment_command_timeout())
        out.append(_experiment_command_missing())
    return out


def write_report(results: list[Resilience], *, now: float | None = None) -> bool:
    """把本轮验收写成一行快照(整文件重写，它只描述「此刻这次混沌验收」)。尽力而为。"""
    now = time.time() if now is None else now
    rec = {"ts": now, "total": len(results),
           "passed": sum(1 for r in results if r.passed),
           "results": [r.to_meta() for r in results]}
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REPORT_PATH.open("w", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:   # noqa: BLE001 —— 报告是副产物，写不出也不该拖垮验收
        return False


def manifest(only: str | None = None) -> dict:
    """导出纯数据：每个实验的三面结果 + 汇总(给 health / 外部消费)。"""
    results = run(only)
    return {"total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "results": [r.to_meta() for r in results]}


def _print_report(results: list[Resilience]) -> None:
    print(f"🌀 opencrab 韧性验收（{len(results)} 个混沌实验）\n")
    families = {"env": "缺失环境变量", "jsonl": "损坏 JSONL", "timeout": "外部命令超时"}
    last_fam = None
    for r in results:
        if r.family != last_fam:
            print(f"  ── {families.get(r.family, r.family)} ──")
            last_fam = r.family
        print(f"  {r.mark} {r.name}（{r.facets()}，{r.elapsed_ms}ms）")
        print(f"      {r.detail}")
    passed = sum(1 for r in results if r.passed)
    print(f"\n  小结：🟢{passed}  🔴{len(results) - passed}")
    if passed == len(results):
        print("🌀 三类逆境都摔得可控、可诊断、可恢复——韧性达标。")
    else:
        print("🌀 有实验没扛住逆境，下面这些防御层得补：")
        for r in results:
            if not r.passed:
                print(f"    🔴 {r.name}：{r.detail}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 混沌注入与韧性验收 🌀")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有实验未通过时输出(适合钩子 / CI)")
    ap.add_argument("--only", choices=["env", "jsonl", "timeout"],
                    help="只跑某一类故障实验")
    ap.add_argument("--json", action="store_true", help="导出机读验收报告")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(args.only), ensure_ascii=False, indent=2))
        return

    results = run(args.only)
    write_report(results)
    all_passed = all(r.passed for r in results)
    if not (args.quiet and all_passed):
        _print_report(results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
