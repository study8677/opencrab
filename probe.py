#!/usr/bin/env python3
"""依赖与外部工具健康探针 🩺 —— 启动前先问一句「到底能不能跑」。

`checkup.py`(镜子)管「整只螃蟹健不健康」，`envcheck.py` 管「配置对不对齐」。
这里只盯一件更底层的事：**运行时真的够得着它依赖的东西吗**——
解释器够不够新、它代码里 import 的标准库模块在不在、自我进化要用的外部命令
(git / 执行器 CLI)装没装、版本够不够、`requirements.txt` 里声明的第三方包
能不能 import。把「跑不起来、为什么跑不起来」提前暴露在启动这一刻，
比心跳半路撞上 `ModuleNotFoundError` / `FileNotFoundError` 再去栈里倒查省事得多。

每条探测带一句**可操作的修复建议**，并按三级归总：
    error(❌) 缺了它心跳就跑不起来 —— 退出码计为未过；
    warn (⚠️) 缺了只丢部分能力(如执行器 CLI=梦境/journal 模式仍能活)；
    ok   (✅) 这一项够得着。

它还能把探测结果原样写进结构化审计(`audit`)，让自愈与失败分流有据可依。

用法:
    python probe.py            # 跑一次健康探针，打印报告
    python probe.py --quiet    # 只在有 error 时说话(适合钩子 / CI)
    python probe.py --strict   # 把 warn 也视作未过(更严格的门禁)
    python probe.py --audit    # 把探测结果写进当天的运行审计

退出码：0 = 没有 error(--strict 下还需没有 warn)；1 = 有未过项。
零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# 跑得动的硬底线：低于这个版本，本体用到的语法/标准库就不保证了。
MIN_PYTHON = (3, 9)

# 本体代码确实 import 的标准库模块——它们理应随 Python 一起在，但精简版/
# 裁剪过的解释器(某些容器镜像)可能缺，缺了对应能力会在运行半途崩。
STDLIB_NEEDED = [
    "json", "urllib.request", "importlib.metadata",
    "ast", "subprocess", "dataclasses", "argparse",
]

# 自我进化要借的外部命令：(命令, 是否致命, 取版本的参数, 缺了的说明/修复)。
#   git 是硬依赖——盘点领地、记录演化、借手改代码都靠它；缺了基本动不了。
#   执行器(claude/codex)只在 propose/merge/publish 自治档需要；
#   journal/梦境模式下没有也能活，故只判 warn。
EXTERNAL_TOOLS = [
    ("git", True, ("--version",),
     "装 git 并加入 PATH —— 盘点领地、记录演化、借手改代码都靠它"),
]

# 发现级别。
OK, WARN, ERROR = "ok", "warn", "error"
_MARK = {OK: "✅", WARN: "⚠️", ERROR: "❌"}


@dataclasses.dataclass(frozen=True)
class Finding:
    """一条健康探测：探了什么、够不够得着、(若够不着)怎么补。"""
    level: str        # ok / warn / error
    label: str        # 探测项名
    detail: str = ""  # 现状一句话
    fix: str = ""     # 可操作的修复建议(仅 warn/error 有意义)

    @property
    def passed(self) -> bool:
        return self.level == OK

    def to_meta(self) -> dict:
        return {"level": self.level, "label": self.label,
                "detail": self.detail, "fix": self.fix}


def _ok(label: str, detail: str = "") -> Finding:
    return Finding(OK, label, detail)


def _warn(label: str, detail: str, fix: str) -> Finding:
    return Finding(WARN, label, detail, fix)


def _err(label: str, detail: str, fix: str) -> Finding:
    return Finding(ERROR, label, detail, fix)


def _parse_env_file(path: pathlib.Path) -> dict[str, str]:
    """把一个 .env 风格文件解析成 dict(与 crab.py / checkup.py 同款极简解析)。"""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.split(" #", 1)[0].strip()
    return out


# ── 探测项 ──────────────────────────────────────────────────────────
def probe_python() -> list[Finding]:
    """🐍 跑它的解释器够不够新(语法/标准库的硬底线)。"""
    cur = sys.version_info[:3]
    ver = ".".join(map(str, cur))
    need = ".".join(map(str, MIN_PYTHON))
    if cur[:2] < MIN_PYTHON:
        return [_err("Python 解释器", f"当前 {ver}，低于所需 ≥ {need}",
                     f"装一个 ≥ {need} 的 Python(如 pyenv install)再重跑")]
    return [_ok("Python 解释器", f"{ver}（≥ {need}）")]


def probe_stdlib() -> list[Finding]:
    """📚 本体 import 的标准库模块在不在(精简解释器可能缺)。"""
    import importlib.util
    missing = []
    for mod in STDLIB_NEEDED:
        try:
            if importlib.util.find_spec(mod) is None:
                missing.append(mod)
        except (ImportError, ValueError):
            missing.append(mod)
    if missing:
        return [_err("标准库模块", f"找不到：{', '.join(missing)}",
                     "你的 Python 像是被裁剪过——换一个完整的官方发行版")]
    return [_ok("标准库模块", f"{len(STDLIB_NEEDED)} 个本体依赖项均可加载")]


def _tool_version(cmd: str, ver_args: tuple[str, ...]) -> str:
    """探一个外部命令的版本串(取首行)；探不到返回空串。"""
    try:
        r = subprocess.run([cmd, *ver_args], capture_output=True,
                           text=True, timeout=10)
    except Exception:
        return ""
    out = (r.stdout or r.stderr or "").strip().splitlines()
    return out[0].strip() if out else ""


def probe_external_tools() -> list[Finding]:
    """🔧 硬依赖的外部命令(git)装没装、够不够得着。"""
    out: list[Finding] = []
    for cmd, fatal, ver_args, fix in EXTERNAL_TOOLS:
        where = shutil.which(cmd)
        if not where:
            mk = _err if fatal else _warn
            out.append(mk(f"命令 {cmd}", "未在 PATH 中找到", fix))
            continue
        ver = _tool_version(cmd, ver_args)
        out.append(_ok(f"命令 {cmd}", ver or where))
    return out


def probe_executor() -> list[Finding]:
    """✋ 它的「手」依赖的执行器 CLI(claude/codex)在不在。

    只在 propose/merge/publish 自治档真正动手时需要；journal/梦境模式没有也能活，
    所以缺了只判 warn——丢的是「动手改代码」这部分能力，不是命脉。
    """
    env = _parse_env_file(REPO_ROOT / ".env")
    executor = env.get("OPENCRAB_EXECUTOR", "claude")
    autonomy = env.get("OPENCRAB_AUTONOMY", "journal")
    where = shutil.which(executor)
    if where:
        ver = _tool_version(executor, ("--version",))
        return [_ok(f"执行器 {executor}", ver or where)]
    if autonomy in ("propose", "merge", "publish"):
        return [_err(f"执行器 {executor}",
                     f"未找到，但 OPENCRAB_AUTONOMY={autonomy} 要靠它动手改代码",
                     f"装好 {executor} 并加入 PATH，或把 OPENCRAB_AUTONOMY 调回 journal")]
    return [_warn(f"执行器 {executor}",
                  f"未找到(当前 autonomy={autonomy}，无手仍能活)",
                  f"想让它真正动手改代码：装好 {executor} 并加入 PATH")]


def _parse_requirement(line: str) -> str | None:
    """从一行 requirement 里抠出包名；注释/空行/选项行返回 None。"""
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
    return m.group(1) if m else None


def probe_packages() -> list[Finding]:
    """📦 requirements.txt 里声明的第三方包能不能 import(防「装了没装上」)。"""
    import importlib.metadata as md

    reqs = REPO_ROOT / "requirements.txt"
    if not reqs.is_file():
        return [_warn("requirements.txt", "缺失",
                      "补一个 requirements.txt(本体零第三方就留空，也是一种声明)")]
    names = [n for n in (_parse_requirement(ln)
                         for ln in reqs.read_text("utf-8").splitlines()) if n]
    if not names:
        return [_ok("第三方依赖", "requirements.txt 为空(零第三方，符合设计)")]

    out: list[Finding] = []
    for name in names:
        try:
            ver = md.version(name)
            out.append(_ok(f"依赖 {name}", f"已装 {ver}"))
        except md.PackageNotFoundError:
            out.append(_err(f"依赖 {name}", "声明了却没装上",
                            "pip install -r requirements.txt"))
    return out


PROBES = [probe_python, probe_stdlib, probe_external_tools,
          probe_executor, probe_packages]


def run() -> list[Finding]:
    """跑完所有探测，返回发现列表(探针自身出错也收敛成一条 error)。"""
    findings: list[Finding] = []
    for p in PROBES:
        try:
            findings.extend(p())
        except Exception as e:
            findings.append(_err(p.__name__, f"探测异常：{e}",
                                 "这是 probe 自己出的错，贴出来看看哪步炸了"))
    return findings


def summarize(findings: list[Finding], *, strict: bool = False) -> tuple[bool, int, int]:
    """归总：(是否健康, error 数, warn 数)。strict 下 warn 也算未过。"""
    errors = sum(1 for f in findings if f.level == ERROR)
    warns = sum(1 for f in findings if f.level == WARN)
    healthy = errors == 0 and (warns == 0 if strict else True)
    return healthy, errors, warns


def manifest() -> dict:
    """🩺 健康探测结果(纯数据，供能力/审计/外部工具消费)。"""
    findings = run()
    healthy, errors, warns = summarize(findings)
    return {"healthy": healthy, "errors": errors, "warns": warns,
            "findings": [f.to_meta() for f in findings]}


def record_to_audit(findings: list[Finding] | None = None) -> dict:
    """把探测结果写进结构化审计，返回写下的那条记录(写审计永不反噬)。"""
    findings = run() if findings is None else findings
    healthy, errors, warns = summarize(findings)
    try:
        sys.path.insert(0, str(REPO_ROOT))
        import audit
        return audit.record("probe", healthy=healthy, errors=errors, warns=warns,
                            failed=[f.label for f in findings if not f.passed])
    except Exception:
        return {}   # 审计是观测者，不能成为新的故障源


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 依赖与外部工具健康探针 🩺")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有 error 时输出(适合钩子 / CI)")
    ap.add_argument("--strict", action="store_true",
                    help="把 warn 也视作未过(更严格的门禁)")
    ap.add_argument("--audit", action="store_true",
                    help="把探测结果写进当天的运行审计")
    args = ap.parse_args(argv)

    findings = run()
    healthy, errors, warns = summarize(findings, strict=args.strict)

    if args.audit:
        record_to_audit(findings)

    if not (args.quiet and healthy):
        print("🩺 opencrab 依赖与外部工具健康探针\n")
        for f in findings:
            line = f"  {_MARK[f.level]} {f.label}"
            if f.detail:
                line += f" — {f.detail}"
            print(line)
            if f.fix:
                print(f"        ↳ 修复：{f.fix}")
        print()

    if healthy:
        if not args.quiet:
            tail = f"（含 {warns} 处提醒）" if warns else ""
            print(f"🦀 够得着：{len(findings)} 项探测通过{tail}，跑得起来。")
    else:
        bits = []
        if errors:
            bits.append(f"{errors} 处缺失")
        if args.strict and warns:
            bits.append(f"{warns} 处提醒")
        print(f"⚠️  健康探针发现 {' · '.join(bits)}，先按上面的修复建议补齐再启动。")
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
