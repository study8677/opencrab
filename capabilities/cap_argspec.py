"""能力 · 参数自省与帮助生成 🔎 —— 把 argparse 命令树拆到「每一个参数」。

helpdex / catalog 已经把领地的能力串成目录，但它们只认得**子命令的名字**：
`catalog` 列出 `python crab.py replay`，却说不清 `replay` 收哪些参数、类型是
什么、有没有默认值、哪些是必填。这一层「参数级自省」正补这个洞。

它直接自省 `crab.build_parser()` 的真实解析器(单一真相源)，递归走遍：
  1. 顶层入口的旗标(含被 SUPPRESS 藏起来的向后兼容旗标，自省照样看得见)。
  2. 每个子命令，以及它的**每一个**参数——位置/可选、metavar、类型、默认值、
     choices、是否必填、help 说明。
  3. 由参数元数据**合成**最小可用的用法示例(只填必填项)，让人照抄就能跑。

产出三块：参数总表(给人查) + 合成用法示例(给人抄) + 机器可读的参数清单
(放在 Result.data，给测试覆盖、能力发现、外部工具消费)。

默认把渲染结果写到仓库根的 `ARGSPEC.md`(自动生成、可重跑覆盖)；
传 ctx={"write": False} 则只渲染不落盘。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import pathlib

from . import Result, capability

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT = _REPO_ROOT / "ARGSPEC.md"


def _type_name(action: argparse.Action) -> str:
    """这个参数吃什么类型；store_true/store_false 是开关，没有取值类型。"""
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        return "开关"
    t = getattr(action, "type", None)
    if t is None:
        return "字符串"
    return getattr(t, "__name__", str(t))


def _describe_arg(action: argparse.Action) -> dict:
    """把一个 argparse action 抽成纯数据的参数元信息。"""
    opts = list(action.option_strings)
    positional = not opts
    hidden = action.help == argparse.SUPPRESS
    default = action.default
    return {
        "name": action.dest if positional else opts[0],
        "flags": opts,                       # 可选参数的所有写法(如 ["--limit"])
        "positional": positional,
        "metavar": action.metavar or (action.dest.upper() if positional else None),
        "type": _type_name(action),
        "required": bool(getattr(action, "required", False)) or positional,
        "default": None if default in (None, argparse.SUPPRESS, False) else default,
        "choices": list(action.choices) if action.choices else None,
        "help": "" if hidden else (action.help or ""),
        "hidden": hidden,
    }


def _args_of(parser: argparse.ArgumentParser) -> list[dict]:
    """一个解析器的所有参数(剔除 -h/--help 与子命令容器本身)。"""
    out: list[dict] = []
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            continue
        out.append(_describe_arg(action))
    return out


def _subcommands(parser: argparse.ArgumentParser) -> list[dict]:
    """自省子命令树：每个子命令的名字、help 与它自己的全部参数。"""
    subs: list[dict] = []
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        helps = {a.dest: (a.help or "") for a in action._choices_actions}
        for name, subparser in action.choices.items():
            subs.append({
                "name": name,
                "help": helps.get(name, ""),
                "args": _args_of(subparser),
            })
    return subs


def _example(cmd: str | None, args: list[dict]) -> str:
    """由参数元数据合成一条「只填必填项」的最小可用命令。"""
    parts = ["python crab.py"]
    if cmd:
        parts.append(cmd)
    for a in args:
        if a["hidden"] or not a["required"]:
            continue
        if a["positional"]:
            # 有 choices 就拿第一个当样例，否则用 metavar 占位
            parts.append(str(a["choices"][0]) if a["choices"] else f"<{a['metavar']}>")
        else:
            val = "" if a["type"] == "开关" else f" <{a['metavar'] or a['name'].lstrip('-').upper()}>"
            parts.append(f"{a['flags'][0]}{val}")
    return " ".join(parts)


def introspect() -> dict:
    """自省 crab.py 的解析器，得到完整的参数树(纯数据，单一真相源)。"""
    import sys
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import crab
    parser = crab.build_parser()
    return {
        "prog": parser.prog,
        "description": parser.description or "",
        "global_args": _args_of(parser),
        "subcommands": _subcommands(parser),
    }


def _fmt_arg_row(a: dict) -> str:
    """参数总表的一行(markdown 表格)。"""
    name = "、".join(f"`{f}`" for f in a["flags"]) if a["flags"] else f"`{a['name']}`"
    req = "✅" if a["required"] else ""
    choices = "、".join(f"`{c}`" for c in a["choices"]) if a["choices"] else ""
    default = f"`{a['default']}`" if a["default"] is not None else ""
    help_text = a["help"].replace("|", "\\|")
    return (f"| {name} | {a['type']} | {req} | {default} | {choices} "
            f"| {help_text} |")


def _arg_table(args: list[dict]) -> list[str]:
    visible = [a for a in args if not a["hidden"]]
    if not visible:
        return ["（无参数）", ""]
    L = ["| 参数 | 类型 | 必填 | 默认 | 可选值 | 说明 |",
         "|---|---|---|---|---|---|"]
    L += [_fmt_arg_row(a) for a in visible]
    L.append("")
    return L


def _render(spec: dict) -> str:
    L: list[str] = []
    L.append("# 🦀 opencrab 参数自省")
    L.append("")
    L.append("> 自动生成，请勿手改——重跑 `python crab.py cap argspec` 即可刷新。")
    L.append("> 直接自省 `crab.build_parser()`，把命令树拆到每一个参数：总表 + 合成用法示例。")
    L.append("")

    # 顶层旗标
    L.append(f"## 顶层入口 `{spec['prog']}`")
    L.append("")
    if spec["description"]:
        L.append(f"> {spec['description']}")
        L.append("")
    n_hidden = sum(1 for a in spec["global_args"] if a["hidden"])
    L += _arg_table(spec["global_args"])
    if n_hidden:
        L.append(f"_（另有 {n_hidden} 个向后兼容的隐藏旗标，自省可见但不在表中）_")
        L.append("")

    # 各子命令
    L.append("## 子命令")
    L.append("")
    for sub in spec["subcommands"]:
        L.append(f"### `{sub['name']}` — {sub['help']}")
        L.append("")
        L += _arg_table(sub["args"])
        L.append("**用法示例：**")
        L.append("")
        L.append("```bash")
        L.append(_example(sub["name"], sub["args"]))
        L.append("```")
        L.append("")

    return "\n".join(L).rstrip() + "\n"


def _count_args(spec: dict) -> tuple[int, int]:
    """(可见参数数, 隐藏参数数)，统计含顶层与所有子命令。"""
    visible = sum(1 for a in spec["global_args"] if not a["hidden"])
    hidden = sum(1 for a in spec["global_args"] if a["hidden"])
    for sub in spec["subcommands"]:
        visible += sum(1 for a in sub["args"] if not a["hidden"])
        hidden += sum(1 for a in sub["args"] if a["hidden"])
    return visible, hidden


@capability("argspec", "参数自省与帮助生成：自省 argparse 命令树，逐参数列出类型/默认/必填+合成用法示例",
            category="自述", tags=("docs", "discovery", "help", "introspect"))
def run(ctx: dict) -> Result:
    try:
        spec = introspect()
    except Exception as e:
        return Result(ok=False, summary=f"自省命令树失败：{e}")

    doc = _render(spec)
    visible, hidden = _count_args(spec)
    n_subs = len(spec["subcommands"])

    write = (ctx or {}).get("write", True)
    written = None
    if write:
        try:
            _OUT.write_text(doc, "utf-8")
            written = _OUT.relative_to(_REPO_ROOT).as_posix()
        except Exception as e:
            return Result(ok=False, summary=f"参数表已生成但落盘失败：{e}", detail=doc)

    summary = (f"自省 {n_subs} 个子命令 · {visible} 个可见参数（另 {hidden} 个隐藏）"
               + (f" → 已写入 {written}" if written else "（未落盘）"))
    return Result(ok=True, summary=summary, detail=doc,
                  data={"subcommands": n_subs, "visible_args": visible,
                        "hidden_args": hidden, "written": written, "spec": spec})
