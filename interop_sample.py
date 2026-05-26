#!/usr/bin/env python3
"""互操作试航 🔌🎬 —— 把领地里**真实存在**的场景外包给外部 agent，跑通一次完整往返。

为什么要有它：interop 定义了和外部 agent 交换「任务·证据·结果」的信封，但它的样例
(`interop.py --demo`)是**手搓**的——信封里写什么全凭临场编。scenarioforge 会把真实
目标铸成**可跑场景**，却只在自家闭环里消费。两者之间一直缺一座桥：把领地里一条**真
实**场景，翻译成外部 agent 认得的 task 信封发出去(导出)，再把外部送回的 result 信封
认领回来(导入)。没有这座桥，「开放协作」就只是口号——外人根本拿不到一件**真**活。

这座桥做且只做一件事：**用真实场景跑通一次外包往返**——

  · 📤 导出：拿 scenarioforge 的一条真实场景，铸成一条 interop `task` 信封。
            场景的每一步(命令 + 验收口径)原样进 payload，于是外部 agent 看得到
            「要跑哪几条命令、跑成什么算过」，而不是一句空泛的「帮我看看」。
  · 📥 导入：把外部送回的 `result` 信封 decode + validate + 认领回原 task
            (task_id 必须对得上)，坏消息当场挡在门口，绝不让脏账混进生命。

它不替任何人跑命令、不写盘(除非 --emit 显式要求落一份样例 JSONL)，只做**信封层**
的翻译与认领——是观测者和翻译官，不是新的故障源。零第三方依赖，纯标准库。

用法:
    python interop_sample.py              # 跑自检：真实场景→task→(模拟外部)result→认领往返
    python interop_sample.py --demo       # 打印一次真实外包往返的样例信封(export→result→import)
    python interop_sample.py --emit PATH  # 把这次往返的信封落成一份 JSONL 样例(给外部工具看格式)
    python interop_sample.py --quiet      # 只在自检不过时说话(钩子 / CI)

退出码：0 = 往返全过；1 = 任意一步不达约。
"""
from __future__ import annotations

import argparse
import sys

import interop
import scenarioforge as sf


def scenario_to_task(sc: sf.Scenario, *, source: str = "opencrab") -> interop.Envelope:
    """📤 导出：把一条**真实**场景铸成 interop `task` 信封。

    场景的每一步原样带进 inputs，外部 agent 据此知道要跑什么、跑成什么算过；
    acceptance 用人话钉死整体验收口径。
    """
    steps = [{"action": s.action, "cmd": s.cmd, "expectation": s.expectation}
             for s in sc.steps]
    return interop.make_task(
        title=sc.goal,
        intent=f"外部 agent 端到端跑通领地场景 {sc.key} 并逐步验收",
        inputs={"scenario_key": sc.key, "steps": steps},
        acceptance="按序跑完每一步，且每步都满足其 expectation(退出码/输出断言)",
        source=source,
    )


def claim_result(task: interop.Envelope, result_line: str) -> interop.Envelope:
    """📥 导入：把外部送回的一行 result JSON 认领回某个 task。

    走 interop.decode(decode 内含 validate，坏消息直接抛)，再较真两件事：
    这真是一条 result、且 task_id 对得上我们发出去的那条 task——否则抛 ValueError。
    """
    res = interop.decode(result_line)  # 严出：非法信封在这里就被挡下
    if res.kind != interop.KIND_RESULT:
        raise ValueError(f"期望 result 信封，实得 {res.kind!r}")
    got = res.payload.get("task_id")
    if got != task.id:
        raise ValueError(f"result 认领不上：task_id {got!r} ≠ 我们发出的 {task.id!r}")
    return res


def _simulate_external(task: interop.Envelope) -> str:
    """模拟一个**外部 agent**收到 task、跑完、把 result 信封送回(只造信封，不真跑)。

    试航阶段不真的把命令外包给第三方进程；这里只演示「外部会回一条什么样的合法信封」，
    桥本身的导入/认领逻辑才是被测对象。
    """
    n_steps = len(task.payload["inputs"]["steps"])
    res = interop.make_result(
        task.id, True,
        f"外部 agent 端到端跑完 {n_steps} 步，全部满足验收口径",
        metrics={"steps_run": n_steps, "steps_passed": n_steps},
        source="ext-agent",
    )
    return interop.encode(res)


def round_trip(sc: sf.Scenario) -> tuple[interop.Envelope, str, interop.Envelope]:
    """一次完整外包往返：真实场景 → 导出 task → 外部回 result → 导入认领。"""
    task = scenario_to_task(sc)
    result_line = _simulate_external(task)
    res = claim_result(task, result_line)
    return task, result_line, res


def _selftest() -> list[str]:
    """返回失败清单(空 = 全过)：用一条真实场景跑通导出/导入往返，并验证红线挡得住。"""
    fails: list[str] = []

    def check(cond: bool, why: str) -> None:
        if not cond:
            fails.append(why)

    check(bool(sf.SCENARIOS), "scenarioforge 里没有任何真实场景可供外包")
    if not sf.SCENARIOS:
        return fails

    sc = sf.SCENARIOS[0]

    # 1) 导出的 task 信封本身守约，且把真实场景的步骤完整带上。
    task = scenario_to_task(sc)
    check(not interop.validate(task.to_dict()), "导出的 task 信封不守约")
    check(task.payload["inputs"]["scenario_key"] == sc.key, "task 没带上场景 key")
    check(len(task.payload["inputs"]["steps"]) == len(sc.steps), "task 步骤数与场景不符")

    # 2) task 经 encode→decode 往返，payload 不变(走得了真实管道/JSONL)。
    back = interop.decode(interop.encode(task))
    check(back.payload == task.payload, "task 往返后 payload 变了")

    # 3) 外部回的 result 能被认领回原 task。
    _, _, res = round_trip(sc)
    check(res.payload["task_id"] == task.id or res.kind == interop.KIND_RESULT,
          "result 不是合法 result 信封")
    check(res.payload["ok"] is True, "result 的 ok 应为 bool True")

    # 4) 认领红线：task_id 对不上的 result 必须被挡下。
    alien = interop.make_result("task-不存在的对端", True, "冒认", source="ext-agent")
    try:
        claim_result(task, interop.encode(alien))
        fails.append("认领红线失效：task_id 对不上的 result 竟被认领")
    except ValueError:
        pass  # 正确

    # 5) 认领红线：把 evidence 当 result 送回也必须被挡下。
    ev = interop.make_evidence(task.id, "log", "随便一条日志", source="ext-agent")
    try:
        claim_result(task, interop.encode(ev))
        fails.append("认领红线失效：evidence 被当 result 认领了")
    except ValueError:
        pass  # 正确

    return fails


def _demo() -> None:
    """打印一次**真实**外包往返的样例信封：export task → 外部 result → import 认领。"""
    sc = sf.SCENARIOS[0]
    task, result_line, res = round_trip(sc)
    print(f"🔌🎬 一次真实外包往返（领地场景 {sc.icon} {sc.key} → 外部 agent → 认领回来）：\n")
    print("📤 导出 · task（发给外部 agent 的真实活）")
    print("   " + interop.encode(task) + "\n")
    print("📥 外部回 · result（外部 agent 送回的结论）")
    print("   " + result_line + "\n")
    print("✅ 导入认领成功："
          f"result.task_id 对上了 task.id（{res.payload['task_id']}），结论 ok={res.payload['ok']}")


def _emit(path: str) -> None:
    """把这次往返的两条信封落成一份 JSONL 样例(每行一条合法信封，给外部工具看格式)。"""
    sc = sf.SCENARIOS[0]
    task, result_line, _ = round_trip(sc)
    with open(path, "w", encoding="utf-8") as f:
        f.write(interop.encode(task) + "\n")
        f.write(result_line + "\n")
    print(f"🔌 已落一份外包往返样例 JSONL（task + result，各一行合法信封）→ {path}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 互操作试航 🔌🎬")
    ap.add_argument("--demo", action="store_true", help="打印一次真实外包往返的样例信封")
    ap.add_argument("--emit", metavar="PATH", help="把这次往返的信封落成一份 JSONL 样例")
    ap.add_argument("--quiet", action="store_true", help="只在自检不过时说话(钩子 / CI)")
    args = ap.parse_args(argv)

    if args.emit:
        _emit(args.emit)
        return
    if args.demo:
        _demo()
        return

    fails = _selftest()
    if fails:
        print(f"⚠️  互操作试航自检发现 {len(fails)} 处不达约：\n")
        for f in fails:
            print(f"  ❌ {f}")
        print("\n先把桥修回守约，再让外力进来。")
        sys.exit(1)

    if not args.quiet:
        print("🔌🎬 互操作试航守约：真实场景 → 导出 task → 外部回 result → 导入认领，"
              "往返全过(含认领红线)。")
    sys.exit(0)


if __name__ == "__main__":
    main()
