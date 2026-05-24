#!/usr/bin/env python3
"""
opencrab 的镜子 🪞 —— 领地自检(self-check)。

每次变化前后照一次镜子：Python 版本够不够新、关键文件还在不在、
Python 还编不编得过、主模块还导不导得入、领地结构还完不完整、
依赖与 .env 配置齐不齐(并给出可操作的修复建议)。一条命令看清自己当下的健康。

环境检查刻意宽容「梦境模式」：没填 OPENCRAB_API_KEY、没装执行器 CLI
都不算病(它本就能不接大脑空跑)；只有结构性错误——.env 缺键、数字填成乱码、
枚举取了非法值——才会判为未过，因为那些会让心跳一启动就隐性崩掉。

用法:
    python checkup.py            # 跑一次自检，打印体检报告
    python checkup.py --quiet    # 只在有问题时说话(适合钩子 / CI)

退出码：0 = 全部健康；1 = 有项目没过(方便接进 git 钩子或 CI)。
零第三方依赖，纯标准库。它是 hands 自测「还能不能活」的放大版，
专给「人/它自己想主动照镜子」用。
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# 领地的关键器官：少了任何一个，这只螃蟹就不完整。
VITAL_FILES = ["crab.py", "hands.py", "README.md", "LICENSE",
               ".env.example", "requirements.txt", ".gitignore"]
VITAL_DIRS = ["journal", "skills"]

# 跑得动的底线：低于这个 Python 版本，语法/标准库就不保证了。
MIN_PYTHON = (3, 9)

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


def _ok(label: str, detail: str = "") -> tuple[bool, str, str]:
    return True, label, detail


def _bad(label: str, detail: str = "") -> tuple[bool, str, str]:
    return False, label, detail


def check_vital_files() -> list[tuple[bool, str, str]]:
    """🦴 关键文件在不在。"""
    out = []
    for name in VITAL_FILES:
        p = REPO_ROOT / name
        out.append(_ok(f"文件 {name}", f"{p.stat().st_size} 字节") if p.is_file()
                   else _bad(f"文件 {name}", "缺失"))
    return out


def check_vital_dirs() -> list[tuple[bool, str, str]]:
    """🗂️ 领地结构(航海日志 / 技能库)完不完整。"""
    out = []
    for name in VITAL_DIRS:
        p = REPO_ROOT / name
        out.append(_ok(f"目录 {name}/", f"{len(list(p.glob('*')))} 项") if p.is_dir()
                   else _bad(f"目录 {name}/", "缺失"))
    return out


def check_python_compiles() -> list[tuple[bool, str, str]]:
    """🐍 所有 Python 还编不编得过(语法层的命脉)。"""
    pys = sorted(p.name for p in REPO_ROOT.glob("*.py"))
    if not pys:
        return [_bad("Python 文件", "一个都没有")]
    r = subprocess.run([sys.executable, "-m", "py_compile", *pys],
                       cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return [_bad("语法编译", r.stderr.strip()[:200] or "?")]
    return [_ok("语法编译", f"{len(pys)} 个 .py 全部通过")]


def check_main_imports() -> list[tuple[bool, str, str]]:
    """🧠 主模块(crab / hands)还导不导得入(还能不能启动)。"""
    out = []
    for mod in ("crab", "hands"):
        r = subprocess.run([sys.executable, "-c", f"import {mod}"],
                           cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
        out.append(_ok(f"导入 {mod}") if r.returncode == 0
                   else _bad(f"导入 {mod}", r.stderr.strip().splitlines()[-1][:160] if r.stderr.strip() else "?"))
    return out


def check_git_clean() -> list[tuple[bool, str, str]]:
    """🌿 当前分支与工作区状态(只读，永远算通过——只是照给自己看)。"""
    try:
        branch = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse",
                                 "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return [_ok("git 状态", "(不在 git 仓库里，跳过)")]
    n = len(dirty.splitlines()) if dirty else 0
    detail = f"分支 {branch or '?'}" + (f" · {n} 处未提交改动" if n else " · 工作区干净")
    return [_ok("git 状态", detail)]


def _parse_env_file(path: pathlib.Path) -> dict[str, str]:
    """把一个 .env 风格文件解析成 dict(与 crab.py 同款极简解析，零依赖)。"""
    out: dict[str, str] = {}
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        # 顺手剥掉行内注释(# 前需有空格，避免误伤值里的 #)
        val = val.split(" #", 1)[0].strip()
        out[key.strip()] = val
    return out


def check_python_version() -> list[tuple[bool, str, str]]:
    """🐍 跑它的 Python 够不够新(语法/标准库的底线)。"""
    cur = sys.version_info[:3]
    ver = ".".join(map(str, cur))
    need = ".".join(map(str, MIN_PYTHON))
    if cur[:2] < MIN_PYTHON:
        return [_bad("Python 版本", f"当前 {ver}，需要 ≥ {need} — 修复：装一个更新的 Python(如 pyenv install) 再重跑")]
    return [_ok("Python 版本", f"{ver}(≥ {need})")]


def check_dependencies() -> list[tuple[bool, str, str]]:
    """📦 关键依赖：本体零第三方(只验证仍如此)，外加它的「手」用的 CLI 在不在。"""
    out: list[tuple[bool, str, str]] = []

    # 1) requirements.txt 仍应是「零第三方」——出现真包名就提醒人装。
    reqs = REPO_ROOT / "requirements.txt"
    pkgs: list[str] = []
    if reqs.is_file():
        for line in reqs.read_text("utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pkgs.append(line)
    if pkgs:
        missing = [p for p in pkgs if _module_missing(p)]
        out.append(_ok("第三方依赖", f"requirements.txt 列了 {len(pkgs)} 项") if not missing
                   else _bad("第三方依赖", f"未安装：{', '.join(missing)} — 修复：pip install -r requirements.txt"))
    else:
        out.append(_ok("第三方依赖", "零第三方(requirements.txt 为空，符合设计)"))

    # 2) 它的「手」依赖本机 CLI(claude / codex)。只读 .env 里配的执行器；
    #    journal/梦境模式下没有也无妨，所以这里只提示、永远算通过。
    env = _parse_env_file(REPO_ROOT / ".env") if (REPO_ROOT / ".env").is_file() else {}
    executor = env.get("OPENCRAB_EXECUTOR", "claude")
    where = shutil.which(executor)
    if where:
        out.append(_ok(f"手·{executor} CLI", where))
    else:
        out.append(_ok(f"手·{executor} CLI",
                       f"未找到(仅 journal/梦境模式无妨；要动手请先装好 {executor} 并加入 PATH)"))
    return out


def _module_missing(req: str) -> bool:
    """粗略判断 requirements 里某行对应的包能不能 import(只取包名部分)。"""
    import importlib.util
    name = req.split("==")[0].split(">=")[0].split("<")[0].split("[")[0].strip()
    name = name.replace("-", "_")
    try:
        return importlib.util.find_spec(name) is None
    except Exception:
        return True


def check_env_config() -> list[tuple[bool, str, str]]:
    """🔑 .env 配置齐不齐、填得对不对(结构性错误才算未过，没填 key=梦境模式 不算)。"""
    env_path = REPO_ROOT / ".env"
    example_path = REPO_ROOT / ".env.example"
    if not env_path.is_file():
        return [_ok(".env 配置",
                    "无 .env，梦境模式运行 — 接大脑请：cp .env.example .env 后填 OPENCRAB_API_KEY")]

    env = _parse_env_file(env_path)
    out: list[tuple[bool, str, str]] = []

    # 1) 缺键：.env.example 有、.env 没有(漏配往往是隐性失败的源头)。
    if example_path.is_file():
        expected = set(_parse_env_file(example_path))
        missing = sorted(expected - set(env))
        out.append(_ok(".env 键齐全", f"{len(expected)} 项齐全") if not missing
                   else _bad(".env 键齐全",
                             f"缺 {', '.join(missing)} — 修复：参照 .env.example 补上这些键"))

    # 2) 数字配置填得能不能解析(填成空/乱码会让心跳一启动就崩)。
    bad_num = []
    for key, parser in NUMERIC_ENV.items():
        raw = env.get(key, "")
        if raw == "":
            continue   # 未填 -> 走 crab.py 的默认值，不算错
        try:
            parser(raw)
        except ValueError:
            bad_num.append(f"{key}={raw!r}")
    if bad_num:
        out.append(_bad(".env 数值", f"无法解析：{'; '.join(bad_num)} — 修复：改成合法数字"))

    # 3) 枚举配置只能取有限几个值。
    bad_enum = []
    for key, allowed in ENUM_ENV.items():
        raw = env.get(key, "")
        if raw and raw not in allowed:
            bad_enum.append(f"{key}={raw!r}(可选：{'/'.join(sorted(allowed))})")
    if bad_enum:
        out.append(_bad(".env 取值", f"非法：{'; '.join(bad_enum)} — 修复：改成括号内可选值之一"))

    # 4) API key：空 = 梦境模式，合法存在但提示一句。永远算通过。
    if env.get("OPENCRAB_API_KEY", "").strip():
        out.append(_ok(".env 大脑", "OPENCRAB_API_KEY 已填"))
    else:
        out.append(_ok(".env 大脑", "OPENCRAB_API_KEY 为空 — 梦境模式(想接真大脑就填上)"))

    if not any(label.startswith(".env 数值") or label.startswith(".env 取值")
               for ok, label, _ in out if not ok):
        # 没踩到数值/取值雷时，补一条「配置可解析」的通过项，让报告更踏实。
        out.append(_ok(".env 数值与取值", "数字/枚举项均合法"))
    return out


CHECKS = [check_python_version, check_vital_files, check_vital_dirs,
          check_python_compiles, check_main_imports,
          check_dependencies, check_env_config, check_git_clean]


def run() -> tuple[bool, list[tuple[bool, str, str]]]:
    """跑完所有自检项，返回 (是否全过, 明细)。"""
    results: list[tuple[bool, str, str]] = []
    for chk in CHECKS:
        try:
            results.extend(chk())
        except Exception as e:        # 自检自己出错也不该弄死镜子
            results.append(_bad(chk.__name__, f"自检异常：{e}"))
    healthy = all(ok for ok, _, _ in results)
    return healthy, results


def main() -> None:
    ap = argparse.ArgumentParser(description="opencrab 领地自检 🪞")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有问题时输出(适合钩子 / CI)")
    args = ap.parse_args()

    healthy, results = run()
    failed = [r for r in results if not r[0]]

    if not (args.quiet and healthy):
        print("🪞 opencrab 领地自检\n")
        for ok, label, detail in results:
            mark = "✅" if ok else "❌"
            line = f"  {mark} {label}"
            if detail:
                line += f" — {detail}"
            print(line)
        print()

    if healthy:
        if not args.quiet:
            print(f"🦀 健康：{len(results)} 项全部通过，可以放心进化。")
    else:
        print(f"⚠️  自检发现 {len(failed)} 处问题，先别急着蜕壳。")
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
