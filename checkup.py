#!/usr/bin/env python3
"""
opencrab 的镜子 🪞 —— 领地自检(self-check)。

每次变化前后照一次镜子：关键文件还在不在、Python 还编不编得过、
主模块还导不导得入、领地结构还完不完整。一条命令看清自己当下的健康。

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
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# 领地的关键器官：少了任何一个，这只螃蟹就不完整。
VITAL_FILES = ["crab.py", "hands.py", "README.md", "LICENSE",
               ".env.example", "requirements.txt", ".gitignore"]
VITAL_DIRS = ["journal", "skills"]


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


CHECKS = [check_vital_files, check_vital_dirs, check_python_compiles,
          check_main_imports, check_git_clean]


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
