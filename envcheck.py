#!/usr/bin/env python3
"""配置与环境一致性校验 🔧 —— 启动前先确认「运行条件」对得上。

很多问题不是代码坏了，而是**运行条件不一致**：`.env` 漏了一个键、数值填成乱码、
本机装的依赖版本和 `requirements.txt` 约定的对不上……这些都不会让 `import` 立刻
报错，却会在心跳跑起来后以各种诡异姿势隐性崩掉。先把这层隐患在启动前抓住，
比事后从一堆栈追溯回「原来是环境没对齐」省事得多。

它和 `checkup.py` 的分工：镜子(checkup)关心「整只螃蟹还健不健康」(文件、语法、
导入、git…)，是宽口径体检；这里只盯**配置与环境的一致性**一件事，把它做深——
不仅查缺键，还查 `.env` 里有没有 `.env.example` 不认识的「孤儿键」(往往是拼错或
过期配置)、依赖版本符不符合 `requirements.txt` 的约束。每条发现都带一句
**可操作的修复建议**，照着做就能修。

发现分三级：
    error(❌) 结构性不一致，会让心跳隐性崩 —— 退出码计为未过；
    warn (⚠️) 值得注意但不阻断(如缺 key=梦境模式、孤儿键)；
    ok   (✅) 这一项对齐了。

用法:
    python envcheck.py            # 跑一次一致性校验，打印报告
    python envcheck.py --quiet    # 只在有 error 时说话(适合钩子 / CI)
    python envcheck.py --strict   # 把 warn 也视作未过(更严格的门禁)

退出码：0 = 没有 error(--strict 下还需没有 warn)；1 = 有未过项。
零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# .env 里需要「能解析成数字」的配置(键 -> 解析器)，填错了心跳一启动就崩。
NUMERIC_ENV = {
    "OPENCRAB_TICK_SECONDS": int,
    "OPENCRAB_DAILY_ENERGY": int,
    "OPENCRAB_MOLT_EVERY": int,
    "OPENCRAB_HAND_BUDGET_USD": float,
}
# .env 里只能取有限几个值的配置(键 -> 合法集合)。
ENUM_ENV = {
    "OPENCRAB_AUTONOMY": {"journal", "propose", "merge", "publish"},
    "OPENCRAB_EXECUTOR": {"claude", "codex"},
}
# 运行时确实会读、但故意不写进 .env.example 的内部键(免得被当成孤儿/漏配误报)。
INTERNAL_ENV = {"OPENCRAB_DRY_RUN", "OPENCRAB_CAPABILITIES"}

# 发现级别。
OK, WARN, ERROR = "ok", "warn", "error"


@dataclasses.dataclass(frozen=True)
class Finding:
    """一条一致性发现：是什么、对不对、(若不对)怎么修。"""
    level: str       # ok / warn / error
    label: str       # 检查项名
    detail: str = "" # 现状一句话
    fix: str = ""    # 可操作的修复建议(仅 warn/error 有意义)

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


def parse_env_file(path: pathlib.Path) -> dict[str, str]:
    """把一个 .env 风格文件解析成 dict(与 crab.py / checkup.py 同款极简解析)。"""
    out: dict[str, str] = {}
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.split(" #", 1)[0].strip()   # 剥行内注释(# 前需空格)
        out[key.strip()] = val
    return out


# ── 校验项 ──────────────────────────────────────────────────────────
def check_example_exists() -> list[Finding]:
    """🗂️ 配置范本 .env.example 在不在(它是所有键的真相源)。"""
    p = REPO_ROOT / ".env.example"
    if p.is_file():
        return [_ok(".env.example", f"{len(parse_env_file(p))} 个键的范本")]
    return [_err(".env.example", "缺失：没有范本就无从校验配置一致性",
                 "补回 .env.example，列出所有 OPENCRAB_* 键及其默认值")]


def check_env_parity() -> list[Finding]:
    """🔑 .env 与 .env.example 的键是否对齐(缺键 / 孤儿键)。"""
    env_path = REPO_ROOT / ".env"
    example_path = REPO_ROOT / ".env.example"
    if not example_path.is_file():
        return []   # 范本都没有，交给 check_example_exists 报
    if not env_path.is_file():
        return [_warn(".env",
                      "无 .env，按梦境模式运行(读不到配置则全走默认值)",
                      "想接真大脑：cp .env.example .env 后填 OPENCRAB_API_KEY")]

    expected = set(parse_env_file(example_path))
    actual = set(parse_env_file(env_path))
    out: list[Finding] = []

    missing = sorted(expected - actual)
    if missing:
        out.append(_err(".env 缺键", f"{', '.join(missing)}",
                        "参照 .env.example 把这些键补进 .env(没填会回落默认值，"
                        "但显式写出能避免行为漂移)"))
    orphans = sorted(actual - expected - INTERNAL_ENV)
    if orphans:
        out.append(_warn(".env 孤儿键",
                         f"{', '.join(orphans)}（.env.example 里没有）",
                         "多半是拼错或过期配置：核对拼写，或从 .env 删掉；"
                         "若是新增的正式配置，记得同步写进 .env.example"))
    if not missing and not orphans:
        out.append(_ok(".env 键对齐", f"{len(expected)} 个键与范本一致"))
    return out


def check_values() -> list[Finding]:
    """🔢 .env 里数值/枚举型配置填得能不能用(填错心跳一启动就崩)。"""
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return []
    env = parse_env_file(env_path)
    out: list[Finding] = []

    for key, parser in NUMERIC_ENV.items():
        raw = env.get(key, "")
        if raw == "":
            continue   # 未填 -> 走默认值，不算错
        try:
            parser(raw)
        except (ValueError, TypeError):
            kind = "整数" if parser is int else "数字"
            out.append(_err(f"数值 {key}", f"{raw!r} 不是合法{kind}",
                            f"把 {key} 改成合法{kind}(参考 .env.example 的默认值)"))

    for key, allowed in ENUM_ENV.items():
        raw = env.get(key, "")
        if raw and raw not in allowed:
            out.append(_err(f"取值 {key}", f"{raw!r} 不在可选范围",
                            f"把 {key} 改成这几个之一：{'/'.join(sorted(allowed))}"))

    if not any(f.level == ERROR for f in out):
        out.append(_ok("数值与取值", "数字/枚举项均可解析、合法"))
    return out


def check_api_key() -> list[Finding]:
    """🧠 大脑钥匙 OPENCRAB_API_KEY 填没填(空=梦境模式，只提示不阻断)。"""
    env_path = REPO_ROOT / ".env"
    env = parse_env_file(env_path) if env_path.is_file() else {}
    if env.get("OPENCRAB_API_KEY", "").strip():
        return [_ok("大脑钥匙", "OPENCRAB_API_KEY 已填")]
    return [_warn("大脑钥匙", "OPENCRAB_API_KEY 为空 —— 梦境模式(不接真大脑)",
                  "想接真大脑：在 .env 填上任意 OpenAI 兼容 key")]


def _parse_requirement(line: str) -> tuple[str, list[tuple[str, str]]] | None:
    """把一行 requirement 解析成 (包名, [(运算符, 版本), ...])；解析不了返回 None。"""
    import re
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(\[[^\]]*\])?\s*(.*)$", line)
    if not m:
        return None
    name = m.group(1)
    specs: list[tuple[str, str]] = []
    for op, ver in re.findall(r"(==|>=|<=|~=|!=|>|<)\s*([0-9][\w.*+!-]*)",
                              m.group(3) or ""):
        specs.append((op, ver))
    return name, specs


def _version_tuple(v: str) -> tuple:
    """把版本串切成可比较的元组(只取前导数字段，宽容地忽略后缀)。"""
    import re
    parts = []
    for chunk in v.split("."):
        m = re.match(r"\d+", chunk)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


def _spec_satisfied(installed: str, op: str, want: str) -> bool:
    """判断已装版本 installed 是否满足约束 (op, want)。"""
    a, b = _version_tuple(installed), _version_tuple(want)
    if op == "==":
        return installed == want or a == b
    if op == "!=":
        return not (installed == want or a == b)
    if op == ">=":
        return a >= b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == "<":
        return a < b
    if op == "~=":      # 兼容版本：>=want 且同一主段
        return a >= b and a[:max(len(b) - 1, 1)] == b[:max(len(b) - 1, 1)]
    return True


def check_dependencies() -> list[Finding]:
    """📦 本机依赖版本是否符合 requirements.txt 的约定(防版本漂移)。"""
    import importlib.metadata as md

    reqs = REPO_ROOT / "requirements.txt"
    if not reqs.is_file():
        return [_warn("requirements.txt", "缺失",
                      "补一个 requirements.txt(本体零第三方就留空，也是一种声明)")]

    parsed = [_parse_requirement(ln) for ln in reqs.read_text("utf-8").splitlines()]
    parsed = [p for p in parsed if p]
    if not parsed:
        return [_ok("第三方依赖", "requirements.txt 为空(零第三方，符合设计)")]

    out: list[Finding] = []
    for name, specs in parsed:
        try:
            installed = md.version(name)
        except md.PackageNotFoundError:
            out.append(_err(f"依赖 {name}", "未安装",
                            "pip install -r requirements.txt"))
            continue
        bad = [(op, ver) for op, ver in specs
               if not _spec_satisfied(installed, op, ver)]
        if bad:
            want = ", ".join(f"{op}{ver}" for op, ver in bad)
            out.append(_err(f"依赖 {name}",
                            f"已装 {installed}，不满足 {want}",
                            f"pip install '{name}{want}' 对齐到约定版本"))
        else:
            shown = "".join(f"{op}{ver}" for op, ver in specs)
            out.append(_ok(f"依赖 {name}", f"已装 {installed}"
                           + (f"（满足 {shown}）" if shown else "")))
    return out


CHECKS = [check_example_exists, check_env_parity, check_values,
          check_api_key, check_dependencies]


def run() -> list[Finding]:
    """跑完所有一致性校验，返回发现列表(校验自身出错也收敛成一条 error)。"""
    findings: list[Finding] = []
    for chk in CHECKS:
        try:
            findings.extend(chk())
        except Exception as e:
            findings.append(_err(chk.__name__, f"校验异常：{e}",
                                 "这是 envcheck 自己出的错，贴出来看看哪步炸了"))
    return findings


def summarize(findings: list[Finding], *, strict: bool = False) -> tuple[bool, int, int]:
    """归总：(是否通过, error 数, warn 数)。strict 下 warn 也算未过。"""
    errors = sum(1 for f in findings if f.level == ERROR)
    warns = sum(1 for f in findings if f.level == WARN)
    healthy = errors == 0 and (warns == 0 if strict else True)
    return healthy, errors, warns


def manifest() -> dict:
    """🔧 一致性校验结果(纯数据，供能力/外部工具消费)。"""
    findings = run()
    healthy, errors, warns = summarize(findings)
    return {"healthy": healthy, "errors": errors, "warns": warns,
            "findings": [f.to_meta() for f in findings]}


_MARK = {OK: "✅", WARN: "⚠️", ERROR: "❌"}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 配置与环境一致性校验 🔧")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有 error 时输出(适合钩子 / CI)")
    ap.add_argument("--strict", action="store_true",
                    help="把 warn 也视作未过(更严格的门禁)")
    args = ap.parse_args(argv)

    findings = run()
    healthy, errors, warns = summarize(findings, strict=args.strict)

    if not (args.quiet and healthy):
        print("🔧 opencrab 配置与环境一致性校验\n")
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
            tail = "（含 %d 处提醒）" % warns if warns else ""
            print(f"🦀 一致：{len(findings)} 项校验通过{tail}，运行条件对齐。")
    else:
        bits = []
        if errors:
            bits.append(f"{errors} 处不一致")
        if args.strict and warns:
            bits.append(f"{warns} 处提醒")
        print(f"⚠️  环境校验发现 {' · '.join(bits)}，先按上面的修复建议对齐再启动。")
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
