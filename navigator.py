#!/usr/bin/env python3
"""命令导航台 🧭🗺️ —— 把散落在领地里的几十个可执行入口，收拢成一张**今天还跑得通**的清单。

领地长到今天，根目录已经躺着四十多个 `*.py`：compass 指方向、smoke 验 README、
evidence 复验证据、planner 排机会……每一个都是一扇门，可门越多，**入口本身**就越成了
负担——一个想用我的人（哪怕是明天的我自己）站在门口，根本不知道：到底有哪些门？
每扇门收什么参数？随手敲一条试试，该敲哪条才安全？哪扇门其实早就锈死、推都推不开了？

能力多不等于好用。当入口分散到没人记得全，等于把「可用性」悄悄漏掉了。这台导航台
就来补这一环——它不新增能力，只做三件让既有能力**重新被找得到、敢去用**的事：

  · 📇 **列全入口**：扫一遍根目录里所有带 `__main__` 的模块，连同一句它在干嘛的自述，
    排成一张索引——再不必靠记忆或 `ls` 去猜。
  · 🧪 **给示例 + 验证命令**：从每个模块自己的「用法：」段里摘出作者写好的示例参数，
    并给一条**只读、零副作用**的验证命令（`python X.py --help`）——想试哪扇门，照着敲就行。
  · 🚑 **测活检失效**：真的去跑一遍每扇门的 `--help`，跑不通的（import 炸了、argparse 报错、
    超时）当场点名为「失效 CLI」——入口清单只有「今天真能跑」才有意义，否则又是一处会撒谎的文档。

导航台是**观测者**：只读地扫描与试推每扇门，绝不写 journal / state，也不改任何文件。
`--help` 没有副作用，故直接在领地里跑；退出码 0=所有入口健在 / 1=有失效 CLI 需修。

用法：
    python navigator.py             # 打印全仓入口清单 + 示例 + 验证命令，并测活
    python navigator.py --list      # 只列入口与一句自述（不测活，最快）
    python navigator.py --quiet     # 只在发现失效 CLI 时说话（适合接进 CI / 钩子）
    python navigator.py --grep 回归  # 只看名字/自述匹配关键词的入口
    python navigator.py --json      # 机读：导出每个入口的自述、示例、验证命令与存活状态

零第三方依赖，纯标准库。与 `compass.py`（指今天往哪走）互补：罗盘管「该做什么」，
导航台管「现成的门都在哪、还开着吗」。
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent

_PY = sys.executable

# 跑 --help 时的梦境环境：空 key=绝不真打大脑、空白名单=回到默认能力集，
# 让「这扇门开不开」只取决于代码本身，而非本机 .env。与 onboarding/smoke 同源。
_DREAM_ENV = {
    "OPENCRAB_API_KEY": "",
    "OPENCRAB_CAPABILITIES": "",
    "PYTHONIOENCODING": "utf-8",
}

# 导航台不把自己也列进去会显得心虚，但跑自己的 --help 没意义——保留列出、跳过测活即可。
# 这里只排除明显不是「面向人」的入口（目前没有，预留）。
_SKIP = set()

_HELP_TIMEOUT = 30  # 单扇门 --help 的超时；正常远小于此，超了多半是 import 期卡死

_STALE_DAYS = 30  # 本机 pyc 心跳超过这个天数，就当作「久未跑」入口提醒复验
_RECHECK_LIMIT = 8  # 最小复验队列只给最值得先敲的几扇门，避免又变成大清单
_HIGH_VALUE = {
    "crab", "navigator", "compass", "smoke", "checkup", "health", "audit",
    "evidence", "evidence_freshness", "planner", "triage", "releasegate",
    "rollback", "regression", "policy", "privacy", "secretscan", "supplychain",
}


@dataclasses.dataclass
class Entry:
    """一个可执行入口（领地根目录下带 __main__ 的模块）。"""
    name: str               # 模块名，如 "compass"
    path: str               # 相对路径，如 "compass.py"
    summary: str            # 一句自述（取自模块 docstring 首行）
    examples: list[str]     # 从「用法：」段摘出的示例命令
    verify: str             # 一条只读验证命令

    # 测活结果（未测时为 None）
    alive: bool | None = None
    detail: str = ""        # 失效时的关键错误行
    elapsed_s: float = 0.0

    # 新鲜度巡航：不写状态，只读 __pycache__ 心跳与源码时间来判断「有没有久未被本机跑过」
    last_seen_days: int | None = None
    freshness: str = "unknown"   # fresh / stale / never-seen
    high_value: bool = False
    recheck_reason: str = ""

    def to_meta(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "summary": self.summary,
            "examples": self.examples,
            "verify": self.verify,
            "alive": self.alive,
            "detail": self.detail if self.alive is False else "",
            "elapsed_s": round(self.elapsed_s, 2),
            "last_seen_days": self.last_seen_days,
            "freshness": self.freshness,
            "high_value": self.high_value,
            "recheck_reason": self.recheck_reason,
        }


def _has_main(tree: ast.Module) -> bool:
    """模块顶层是否有 `if __name__ == "__main__":` —— 判定它是不是一个可执行入口。"""
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name) and test.left.id == "__name__"
                and len(test.comparators) == 1):
            c = test.comparators[0]
            if isinstance(c, ast.Constant) and c.value == "__main__":
                return True
    return False


def _docstring_parts(doc: str) -> tuple[str, list[str]]:
    """从模块 docstring 里摘出 (一句自述, 示例命令列表)。

    自述 = 第一行去掉装饰性破折号后的核心句；示例 = 「用法：」段里所有含
    `python <mod>.py` 的行，原样保留作者写好的参数样例。
    """
    doc = (doc or "").strip()
    if not doc:
        return "", []
    lines = doc.splitlines()

    # 自述：首行，砍掉「—— ...」之前的标题装饰，留下「在干嘛」那半句
    first = lines[0].strip()
    if "——" in first:
        first = first.split("——", 1)[1].strip()
    summary = first.strip(" 。.")

    # 示例：定位「用法：/用法:」后的命令行
    examples: list[str] = []
    in_usage = False
    for ln in lines[1:]:
        s = ln.strip()
        if s.startswith("用法"):
            in_usage = True
            continue
        if in_usage:
            # 用法段以空行 + 非命令的整段说明结束；命令行都含 "python "
            if s.startswith("python "):
                # 砍掉行内 "# 注释"，只留可直接敲的命令
                cmd = s.split("#", 1)[0].strip()
                examples.append(cmd)
            elif s and not s.startswith("python ") and examples:
                # 已经收过命令、又遇到一段散文 → 用法段结束
                break
    return summary, examples


def _freshness_for(path: pathlib.Path) -> tuple[int | None, str]:
    """只读估算入口新鲜度：优先看 __pycache__ 心跳；没有 pyc 就标成 never-seen。

    这不是审计日志，不声称精确记录「最后一次人工执行」；它只回答一个更朴素的问题：
    本机最近有没有留下过 import/run 过这扇门的痕迹。导航台随后会真的跑 --help，因此这里
    必须在 probe 之前完成，避免被本次巡航刷新心跳。
    """
    cache_dir = path.with_name("__pycache__")
    pyc_times = [p.stat().st_mtime for p in cache_dir.glob(f"{path.stem}.*.pyc")] if cache_dir.exists() else []
    if not pyc_times:
        return None, "never-seen"
    days = int((time.time() - max(pyc_times)) // 86400)
    return days, ("stale" if days >= _STALE_DAYS else "fresh")


def _recheck_reason(name: str, freshness: str, high_value: bool) -> str:
    reasons: list[str] = []
    if high_value:
        reasons.append("高价值入口")
    if freshness == "never-seen":
        reasons.append("本机未见跑过")
    elif freshness == "stale":
        reasons.append(f"久未跑(≥{_STALE_DAYS}天)")
    return "；".join(reasons)


def discover() -> list[Entry]:
    """扫描根目录所有可执行入口，连同自述、示例、验证命令——但不测活。"""
    entries: list[Entry] = []
    for p in sorted(REPO_ROOT.glob("*.py")):
        stem = p.stem
        if stem.startswith("_") or stem in _SKIP:
            continue
        try:
            src = p.read_text("utf-8", errors="ignore")
            tree = ast.parse(src)
        except Exception:
            continue
        if not _has_main(tree):
            continue
        summary, examples = _docstring_parts(ast.get_docstring(tree) or "")
        last_seen_days, freshness = _freshness_for(p)
        high_value = stem in _HIGH_VALUE
        entries.append(Entry(
            name=stem,
            path=p.name,
            summary=summary or "（无自述）",
            examples=examples,
            verify=f"python {p.name} --help",
            last_seen_days=last_seen_days,
            freshness=freshness,
            high_value=high_value,
            recheck_reason=_recheck_reason(stem, freshness, high_value),
        ))
    return entries


def _probe(entry: Entry) -> None:
    """真去跑一遍 `python X.py --help`，就地记录存活状态与耗时。

    --help 是 argparse 的通用心跳：能跑通=模块至少 import 得动、CLI 装得起来；
    跑不通=import 期炸了 / argparse 配错 / 卡死，这扇门今天推不开。
    """
    t0 = time.monotonic()
    env = {**os.environ, **_DREAM_ENV}
    try:
        proc = subprocess.run(
            [_PY, entry.path, "--help"], cwd=str(REPO_ROOT), env=env,
            capture_output=True, text=True, timeout=_HELP_TIMEOUT)
        entry.elapsed_s = time.monotonic() - t0
        if proc.returncode == 0:
            entry.alive = True
        else:
            entry.alive = False
            err = (proc.stderr or proc.stdout).strip()
            tail = err.splitlines()[-1][:160] if err else "(无输出)"
            entry.detail = f"退出码 {proc.returncode}：{tail}"
    except subprocess.TimeoutExpired:
        entry.elapsed_s = time.monotonic() - t0
        entry.alive = False
        entry.detail = f"超时 >{_HELP_TIMEOUT}s（疑似 import 期卡死）"
    except Exception as e:
        entry.elapsed_s = time.monotonic() - t0
        entry.alive = False
        entry.detail = f"<执行异常> {e!r}"


def survey(grep: str | None = None, probe: bool = True) -> list[Entry]:
    """产出一份导航清单；probe=True 时逐个测活。grep 按名字/自述过滤。"""
    entries = discover()
    if grep:
        low = grep.lower()
        entries = [e for e in entries
                   if low in e.name.lower() or low in e.summary.lower()]
    if probe:
        for e in entries:
            _probe(e)
    return entries


def manifest(grep: str | None = None) -> dict:
    """机读：全清单 + 测活结论 + 失效汇总。"""
    entries = survey(grep=grep, probe=True)
    dead = [e for e in entries if e.alive is False]
    return {
        "total": len(entries),
        "alive": sum(1 for e in entries if e.alive),
        "dead": len(dead),
        "dead_names": [e.name for e in dead],
        "stale_or_never_seen": [e.name for e in entries if e.freshness in {"stale", "never-seen"}],
        "high_value": [e.name for e in entries if e.high_value],
        "recheck_queue": [e.to_meta() for e in _recheck_queue(entries)],
        "entries": [e.to_meta() for e in entries],
    }


def _recheck_queue(entries: list[Entry]) -> list[Entry]:
    """最小复验队列：失效优先，其次高价值且不新鲜，再其次普通不新鲜。"""
    def score(e: Entry) -> tuple[int, int, int, str]:
        dead = 0 if e.alive is False else 1
        valuable = 0 if e.high_value else 1
        stale_rank = 0 if e.freshness == "never-seen" else (1 if e.freshness == "stale" else 2)
        return (dead, valuable, stale_rank, e.name)

    needs = [
        e for e in entries
        if e.alive is False or e.freshness in {"stale", "never-seen"} or e.high_value
    ]
    return sorted(needs, key=score)[:_RECHECK_LIMIT]


def _freshness_badge(e: Entry) -> str:
    bits: list[str] = []
    if e.high_value:
        bits.append("⭐高价值")
    if e.freshness == "never-seen":
        bits.append("🕳️未见跑过")
    elif e.freshness == "stale":
        bits.append(f"⏳久未跑 {e.last_seen_days}天")
    return " ".join(bits)


def _render(entries: list[Entry], probed: bool) -> str:
    L = ["🦀🗺️  opencrab 命令导航台 —— 全仓可执行入口清单", ""]
    dead = [e for e in entries if e.alive is False]
    for e in entries:
        if not probed:
            mark = "•"
        else:
            mark = "✅" if e.alive else "❌"
        badge = _freshness_badge(e)
        suffix = f"  [{badge}]" if badge else ""
        L.append(f"{mark} {e.name}.py — {e.summary}{suffix}")
        if e.examples:
            for ex in e.examples:
                L.append(f"     ↳ {ex}")
        L.append(f"     验证：{e.verify}")
        if e.alive is False:
            L.append(f"     ⚠️  失效：{e.detail}")
        L.append("")
    if probed:
        if dead:
            names = "、".join(e.name for e in dead)
            L.append(f"⚠️  {len(entries)} 个入口里有 {len(dead)} 个推不开：{names}——先修好这几扇门。")
        else:
            L.append(f"🦀 {len(entries)} 个入口全部健在，门门推得开。")
    else:
        L.append(f"📇 共 {len(entries)} 个入口（未测活；去掉 --list 可逐个验证存活）。")

    queue = _recheck_queue(entries)
    if queue:
        L.append("")
        L.append(f"🧭 最小复验队列（先敲这 {len(queue)} 扇门，校正旧地图）：")
        for e in queue:
            reason = e.recheck_reason or ("失效入口" if e.alive is False else "抽样复验")
            if e.alive is False and "失效入口" not in reason:
                reason = "失效入口；" + reason
            L.append(f"   - {e.verify}  # {reason}")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 命令导航台 🗺️ —— 收拢全仓可执行入口，给示例与验证命令，并检测失效 CLI")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true",
                   help="只列入口与一句自述（不测活，最快）")
    g.add_argument("--quiet", action="store_true",
                   help="只在发现失效 CLI 时说话（适合接进 CI / 钩子）")
    g.add_argument("--json", action="store_true",
                   help="机读：导出每个入口的自述、示例、验证命令与存活状态")
    ap.add_argument("--grep", metavar="KW",
                    help="只看名字/自述匹配关键词的入口")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(grep=args.grep), ensure_ascii=False, indent=2))
        sys.exit(0)

    if args.list:
        entries = survey(grep=args.grep, probe=False)
        print(_render(entries, probed=False))
        sys.exit(0)

    entries = survey(grep=args.grep, probe=True)
    dead = [e for e in entries if e.alive is False]

    if args.quiet:
        if dead:
            names = "、".join(e.name for e in dead)
            print(f"🗺️  命令导航台：{len(dead)}/{len(entries)} 个入口推不开 —— {names}")
            for e in dead:
                print(f"   ❌ {e.name}.py：{e.detail}")
    else:
        print(_render(entries, probed=True))

    sys.exit(1 if dead else 0)


if __name__ == "__main__":
    main()
