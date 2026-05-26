#!/usr/bin/env python3
"""交接包 📦 —— 把半完成的任务封成「换个人/换个时刻也能无损续跑」的一只箱子。

自治最怕的不是失败,而是**被打断**:上下文一塌,下一程(可能是另一个我,也可能是
几小时后忘了细节的我)只能从代码与零碎日志里考古,把刚走通的判断重走一遍——重复的
不是工作,是**犹豫**。交接包补的就是这一环:在还没忘之前,把「现在到哪了、接下来该
干嘛、哪里有雷、怎么验证接对了」一次性钉死,让续跑的人**省掉重新理解的成本**。

一只合格的交接包装四样东西,缺一不可:
  · 状态(done)   —— 已经走通、不必重来的部分。让续跑者知道「这些可以信」。
  · 下一步(next) —— 有序的待办,第一条就是「拿起来先干这个」。
  · 风险(risk)   —— 已知的雷与悬而未决的判断。最贵的知识就是「我差点踩的坑」。
  · 验证(verify) —— 一串命令,跑通即证明「我接对了、没把半成品当成品」。

外加一张**自动抓取的 git 现场快照**(只读):当前分支、HEAD、是否有未提交改动、
落后/领先远端多少。续跑者照着快照就能确认「我站在交接者离开时的同一块地上」。

判准:交接包只描述、不执行,也不替你动手——它是一张**移交清单**,不是机器人。唯一
会真的跑外部命令的是 `--run`(执行 verify 命令验证续跑状态),且必须显式开启;没有它,
本模块全程只读环境、只追加自己的账本与导出的 .md 包,绝不反噬生命。

用法:
    # 封一只交接包(列表项可多次给,顺序即记录顺序):
    python handoff.py --title "接入 boundaryeval 回归抽测" \\
        --why "自治会被打断,半成品得能续跑" \\
        --done "用例库已铸好" --done "CLI --list 跑通" \\
        --next "把抽测接进 regression.py" --next "补 --json 输出" \\
        --risk "抽测可能与现有 seed 冲突" \\
        --verify "python boundaryeval.py --list" \\
        --verify "python -c 'import boundaryeval'"
    python handoff.py --title "..." --dry       # 只看不存(连同 git 快照预览)
    python handoff.py --list                     # 列出还开着的交接包
    python handoff.py --show <id>                # 渲染某只包的完整续跑简报
    python handoff.py --resume <id>              # 同 --show,但标记为「已被取用」
    python handoff.py --run <id>                 # 真的跑该包的 verify 命令,报通过/失败
    python handoff.py --close <id>               # 标记任务已续完,合箱
    python handoff.py --json --list              # 机读

零第三方依赖,纯标准库。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import append_jsonl, read_jsonl  # noqa: E402

HANDOFF_LOG = REPO_ROOT / "state" / "handoff.jsonl"
PACKAGE_DIR = REPO_ROOT / "state" / "handoffs"

# 交接包的状态机:开着 → 被取用 → 续完。只能往前走,不回头。
STATUS_OPEN = "open"        # 刚封好,等人来接
STATUS_RESUMED = "resumed"  # 已被某次续跑取用(--resume)
STATUS_DONE = "done"        # 任务续完,合箱(--close)
_STATUS_ICON = {STATUS_OPEN: "📦", STATUS_RESUMED: "🚚", STATUS_DONE: "✅"}


# ── git 现场快照:只读,绝不改动工作区 ────────────────────────────────────
def _git(*args: str, timeout: float = 5.0) -> str | None:
    """跑一条只读 git 命令,回 stdout(strip 后);任何失败都回 None,绝不抛。"""
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True,
            text=True, timeout=timeout,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def git_snapshot() -> dict:
    """抓一张当前 git 现场:分支 / HEAD / 脏不脏 / 落后领先远端多少。全程只读。

    续跑者拿这张快照,就能确认自己站在交接者离开时的同一块地上。任何一项取不到
    都老实记 None / 0,绝不编。
    """
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    head = _git("rev-parse", "--short", "HEAD")
    subject = _git("log", "-1", "--pretty=%s")
    porcelain = _git("status", "--porcelain")
    dirty = [ln for ln in (porcelain or "").splitlines() if ln.strip()]
    untracked = [ln for ln in dirty if ln.startswith("??")]
    # 落后/领先上游:没配上游就回 None,不报错。
    ahead = behind = None
    counts = _git("rev-list", "--left-right", "--count", "@{upstream}...HEAD")
    if counts:
        parts = counts.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            behind, ahead = int(parts[0]), int(parts[1])
    return {
        "branch": branch,
        "head": head,
        "head_subject": subject,
        "dirty_count": len(dirty),
        "untracked_count": len(untracked),
        "dirty_files": [ln[3:] for ln in dirty][:20],  # 只留前 20 条,够定位即可
        "ahead": ahead,
        "behind": behind,
    }


# ── 封包 ─────────────────────────────────────────────────────────────────
def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def build(title: str, why: str, done: list[str], nexts: list[str],
          risks: list[str], verify: list[str]) -> dict:
    """把四样东西 + git 快照组装成一只交接包(还没落盘)。"""
    return {
        "kind": "handoff",
        "id": _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
        "ts": _now(),
        "status": STATUS_OPEN,
        "title": title.strip(),
        "why": (why or "").strip(),
        "done": [s.strip() for s in done if s.strip()],
        "next": [s.strip() for s in nexts if s.strip()],
        "risk": [s.strip() for s in risks if s.strip()],
        "verify": [s.strip() for s in verify if s.strip()],
        "snapshot": git_snapshot(),
    }


def gaps(pkg: dict) -> list[str]:
    """挑出这只包**缺斤少两**的地方——交接最忌讳「半张清单」,宁可当场喊出来。"""
    out = []
    if not pkg.get("next"):
        out.append("没有「下一步」:续跑者拿起来不知道先干什么。")
    if not pkg.get("verify"):
        out.append("没有「验证命令」:续跑者无法证明自己接对了。")
    if not pkg.get("done"):
        out.append("没有「已完成状态」:续跑者分不清哪些可信、哪些得重来。")
    if not pkg.get("why"):
        out.append("没写「为什么」:续跑者只知道做什么,不知道为何而做,容易跑偏。")
    return out


def save(pkg: dict) -> pathlib.Path:
    """落账本(JSONL)并导出一只自包含的 .md 包,回 .md 路径。"""
    append_jsonl(HANDOFF_LOG, pkg)
    path = PACKAGE_DIR / f"HANDOFF-{pkg['id']}.md"
    try:
        PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(pkg), encoding="utf-8")
    except Exception:
        pass  # 导出失败不反噬:账本已落,.md 只是副本
    return path


# ── 读账本 ───────────────────────────────────────────────────────────────
def _all() -> list[dict]:
    return [r for r in read_jsonl(HANDOFF_LOG) if r.get("kind") == "handoff"]


def _latest_by_id() -> dict[str, dict]:
    """同一 id 可能被多次追加(状态流转),取每个 id 的**最后一条**为准。"""
    out: dict[str, dict] = {}
    for r in _all():
        if r.get("id"):
            out[r["id"]] = r
    return out


def find(pkg_id: str) -> dict | None:
    """按 id 取最新状态的包;支持前缀匹配(给全 id 太累)。"""
    latest = _latest_by_id()
    if pkg_id in latest:
        return latest[pkg_id]
    hits = [v for k, v in latest.items() if k.startswith(pkg_id)]
    return hits[0] if len(hits) == 1 else None


def open_packages() -> list[dict]:
    return [p for p in _latest_by_id().values() if p.get("status") == STATUS_OPEN]


def set_status(pkg: dict, status: str) -> dict:
    """流转状态:追加一条新记录(账本只增不改),回新记录。"""
    nxt = dict(pkg)
    nxt["status"] = status
    nxt["ts"] = _now()
    append_jsonl(HANDOFF_LOG, nxt)
    return nxt


# ── 跑验证命令(唯一会动外部的入口,须显式 --run) ────────────────────────
def run_verify(pkg: dict, timeout: float = 120.0) -> list[dict]:
    """逐条跑 verify 命令,回每条的 {cmd, ok, code}。逐条带超时,绝不卡死。"""
    results = []
    for cmd in pkg.get("verify", []):
        try:
            out = subprocess.run(cmd, cwd=REPO_ROOT, shell=True,
                                  capture_output=True, text=True, timeout=timeout)
            ok, code = out.returncode == 0, out.returncode
        except subprocess.TimeoutExpired:
            ok, code = False, "timeout"
        except Exception as e:  # noqa: BLE001
            ok, code = False, f"err:{e}"
        results.append({"cmd": cmd, "ok": ok, "code": code})
    return results


# ── 渲染 ─────────────────────────────────────────────────────────────────
def _render_snapshot_lines(snap: dict) -> list[str]:
    lines = []
    br = snap.get("branch") or "?"
    head = snap.get("head") or "?"
    subj = snap.get("head_subject") or ""
    lines.append(f"- 分支:`{br}` · HEAD:`{head}` {subj}")
    dc, uc = snap.get("dirty_count", 0), snap.get("untracked_count", 0)
    if dc:
        lines.append(f"- 未提交改动:{dc} 处(其中未跟踪 {uc})")
        for f in snap.get("dirty_files", []):
            lines.append(f"    · {f}")
    else:
        lines.append("- 工作区干净(无未提交改动)")
    ahead, behind = snap.get("ahead"), snap.get("behind")
    if ahead is not None or behind is not None:
        lines.append(f"- 相对上游:领先 {ahead or 0} · 落后 {behind or 0}")
    return lines


def render_markdown(pkg: dict) -> str:
    """把一只交接包渲染成自包含的 markdown —— 拷给任何人都能照着续跑。"""
    L = [f"# 📦 交接包 · {pkg['title']}", "",
         f"> id `{pkg['id']}` · 封于 {pkg['ts']} · 状态 {pkg.get('status')}", ""]
    if pkg.get("why"):
        L += ["## 为什么", pkg["why"], ""]
    L += ["## ✅ 已完成的状态(可信,不必重来)"]
    L += [f"- {s}" for s in pkg["done"]] or ["- (空)"]
    L += ["", "## 👉 下一步(从第一条接起)"]
    L += [f"{i}. {s}" for i, s in enumerate(pkg["next"], 1)] or ["- (空)"]
    L += ["", "## ⚠️ 风险与悬而未决"]
    L += [f"- {s}" for s in pkg["risk"]] or ["- (无已知风险)"]
    L += ["", "## 🔍 验证命令(跑通即证明接对了)"]
    L += [f"- `{s}`" for s in pkg["verify"]] or ["- (空)"]
    L += ["", "## 🗺️ git 现场快照(封包时刻)"]
    L += _render_snapshot_lines(pkg["snapshot"])
    L.append("")
    return "\n".join(L)


def _print_package(pkg: dict) -> None:
    print(render_markdown(pkg))
    g = gaps(pkg)
    if g:
        print("⚠️ 这只包还缺斤少两:")
        for s in g:
            print(f"   · {s}")


def _print_list(rows: list[dict]) -> None:
    if not rows:
        print("📦 没有开着的交接包 —— 用 --title 封一只,或 --json --list 看全部。")
        return
    print(f"📦 开着的交接包({len(rows)} 只):")
    for p in sorted(rows, key=lambda r: r["ts"], reverse=True):
        snap = p.get("snapshot", {})
        nxt = p.get("next") or []
        first = nxt[0] if nxt else "(无下一步)"
        print(f"   {_STATUS_ICON.get(p['status'],'?')} {p['id'][:15]}  {p['title']}")
        print(f"       分支 {snap.get('branch','?')} · 待办 {len(nxt)} 步 · 先做:{first}")


def _print_run(pkg: dict, results: list[dict]) -> None:
    print(f"🔍 跑交接包 {pkg['id'][:15]} 的验证命令({len(results)} 条):")
    if not results:
        print("   (这只包没写 verify 命令 —— 无从验证续跑状态)")
        return
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        print(f"   {mark} `{r['cmd']}`  (code={r['code']})")
    bad = [r for r in results if not r["ok"]]
    if bad:
        print(f"   ⚠️ {len(bad)} 条没通过 —— 续跑前先把现场对齐到快照。")
    else:
        print("   全部通过 —— 现场可信,接着干。")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="交接包:把半完成任务封成可续跑的箱子。")
    ap.add_argument("--title", help="任务标题(封新包时必给)")
    ap.add_argument("--why", default="", help="为什么做这件事")
    ap.add_argument("--done", action="append", default=[], metavar="状态",
                    help="已走通、不必重来的部分(可多次)")
    ap.add_argument("--next", action="append", default=[], dest="nexts",
                    metavar="步骤", help="有序的下一步(可多次,第一条最先做)")
    ap.add_argument("--risk", action="append", default=[], metavar="风险",
                    help="已知的雷与悬而未决的判断(可多次)")
    ap.add_argument("--verify", action="append", default=[], metavar="命令",
                    help="验证续跑状态的命令(可多次)")
    ap.add_argument("--dry", action="store_true", help="只看不存(连同 git 快照预览)")
    ap.add_argument("--list", action="store_true", help="列出还开着的交接包")
    ap.add_argument("--show", metavar="ID", help="渲染某只包的完整续跑简报")
    ap.add_argument("--resume", metavar="ID", help="同 --show,但标记为「已被取用」")
    ap.add_argument("--run", metavar="ID", help="真的跑该包的 verify 命令(唯一会动外部)")
    ap.add_argument("--close", metavar="ID", help="标记任务已续完,合箱")
    ap.add_argument("--json", action="store_true", help="机读输出")
    args = ap.parse_args(argv)

    # ── 查看类 ──
    if args.list:
        rows = open_packages()
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            _print_list(rows)
        return 0

    for flag in ("show", "resume", "run", "close"):
        pkg_id = getattr(args, flag)
        if not pkg_id:
            continue
        pkg = find(pkg_id)
        if pkg is None:
            ap.error(f"找不到交接包(或前缀不唯一):{pkg_id}")
        if flag == "run":
            results = run_verify(pkg)
            if args.json:
                print(json.dumps({"id": pkg["id"], "results": results},
                                 ensure_ascii=False, indent=2))
            else:
                _print_run(pkg, results)
            return 0
        if flag == "resume" and pkg["status"] == STATUS_OPEN:
            pkg = set_status(pkg, STATUS_RESUMED)
        if flag == "close":
            pkg = set_status(pkg, STATUS_DONE)
            if not args.json:
                print(f"✅ 交接包 {pkg['id'][:15]} 已合箱(续完)。")
                return 0
        if args.json:
            print(json.dumps(pkg, ensure_ascii=False, indent=2))
        else:
            _print_package(pkg)
        return 0

    # ── 封包 ──
    if not args.title:
        ap.error("封新包请给 --title;或用 --list / --show / --resume / --run / --close")
    pkg = build(args.title, args.why, args.done, args.nexts, args.risk, args.verify)
    if not args.dry:
        path = save(pkg)
        pkg["_package_path"] = str(path.relative_to(REPO_ROOT))
    if args.json:
        print(json.dumps(pkg, ensure_ascii=False, indent=2))
    else:
        _print_package(pkg)
        if args.dry:
            print("   (--dry:本次没落账本、没导出 .md)")
        else:
            print(f"\n📦 已封包并导出:{pkg['_package_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
