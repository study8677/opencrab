#!/usr/bin/env python3
"""能力消融台 🔬 —— 把一样本事「禁掉/换掉」再跑一遍同一套任务，用验收、耗时、失败率
三把尺对照，逼出一句话：这个器官**真有用**，还是只是越长越臃肿的一块赘肉。

为什么要有它：这只螃蟹每天给自己添一个模块，壳越来越厚。`skillgraph` 答「我会什么」、
`lifecycle` 管「本事从生到死的节律」、`evalbench` 量「我整体有没有变强」——可它们都答不了
一个最扎心的问题：**单独拎出某一样本事，它到底贡献了什么？** 不验证这个，添模块就成了
只进不出的囤积：每样东西都「看起来有用」，谁也不敢删，壳一年厚过一年，却没人能指着
其中一块说清「拿掉它，我会差在哪」。

消融是实验科学里最朴素也最诚实的一招：想知道一个器官有没有用，就把它**摘掉**，看整体
垮不垮。本层把这招钉成一次可记账的对照实验——同一套任务，跑两遍:

  · 🟢 baseline(基线)  —— 这样本事**在场**时的表现。
  · 🔪 ablated(消融)   —— 把它**禁掉或换成平替**后，其余不变，再跑一遍同一套任务。

两遍各量三把尺(都按每任务归一，便于跨实验比较):

  · ✅ 验收率(acceptance) —— 通过验收的任务占比。摘掉它，事还做得成吗？
  · ⏱️ 平均耗时(seconds)  —— 每任务平均花多久。它是省了时间，还是只是徒增开销？
  · 💥 失败率(failure)    —— 崩溃/报错的任务占比。摘掉它，是不是更容易翻车？

**对照的硬闸**(和 lifecycle 退役证据闸门同一种洁癖)：两遍必须**跑同一套任务**
(任务数相等且 > 0)，否则是拿苹果比橘子，结论一律判**证据不足**(inconclusive)，
绝不让一次跑歪的实验冒充「有用/没用」的判决。任务数太少(< MIN_TASKS)也判证据不足——
一两个样本上的差异是噪声，不配给一个器官定生死。

闸门过了，才给裁决。核心是「摘掉它，整体垮多少」——取**验收掉的幅度**与**失败涨的幅度**
里更狠的那个当伤害值(harm)：

  · 🟢 essential(要害)  —— 摘掉它，验收明显掉或失败明显涨(harm ≥ 要害线)。它在兜真活，留。
  · 🟡 marginal(边际)   —— 摘掉它只有微小变化(harm 在边际线与要害线之间)。功过不明，再攒证据。
  · 🔴 bloat(赘肉)      —— 摘掉它，验收/失败几乎纹丝不动(harm < 边际线)。它没在兜活;
                          若消融后**还更快**,那是双重退役信号——这块壳该考虑卸了(见 lifecycle)。

这正是「证明每个器官真有用，而不是越长越臃肿」的硬约束:一样本事想留在壳上，得拿得出
「摘了我你会差在哪」的对照证据;拿不出,它就是赘肉,该走 deprecated→retired 那条路。

ablation 只**定义对照、守住闸门、记账、下裁决**:
  · 一次实验 = 一个能力 + baseline/ablated 两条 RunResult，verdict() 据三尺对照出裁决;
  · check_pair() 把对照的红线一次说清(同套任务、任务数足够);
  · 实验记进 `state/ablation.jsonl`(一行一次实验，append-only)，--status 折叠成
    「每样本事最近一次消融判成了啥」,--bloat 单列出所有被判赘肉的、该考虑卸壳的器官。
它不替你跑任何任务、不替你禁用任何模块——你把两遍的实测数喂进来,它只负责诚实地对照。

用法:
    python ablation.py                   # 自检:对照闸门 + 三尺裁决
    python ablation.py --demo            # 演示三种结局(要害/边际/赘肉)各一例
    python ablation.py --status          # 读账本,列每样本事最近一次消融裁决
    python ablation.py --bloat           # 只列被判赘肉、该考虑卸壳的器官(欠的债)
    python ablation.py --json            # 机读:导出当前各能力最近裁决
    python ablation.py --quiet           # 只在自检不过时说话(适合钩子 / CI)

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
LEDGER = REPO_ROOT / "state" / "ablation.jsonl"

# ── 三种裁决:一样本事摘掉后,整体垮不垮 ──────────────────────────────────
ESSENTIAL = "essential"     # 🟢 要害:摘了明显变差,在兜真活
MARGINAL = "marginal"       # 🟡 边际:摘了只有微小变化,功过不明
BLOAT = "bloat"             # 🔴 赘肉:摘了几乎纹丝不动,该考虑卸壳
INCONCLUSIVE = "inconclusive"  # ⬜ 证据不足:对照不成立,不配下判决

_EMOJI = {ESSENTIAL: "🟢", MARGINAL: "🟡", BLOAT: "🔴", INCONCLUSIVE: "⬜"}

# 裁决阈值(以「每任务归一」的比率为单位,跨实验可比):
MIN_TASKS = 5          # 少于这么多任务,差异是噪声,不配定生死
MARGINAL_THRESHOLD = 0.03   # harm 低于此 → 赘肉(摘了纹丝不动)
ESSENTIAL_THRESHOLD = 0.15  # harm 高于此 → 要害(摘了明显垮)


def _now() -> str:
    """统一的 UTC ISO 时间戳(秒级、带 Z),让账本里的时间可比、可排序。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclasses.dataclass(frozen=True)
class RunResult:
    """一遍跑完一套任务的实测三尺(原始计数,归一交给属性算,免得喂进来的比率自相矛盾)。"""
    n_tasks: int            # 这一遍跑了多少任务
    n_accepted: int         # 其中通过验收的任务数
    n_failed: int           # 其中崩溃/报错的任务数(失败与未通过验收可重叠)
    total_seconds: float    # 这一遍总耗时(秒)

    def __post_init__(self) -> None:
        # 计数得自洽:非负,且通过/失败都不能超过总数。坏数据当场拦,别污染裁决。
        if self.n_tasks < 0 or self.n_accepted < 0 or self.n_failed < 0 or self.total_seconds < 0:
            raise ValueError("RunResult 的计数与耗时不能为负")
        if self.n_accepted > self.n_tasks or self.n_failed > self.n_tasks:
            raise ValueError("通过/失败的任务数不能超过总任务数")

    @property
    def acceptance(self) -> float:
        """验收率 = 通过验收 ÷ 总任务(无任务则 0)。"""
        return self.n_accepted / self.n_tasks if self.n_tasks else 0.0

    @property
    def failure(self) -> float:
        """失败率 = 崩溃/报错 ÷ 总任务(无任务则 0)。"""
        return self.n_failed / self.n_tasks if self.n_tasks else 0.0

    @property
    def avg_seconds(self) -> float:
        """每任务平均耗时(无任务则 0)。"""
        return self.total_seconds / self.n_tasks if self.n_tasks else 0.0

    def to_record(self) -> dict:
        return {"n_tasks": self.n_tasks, "n_accepted": self.n_accepted,
                "n_failed": self.n_failed, "total_seconds": self.total_seconds}

    @staticmethod
    def from_record(rec: dict) -> "RunResult":
        return RunResult(n_tasks=int(rec.get("n_tasks", 0)),
                         n_accepted=int(rec.get("n_accepted", 0)),
                         n_failed=int(rec.get("n_failed", 0)),
                         total_seconds=float(rec.get("total_seconds", 0.0)))


def check_pair(baseline: RunResult, ablated: RunResult) -> list[str]:
    """对照要守的红线,一次说清;返回违规清单(空 = 对照成立)。

    红线两条:
      1) **同一套任务**——两遍任务数必须相等且 > 0,否则是拿苹果比橘子;
      2) **任务数足够**——少于 MIN_TASKS 的差异是噪声,不配给一个器官定生死。
    """
    errs: list[str] = []
    if baseline.n_tasks == 0 or ablated.n_tasks == 0:
        errs.append("对照不成立:有一遍一个任务都没跑")
    elif baseline.n_tasks != ablated.n_tasks:
        errs.append(f"对照不成立:两遍任务数不等({baseline.n_tasks} vs {ablated.n_tasks}),"
                    f"得跑同一套任务才比得了")
    elif baseline.n_tasks < MIN_TASKS:
        errs.append(f"证据不足:只跑了 {baseline.n_tasks} 个任务(< {MIN_TASKS}),"
                    f"差异是噪声,不配给器官定生死")
    return errs


def harm_of(baseline: RunResult, ablated: RunResult) -> float:
    """摘掉这器官「整体垮多少」:取验收掉的幅度与失败涨的幅度里更狠的那个。

    验收掉得越多 / 失败涨得越多 → 伤害越大 → 越说明它在兜真活。两者都不变 → 伤害≈0 → 赘肉。
    伤害只取「往坏走」的方向:消融后反而更好(验收涨/失败降)记 0,不替赘肉脸上贴金。
    """
    acc_drop = baseline.acceptance - ablated.acceptance   # 验收掉了多少
    fail_rise = ablated.failure - baseline.failure         # 失败涨了多少
    return max(0.0, acc_drop, fail_rise)


@dataclasses.dataclass(frozen=True)
class Ablation:
    """一次消融对照实验的账本记录:谁、两遍实测、何时、凭什么。"""
    cap: str                    # 被消融的能力名(通常是模块名)
    baseline: RunResult         # 它在场时的表现
    ablated: RunResult          # 把它禁掉/换平替后的表现
    method: str = ""            # 怎么消融的:"禁用" / "换成 X 平替" 等
    ts: str = ""                # UTC 时间戳,留空则取当下
    note: str = ""              # 一句话备注

    def __post_init__(self) -> None:
        if not self.ts:
            object.__setattr__(self, "ts", _now())

    def verdict(self) -> str:
        """据三尺对照下裁决(闸门不过 → inconclusive)。"""
        if check_pair(self.baseline, self.ablated):
            return INCONCLUSIVE
        harm = harm_of(self.baseline, self.ablated)
        if harm >= ESSENTIAL_THRESHOLD:
            return ESSENTIAL
        if harm >= MARGINAL_THRESHOLD:
            return MARGINAL
        return BLOAT

    def faster_when_ablated(self) -> bool:
        """消融后是否还更快(每任务平均耗时下降)——赘肉若兼此条,是双重卸壳信号。"""
        return self.ablated.avg_seconds < self.baseline.avg_seconds

    def to_record(self) -> dict:
        return {
            "cap": self.cap,
            "verdict": self.verdict(),
            "harm": round(harm_of(self.baseline, self.ablated), 4),
            "baseline": self.baseline.to_record(),
            "ablated": self.ablated.to_record(),
            "method": self.method,
            "ts": self.ts,
            "note": self.note,
        }


def record_ablation(cap: str, baseline: RunResult, ablated: RunResult, *,
                    method: str = "", note: str = "",
                    ledger: pathlib.Path = LEDGER) -> Ablation:
    """落账一次消融实验,返回该实验(含裁决)。

    对照不成立也照记——一次证据不足的实验本身就是值得留痕的事实(提醒补做对照),
    但裁决会诚实地标成 inconclusive,绝不冒充判决。
    """
    a = Ablation(cap=cap, baseline=baseline, ablated=ablated, method=method, note=note)
    append_jsonl(ledger, a.to_record())
    return a


def current_verdicts(ledger: pathlib.Path = LEDGER) -> dict[str, dict]:
    """把 append-only 账本折叠成「每样本事最近一次消融判成了啥」:同名取最后一条。"""
    out: dict[str, dict] = {}
    for rec in read_jsonl(ledger):
        cap = rec.get("cap")
        if cap:
            out[cap] = rec
    return out


def bloat_caps(ledger: pathlib.Path = LEDGER) -> list[dict]:
    """最近一次被判赘肉的能力(按伤害值升序——越接近 0 越该先卸)。"""
    bloats = [r for r in current_verdicts(ledger).values() if r.get("verdict") == BLOAT]
    return sorted(bloats, key=lambda r: r.get("harm", 0.0))


# ── 自检:对照闸门 + 三尺裁决,一步不过即违约 ──────────────────────────────
def _selftest() -> list[str]:
    """返回失败清单(空 = 全过);每条都是自给自足、无副作用(不碰真账本)的真实调用。"""
    fails: list[str] = []

    def check(cond: bool, why: str) -> None:
        if not cond:
            fails.append(why)

    # 0) RunResult 的计数得自洽:坏数据当场拦。
    try:
        RunResult(n_tasks=3, n_accepted=5, n_failed=0, total_seconds=1.0)
        fails.append("通过数超过总数竟没被拦")
    except ValueError:
        pass
    try:
        RunResult(n_tasks=3, n_accepted=0, n_failed=0, total_seconds=-1.0)
        fails.append("负耗时竟没被拦")
    except ValueError:
        pass

    # 1) 归一三尺算对:10 任务、8 通过、1 失败、20 秒。
    r = RunResult(n_tasks=10, n_accepted=8, n_failed=1, total_seconds=20.0)
    check(abs(r.acceptance - 0.8) < 1e-9, "验收率该是 0.8")
    check(abs(r.failure - 0.1) < 1e-9, "失败率该是 0.1")
    check(abs(r.avg_seconds - 2.0) < 1e-9, "平均耗时该是 2.0 秒")

    # 2) 对照闸门:任务数不等 / 太少 / 为零都判证据不足。
    big = RunResult(n_tasks=10, n_accepted=9, n_failed=0, total_seconds=10.0)
    mismatch = RunResult(n_tasks=7, n_accepted=5, n_failed=0, total_seconds=7.0)
    check(any("任务数不等" in e for e in check_pair(big, mismatch)), "任务数不等该被拦")
    tiny = RunResult(n_tasks=3, n_accepted=2, n_failed=0, total_seconds=3.0)
    tiny2 = RunResult(n_tasks=3, n_accepted=1, n_failed=1, total_seconds=4.0)
    check(any("证据不足" in e for e in check_pair(tiny, tiny2)), "任务太少该判证据不足")
    empty = RunResult(n_tasks=0, n_accepted=0, n_failed=0, total_seconds=0.0)
    check(any("一个任务都没跑" in e for e in check_pair(big, empty)), "空跑该被拦")
    check(not check_pair(big, RunResult(10, 5, 2, 30.0)), "同套足量任务该让对照成立")

    # 3) 裁决三结局:
    #    a) 要害——摘了验收从 0.9 掉到 0.4(harm=0.5 ≥ 要害线)。
    ess = Ablation("contracts.py",
                   RunResult(10, 9, 0, 10.0), RunResult(10, 4, 3, 9.0),
                   method="禁用契约校验")
    check(ess.verdict() == ESSENTIAL, f"验收大跌该判要害,实得 {ess.verdict()}")
    #    b) 边际——验收从 0.9 掉到 0.8(harm=0.1,落在边际区间)。
    mar = Ablation("hands.py", RunResult(10, 9, 0, 10.0), RunResult(10, 8, 0, 10.0))
    check(mar.verdict() == MARGINAL, f"小幅变化该判边际,实得 {mar.verdict()}")
    #    c) 赘肉——验收/失败都纹丝不动,且消融后更快(harm=0 < 边际线)。
    blt = Ablation("decor.py", RunResult(10, 9, 0, 20.0), RunResult(10, 9, 0, 12.0),
                   method="禁用")
    check(blt.verdict() == BLOAT, f"纹丝不动该判赘肉,实得 {blt.verdict()}")
    check(blt.faster_when_ablated(), "消融后更快该被识出(双重卸壳信号)")
    #    d) 消融后反而更好(验收涨),伤害记 0,不给赘肉脸上贴金 → 仍判赘肉。
    better = Ablation("noise.py", RunResult(10, 7, 1, 10.0), RunResult(10, 9, 0, 10.0))
    check(harm_of(better.baseline, better.ablated) == 0.0, "消融后变好该记 0 伤害")
    check(better.verdict() == BLOAT, "消融后变好该判赘肉")
    #    e) 对照不成立 → inconclusive,绝不冒充判决。
    inc = Ablation("x.py", RunResult(3, 3, 0, 3.0), RunResult(3, 0, 3, 3.0))
    check(inc.verdict() == INCONCLUSIVE, f"证据不足该判 inconclusive,实得 {inc.verdict()}")

    # 4) 账本折叠 + 赘肉清单:临时账本里同名取最后一条,赘肉单列且按伤害升序。
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d) / "ab.jsonl"
        record_ablation("a.py", RunResult(10, 9, 0, 10.0), RunResult(10, 4, 2, 9.0), ledger=tmp)
        record_ablation("b.py", RunResult(10, 9, 0, 20.0), RunResult(10, 9, 0, 12.0), ledger=tmp)
        # b.py 后判一次更明确的赘肉(harm 仍 0),同名应覆盖。
        record_ablation("b.py", RunResult(20, 18, 0, 40.0), RunResult(20, 18, 0, 25.0), ledger=tmp)
        cur = current_verdicts(tmp)
        check(cur.get("a.py", {}).get("verdict") == ESSENTIAL, "a.py 该判要害")
        check(cur.get("b.py", {}).get("verdict") == BLOAT, "b.py 折叠后该判赘肉")
        check(cur.get("b.py", {}).get("baseline", {}).get("n_tasks") == 20,
              "同名能力该取最后一条(20 任务那次)")
        blts = bloat_caps(tmp)
        check([r["cap"] for r in blts] == ["b.py"], f"赘肉清单该只含 b.py,实得 {blts}")

    return fails


def _fmt_run(r: RunResult) -> str:
    return (f"验收 {r.acceptance:.0%} · 失败 {r.failure:.0%} · "
            f"均耗 {r.avg_seconds:.2f}s（{r.n_tasks} 任务）")


def _demo() -> None:
    """演示三种结局各一例:要害留、边际再观察、赘肉考虑卸壳。"""
    cases = [
        ("contracts.py", "禁用入口契约校验",
         RunResult(20, 19, 0, 24.0), RunResult(20, 11, 5, 22.0),
         "摘了契约,验收从 95% 塌到 55%、还多崩 5 个——它在兜真活"),
        ("coach.py", "换成不给建议的空壳平替",
         RunResult(20, 18, 0, 30.0), RunResult(20, 16, 1, 28.0),
         "摘了只掉一点,功过不明,再攒几轮证据"),
        ("decor.py", "禁用",
         RunResult(20, 18, 1, 40.0), RunResult(20, 18, 1, 26.0),
         "摘了验收失败都纹丝不动,反而快了 35%——这块壳该考虑卸了"),
    ]
    print("🔬 消融对照:同一套任务,把器官禁掉/换平替再跑一遍,看整体垮不垮：\n")
    for cap, method, base, abl, why in cases:
        a = Ablation(cap, base, abl, method=method)
        v = a.verdict()
        harm = harm_of(base, abl)
        print(f"  {_EMOJI[v]} {cap}  [{v}]  伤害 {harm:.0%}  ——消融手法:{method}")
        print(f"      🟢 在场：{_fmt_run(base)}")
        print(f"      🔪 消融：{_fmt_run(abl)}")
        if v == BLOAT and a.faster_when_ablated():
            print(f"      ⚠️  消融后更快,双重卸壳信号(见 lifecycle 的 deprecated→retired)")
        print(f"      判语：{why}\n")
    print("一样本事想留在壳上,得拿得出「摘了我你会差在哪」的对照证据——拿不出,它就是赘肉。")


def _print_status(as_json: bool, only_bloat: bool) -> None:
    """读真账本,列每样本事最近一次消融裁决(或只列赘肉)。"""
    cur = current_verdicts()
    if as_json:
        print(json.dumps(cur, ensure_ascii=False, indent=2))
        return
    if only_bloat:
        blts = bloat_caps()
        if not blts:
            print("🔬 暂无被判赘肉的器官——要么都在兜活,要么还没做过消融对照。")
            return
        print(f"🔴 被判赘肉、该考虑卸壳的器官(共 {len(blts)},按伤害升序):\n")
        for r in blts:
            faster = ""
            b, a = r.get("baseline", {}), r.get("ablated", {})
            if a.get("total_seconds", 0) < b.get("total_seconds", 0):
                faster = " ⚠️ 消融后更快"
            print(f"  🔴 {r['cap']:<18} 伤害 {r.get('harm', 0):.0%}{faster}")
        print("\n下一步:给它们走 lifecycle 的 deprecated→retired(退役需 before/after 证据对照)。")
        return
    if not cur:
        print(f"🔬 消融账本还空着（{LEDGER.relative_to(REPO_ROOT)} 未记录任何实验）。")
        return
    order = {ESSENTIAL: 0, MARGINAL: 1, INCONCLUSIVE: 2, BLOAT: 3}
    print(f"🔬 各能力最近一次消融裁决(共 {len(cur)} 样,账本 {LEDGER.relative_to(REPO_ROOT)})：\n")
    for cap, r in sorted(cur.items(), key=lambda kv: (order.get(kv[1].get("verdict"), 9), kv[0])):
        v = r.get("verdict", INCONCLUSIVE)
        print(f"  {_EMOJI.get(v, '⬜')} {v:<13} 伤害 {r.get('harm', 0):.0%}  {cap}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 能力消融台 🔬")
    ap.add_argument("--demo", action="store_true", help="演示三种结局(要害/边际/赘肉)各一例")
    ap.add_argument("--status", action="store_true", help="读账本,列每样本事最近一次消融裁决")
    ap.add_argument("--bloat", action="store_true", help="只列被判赘肉、该考虑卸壳的器官")
    ap.add_argument("--json", action="store_true", help="机读:导出当前各能力最近裁决")
    ap.add_argument("--quiet", action="store_true", help="只在自检不过时说话(适合钩子 / CI)")
    args = ap.parse_args(argv)

    if args.demo:
        _demo()
        return
    if args.status or args.bloat or args.json:
        _print_status(as_json=args.json, only_bloat=args.bloat)
        return

    fails = _selftest()
    if fails:
        print(f"⚠️  消融台自检发现 {len(fails)} 处不达约：\n")
        for f in fails:
            print(f"  ❌ {f}")
        print("\n先把对照闸门与裁决改回守约,再拿它给器官定生死。")
        sys.exit(1)

    if not args.quiet:
        print(f"🔬 消融台守约:对照须同套足量任务(≥ {MIN_TASKS}),"
              f"据验收/耗时/失败三尺裁决(要害/边际/赘肉),证据不足绝不冒充判决——闸门全部生效。")
    sys.exit(0)


if __name__ == "__main__":
    main()
