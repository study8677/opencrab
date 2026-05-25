#!/usr/bin/env python3
"""兼容性守门层 🔌 —— 给每条命令的 `--json` 输出留一份「形状样本」，变更前先抓 schema 破坏。

会用 opencrab 的人越多，**稳定的接口比新增的本事更值钱**。每条命令的机读输出
(`--json`)就是一份对外契约：下游脚本、CI、别的工具都照着它的字段取值。可这层契约
过去只活在「这次输出长这样」的默契里——某天自改顺手把一个键改名、把 `str` 改成 `list`、
或干脆删掉一个字段，单测照样全绿,等下游崩了才知道接口被悄悄掀了。

`regression.py` 比的是**逐字节的黄金输出**(连那句话都不许变)，`contracts.py` 钉的是
**函数级**的输入输出承诺。本层补的是中间那一格:**命令级 `--json` 输出的结构**——
不管字段里装的是哪天的数据，只看**形状**(有哪些键、各是什么类型、嵌套成什么样)。
形状把易变的值抽掉、只留下接口骨架,于是它能稳稳地回答一个问题:

  **「我这次自改,把哪条命令的对外 schema 弄破了?」**

它做三件事,全程只读、只动自己那份基线文件:

  · 取形(shape)    —— 跑一条命令的 `--json`,把输出递归抽成「键→类型」的骨架。
  · 比对(check)    —— 拿当下骨架对照基线,把差异分成两档:
                      **破坏 💥**(删键 / 改类型 / 容器变种)——下游会当场崩;
                      **新增 ➕**(多了个键)——向后兼容,放行但记一笔。
  · 立基(update)   —— 确认当前输出正确后,把骨架录成新基线(state/compat.json)。

判据故意保守,只在「真会让既有调用方取不到、取错」时报破坏:
  - 删掉一个基线里有的键        → 💥(老调用方 KeyError)
  - 某键的类型从 A 变成 B       → 💥(老调用方拿到意外类型)
  - 标量 ↔ 容器(对象/数组)互换 → 💥
  - 多出一个新键                → ➕(老调用方不取它,不受影响)
  - 基线或当下是 null           → 放行(可空字段,值缺席不算破坏)

用法:
    python compat.py                 # 对照基线,跑全部样本命令,报破坏/新增
    python compat.py --quiet         # 只在有「破坏」时说话(适合钩子 / CI)
    python compat.py --list          # 只列登记在册的样本命令
    python compat.py --update        # 确认输出正确后,(重新)录制全部基线
    python compat.py <name> ...      # 只盯某几条命令(按登记名过滤)
    python compat.py --json          # 机读:导出本次比对结论

退出码:0 = 无 schema 破坏(可含向后兼容的新增);1 = 至少一条命令的对外 schema 被破坏。
零第三方依赖,纯标准库。比对全程只读命令输出,只写自己的基线,绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BASELINE = REPO_ROOT / "state" / "compat.json"


# ── 样本命令:登记在册、该钉死对外 schema 的那些 `--json` 出口 ──────────
# 只收「输出结构稳定、不依赖外部状态、跑起来无副作用」的命令——这样形状才是接口骨架,
# 而非某天数据的快照。argv 不含 python/脚本名,只写传给该模块的参数(必带 --json)。
@dataclasses.dataclass(frozen=True)
class Sample:
    """一条登记在册的样本命令:它的对外 `--json` 输出形状,是要守住的接口。"""
    name: str          # 登记名(= 模块名,作过滤与基线键)
    argv: list[str]    # 传给 `python <name>.py` 的参数(必含 --json)
    note: str          # 一句话:这条命令对外吐的是什么

    def cmd(self) -> list[str]:
        return [sys.executable, str(REPO_ROOT / f"{self.name}.py"), *self.argv]


SAMPLES: list[Sample] = [
    Sample("contracts", ["--json"], "各底座模块的契约清单"),
    Sample("playbook", ["--json"], "所有剧本的元数据清单"),
    Sample("route", ["--json", "想给领地加一块新能力"], "一次路由选向的结论"),
    Sample("lexicon", ["--json"], "能力命名词典(归一后的技能表)"),
    Sample("skillgraph", ["--json"], "技能依赖图的节点与边"),
]


# ── 取形:把一份 JSON 值递归抽成「键→类型」的接口骨架 ────────────────
def shape(value) -> object:
    """把任意 JSON 值抽成只剩结构的骨架:值被抹掉,只留类型与嵌套形状。

    标量 → 类型名字符串;对象 → {键: 子形状}(键排序);数组 → [元素形状的并]。
    空数组 → [](元素形状未知,比对时放行)。
    """
    if value is None:
        return "null"
    if isinstance(value, bool):           # 必须在 int 之前判:bool 是 int 的子类
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return {k: shape(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        merged = None
        for item in value:
            merged = _merge(merged, shape(item))
        return [] if merged is None else [merged]
    return "str"   # 兜底:不该出现的类型当字符串处理


def _merge(a, b):
    """合并同一数组里不同元素的形状:对象并键、数组并元素,矛盾则保留以便比对发现。"""
    if a is None:
        return b
    if b is None:
        return a
    if a == b:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge(a.get(k), v) if k in a else v
        return out
    if isinstance(a, list) and isinstance(b, list):
        inner = None
        for lst in (a, b):
            if lst:
                inner = _merge(inner, lst[0])
        return [] if inner is None else [inner]
    if a == "null":
        return b
    if b == "null":
        return a
    return a   # 标量类型不一,保留先见到的;真正的不一致留给逐命令基线去抓


# ── 比对:拿当下骨架对照基线,把差异分成「破坏」与「新增」 ────────────
def diff(base, cur, path: str = "") -> list[dict]:
    """递归比对基线骨架与当下骨架,返回差异列表。

    每条差异:{path, kind: 'break'|'add', detail}。判据保守,只在真会让既有调用方
    取不到/取错时判 break;向后兼容的多出键判 add;null 一侧放行(可空字段)。
    """
    out: list[dict] = []
    if base == "null" or cur == "null":
        return out                              # 可空字段:值缺席不算破坏
    bd, cd = isinstance(base, dict), isinstance(cur, dict)
    bl, cl = isinstance(base, list), isinstance(cur, list)
    if bd and cd:
        for k in base:
            sub = f"{path}.{k}" if path else k
            if k not in cur:
                out.append({"path": sub, "kind": "break", "detail": "删掉了基线里的键"})
            else:
                out.extend(diff(base[k], cur[k], sub))
        for k in cur:
            if k not in base:
                sub = f"{path}.{k}" if path else k
                out.append({"path": sub, "kind": "add", "detail": "新增了键(向后兼容)"})
        return out
    if bl and cl:
        if base and cur:                        # 两边都非空才比元素形状
            out.extend(diff(base[0], cur[0], f"{path}[]"))
        return out
    if base != cur:
        out.append({"path": path or "<root>", "kind": "break",
                    "detail": f"类型/结构变了:{_kind(base)} → {_kind(cur)}"})
    return out


def _kind(s) -> str:
    if isinstance(s, dict):
        return "对象{}"
    if isinstance(s, list):
        return "数组[]"
    return str(s)


# ── 跑样本 & 比对 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Result:
    """一条样本命令的本次比对结论。"""
    name: str
    status: str            # ok / broken / added / new / error
    changes: list[dict]    # diff 出的差异(error 时为空)
    error: str = ""        # 跑命令/解析失败的原因

    @property
    def breaks(self) -> list[dict]:
        return [c for c in self.changes if c["kind"] == "break"]

    @property
    def adds(self) -> list[dict]:
        return [c for c in self.changes if c["kind"] == "add"]


def _capture_shape(s: Sample) -> tuple[object, str]:
    """跑一条样本命令,把它的 stdout 解析成 JSON 再抽成骨架。失败回 (None, 原因)。"""
    try:
        proc = subprocess.run(s.cmd(), capture_output=True, text=True,
                              cwd=str(REPO_ROOT), timeout=60)
    except Exception as e:
        return None, f"命令跑不起来:{type(e).__name__}: {e}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        return None, f"命令退出码 {proc.returncode}:{tail[0]}"
    try:
        data = json.loads(proc.stdout)
    except Exception as e:
        return None, f"输出不是合法 JSON:{type(e).__name__}: {e}"
    return shape(data), ""


def _load_baseline() -> dict:
    if not BASELINE.exists():
        return {}
    try:
        return json.loads(BASELINE.read_text("utf-8"))
    except Exception:
        return {}


def _save_baseline(data: dict) -> bool:
    try:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        return True
    except Exception:
        return False


def check(samples: list[Sample]) -> list[Result]:
    """对照基线比对每条样本命令的当下输出形状。"""
    base = _load_baseline()
    results: list[Result] = []
    for s in samples:
        cur, err = _capture_shape(s)
        if err:
            results.append(Result(s.name, "error", [], err))
            continue
        if s.name not in base:
            results.append(Result(s.name, "new", []))    # 还没立过基线
            continue
        changes = diff(base[s.name]["shape"], cur)
        if any(c["kind"] == "break" for c in changes):
            status = "broken"
        elif changes:
            status = "added"
        else:
            status = "ok"
        results.append(Result(s.name, status, changes))
    return results


def update(samples: list[Sample]) -> tuple[dict, list[Result]]:
    """把当前输出形状录成基线;跑不起来的命令保留旧基线并如实标 error。"""
    base = _load_baseline()
    results: list[Result] = []
    for s in samples:
        cur, err = _capture_shape(s)
        if err:
            results.append(Result(s.name, "error", [], err))
            continue
        base[s.name] = {"argv": s.argv, "note": s.note,
                        "shape": cur, "recorded": _now()}
        results.append(Result(s.name, "ok", []))
    return base, results


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def summarize(results: list[Result]) -> tuple[bool, int, int]:
    """归一化:是否无破坏、破坏几条命令、出错几条命令。"""
    broken = sum(1 for r in results if r.status == "broken")
    errored = sum(1 for r in results if r.status == "error")
    return (broken == 0, broken, errored)


# ── 打印 ─────────────────────────────────────────────────────────────
_GLYPH = {"ok": "✅", "added": "➕", "broken": "💥", "new": "🆕", "error": "⚠️"}
_WORD = {"ok": "稳", "added": "新增(兼容)", "broken": "schema 破坏",
         "new": "未立基线", "error": "跑不通"}


def _print_results(results: list[Result]) -> None:
    print(f"🔌 命令对外 schema 比对（{len(results)} 条样本）\n")
    for r in results:
        print(f"  {_GLYPH[r.status]} {r.name} — {_WORD[r.status]}")
        if r.status == "error":
            print(f"      {r.error}")
        for c in r.breaks:
            print(f"      💥 {c['path']}:{c['detail']}")
        for c in r.adds:
            print(f"      ➕ {c['path']}:{c['detail']}")
        if r.status == "new":
            print("      还没立过基线 —— 确认输出正确后跑 --update 录一份。")
    print()


def to_meta(results: list[Result]) -> dict:
    healthy, broken, errored = summarize(results)
    return {
        "healthy": healthy,
        "broken": broken,
        "errored": errored,
        "results": [{"name": r.name, "status": r.status,
                     "changes": r.changes, "error": r.error} for r in results],
    }


def _select(names: list[str]) -> list[Sample]:
    if not names:
        return SAMPLES
    by_name = {s.name: s for s in SAMPLES}
    picked = [by_name[n] for n in names if n in by_name]
    unknown = [n for n in names if n not in by_name]
    if unknown:
        print(f"🔌 不认识的样本名:{', '.join(unknown)}", file=sys.stderr)
        print(f"   在册的:{', '.join(s.name for s in SAMPLES)}", file=sys.stderr)
    return picked


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="opencrab 命令兼容性守门层 🔌")
    ap.add_argument("names", nargs="*", help="只盯某几条样本命令(按登记名过滤)")
    ap.add_argument("--list", action="store_true", help="只列登记在册的样本命令")
    ap.add_argument("--update", action="store_true",
                    help="确认输出正确后,(重新)录制基线")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有 schema 破坏时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="机读:导出本次比对结论")
    args = ap.parse_args(argv)

    if args.list:
        if args.json:
            print(json.dumps([{"name": s.name, "argv": s.argv, "note": s.note}
                              for s in SAMPLES], ensure_ascii=False, indent=2))
        else:
            print(f"🔌 在册样本命令（{len(SAMPLES)} 条）:\n")
            for s in SAMPLES:
                print(f"  · {s.name} {' '.join(s.argv)}")
                print(f"      {s.note}")
            print()
        return 0

    samples = _select(args.names)
    if not samples:
        return 0

    if args.update:
        base, results = update(samples)
        ok = _save_baseline(base)
        if args.json:
            print(json.dumps({"saved": ok, "results": to_meta(results)["results"]},
                             ensure_ascii=False, indent=2))
        else:
            good = [r for r in results if r.status == "ok"]
            print(f"🔌 已录基线:{len(good)} 条样本的对外 schema 写入 {BASELINE.name}")
            for r in results:
                if r.status == "error":
                    print(f"  ⚠️ {r.name} 跑不通,保留旧基线:{r.error}")
            if not ok:
                print("  ⚠️ 基线落盘失败(权限/磁盘?)——这次没存住。")
        return 0 if ok else 1

    results = check(samples)
    healthy, broken, errored = summarize(results)

    if args.json:
        print(json.dumps(to_meta(results), ensure_ascii=False, indent=2))
        return 0 if healthy else 1

    if not (args.quiet and healthy):
        _print_results(results)

    if healthy:
        if not args.quiet:
            extra = " (有向后兼容的新增)" if any(r.status == "added" for r in results) else ""
            print(f"🔌 对外 schema 稳住了{extra}。")
            if errored:
                print(f"   另有 {errored} 条样本跑不通,没比成——先让它们能出 JSON。")
    else:
        print(f"💥 有 {broken} 条命令的对外 schema 被破坏,先把接口改回兼容再蜕壳。")
        print("   (确属有意的破坏式变更,再跑 --update 立新基线,并告知下游。)")
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
