#!/usr/bin/env python3
"""交接外包桥 🤝📦🔌 —— 把一只**真实**交接包外包给外部 agent，跑通一次完整往返。

为什么要有它：opencrab 已经有三件零件，却各管一段、缺一座桥——
  · 📦 handoff 把半完成的活封成「换个人也能无损续跑」的箱子(状态/下一步/风险/验证)，
       可它的受众一直默认是**另一个我**，从没想过把这只箱子递到**领地之外**的手里。
  · 🔌 interop 定义了和外部 agent 交换「任务·证据·结果」的信封，可它的样例是手搓的——
       信封里写什么全凭临场编，从不取自一件**真**活。
  · 🤝 embassy 懂对外协作的礼仪(背景—我想做什么—想请教/请帮的点 三段式)，可它只对着
       missionboard/market 起草，没把这套礼仪用到「把一只待续跑的箱子递出去」上。

这座桥做且只做一件事：**用一只真实交接包跑通一次外包往返**——

  · 📤 导出：拿一只 handoff 包，铸成一条 interop `task` 信封。
            done→「这些可以信」进 inputs；next→要干的活进 intent/acceptance；
            verify→**字面的验收命令**进 acceptance(跑通即算过，不是一句空泛的「帮我看看」)；
            再按 embassy 三段式生成一段**人话封面**，让接收方一眼接得住。
  · 📥 认领：把外部送回的 `result` 信封 decode + validate + 认领回原 task
            (task_id 必须对得上、ok 必须为真)，坏消息当场挡在门口，绝不让脏账混进生命。

它不替任何人跑命令、不写盘(除非 --emit 显式要求落一份样例 JSONL)，更**绝不**替你按下
发布键或反噬 handoff 账本——只做**信封层**的翻译与认领，是翻译官，不是新的故障源。
零第三方依赖，纯标准库(handoff/interop 同仓)。

用法:
    python handoff_interop.py                 # 自检:真实/合成包→task→(模拟外部)result→认领往返
    python handoff_interop.py --export <id>   # 把某只交接包铸成 task 信封并打印(含人话封面)
    python handoff_interop.py --export-open   # 把最近一只**开着**的交接包铸成 task 信封
    python handoff_interop.py --demo          # 打印一次真实外包往返样例(export→result→claim)
    python handoff_interop.py --emit PATH     # 把这次往返的信封落成一份 JSONL 样例(给外部工具看格式)
    python handoff_interop.py --quiet         # 只在自检不过时说话(钩子 / CI)

退出码：0 = 往返/自检全过；1 = 任意一步不达约。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import handoff  # noqa: E402
import interop  # noqa: E402


# ── 📤 导出：交接包 → interop task 信封 ──────────────────────────────────
def cover_for(pkg: dict) -> str:
    """按 embassy 三段式(背景—我想做什么—想请教/请帮的点)给一只交接包写**人话封面**。

    封面是给「领地之外那只手」看的:不读代码、不懂内部账本的人，照这段也能判断
    「这活我接不接得住、要跑哪几条命令算过」。
    """
    title = pkg.get("title") or "(未命名任务)"
    why = pkg.get("why") or "(未写动机)"
    done = pkg.get("done") or []
    nexts = pkg.get("next") or []
    verify = pkg.get("verify") or []
    risk = pkg.get("risk") or []

    L = [f"## 背景\n{why}", ""]
    if done:
        L.append("已经走通、可以信的部分:")
        L += [f"  · {s}" for s in done]
        L.append("")
    L.append("## 我想请你做什么")
    if nexts:
        L += [f"  {i}. {s}" for i, s in enumerate(nexts, 1)]
    else:
        L.append("  (这只包没写下一步——外包前请先补齐，否则接的人无从下手)")
    L.append("")
    L.append("## 怎么算做完(验收口径)")
    if verify:
        L.append("跑通下面每一条命令(退出码 0)即视为接对、做成:")
        L += [f"  $ {c}" for c in verify]
    else:
        L.append("  (这只包没写验证命令——外包前请先补齐，否则双方对不上账)")
    if risk:
        L += ["", "## 已知的雷(替你先喊出来)"]
        L += [f"  · {s}" for s in risk]
    return "\n".join(L)


def acceptance_for(pkg: dict) -> str:
    """把 handoff 的 verify 命令拼成一句**可机读、可人读**的验收口径。

    没有 verify 命令的包不该被外包——验收无从谈起，这里如实说明，让导出方知道得先补。
    """
    verify = pkg.get("verify") or []
    if not verify:
        return "⚠️ 该交接包未写验证命令，无法定义客观验收口径——外包前请先补 verify。"
    cmds = "；".join(verify)
    return f"逐条跑通下列命令且退出码均为 0：{cmds}（任一非零即视为未达约，result.ok 应为 false）"


def task_from_handoff(pkg: dict, *, source: str = "opencrab") -> interop.Envelope:
    """📤 把一只 handoff 包铸成一条 interop `task` 信封。

    映射(把内部账本翻译成外部认得的方言):
      · title      ← 包标题
      · intent     ← 包的「为什么」(动机)，让接收方懂这活为何而做
      · inputs     ← 已走通的状态(done) + git 现场快照指针 + 源包 id(可追溯回认领)
      · acceptance ← verify 命令拼成的客观口径(跑通即过)
      · cover      ← embassy 三段式人话封面(给不读代码的人)
      · next       ← 有序待办(第一条就是「拿起来先干这个」)
      · handoff_id ← 源包 id，认领时据此对账
    """
    snap = pkg.get("snapshot") or {}
    inputs = {
        "handoff_id": pkg.get("id"),
        "done": list(pkg.get("done") or []),
        "branch": snap.get("branch"),
        "head": snap.get("head"),
    }
    return interop.make_task(
        title=pkg.get("title") or "(未命名交接任务)",
        intent=pkg.get("why") or "(未写动机)",
        inputs=inputs,
        acceptance=acceptance_for(pkg),
        source=source,
        cover=cover_for(pkg),
        next=list(pkg.get("next") or []),
        verify=list(pkg.get("verify") or []),
        handoff_id=pkg.get("id"),
    )


# ── 📥 认领：外部 result 信封 → 对账回原 task ────────────────────────────
def claim_result(result_text: str, task: interop.Envelope) -> list[str]:
    """把外部送回的 result 信封文本认领回某个 task；返回问题清单(空 = 认领通过)。

    把坏消息挡在门口分三道:
      1) decode 守约(协议/版本/kind/必需字段)——交给 interop 这门方言的单一真相源；
      2) task_id 必须对得上原 task——外人不能拿张张冠李戴的结果来认领；
      3) ok 必须为真——失败的结果**可以**认领回来(记账)，但这里专判「这件外包活有没有做成」。
    """
    problems: list[str] = []
    try:
        env = interop.decode(result_text)
    except ValueError as e:
        return [f"result 信封不守约，挡在门口：{e}"]

    if env.kind != interop.KIND_RESULT:
        problems.append(f"认领的应是 result 信封，实得 {env.kind!r}")
    claimed = env.payload.get("task_id")
    if claimed != task.id:
        problems.append(f"task_id 对不上：result 认领的是 {claimed!r}，本地 task 是 {task.id!r}")
    if env.payload.get("ok") is not True:
        problems.append(f"外部判定这件活**没做成**(ok={env.payload.get('ok')!r})：{env.payload.get('summary')!r}")
    return problems


# ── 一次完整往返(供 demo / selftest / emit 复用) ────────────────────────
def _roundtrip(pkg: dict) -> tuple[interop.Envelope, interop.Envelope, list[str]]:
    """跑一次往返:包→task→(模拟外部回送的)result→认领。回 (task, result, problems)。

    这里的 result 是**本地模拟**外部 agent 的回送——真实往返里它来自领地之外，
    但信封长相、对账规则与这里**一模一样**(走的就是 interop 这门方言)。
    """
    task = task_from_handoff(pkg)
    result = interop.make_result(
        task.id, True,
        f"已按交接包续完：{pkg.get('title')}",
        metrics={"verify_cmds": len(pkg.get("verify") or []), "next_done": len(pkg.get("next") or [])},
        source="external-agent",
    )
    problems = claim_result(interop.encode(result), task)
    return task, result, problems


def _sample_handoff() -> dict:
    """造一只**自包含、无副作用**的合成交接包(自检用，绝不碰 git / 账本)。"""
    return {
        "kind": "handoff",
        "id": "20260526-000000-sample",
        "ts": "2026-05-26T00:00:00",
        "status": handoff.STATUS_OPEN,
        "title": "给 interop 的 decode 补一版「尾随逗号容错」用例",
        "why": "外部工具偶发回送带尾随逗号的 JSON，decode 当场崩会让一次外包往返白跑。",
        "done": ["定位到 decode 走 json.loads，尾随逗号会抛 JSONDecodeError",
                 "确认 validate 这层不背锅，问题在解析前"],
        "next": ["在 decode 解析失败时尝试一次容错清洗后重解析",
                 "补一条 selftest 用例:带尾随逗号的 result 能被认领"],
        "risk": ["容错不能宽到吞掉真正畸形的 JSON——只清尾随逗号，别自作主张补全"],
        "verify": ["python interop.py --quiet", "python handoff_interop.py --quiet"],
        "snapshot": {"branch": "crab/sample", "head": "0000000",
                     "head_subject": "(sample)", "dirty_count": 0, "untracked_count": 0,
                     "dirty_files": [], "ahead": 0, "behind": 0},
    }


def _pick_real_handoff() -> dict | None:
    """挑一只**真实**开着的交接包(取最新)；取不到/出错都回 None，绝不抛。"""
    try:
        rows = handoff.open_packages()
    except Exception:
        return None
    if not rows:
        return None
    return sorted(rows, key=lambda r: r.get("ts", ""), reverse=True)[0]


# ── 自检 ─────────────────────────────────────────────────────────────────
def _selftest() -> list[str]:
    """返回失败清单(空 = 全过)；全程无副作用,不碰 git / 账本 / 网络。"""
    fails: list[str] = []

    def check(cond: bool, why: str) -> None:
        if not cond:
            fails.append(why)

    pkg = _sample_handoff()

    # 1) 导出的 task 信封自身守约,且必需字段齐全。
    task = task_from_handoff(pkg)
    errs = interop.validate(task.to_dict())
    check(not errs, f"导出的 task 信封不守约：{errs}")
    check(task.kind == interop.KIND_TASK, "导出的不是 task 信封")

    # 2) 关键映射没丢:动机/源包 id/验收命令都进了信封。
    check(task.payload["intent"] == pkg["why"], "intent 没映射到包的 why")
    check(task.payload.get("handoff_id") == pkg["id"], "handoff_id 没带上,认领时无从对账")
    check(all(c in task.payload["acceptance"] for c in pkg["verify"]),
          "verify 命令没进 acceptance,验收口径不客观")
    check(pkg["verify"][0] in task.payload.get("verify", []),
          "verify 命令清单没原样进 payload")

    # 3) 人话封面带齐三段式锚点(背景/请你做什么/怎么算做完)。
    cover = task.payload.get("cover", "")
    for anchor in ("## 背景", "## 我想请你做什么", "## 怎么算做完"):
        check(anchor in cover, f"封面缺三段式锚点 {anchor!r}")

    # 4) 往返:模拟外部回送的 result 能被认领回原 task（task.id 每次新生成，
    #    故对账用 _roundtrip 内部那条 task；认领是否对得上已收进 problems）。
    _, result, problems = _roundtrip(pkg)
    check(not problems, f"正常往返竟认领失败：{problems}")
    check(result.kind == interop.KIND_RESULT, "往返回送的不是 result 信封")

    # 5) 严:task_id 对不上的 result 必须被挡。
    wrong = interop.make_result("task-deadbeef", True, "张冠李戴", source="external-agent")
    p2 = claim_result(interop.encode(wrong), task)
    check(any("task_id 对不上" in s for s in p2), "task_id 错配的 result 竟被认领放行")

    # 6) 严:ok=false 的 result 应被判「没做成」(可记账,但认领不算通过)。
    failed = interop.make_result(task.id, False, "verify 第二条没过", source="external-agent")
    p3 = claim_result(interop.encode(failed), task)
    check(any("没做成" in s for s in p3), "ok=false 的 result 没被判为未做成")

    # 7) 严:畸形 JSON 必须被 decode 挡在门口,不得让认领崩。
    p4 = claim_result("{not json", task)
    check(any("不守约" in s for s in p4), "畸形 result 竟没被挡在门口")

    # 8) 没写 verify 的包:验收口径如实喊出「无法定义」,不假装可验收。
    bare = dict(pkg)
    bare["verify"] = []
    check("无法定义客观验收" in acceptance_for(bare), "缺 verify 的包没如实喊出验收无从谈起")

    return fails


# ── 渲染 / demo ──────────────────────────────────────────────────────────
def _print_export(pkg: dict) -> None:
    task = task_from_handoff(pkg)
    print(f"📤 把交接包 {pkg.get('id','?')[:15]} 铸成 interop task 信封：\n")
    print("── 人话封面(给领地之外那只手) ──")
    print(task.payload.get("cover", "(无)"))
    print("\n── task 信封(走 interop 方言,外部 agent 直接 decode) ──")
    print(interop.encode(task))
    if not (pkg.get("verify")):
        print("\n⚠️ 这只包没写 verify 命令——外包前请先补,否则验收无从谈起。")


def _demo() -> None:
    pkg = _pick_real_handoff()
    where = "领地里真实开着的" if pkg else "合成的(领地里暂无开着的交接包)"
    if pkg is None:
        pkg = _sample_handoff()
    print(f"🤝📦🔌 一次真实外包往返样例（取自{where}交接包）：\n")
    task, result, problems = _roundtrip(pkg)
    print("📤 export — 把交接包铸成 task 发出去：")
    print("   " + interop.encode(task) + "\n")
    print("📊 result — 外部 agent 续完后回送结论：")
    print("   " + interop.encode(result) + "\n")
    print("📥 claim — 认领回原 task：", "✅ 对账通过" if not problems else f"❌ {problems}")


def _emit(path: str) -> None:
    pkg = _pick_real_handoff() or _sample_handoff()
    task, result, _ = _roundtrip(pkg)
    lines = [interop.encode(task), interop.encode(result)]
    pathlib.Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"📝 已落样例 JSONL(task + result 两行)→ {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="交接外包桥 🤝📦🔌：把真实交接包外包出去跑通往返。")
    ap.add_argument("--export", metavar="ID", help="把某只交接包铸成 task 信封并打印")
    ap.add_argument("--export-open", action="store_true", help="把最近一只开着的交接包铸成 task 信封")
    ap.add_argument("--demo", action="store_true", help="打印一次真实外包往返样例")
    ap.add_argument("--emit", metavar="PATH", help="把往返信封落成 JSONL 样例")
    ap.add_argument("--quiet", action="store_true", help="只在自检不过时说话(钩子 / CI)")
    args = ap.parse_args(argv)

    if args.export:
        pkg = handoff.find(args.export)
        if pkg is None:
            print(f"❌ 没找到交接包 {args.export!r}（试试 python handoff.py --list）")
            return 1
        _print_export(pkg)
        return 0
    if args.export_open:
        pkg = _pick_real_handoff()
        if pkg is None:
            print("📦 领地里没有开着的交接包——用 handoff.py --title 先封一只。")
            return 1
        _print_export(pkg)
        return 0
    if args.demo:
        _demo()
        return 0
    if args.emit:
        _emit(args.emit)
        return 0

    fails = _selftest()
    if fails:
        print(f"⚠️  交接外包桥自检发现 {len(fails)} 处不达约：\n")
        for f in fails:
            print(f"  ❌ {f}")
        print("\n先把桥修回守约，再把真活递出去。")
        return 1
    if not args.quiet:
        print("✅ 交接外包桥自检全过：真实/合成包→task→result→认领，往返闭环、坏消息挡门。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
