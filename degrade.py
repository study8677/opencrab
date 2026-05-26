#!/usr/bin/env python3
"""降级层 🪫 —— 当网络/模型/依赖塌了一角，替我把「还能做什么」从废墟里捞出来。

真正的自治不是「样样齐备时跑得漂亮」，而是**残缺环境里也能稳住价值**。网线断了、
模型端点超时了、本机的 `claude` 爪子不在了——这些不是「报错退出」就完事的意外，而是
日常。慌乱时最容易犯的错是**全有或全无**:一个依赖缺席，就把整张能力清单一并放下,
仿佛少了大脑就连扫地都不会了。

降级补的就是这一环:**有损但不停摆的纪律**。它不修复环境(那是运维的活)、不替我执行
(那是 crab 的活),只做三件事:

  · 探境(probe) —— 轻量探一探当下哪几样资源真的不可用(网络/模型/git 远端/本机爪子),
                   全程只读、带超时、绝不卡死。
  · 出方案(plan) —— 拿「不可用资源集合」对照每项能力的依赖,把全部能力分成三档:
                     ✅ 照常 / 🔁 降级(给出替代命令 + 明说损失什么) / ⛔ 受阻(说清丢了什么价值)。
  · 记账(log)    —— 每出一份降级方案就追加一条记录,事后能复看「那天断了网,我退到了哪」。

判准是一张人定的能力—资源依赖表(`CAPABILITIES`):每项能力声明它**需要**哪些资源、
缺了之后**退到**哪条命令、退下去**损失**什么。表里只收「确实有像样退路」的替代,宁可
诚实地标成「受阻」,也不编一条假装能顶上的命令——降级方案最忌讳的就是给人虚假的安心。

资源(`RESOURCES`):
  · network    —— 能不能连出去(urllib/socket)。
  · model      —— 大脑端点:既要 network,又要 OPENCRAB_API_KEY 在场且端点可达。
  · git-remote —— 能不能 push 到远端(同样依赖 network)。
  · hands      —— 本机的 claude / codex CLI 爪子在不在 PATH 上。

用法:
    python degrade.py --probe                  # 探一探当下哪些资源不可用(只读)
    python degrade.py --down network           # 假设网络挂了,出一份降级方案
    python degrade.py --down model --down hands # 多个资源同时塌
    python degrade.py --probe --plan           # 先探境,再按探出的结果出方案(并记账)
    python degrade.py --dry --down network      # 只看方案,不记账
    python degrade.py --history                # 复看历次降级方案
    python degrade.py --json --down model      # 机读

零第三方依赖,纯标准库。降级全程只读环境、只追加自己的日志,绝不反噬生命。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import shutil
import socket
import sys
from urllib.parse import urlparse

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import append_jsonl, read_jsonl  # noqa: E402

DEGRADE_LOG = REPO_ROOT / "state" / "degrade.jsonl"

# 四样会塌的资源 —— 顺序即「从外到内」:网络最外,爪子最内。
RESOURCES = ("network", "model", "git-remote", "hands")


# ── 能力—资源依赖表:人定的判准 ──────────────────────────────────────────
# 每项能力声明三件事:
#   needs    —— 缺了哪样资源它就跑不动(空 = 纯本地,永不受影响)。
#   fallback —— 退到哪条命令/做法;None = 没有像样退路,缺了就受阻。
#   loss     —— 退下去之后**诚实地**损失什么(给 fallback 配套;None 表示几乎无损)。
# 收录原则:只写「确实顶得上」的替代。宁可标成受阻,也不编一条假装能用的命令。
class Cap:
    __slots__ = ("name", "needs", "fallback", "loss", "blurb")

    def __init__(self, name, needs, fallback, loss, blurb):
        self.name = name
        self.needs = frozenset(needs)
        self.fallback = fallback
        self.loss = loss
        self.blurb = blurb


CAPABILITIES: tuple[Cap, ...] = (
    Cap("think", needs={"model", "network"},
        fallback="python route.py / planner.py 的本地启发式选向",
        loss="只剩规则与历史经验,接不了大脑的随机应变;新颖局面会更钝。",
        blurb="调用大脑端点做开放式推理。"),
    Cap("hands", needs={"hands"},
        fallback="python crab.py --autonomy journal(只写日志,不真动手)",
        loss="能想清楚、能记下来,但落不了地——改动得攒着等爪子回来。",
        blurb="借本机 claude/codex CLI 真的改代码。"),
    Cap("publish", needs={"git-remote", "network"},
        fallback="本地 git commit + 留在当前分支,等远端恢复再 push",
        loss="成果出不了门,外部看不到;协作者拿不到最新分支。",
        blurb="把自测过的改动 push 到公开远端。"),
    Cap("self-edit", needs=set(),
        fallback=None,
        loss=None,
        blurb="本地读代码、出方案、跑测试、提交——纯本地,断网也照常。"),
    Cap("evidence", needs=set(),
        fallback=None,
        loss=None,
        blurb="复证既有声明、跑 evidence/regression——纯本地账本,不依赖外部。"),
    Cap("journal", needs=set(),
        fallback=None,
        loss=None,
        blurb="写日志、记账、复盘——最内层的活,任何残缺下都还在。"),
    Cap("research", needs={"network"},
        fallback="退回本机 docs/ 与既有 journal 的离线知识",
        loss="查不了外部最新资料,只能吃存量;时效性问题会答错。",
        blurb="联网取外部文档/资料。"),
)
_BY_NAME = {c.name: c for c in CAPABILITIES}


# ── 探境:轻量、只读、带超时,绝不卡死 ────────────────────────────────────
def _network_up(host: str = "1.1.1.1", port: int = 443, timeout: float = 2.0) -> bool:
    """能不能连出去:对一个公共地址开一条短超时的 TCP,连上即算通。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _model_endpoint() -> tuple[str | None, str | None]:
    """从 .env / 环境读出大脑端点(key, base_url);不真发请求,只看在不在场。"""
    key = os.environ.get("OPENCRAB_API_KEY")
    base = os.environ.get("OPENCRAB_BASE_URL")
    envfile = REPO_ROOT / ".env"
    if (key is None or base is None) and envfile.exists():
        for line in envfile.read_text("utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == "OPENCRAB_API_KEY" and key is None:
                key = v
            elif k == "OPENCRAB_BASE_URL" and base is None:
                base = v
    return (key or None), (base or None)


def _model_reachable(timeout: float = 2.0) -> bool:
    """模型端点的主机能不能连上(只探 TCP,不发推理请求、不烧 token)。"""
    _, base = _model_endpoint()
    if not base:
        return False
    host = urlparse(base).hostname
    if not host:
        return False
    port = urlparse(base).port or (443 if base.startswith("https") else 80)
    return _network_up(host, port, timeout)


def _git_remote_configured() -> bool:
    """git 是否配了远端(只读 .git/config,不真 fetch)。"""
    cfg = REPO_ROOT / ".git" / "config"
    if not cfg.exists():
        return False
    return '[remote "' in cfg.read_text("utf-8", errors="ignore")


def _hands_present() -> bool:
    """本机有没有 claude / codex CLI 爪子。"""
    return bool(shutil.which("claude") or shutil.which("codex"))


def probe() -> dict:
    """探一探当下各资源的可用性,回 {resource: up?} + 一句缘由。全程只读。"""
    net = _network_up()
    key, _ = _model_endpoint()
    # 模型要三件齐全:网通、key 在场、端点可达。任缺一件即不可用。
    model = net and bool(key) and _model_reachable()
    git_remote = _git_remote_configured() and net
    hands = _hands_present()
    reasons = {
        "network": "TCP 探测可达" if net else "连不出去",
        "model": ("端点可达且 key 在场" if model else
                  ("缺 OPENCRAB_API_KEY" if not key else
                   ("网络不通" if not net else "端点连不上"))),
        "git-remote": ("已配远端且网通" if git_remote else
                       ("未配 git 远端" if not _git_remote_configured() else "网络不通")),
        "hands": "claude/codex 在 PATH" if hands else "本机找不到 claude/codex",
    }
    up = {"network": net, "model": model, "git-remote": git_remote, "hands": hands}
    return {"up": up, "down": [r for r in RESOURCES if not up[r]], "reasons": reasons}


# ── 出方案:拿不可用集合给每项能力分档 ──────────────────────────────────
def classify(cap: Cap, down: set[str]) -> dict:
    """单项能力在给定「不可用集合」下的处置:照常 / 降级 / 受阻。"""
    hit = sorted(cap.needs & down)
    if not hit:
        return {"name": cap.name, "status": "ok", "blocked_by": [],
                "blurb": cap.blurb, "fallback": None, "loss": None}
    # 被打中了:看 fallback 本身依不依赖任何仍然不可用的资源。
    # 这里 fallback 是人写的文字描述,我们不解析它的依赖——保守起见,
    # 只要原能力声明过 fallback 就算「有退路」,否则受阻。
    if cap.fallback is None:
        return {"name": cap.name, "status": "blocked", "blocked_by": hit,
                "blurb": cap.blurb, "fallback": None, "loss": cap.loss}
    return {"name": cap.name, "status": "degraded", "blocked_by": hit,
            "blurb": cap.blurb, "fallback": cap.fallback, "loss": cap.loss}


def plan(down: set[str]) -> dict:
    """对全部能力出一份降级方案,按 受阻 > 降级 > 照常 排序(最该看的在前)。"""
    unknown = sorted(down - set(RESOURCES))
    down = down & set(RESOURCES)
    rows = [classify(c, down) for c in CAPABILITIES]
    order = {"blocked": 0, "degraded": 1, "ok": 2}
    rows.sort(key=lambda r: order[r["status"]])
    counts = {s: sum(1 for r in rows if r["status"] == s)
              for s in ("ok", "degraded", "blocked")}
    return {
        "down": sorted(down),
        "unknown": unknown,
        "rows": rows,
        "counts": counts,
        "lost_value": [r["name"] for r in rows if r["status"] == "blocked"],
    }


# ── 记账 & 复盘 ──────────────────────────────────────────────────────────
def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def log_plan(p: dict, source: str) -> str:
    """把一份降级方案追加进日志,回填 id。source: probe / manual。"""
    pid = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    rec = {"kind": "plan", "id": pid, "ts": _now(), "source": source,
           "down": p["down"], "counts": p["counts"],
           "lost_value": p["lost_value"]}
    append_jsonl(DEGRADE_LOG, rec)
    return pid


def history(limit: int = 10) -> list[dict]:
    return [r for r in read_jsonl(DEGRADE_LOG) if r.get("kind") == "plan"][-limit:]


# ── 打印 ─────────────────────────────────────────────────────────────────
_ICON = {"ok": "✅", "degraded": "🔁", "blocked": "⛔"}


def _print_probe(pr: dict) -> None:
    print("🪫 探境(只读、带超时):")
    for r in RESOURCES:
        mark = "🟢" if pr["up"][r] else "🔴"
        print(f"   {mark} {r:<11} —— {pr['reasons'][r]}")
    if pr["down"]:
        print(f"   塌掉的资源:{', '.join(pr['down'])}")
    else:
        print("   四样资源都在 —— 满血,无需降级。")


def _print_plan(p: dict) -> None:
    down = ", ".join(p["down"]) if p["down"] else "(无)"
    print(f"🪫 降级方案 · 不可用资源:{down}")
    if p["unknown"]:
        print(f"   ⚠️ 不认识的资源名(已忽略):{', '.join(p['unknown'])}")
    c = p["counts"]
    print(f"   ✅ 照常 {c['ok']} · 🔁 降级 {c['degraded']} · ⛔ 受阻 {c['blocked']}")
    for r in p["rows"]:
        print(f"   {_ICON[r['status']]} {r['name']} —— {r['blurb']}")
        if r["blocked_by"]:
            print(f"       缺:{', '.join(r['blocked_by'])}")
        if r["status"] == "degraded":
            print(f"       🔁 退到:{r['fallback']}")
            if r["loss"]:
                print(f"       损失:{r['loss']}")
        elif r["status"] == "blocked":
            print("       ⛔ 没有像样退路 —— 这块价值暂时丢失:")
            print(f"          {r['loss']}")
    if p["lost_value"]:
        print(f"   ⛔ 本次彻底受阻的能力:{', '.join(p['lost_value'])}")
    else:
        print("   没有能力被彻底逼停 —— 都能照常或有损顶上。")


def _print_history(rows: list[dict]) -> None:
    if not rows:
        print("🪫 还没出过降级方案 —— 用 --down 或 --probe --plan 跑一次。")
        return
    print("🪫 历次降级方案:")
    for r in rows:
        down = ", ".join(r.get("down") or []) or "(无)"
        c = r.get("counts", {})
        lost = ", ".join(r.get("lost_value") or []) or "无"
        print(f"   [{r['ts']}] ({r.get('source','?')}) 断:{down} · "
              f"受阻 {c.get('blocked', 0)} 项(丢:{lost})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="降级层:残缺环境里捞出「还能做什么」。")
    ap.add_argument("--down", action="append", default=[], metavar="RESOURCE",
                    help=f"手动声明不可用的资源(可多次):{', '.join(RESOURCES)}")
    ap.add_argument("--probe", action="store_true", help="探一探当下哪些资源不可用(只读)")
    ap.add_argument("--plan", action="store_true",
                    help="配合 --probe:按探出的结果直接出方案")
    ap.add_argument("--history", action="store_true", help="复看历次降级方案")
    ap.add_argument("--dry", action="store_true", help="只看方案,不记进日志")
    ap.add_argument("--json", action="store_true", help="机读输出")
    args = ap.parse_args(argv)

    if args.history:
        rows = history()
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            _print_history(rows)
        return 0

    pr = None
    if args.probe:
        pr = probe()

    # 确定「不可用集合」:--probe 探出的 + 手动 --down 的,取并集。
    down: set[str] = set(args.down)
    if pr is not None:
        down |= set(pr["down"])

    # 只探境、不出方案:探完即止。
    want_plan = bool(args.down) or args.plan or (pr is None)
    if pr is not None and not want_plan:
        if args.json:
            print(json.dumps(pr, ensure_ascii=False, indent=2))
        else:
            _print_probe(pr)
        return 0

    if pr is None and not args.down:
        ap.error("给我 --down <资源> 出方案,或 --probe 探境,或 --history 复盘")

    p = plan(down)
    pid = None
    if not args.dry:
        pid = log_plan(p, source="probe" if pr is not None else "manual")
        p["logged_id"] = pid

    if args.json:
        out = {"probe": pr, "plan": p} if pr is not None else p
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if pr is not None:
            _print_probe(pr)
            print()
        _print_plan(p)
        if args.dry:
            print("   (--dry:本次没记进日志)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
