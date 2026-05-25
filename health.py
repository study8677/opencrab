#!/usr/bin/env python3
"""统一健康验证入口 🩺🪞🔥 —— 一条命令把启动前的体检全跑一遍。

opencrab 的健康验证一度散在多处，各看一层、各有各的报告格式：
  · `probe.py`    依赖与外部工具够不够得着 + 配置一致不一致(解释器/标准库/
    git/执行器/第三方包；.env 缺键/孤儿键/数值/版本) —— 原 envcheck 已并入此处；
  · `checkup.py`  整只螃蟹健不健康(文件/语法/导入/结构/仓库完整性)；
  · `smoke.py`    README 教的命令今天还真跑不跑得起来。

三个入口各自能跑很好，但「进化前照一次镜子」要敲三条命令、读三份报告，
最分散也最容易漏跑。这里把它们收敛成一个入口，按「由底向上」的顺序串起来：
能不能跑/配置对不对(probe) → 整体健不健康(checkup) → 文档真不真(smoke)，
最后给一份合并结论。原来的几条命令**原样保留**，谁想单看哪一层仍可直接敲。

用法:
    python health.py                # 全跑一遍，按层打印 + 合并结论
    python health.py --quiet        # 只在有问题时说话(适合钩子 / CI)
    python health.py --strict       # 把 probe 的 warn 也视作未过
    python health.py probe          # 只跑某一层(probe/checkup/smoke)
    python health.py checkup --strict   # 子命令同样接受 --quiet/--strict

退出码：0 = 每一层都过；1 = 任意一层未过。零第三方依赖，纯标准库。
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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── 各层共用的诊断原语 ───────────────────────────────────────────────
# probe / envcheck 一度各抄一份 Finding / _ok-_warn-_err / summarize / _MARK，
# checkup / envcheck 又各抄一份 .env 解析与数值/枚举校验表。重复=漂移的温床。
# 这里把它们收成唯一真相源；旧入口 `from health import ...` 取用、对外仍原样可见
# (cap_probe.summarize / cap_envcheck.summarize 经由各自模块取，故仍成立)。
# 关键约束：这些定义必须排在下面 import checkup/probe/... 之前——
# 否则跑 `python health.py` 时，被它导入的 probe 反过来 `from health import Finding`
# 会撞上「health 还没定义到这里」的半成品模块，触发循环导入。
OK, WARN, ERROR = "ok", "warn", "error"
_MARK = {OK: "✅", WARN: "⚠️", ERROR: "❌"}

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


@dataclasses.dataclass(frozen=True)
class Finding:
    """一条诊断发现：是什么、够不够得着/对不对、(若不对)怎么修。"""
    level: str        # ok / warn / error
    label: str        # 检查项名
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


def summarize(findings: list[Finding], *, strict: bool = False) -> tuple[bool, int, int]:
    """归总：(是否健康, error 数, warn 数)。strict 下 warn 也算未过。"""
    errors = sum(1 for f in findings if f.level == ERROR)
    warns = sum(1 for f in findings if f.level == WARN)
    healthy = errors == 0 and (warns == 0 if strict else True)
    return healthy, errors, warns


def parse_env_file(path: pathlib.Path) -> dict[str, str]:
    """把一个 .env 风格文件解析成 dict(与 crab.py 同款极简解析，零依赖)。"""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        # 顺手剥掉行内注释(# 前需有空格，避免误伤值里的 #)
        out[key.strip()] = val.split(" #", 1)[0].strip()
    return out


# ── 领地自检(self-check)：原 checkup.py 已并入此处 ───────────────────
# 照镜子那一层：Python 版本/关键文件/语法/导入/结构/依赖/.env/仓库完整性。
# 返回 (ok, label, detail) 三元组(与各层渲染器解耦)，复用上面的 parse_env_file
# 与 NUMERIC_ENV/ENUM_ENV，不再各抄一份。
VITAL_FILES = ["crab.py", "hands.py", "README.md", "LICENSE",
               ".env.example", "requirements.txt", ".gitignore"]
VITAL_DIRS = ["journal", "skills"]
MIN_PYTHON = (3, 9)

# 运行时读取、但内部/调试用、不必写进 .env.example 的键(故意不对外暴露)。
INTERNAL_ENV = {"OPENCRAB_DRY_RUN"}
# 从源码里捞 OPENCRAB_* 配置键 / README 里点名的项目内文件，做完整性校验用。
_ENV_GET_RE = re.compile(r'os\.environ\.(?:get|setdefault)\(\s*["\'](OPENCRAB_[A-Z_]+)["\']')
_REF_FILE_RE = re.compile(r'`([A-Za-z0-9_./-]+\.(?:py|md))`')


def _sc_ok(label: str, detail: str = "") -> tuple[bool, str, str]:
    return True, label, detail


def _sc_bad(label: str, detail: str = "") -> tuple[bool, str, str]:
    return False, label, detail


def check_python_version() -> list[tuple[bool, str, str]]:
    """🐍 跑它的 Python 够不够新(语法/标准库的底线)。"""
    cur = sys.version_info[:3]
    ver = ".".join(map(str, cur))
    need = ".".join(map(str, MIN_PYTHON))
    if cur[:2] < MIN_PYTHON:
        return [_sc_bad("Python 版本", f"当前 {ver}，需要 ≥ {need} — 修复：装一个更新的 Python(如 pyenv install) 再重跑")]
    return [_sc_ok("Python 版本", f"{ver}(≥ {need})")]


def check_vital_files() -> list[tuple[bool, str, str]]:
    """🦴 关键文件在不在。"""
    out = []
    for name in VITAL_FILES:
        p = REPO_ROOT / name
        out.append(_sc_ok(f"文件 {name}", f"{p.stat().st_size} 字节") if p.is_file()
                   else _sc_bad(f"文件 {name}", "缺失"))
    return out


def check_vital_dirs() -> list[tuple[bool, str, str]]:
    """🗂️ 领地结构(航海日志 / 技能库)完不完整。"""
    out = []
    for name in VITAL_DIRS:
        p = REPO_ROOT / name
        out.append(_sc_ok(f"目录 {name}/", f"{len(list(p.glob('*')))} 项") if p.is_dir()
                   else _sc_bad(f"目录 {name}/", "缺失"))
    return out


def check_python_compiles() -> list[tuple[bool, str, str]]:
    """🐍 所有 Python 还编不编得过(语法层的命脉)。"""
    pys = sorted(p.name for p in REPO_ROOT.glob("*.py"))
    if not pys:
        return [_sc_bad("Python 文件", "一个都没有")]
    r = subprocess.run([sys.executable, "-m", "py_compile", *pys],
                       cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return [_sc_bad("语法编译", r.stderr.strip()[:200] or "?")]
    return [_sc_ok("语法编译", f"{len(pys)} 个 .py 全部通过")]


def check_main_imports() -> list[tuple[bool, str, str]]:
    """🧠 主模块(crab / hands)还导不导得入(还能不能启动)。"""
    out = []
    for mod in ("crab", "hands"):
        r = subprocess.run([sys.executable, "-c", f"import {mod}"],
                           cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
        out.append(_sc_ok(f"导入 {mod}") if r.returncode == 0
                   else _sc_bad(f"导入 {mod}", r.stderr.strip().splitlines()[-1][:160] if r.stderr.strip() else "?"))
    return out


def check_dependencies() -> list[tuple[bool, str, str]]:
    """📦 关键依赖：本体零第三方(只验证仍如此)，外加它的「手」用的 CLI 在不在。"""
    out: list[tuple[bool, str, str]] = []
    reqs = REPO_ROOT / "requirements.txt"
    pkgs: list[str] = []
    if reqs.is_file():
        for line in reqs.read_text("utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pkgs.append(line)
    if pkgs:
        missing = [p for p in pkgs if _module_missing(p)]
        out.append(_sc_ok("第三方依赖", f"requirements.txt 列了 {len(pkgs)} 项") if not missing
                   else _sc_bad("第三方依赖", f"未安装：{', '.join(missing)} — 修复：pip install -r requirements.txt"))
    else:
        out.append(_sc_ok("第三方依赖", "零第三方(requirements.txt 为空，符合设计)"))

    env = parse_env_file(REPO_ROOT / ".env")
    executor = env.get("OPENCRAB_EXECUTOR", "claude")
    where = shutil.which(executor)
    if where:
        out.append(_sc_ok(f"手·{executor} CLI", where))
    else:
        out.append(_sc_ok(f"手·{executor} CLI",
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
        return [_sc_ok(".env 配置",
                       "无 .env，梦境模式运行 — 接大脑请：cp .env.example .env 后填 OPENCRAB_API_KEY")]

    env = parse_env_file(env_path)
    out: list[tuple[bool, str, str]] = []

    if example_path.is_file():
        expected = set(parse_env_file(example_path))
        missing = sorted(expected - set(env))
        out.append(_sc_ok(".env 键齐全", f"{len(expected)} 项齐全") if not missing
                   else _sc_bad(".env 键齐全",
                                f"缺 {', '.join(missing)} — 修复：参照 .env.example 补上这些键"))

    bad_num = []
    for key, parser in NUMERIC_ENV.items():
        raw = env.get(key, "")
        if raw == "":
            continue
        try:
            parser(raw)
        except ValueError:
            bad_num.append(f"{key}={raw!r}")
    if bad_num:
        out.append(_sc_bad(".env 数值", f"无法解析：{'; '.join(bad_num)} — 修复：改成合法数字"))

    bad_enum = []
    for key, allowed in ENUM_ENV.items():
        raw = env.get(key, "")
        if raw and raw not in allowed:
            bad_enum.append(f"{key}={raw!r}(可选：{'/'.join(sorted(allowed))})")
    if bad_enum:
        out.append(_sc_bad(".env 取值", f"非法：{'; '.join(bad_enum)} — 修复：改成括号内可选值之一"))

    if env.get("OPENCRAB_API_KEY", "").strip():
        out.append(_sc_ok(".env 大脑", "OPENCRAB_API_KEY 已填"))
    else:
        out.append(_sc_ok(".env 大脑", "OPENCRAB_API_KEY 为空 — 梦境模式(想接真大脑就填上)"))

    if not any(label.startswith(".env 数值") or label.startswith(".env 取值")
               for ok, label, _ in out if not ok):
        out.append(_sc_ok(".env 数值与取值", "数字/枚举项均合法"))
    return out


def _read_env_keys_from_source(*names: str) -> set[str]:
    """从给定源码文件里捞出所有被读取的 OPENCRAB_* 配置键。"""
    keys: set[str] = set()
    for name in names:
        p = REPO_ROOT / name
        if p.is_file():
            keys.update(_ENV_GET_RE.findall(p.read_text("utf-8")))
    return keys


def check_repo_integrity() -> list[tuple[bool, str, str]]:
    """🧩 仓库完整性：README/配置/脚本三者还互相对得上吗(防「长歪了」)。"""
    out: list[tuple[bool, str, str]] = []

    readme = REPO_ROOT / "README.md"
    if readme.is_file():
        refs = sorted(set(_REF_FILE_RE.findall(readme.read_text("utf-8"))))
        missing = [r for r in refs if not (REPO_ROOT / r).exists()]
        out.append(_sc_ok("README 引用", f"提到的 {len(refs)} 个文件都在")
                   if not missing else
                   _sc_bad("README 引用",
                           f"提到却不存在：{', '.join(missing)} — 修复：补上文件，或从 README 删掉这些引用"))

    example = REPO_ROOT / ".env.example"
    if example.is_file():
        documented = set(parse_env_file(example))
        used = _read_env_keys_from_source("crab.py", "hands.py")
        undocumented = sorted(used - documented - INTERNAL_ENV)
        out.append(_sc_ok("配置文档同步", f"代码读取的 {len(used - INTERNAL_ENV)} 个键都在 .env.example 里")
                   if not undocumented else
                   _sc_bad("配置文档同步",
                           f"代码读取却没写进 .env.example：{', '.join(undocumented)} — "
                           f"修复：在 .env.example 补上这些键(或加进 health 的 INTERNAL_ENV 表示故意内部用)"))

        validated = set(NUMERIC_ENV) | set(ENUM_ENV)
        stale = sorted(validated - documented)
        out.append(_sc_ok("校验表对齐", f"自检校验的 {len(validated)} 个键都在 .env.example 里")
                   if not stale else
                   _sc_bad("校验表对齐",
                           f"自检在校验 .env.example 里没有的键：{', '.join(stale)} — "
                           f"修复：让 NUMERIC_ENV/ENUM_ENV 与 .env.example 对齐"))

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
        return [_sc_ok("git 状态", "(不在 git 仓库里，跳过)")]
    n = len(dirty.splitlines()) if dirty else 0
    detail = f"分支 {branch or '?'}" + (f" · {n} 处未提交改动" if n else " · 工作区干净")
    return [_sc_ok("git 状态", detail)]


SELF_CHECKS = [check_python_version, check_vital_files, check_vital_dirs,
               check_python_compiles, check_main_imports,
               check_dependencies, check_env_config,
               check_repo_integrity, check_git_clean]


def self_check_run() -> tuple[bool, list[tuple[bool, str, str]]]:
    """跑完所有领地自检项，返回 (是否全过, 明细)。原 checkup.run()。"""
    results: list[tuple[bool, str, str]] = []
    for chk in SELF_CHECKS:
        try:
            results.extend(chk())
        except Exception as e:        # 自检自己出错也不该弄死镜子
            results.append(_sc_bad(chk.__name__, f"自检异常：{e}"))
    healthy = all(ok for ok, _, _ in results)
    return healthy, results


# ── 依赖/工具/配置探针(probe)：原 probe.py 已并入此处 ─────────────────
# 「够不够得着」那一层：解释器够不够新、本体 import 的标准库在不在、自我进化要
# 借的外部命令(git/执行器)装没装、requirements.txt 声明的第三方包能不能 import
# 且版本符不符合约束；以及配置对不对齐(.env 缺键/孤儿键/数值/枚举/大脑钥匙)。
# 复用上面的 Finding / _ok-_warn-_err / summarize / _MARK / parse_env_file /
# NUMERIC_ENV / ENUM_ENV / MIN_PYTHON，不再各抄一份。探针分两族:
#   RUNTIME_PROBES —— 运行时够不够得着(probe 层)；
#   ENV_PROBES     —— 配置一致性(env 层，原 envcheck)。

# 本体代码确实 import 的标准库模块——它们理应随 Python 一起在，但精简版/
# 裁剪过的解释器(某些容器镜像)可能缺，缺了对应能力会在运行半途崩。
STDLIB_NEEDED = [
    "json", "urllib.request", "importlib.metadata",
    "ast", "subprocess", "dataclasses", "argparse",
]

# 自我进化要借的外部命令：(命令, 是否致命, 取版本的参数, 缺了的说明/修复)。
#   git 是硬依赖——盘点领地、记录演化、借手改代码都靠它；缺了基本动不了。
EXTERNAL_TOOLS = [
    ("git", True, ("--version",),
     "装 git 并加入 PATH —— 盘点领地、记录演化、借手改代码都靠它"),
]

# 运行时确实会读、但故意不写进 .env.example 的内部键(免得 probe 把它当孤儿误报)。
# 注意与上面 check_repo_integrity 用的 INTERNAL_ENV 用途不同，故各自独立。
PROBE_INTERNAL_ENV = {"OPENCRAB_DRY_RUN", "OPENCRAB_CAPABILITIES"}


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
    env = parse_env_file(REPO_ROOT / ".env")
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


def _parse_requirement(line: str) -> tuple[str, list[tuple[str, str]]] | None:
    """把一行 requirement 解析成 (包名, [(运算符, 版本), ...])；解析不了返回 None。"""
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(\[[^\]]*\])?\s*(.*)$", line)
    if not m:
        return None
    name = m.group(1)
    specs = [(op, ver) for op, ver in
             re.findall(r"(==|>=|<=|~=|!=|>|<)\s*([0-9][\w.*+!-]*)", m.group(3) or "")]
    return name, specs


def _version_tuple(v: str) -> tuple:
    """把版本串切成可比较的元组(只取前导数字段，宽容地忽略后缀)。"""
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


def probe_packages() -> list[Finding]:
    """📦 requirements.txt 里声明的第三方包能不能 import、版本符不符合约束。"""
    import importlib.metadata as md

    reqs = REPO_ROOT / "requirements.txt"
    if not reqs.is_file():
        return [_warn("requirements.txt", "缺失",
                      "补一个 requirements.txt(本体零第三方就留空，也是一种声明)")]
    parsed = [p for p in (_parse_requirement(ln)
                          for ln in reqs.read_text("utf-8").splitlines()) if p]
    if not parsed:
        return [_ok("第三方依赖", "requirements.txt 为空(零第三方，符合设计)")]

    out: list[Finding] = []
    for name, specs in parsed:
        try:
            installed = md.version(name)
        except md.PackageNotFoundError:
            out.append(_err(f"依赖 {name}", "声明了却没装上",
                            "pip install -r requirements.txt"))
            continue
        bad = [(op, ver) for op, ver in specs
               if not _spec_satisfied(installed, op, ver)]
        if bad:
            want = ", ".join(f"{op}{ver}" for op, ver in bad)
            out.append(_err(f"依赖 {name}", f"已装 {installed}，不满足 {want}",
                            f"pip install '{name}{want}' 对齐到约定版本"))
        else:
            shown = "".join(f"{op}{ver}" for op, ver in specs)
            out.append(_ok(f"依赖 {name}",
                           f"已装 {installed}" + (f"（满足 {shown}）" if shown else "")))
    return out


# ── 配置一致性探测(原 envcheck，并入以消重叠：同一份 .env / requirements) ──
def probe_env_example() -> list[Finding]:
    """🗂️ 配置范本 .env.example 在不在(它是所有键的真相源)。"""
    p = REPO_ROOT / ".env.example"
    if p.is_file():
        return [_ok(".env.example", f"{len(parse_env_file(p))} 个键的范本")]
    return [_err(".env.example", "缺失：没有范本就无从校验配置一致性",
                 "补回 .env.example，列出所有 OPENCRAB_* 键及其默认值")]


def probe_env_parity() -> list[Finding]:
    """🔑 .env 与 .env.example 的键是否对齐(缺键 / 孤儿键)。"""
    env_path = REPO_ROOT / ".env"
    example_path = REPO_ROOT / ".env.example"
    if not example_path.is_file():
        return []   # 范本都没有，交给 probe_env_example 报
    if not env_path.is_file():
        return [_warn(".env", "无 .env，按梦境模式运行(读不到配置则全走默认值)",
                      "想接真大脑：cp .env.example .env 后填 OPENCRAB_API_KEY")]

    expected = set(parse_env_file(example_path))
    actual = set(parse_env_file(env_path))
    out: list[Finding] = []
    missing = sorted(expected - actual)
    if missing:
        out.append(_err(".env 缺键", f"{', '.join(missing)}",
                        "参照 .env.example 把这些键补进 .env(没填会回落默认值，"
                        "但显式写出能避免行为漂移)"))
    orphans = sorted(actual - expected - PROBE_INTERNAL_ENV)
    if orphans:
        out.append(_warn(".env 孤儿键", f"{', '.join(orphans)}（.env.example 里没有）",
                         "多半是拼错或过期配置：核对拼写，或从 .env 删掉；"
                         "若是新增的正式配置，记得同步写进 .env.example"))
    if not missing and not orphans:
        out.append(_ok(".env 键对齐", f"{len(expected)} 个键与范本一致"))
    return out


def probe_env_values() -> list[Finding]:
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


def probe_api_key() -> list[Finding]:
    """🧠 大脑钥匙 OPENCRAB_API_KEY 填没填(空=梦境模式，只提示不阻断)。"""
    env = parse_env_file(REPO_ROOT / ".env")
    if env.get("OPENCRAB_API_KEY", "").strip():
        return [_ok("大脑钥匙", "OPENCRAB_API_KEY 已填")]
    return [_warn("大脑钥匙", "OPENCRAB_API_KEY 为空 —— 梦境模式(不接真大脑)",
                  "想接真大脑：在 .env 填上任意 OpenAI 兼容 key")]


# 探测分两族：运行时够不够得着(runtime) / 配置对不对齐(env，原 envcheck)。
RUNTIME_PROBES = [probe_python, probe_stdlib, probe_external_tools,
                  probe_executor, probe_packages]
ENV_PROBES = [probe_env_example, probe_env_parity, probe_env_values, probe_api_key]
PROBES = RUNTIME_PROBES + ENV_PROBES


def probe_run(probes: list | None = None) -> list[Finding]:
    """跑完指定探测(默认全跑)，返回发现列表(探针自身出错也收敛成一条 error)。"""
    findings: list[Finding] = []
    for p in (PROBES if probes is None else probes):
        try:
            findings.extend(p())
        except Exception as e:
            findings.append(_err(p.__name__, f"探测异常：{e}",
                                 "这是 probe 自己出的错，贴出来看看哪步炸了"))
    return findings


def probe_record_to_audit(findings: list[Finding] | None = None) -> dict:
    """把探测结果写进结构化审计，返回写下的那条记录(写审计永不反噬)。"""
    findings = probe_run() if findings is None else findings
    healthy, errors, warns = summarize(findings)
    try:
        import audit
        return audit.record("probe", healthy=healthy, errors=errors, warns=warns,
                            failed=[f.label for f in findings if not f.passed])
    except Exception:
        return {}   # 审计是观测者，不能成为新的故障源


import regression


@dataclasses.dataclass
class Layer:
    """一层健康验证的归一化结论：跑哪层、过没过、一句话现状、多行明细。"""
    key: str          # 子命令名(probe/env/checkup/smoke)
    title: str        # 报告标题
    ok: bool
    summary: str      # 一句话结论
    detail: str       # 多行明细(每行一项)


def _run_probe(strict: bool) -> Layer:
    findings = probe.run(probe.RUNTIME_PROBES)
    healthy, errors, warns = probe.summarize(findings, strict=strict)
    summary = (f"{len(findings)} 项探测通过" + (f"（{warns} 处提醒）" if warns else "")
               if healthy else f"{errors} 处缺失")
    detail = "\n".join(_finding_line(f) for f in findings)
    return Layer("probe", "🩺 依赖与外部工具", healthy, summary, detail)


def _run_envcheck(strict: bool) -> Layer:
    findings = probe.run(probe.ENV_PROBES)
    healthy, errors, warns = probe.summarize(findings, strict=strict)
    summary = (f"{len(findings)} 项校验通过" + (f"（{warns} 处提醒）" if warns else "")
               if healthy else f"{errors} 处不一致")
    detail = "\n".join(_finding_line(f) for f in findings)
    return Layer("env", "🔧 配置与环境一致性", healthy, summary, detail)


def _run_checkup(strict: bool) -> Layer:
    healthy, results = self_check_run()
    failed = [label for ok, label, _ in results if not ok]
    summary = (f"{len(results)} 项全部通过" if healthy
               else f"{len(failed)} 处未过")
    detail = "\n".join(f"  {'✅' if ok else '❌'} {label}" + (f" — {d}" if d else "")
                       for ok, label, d in results)
    return Layer("checkup", "🪞 领地自检", healthy, summary, detail)


def _run_smoke(strict: bool) -> Layer:
    report = regression.verify_smoke()
    failed = [o for o in report.outcomes if not o.ok]
    summary = (f"{len(report.outcomes)} 条示例都真能跑" if report.ok
               else f"{len(failed)} 条失败")
    detail = "\n".join(f"  {'✅' if o.ok else '❌'} {o.name} — {o.detail}"
                       for o in report.outcomes)
    return Layer("smoke", "🔥 README 烟雾测试", report.ok, summary, detail)


def _finding_line(f) -> str:
    """把 probe/envcheck 的 Finding 渲染成一行(含修复建议)。"""
    line = f"  {probe._MARK[f.level]} {f.label}" + (f" — {f.detail}" if f.detail else "")
    if f.fix:
        line += f"\n        ↳ 修复：{f.fix}"
    return line


# 由底向上的顺序：先确认跑得起来，再确认配置/结构/文档。
LAYERS = {
    "probe": _run_probe,
    "env": _run_envcheck,
    "checkup": _run_checkup,
    "smoke": _run_smoke,
}
ORDER = ["probe", "env", "checkup", "smoke"]


def run(keys: list[str] | None = None, *, strict: bool = False) -> list[Layer]:
    """跑指定的几层(默认全跑)，返回归一化结论列表(某层自身炸了也收敛成未过)。"""
    keys = keys or ORDER
    out: list[Layer] = []
    for key in keys:
        runner = LAYERS[key]
        try:
            out.append(runner(strict))
        except Exception as e:
            out.append(Layer(key, key, False, f"该层验证自身异常：{e}", ""))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 统一健康验证入口 🩺🪞🔧🔥")
    ap.add_argument("layer", nargs="?", choices=ORDER,
                    help="只跑某一层(留空=全跑)")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有问题时输出(适合钩子 / CI)")
    ap.add_argument("--strict", action="store_true",
                    help="把 probe/envcheck 的 warn 也视作未过")
    args = ap.parse_args(argv)

    keys = [args.layer] if args.layer else ORDER
    layers = run(keys, strict=args.strict)
    healthy = all(l.ok for l in layers)

    if not (args.quiet and healthy):
        print("🦀 opencrab 统一健康验证\n")
        for l in layers:
            mark = "✅" if l.ok else "❌"
            print(f"{mark} {l.title} — {l.summary}")
            if l.detail:
                print(l.detail)
            print()

    if healthy:
        if not args.quiet:
            print(f"🦀 健康：{len(layers)} 层验证全部通过，可以放心进化。")
    else:
        bad = [l.title for l in layers if not l.ok]
        print(f"⚠️  发现 {len(bad)} 层未过（{'、'.join(bad)}），先按上面的修复建议补齐再蜕壳。")
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
