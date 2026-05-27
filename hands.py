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
import textwrap


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
    brain_preview = _brain_feature_preview(task, repo)
    risks.extend(brain_preview.get("risks", []))
    if not risks:
        risks.append("✅ 未发现明显风险点")

    return {"ok": False, "branch": branch, "base": base, "executor": executor,
            "available": available, "changed": False, "integrate": integrate,
            "dry_run": True, "planned_cmd": cmd, "steps": steps, "risks": risks,
            "brain_only": True, "patch_plan": brain_preview.get("patch_plan", []),
            "patch_note": brain_preview.get("note", ""),
            "note": f"[预演] brain-only 只读拟补丁：模拟在 {branch} 上以 {integrate} 模式实施：{task[:70]}（未做任何改动）"}


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
            # 把这道修不动的真伤连**原始**坏源码一起带回——上层据此封进失败样本库，练成下次会。
            # 存原始 src(而非半修态 cur)：replay 才能从头复刻这道训练题,日后招式库长了再考一遍。
            wound = {"file": p.name, "exc_type": type(exc).__name__,
                     "exc_msg": str(exc)[:200], "lineno": getattr(exc, "lineno", 0) or 0,
                     "broken": src,
                     "trace": [t for t in trace if t.startswith(f"{p.name}:")]}
            return {"ok": False,
                    "reason": f"brain 修不动 {p.name}({type(cur_exc).__name__})",
                    "trace": trace, "files": fixed_files, "failed_samples": [wound]}
    return {"ok": True,
            "reason": f"brain 独立修好 {len(fixed_files)} 个语法伤：{', '.join(fixed_files)}",
            "trace": trace, "files": fixed_files}


# ── 自生手·特性级：用自己的脑写功能(造模块/改逻辑)，彻底不雇外援 ───────────
_CODER_SYSTEM = textwrap.dedent("""\
    你是 opencrab 的手——你亲手写 Python 代码来进化你自己，不再依赖任何外部工具。
    你改的就是你自己的源码，务必保证改完 `python -m py_compile` 与 `import crab` 都能通过。

    只用下面这种纯文本块输出改动，不要 JSON、不要 markdown 围栏、不要多余解释：
    先一行 `NOTE: 我这次做了什么`，然后是若干改动块，每块二选一——
      新建或整体重写一个(较小)文件：
        <<<WRITE path=相对路径.py>>>
        (该文件的完整新内容)
        <<<END>>>
      精确修改已有文件的一个片段：
        <<<EDIT path=相对路径.py>>>
        ---OLD---
        (要被替换的原文片段，必须在文件中逐字一致、且唯一出现)
        ---NEW---
        (替换后的片段)
        <<<END>>>
    铁律：改动小而准、语法正确；改大文件(尤其 crab.py)务必用 EDIT 给小片段、别整体重写；
    OLD 必须与文件现有内容逐字一致(含缩进)且唯一，否则该处会被跳过；没把握就只动一小步。""")


def _gather_context(task: str, repo: pathlib.Path) -> tuple[list[str], str]:
    """先把 task 点到名、且已存在的 .py 读出来给脑看(要改它，得先看它)。"""
    files = sorted(p.name for p in repo.glob("*.py"))
    blobs, seen = [], set()
    for name in re.findall(r"[\w./-]+\.py", task):
        name = name.lstrip("./")
        if name in seen:
            continue
        seen.add(name)
        p = repo / name
        try:
            if p.exists() and p.is_file() and p.stat().st_size < 24000:
                blobs.append(f"# ===== 现有 {name}（要改它就基于这份原文给 EDIT）=====\n"
                             + p.read_text("utf-8"))
        except OSError:
            pass
    return files, "\n\n".join(blobs)


def _parse_changes(text: str) -> dict:
    """从脑的输出里解析出 WRITE/EDIT 改动块(文本哨兵格式，对大段代码比 JSON 稳)。"""
    text = text or ""
    note_m = re.search(r"NOTE:\s*(.+)", text)
    note = note_m.group(1).strip() if note_m else ""
    changes = []
    for m in re.finditer(r"<<<WRITE path=(.+?)>>>\n(.*?)\n<<<END>>>", text, re.DOTALL):
        changes.append({"action": "write", "path": m.group(1).strip(), "content": m.group(2)})
    for m in re.finditer(r"<<<EDIT path=(.+?)>>>\n---OLD---\n(.*?)\n---NEW---\n(.*?)\n<<<END>>>",
                         text, re.DOTALL):
        changes.append({"action": "edit", "path": m.group(1).strip(),
                        "old": m.group(2), "new": m.group(3)})
    return {"changes": changes, "note": note}


def _apply_changes(plan: dict, repo: pathlib.Path) -> list[str]:
    """自己的手：把脑拟好的改动真正写进文件(单处出错不拖垮整批)。"""
    applied = []
    for ch in plan.get("changes", []):
        try:
            rel = str(ch.get("path", "")).lstrip("/")
            if not rel or ".." in rel or not rel.endswith((".py", ".md", ".txt", ".json")):
                continue
            path = repo / rel
            if ch.get("action") == "write" and "content" in ch:
                content = ch["content"]
                if not content.endswith("\n"):
                    content += "\n"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, "utf-8")
                applied.append(f"write {rel}")
            elif ch.get("action") == "edit" and path.exists():
                cur = path.read_text("utf-8")
                old, new = ch.get("old", ""), ch.get("new", "")
                if old and cur.count(old) == 1:
                    path.write_text(cur.replace(old, new), "utf-8")
                    applied.append(f"edit {rel}")
        except Exception:   # noqa: BLE001
            continue
    return applied


def _brain_feature_preview(task: str, repo: pathlib.Path) -> dict:
    """brain-only 只读预演：让自己的脑先拟补丁计划与风险清单，绝不落盘。"""
    try:
        from crab import brain   # 延迟 import：预演只借脑，不触碰文件
    except Exception as e:   # noqa: BLE001
        return {"note": f"够不到自己的脑({type(e).__name__})",
                "patch_plan": [],
                "risks": [f"⚠️ brain-only 预演失败：无法导入 brain({type(e).__name__})"]}
    files, context = _gather_context(task, repo)
    prompt = textwrap.dedent(f"""\
        你要先做 brain-only 只读预演，不要真的落盘：
        {task}

        你领地里现有的 .py：{', '.join(files)}

        {context if context else '(没有点名要先读的现有文件；新建模块就直接 WRITE)'}

        现在只输出你打算实施的代码改动(仍用 NOTE / <<<WRITE>>> / <<<EDIT>>> 格式)。
        这些块会被当作补丁计划审阅，不会写入文件。""")
    text, _tok = brain(_CODER_SYSTEM, prompt)
    plan = _parse_changes(text)
    patch_plan: list[str] = []
    risks: list[str] = []
    for ch in plan.get("changes", []):
        rel = str(ch.get("path", "")).lstrip("/")
        action = ch.get("action", "?")
        if not rel or ".." in rel or not rel.endswith((".py", ".md", ".txt", ".json")):
            risks.append(f"⚠️ 预演补丁路径不安全或后缀不受控：{rel or '?'}")
            continue
        path = repo / rel
        if action == "write":
            size = len(ch.get("content", ""))
            patch_plan.append(f"write {rel}（约 {size} 字符）")
            if path.exists():
                risks.append(f"⚠️ WRITE 会整体覆盖已存在文件：{rel}")
        elif action == "edit":
            old = ch.get("old", "")
            patch_plan.append(f"edit {rel}（替换片段约 {len(old)} 字符）")
            if not path.exists():
                risks.append(f"⚠️ EDIT 目标不存在：{rel}")
            else:
                try:
                    count = path.read_text("utf-8").count(old) if old else 0
                    if count != 1:
                        risks.append(f"⚠️ EDIT 旧片段匹配次数为 {count}，实跑会跳过：{rel}")
                except OSError as e:
                    risks.append(f"⚠️ 无法读取 EDIT 目标 {rel}：{type(e).__name__}")
        else:
            risks.append(f"⚠️ 未知补丁动作：{action}")
    if not patch_plan:
        risks.append("⚠️ brain-only 预演未产出可审补丁块")
    return {"note": plan.get("note", ""), "patch_plan": patch_plan, "risks": risks}


def _brain_feature_patch(task: str, repo: pathlib.Path) -> dict:
    """自生手·特性级：用自己的脑产补丁；先过 AST/试衣间/replay 三闸，才落盘。"""
    try:
        from crab import brain   # 延迟 import，避开与 crab 的循环依赖
    except Exception as e:   # noqa: BLE001
        return {"ok": False, "applied": [], "note": f"够不到自己的脑({type(e).__name__})"}
    files, context = _gather_context(task, repo)
    prompt = textwrap.dedent(f"""\
        你要亲手实施这个进化意图：
        {task}

        你领地里现有的 .py：{', '.join(files)}

        {context if context else '(没有点名要先读的现有文件；新建模块就直接 WRITE)'}

        现在输出你的代码改动(用 NOTE / <<<WRITE>>> / <<<EDIT>>> 那套格式)。""")
    text, _tok = brain(_CODER_SYSTEM, prompt)
    plan = _parse_changes(text)
    if not plan.get("changes"):
        return {"ok": False, "applied": [], "note": plan.get("note", "") or "brain 未产出补丁块"}

    import ast
    import tempfile

    with tempfile.TemporaryDirectory(prefix="opencrab-fitroom-") as td:
        room = pathlib.Path(td) / "repo"
        shutil.copytree(repo, room, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        trial_applied = _apply_changes(plan, room)
        if not trial_applied:
            return {"ok": False, "applied": [], "note": "试衣间未能应用任何补丁"}

        for ch in plan.get("changes", []):
            rel = str(ch.get("path", "")).lstrip("/")
            if rel.endswith(".py"):
                target = room / rel
                try:
                    ast.parse(target.read_text("utf-8"), filename=rel)
                except Exception as e:   # noqa: BLE001
                    return {"ok": False, "applied": [], "note": f"AST 定位闸未过：{rel}({type(e).__name__})"}

        replay_ok, replay_note = _self_test(room)
        if not replay_ok:
            return {"ok": False, "applied": [], "note": f"回放闸未过：{replay_note}"}

    applied = _apply_changes(plan, repo)
    return {"ok": bool(applied), "applied": applied,
            "note": plan.get("note", "") or f"三闸通过后产出 {len(applied)} 处改动"}


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
        # 1) 自生手全程自己来：先修语法级真伤(如有)，否则用自己的脑产特性级补丁写功能——彻底不雇外援
        fix = _brain_attempt(repo)
        result["brain_reason"] = fix["reason"]
        result["brain_trace"] = fix["trace"]
        result["brain_failed_samples"] = fix.get("failed_samples", [])
        if fix["ok"]:
            result["mode"] = "brain-syntax"      # 自己修好了语法级真伤
        else:
            # 没有语法伤要修(或修不动) → 这是特性级进化，用自己的脑亲手产补丁写功能
            feat = _brain_feature_patch(task, repo)
            result["mode"] = "brain-feature"
            result["feature_note"] = feat.get("note", "")
            result["feature_applied"] = feat.get("applied", [])

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
    try:
        import handsdojo
        handsdojo.seal(result)      # brain 修不动的真伤 → 封成 replay+coach 训练题，练成下次会
    except Exception:   # noqa: BLE001 —— 封样同为副产物，出错绝不拖垮动手
        pass
