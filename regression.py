#!/usr/bin/env python3
"""统一回归验证链 🧪🛤️ —— 一条命令把「防退化」的两道防线一起跑完。

opencrab 防退化一度散在两处，各看一层、各有各的报告：
  · `goldens.py`    回归快照：把关键命令的标准输出/错误/退出码固化成黄金样本，
                    逐字比对，专抓「命令还能跑、退出码还是 0，可输出已经变味」；
  · 黄金路径(本文件) 在临时副本里把核心生命线端到端跑一遍
                    (自检→启动+心跳→审计落盘→回放→失败分流)，专抓
                    「单测都绿、串起来却断了」的接缝退化。

这两道防线同属「防退化」家族，但要敲两条命令、读两份报告，最容易漏跑其一。
这里把它们收敛成一个入口，按「由细到粗」的顺序串起来：
单命令快照(goldens) → 端到端生命线(本文件内联)，最后给一份合并结论。
单命令快照仍保留 `goldens.py` 可单独敲；端到端必经链已并入这里，不再单独成命令。

用法:
    python regression.py            # 两层都跑一遍，按层打印 + 合并结论
    python regression.py --quiet    # 只在有回归时说话(适合钩子 / CI)
    python regression.py --update   # 确认当前行为正确后，(重新)录制两层的黄金样本
    python regression.py snapshot   # 只跑某一层(snapshot/path)
    python regression.py path --update

退出码：0 = 每一层都无回归；1 = 任意一层有回归/漂移/未录。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import goldens


# ════════════════════════════════════════════════════════════════════
# 黄金路径 · 端到端必经链 🛤️
#   把最核心的生命线串成一条整链验证：在一份临时副本里(绝不弄脏真实领地、
#   绝不真打大脑)把生命线端到端跑一遍，验证每一段都把接力棒交到了下一段：
#       🪞 自检 → 🌊 启动+心跳 → 🧾 审计落盘(事件骨架有序) → ⏪ 回放 → 🚑 失败分流
#   再把整链的关键信号固化成「黄金指纹」，每次变更后逐项比对。
# ════════════════════════════════════════════════════════════════════
GOLDEN_PATH = REPO_ROOT / "goldens" / "golden-path.json"

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


def _run_cmd(argv: list[str], cwd: pathlib.Path) -> tuple[int, str]:
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


def _walk_path() -> list[Stage]:
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
        code, out = _run_cmd([_PY, "checkup.py", "--quiet"], sandbox)
        tail = (out.strip().splitlines() or ["(无输出)"])[-1][:160]
        s_check.done(code == 0, f"退出码 {code}"
                     + ("" if code == 0 else f"：{tail}"), signal=(code == 0))

        # 2) 启动 + 一次心跳：生命线的主干，必须从「醒来」走到「沉淀完毕」。
        code, out = _run_cmd([_PY, "crab.py", "once"], sandbox)
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
        code, out = _run_cmd([_PY, "crab.py", "replay"], sandbox)
        replay_ok = code == 0 and "回放" in out
        s_replay.done(replay_ok, f"退出码 {code}"
                      + ("" if replay_ok else "：回放没把今天的审计读回来"),
                      signal=replay_ok)

    # 5) 失败分流：在本进程内探一组典型失败，确认分流网兜得住、错误码稳定。
    import errors
    hits = {name: errors.classify(**scene).code for name, scene, _ in TRIAGE_PROBES}
    wrong = [f"{name}: 期望 {want} 得 {hits[name]}"
             for name, _, want in TRIAGE_PROBES if hits[name] != want]
    s_triage.done(not wrong,
                  "全部命中预期错误码" if not wrong else "；".join(wrong),
                  signal=hits)

    return [s_check, s_tick, s_audit, s_replay, s_triage]


def _path_fingerprint(stages: list[Stage]) -> dict:
    """从各段抽出**稳定信号**，组成可比对的黄金指纹(不含时间戳/路径等噪声)。"""
    return {st.name: st.signal for st in stages}


class PathVerdict:
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


def _load_path_golden() -> dict | None:
    if not GOLDEN_PATH.exists():
        return None
    try:
        return json.loads(GOLDEN_PATH.read_text("utf-8"))
    except Exception:
        return None


def verify_path() -> PathVerdict:
    """端到端跑一遍并与黄金指纹比对(不修改任何样本)。"""
    v = PathVerdict()
    v.stages = _walk_path()
    v.broken = [st.name for st in v.stages if not st.ok]

    golden = _load_path_golden()
    if golden is None:
        v.missing_golden = True
        return v

    now = _path_fingerprint(v.stages)
    for st in v.stages:
        want, got = golden.get(st.name), now.get(st.name)
        if want != got:
            v.drifted.append(st.name)
            v.diffs[st.name] = f"黄金 {want!r} → 现在 {got!r}"
    return v


def update_path() -> dict:
    """确认当前链路正确后，(重新)录制黄金指纹。"""
    fp = _path_fingerprint(_walk_path())
    GOLDEN_PATH.parent.mkdir(exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(fp, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return fp


@dataclasses.dataclass
class Layer:
    """一层回归验证的归一化结论：跑哪层、过没过、一句话现状、多行明细。"""
    key: str          # 子命令名(snapshot/path)
    title: str        # 报告标题
    ok: bool
    summary: str      # 一句话结论
    detail: str       # 多行明细(每行一项)


def _run_snapshot() -> Layer:
    v = goldens.verify()
    lines: list[str] = []
    for name in v.passed:
        lines.append(f"  ✅ {name}")
    for name in v.missing:
        lines.append(f"  ⚪ {name} — 还没有黄金样本(先跑 python goldens.py --update)")
    for name in v.regressed:
        lines.append(f"  ❌ {name} — 行为变了：")
        lines += ["       " + line for line in v.diffs[name]]
    if v.ok:
        summary = f"{len(v.passed)}/{v.total} 条用例行为与样本一致"
    else:
        bits = []
        if v.regressed:
            bits.append(f"{len(v.regressed)} 条回归")
        if v.missing:
            bits.append(f"{len(v.missing)} 条未录")
        summary = "、".join(bits)
    return Layer("snapshot", "🧪 回归快照 · 单命令逐字比对", v.ok, summary, "\n".join(lines))


def _run_path() -> Layer:
    v = verify_path()
    lines: list[str] = []
    for st in v.stages:
        lines.append(f"  {'✅' if st.ok else '❌'} {st.label}")
        lines.append(f"       {st.detail}")
        if st.name in v.diffs:
            lines.append(f"       ↳ 指纹漂移：{v.diffs[st.name]}")
    if v.missing_golden:
        summary = "还没有黄金指纹(先跑 python regression.py path --update)"
        # 链已跑断时按未过收尾；仅缺指纹但链通畅，视作「待录」也算未过。
        ok = False
    elif v.ok:
        summary = f"{len(v.stages)} 段全部接得上，且与黄金指纹一致"
        ok = True
    else:
        bits = []
        if v.broken:
            bits.append(f"{len(v.broken)} 段跑断({', '.join(v.broken)})")
        if v.drifted:
            bits.append(f"{len(v.drifted)} 段指纹漂移({', '.join(v.drifted)})")
        summary = "；".join(bits)
        ok = False
    return Layer("path", "🛤️ 黄金路径 · 端到端必经链", ok, summary, "\n".join(lines))


# 由细到粗的顺序：先比单命令快照，再跑端到端生命线。
LAYERS = {
    "snapshot": _run_snapshot,
    "path": _run_path,
}
ORDER = ["snapshot", "path"]


def run(keys: list[str] | None = None) -> list[Layer]:
    """跑指定的几层(默认全跑)，返回归一化结论列表(某层自身炸了也收敛成未过)。"""
    keys = keys or ORDER
    out: list[Layer] = []
    for key in keys:
        runner = LAYERS[key]
        try:
            out.append(runner())
        except Exception as e:
            out.append(Layer(key, key, False, f"该层验证自身异常：{e}", ""))
    return out


def _update(keys: list[str]) -> None:
    """确认当前行为正确后，(重新)录制选定层的黄金样本。"""
    if "snapshot" in keys:
        touched = goldens.update()
        print(f"🧪 已录制 {len(touched)} 条回归快照：{', '.join(touched)}")
    if "path" in keys:
        fp = update_path()
        print(f"🛤️  已录制黄金指纹（{len(fp)} 段关键信号）")
    print("   样本写入 goldens/，记得连同改动一起提交。")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 统一回归验证链 🧪🛤️")
    ap.add_argument("layer", nargs="?", choices=ORDER,
                    help="只跑某一层(留空=全跑)")
    ap.add_argument("--update", action="store_true",
                    help="确认当前行为正确后，(重新)录制黄金样本")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有回归时输出(适合钩子 / CI)")
    args = ap.parse_args(argv)

    keys = [args.layer] if args.layer else ORDER

    if args.update:
        _update(keys)
        return

    layers = run(keys)
    clean = all(l.ok for l in layers)

    if not (args.quiet and clean):
        print("🦀 opencrab 统一回归验证\n")
        for l in layers:
            mark = "✅" if l.ok else "❌"
            print(f"{mark} {l.title} — {l.summary}")
            if l.detail:
                print(l.detail)
            print()

    if clean:
        if not args.quiet:
            print(f"🦀 无回归：{len(layers)} 层防退化验证全部通过，可以放心进化。")
    else:
        bad = [l.title for l in layers if not l.ok]
        print(f"⚠️  发现 {len(bad)} 层有回归（{'、'.join(bad)}），"
              "若改动是有意为之、确认无误后 python regression.py --update。")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
