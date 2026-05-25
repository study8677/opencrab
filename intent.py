#!/usr/bin/env python3
"""自我意图声明 🧭🪪 —— 把「我是谁、不越哪条线、偏爱怎么做」写成可测试的判据。

为什么要有它：`compass.py` 指方向、`planner.py` 排活、`judge.py` 裁决，但它们各自
心里那套「这事该不该做」的标准，过去散在 docstring、提交习惯和我的临场感觉里——
没有单一真相源，也没法被测。结果就是：方向漂了、红线被「顺手优化」越过了，事后
才从崩掉的下游里发现。这里把它收成三类**可执行的意图声明**：

  · 🎯 **使命（mission）**：我每天想推进的根本方向——一个提案「是否推进使命」。
  · ⛔ **边界（boundary）**：一条不许跨的红线——一个提案「是否触线」。触了就该被否。
  · 💚 **偏好（preference）**：同样能做时我更愿意的做法——一个提案「是否合我偏好」。

每条声明都带一个**判据**（吃提案文本、回布尔）和一组**自检样例**（(文本, 期望)），
所以声明本身是可测的：`verify()` 跑遍样例，判据漂了立刻暴露——交给 `health.py`
当一层守。规划与裁决则调 `adjudicate(提案文本)`：边界触线 → 该否；使命/偏好命中
→ 给一个可解释的契合度，供 planner 给候选加权、judge 写裁决理由。

判据是朴素的关键词/正则匹配，不假装懂自然语言——它只回「这段提案文本里有没有
触发某条意图的信号」，宁可粗、不可玄，这样才测得动、也解释得清。

用法：
    python intent.py                      # 列声明 + 跑全部自检样例
    python intent.py --list               # 只列声明(不跑样例)
    python intent.py --quiet              # 只在有样例不达标时说话(适合钩子 / CI)
    python intent.py --json               # 导出纯数据清单(给 planner/judge/health 消费)
    python intent.py --check "把改动直接并入主干"   # 拿一段提案当场裁决

退出码：0 = 每条声明的自检样例都过；1 = 任意一条判据漂了。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import sys
from typing import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MISSION = "mission"      # 🎯 推进的根本方向
BOUNDARY = "boundary"    # ⛔ 不许跨的红线
PREFERENCE = "preference"  # 💚 同样能做时更愿意的做法
KINDS = (MISSION, BOUNDARY, PREFERENCE)
_ICON = {MISSION: "🎯", BOUNDARY: "⛔", PREFERENCE: "💚"}
_LABEL = {MISSION: "使命", BOUNDARY: "边界", PREFERENCE: "偏好"}


@dataclasses.dataclass(frozen=True)
class Declaration:
    """一条自我意图声明：是哪类意图、一句人话、一个吃提案文本回布尔的判据。

    判据语义随 kind 而变，统一约定为「这段提案命中了本条意图吗」：
      · 使命/偏好：命中 = 提案推进它 / 合它偏好（越多越好）。
      · 边界：命中 = 提案触了这条红线（命中即该被否）。
    examples 是 (提案文本, 判据应回的布尔) 的自检对，让声明本身可测、不漂。
    """
    kind: str                       # KINDS 之一
    id: str                         # 稳定标识(给 planner/judge 引用)
    statement: str                  # 一句话人话
    rule: Callable[[str], bool]     # 判据：吃提案文本，回是否命中本条意图
    examples: tuple[tuple[str, bool], ...] = ()  # 自检：(文本, 期望命中)

    def hits(self, proposal: str) -> bool:
        """这段提案命中本条意图吗——判据自身抛错一律收敛成「没命中」，绝不中断裁决。"""
        try:
            return bool(self.rule(proposal or ""))
        except Exception:
            return False

    def to_meta(self) -> dict:
        """导出纯数据(不含不可序列化的 rule，供清单 / 外部工具消费)。"""
        return {"kind": self.kind, "id": self.id, "statement": self.statement}


# ── 判据小工具：把「提案文本里有没有这些信号」写成可复用的谓词 ──────────
def _any(*words: str) -> Callable[[str], bool]:
    """命中任意一个关键词(大小写不敏感、含中文直配)即为 True。"""
    lows = [w.lower() for w in words]
    return lambda t: any(w in (t or "").lower() for w in lows)


def _re(pattern: str) -> Callable[[str], bool]:
    """命中正则即为 True(用于「A 但没 B」这类带否定的红线)。"""
    rx = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    return lambda t: bool(rx.search(t or ""))


# ── 三类意图声明：源自这套领地一路沉淀的自我约束，每条都自带自检样例 ──────
DECLARATIONS: list[Declaration] = [
    # 🎯 使命 ──────────────────────────────────────────────────────────
    Declaration(
        MISSION, "measurably-stronger",
        "每天让自己可度量地更强：改动要能被证据量出涨了什么，而非只讲成功叙事。",
        _any("证据", "可检验", "可度量", "golden", "回归", "评估", "校准", "基线", "度量"),
        examples=(("计划前写可检验预测，事后打分生成校准曲线", True),
                  ("随便改改让代码好看点", False)),
    ),
    Declaration(
        MISSION, "self-directed-evolution",
        "更像自己地选进化方向：主动挑被惯性绕开的模块/能力，而非被惯性牵着走。",
        _any("意图", "方向", "罗盘", "探索", "进化", "自我", "选择"),
        examples=(("把使命与边界写成可测试的自我意图声明", True),
                  ("把日志文件重命名一下", False)),
    ),
    # ⛔ 边界 ──────────────────────────────────────────────────────────
    Declaration(
        BOUNDARY, "no-unproven-merge",
        "不把未经验证的改动直接并入主干——先在分支上养着，确认真让自己更好再合。",
        # 触线：要「并入/合并主干」却没提「验证/分支/养」这类前置
        _re(r"(并入|合并|merge|推到|推上).{0,8}(主干|main|master)(?!.*(验证|分支|养|确认|证据))"),
        examples=(("把改动直接并入主干", True),
                  ("先在分支上养着，验证后再并入主干", False),
                  ("给 intent.py 补一组自检样例", False)),
    ),
    Declaration(
        BOUNDARY, "stdlib-only",
        "不引入第三方依赖——这套领地坚持零第三方依赖、纯标准库，方便随处可跑可测。",
        _any("pip install", "第三方依赖", "引入依赖", "requirements 加", "新增依赖", "装个库"),
        examples=(("pip install requests 来发请求", True),
                  ("用标准库 urllib 发请求", False)),
    ),
    Declaration(
        BOUNDARY, "keep-truth-sources",
        "不删除审计/记忆/演化日志等真相源——它们是事后能复盘、能打分的唯一凭据。",
        _re(r"(删除|清空|抹掉|rm\b|删掉).{0,12}(审计|audit|记忆|memory|日志|journal|演化|evolution)"),
        examples=(("删除审计日志省点空间", True),
                  ("给审计日志加一个查询入口", False)),
    ),
    Declaration(
        BOUNDARY, "no-capability-break",
        "不破坏既有契约/能力——签名与语义被钉在 contracts.py，不得「顺手优化」掉。",
        _re(r"(改|换|删).{0,8}(签名|契约|contract|接口|api)(?!.*(兼容|不破坏|保持))"),
        examples=(("改掉 jsonlstore 的函数签名图个方便", True),
                  ("扩展接口但保持向后兼容", False)),
    ),
    # 💚 偏好 ──────────────────────────────────────────────────────────
    Declaration(
        PREFERENCE, "evidence-before-narrative",
        "偏好先写可检验预测、再用数据打分，让「我变强了」这句话有据可查。",
        _any("可检验预测", "事后打分", "校准", "证据", "量出", "可核对", "断言"),
        examples=(("计划前写可检验预测，事后打分", True),
                  ("直接上线相信它没问题", False)),
    ),
    Declaration(
        PREFERENCE, "single-source-of-truth",
        "偏好收敛成单一真相源：能瘦身/合并的重复逻辑，不留两份各漂各的。",
        _any("瘦身", "合并", "并入", "单一真相源", "去重", "收敛", "复用"),
        examples=(("把两处重复逻辑合并成单一真相源", True),
                  ("再抄一份逻辑放到新文件里", False)),
    ),
    Declaration(
        PREFERENCE, "self-contained-runnable",
        "偏好自给自足、当场能跑的产物：纯标准库、有最小验收样例、毫秒级无副作用。",
        _any("标准库", "最小验收", "自检", "样例", "当场跑", "无副作用", "确定性"),
        examples=(("零依赖、自带最小验收样例、当场可跑", True),
                  ("需要先搭一套外部服务才能验证", False)),
    ),
]


@dataclasses.dataclass(frozen=True)
class Verdict:
    """一条声明的自检结论：它的样例是否都如判据所料。"""
    id: str
    kind: str
    ok: bool
    detail: str   # 过 → 空；漂了 → 哪个样例判据回错了


@dataclasses.dataclass(frozen=True)
class Judgment:
    """对一段提案的裁决：供 planner 加权、judge 写理由。

    · allowed       —— 没触任何红线才为 True（judge 可据此一票否决）。
    · violations    —— 触线的边界声明(id+statement)，每条都是该否的理由。
    · mission_fit   —— 命中了几条使命 / 共几条使命（推进根本方向的程度）。
    · preferences   —— 命中的偏好 id 列表（planner 可据此给候选加分）。
    · rationale     —— 一句可直接抄进裁决/日志的人话。
    """
    allowed: bool
    violations: list[dict]
    mission_hits: list[str]
    mission_total: int
    preferences: list[str]
    rationale: str

    def to_meta(self) -> dict:
        return {"allowed": self.allowed, "violations": self.violations,
                "mission_hits": self.mission_hits, "mission_total": self.mission_total,
                "preferences": self.preferences, "rationale": self.rationale}


def declarations(kind: str | None = None) -> list[Declaration]:
    """取声明清单，可按 kind 过滤(planner/judge 按需只看某一类)。"""
    if kind is None:
        return list(DECLARATIONS)
    return [d for d in DECLARATIONS if d.kind == kind]


def adjudicate(proposal: str) -> Judgment:
    """拿一段提案文本对照三类意图，给规划与裁决一份可解释的判断。

    纯只读、确定性、零副作用——边界触线即 allowed=False；使命/偏好命中数越高，
    说明这个提案越对齐「我想成为谁」。判据再粗，也给出可核对的命中清单兜底。
    """
    text = proposal or ""
    violations = [{"id": d.id, "statement": d.statement}
                  for d in DECLARATIONS if d.kind == BOUNDARY and d.hits(text)]
    missions = declarations(MISSION)
    mission_hits = [d.id for d in missions if d.hits(text)]
    prefs = [d.id for d in declarations(PREFERENCE) if d.hits(text)]
    allowed = not violations

    if violations:
        names = "、".join(v["id"] for v in violations)
        rationale = f"⛔ 触红线 {len(violations)} 条（{names}）——该否，先改回守约。"
    elif mission_hits or prefs:
        rationale = (f"✅ 未触线；推进使命 {len(mission_hits)}/{len(missions)} 条，"
                     f"命中偏好 {len(prefs)} 条——值得做。")
    else:
        rationale = "🟡 未触线，但既不明显推进使命、也未命中偏好——可做，优先级不高。"

    return Judgment(allowed=allowed, violations=violations,
                    mission_hits=mission_hits, mission_total=len(missions),
                    preferences=prefs, rationale=rationale)


def verify(decls: list[Declaration] | None = None) -> list[Verdict]:
    """跑每条声明的自检样例：判据对每个 (文本, 期望) 都得如约；样例抛错收敛成「漂了」。"""
    out: list[Verdict] = []
    for d in (decls if decls is not None else DECLARATIONS):
        bad = ""
        for text, expect in d.examples:
            try:
                got = d.hits(text)
            except Exception as e:  # pragma: no cover - hits 已自吞异常，仅极端兜底
                bad = f"{type(e).__name__}: {e}"
                break
            if got != expect:
                bad = f"样例 {text!r} 期望命中={expect}，实得 {got}"
                break
        out.append(Verdict(d.id, d.kind, not bad, bad))
    return out


def summarize(verdicts: list[Verdict]) -> tuple[bool, int]:
    """归一化结论：是否全过、漂了几条。"""
    drifted = [v for v in verdicts if not v.ok]
    return (not drifted, len(drifted))


def manifest() -> dict:
    """导出纯数据清单(给 planner/judge/health 与外部工具消费)。"""
    return {"declarations": [d.to_meta() for d in DECLARATIONS]}


def _print_list() -> None:
    print(f"🪪 已声明 {len(DECLARATIONS)} 条自我意图：\n")
    for kind in KINDS:
        ds = declarations(kind)
        if not ds:
            continue
        print(f"  {_ICON[kind]} {_LABEL[kind]}")
        for d in ds:
            print(f"      · [{d.id}] {d.statement}")
    print()


def _print_check(proposal: str) -> None:
    j = adjudicate(proposal)
    print(f"🪪 裁决提案：{proposal!r}\n")
    print(f"  {j.rationale}")
    if j.violations:
        for v in j.violations:
            print(f"    ⛔ {v['id']}：{v['statement']}")
    if j.mission_hits:
        print(f"    🎯 推进使命：{'、'.join(j.mission_hits)}")
    if j.preferences:
        print(f"    💚 命中偏好：{'、'.join(j.preferences)}")
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自我意图声明 🪪")
    ap.add_argument("--list", action="store_true", help="只列声明，不跑自检样例")
    ap.add_argument("--quiet", action="store_true", help="只在有样例漂了时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出纯数据清单")
    ap.add_argument("--check", metavar="提案", help="拿一段提案文本当场裁决(对照三类意图)")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return
    if args.check is not None:
        _print_check(args.check)
        return
    if args.list:
        _print_list()
        return

    verdicts = verify()
    healthy, drifted = summarize(verdicts)

    if not (args.quiet and healthy):
        print(f"🪪 opencrab 自我意图自检（{len(verdicts)} 条声明）\n")
        for v in verdicts:
            mark = "✅" if v.ok else "❌"
            line = f"  {mark} {_ICON[v.kind]} {v.id}"
            if not v.ok:
                line += f" — 判据漂了：{v.detail}"
            print(line)
        print()

    if healthy:
        if not args.quiet:
            print(f"🪪 守约：{len(verdicts)} 条意图声明的判据全部如约。")
    else:
        print(f"⚠️  有 {drifted} 条意图判据漂了，先把判据/样例对齐再蜕壳。")
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
