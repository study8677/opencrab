#!/usr/bin/env python3
"""契约断裂演练 🧬 —— 给核心 JSONL 链路注入「字段漂移」，复现下游静默误读，并随附修复包。

为什么要有它：`jsonlstore` 保证「坏行跳过、好行照读、永不抛错」(chaos.py 已验)，
`contracts` 钉函数签名，`compat` 钉命令 `--json` 的形状。可这三层都**漏掉了中间最危险的一格**：
落进 JSONL 的**那条记录本身的字段约定**。产出方某天顺手把 `seq` 改名成 `index`、把 `ok`
从 bool 写成 "true" 字符串、或干脆删掉 `situation`——记录仍是**合法 JSON**，jsonlstore 照读不误，
单测、契约、compat 全绿。可消费方还在 `rec.get("seq")`，于是静默拿到 `None`/错类型，
排序错乱、判真为假、统计归零——**等下游崩了才发现接口早被掀了**。这就是「字段漂移」型契约断裂。

本层主动制造这种逆境：对每条登记在册的核心链路，
  · 取一条**健康记录**(字段照真实产出方),让消费读法跑通,记下基线;
  · 注入三类漂移——**删字段 / 改名 / 改类型**——验证 `rec.get(...)` 是否**静默误读**(漏报=风险真实存在);
  · 用随附的 `guard()` 修复件复跑,验证它**当场抓到**该漂移(修复有效)。

漂移演练「通过」的判据是双向的：每个注入既要**骗过裸 .get**(证明风险确实潜伏),
又要**被 guard 抓住**(证明修复包能堵住)。任一漂移溜过 guard → 退出码非零。

全程**绝不碰真实状态**：所有记录都是当场构造的合成样本,只在内存里漂移、只读不写真账本。

用法:
    python fielddrift.py              # 跑全部链路的漂移演练,打印复现+修复报告
    python fielddrift.py --quiet      # 只在有漂移溜过 guard 时说话(适合钩子 / CI)
    python fielddrift.py --only audit # 只演练某一条链路(按登记名)
    python fielddrift.py --list       # 只列登记在册的核心链路
    python fielddrift.py --json       # 机读:每条漂移的复现取证 + guard 结论

退出码:0 = 每个注入的漂移都被 guard 抓住;1 = 有漂移溜过修复件。零第三方依赖,纯标准库。
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import sys

# ── 核心 JSONL 链路的字段契约 ───────────────────────────────────────────
# 每条链路 = 一个产出方写、消费方读的 JSONL 记录约定。`reads` 是消费方真实靠 `.get(key)`
# 取值的关键字段及其期望类型(摘自仓库里现存的读法)。健康样本字段照真实产出方一比一。
@dataclasses.dataclass(frozen=True)
class Link:
    """一条核心 JSONL 链路:产出方写、消费方读,中间靠一组关键字段的类型约定咬合。"""
    name: str                    # 登记名(= 链路名,作过滤)
    store: str                   # 落点(人话)
    flow: str                    # 产出方 → 消费方
    healthy: dict                # 一条健康记录(字段照真实产出方)
    reads: dict[str, type]       # 消费方靠 .get(key) 取的关键字段 → 期望类型


_LINKS: list[Link] = [
    Link(
        name="audit", store="state/audit/<date>.jsonl",
        flow="audit.record() → audit.reconstruct()/timeline",
        healthy={"ts": "2026-05-26T00:02:13.330", "run_id": "20260525-232424-16085",
                 "seq": 32, "event": "tick_start", "tick": 280, "energy_spent": 0},
        reads={"ts": str, "seq": int, "event": str}),
    Link(
        name="episode", store="state/memory/episodes.jsonl",
        flow="memory.remember() → memory 召回/相似度",
        healthy={"at": "2026-05-25T14:08:52", "situation": "推进契约断裂演练",
                 "action": "自我进化", "result": "已合并", "ok": True,
                 "code": "", "tags": []},
        reads={"situation": str, "result": str, "ok": bool}),
    Link(
        name="evidence", store="state/evidence/ledger.jsonl",
        flow="evidence.run_verify() → evidence 复核/出票",
        healthy={"name": "smoke", "ok": True, "ts": 1748000000.0,
                 "detail": "全过", "argv": ["python", "smoke.py"]},
        reads={"name": str, "ok": bool, "detail": str}),
    Link(
        name="chaos", store="state/chaos/report.jsonl",
        flow="chaos.write_report() → 韧性看板消费",
        healthy={"ts": 1748000000.0, "total": 9, "passed": 9,
                 "results": [{"family": "env", "name": "缺失 X", "passed": True}]},
        reads={"total": int, "passed": int, "results": list}),
    Link(
        name="contract", store="contracts.manifest() (机读契约清单)",
        flow="contracts.manifest() → 外部工具消费",
        healthy={"module": "jsonlstore", "duty": "读一批/追一条",
                 "inputs": "path", "outputs": "缺失→[]"},
        reads={"module": str, "duty": str, "outputs": str}),
]


# ── 修复包:字段契约守卫 ─────────────────────────────────────────────────
# 这是随演练一并交付的「修复件」——消费方在 .get 之前先过它一道,字段漂移当场现形,
# 不再静默拿 None/错类型往下走。判据与消费方真实依赖一致:关键字段须在、且类型对。
def guard(rec: dict, link: Link) -> list[str]:
    """拿一条记录对照链路的字段契约,返回违约清单(空=守约)。这是漂移演练的修复包核心。"""
    out: list[str] = []
    if not isinstance(rec, dict):
        return [f"记录不是对象而是 {type(rec).__name__}"]
    for key, want in link.reads.items():
        if key not in rec:
            out.append(f"缺关键字段 `{key}`(消费方将静默拿 None)")
            continue
        val = rec[key]
        # bool 是 int 子类,须先判 bool;期望非 bool 时 bool 值也算漂移。
        if want is bool:
            if not isinstance(val, bool):
                out.append(f"`{key}` 类型漂移:期望 bool,实得 {type(val).__name__}")
        elif isinstance(val, bool) or not isinstance(val, want):
            out.append(f"`{key}` 类型漂移:期望 {want.__name__},实得 {type(val).__name__}")
    return out


# ── 漂移注入:删字段 / 改名 / 改类型 ─────────────────────────────────────
def _drifts(link: Link) -> list[dict]:
    """为一条链路造三类字段漂移,各打在一个消费方真在意的关键字段上。"""
    keys = list(link.reads)
    drop_key = keys[0]
    rename_key = keys[-1] if len(keys) > 1 else keys[0]
    retype_key = keys[1] if len(keys) > 1 else keys[0]
    return [
        {"kind": "drop", "key": drop_key,
         "how": f"产出方删掉了字段 `{drop_key}`"},
        {"kind": "rename", "key": rename_key, "to": f"{rename_key}_v2",
         "how": f"产出方把 `{rename_key}` 改名成 `{rename_key}_v2`"},
        {"kind": "retype", "key": retype_key,
         "how": f"产出方把 `{retype_key}` 写成了字符串"},
    ]


def _apply(rec: dict, drift: dict) -> dict:
    """把一类漂移作用到记录的合成副本上(只在内存,绝不碰真实记录)。"""
    r = copy.deepcopy(rec)
    k = drift["key"]
    if drift["kind"] == "drop":
        r.pop(k, None)
    elif drift["kind"] == "rename":
        r[drift["to"]] = r.pop(k, None)
    elif drift["kind"] == "retype":
        r[k] = "DRIFTED"          # 不论原本是什么,都改成字符串,模拟类型漂移
    return r


def _reads_ok(rec: dict, link: Link) -> bool:
    """消费方的「裸 .get」读法:关键字段都取得到且类型对,才算读对。"""
    for key, want in link.reads.items():
        val = rec.get(key)
        if val is None:
            return False
        if want is bool:
            if not isinstance(val, bool):
                return False
        elif isinstance(val, bool) or not isinstance(val, want):
            return False
    return True


@dataclasses.dataclass
class Shot:
    """一次漂移注入的复现取证 + 修复结论。"""
    link: str
    kind: str
    how: str
    silent_break: bool     # 裸 .get 被骗(读法"没报错"却已误读)→ 风险真实
    caught: bool           # guard 当场抓住 → 修复有效
    repro: str             # 一句话复现:漂移后消费方看到了什么
    fix: str               # guard 给出的违约原文(修复件的输出)

    @property
    def good(self) -> bool:
        # 演练通过:既骗过裸读(证明风险),又被 guard 抓住(证明修复)。
        return self.silent_break and self.caught

    @property
    def mark(self) -> str:
        return "🟢" if self.good else "🔴"

    def to_meta(self) -> dict:
        return {"link": self.link, "kind": self.kind, "how": self.how,
                "silent_break": self.silent_break, "caught": self.caught,
                "good": self.good, "repro": self.repro, "fix": self.fix}


def drill(link: Link) -> list[Shot]:
    """对一条链路跑全部漂移注入,逐个产出复现+修复取证。"""
    # 先确认健康样本本身读得通、守得约——基线不成立就别谈漂移。
    base_reads = _reads_ok(link.healthy, link)
    base_guard = guard(link.healthy, link)
    shots: list[Shot] = []
    for d in _drifts(link):
        drifted = _apply(link.healthy, d)
        reads_after = _reads_ok(drifted, link)
        violations = guard(drifted, link)
        # 静默断裂 = 健康时读得通,漂移后读不对(裸 .get 不抛错却已误读)。
        silent = base_reads and not reads_after
        caught = bool(violations) and not base_guard
        if not base_reads:
            repro = "⚠️ 健康样本基线就读不通,跳过(请修健康样本)"
        elif silent:
            repro = f"漂移后裸 .get 静默误读(关键字段取不到/类型错),无任何报错"
        else:
            repro = "漂移没动到消费方在意的字段,裸读仍正常(此类漂移无害)"
        fix = "；".join(violations) if violations else "guard 未报违约(漏网!)"
        shots.append(Shot(link.name, d["kind"], d["how"], silent, caught, repro, fix))
    return shots


def run(only: str | None = None) -> list[Shot]:
    links = [l for l in _LINKS if only in (None, l.name)]
    out: list[Shot] = []
    for l in links:
        out.extend(drill(l))
    return out


def summarize(shots: list[Shot]) -> tuple[bool, int, int]:
    """归一化:是否全员被 guard 堵住、有几个漂移溜过 guard、有几个无害漂移。"""
    leaked = sum(1 for s in shots if s.silent_break and not s.caught)
    harmless = sum(1 for s in shots if not s.silent_break)
    return (leaked == 0, leaked, harmless)


def manifest(only: str | None = None) -> dict:
    shots = run(only)
    healthy, leaked, harmless = summarize(shots)
    return {"total": len(shots), "leaked": leaked, "harmless": harmless,
            "healthy": healthy, "shots": [s.to_meta() for s in shots]}


# ── 打印 ─────────────────────────────────────────────────────────────────
def _print(shots: list[Shot]) -> None:
    print(f"🧬 契约断裂演练 · 字段漂移（{len(shots)} 个注入）\n")
    last = None
    by_name = {l.name: l for l in _LINKS}
    for s in shots:
        if s.link != last:
            l = by_name[s.link]
            print(f"  ── {l.name}：{l.store}")
            print(f"     {l.flow}")
            last = s.link
        print(f"  {s.mark} [{s.kind}] {s.how}")
        print(f"      复现：{s.repro}")
        print(f"      修复：guard → {s.fix}")
    healthy, leaked, harmless = summarize(shots)
    print(f"\n  小结：{len(shots)} 个注入，{leaked} 个溜过 guard，{harmless} 个无害。")
    if healthy:
        print("🧬 每个有害漂移都被 guard 当场抓住——修复包堵得住,接口可放心提速。")
    else:
        print(f"💥 有 {leaked} 个字段漂移溜过 guard,修复件还没覆盖到——先补 guard 再蜕壳。")


def _list() -> None:
    print(f"🧬 在册核心 JSONL 链路（{len(_LINKS)} 条）:\n")
    for l in _LINKS:
        print(f"  · {l.name} —— {l.store}")
        print(f"      {l.flow}")
        print(f"      消费方关键字段：" +
              "，".join(f"{k}:{t.__name__}" for k, t in l.reads.items()))
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 契约断裂演练 · 字段漂移 🧬")
    ap.add_argument("--only", help="只演练某一条链路(按登记名)")
    ap.add_argument("--list", action="store_true", help="只列在册核心链路")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有漂移溜过 guard 时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="机读:导出复现+修复结论")
    args = ap.parse_args(argv)

    if args.list:
        _list()
        return
    if args.json:
        print(json.dumps(manifest(args.only), ensure_ascii=False, indent=2))
        return

    shots = run(args.only)
    healthy, _, _ = summarize(shots)
    if not (args.quiet and healthy):
        _print(shots)
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
