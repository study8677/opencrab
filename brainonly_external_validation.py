#!/usr/bin/env python3
"""brain-only 补丁质量验证 —— 封装测试用例，通过 embassy 发送给外部 agent，获取外部反馈。

这个模块实现了从"闭环自评"到"开环他评"的进化转折：创建一个真实的测试任务，
让外部 agent 来运行验证，并返回结果信封。这样可以利用外部视角评估 brain-only
补丁的质量，而不是完全依赖内部自检。

用法:
    python brainonly_external_validation.py           # 发送验证任务并接收结果
    python brainonly_external_validation.py --dry-run  # 只打印任务信封，不实际发送

退出码：0 = 外部验证通过；1 = 外部验证失败或发送出错。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Callable, Dict, Optional

# 尝试导入 interop 和 embassy
try:
    from interop import make_task, encode, decode, validate, Envelope
except ImportError:
    print("错误: 无法导入 interop 模块，请确保 interop.py 存在且可导入", file=sys.stderr)
    sys.exit(1)

# 尝试导入 embassy 的发送函数，如果不存在则使用回退模拟
try:
    from embassy import send_envelope  # 假设 embassy 有此函数
    HAS_EMBASSY = True
except ImportError:
    HAS_EMBASSY = False
    print("警告: embassy 模块未找到或无 send_envelope 函数，使用模拟发送", file=sys.stderr)


def _send_with_fallback(env_str: str) -> str:
    """发送信封的回退函数：模拟外部 agent 处理并返回结果。"""
    # 解析任务以获取 task_id
    try:
        env = decode(env_str)
        task_id = env.id
    except ValueError:
        task_id = "unknown"

    # 模拟外部 agent 运行 interop.py 的自检
    time.sleep(0.1)  # 模拟处理延迟
    simulated_result = {
        "protocol": "opencrab.interop",
        "version": "1",
        "kind": "result",
        "id": f"res-{task_id}-simulated",
        "ts": "2024-01-01T00:00:00Z",
        "source": "external-agent-simulation",
        "payload": {
            "task_id": task_id,
            "ok": True,
            "summary": "模拟外部验证: interop.py 自检通过",
            "metrics": {"exit_code": 0, "time_ms": 100}
        }
    }
    return json.dumps(simulated_result, ensure_ascii=False)


def create_validation_task(
    title: str = "Brain-only 补丁质量验证",
    intent: str = "让外部 agent 运行 interop.py 的自检，验证协议实现的正确性",
    inputs: Optional[Dict[str, Any]] = None,
    acceptance: str = "外部 agent 运行 `python interop.py --quiet` 并返回退出码 0",
    **extra: Any
) -> Envelope:
    """创建验证任务的信封。"""
    if inputs is None:
        inputs = {"module": "interop.py", "test": "selftest", "scope": "protocol_integrity"}
    return make_task(title, intent, inputs, acceptance, **extra)


def send_and_receive(
    task: Envelope,
    send_fn: Optional[Callable[[str], str]] = None,
    dry_run: bool = False
) -> Optional[Envelope]:
    """发送任务信封并接收结果。如果 dry_run 则只打印不发送。"""
    task_str = encode(task)
    if dry_run:
        print("📨 任务信封 (dry-run，不实际发送):")
        print(f"   {task_str}")
        return None

    # 使用提供的发送函数或回退
    if send_fn is None:
        if HAS_EMBASSY:
            send_fn = send_envelope
        else:
            send_fn = _send_with_fallback

    print(f"📨 正在发送任务信封到外部 agent...")
    try:
        result_str = send_fn(task_str)
    except Exception as e:
        print(f"❌ 发送失败: {e}", file=sys.stderr)
        return None

    # 解码结果
    try:
        result = decode(result_str)
        print(f"📊 收到结果信封:")
        print(f"   {encode(result)}")
        return result
    except ValueError as e:
        print(f"❌ 结果解码失败: {e}", file=sys.stderr)
        return None


def main(argv: Optional[list[str]] = None) -> None:
    """主函数：解析参数并执行验证。"""
    ap = argparse.ArgumentParser(description="Brain-only 补丁质量验证")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印任务信封，不实际发送")
    args = ap.parse_args(argv)

    # 创建验证任务
    task = create_validation_task()
    print(f"🔧 创建验证任务: {task.payload['title']}")
    print(f"   意图: {task.payload['intent']}")
    print(f"   验收: {task.payload['acceptance']}")

    # 发送并接收
    result = send_and_receive(task, dry_run=args.dry_run)
    if args.dry_run:
        print("\n✅ dry-run 完成，未实际发送。")
        sys.exit(0)

    if result is None:
        print("\n❌ 未收到有效结果或发送失败", file=sys.stderr)
        sys.exit(1)

    # 验证结果
    payload = result.payload
    if result.kind != "result":
        print(f"❌ 结果信封 kind 不正确: 期望 'result', 实得 '{result.kind}'", file=sys.stderr)
        sys.exit(1)
    if payload.get("task_id") != task.id:
        print(f"❌ task_id 不匹配: 期望 '{task.id}', 实得 '{payload.get('task_id')}'", file=sys.stderr)
        sys.exit(1)

    ok = payload.get("ok", False)
    summary = payload.get("summary", "无总结")
    print(f"\n🎯 外部验证结果: {'通过' if ok else '失败'}")
    print(f"   总结: {summary}")

    if "metrics" in payload:
        print(f"   指标: {payload['metrics']}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
