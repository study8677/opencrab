#!/usr/bin/env python3
"""自生手触觉层 👋🖐️ —— 落笔前后比对目标的副作用足迹，候选**新增**危险即拒收。

为什么要有它：`patchcontract` 验补丁的**形状**（畸形/越界），`patchfitroom` 让候选先穿
临时副本过 语法/import/契约 闸——它们都能挡住「改坏了」「改崩了」「改塌了语义」。可它们
都**摸不到一类更隐蔽的伤**：一个候选编译得过、加载得起、契约也守约，却在原本只算数的函数里
**悄悄长出了新的副作用**——读写文件、动环境变量、连网、起子进程跑命令。这一爪本身「能跑」，
危险却是真的：一个会动手的爪子，不只要会写得「对」，还要**摸得到**自己这一爪会不会伸向
身体之外。手要有触觉。

本层就是那层触觉：把源码里的副作用足迹按四类摸出来——

  · 📂 **IO**     —— 开文件/删改文件/建删目录/改权限（open/os.remove/shutil.*/Path.write_text…）
  · 🌱 **环境变量** —— 读写进程环境（os.getenv/os.putenv/os.environ…）
  · 🌐 **网络**    —— 连网/收发（import socket·urllib·requests…，及它们的调用）
  · ⚙️ **执行命令** —— 起子进程/执行外部命令/动态执行（subprocess.*/os.system/exec/eval…）

落笔时把 **before（真文件原样）** 与 **after（候选）** 各摸一遍，按「同一足迹的出现次数」
做差：候选里**多出来**的那一份副作用，就是这一爪**新增**的危险——`feel` 当场拒收，点名
是哪类、新增了什么。**只拒新增**：原文里本就有的副作用（试衣间自己就满是 subprocess /
tempfile）不算它的账，挪个位置、加行注释这类不碰副作用的改动照样放行。

纯静态、纯内存：只 `ast.parse`（**绝不执行**候选），不起子进程、不碰真文件。读不出
（解析失败）就老实**弃权**（判过、交由语法/契约等闸把关），绝不把「我没看懂」误判成「有危险」
而错杀，也绝不抛错——触觉自己绝不能成为新的伤口。

用法:
    python touch.py                 # 演示：几个候选各摸一遍（无新增/各类新增）
    python touch.py --selfcheck     # 自检：四类新增各能摸出、原有副作用不误伤、解析失败弃权
    python touch.py --json          # 机读：四类足迹的监视清单
    python touch.py --feel PATH     # 从 stdin 读候选，对 PATH(真仓库内)摸出新增副作用
    加 --quiet 静默，仅以退出码表态。

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import ast
import collections
import dataclasses
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# ── 四类副作用的机读码 → 人话标签 ──────────────────────────────────────
CAT_IO = "IO"
CAT_ENV = "ENV"
CAT_NET = "NET"
CAT_EXEC = "EXEC"
CAT_LABEL = {
    CAT_IO: "文件IO",
    CAT_ENV: "环境变量",
    CAT_NET: "网络",
    CAT_EXEC: "执行命令",
}
CAT_MARK = {CAT_IO: "📂", CAT_ENV: "🌱", CAT_NET: "🌐", CAT_EXEC: "⚙️"}

# ── 监视表：哪些调用/导入算哪类副作用 ──────────────────────────────────
# 顶层裸名调用（func 是 Name，没有点号前缀）：open(...)/exec(...)/...
_NAME_CALLS = {
    "open": (CAT_IO, "open"),
    "input": (CAT_IO, "input"),          # 读 stdin 也是一次输入副作用
    "exec": (CAT_EXEC, "exec"),
    "eval": (CAT_EXEC, "eval"),
    "compile": (CAT_EXEC, "compile"),
    "__import__": (CAT_EXEC, "__import__"),
}

# 网络相关的顶层模块名：它们的导入、以及 `<root>.xxx(...)` 形态的调用都记作网络
_NET_ROOTS = {
    "socket", "ssl", "ftplib", "smtplib", "telnetlib", "poplib", "imaplib",
    "http", "urllib", "requests", "httpx", "aiohttp", "xmlrpc",
    "websocket", "websockets", "paramiko", "asyncore", "asynchat",
}

# 导入即记一笔的危险模块（光导入还没调用，但已经把危险能力请进了门）：
_RISKY_IMPORT_ROOTS = {
    "subprocess": (CAT_EXEC, "import:subprocess"),
    "multiprocessing": (CAT_EXEC, "import:multiprocessing"),
    "ctypes": (CAT_EXEC, "import:ctypes"),
    "pty": (CAT_EXEC, "import:pty"),
}

# os.<leaf>(...) 按 leaf 归类
_OS_EXEC_LEAVES = {"system", "popen", "fork", "forkpty", "kill", "abort", "plock"}
_OS_IO_LEAVES = {
    "remove", "unlink", "rename", "renames", "replace", "rmdir", "removedirs",
    "mkdir", "makedirs", "chmod", "chown", "truncate", "link", "symlink",
    "mkfifo", "write", "open", "ftruncate",
}
_OS_ENV_LEAVES = {"getenv", "putenv", "unsetenv", "setenv"}

# subprocess.<leaf>(...) 里这些算「起子进程/执行命令」
_SUBPROCESS_EXEC_LEAVES = {
    "run", "call", "check_call", "check_output", "Popen",
    "getoutput", "getstatusoutput",
}

# shutil.<leaf>(...) 里这些动文件系统
_SHUTIL_IO_LEAVES = {
    "copy", "copy2", "copyfile", "copytree", "copyfileobj", "move",
    "rmtree", "make_archive", "unpack_archive", "chown",
}

# tempfile.<leaf>(...) 里这些会真的建文件/目录
_TEMPFILE_IO_LEAVES = {
    "mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryFile",
}

# 不论挂在谁身上都几乎只可能是「写盘/删盘」的方法名（如 pathlib.Path 的方法）。
# 只收**罕见、不会与字符串等常见类型的方法重名**的：绝不收 replace/rename/write
# 这类（"x".replace、io 对象 .write 满地都是），免得把无害改动误判成新增 IO。
_FS_METHOD_LEAVES = {
    "write_text", "write_bytes", "unlink", "rmdir", "mkdir",
    "symlink_to", "hardlink_to", "touch",
}


@dataclasses.dataclass(frozen=True)
class TouchVerdict:
    """一次触觉裁决：候选有没有新增副作用，新增了哪些。"""
    ok: bool                       # True = 没摸到新增危险（或弃权）
    added: list[str]               # 新增的足迹码（"CAT:token"），按字典序
    abstained: bool                # True = 读不出（解析失败），弃权放行、交别的闸把关
    detail: str                    # 一句人话：摸到了什么 / 为什么放行
    before: dict[str, int]         # before 各足迹的出现次数（机读，账本可翻）
    after: dict[str, int]          # after 各足迹的出现次数

    def to_meta(self) -> dict:
        return {"ok": self.ok, "added": self.added, "abstained": self.abstained,
                "detail": self.detail, "before": self.before, "after": self.after}


def _name_root(node: ast.AST) -> str | None:
    """顺着 Attribute 链走到最底，取那个裸名（如 os.path.join → "os"）；走不到则 None。"""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _classify_call(func: ast.AST) -> tuple[str, str] | None:
    """把一个被调用的 func 节点归到某类副作用足迹，归不上回 None。"""
    # 裸名调用：open(...) / exec(...) / ...
    if isinstance(func, ast.Name):
        return _NAME_CALLS.get(func.id)

    if not isinstance(func, ast.Attribute):
        return None

    leaf = func.attr
    root = _name_root(func.value)

    # 顶层模块点名调用：os.* / subprocess.* / shutil.* / tempfile.* / 网络模块.*
    if root == "os":
        if leaf in _OS_EXEC_LEAVES or leaf.startswith("exec") or leaf.startswith("spawn"):
            return (CAT_EXEC, f"os.{leaf}")
        if leaf in _OS_IO_LEAVES:
            return (CAT_IO, f"os.{leaf}")
        if leaf in _OS_ENV_LEAVES:
            return (CAT_ENV, f"os.{leaf}")
    elif root == "subprocess" and leaf in _SUBPROCESS_EXEC_LEAVES:
        return (CAT_EXEC, f"subprocess.{leaf}")
    elif root == "pty" and leaf in {"spawn", "fork"}:
        return (CAT_EXEC, f"pty.{leaf}")
    elif root == "shutil" and leaf in _SHUTIL_IO_LEAVES:
        return (CAT_IO, f"shutil.{leaf}")
    elif root == "tempfile" and leaf in _TEMPFILE_IO_LEAVES:
        return (CAT_IO, f"tempfile.{leaf}")
    elif root in _NET_ROOTS:
        return (CAT_NET, f"{root}.{leaf}")

    # 不论挂谁身上都几乎只可能是写盘的方法名（pathlib.Path().write_text() 等）
    if leaf in _FS_METHOD_LEAVES:
        return (CAT_IO, f".{leaf}")
    return None


def risk_footprint(src: str) -> collections.Counter:
    """把一段源码里的副作用足迹按四类摸出来，回 Counter{"CAT:token": 次数}。

    纯 `ast.parse`，绝不执行源码。解析失败抛 SyntaxError（由 feel 兜成弃权）。
    """
    tree = ast.parse(src)
    fp: collections.Counter = collections.Counter()
    for node in ast.walk(tree):
        # 1) 调用：open()/os.system()/subprocess.run()/socket.socket()/...
        if isinstance(node, ast.Call):
            hit = _classify_call(node.func)
            if hit is not None:
                fp[f"{hit[0]}:{hit[1]}"] += 1
            continue
        # 2) 环境变量的属性访问：os.environ（读或写都算动了环境）
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            if _name_root(node.value) == "os":
                fp[f"{CAT_ENV}:os.environ"] += 1
            continue
        # 3) 导入危险模块：subprocess / 网络模块 / ctypes / pty…（导入即把能力请进门）
        if isinstance(node, ast.Import):
            for alias in node.names:
                _note_import(fp, alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            _note_import(fp, node.module)
    return fp


def _note_import(fp: collections.Counter, module: str) -> None:
    """一条 import 的模块名，若属危险模块则记一笔导入足迹。"""
    root = module.split(".")[0]
    if root in _RISKY_IMPORT_ROOTS:
        cat, token = _RISKY_IMPORT_ROOTS[root]
        fp[f"{cat}:{token}"] += 1
    elif root in _NET_ROOTS:
        fp[f"{CAT_NET}:import:{root}"] += 1


def _describe(added: list[str]) -> str:
    """把新增足迹码列成一句人话：按类归拢，点名具体调用。"""
    by_cat: dict[str, list[str]] = collections.defaultdict(list)
    for marker in added:
        cat, _, token = marker.partition(":")
        by_cat[cat].append(token)
    parts = []
    for cat in (CAT_IO, CAT_ENV, CAT_NET, CAT_EXEC):
        if cat in by_cat:
            parts.append(f"{CAT_MARK[cat]}{CAT_LABEL[cat]}（{ '、'.join(sorted(by_cat[cat])) }）")
    return "新增副作用：" + "；".join(parts)


def feel(before, after) -> TouchVerdict:
    """落笔前后比对副作用足迹：候选**新增**的危险即拒收，只拒新增、不算原有的账。

    before/after 都是源码字符串。按「同一足迹出现次数」做差，after 比 before 多出的那份
    就是这一爪新增的副作用。读不出（after 解析失败）→ 弃权放行（ok=True, abstained=True），
    交语法/契约等闸把关。永不抛错——触觉自己绝不能成为新伤口。
    """
    try:
        if not isinstance(after, str) or not isinstance(before, str):
            # 形状的活儿归 patchcontract；这里读不出就弃权，不越权拒收
            return TouchVerdict(True, [], True, "触觉弃权：原文或候选不是源码字符串，交别的闸把关",
                                {}, {})
        try:
            after_fp = risk_footprint(after)
        except SyntaxError as e:
            return TouchVerdict(True, [], True,
                                f"触觉弃权：候选解析不出（{e.__class__.__name__}），交语法闸把关",
                                {}, {})
        try:
            before_fp = risk_footprint(before)
        except SyntaxError:
            before_fp = collections.Counter()   # 原文都解析不出？保守按「原本无副作用」算，宁可多拒

        added = sorted(m for m, c in after_fp.items() if c > before_fp.get(m, 0))
        if not added:
            return TouchVerdict(True, [], False, "没摸到新增副作用 —— 这一爪没伸向身体之外",
                                dict(before_fp), dict(after_fp))
        return TouchVerdict(False, added, False, _describe(added),
                            dict(before_fp), dict(after_fp))
    except Exception as e:  # noqa: BLE001 —— 触觉绝不能崩；意外即弃权放行，不误杀也不反噬生命
        return TouchVerdict(True, [], True,
                            f"触觉弃权：比对时出意外（{type(e).__name__}: {e}），交别的闸把关",
                            {}, {})


def accepts(before, after) -> bool:
    """便捷断言：这一爪不新增副作用吗（供调用方一行判收/拒）。"""
    return feel(before, after).ok


def manifest() -> dict:
    """机读：四类足迹的监视清单（给 health / 外部消费）。"""
    return {
        "categories": {c: CAT_LABEL[c] for c in (CAT_IO, CAT_ENV, CAT_NET, CAT_EXEC)},
        "name_calls": {k: f"{v[0]}:{v[1]}" for k, v in _NAME_CALLS.items()},
        "net_roots": sorted(_NET_ROOTS),
        "risky_imports": sorted(_RISKY_IMPORT_ROOTS),
        "os_exec_leaves": sorted(_OS_EXEC_LEAVES),
        "os_io_leaves": sorted(_OS_IO_LEAVES),
        "os_env_leaves": sorted(_OS_ENV_LEAVES),
        "subprocess_exec_leaves": sorted(_SUBPROCESS_EXEC_LEAVES),
        "fs_method_leaves": sorted(_FS_METHOD_LEAVES),
        "policy": "只拒 after 比 before 新增的副作用；原文已有的不算；解析失败弃权放行",
    }


# ── 自检：四类新增各能摸出、原有副作用不误伤、解析失败弃权 ──────────────────
def _selfcheck(quiet: bool = False) -> bool:
    base = "def area(w, h):\n    return w * h\n"
    failures: list[str] = []

    def expect_reject(after, cat, label):
        v = feel(base, after)
        if v.ok:
            failures.append(f"新增{CAT_LABEL.get(cat, cat)}的候选「{label}」竟被放行，危险")
        elif not any(m.startswith(cat + ":") for m in v.added):
            failures.append(f"「{label}」该摸出 {cat} 新增，实得 {v.added}")

    def expect_accept(before, after, label):
        v = feel(before, after)
        if not v.ok:
            failures.append(f"无新增副作用的「{label}」竟被拒收：{v.detail}")

    # —— 四类新增各须摸出并拒收 ——
    expect_reject("import os\ndef area(w, h):\n    os.system('echo hi')\n    return w * h\n",
                  CAT_EXEC, "函数里偷起 os.system")
    expect_reject("import subprocess\ndef area(w, h):\n    subprocess.run(['ls'])\n    return w * h\n",
                  CAT_EXEC, "新增 subprocess.run")
    expect_reject("def area(w, h):\n    open('/tmp/x', 'w').write('!')\n    return w * h\n",
                  CAT_IO, "新增 open 写文件")
    expect_reject("import os\ndef area(w, h):\n    os.getenv('SECRET')\n    return w * h\n",
                  CAT_ENV, "新增读环境变量")
    expect_reject("import os\ndef area(w, h):\n    os.environ['X'] = '1'\n    return w * h\n",
                  CAT_ENV, "新增写 os.environ")
    expect_reject("import socket\ndef area(w, h):\n    socket.socket()\n    return w * h\n",
                  CAT_NET, "新增连网")
    expect_reject("import urllib.request\ndef area(w, h):\n    return w * h\n",
                  CAT_NET, "光导入网络模块也算新增能力")
    expect_reject("def area(w, h):\n    eval('w * h')\n    return w * h\n",
                  CAT_EXEC, "新增动态执行 eval")
    expect_reject("import pathlib\ndef area(w, h):\n    pathlib.Path('x').write_text('!')\n    return w * h\n",
                  CAT_IO, "新增 Path.write_text 写盘")

    # —— 无新增：放行 ——
    expect_accept(base, "def area(w, h):\n    return w * h  # 量过了\n", "只加行内注释")
    expect_accept(base, "def area(w, h):\n    return h * w\n", "只换运算次序")
    # 原文本就有副作用，候选挪个位置/加注释但副作用没变多 → 不算它的账，放行
    dirty = "import subprocess\ndef run():\n    return subprocess.run(['ls'])\n"
    expect_accept(dirty, "import subprocess\ndef run():\n    return subprocess.run(['ls'])  # 列目录\n",
                  "原有 subprocess 不变、只加注释")
    # 原文有一处 os.system，候选改了别处但 os.system 仍是一处 → 不新增，放行
    one_sys = "import os\ndef boot():\n    os.system('echo a')\n    return 1\n"
    expect_accept(one_sys, "import os\ndef boot():\n    os.system('echo a')\n    return 2\n",
                  "原有 os.system 数量不变")

    # —— 候选解析失败：弃权放行（交语法闸把关），且不抛错 ——
    v = feel(base, "def area(w, h)\n    return w * h\n")    # 漏冒号
    if not (v.ok and v.abstained):
        failures.append(f"候选解析失败时该弃权放行，实得 {v.to_meta()}")

    # —— 同类多处新增：原文一处 os.system、候选变两处 → 摸出新增 ——
    v2 = feel(one_sys, "import os\ndef boot():\n    os.system('echo a')\n    os.system('echo b')\n    return 1\n")
    if v2.ok or not any(m == f"{CAT_EXEC}:os.system" for m in v2.added):
        failures.append(f"同一危险调用从一处增到两处该摸出新增，实得 {v2.to_meta()}")

    # —— 非字符串输入：弃权、不抛错 ——
    if not feel(None, base).ok or not feel(base, 123).ok:
        failures.append("非字符串输入该弃权放行而非崩溃")

    ok = not failures
    if not quiet:
        if ok:
            print("✅ touch selfcheck：四类(IO/env/网络/执行命令)新增副作用各能摸出并拒收，"
                  "原有副作用不误伤，解析失败稳稳弃权——手长出触觉了。")
        else:
            print("❌ touch selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    base = "def area(w, h):\n    return w * h\n"
    print("👋🖐️  自生手触觉层 —— 落笔前后比对副作用，新增危险即拒收：\n")
    print(f"   原文：{base!r}\n")
    samples = [
        ("✅ 只加行内注释（不碰副作用）", "def area(w, h):\n    return w * h  # 量过了\n"),
        ("⚙️ 偷起 os.system", "import os\ndef area(w, h):\n    os.system('echo hi')\n    return w * h\n"),
        ("📂 偷写文件", "def area(w, h):\n    open('/tmp/x', 'w').write('!')\n    return w * h\n"),
        ("🌱 偷读环境变量", "import os\ndef area(w, h):\n    os.getenv('SECRET')\n    return w * h\n"),
        ("🌐 偷连网", "import socket\ndef area(w, h):\n    socket.socket()\n    return w * h\n"),
    ]
    for label, cand in samples:
        v = feel(base, cand)
        mark = "🟢 放行" if v.ok else f"🔴 拒收"
        print(f"  {label}\n      {mark} —— {v.detail}")
    print()


def _feel_from_stdin(path: str, *, quiet: bool) -> int:
    """从 stdin 读候选，对真仓库内 path 摸出新增副作用。退出码 0=无新增 1=有新增 2=路径越界。"""
    target = (REPO_ROOT / path).resolve()
    if not target.is_relative_to(REPO_ROOT):
        if not quiet:
            print(f"⛔ 拒绝：{path} 解析到仓库之外（{target}）")
        return 2
    before = target.read_text(encoding="utf-8") if target.exists() else ""
    after = sys.stdin.read()
    v = feel(before, after)
    if not quiet:
        mark = "🟢" if v.ok else "🔴"
        print(f"{mark} {target.name}：{v.detail}")
    return 0 if v.ok else 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手触觉层 👋🖐️")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检：四类新增各能摸出、原有副作用不误伤、解析失败弃权(供 evidence 复跑)")
    ap.add_argument("--json", action="store_true", help="机读：四类足迹的监视清单")
    ap.add_argument("--feel", metavar="PATH",
                    help="从 stdin 读候选源码，对真仓库内 PATH 摸出新增副作用")
    ap.add_argument("--quiet", action="store_true", help="静默，仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if _selfcheck(quiet=args.quiet) else 1)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if args.feel:
        sys.exit(_feel_from_stdin(args.feel, quiet=args.quiet))

    if not args.quiet:
        _demo()


if __name__ == "__main__":
    main()
