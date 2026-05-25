"""能力 · 变更影响范围探测 🎯 —— 进化前先算清「该改哪里、先验哪些」。

每次自我进化总怕漏改、怕连锁回归：动了一个模块，谁还在 import 它？哪些文档
点了它的名？哪条运行路径会被波及？哪套自检/回归该先跑？这条能力就把这些
一次性铺开，给出一份「影响清单 + 验证顺序」，让改动更稳、回归更少。

它做三件事：
  1. 找出本次「变更文件」  —— 默认问 git：相对某个基线(默认 `main`)的差异 +
     工作区未提交的脏改动；也可传 ctx={"files": [...]} 直接给定。
  2. 顺着依赖摸出受影响面 —— 用 ast 建一张「谁 import 谁」的反向依赖图，
     算出每个变更 .py 的下游依赖者；再扫文档(*.md)里点名了它的地方；
     若动的是 `cap_*.py` 还会标出对应的 `crab.py cap <NAME>` 运行路径。
  3. 排出「先验哪些」清单   —— 按影响把自检/回归/烟雾/受影响能力排成有序的
     验证步骤(checkup → smoke → goldens → 受影响能力)，照着跑即可。

默认把清单写到 state/impact/<时间>.md(落在被 .gitignore 的 state/ 里，
自动生成、可重跑覆盖)；传 ctx={"write": False} 则只渲染不落盘。
ctx 选项：{"base": "main"(对比基线), "files": [...](直接给定变更文件),
"write": bool}。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import ast
import datetime
import pathlib
import subprocess

from . import Result, capability, get as _get_cap

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT_DIR = _REPO_ROOT / "state" / "impact"     # 落在被 .gitignore 的 state/ 里

# 验证入口：领地里「证明自己还能活」的命令，按从快到慢排。
_VERIFY = [
    ("python checkup.py --quiet", "领地自检：关键文件/可编译/可导入/结构完整"),
    ("python smoke.py", "最小烟雾测试：README 关键用法还能跑"),
    ("python regression.py snapshot", "回归样本：关键命令输出/退出码未漂移"),
]


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(["git", "-C", str(_REPO_ROOT), *args],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return ""


def _py_files() -> list[pathlib.Path]:
    """领地里所有受版本管理的 .py(排除 state/ 与 .git/)。"""
    out: list[pathlib.Path] = []
    for p in _REPO_ROOT.rglob("*.py"):
        rel = p.relative_to(_REPO_ROOT).as_posix()
        if rel.startswith(("state/", ".git/")):
            continue
        out.append(p)
    return sorted(out)


def _imports(src: str) -> set[str]:
    """一个源文件 import 进来的所有顶层/点分模块名(尽力而为,坏语法返回空集)。"""
    mods: set[str] = set()
    try:
        tree = ast.parse(src)
    except Exception:
        return mods
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # `from . import x` 的 module 为 None；带名字的才好定位
                mods.add(node.module)
    return mods


def _module_keys(rel: str) -> set[str]:
    """一个文件路径可能被 import 的模块名形态(用来在他人 import 集合里匹配)。"""
    parts = rel[:-3].split("/")          # 去掉 .py
    keys = {parts[-1]}                    # 裸 stem，如 `audit`
    keys.add(".".join(parts))            # 包路径，如 `capabilities.cap_impact`
    return keys


def _changed_files(ctx: dict) -> tuple[list[str], str]:
    """求出本次变更文件(相对仓库根的 posix 路径,去重保序),并附一句来源说明。"""
    given = ctx.get("files")
    if given:
        files = [str(f).replace("\\", "/") for f in given]
        return _dedup_existing(files), "由 ctx.files 直接给定"

    base = ctx.get("base", "main")
    changed: list[str] = []
    # 1) 相对基线的差异(若基线存在)
    if _git(["rev-parse", "--verify", "--quiet", base]):
        diff = _git(["diff", "--name-only", f"{base}...HEAD"])
        changed += [ln.strip() for ln in diff.splitlines() if ln.strip()]
        src = f"git diff {base}...HEAD"
    else:
        src = f"(基线 {base!r} 不存在,只看工作区)"
    # 2) 工作区未提交的脏改动(porcelain 的第 4 列起是路径)
    porcelain = _git(["status", "--porcelain"])
    for ln in porcelain.splitlines():
        if ln.strip():
            changed.append(ln[3:].strip())
    return _dedup_existing(changed), src


def _dedup_existing(files: list[str]) -> list[str]:
    """去重保序,只保留仍存在于工作区的文件。"""
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        if f and f not in seen and (_REPO_ROOT / f).exists():
            seen.add(f)
            out.append(f)
    return out


def _build_rdeps() -> dict[str, list[str]]:
    """反向依赖图：模块文件 -> 「import 了它的文件」列表(均为 posix 相对路径)。"""
    files = _py_files()
    # 先把每个文件 import 了哪些模块名抓出来
    imports_of: dict[str, set[str]] = {}
    for p in files:
        rel = p.relative_to(_REPO_ROOT).as_posix()
        imports_of[rel] = _imports(p.read_text("utf-8", errors="ignore"))
    # 再为每个文件，找出谁 import 了它
    rdeps: dict[str, list[str]] = {}
    for p in files:
        rel = p.relative_to(_REPO_ROOT).as_posix()
        keys = _module_keys(rel)
        dependents = sorted(
            other for other, mods in imports_of.items()
            if other != rel and (mods & keys or any(
                m.endswith("." + k) for m in mods for k in keys))
        )
        rdeps[rel] = dependents
    return rdeps


def _doc_mentions(filename: str) -> list[str]:
    """哪些文档(*.md)点名了这个文件——文档可能要跟着同步更新。"""
    hits: list[str] = []
    for p in sorted(_REPO_ROOT.rglob("*.md")):
        rel = p.relative_to(_REPO_ROOT).as_posix()
        if rel.startswith(("state/", ".git/")):
            continue
        try:
            if filename in p.read_text("utf-8", errors="ignore"):
                hits.append(rel)
        except Exception:
            continue
    return hits


def _cap_name(rel: str) -> str | None:
    """若是 capabilities/cap_X.py，返回它登记的能力名(优先用注册表,失败回退到 X)。"""
    name = pathlib.Path(rel).name
    if not (rel.startswith("capabilities/") and name.startswith("cap_")):
        return None
    stem = name[len("cap_"):-len(".py")]
    # 注册表里能力名通常等于 stem(如 cap_impact -> impact)，校验一下
    return stem if _get_cap(stem) else stem


def analyze(ctx: dict) -> dict:
    """把「变更 -> 受影响面 -> 该验什么」算成一份纯数据的影响报告。"""
    files, src = _changed_files(ctx)
    rdeps = _build_rdeps()

    per_file: list[dict] = []
    all_deps: set[str] = set()
    affected_caps: set[str] = set()
    for f in files:
        is_py = f.endswith(".py")
        deps = rdeps.get(f, []) if is_py else []
        docs = _doc_mentions(pathlib.Path(f).name)
        cap = _cap_name(f)
        if cap:
            affected_caps.add(cap)
        all_deps.update(deps)
        per_file.append({
            "file": f, "is_py": is_py, "dependents": deps,
            "docs": docs, "cap": cap,
        })

    # 排「先验哪些」：标准自检/回归三连 + 每个受影响能力单独跑一遍
    verify = list(_VERIFY)
    for cap in sorted(affected_caps):
        verify.append((f"python crab.py cap {cap}",
                       f"单跑受影响能力 `{cap}`，确认它本身没坏"))

    return {
        "source": src,
        "changed": files,
        "per_file": per_file,
        "dependents": sorted(all_deps),
        "affected_caps": sorted(affected_caps),
        "verify": verify,
    }


def _render(a: dict) -> str:
    """把影响报告渲染成一份「该改哪里、先验哪些」清单(markdown)。"""
    L: list[str] = []
    L.append("# 🦀🎯 opencrab 变更影响范围")
    L.append("")
    L.append("> 自动生成,请勿手改——重跑 `python crab.py cap impact` 即可刷新。")
    L.append(f"> 变更来源：{a['source']}。进化前照此清单逐项落实，少漏改、少回归。")
    L.append("")

    if not a["changed"]:
        L.append("（没有探测到变更文件——工作区干净，或基线选错了。）")
        L.append("")
        return "\n".join(L).rstrip() + "\n"

    L.append(f"**概览**：{len(a['changed'])} 个变更文件 · "
             f"{len(a['dependents'])} 个下游依赖者 · "
             f"{len(a['affected_caps'])} 个受影响能力")
    L.append("")

    # 1) 该改哪里
    L.append("## 📝 该改哪里")
    L.append("")
    for item in a["per_file"]:
        head = f"### `{item['file']}`"
        if item["cap"]:
            head += f" · 能力 `{item['cap']}`"
        L.append(head)
        L.append("")
        if item["is_py"]:
            if item["dependents"]:
                L.append("- ⛓️ 下游依赖者(改了接口要一并检查)：")
                L.extend(f"  - `{d}`" for d in item["dependents"])
            else:
                L.append("- ⛓️ 下游依赖者：无(暂没有别的模块 import 它)")
        if item["docs"]:
            L.append("- 📄 点名它的文档(可能要同步更新)：")
            L.extend(f"  - `{d}`" for d in item["docs"])
        else:
            L.append("- 📄 点名它的文档：无")
        L.append("")

    # 2) 先验哪些
    L.append("## ✅ 先验哪些（按顺序）")
    L.append("")
    L.append("```bash")
    for cmd, _why in a["verify"]:
        L.append(cmd)
    L.append("```")
    L.append("")
    L.append("| 步骤 | 验什么 |")
    L.append("|---|---|")
    for cmd, why in a["verify"]:
        L.append(f"| `{cmd}` | {why} |")
    L.append("")
    return "\n".join(L).rstrip() + "\n"


@capability("impact", "变更影响范围探测：找出受影响的脚本/依赖/文档/能力,给出「该改哪里、先验哪些」清单",
            category="感知", tags=("impact", "deps", "git", "checklist"))
def run(ctx: dict) -> Result:
    ctx = ctx or {}
    a = analyze(ctx)
    report = _render(a)

    written = None
    if ctx.get("write", True):
        try:
            _OUT_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
            out = _OUT_DIR / f"{stamp}.md"
            out.write_text(report, "utf-8")
            written = out.relative_to(_REPO_ROOT).as_posix()
        except Exception as e:
            return Result(ok=False, summary=f"清单已生成但落盘失败：{e}", detail=report)

    if not a["changed"]:
        return Result(ok=True, summary=f"没探测到变更文件（来源：{a['source']}）。",
                      detail=report, data=a)

    summary = (f"{len(a['changed'])} 个变更 · {len(a['dependents'])} 个下游依赖者 · "
               f"{len(a['affected_caps'])} 个受影响能力 · {len(a['verify'])} 步验证"
               + (f" → 已写入 {written}" if written else "（未落盘）"))
    return Result(ok=True, summary=summary, detail=report, data=a)
