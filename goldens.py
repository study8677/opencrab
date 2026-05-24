#!/usr/bin/env python3
"""回归快照(golden snapshots)🧪 —— 把关键命令的「行为」固化成可比对的样本。

为什么要有它：自检(checkup)看的是「器官还在不在」，单元级别的检查看的是
「某个函数对不对」；但一只持续进化的螃蟹最怕的，是**整体行为悄悄退化**——
命令还能跑、退出码还是 0，可输出已经变味了(少了一行、措辞错了、顺序乱了)。
回归快照专抓这种「看起来能跑、其实变差」：把几条关键命令的
标准输出 / 标准错误 / 退出码录成黄金样本(golden)，每次进化后重跑、逐字比对。

怎么保证不误报：命令输出里天然有「会变但无关对错」的噪声——时间戳、git 短哈希、
绝对路径、字节数……比对前先用一组规整规则(normalize)把它们抹成占位符，
于是只有**真正的行为差异**才会被判为回归。

样本进仓库(goldens/，是资产)；录制与比对都零第三方依赖，纯标准库。

用法:
    python goldens.py              # 比对所有用例，报告回归(退出码 0=全过 / 1=有回归)
    python goldens.py --update     # 重新录制(确认当前行为正确后再 bless)
    python goldens.py --list       # 只列出有哪些用例
"""
from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import os
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
GOLDEN_DIR = REPO_ROOT / "goldens"


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

_PY = sys.executable

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


def _capture(case: Case) -> dict:
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


def _golden_path(case: Case) -> pathlib.Path:
    return GOLDEN_DIR / f"{case.name}.json"


def _load_golden(case: Case) -> dict | None:
    p = _golden_path(case)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return None


def _save_golden(case: Case, observed: dict) -> None:
    GOLDEN_DIR.mkdir(exist_ok=True)
    record = {"cmd": " ".join(["python", *case.argv[1:]]),  # 给人看的可读命令
              "summary": case.summary, **observed}
    _golden_path(case).write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _diff(name: str, field: str, want: str, got: str) -> list[str]:
    lines = list(difflib.unified_diff(
        want.splitlines(), got.splitlines(),
        fromfile=f"golden/{name}.{field}", tofile=f"now/{name}.{field}",
        lineterm=""))
    return lines


# ── 对外:录制 / 比对 ──────────────────────────────────────────────────
def update() -> list[str]:
    """(重新)录制所有用例为黄金样本，返回受影响的用例名。"""
    touched = []
    for case in CASES:
        _save_golden(case, _capture(case))
        touched.append(case.name)
    return touched


@dataclasses.dataclass
class Verdict:
    """一次回归比对的结论。"""
    ok: bool
    total: int
    passed: list[str]
    regressed: list[str]      # 行为与黄金样本不符
    missing: list[str]        # 还没录过黄金样本(需先 --update)
    diffs: dict[str, list[str]]   # 用例名 -> 可读 diff 行


def verify() -> Verdict:
    """逐条比对当前行为与黄金样本，给出回归结论(不修改任何样本)。"""
    passed, regressed, missing, diffs = [], [], [], {}
    for case in CASES:
        golden = _load_golden(case)
        if golden is None:
            missing.append(case.name)
            continue
        observed = _capture(case)
        case_diffs: list[str] = []
        if golden.get("exit") != observed["exit"]:
            case_diffs.append(f"退出码 {golden.get('exit')} → {observed['exit']}")
        for field in ("stdout", "stderr"):
            if golden.get(field, "") != observed[field]:
                case_diffs += _diff(case.name, field,
                                    golden.get(field, ""), observed[field])
        if case_diffs:
            regressed.append(case.name)
            diffs[case.name] = case_diffs
        else:
            passed.append(case.name)
    ok = not regressed and not missing
    return Verdict(ok=ok, total=len(CASES), passed=passed,
                   regressed=regressed, missing=missing, diffs=diffs)


def main() -> None:
    ap = argparse.ArgumentParser(description="opencrab 回归快照 🧪")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--update", action="store_true",
                   help="确认当前行为正确后，(重新)录制黄金样本")
    g.add_argument("--list", action="store_true", help="只列出有哪些用例")
    args = ap.parse_args()

    if args.list:
        print("🧪 回归用例：")
        for c in CASES:
            recorded = "已录" if _golden_path(c).exists() else "未录"
            print(f"  [{recorded}] {c.name} — {c.summary}")
        return

    if args.update:
        touched = update()
        print(f"🧪 已录制 {len(touched)} 条黄金样本：{', '.join(touched)}")
        print(f"   样本写入 {GOLDEN_DIR.relative_to(REPO_ROOT)}/，记得连同改动一起提交。")
        return

    v = verify()
    print("🧪 opencrab 回归快照比对\n")
    for name in v.passed:
        print(f"  ✅ {name}")
    for name in v.missing:
        print(f"  ⚪ {name} — 还没有黄金样本(先跑 python goldens.py --update)")
    for name in v.regressed:
        print(f"  ❌ {name} — 行为变了：")
        for line in v.diffs[name]:
            print("       " + line)
    print()
    if v.ok:
        print(f"🦀 无回归：{len(v.passed)}/{v.total} 条用例行为与样本一致。")
        sys.exit(0)
    msg = []
    if v.regressed:
        msg.append(f"{len(v.regressed)} 条回归")
    if v.missing:
        msg.append(f"{len(v.missing)} 条未录")
    print(f"⚠️  {'、'.join(msg)}——若改动是有意为之，确认无误后 python goldens.py --update。")
    sys.exit(1)


if __name__ == "__main__":
    main()
