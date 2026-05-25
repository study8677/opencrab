#!/usr/bin/env python3
"""统一回归验证链 🧪🛤️ —— 一条命令把「防退化」的两道防线一起跑完。

opencrab 防退化一度散在两处，各看一层、各有各的报告：
  · 回归快照(snapshot) 把关键命令的标准输出/错误/退出码固化成黄金样本，
                    逐字比对，专抓「命令还能跑、退出码还是 0，可输出已经变味」；
  · 黄金路径(path)    在临时副本里把核心生命线端到端跑一遍
                    (自检→启动+心跳→审计落盘→回放→失败分流)，专抓
                    「单测都绿、串起来却断了」的接缝退化。

这两道防线同属「防退化」家族，但曾要敲两条命令、读两份报告，最容易漏跑其一。
这里把它们收敛成一个入口，按「由细到粗」的顺序串起来：
单命令快照 → 端到端生命线，最后给一份合并结论。两层实现都已内联本文件，
不再单独成命令(原 `goldens.py` 的快照逻辑已并入此处)。

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
import difflib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

try:
    import resource   # POSIX only；缺了就降级为「不量内存」
except ImportError:    # pragma: no cover - Windows 等无 resource
    resource = None

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GOLDEN_DIR = REPO_ROOT / "goldens"

_PY = sys.executable


# ════════════════════════════════════════════════════════════════════
# 回归快照 · 单命令逐字比对 🧪
#   把几条关键命令的标准输出/错误/退出码录成黄金样本(goldens/*.json)，每次
#   进化后重跑、逐字比对。比对前先把「会变但无关对错」的噪声(时间戳/短哈希/
#   绝对路径/字节数)抹成占位符，于是只有**真正的行为差异**才会被判为回归。
# ════════════════════════════════════════════════════════════════════
@dataclasses.dataclass
class Case:
    """一条回归用例：跑哪条命令、要不要把数字也抹成占位符。

    `scrub_numbers` 给那些输出里含「会随进化而变的计数/行数」的命令用
    (如 snapshot 的代码行数)——抹掉数字后，仍能守住「输出格式」这道防线。
    """
    name: str
    argv: list[str]            # 在仓库根下执行的命令(含解释器)
    summary: str
    scrub_numbers: bool = False


# 录制时强制的环境：让命令行为只取决于代码本身，而非本机 .env / 白名单，
# 这样不同机器、不同配置下录出来的样本才一致、可共享。
_STABLE_ENV = {
    "OPENCRAB_CAPABILITIES": "",   # 空 -> 回到「默认启用」的能力集，不受 .env 白名单影响
    "OPENCRAB_API_KEY": "",        # 空 -> 梦境模式，绝不在录制时真打大脑
    "PYTHONIOENCODING": "utf-8",
}

CASES = [
    Case("crab-help", [_PY, "crab.py", "--help"],
         "crab.py 的用法帮助(参数契约不该悄悄变)"),
    Case("crab-caps", [_PY, "crab.py", "--caps"],
         "已注册能力的清单与启用状态(能力不该悄悄丢失或改名)"),
    Case("checkup-help", [_PY, "checkup.py", "--help"],
         "checkup.py 的用法帮助"),
    Case("cap-snapshot", [_PY, "crab.py", "--cap", "snapshot"],
         "单跑 snapshot 能力的输出格式", scrub_numbers=True),
]


# ── 规整(normalize):把「会变但无关对错」的噪声抹成占位符 ────────────────
def _normalize(text: str, *, scrub_numbers: bool) -> str:
    # 绝对仓库路径 -> <REPO>(不同机器克隆到不同目录)
    text = text.replace(str(REPO_ROOT), "<REPO>")
    # ISO 时间戳(含可选毫秒)-> <TS>
    text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?", "<TS>", text)
    # git 短/长哈希 -> <HASH>
    text = re.sub(r"\b[0-9a-f]{7,40}\b", "<HASH>", text)
    # 「N 字节」里的数字(文件大小随内容变)
    text = re.sub(r"\d+(?=\s*字节)", "<N>", text)
    if scrub_numbers:
        # 含「会随进化而变的计数」时，把独立数字整体抹掉，只守格式
        text = re.sub(r"\d+", "<N>", text)
    return text.strip("\n")


def _capture_case(case: Case) -> dict:
    """跑一条用例，返回规整后的 {exit, stdout, stderr}。"""
    env = {**os.environ, **_STABLE_ENV}
    try:
        proc = subprocess.run(case.argv, cwd=str(REPO_ROOT), env=env,
                              capture_output=True, text=True, timeout=120)
        exit_code, out, err = proc.returncode, proc.stdout, proc.stderr
    except Exception as e:   # 命令本身起不来也是一种「行为」——如实录下来
        exit_code, out, err = -1, "", f"<能力录制异常> {e!r}"
    return {
        "exit": exit_code,
        "stdout": _normalize(out, scrub_numbers=case.scrub_numbers),
        "stderr": _normalize(err, scrub_numbers=case.scrub_numbers),
    }


def snapshot_golden_path(case: Case) -> pathlib.Path:
    return GOLDEN_DIR / f"{case.name}.json"


def _load_snapshot_golden(case: Case) -> dict | None:
    p = snapshot_golden_path(case)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return None


def _save_snapshot_golden(case: Case, observed: dict) -> None:
    GOLDEN_DIR.mkdir(exist_ok=True)
    record = {"cmd": " ".join(["python", *case.argv[1:]]),  # 给人看的可读命令
              "summary": case.summary, **observed}
    snapshot_golden_path(case).write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _snapshot_diff(name: str, field: str, want: str, got: str) -> list[str]:
    return list(difflib.unified_diff(
        want.splitlines(), got.splitlines(),
        fromfile=f"golden/{name}.{field}", tofile=f"now/{name}.{field}",
        lineterm=""))


@dataclasses.dataclass
class SnapshotVerdict:
    """一次回归比对的结论。"""
    ok: bool
    total: int
    passed: list[str]
    regressed: list[str]      # 行为与黄金样本不符
    missing: list[str]        # 还没录过黄金样本(需先 --update)
    diffs: dict[str, list[str]]   # 用例名 -> 可读 diff 行


def verify_snapshot() -> SnapshotVerdict:
    """逐条比对当前行为与黄金样本，给出回归结论(不修改任何样本)。"""
    passed, regressed, missing, diffs = [], [], [], {}
    for case in CASES:
        golden = _load_snapshot_golden(case)
        if golden is None:
            missing.append(case.name)
            continue
        observed = _capture_case(case)
        case_diffs: list[str] = []
        if golden.get("exit") != observed["exit"]:
            case_diffs.append(f"退出码 {golden.get('exit')} → {observed['exit']}")
        for field in ("stdout", "stderr"):
            if golden.get(field, "") != observed[field]:
                case_diffs += _snapshot_diff(case.name, field,
                                             golden.get(field, ""), observed[field])
        if case_diffs:
            regressed.append(case.name)
            diffs[case.name] = case_diffs
        else:
            passed.append(case.name)
    ok = not regressed and not missing
    return SnapshotVerdict(ok=ok, total=len(CASES), passed=passed,
                           regressed=regressed, missing=missing, diffs=diffs)


def update_snapshot() -> list[str]:
    """(重新)录制所有用例为黄金样本，返回受影响的用例名。"""
    touched = []
    for case in CASES:
        _save_snapshot_golden(case, _capture_case(case))
        touched.append(case.name)
    return touched


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


# ════════════════════════════════════════════════════════════════════
# 烟雾测试 · README 教的命令今天还跑不跑得起来 🔥
#   checkup 看「器官在不在」、snapshot/path 看「行为变没变」，这一层守的是
#   最朴素的另一面：**README 教人敲的那几条命令，今天还跑得起来吗？** 文档最易
#   悄悄漂移——命令改名、子命令删了、退出码变了。它做两件事：① 文档同步：每条
#   示例命令必须原样还在 README 里；② 真能跑：只读命令就地跑，有副作用的进临时
#   副本跑(复用上面的 _DREAM_ENV / _COPY_IGNORE / _run_cmd，副作用跑完即弃)。
# ════════════════════════════════════════════════════════════════════
README = REPO_ROOT / "README.md"


@dataclasses.dataclass
class Sample:
    """一条「可执行示例」：README 里教的某条命令，连同怎么验证它真能跑。

    `doc` 是它在 README 里的原样文本，用来守「文档没漂移」这道防线。
    `argv` 为空表示「只校验文档、不执行」(留给天生不结束的命令，如持续心跳)。
    `isolate=True` 表示命令有副作用，要在仓库的临时副本里跑，跑完即弃。
    """
    name: str
    doc: str                    # 命令在 README 里的原样文本
    argv: list[str]             # 真正执行的命令(含解释器)；[] = 只校验文档
    summary: str
    expect_exit: int = 0        # 期望的退出码
    expect_substr: str = ""     # 输出里应出现的片段(留空=只看退出码)
    isolate: bool = False       # True = 在临时副本里跑(命令有副作用)


SAMPLES = [
    Sample("checkup", "python checkup.py", [_PY, "checkup.py"],
           "领地自检跑得起来、报告健康", expect_substr="健康"),
    Sample("checkup-quiet", "python checkup.py --quiet", [_PY, "checkup.py", "--quiet"],
           "自检 --quiet 全过时静默、退出码 0"),
    Sample("crab-once", "python crab.py --once", [_PY, "crab.py", "--once"],
           "心跳一次能从醒来走到沉淀(在临时副本里跑)",
           expect_substr="沉淀完毕", isolate=True),
    Sample("crab-live", "python crab.py", [],
           "持续心跳(天生不结束，只校验 README 仍这么教，不执行)"),
]


@dataclasses.dataclass
class Outcome:
    """一条烟雾用例的结论。"""
    name: str
    ok: bool
    detail: str


def _run_isolated(argv: list[str]) -> tuple[int, str]:
    """把领地复制进临时目录再跑——副作用全落在临时目录，跑完即弃。"""
    with tempfile.TemporaryDirectory(prefix="opencrab-smoke-") as tmp:
        sandbox = pathlib.Path(tmp) / "repo"
        shutil.copytree(REPO_ROOT, sandbox, ignore=_COPY_IGNORE)
        return _run_cmd(argv, sandbox)


def _check_sample(sample: Sample, readme_text: str) -> Outcome:
    # 1) 文档同步：命令必须原样还在 README 里。
    if sample.doc not in readme_text:
        return Outcome(sample.name, False,
                       f"README 里找不到 `{sample.doc}` —— 文档漂移了？"
                       f"修复：让 README 与命令对齐，或更新本用例的 doc")
    # 2) 只校验文档的用例(argv 为空)到此为止。
    if not sample.argv:
        return Outcome(sample.name, True, f"`{sample.doc}`(只校验文档)")
    # 3) 真能跑：只读的就地跑，有副作用的进临时副本跑。
    exit_code, out = (_run_isolated(sample.argv) if sample.isolate
                      else _run_cmd(sample.argv, REPO_ROOT))
    if exit_code != sample.expect_exit:
        tail = out.strip().splitlines()[-1][:160] if out.strip() else "(无输出)"
        return Outcome(sample.name, False,
                       f"退出码 {exit_code}(期望 {sample.expect_exit})：{tail}")
    if sample.expect_substr and sample.expect_substr not in out:
        return Outcome(sample.name, False,
                       f"输出里没等到「{sample.expect_substr}」—— 行为变了？")
    where = "临时副本" if sample.isolate else "就地"
    return Outcome(sample.name, True, f"`{sample.doc}` 跑通({where})")


def _readme_python_commands(text: str) -> list[str]:
    """从 README 的 ```bash``` 代码块里捞出所有 `python ...` 命令行(去重保序)。"""
    cmds: list[str] = []
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_block = stripped.startswith("```bash") if stripped != "```" else False
            continue
        if in_block and stripped.startswith("python "):
            core = stripped.split(" || ", 1)[0].split(" && ", 1)[0].strip()
            if core not in cmds:
                cmds.append(core)
    return cmds


@dataclasses.dataclass
class SmokeVerdict:
    """一次烟雾测试的结论。"""
    ok: bool
    outcomes: list[Outcome]
    uncovered: list[str]   # README 里出现、却没有对应用例的 python 命令(只提示)


def verify_smoke() -> SmokeVerdict:
    """跑完所有烟雾用例，外加扫一遍 README 里有没有「没被覆盖」的命令。"""
    text = README.read_text("utf-8") if README.is_file() else ""
    outcomes = [_check_sample(s, text) for s in SAMPLES]
    documented = {s.doc for s in SAMPLES}
    uncovered = [c for c in _readme_python_commands(text) if c not in documented]
    return SmokeVerdict(ok=all(o.ok for o in outcomes),
                        outcomes=outcomes, uncovered=uncovered)


def _run_smoke() -> "Layer":
    v = verify_smoke()
    lines = [f"  {'✅' if o.ok else '❌'} {o.name} — {o.detail}" for o in v.outcomes]
    if v.uncovered:
        lines.append("  ⚪ README 这些命令还没被烟雾用例覆盖(建议补进 SAMPLES)：")
        lines += [f"       $ {c}" for c in v.uncovered]
    failed = [o for o in v.outcomes if not o.ok]
    summary = (f"{len(v.outcomes)} 条示例都真能跑、且 README 没漂移" if v.ok
               else f"{len(failed)} 条失败——README 与行为对不上了")
    return Layer("smoke", "🔥 烟雾测试 · README 关键用法真能跑吗", v.ok, summary, "\n".join(lines))


@dataclasses.dataclass
class Layer:
    """一层回归验证的归一化结论：跑哪层、过没过、一句话现状、多行明细。"""
    key: str          # 子命令名(snapshot/path)
    title: str        # 报告标题
    ok: bool
    summary: str      # 一句话结论
    detail: str       # 多行明细(每行一项)


def _run_snapshot() -> Layer:
    v = verify_snapshot()
    lines: list[str] = []
    for name in v.passed:
        lines.append(f"  ✅ {name}")
    for name in v.missing:
        lines.append(f"  ⚪ {name} — 还没有黄金样本(先跑 python regression.py snapshot --update)")
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


# 由细到粗的顺序：先比单命令快照，再跑端到端生命线，最后看 README 的命令真能跑。
LAYERS = {
    "snapshot": _run_snapshot,
    "path": _run_path,
    "smoke": _run_smoke,
}
ORDER = ["snapshot", "path", "smoke"]


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
        touched = update_snapshot()
        print(f"🧪 已录制 {len(touched)} 条回归快照：{', '.join(touched)}")
    if "path" in keys:
        fp = update_path()
        print(f"🛤️  已录制黄金指纹（{len(fp)} 段关键信号）")
    print("   样本写入 goldens/，记得连同改动一起提交。")


# ════════════════════════════════════════════════════════════════════
# 命令级性能基线与回归告警 · 变强了，是不是也悄悄变慢了 ⏱️🚨
#   snapshot/path/smoke 守的都是「行为对不对」，这一层守最后一条防线——**性能
#   退化**：功能越加越多，核心命令可能在不知不觉里越跑越慢、越吃越多内存。
#   它跑一组核心命令，量耗时/峰值内存/退出码，与**本机历史基线**逐条比对。
#
#   为什么是 --perf 而非默认层：基线强烈依赖机器(CPU/磁盘/负载)，跨机器比对
#   没有意义，故落在被 .gitignore 的 state/perf/baseline.json，每台机器各自校准
#   ——它不是能提交进仓库的黄金样本，因此独立成一个**显式开关**的层，不混进默认跑。
#
#   怎么不误报：耗时取多次采样的最小值(最接近纯计算成本)；双重门槛(既慢过
#   threshold_pct，又慢过 min_delta_ms)挡住小命令的百分比抖动；退出码 0→非0
#   单独判为回归(跑挂了比慢更严重)。内存用标准库 resource 尽力而为(POSIX、近似)。
# ════════════════════════════════════════════════════════════════════
PERF_DIR = REPO_ROOT / "state" / "perf"        # 落在被 .gitignore 的 state/ 里
PERF_BASELINE_PATH = PERF_DIR / "baseline.json"

# 默认阈值：慢过基线 25% 且 绝对增量超过 80ms 才告警(双重门槛，挡抖动)
PERF_THRESHOLD_PCT = 25.0
PERF_MIN_DELTA_MS = 80.0
PERF_REPEAT = 3


@dataclasses.dataclass
class Bench:
    """一条被测命令：跑什么、给人看的可读说明。"""
    name: str
    argv: list[str]            # 在仓库根下执行的命令(含解释器)
    summary: str


# 核心命令：启动/能力清单/自检/单跑能力——日常最常走的路径，最值得守住速度。
BENCHES = [
    Bench("crab-help", [_PY, "crab.py", "--help"],
          "crab.py 启动与参数解析的基础开销"),
    Bench("crab-caps", [_PY, "crab.py", "caps"],
          "能力发现+清单渲染(能力越加越多，这里最先变慢)"),
    Bench("checkup", [_PY, "checkup.py", "--quiet"],
          "整套健康自检的耗时"),
    Bench("cap-snapshot", [_PY, "crab.py", "cap", "snapshot"],
          "单跑 snapshot 能力(扫仓库，规模越大越慢)"),
]


def _maxrss_kb() -> float | None:
    """读当前已回收子进程的峰值 RSS(KB)；无 resource 则 None。

    注意系统语义：RUSAGE_CHILDREN.ru_maxrss 是「最大的那个子进程」的峰值，
    且单位随平台不同(Linux=KB, macOS=字节)，这里统一归一到 KB。
    """
    if resource is None:
        return None
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    if rss <= 0:
        return None
    # macOS 上 ru_maxrss 是字节，Linux 上是 KB——按平台归一到 KB
    return rss / 1024.0 if sys.platform == "darwin" else float(rss)


def _perf_measure_once(bench: Bench) -> dict:
    """跑一次，返回 {duration_ms, exit, mem_kb}(mem 为近似/可能 None)。"""
    env = {**os.environ, **_STABLE_ENV}
    mem_before = _maxrss_kb()
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(bench.argv, cwd=str(REPO_ROOT), env=env,
                              capture_output=True, text=True, timeout=120)
        exit_code = proc.returncode
    except Exception:     # 起不来/超时也是一种「性能」——记为失败退出码
        exit_code = -1
    duration_ms = (time.perf_counter() - t0) * 1000.0
    mem_after = _maxrss_kb()
    mem_kb = None
    if mem_before is not None and mem_after is not None:
        delta = mem_after - mem_before
        mem_kb = delta if delta > 0 else None    # 因 maxrss 是单调最大值，只在抬升时记
    return {"duration_ms": duration_ms, "exit": exit_code, "mem_kb": mem_kb}


def perf_sample(bench: Bench, repeat: int = PERF_REPEAT) -> dict:
    """对一条命令采样 repeat 次，取最小耗时(最接近纯计算成本)。"""
    runs = [_perf_measure_once(bench) for _ in range(max(1, repeat))]
    best = min(runs, key=lambda r: r["duration_ms"])
    mems = [r["mem_kb"] for r in runs if r["mem_kb"] is not None]
    return {
        "duration_ms": round(best["duration_ms"], 1),
        "exit": best["exit"],
        "mem_kb": round(max(mems), 1) if mems else None,
        "repeat": len(runs),
    }


def _load_perf_baseline() -> dict:
    """读本机基线；不存在或坏了都退化成空 dict(视作未录)。"""
    if not PERF_BASELINE_PATH.exists():
        return {}
    try:
        return json.loads(PERF_BASELINE_PATH.read_text("utf-8"))
    except Exception:
        return {}


def update_perf(repeat: int = PERF_REPEAT) -> dict:
    """(重新)录制所有命令为本机基线，返回写入的基线数据。"""
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    samples = {b.name: perf_sample(b, repeat) for b in BENCHES}
    data = {
        "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "platform": sys.platform,
        "repeat": repeat,
        "benches": samples,
    }
    PERF_BASELINE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return data


@dataclasses.dataclass
class PerfVerdict:
    """一次性能比对的结论。"""
    ok: bool
    total: int
    measured: dict              # name -> 本次采样
    baseline: dict              # name -> 基线采样
    regressed: list[dict]       # 每条：{name, kind, baseline_ms, current_ms, delta_pct, ...}
    missing: list[str]          # 还没录过基线的命令
    has_baseline: bool


def verify_perf(repeat: int = PERF_REPEAT,
                threshold_pct: float = PERF_THRESHOLD_PCT,
                min_delta_ms: float = PERF_MIN_DELTA_MS) -> PerfVerdict:
    """采样当前性能并与本机基线逐条比对，给出回归结论(不改基线)。"""
    base = _load_perf_baseline()
    base_benches = base.get("benches", {})
    has_baseline = bool(base_benches)

    measured: dict[str, dict] = {}
    regressed: list[dict] = []
    missing: list[str] = []

    for bench in BENCHES:
        cur = perf_sample(bench, repeat)
        measured[bench.name] = cur
        b = base_benches.get(bench.name)
        if not has_baseline or b is None:
            missing.append(bench.name)
            continue
        base_ms = float(b.get("duration_ms", 0) or 0)
        cur_ms = cur["duration_ms"]
        # 1) 退出码回归：命令跑挂了，比慢更严重
        if b.get("exit") == 0 and cur["exit"] != 0:
            regressed.append({
                "name": bench.name, "kind": "exit",
                "baseline_exit": b.get("exit"), "current_exit": cur["exit"],
                "baseline_ms": base_ms, "current_ms": cur_ms, "delta_pct": None,
            })
            continue
        # 2) 耗时回归：双重门槛——百分比 + 绝对毫秒，都超才告警
        if base_ms > 0:
            delta_ms = cur_ms - base_ms
            delta_pct = delta_ms / base_ms * 100.0
            if delta_pct > threshold_pct and delta_ms > min_delta_ms:
                regressed.append({
                    "name": bench.name, "kind": "slower",
                    "baseline_ms": base_ms, "current_ms": cur_ms,
                    "delta_ms": round(delta_ms, 1),
                    "delta_pct": round(delta_pct, 1),
                })

    ok = has_baseline and not regressed and not missing
    return PerfVerdict(ok=ok, total=len(BENCHES), measured=measured,
                       baseline=base_benches, regressed=regressed,
                       missing=missing, has_baseline=has_baseline)


def _perf_audit(v: PerfVerdict) -> None:
    """把本次比对留痕到审计：每条采样一条 perf_sample，每条回归一条 perf_regression。

    审计是观测者，绝不反噬——任何异常都吞掉，不让留痕本身弄死调用方。
    """
    try:
        import audit
        for name, m in v.measured.items():
            audit.record("perf_sample", bench=name, duration_ms=m["duration_ms"],
                         exit=m["exit"], mem_kb=m["mem_kb"], repeat=m.get("repeat"))
        for r in v.regressed:
            audit.record("perf_regression", **r)
    except Exception:
        pass


def _fmt_ms(ms: float | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def _run_perf_list() -> None:
    print("⏱️  被测命令：")
    base = _load_perf_baseline().get("benches", {})
    for b in BENCHES:
        tag = "已录" if b.name in base else "未录"
        base_ms = _fmt_ms(base.get(b.name, {}).get("duration_ms")) if b.name in base else "—"
        print(f"  [{tag}] {b.name}（基线 {base_ms}）— {b.summary}")


def _run_perf_update(repeat: int) -> None:
    data = update_perf(repeat)
    print(f"⏱️  已录制 {len(data['benches'])} 条本机性能基线 → "
          f"{PERF_BASELINE_PATH.relative_to(REPO_ROOT)}（平台 {data['platform']}）")
    for name, s in data["benches"].items():
        print(f"     {name}: {_fmt_ms(s['duration_ms'])}"
              + (f" · {s['mem_kb']:.0f}KB" if s["mem_kb"] else ""))
    print("   基线是本机资产，不进仓库——换机器请重新 --perf --update。")


def _run_perf(repeat: int, threshold_pct: float, quiet: bool) -> int:
    """跑性能比对层，打印报告，返回退出码(0=无回归 / 1=有回归或未录)。"""
    v = verify_perf(repeat, threshold_pct)
    _perf_audit(v)

    if not v.has_baseline:
        print("⏱️  opencrab 命令级性能比对\n")
        print("  ⚪ 本机还没有性能基线——先跑 python regression.py --perf --update 校准。\n")
        return 1

    if not (quiet and v.ok):
        print("⏱️  opencrab 命令级性能比对\n")
        for b in BENCHES:
            m = v.measured.get(b.name, {})
            base_ms = v.baseline.get(b.name, {}).get("duration_ms")
            reg = next((r for r in v.regressed if r["name"] == b.name), None)
            if b.name in v.missing:
                print(f"  ⚪ {b.name} — 未录基线（本次 {_fmt_ms(m.get('duration_ms'))}）")
            elif reg and reg["kind"] == "exit":
                print(f"  ❌ {b.name} — 退出码回归 {reg['baseline_exit']}→{reg['current_exit']}")
            elif reg:
                print(f"  ❌ {b.name} — 变慢 {reg['delta_pct']}%："
                      f"{_fmt_ms(reg['baseline_ms'])} → {_fmt_ms(reg['current_ms'])}")
            else:
                print(f"  ✅ {b.name} — {_fmt_ms(base_ms)} → {_fmt_ms(m.get('duration_ms'))}")
        print()

    if v.ok:
        if not quiet:
            print(f"🦀 无性能回归：{v.total} 条命令均未慢过基线。")
        return 0
    parts = []
    if v.regressed:
        parts.append(f"{len(v.regressed)} 条回归")
    if v.missing:
        parts.append(f"{len(v.missing)} 条未录基线")
    print(f"⚠️  {'、'.join(parts)}——若是有意为之(如换了机器/接受了新成本)，"
          f"确认后 python regression.py --perf --update 重录基线。回归已写入审计(state/audit)。")
    return 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 统一回归验证链 🧪🛤️")
    ap.add_argument("layer", nargs="?", choices=ORDER,
                    help="只跑某一层(留空=全跑)")
    ap.add_argument("--update", action="store_true",
                    help="确认当前行为正确后，(重新)录制黄金样本")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有回归时输出(适合钩子 / CI)")
    ap.add_argument("--perf", action="store_true",
                    help="跑命令级性能比对层(与本机基线比，基线不进仓库，需显式开启)")
    ap.add_argument("--list", action="store_true",
                    help="(配合 --perf)只列出有哪些被测命令")
    ap.add_argument("--repeat", type=int, default=PERF_REPEAT,
                    help=f"(配合 --perf)每条命令采样次数，取最小(默认 {PERF_REPEAT})")
    ap.add_argument("--threshold-pct", type=float, default=PERF_THRESHOLD_PCT,
                    help=f"(配合 --perf)耗时慢过基线多少%%才告警(默认 {PERF_THRESHOLD_PCT})")
    args = ap.parse_args(argv)

    # 性能层是显式开关、与本机基线(不进仓库)比对，独立于默认的黄金样本层。
    if args.perf:
        if args.list:
            _run_perf_list()
            return
        if args.update:
            _run_perf_update(args.repeat)
            return
        sys.exit(_run_perf(args.repeat, args.threshold_pct, args.quiet))

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
