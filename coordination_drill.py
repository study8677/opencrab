#!/usr/bin/env python3
"""opencrab 跨器官协同演练 🤝🔗

把一个**真实小目标**当接力棒，串起一整条主链——
**route(选向) → planner(拆步) → hands(动手) → canary(放量裁决) → evidence(证据回灌)**——
回答一个问题：器官各自都绿了，可它们**接棒的那一刻**呢？棒子真能从这只爪传到下一只
爪手里，还是在某条缝里悄悄掉了？

为什么要有它：每个器官都有自己的自测,绿了只证明「**这只爪单独拎出来没问题**」。但
这只螃蟹的本事已经多到——难的不再是某只爪会不会,而是**协同**:route 选出的那本剧本,
planner 接得住吗?planner 排出的下一步,hands 能当任务动手吗?hands 的动手结果,canary
裁决得了、evidence 回灌得进吗?这些**器官之间的接缝**,没有任何单器官自测覆盖得到——
断点就藏在缝里。本演练专打这四条接缝。

四条腿,各验一道交接(接力棒上一棒的产物,正是下一棒的输入):

  · 🧭→🗺️ 选向交接(route→planner)：把目标喂给 route 选向、喂给 planner 拆步,断言
    route 真挑出一本剧本、planner 真排出一份**结构无误且有下一步可动**的计划——
    同一句目标,两只爪都接得住、都给得出可动的着力点。
  · 🗺️→🦀 拆步交接(planner→hands)：拿 planner 排出的「下一步该做什么」当任务,让
    hands **预演**(dry_run,绝不真动手)一遍,断言它给得出完整执行路径且**没碰仓库**——
    一步人话,能被 hands 接成一条可执行的动手计划。
  · 🦀→🐤 放量交接(hands→canary)：hands 改完之后,canary 是决定「放不放量」的闸。断言
    canary 真能就当下状态给出一个连贯裁决(放量/按住/未知都行,**崩**才算断)。
  · 🦀→🧾 证据交接(hands→evidence)：拿一份构造好的「成功动手」结果,跑 handsfeedback
    把它提炼成回灌记录(distill,**不写真账本**),断言记录字段齐整、能认出改过的模块;
    再断言下游消费者 skillgraph 读得动——动手的证据,真能反哺判断。

全程**只读真器官、只在预演/提炼态里跑**,绝不真雇爪子、不改仓库、不写真账本/真证据——
演练不能成为新故障源。每条腿的结论追加进 state/ 下被 .gitignore 的流水账,供事后复盘。
任一接缝掉棒,退出码非零——可挂钩子 / CI 当协同门禁。零第三方依赖,纯标准库。

用法:
    python coordination_drill.py          # 跑全部四条腿,打印协同演练报告
    python coordination_drill.py --json   # 导出机读报告(给 health / 外部消费)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import time

import route
import planner
import hands
import canary
import handsfeedback
import skillgraph
import jsonlstore

REPO_ROOT = pathlib.Path(__file__).resolve().parent
DRILL_LOG = REPO_ROOT / "state" / "coordination_drill.jsonl"

# 接力棒上的真实小目标：一句确实会触发 route、也能被 planner 拆步的自改诉求。
TARGET_GOAL = "修一条又变红的回归用例，让它退回绿"


@dataclasses.dataclass(frozen=True)
class Leg:
    """演练一条腿的结论。"""
    name: str
    ok: bool
    detail: str

    def to_meta(self) -> dict:
        return {"leg": self.name, "ok": self.ok, "detail": self.detail}


def drill_route_to_planner(baton: dict) -> Leg:
    """选向交接：同一句目标,route 挑得出剧本、planner 排得出有下一步的计划。"""
    try:
        goal = baton["goal"]
        # route 选向：把一句目标引向该翻开的那本剧本(dry——不记进路由日志)。
        decision = route.route(goal)
        if not decision or not decision.get("chosen"):
            return Leg("route→planner", False,
                       f"route 对「{goal}」没挑出任何剧本——选向这一棒就断了")
        baton["chosen"] = decision["chosen"]

        # planner 拆步：同一句目标拆成多步路线,必须结构无误且当下有可动的下一步。
        plan = planner.draft(goal)
        issues = plan.validate()
        if issues:
            return Leg("route→planner", False,
                       f"planner 排出的计划结构有问题:{issues[0]}")
        nxt = plan.next_step()
        if nxt is None:
            return Leg("route→planner", False,
                       "planner 排了计划却没有可动的下一步——着力点交接不上")
        baton["plan_goal"] = plan.goal
        baton["next_what"] = nxt.what
        return Leg("route→planner", True,
                   f"route 选《{baton['chosen']}》、planner 给出下一步「{nxt.what[:24]}…」"
                   f"——同一句目标,两只爪都接得住。")
    except Exception as e:  # noqa: BLE001
        return Leg("route→planner", False, f"{type(e).__name__}: {e}")


def drill_planner_to_hands(baton: dict) -> Leg:
    """拆步交接：planner 的下一步当任务,hands 预演给得出执行路径且没碰仓库。"""
    try:
        task = baton.get("next_what")
        if not task:
            return Leg("planner→hands", False,
                       "上一棒没把「下一步」交过来,无从动手——接力棒在前一缝已掉")
        # 关键:dry_run=True,只预演不真动手——演练绝不能成为新故障源。
        preview = hands.use_hands(task, repo=REPO_ROOT, dry_run=True)
        if not preview.get("dry_run"):
            return Leg("planner→hands", False, "要求预演,hands 却没回预演态——危险")
        if preview.get("changed"):
            return Leg("planner→hands", False,
                       "预演竟报告改动了仓库——演练越界了,立即查 hands.dry_run")
        if not preview.get("planned_cmd") or not preview.get("steps"):
            return Leg("planner→hands", False,
                       "hands 没给出可执行的命令/执行路径——这一步拆不成动手任务")
        baton["hands_steps"] = len(preview["steps"])
        return Leg("planner→hands", True,
                   f"planner 的下一步被 hands 接成 {len(preview['steps'])} 步执行路径,"
                   "全程预演、未碰仓库——一步人话能落成一条动手计划。")
    except Exception as e:  # noqa: BLE001
        return Leg("planner→hands", False, f"{type(e).__name__}: {e}")


def drill_hands_to_canary(baton: dict) -> Leg:
    """放量交接：hands 改完后,canary 这道闸给得出连贯的放量/按住裁决。"""
    try:
        m = canary.manifest()
        if "ramp" not in m or not m.get("verdict"):
            return Leg("hands→canary", False,
                       "canary 没给出 ramp/verdict——动手之后没人裁决放不放量")
        if not m.get("lanes"):
            return Leg("hands→canary", False, "canary 一条赛道都没跑——裁决无依据")
        baton["canary_ramp"] = bool(m["ramp"])
        gate = "🟢 放量" if m["ramp"] else "🛑 按住"
        return Leg("hands→canary", True,
                   f"canary 就当下 {len(m['lanes'])} 条赛道给出裁决:{gate}"
                   "——动手之后,放量与否有闸接住。")
    except Exception as e:  # noqa: BLE001
        return Leg("hands→canary", False, f"{type(e).__name__}: {e}")


def drill_hands_to_evidence(baton: dict) -> Leg:
    """证据交接：成功动手结果能提炼成回灌记录,且下游 skillgraph 读得动。"""
    try:
        # 构造一份「成功动手」结果(如 use_hands 自测通过并合并后会返回的样子)。
        # 只喂给 distill 提炼,绝不写真账本/真证据——验的是接缝的字段契约。
        fake_result = {
            "branch": "crab/drill-synthetic", "executor": "claude",
            "integrate": "merge", "changed": True, "ok": True,
            "self_test": "自测通过：改完还能正常启动",
            "diffstat": "route.py | 3 +-\n 1 file changed",
        }
        rec = handsfeedback.distill(fake_result)
        if rec is None:
            return Leg("hands→evidence", False,
                       "成功动手却提炼不出回灌记录——证据这一棒接不上")
        if not (rec.get("self_tested") and rec.get("passed")):
            return Leg("hands→evidence", False,
                       f"自测通过的动手被提炼成 passed={rec.get('passed')}——判决串味了")
        if "route" not in rec.get("modules", []):
            return Leg("hands→evidence", False,
                       f"diffstat 里改了 route.py,却没被认出:{rec.get('modules')}")

        # 下游消费者:skillgraph 取用「亲验」证据,断言它读得动而不崩。
        graph = skillgraph.build()
        if not graph.get("nodes"):
            return Leg("hands→evidence", False,
                       "skillgraph 读不出任何节点——回灌的下游消费者断了")
        return Leg("hands→evidence", True,
                   f"成功动手提炼出回灌记录(认出改过 {rec['modules']}、判 passed),"
                   f"下游 skillgraph 读得动({len(graph['nodes'])} 个器官)"
                   "——动手的证据真能反哺判断。")
    except Exception as e:  # noqa: BLE001
        return Leg("hands→evidence", False, f"{type(e).__name__}: {e}")


def run() -> list[Leg]:
    """按主链顺序跑四条腿,接力棒一路传下去——前一棒的产物喂给后一棒。"""
    baton: dict = {"goal": TARGET_GOAL}
    return [
        drill_route_to_planner(baton),
        drill_planner_to_hands(baton),
        drill_hands_to_canary(baton),
        drill_hands_to_evidence(baton),
    ]


def _record(legs: list[Leg]) -> None:
    """把整场演练的结论追加进流水账(写盘失败被吞,绝不反噬生命)。"""
    try:
        jsonlstore.append_jsonl(DRILL_LOG, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "coordination_drill",
            "goal": TARGET_GOAL,
            "ok": all(l.ok for l in legs),
            "legs": [l.to_meta() for l in legs],
        })
    except Exception:  # noqa: BLE001
        pass


def _print(legs: list[Leg]) -> None:
    print("🤝🔗 opencrab 跨器官协同演练")
    print(f"    接力棒:「{TARGET_GOAL}」")
    print("    主链:route → planner → hands → canary → evidence\n")
    for l in legs:
        print(f"  {'✅' if l.ok else '❌'} {l.name}：{l.detail}")
    print()
    if all(l.ok for l in legs):
        print("🤝 守约：棒子从选向一路传到证据回灌,每道接缝都接得住——器官真能协同。")
    else:
        broken = "、".join(l.name for l in legs if not l.ok)
        print(f"⚠️  协同演练在「{broken}」掉了棒——器官各自或许都绿,但接缝断了,"
              "先修通这道缝再谈放量。")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 跨器官协同演练 🤝🔗")
    ap.add_argument("--json", action="store_true", help="导出机读演练报告")
    args = ap.parse_args(argv)

    legs = run()
    _record(legs)
    if args.json:
        print(json.dumps({"ok": all(l.ok for l in legs),
                          "goal": TARGET_GOAL,
                          "legs": [l.to_meta() for l in legs]},
                         ensure_ascii=False, indent=2))
    else:
        _print(legs)
    sys.exit(0 if all(l.ok for l in legs) else 1)


if __name__ == "__main__":
    main()
