#!/usr/bin/env python3
"""黄金路径 · 端到端必经链 🛤️ —— 把最核心的生命线串成一条命令的整链验证。

为什么要有它：领地里已经有不少**单点**防线——checkup 看「器官还在不在」、
goldens 看「单条命令输出有没有变味」、smoke 看「README 的命令各自还跑不跑」。
但一只越长越复杂的螃蟹，最隐蔽的退化不在某个零件，而在**零件之间的接缝**：
启动写没写下审计？心跳有没有从「醒来」一路走到「沉淀」？审计的事件骨架还
连得上吗？失败时分流网兜不兜得住？这些「单测都绿、串起来却断了」的退化，
没有任何单点检查能抓到。

黄金路径专守这条接缝。它在一份**临时副本**里(绝不弄脏真实领地、绝不真打大脑)
把生命线**端到端**跑一遍，验证每一段都把接力棒交到了下一段手里：

    🪞 自检  →  🌊 启动+心跳  →  🧾 审计落盘(事件骨架有序)  →  ⏪ 回放  →  🚑 失败分流

然后把整链的**关键信号**(各段是否通、审计事件骨架、分流命中的错误码)固化成
一张「黄金指纹」。每次变更后重跑、逐项比对——主流程一旦悄悄断裂或骨架变形，
这里立刻红，逼着「核心生命线」始终是一条走得通的必经链。

零第三方依赖，纯标准库。

用法:
    python goldenpath.py            # 跑整条必经链，比对黄金指纹(退出码 0=通 / 1=断或变形)
    python goldenpath.py --update   # 确认当前链路正确后，(重新)录制黄金指纹
    python goldenpath.py --list     # 只列出这条链有哪几段
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent
GOLDEN = REPO_ROOT / "goldens" / "golden-path.json"

_PY = sys.executable

# 跑链时强制的环境：空 key=梦境模式(绝不真打大脑)、空白名单=默认能力集，
# 让「链路通不通」只取决于代码本身，而非本机 .env。
_DREAM_ENV = {
    "OPENCRAB_API_KEY": "",
    "OPENCRAB_CAPABILITIES": "",
    "OPENCRAB_AUTONOMY": "journal",   # 不借手改代码，只走最朴素的「写日志」生命线
    "PYTHONIOENCODING": "utf-8",
}

# 复制临时副本时跳过的东西：版本库、运行期记忆、缓存、真实 .env(免得带进真 key)。
_COPY_IGNORE = shutil.ignore_patterns(".git", "state", "__pycache__", ".env", "*.pyc")

# 这条必经链的**审计事件骨架**：一次完整的「醒来→沉淀」必须按此顺序出现这些事件。
# 它是生命线的脊椎——少一节、或顺序乱了，就说明主流程在某个接缝处断了。
REQUIRED_BACKBONE = [
    "startup",      # 启动：进程醒来，第一件事就该留下审计
    "tick_start",   # 心跳开始
    "decision",     # 本能闸门(体力)做出放行决定
    "intent",       # 生成意图(心脏)
    "act",          # 横行：把意图落成一篇航海日志
    "tick_done",    # 心跳收尾、沉淀
    "exit",         # 退出：once 模式干净收场
]

# 失败分流探针：喂一组**典型失败现场**，断言分流网把它们兜到预期的错误码。
# 守的是「失败时这只螃蟹仍知道自己错在哪、下一步怎么办」这道最后防线。
TRIAGE_PROBES = [
    ("auth", {"http_status": 401}, "E-BRAIN-AUTH"),
    ("ratelimit", {"http_status": 429}, "E-BRAIN-RATELIMIT"),
    ("selftest", {"message": "自测没过：py_compile 语法错误"}, "E-EVOLVE-SELFTEST"),
    ("merge", {"message": "merge conflict in crab.py"}, "E-EVOLVE-MERGE"),
    ("unknown", {"message": "天外飞仙般莫名其妙的一句话"}, "E-UNKNOWN"),
]


# ── 一段段的结论 ──────────────────────────────────────────────────────
class Stage:
    """链上一段的结论：通没通、一句人话、以及要进指纹比对的关键信号。"""

    def __init__(self, name: str, label: str) -> None:
        self.name = name
        self.label = label
        self.ok = False
        self.detail = ""
        self.signal = None   # 进黄金指纹比对的稳定信号(已抹去噪声)

    def done(self, ok: bool, detail: str, signal=None) -> "Stage":
        self.ok, self.detail, self.signal = ok, detail, signal
        return self


def _run(argv: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    """在 cwd 下按梦境模式跑一条命令，返回 (退出码, 合并的 stdout+stderr)。"""
    env = {**os.environ, **_DREAM_ENV}
    try:
        proc = subprocess.run(argv, cwd=str(cwd), env=env,
                              capture_output=True, text=True, timeout=120)
        return proc.returncode, proc.stdout + proc.stderr
    except Exception as e:   # 命令本身起不来，也是一种「链断了」
        return -1, f"<执行异常> {e!r}"


def _read_backbone(sandbox: pathlib.Path) -> list[str]:
    """读临时副本里今天的审计 JSONL，按时间序抽出事件名(即链路的脊椎)。"""
    day = datetime.date.today().isoformat()
    path = sandbox / "state" / "audit" / f"{day}.jsonl"
    if not path.exists():
        return []
    events: list[str] = []
    for line in path.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line).get("event", "?"))
        except Exception:
            continue
    return events


def _is_ordered_subseq(needle: list[str], haystack: list[str]) -> bool:
    """needle 是否按序(可不连续)地出现在 haystack 中——校验脊椎完整且顺序对。"""
    it = iter(haystack)
    return all(x in it for x in needle)


# ── 端到端跑一遍这条必经链 ────────────────────────────────────────────
def walk() -> list[Stage]:
    """在临时副本里把生命线端到端跑一遍，返回每一段的结论。

    五段一次性在**同一份副本**上跑出来：checkup 与 once 是子进程，审计/回放
    复用同一份副本的产物，失败分流则在本进程内直接探。一次副本、一条链。
    """
    s_check = Stage("checkup", "🪞 自检：器官齐不齐")
    s_tick = Stage("tick", "🌊 启动+心跳：从醒来走到沉淀")
    s_audit = Stage("audit", "🧾 审计落盘：事件骨架有序")
    s_replay = Stage("replay", "⏪ 回放：审计读得回来")
    s_triage = Stage("triage", "🚑 失败分流：兜底网还在")

    with tempfile.TemporaryDirectory(prefix="opencrab-goldenpath-") as tmp:
        sandbox = pathlib.Path(tmp) / "repo"
        shutil.copytree(REPO_ROOT, sandbox, ignore=_COPY_IGNORE)

        # 1) 自检：起飞前先确认器官都在。
        code, out = _run([_PY, "checkup.py", "--quiet"], sandbox)
        tail = (out.strip().splitlines() or ["(无输出)"])[-1][:160]
        s_check.done(code == 0, f"退出码 {code}"
                     + ("" if code == 0 else f"：{tail}"), signal=(code == 0))

        # 2) 启动 + 一次心跳：生命线的主干，必须从「醒来」走到「沉淀完毕」。
        code, out = _run([_PY, "crab.py", "once"], sandbox)
        reached = "沉淀完毕" in out
        journals = list((sandbox / "journal").glob("*.md")) if (sandbox / "journal").exists() else []
        tick_ok = code == 0 and reached
        s_tick.done(tick_ok,
                    f"退出码 {code} · {'到达沉淀' if reached else '没到沉淀'} · "
                    f"产出日志 {len(journals)} 篇",
                    signal=tick_ok)

        # 3) 审计落盘：心跳必须留下一条有序的事件脊椎(接缝没断的硬证据)。
        backbone = _read_backbone(sandbox)
        spine_ok = _is_ordered_subseq(REQUIRED_BACKBONE, backbone)
        missing = [e for e in REQUIRED_BACKBONE if e not in backbone]
        s_audit.done(spine_ok,
                     ("骨架完整：" + "→".join(REQUIRED_BACKBONE)) if spine_ok
                     else f"骨架断裂，缺 {missing}；实际：{backbone}",
                     signal=backbone)   # 整条事件序列进指纹

        # 4) 回放：刚写下的审计必须能被原路读回、归纳出来。
        code, out = _run([_PY, "crab.py", "replay"], sandbox)
        replay_ok = code == 0 and "回放" in out
        s_replay.done(replay_ok, f"退出码 {code}"
                      + ("" if replay_ok else "：回放没把今天的审计读回来"),
                      signal=replay_ok)

    # 5) 失败分流：在本进程内探一组典型失败，确认分流网兜得住、错误码稳定。
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import errors
    hits = {name: errors.classify(**scene).code for name, scene, _ in TRIAGE_PROBES}
    wrong = [f"{name}: 期望 {want} 得 {hits[name]}"
             for name, _, want in TRIAGE_PROBES if hits[name] != want]
    s_triage.done(not wrong,
                  "全部命中预期错误码" if not wrong else "；".join(wrong),
                  signal=hits)

    return [s_check, s_tick, s_audit, s_replay, s_triage]


# ── 黄金指纹：把整链的关键信号固化下来，逐项比对 ──────────────────────
def fingerprint(stages: list[Stage]) -> dict:
    """从各段抽出**稳定信号**，组成可比对的黄金指纹(不含时间戳/路径等噪声)。"""
    return {st.name: st.signal for st in stages}


class Verdict:
    """一次必经链验证的结论。"""

    def __init__(self) -> None:
        self.stages: list[Stage] = []
        self.broken: list[str] = []        # 当场跑断的段
        self.drifted: list[str] = []       # 跑通了，但关键信号与黄金指纹不符
        self.missing_golden = False        # 还没录过黄金指纹
        self.diffs: dict[str, str] = {}

    @property
    def ok(self) -> bool:
        return not self.broken and not self.drifted and not self.missing_golden


def _load_golden() -> dict | None:
    if not GOLDEN.exists():
        return None
    try:
        return json.loads(GOLDEN.read_text("utf-8"))
    except Exception:
        return None


def verify() -> Verdict:
    """端到端跑一遍并与黄金指纹比对(不修改任何样本)。"""
    v = Verdict()
    v.stages = walk()
    v.broken = [st.name for st in v.stages if not st.ok]

    golden = _load_golden()
    if golden is None:
        v.missing_golden = True
        return v

    now = fingerprint(v.stages)
    for st in v.stages:
        want, got = golden.get(st.name), now.get(st.name)
        if want != got:
            v.drifted.append(st.name)
            v.diffs[st.name] = f"黄金 {want!r} → 现在 {got!r}"
    return v


def update() -> dict:
    """确认当前链路正确后，(重新)录制黄金指纹。"""
    fp = fingerprint(walk())
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(fp, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return fp


# ── CLI ─────────────────────────────────────────────────────────────
def _list() -> None:
    print("🛤️  黄金路径 · 必经链的各段：")
    template = walk.__doc__  # 仅取注释，不真跑
    del template
    for name, label in (("checkup", "🪞 自检：器官齐不齐"),
                        ("tick", "🌊 启动+心跳：从醒来走到沉淀"),
                        ("audit", "🧾 审计落盘：事件骨架有序"),
                        ("replay", "⏪ 回放：审计读得回来"),
                        ("triage", "🚑 失败分流：兜底网还在")):
        print(f"  · {name:<8} {label}")
    print("\n  审计事件脊椎：" + " → ".join(REQUIRED_BACKBONE))


def main() -> None:
    ap = argparse.ArgumentParser(description="opencrab 黄金路径 · 端到端必经链 🛤️")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--update", action="store_true",
                   help="确认当前链路正确后，(重新)录制黄金指纹")
    g.add_argument("--list", action="store_true", help="只列出这条链有哪几段(不执行)")
    args = ap.parse_args()

    if args.list:
        _list()
        return

    if args.update:
        fp = update()
        print(f"🛤️  已录制黄金指纹 → {GOLDEN.relative_to(REPO_ROOT)}")
        print("   关键信号：")
        for k, val in fp.items():
            print(f"     {k}: {json.dumps(val, ensure_ascii=False)}")
        print("   记得连同改动一起提交。")
        return

    v = verify()
    print("🛤️  opencrab 黄金路径 —— 核心生命线端到端必经链\n")
    for st in v.stages:
        print(f"  {'✅' if st.ok else '❌'} {st.label}")
        print(f"       {st.detail}")
        if st.name in v.diffs:
            print(f"       ↳ 指纹漂移：{v.diffs[st.name]}")
    print()

    if v.missing_golden:
        print("⚪ 还没有黄金指纹——先确认上面各段都 ✅，再 python goldenpath.py --update。")
        # 链本身若已跑断，仍按失败退出，挡住带病改动。
        sys.exit(0 if not v.broken else 1)

    if v.ok:
        print(f"🦀 必经链通畅：{len(v.stages)} 段全部接得上，且与黄金指纹一致。")
        sys.exit(0)

    msg = []
    if v.broken:
        msg.append(f"{len(v.broken)} 段跑断({', '.join(v.broken)})")
    if v.drifted:
        msg.append(f"{len(v.drifted)} 段指纹漂移({', '.join(v.drifted)})")
    print(f"⚠️  {'；'.join(msg)}——核心生命线退化了。"
          "若改动是有意为之、确认无误后 python goldenpath.py --update。")
    sys.exit(1)


if __name__ == "__main__":
    main()
