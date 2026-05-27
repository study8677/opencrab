#!/usr/bin/env python3
"""
opencrab 的手 🦀 —— 雇佣 Claude Code / Codex 当爪子，并安全地自我进化。

自我进化的 integrate 模式（由 OPENCRAB_AUTONOMY 决定）：
  branch  : 改动只留在新分支(最稳)
  merge   : 自测通过才合并到本地主干(不 push)
  publish : 自测通过才合并并 push 到公开仓(完全自主，"公开大海")

自生手默认优先：每次动手先走 brain-only 补丁(brain 凭招式库修语法级真伤、过补丁契约)，
brain 修不动或不适用才**降级**雇外援，并把降级原因记进 result["brain_reason"]。
断奶要从默认路径开始——能自己修的，绝不花钱雇爪子。

关键的免疫系统：它改完自己后，先自测「还能不能正常启动」——
通过才合并；不通过就自动回滚、丢弃这次改动，保住自己(断肢再生)。
git 始终攥在 opencrab 手里；爪子只拿到「改文件」的最小权限。
"""
from __future__ import annotations

import datetime
import pathlib
import re
import shutil
import subprocess
import sys


def has_hands(executor: str = "claude") -> bool:
    """这只手(执行器 CLI)是否就绪。"""
    return shutil.which(executor) is not None


def _slug(text: str, n: int = 24) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n] or "change"


def _git(repo: pathlib.Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=timeout)


def _plan_cmd(task: str, executor: str, budget_usd: float) -> list[str]:
    """爪子将要执行的真实命令(预演与实跑共用，保证预演看到的就是要跑的)。"""
    if executor == "codex":  # 实验性
        return ["codex", "exec", "--sandbox", "workspace-write", task]
    return ["claude", "-p", task, "--permission-mode", "acceptEdits",
            "--allowedTools", "Read Edit Write Glob Grep Bash(git rm:*) Bash(git mv:*)",
            "--disallowedTools", "WebFetch WebSearch",
            "--max-budget-usd", str(budget_usd), "--output-format", "text"]


def _dry_run_preview(task: str, *, repo: pathlib.Path, branch: str, base: str,
                     executor: str, budget_usd: float, integrate: str,
                     available: bool) -> dict:
    """预演：真正雇佣爪子之前，先把完整执行路径、将要做的改动与风险点摊开看。"""
    cmd = _plan_cmd(task, executor, budget_usd)

    # 执行路径：把 integrate 模式下会一步步发生什么写清楚
    steps = [f"开新分支 {branch}（从 {base}）",
             "自生手优先：先走 brain-only 补丁（招式库修语法级真伤，过补丁契约，不雇外援、不花钱）",
             f"brain 修不动 → 降级雇佣 {executor} 改文件（预算 ${budget_usd}，仅 Read/Edit/Write/Glob/Grep，禁 Bash/联网），并记录降级原因",
             "opencrab 亲自 git add -A 并提交改动到分支"]
    if integrate == "branch":
        steps.append("停在分支上养着，不合并、不 push")
    else:
        steps.append("自测：py_compile 全部 *.py + import crab（不过则回滚丢弃、保命）")
        steps.append(f"自测通过 → checkout {base} 并 --no-ff 合并（冲突则放弃留分支）")
        if integrate == "publish":
            steps.append(f"push origin {base} 到公开仓 🌊")
        else:
            steps.append("只到本地主干，不 push")

    # 风险点：越靠后越危险，预演的价值就在这里
    risks: list[str] = []
    if not available:
        risks.append(f"⛔ 未找到 {executor} CLI —— brain 修不动时无外援可降级，那类任务将放弃、无改动")
    if executor == "codex":
        risks.append("⚠️ codex 执行器仍是实验性，sandbox 行为未充分验证")
    if integrate == "publish":
        risks.append("🌊 publish：自测一过就会 push 到公开仓，改动将对全世界可见")
    elif integrate == "merge":
        risks.append("🔀 merge：自测一过就并入本地主干（不 push，但本地主干会变）")

    dirty = _git(repo, "status", "--porcelain").stdout.strip()
    if dirty:
        n = len(dirty.splitlines())
        risks.append(f"⚠️ 工作区已有 {n} 处未提交改动 —— git add -A 会把它们一起卷进本次提交")
    if _git(repo, "rev-parse", "--verify", branch).returncode == 0:
        risks.append(f"⚠️ 分支 {branch} 已存在 —— 实跑开分支会失败")
    if not risks:
        risks.append("✅ 未发现明显风险点")

    return {"ok": False, "branch": branch, "base": base, "executor": executor,
            "available": available, "changed": False, "integrate": integrate,
            "dry_run": True, "planned_cmd": cmd, "steps": steps, "risks": risks,
            "note": f"[预演] 模拟在 {branch} 上以 {integrate} 模式实施：{task[:70]}（未做任何改动）"}


def _self_test(repo: pathlib.Path) -> tuple[bool, str]:
    """它改完自己后，验证「还能不能启动」：语法编译 + 导入主模块。"""
    pys = [p.name for p in repo.glob("*.py")]
    if pys:
        r = subprocess.run([sys.executable, "-m", "py_compile", *pys],
                           cwd=str(repo), capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return False, "语法错误：" + (r.stderr.strip()[:200] or "?")
    r2 = subprocess.run([sys.executable, "-c", "import crab"],
                        cwd=str(repo), capture_output=True, text=True, timeout=60)
    if r2.returncode != 0:
        return False, "导入失败：" + (r2.stderr.strip()[:200] or "?")
    return True, "自测通过：改完还能正常启动"


def _brain_attempt(repo: pathlib.Path) -> dict:
    """自生手优先：先让 brain 独立产「brain-only 补丁」，一律不雇外援。

    brain 的招式库(weaning_trial.TACTICS)只覆盖**语法级真伤**(补冒号 / print 括号等)——
    能修就自己修；本就没有语法伤(特性级改动它不会)或修不动，就老实记下原因，交回上层降级外援。
    断奶要从默认路径开始：先走这里，失败才花钱雇爪子。
    返回 {ok, reason, trace, files}。
    """
    try:
        import weaning_trial
        import patchcontract
    except Exception as e:   # noqa: BLE001 —— brain 模块缺席就如实降级，绝不假装能自修
        return {"ok": False, "reason": f"brain 模块缺席({type(e).__name__})，无法自修",
                "trace": [], "files": []}

    broken: list[tuple[pathlib.Path, str, SyntaxError]] = []
    for p in sorted(repo.glob("*.py")):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            compile(src, p.name, "exec")   # 只编译不 exec：探伤安全，绝不跑真模块的副作用
        except SyntaxError as e:
            broken.append((p, src, e))
        except OSError:
            continue
    if not broken:
        return {"ok": False, "reason": "无语法级真伤可修——brain 招式库不覆盖特性级改动",
                "trace": [], "files": []}

    trace: list[str] = []
    fixed_files: list[str] = []
    for p, src, exc in broken:
        cur, cur_exc, healed = src, exc, False
        for _ in range(6):
            applied = False
            for tactic in weaning_trial.TACTICS:
                cand = tactic(cur, cur_exc)
                if not cand or cand == cur:
                    continue
                verdict = patchcontract.validate(cur, cand)   # 拒收闸：畸形/越界(重写式大改)当场拒
                if not verdict.ok:
                    trace.append(f"{p.name}: {tactic.__name__} 被契约拒收({verdict.code})")
                    continue
                trace.append(f"{p.name}: {tactic.__name__} ⮕ {type(cur_exc).__name__}")
                cur, applied = cand, True
                break
            if not applied:
                break
            try:
                compile(cur, p.name, "exec")
                healed = True
                break
            except SyntaxError as e2:
                cur_exc = e2
        if healed:
            p.write_text(cur, encoding="utf-8")
            fixed_files.append(p.name)
        else:   # 无招可解：本文件回滚原样(不落盘)，交回上层降级外援
            trace.append(f"{p.name}: 无招可解 {type(cur_exc).__name__}")
            return {"ok": False,
                    "reason": f"brain 修不动 {p.name}({type(cur_exc).__name__})",
                    "trace": trace, "files": fixed_files}
    return {"ok": True,
            "reason": f"brain 独立修好 {len(fixed_files)} 个语法伤：{', '.join(fixed_files)}",
            "trace": trace, "files": fixed_files}


def use_hands(task: str, *, repo: pathlib.Path, executor: str = "claude",
              budget_usd: float = 0.5, dry_run: bool = False,
              integrate: str = "branch") -> dict:
    """让手在新分支上实施 task，再按 integrate 模式安全地并入。"""
    repo = pathlib.Path(repo)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = f"crab/{stamp}-{_slug(task)}"
    available = has_hands(executor)
    base = "main"   # 合并目标恒为主干，绝不跟着「当前分支」跑偏（曾因被 kill 时停在 crab 分支而锁死、进化推不上云端）

    if dry_run:
        return _dry_run_preview(task, repo=repo, branch=branch, base=base,
                                executor=executor, budget_usd=budget_usd,
                                integrate=integrate, available=available)

    _git(repo, "checkout", "-f", base)   # 先强制回主干：确保从 main 开枝、改完也回 main，不在 crab 分支上越积越偏
    base_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()   # 开枝前 base 的 HEAD：补丁解释层据此算回滚点
    if _git(repo, "checkout", "-b", branch).returncode != 0:
        return {"ok": False, "branch": branch, "changed": False,
                "integrate": integrate, "note": "开分支失败(可能重名)。"}

    result = {"branch": branch, "base": base, "executor": executor,
              "available": available, "integrate": integrate, "changed": False,
              "ok": False, "task": task, "base_sha": base_sha}   # task/base_sha 供 patchnote 写「依据」与「回滚点」
    try:
        # 1) 自生手优先：先走 brain-only 补丁，失败才降级外援，并记录原因（断奶从默认路径开始）
        brain = _brain_attempt(repo)
        result["brain_reason"] = brain["reason"]
        result["brain_trace"] = brain["trace"]
        if brain["ok"]:
            result["mode"] = "brain"   # brain 独立动手，不雇外援、不花一分钱
        else:
            # 降级外援：brain 没解，记下原因，再雇爪子
            if not available:          # 连外援都没有 → 无路可走，丢弃空分支保持干净
                result["mode"] = "downgrade-unavailable"
                _git(repo, "checkout", "-f", base)
                _git(repo, "branch", "-D", branch)
                result["note"] = (f"[brain 未解：{brain['reason']}；且未找到 {executor} CLI] "
                                  f"本应（{integrate} 模式）实施：{task[:70]}")
                return result
            result["mode"] = "hired"
            # 雇佣爪子改文件：只给「改文件」最小权限，不碰 git / Bash / 联网
            cmd = _plan_cmd(task, executor, budget_usd)  # 与预演看到的命令完全一致
            proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=900)
            result["exit"] = proc.returncode

        # 2) opencrab 亲自把改动提交到分支
        _git(repo, "add", "-A")
        diffstat = _git(repo, "diff", "--cached", "--stat").stdout.strip()
        result["diffstat"] = diffstat
        if not diffstat:
            result["note"] = ("brain 与外援都没做出任何改动。" if result["mode"] == "brain"
                              else "爪子没做出任何改动。")
            return result
        result["changed"] = True
        hand = "brain-only 自生手" if result["mode"] == "brain" else f"外援 {executor}"
        _git(repo, "commit", "-m", f"🦀 self-evolve: {task[:60]}",
             "-m", f"opencrab 自主提出并实施（{hand}）。")

        result["patch_sha"] = _git(repo, "rev-parse", "HEAD").stdout.strip()  # 分支上这条提交：回滚点之一

        if integrate == "branch":
            result["ok"] = True
            result["note"] = f"改动在分支 {branch}，先养着，未合并。"
            return result

        # 3) 免疫系统：改完自己，先自测「还能不能活」
        ok, why = _self_test(repo)
        result["self_test"] = why
        if not ok:
            _git(repo, "checkout", base)          # 断肢再生：回滚保命
            _git(repo, "branch", "-D", branch)
            result["healed"] = True
            result["note"] = f"自测没过（{why}）→ 已回滚丢弃，保住了自己。"
            return result

        # 4) 自测通过 → 合并到主干
        _git(repo, "checkout", base)
        if _git(repo, "merge", "--no-ff", branch,
                "-m", f"🦀 evolve: {task[:50]}").returncode != 0:
            _git(repo, "merge", "--abort")
            result["note"] = "合并冲突 → 已放弃，改动留在分支。"
            return result
        result["merge_sha"] = _git(repo, "rev-parse", "HEAD").stdout.strip()  # 合并提交：publish/merge 的回滚点
        _git(repo, "branch", "-D", branch)

        if integrate == "publish":              # 公开大海：推向全世界
            push = _git(repo, "push", "origin", base, timeout=120)
            result["ok"] = push.returncode == 0
            result["note"] = ("自测通过 → 已合并并 push 到公开仓 🌊" if result["ok"]
                              else "已合并到本地，但 push 失败：" + push.stderr.strip()[:120])
        else:                                   # merge：只到本地主干
            result["ok"] = True
            result["note"] = "自测通过 → 已合并到本地主干(未 push)。"
        return result
    finally:
        cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if cur and cur != base:                 # 兜底：确保回到主干
            _git(repo, "checkout", base)
        _feedback(result)                       # 证据回灌：把这次自测判决喂回信任分/能力图谱


def _feedback(result: dict) -> None:
    """把这次动手的结果回灌给证据账本/能力图谱，并落一条可审的补丁说明(尽力而为，绝不反噬动手)。"""
    try:
        import handsfeedback
        handsfeedback.feed(result)
    except Exception:   # noqa: BLE001 —— 回灌是副产物，缺席/出错都不该拖垮手
        pass
    try:
        import patchnote
        patchnote.explain(result)   # 落笔即写下依据/契约影响/回滚点，让每一爪可审
    except Exception:   # noqa: BLE001 —— 解释同为副产物，出错绝不拖垮动手
        pass
