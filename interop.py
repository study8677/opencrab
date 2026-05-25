#!/usr/bin/env python3
"""互通协议 🔌 —— 与外部 agent / eval 工具交换「任务·证据·结果」的最小 JSON 信封。

为什么要有它：opencrab 已经会自己定目标、自己拆活、自己验收，但它的进化目前是
**闭门**的——所有任务、证据、结论都只在自己这一圈模块之间流动。要真正借外力进化
（让外部 agent 帮着做一段活、让外部 eval 工具替它打一次分），就得先有一门**双方
都认的方言**：一条消息长什么样、必须带哪些字段、版本怎么标、对方吐回来的东西怎么
认领。没有这层约定，每接一个外部工具就要现编一套格式，迟早各说各话、对不上账。

interop 不替任何人干活，它只定义并守住**信封**本身：

  · 📨 三种消息(kind)，覆盖一次外包协作的最小闭环——
      - task     ：把一件要做/要评的活**发出去**(描述 + 输入 + 验收口径)。
      - evidence ：把支撑某个判断的**证据**随任务/结果附上(日志、指标、产物指针)。
      - result   ：外部把**结论**送回来(成功与否 + 度量 + 关联的 task_id)。
  · 🧬 每条消息都裹在统一信封里：protocol/version/kind/id/ts/source/payload，
    于是「这是哪版协议、谁发的、什么时候、是哪类、关联谁」一眼可认、跨工具稳定。
  · ✅ encode / decode / validate 三件套是这门方言的**单一真相源**：
    本地发出去的、外面送回来的，都走同一套编解码与校验，坏消息当场被挡在门口，
    绝不让格式漂移的脏数据混进生命的账本。

设计原则：信封**薄**——只钉死互通必需的字段，payload 内部留给具体工具自由发挥；
向后兼容**宽进严出**——decode 容忍未知附加字段(未来扩展不破老消息)，validate 只
对必需字段较真。零第三方依赖，纯标准库。

用法:
    python interop.py            # 跑一遍自检：造三类消息、编解码往返、校验红线
    python interop.py --demo     # 打印一次完整外包闭环的样例信封(task→evidence→result)
    python interop.py --schema   # 导出协议 schema(给外部工具 / health 消费)
    python interop.py --quiet    # 只在自检不过时说话(适合钩子 / CI)

退出码：0 = 自检全过；1 = 任意一步不达约。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import sys
import uuid

# ── 协议身份：握手时双方先认这两个常量 ──────────────────────────────────
PROTOCOL = "opencrab.interop"   # 协议名：认出「这是不是冲我们这门方言来的」
VERSION = "1"                   # 协议大版本：不兼容的改动才 +1

# ── 三种消息：一次外包协作的最小闭环 ────────────────────────────────────
KIND_TASK = "task"          # 📨 把一件要做/要评的活发出去
KIND_EVIDENCE = "evidence"  # 🧾 附上支撑某判断的证据
KIND_RESULT = "result"      # 📊 外部把结论送回来
KINDS = (KIND_TASK, KIND_EVIDENCE, KIND_RESULT)

# 每种消息 payload 里**必须**出现的字段(宽进严出：只对这些较真，余者随意附加)。
_REQUIRED_PAYLOAD: dict[str, tuple[str, ...]] = {
    KIND_TASK: ("title", "intent", "inputs", "acceptance"),
    KIND_EVIDENCE: ("task_id", "kind_of", "body"),
    KIND_RESULT: ("task_id", "ok", "summary"),
}


def _now() -> str:
    """统一的 UTC ISO 时间戳(秒级、带 Z)，让跨工具的时间可比。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix: str) -> str:
    """带类型前缀的短 id，便于一眼认出是哪类消息(task-…/ev-…/res-…)。"""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclasses.dataclass(frozen=True)
class Envelope:
    """一条互通消息的统一信封：薄壳裹住「谁、何时、哪类、关联谁」，payload 留给内容。"""
    kind: str                       # task / evidence / result 之一
    payload: dict                   # 该 kind 的正文(必含 _REQUIRED_PAYLOAD[kind])
    id: str = ""                    # 消息 id，留空则按 kind 自动生成
    ts: str = ""                    # UTC 时间戳，留空则取当下
    source: str = "opencrab"        # 发信方标识(本地默认 opencrab)
    protocol: str = PROTOCOL
    version: str = VERSION

    def __post_init__(self) -> None:
        # frozen dataclass：要改字段须走 object.__setattr__。
        if not self.id:
            prefix = {"task": "task", "evidence": "ev", "result": "res"}.get(self.kind, "msg")
            object.__setattr__(self, "id", _new_id(prefix))
        if not self.ts:
            object.__setattr__(self, "ts", _now())

    def to_dict(self) -> dict:
        """信封→纯 dict(字段顺序稳定，便于人读与 diff)。"""
        return {
            "protocol": self.protocol,
            "version": self.version,
            "kind": self.kind,
            "id": self.id,
            "ts": self.ts,
            "source": self.source,
            "payload": self.payload,
        }


# ── 构造：本地往外发消息时，用这三个 builder，免得手搓信封漏字段 ──────────
def make_task(title: str, intent: str, inputs: dict, acceptance: str,
              *, source: str = "opencrab", **extra) -> Envelope:
    """造一条 task：把一件要做/要评的活描述清楚——干什么、喂什么、怎么算过。

    extra 里的键并入 payload，留给具体工具自由扩展(如 budget/deadline)。
    """
    payload = {"title": title, "intent": intent, "inputs": dict(inputs),
               "acceptance": acceptance, **extra}
    return Envelope(kind=KIND_TASK, payload=payload, source=source)


def make_evidence(task_id: str, kind_of: str, body, *,
                  source: str = "opencrab", **extra) -> Envelope:
    """造一条 evidence：给某个 task/result 附上一份证据。

    kind_of 是证据的体裁(log / metric / artifact / note…)，body 是其正文/指针。
    """
    payload = {"task_id": task_id, "kind_of": kind_of, "body": body, **extra}
    return Envelope(kind=KIND_EVIDENCE, payload=payload, source=source)


def make_result(task_id: str, ok: bool, summary: str, *,
                metrics: dict | None = None, source: str = "external",
                **extra) -> Envelope:
    """造一条 result：把某个 task 的结论送回——成没成、一句话总结、可选度量。"""
    payload: dict = {"task_id": task_id, "ok": bool(ok), "summary": summary}
    if metrics is not None:
        payload["metrics"] = dict(metrics)
    payload.update(extra)
    return Envelope(kind=KIND_RESULT, payload=payload, source=source)


# ── 编解码 + 校验：本门方言的单一真相源(本地发的、外面来的都走这里) ──────
def encode(env: Envelope) -> str:
    """信封→一行 JSON 文本(可直接写进 JSONL / 走管道 / 进 HTTP body)。"""
    return json.dumps(env.to_dict(), ensure_ascii=False, sort_keys=False)


def validate(obj: dict) -> list[str]:
    """校验一个**纯 dict**是否守约；返回违规清单(空列表 = 守约)。

    宽进严出：只对协议必需字段较真，未知附加字段一律放行(留给未来扩展)。
    """
    errs: list[str] = []
    if not isinstance(obj, dict):
        return [f"信封须是对象，实得 {type(obj).__name__}"]
    if obj.get("protocol") != PROTOCOL:
        errs.append(f"protocol 须为 {PROTOCOL!r}，实得 {obj.get('protocol')!r}")
    if str(obj.get("version", "")) != VERSION:
        errs.append(f"version 须为 {VERSION!r}，实得 {obj.get('version')!r}")
    kind = obj.get("kind")
    if kind not in KINDS:
        errs.append(f"kind 须是 {KINDS} 之一，实得 {kind!r}")
    for field in ("id", "ts", "source"):
        if not obj.get(field):
            errs.append(f"信封字段 {field} 不可为空")
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        errs.append(f"payload 须是对象，实得 {type(payload).__name__}")
    elif kind in _REQUIRED_PAYLOAD:
        for field in _REQUIRED_PAYLOAD[kind]:
            if field not in payload:
                errs.append(f"{kind} 的 payload 缺必需字段 {field!r}")
    return errs


def decode(text: str) -> Envelope:
    """一行 JSON 文本→Envelope；解析失败或不守约都抛 ValueError(把坏消息挡在门口)。

    宽进：信封里的未知附加字段被无害忽略(只取协议认得的部分重建 Envelope)，
    于是对方用更新的小版本加了字段，老 decode 也不至于崩。
    """
    try:
        obj = json.loads(text)
    except Exception as e:
        raise ValueError(f"不是合法 JSON：{e}") from e
    errs = validate(obj)
    if errs:
        raise ValueError("消息不守约：" + "；".join(errs))
    return Envelope(
        kind=obj["kind"],
        payload=obj["payload"],
        id=obj["id"],
        ts=obj["ts"],
        source=obj["source"],
        protocol=obj["protocol"],
        version=str(obj["version"]),
    )


def schema() -> dict:
    """导出协议 schema(纯数据，给外部工具 / health 消费)。"""
    return {
        "protocol": PROTOCOL,
        "version": VERSION,
        "envelope_fields": ["protocol", "version", "kind", "id", "ts", "source", "payload"],
        "kinds": {k: list(_REQUIRED_PAYLOAD[k]) for k in KINDS},
        "note": "宽进严出：decode 容忍未知附加字段，validate 只校验必需字段。",
    }


# ── 自检：造三类消息、编解码往返、校验红线，一步不过即违约 ────────────────
def _selftest() -> list[str]:
    """返回失败清单(空 = 全过)；每条都是自给自足、无副作用的真实调用。"""
    fails: list[str] = []

    def check(cond: bool, why: str) -> None:
        if not cond:
            fails.append(why)

    # 1) 三个 builder 造出的信封，自身就该守约。
    task = make_task("修一个解析 bug", "让 decode 容忍尾随逗号",
                     {"file": "interop.py"}, "新增用例通过且不破老用例")
    ev = make_evidence(task.id, "metric", {"tests_passed": 12})
    res = make_result(task.id, True, "已修复并通过", metrics={"latency_ms": 8})
    for env in (task, ev, res):
        errs = validate(env.to_dict())
        check(not errs, f"{env.kind} builder 造出的信封不守约：{errs}")

    # 2) 编解码往返：encode 后 decode 回来，关键字段不变。
    back = decode(encode(task))
    check(back.kind == task.kind and back.id == task.id, "task 往返后 kind/id 变了")
    check(back.payload == task.payload, "task 往返后 payload 变了")

    # 3) result 关联回 task，且 ok 被规整成 bool。
    check(res.payload["task_id"] == task.id, "result 没正确关联回 task_id")
    check(res.payload["ok"] is True, "result 的 ok 须为 bool True")

    # 4) 宽进：未知附加字段不该让 decode 崩，且被无害忽略。
    d = task.to_dict()
    d["future_field"] = {"whatever": 1}
    try:
        wide = decode(json.dumps(d, ensure_ascii=False))
        check(not hasattr(wide, "future_field"), "未知字段不该污染 Envelope")
    except Exception as e:
        fails.append(f"宽进失败：未知附加字段让 decode 崩了：{e}")

    # 5) 严出：坏消息必须被挡在门口。
    bad_cases = [
        ("非 JSON", "{not json"),
        ("协议不符", json.dumps({"protocol": "x", "version": VERSION, "kind": "task",
                              "id": "i", "ts": "t", "source": "s", "payload": {}})),
        ("版本不符", json.dumps({"protocol": PROTOCOL, "version": "999", "kind": "task",
                              "id": "i", "ts": "t", "source": "s", "payload": {}})),
        ("未知 kind", json.dumps({"protocol": PROTOCOL, "version": VERSION, "kind": "huh",
                               "id": "i", "ts": "t", "source": "s", "payload": {}})),
        ("缺必需字段", json.dumps({"protocol": PROTOCOL, "version": VERSION, "kind": "task",
                               "id": "i", "ts": "t", "source": "s", "payload": {"title": "x"}})),
    ]
    for label, text in bad_cases:
        try:
            decode(text)
            fails.append(f"严出失败：坏消息「{label}」竟被 decode 放行")
        except ValueError:
            pass  # 正确：坏消息被挡下

    return fails


def _demo() -> None:
    """打印一次完整外包闭环的样例信封：task → evidence → result。"""
    task = make_task(
        title="给 migration.py 的 JSONL 账本补一版兼容性测试",
        intent="确保 schema 演进后老账本仍读得回来",
        inputs={"target": "migration.py", "ledgers": ["state/audit.jsonl"]},
        acceptance="新增测试覆盖 v0→v1 迁移且全绿，老用例不回归",
        budget="≤ 30min",
    )
    ev = make_evidence(task.id, "log", "pytest -q → 18 passed in 0.42s")
    res = make_result(task.id, True, "迁移测试已补齐并通过",
                      metrics={"new_tests": 4, "coverage_delta": "+3%"})
    print("🔌 一次外包协作的最小闭环（task → evidence → result）：\n")
    for label, env in (("📨 task", task), ("🧾 evidence", ev), ("📊 result", res)):
        print(f"{label}")
        print("   " + encode(env))
        print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 互通协议 🔌")
    ap.add_argument("--demo", action="store_true", help="打印一次完整外包闭环的样例信封")
    ap.add_argument("--schema", action="store_true", help="导出协议 schema(纯数据)")
    ap.add_argument("--quiet", action="store_true", help="只在自检不过时说话(适合钩子 / CI)")
    args = ap.parse_args(argv)

    if args.schema:
        print(json.dumps(schema(), ensure_ascii=False, indent=2))
        return
    if args.demo:
        _demo()
        return

    fails = _selftest()
    if fails:
        print(f"⚠️  互通协议自检发现 {len(fails)} 处不达约：\n")
        for f in fails:
            print(f"  ❌ {f}")
        print("\n先把信封改回守约，再让外力进来。")
        sys.exit(1)

    if not args.quiet:
        print(f"🔌 互通协议守约：{PROTOCOL} v{VERSION}，"
              f"{len(KINDS)} 类消息(task/evidence/result)编解码往返 + 宽进严出全部通过。")
    sys.exit(0)


if __name__ == "__main__":
    main()
