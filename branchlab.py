#!/usr/bin/env python3
"""分支实验室 🧪 —— 把「大改先在分支上试稳，再并主干」从口头纪律变成**可执行本能**。

为什么要有它：领地一天天长大，越往后越有「想动一处大改」的冲动——重构落地层、换
心跳节律、改能力闸门。直接在主干上动手，就是拿外人能跑得起来的那条路冒险。老道的
做法人人会背：「开个分支养着，验稳了再合」。可纪律只活在嘴上就会松——立项时拍脑袋
开个分支,过两周自己都忘了当初想验什么、凭什么算成功、什么情况该认栽删掉,于是分支
越积越多,既不敢合也不舍得删,成了悬在领地上的一片烂尾。

本实验室把每次大改逼成一份**当场可查的契约**,缺一项都立不了项:

  · 🎯 假设     —— 这次大改到底想验证什么(一句能被证伪的话,不是「优化一下」)
  · 🔬 验证命令 —— 拿什么证明它成了(一串真能跑、跑完有退出码的命令)
  · 🚪 合并门槛 —— 满足什么才配并回主干(验证命令全绿,是最起码的硬门槛)
  · 🪦 废弃条件 —— 什么情况就该认栽、删掉分支(比如养过 N 天仍未达门槛)

立项即在册:记录落进 state,并**安全地**建出分支 ref(只 `git branch`,绝不切换
HEAD、绝不碰工作区——领地此刻可能正自改着,实验室决不抢它脚下的地)。此后随时
`--check`:对每个在册实验跑一遍它自己的验证命令,对照门槛与废弃条件,当场裁决
它「在跑 / 可并 / 该废」。把判断权交还给可复现的命令,而不是当初那点记忆。

用法:
    python branchlab.py                       # 列出在册实验 + 各自当前裁决(在跑/可并/该废)
    python branchlab.py --start "假设" \\      # 立项:记录契约 + 安全建分支 ref
        --name slug --validate "cmd" [--validate "cmd2"] \\
        --gate "门槛描述" --deprecate "废弃描述" [--max-age-days 7]
    python branchlab.py --check [name]        # 对全部(或指定)实验跑验证命令并裁决
    python branchlab.py --list                # 只列在册实验的契约(不跑验证)
    python branchlab.py --json                # 机读:导出每个实验的契约与最近裁决

退出码:默认/--check 时,只要有实验「该废」→ 1,否则 0(可接进钩子,提醒清理烂尾)。
零第三方依赖,纯标准库。实验室是观测者:除了 `git branch` 建 ref 与写自己那本账,
跑验证命令时强制梦境模式(空 key / 默认能力集),绝不真打大脑、绝不弄脏真实领地。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
LEDGER = REPO_ROOT / "state" / "branchlab.jsonl"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import append_jsonl, read_jsonl  # noqa: E402

# 分支命名前缀,与领地里 crab 自己开的实验分支同源(crab/<时间戳>-<题>)。
BRANCH_PREFIX = "lab/"

# 默认养护期:超过这么多天仍未达门槛,就触发废弃条件——别让分支烂尾。
DEFAULT_MAX_AGE_DAYS = 7

# 跑验证命令时强制梦境模式:空 key=绝不真打大脑、空白名单=回默认能力集,
# 让「验证过没过」只取决于代码本身,而非本机 .env。与 onboarding/smoke 同源。
_DREAM_ENV = {
    "OPENCRAB_API_KEY": "",
    "OPENCRAB_CAPABILITIES": "",
    "PYTHONIOENCODING": "utf-8",
}


def _git(args: list[str]) -> tuple[int, str]:
    """在领地里跑一条 git,返回 (退出码, 合并输出)。失败永不抛错。"""
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                             capture_output=True, text=True, timeout=15)
        return out.returncode, (out.stdout + out.stderr).strip()
    except Exception as e:
        return -1, f"<git 异常> {e!r}"


def _branch_exists(branch: str) -> bool:
    code, _ = _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"])
    return code == 0


def _run_cmd(argv: list[str], timeout: int = 180) -> tuple[int, str]:
    """在领地根目录按梦境模式跑一条验证命令,返回 (退出码, 输出末尾一行)。"""
    env = {**os.environ, **_DREAM_ENV}
    try:
        proc = subprocess.run(argv, cwd=str(REPO_ROOT), env=env,
                              capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout + proc.stderr).strip()
        tail = out.splitlines()[-1][:160] if out else "(无输出)"
        return proc.returncode, tail
    except Exception as e:
        return -1, f"<执行异常> {e!r}"


@dataclasses.dataclass
class Experiment:
    """一次大改的实验契约:想验什么、拿什么证、凭什么并、什么情况认栽。

    四样缺一不可——少了假设就是瞎改,少了验证命令就无从证成,少了门槛就会凭感觉
    硬合,少了废弃条件就会烂尾。`validations` 是一串真能跑的命令(各自一个 argv),
    全绿才算够到 `merge_gate` 的硬门槛;`max_age_days` 给 `deprecate` 一个可判定的
    兜底:养过这么多天仍未达门槛,就该认栽删分支,而不是无限期挂着。
    """
    name: str                       # 实验代号(也是分支名后缀)
    hypothesis: str                 # 🎯 一句能被证伪的假设
    validations: list[list[str]]    # 🔬 验证命令(每条一个 argv)
    merge_gate: str                 # 🚪 满足什么才配并主干(人话)
    deprecate: str                  # 🪦 什么情况该认栽删分支(人话)
    max_age_days: int               # 废弃兜底:超龄仍未达门槛即该废
    branch: str                     # 对应的 git 分支名
    created_at: float               # 立项时间(epoch 秒)

    def to_record(self) -> dict:
        """落进 state 账本的纯数据形态。"""
        return dataclasses.asdict(self)

    @classmethod
    def from_record(cls, d: dict) -> "Experiment":
        return cls(
            name=d["name"], hypothesis=d["hypothesis"],
            validations=[list(c) for c in d.get("validations", [])],
            merge_gate=d.get("merge_gate", ""), deprecate=d.get("deprecate", ""),
            max_age_days=int(d.get("max_age_days", DEFAULT_MAX_AGE_DAYS)),
            branch=d.get("branch", ""), created_at=float(d.get("created_at", 0.0)),
        )

    @property
    def age_days(self) -> float:
        return max(0.0, (time.time() - self.created_at) / 86400.0)


@dataclasses.dataclass
class Verdict:
    """对一个实验跑完验证命令后的裁决。"""
    exp: Experiment
    gate_met: bool                  # 验证命令是否全绿(达到合并硬门槛)
    details: list[str]              # 每条验证命令的一行结论
    status: str                     # "可并" / "该废" / "在跑"

    def to_meta(self) -> dict:
        return {
            "name": self.exp.name, "hypothesis": self.exp.hypothesis,
            "branch": self.exp.branch, "age_days": round(self.exp.age_days, 1),
            "gate_met": self.gate_met, "status": self.status,
            "merge_gate": self.exp.merge_gate, "deprecate": self.exp.deprecate,
            "validations": [list(c) for c in self.exp.validations],
            "details": self.details,
        }


def _load() -> list[Experiment]:
    """从账本读出全部在册实验;同名以最后一条为准(允许 --start 覆盖重立)。"""
    by_name: dict[str, Experiment] = {}
    for rec in read_jsonl(LEDGER):
        try:
            exp = Experiment.from_record(rec)
        except Exception:
            continue   # 坏行跳过,账本读取永不抛错
        by_name[exp.name] = exp
    return list(by_name.values())


def start(name: str, hypothesis: str, validations: list[list[str]],
          merge_gate: str, deprecate: str, max_age_days: int) -> tuple[Experiment, str]:
    """立项:记录契约 + 安全建分支 ref。返回 (实验, 一句结果说明)。

    只 `git branch`(建 ref),绝不 checkout/switch——领地此刻可能正自改着,
    实验室决不抢它脚下的工作区。分支已存在则复用、不重建。
    """
    branch = f"{BRANCH_PREFIX}{name}"
    exp = Experiment(name=name, hypothesis=hypothesis, validations=validations,
                     merge_gate=merge_gate, deprecate=deprecate,
                     max_age_days=max_age_days, branch=branch,
                     created_at=time.time())
    append_jsonl(LEDGER, exp.to_record())

    if _branch_exists(branch):
        return exp, f"分支 {branch} 已存在,复用(契约已更新入账)"
    code, msg = _git(["branch", branch])
    if code == 0:
        return exp, f"已建分支 ref {branch}(未切换 HEAD,工作区原样不动)"
    return exp, f"分支未建成(契约仍已入账):{msg or '未知原因'}"


def evaluate(exp: Experiment) -> Verdict:
    """对一个实验跑一遍它自己的验证命令,对照门槛与废弃条件给裁决。"""
    details: list[str] = []
    gate_met = True
    for cmd in exp.validations:
        code, tail = _run_cmd(cmd)
        mark = "✅" if code == 0 else "❌"
        details.append(f"{mark} {' '.join(cmd)} → 退出码 {code}:{tail}")
        if code != 0:
            gate_met = False

    if gate_met:
        status = "可并"          # 验证命令全绿,够到合并硬门槛
    elif exp.age_days > exp.max_age_days:
        status = "该废"          # 超龄仍未达门槛,触发废弃条件,该认栽删分支
    else:
        status = "在跑"          # 还在养护期内,继续养着
    return Verdict(exp, gate_met, details, status)


def check(name: str | None = None) -> list[Verdict]:
    """裁决全部(或指定 name)在册实验。"""
    exps = _load()
    if name:
        exps = [e for e in exps if e.name == name]
    return [evaluate(e) for e in exps]


# ── 输出 ─────────────────────────────────────────────────────────────────────
_STATUS_ICON = {"可并": "🟢", "该废": "🪦", "在跑": "🟡"}


def _print_list(exps: list[Experiment]) -> None:
    if not exps:
        print("🧪 分支实验室空着——还没立过项。用 --start 把下一个大改逼成一份契约。")
        return
    print(f"🧪 在册实验 {len(exps)} 个:\n")
    for e in exps:
        print(f"  · {e.name}  〔{e.branch}〕  养了 {e.age_days:.1f} 天")
        print(f"    🎯 假设：{e.hypothesis}")
        for cmd in e.validations:
            print(f"    🔬 验证：{' '.join(cmd)}")
        print(f"    🚪 门槛：{e.merge_gate}")
        print(f"    🪦 废弃：{e.deprecate}（兜底：超 {e.max_age_days} 天未达门槛）\n")


def _print_verdicts(verdicts: list[Verdict]) -> None:
    if not verdicts:
        print("🧪 没有可裁决的实验。")
        return
    print(f"🧪 分支实验室 —— {len(verdicts)} 个实验的当前裁决\n")
    for v in verdicts:
        icon = _STATUS_ICON.get(v.status, "·")
        print(f"  {icon} {v.exp.name}〔{v.status}〕 养了 {v.exp.age_days:.1f} 天 — {v.exp.hypothesis}")
        for d in v.details:
            print(f"      {d}")
        if v.status == "可并":
            print(f"      🚪 验证全绿,够到门槛「{v.exp.merge_gate}」——可并回主干。")
        elif v.status == "该废":
            print(f"      🪦 超 {v.exp.max_age_days} 天仍未达门槛,触发废弃条件:{v.exp.deprecate}")
            print(f"         认栽删分支：git branch -D {v.exp.branch}")
        else:
            print(f"      🟡 还在养护期内({v.exp.max_age_days} 天),继续验。")
        print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 分支实验室 🧪")
    ap.add_argument("--start", metavar="假设",
                    help="立项:这次大改想验证的一句可证伪的假设")
    ap.add_argument("--name", help="实验代号(分支名后缀);--start 时必填")
    ap.add_argument("--validate", action="append", default=[], metavar="CMD",
                    help="验证命令(可多次);如 --validate \"python checkup.py --quiet\"")
    ap.add_argument("--gate", default="", help="合并门槛描述(验证命令全绿是硬门槛)")
    ap.add_argument("--deprecate", default="", help="废弃条件描述(什么情况该认栽删分支)")
    ap.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
                    help=f"废弃兜底:超此天数未达门槛即该废(默认 {DEFAULT_MAX_AGE_DAYS})")
    ap.add_argument("--check", nargs="?", const="*", metavar="NAME",
                    help="对全部(或指定 NAME)在册实验跑验证并裁决")
    ap.add_argument("--list", action="store_true", help="只列在册实验的契约(不跑验证)")
    ap.add_argument("--json", action="store_true", help="导出机读:每个实验的契约与裁决")
    args = ap.parse_args(argv)

    # 立项
    if args.start is not None:
        if not args.name:
            ap.error("--start 立项必须带 --name(实验代号)")
        if not args.validate:
            ap.error("--start 立项必须带至少一条 --validate(没有验证命令就无从证成)")
        validations = [c.split() for c in args.validate]
        exp, msg = start(args.name, args.start, validations,
                         args.gate or "(未声明,默认:验证命令全绿才可并)",
                         args.deprecate or f"超 {args.max_age_days} 天未达门槛即认栽删分支",
                         args.max_age_days)
        print(f"🧪 已立项「{exp.name}」：{msg}")
        print(f"   🎯 假设：{exp.hypothesis}")
        print(f"   🪜 下一步：在分支上动手,随时 `python branchlab.py --check {exp.name}` 看够没够到门槛。")
        return

    if args.list:
        _print_list(_load())
        return

    # 默认行为与 --check 一致:列出每个实验的当前裁决。
    name = None if (args.check in (None, "*")) else args.check
    verdicts = check(name)

    if args.json:
        print(json.dumps([v.to_meta() for v in verdicts], ensure_ascii=False, indent=2))
        sys.exit(0)

    _print_verdicts(verdicts)
    # 有实验该废 → 退出码 1,提醒清理烂尾分支。
    sys.exit(1 if any(v.status == "该废" for v in verdicts) else 0)


if __name__ == "__main__":
    main()
