#!/usr/bin/env python3
"""自生手补丁可解释层 🧾🖐️ —— brain 每落一爪，同步写下「依据 / 契约影响 / 回滚点」。

为什么要有它：`hands.py` 已经会动手改代码、改完自测、通过才合并；`handsfeedback.py`
把那次自测判决回灌成证据。可那条流水只记得「改没改、自测过没过、碰了哪些模块」——
**它说不清这一爪「为什么落、动了谁的承诺、出事怎么退」**。一只会动手的爪子若不可审，
便不可托付：日后翻账只见一行 diffstat，问不出「当初凭什么改成这样」。

本层就补上这块「可解释」：`hands.use_hands` 每跑完真动手的一次，把结果交给 `explain()`，
它当场提炼出三件可审的事，落进自己的账本，也渲染成一段人能读的补丁说明——

  1) 📌 **依据(rationale)**：这一爪是冲着什么任务落的、碰了哪些模块、自测判了什么。
     不是事后补的注脚，是落笔当下就钉死的「我为何这么改」。
  2) 📜 **契约影响(contract impact)**：碰过的模块里，哪些在 `contracts.py` 立过对外契约。
     动了立约模块 = 动了对下游的公开承诺，必须显式标红——这是问责的着力点。
  3) 🪂 **回滚点(rollback point)**：给出一条**具体能跑的**退路命令，按 integrate 模式分流：
     branch 留分支(base 没动，删分支即可)、merge 本地合并(revert 合并提交)、
     publish 已推公开仓(只能 revert + 再 push，绝不改写公开历史)。

账本落在被 .gitignore 的 state/ 里，写盘失败绝不反噬生命；解释是落笔的副产物，
出任何错都被吞掉，绝不拖垮 hands 的动手主流程。零第三方依赖，纯标准库。

用法：
    python patchnote.py             # 看最近几爪的补丁说明(依据/契约影响/回滚点)
    python patchnote.py --last      # 只看最近一爪的完整说明
    python patchnote.py --json      # 机读：最近若干条解释记录
    python patchnote.py --selfcheck --quiet   # 自检(供 evidence 的 patchnote 声明复跑)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402  —— 复用「读一批 / 追一条」的安全落地层

LEDGER_PATH = REPO_ROOT / "state" / "patchnote" / "ledger.jsonl"

SHOW_DEFAULT = 5        # 默认列最近这么多条补丁说明


# ── 从结果里提炼三件可审的事 ──────────────────────────────────────────
def _touched_modules(diffstat: str) -> list[str]:
    """从 git diff --stat 文案里挑出本次碰过的、领地根目录的 *.py 模块名(stem)。

    与 handsfeedback 同口径：取 `|` 前的路径，只认根目录下的 .py(带 / 的是子目录、
    跳过；`=>` 是重命名行、跳过)。本地实现一份，免得为提炼模块名硬依赖回灌层在场。
    """
    mods: list[str] = []
    for line in (diffstat or "").splitlines():
        path = line.split("|", 1)[0].strip()
        if not path or "=>" in path:
            continue
        if "/" in path or not path.endswith(".py"):
            continue
        stem = path[:-3]
        if stem and stem not in mods:
            mods.append(stem)
    return mods


def _contract_modules() -> set[str]:
    """当前在 contracts.py 立过对外契约的模块名集合(取不到就当空集，绝不抛)。"""
    try:
        import contracts
        return {c["module"] for c in contracts.manifest().get("contracts", [])}
    except Exception:  # noqa: BLE001 —— 契约层缺席/出错都不该挡住解释
        return set()


def _verdict(result: dict) -> str:
    """把这一爪的自测判决浓缩成一句人话。"""
    if "self_test" not in result:
        return "未自测(branch 模式不跑自测)"
    if result.get("healed"):
        return f"自测未过 → 已断肢再生回滚（{result.get('self_test', '?')}）"
    return f"自测通过（{result.get('self_test', '改完还能正常启动')}）"


def _rollback_plan(result: dict) -> dict:
    """按这一爪**真正落到哪一步**给出一条具体能跑的退路——不看 integrate 的意图，
    看 merge_sha / push 结果这些**事实**，免得「想 publish 但 push 失败」被误判成没动主干。

    分四种处境，退法天差地别——这正是「回滚点」要钉死的：
      · 自测未过(healed)：免疫系统已当场回滚删分支，base 从未被污染 → 无需再退。
      · 没并入主干       ：branch 模式留分支 / 合并冲突已 abort，base 没动 → 删分支即弃。
      · 已并入本地、未 push：merge 模式，或 publish 但 push 失败 → revert 合并提交(或 reset 回 base)。
      · 已并入并 push    ：公开历史不可改写 → 只能 revert 合并提交后再 push。
    """
    integrate = str(result.get("integrate") or "?")
    branch = str(result.get("branch") or "?")
    base = str(result.get("base") or "main")
    base_sha = result.get("base_sha") or ""        # 开枝前 base 的 HEAD
    merge_sha = result.get("merge_sha") or ""       # 合并后 base 的 HEAD(合并提交)
    patch_sha = result.get("patch_sha") or ""       # 分支上那条提交(branch 模式留着的就是它)
    merged_local = bool(merge_sha)                  # 事实：是否真已并入本地主干
    pushed = bool(result.get("ok")) and integrate == "publish"   # 事实：是否真已 push 公开

    if result.get("healed"):
        # 自测没过，hands 已断肢再生(回滚+删分支)，base 从未被污染，没有残留可退。
        return {"mode": "auto-healed",
                "where": f"base（{base}）未动，自测未过已被免疫系统自动回滚",
                "command": "(无需回滚：自测未过，已断肢再生)", "safe": True,
                "why": "改动从未并入主干，hands 当场回滚并删了分支，没有残留可退。"}

    if not merged_local:
        # 没并入主干：base 没动一根毫毛，弃掉这爪只需删分支(branch 模式留着的就是它)。
        cmd = f"git branch -D {branch}"
        where = f"base（{base}）未动" + (f"，分支停在 {patch_sha[:9]}" if patch_sha else "")
        return {"mode": "discard-branch", "where": where, "command": cmd,
                "safe": True, "patch_sha": patch_sha,
                "why": "改动只在分支上养着，从未触碰主干，删分支即彻底丢弃、零残留。"}

    if pushed:
        # 已推公开仓：公开历史不可改写，只能用 revert 造一条反向提交再 push。
        cmd = f"git revert -m 1 {merge_sha[:9]} && git push origin {base}"
        return {"mode": "revert-published", "where": f"已并入并 push 到 origin/{base}",
                "command": cmd, "safe": False,
                "why": "公开历史已对全世界可见，绝不可 reset 改写；只能 revert 合并提交"
                       "造一条反向爪印，再 push 让退路同样公开可查。"}

    # 已并入本地、未 push(merge 模式，或 publish 但 push 失败)：首选不改写历史的 revert。
    alt = f"git reset --hard {base_sha[:9]}" if base_sha else f"git reset --hard {base}@{{1}}"
    cmd = f"git revert -m 1 {merge_sha[:9]}"
    return {"mode": "revert-local", "where": f"已并入本地主干 {base}（未 push）",
            "command": cmd, "safe": True, "alt": alt,
            "why": "已在本地主干、尚未公开，首选 revert 合并提交(不改写历史)；"
                   "确无人依赖这几条提交时，也可 reset --hard 回改前那一刻。"}


def distill(result: dict, *, now: float | None = None,
            known_contracts: set[str] | None = None) -> dict | None:
    """把一次 use_hands 的结果提炼成一条可审的补丁说明；不该解释的返回 None。

    只解释「真动了手」的那几次——没改动 / 预演 / 没找到爪子，都没有可审的一爪。
    known_contracts 为立约模块名集合(默认现读 contracts.py；测试时可注入以求确定)。
    """
    if not isinstance(result, dict) or result.get("dry_run"):
        return None
    if not result.get("changed"):
        return None

    declared = _contract_modules() if known_contracts is None else known_contracts
    modules = _touched_modules(result.get("diffstat", ""))
    contract_mods = sorted(set(modules) & declared)
    return {
        "ts": time.time() if now is None else now,
        "executor": str(result.get("executor") or "?"),
        "integrate": str(result.get("integrate") or "?"),
        "branch": str(result.get("branch") or ""),
        "merged": bool(result.get("ok") and result.get("integrate") != "branch"),
        # 📌 依据：冲着什么任务落的、碰了谁、自测判了什么
        "rationale": {
            "task": str(result.get("task") or "")[:200] or "(未记录任务文案)",
            "modules": modules,
            "verdict": _verdict(result),
        },
        # 📜 契约影响：碰过的立约模块(动了它=动了对下游的公开承诺)
        "contract_impact": {
            "touched_contract_modules": contract_mods,
            "level": "high" if contract_mods else ("low" if modules else "none"),
            "note": ("动了立约模块，须确认契约验收样例仍守约（python contracts.py）"
                     if contract_mods else "未触碰任何立约模块"),
        },
        # 🪂 回滚点：一条具体能跑的退路
        "rollback": _rollback_plan(result),
    }


def explain(result: dict, *, now: float | None = None) -> dict | None:
    """解释入口：把一次 use_hands 结果提炼成补丁说明并落账。

    返回落下的那条记录(没可解释的返回 None)。全程尽力而为：任何异常都被吞掉，
    绝不反噬 hands 的动手主流程。
    """
    try:
        rec = distill(result, now=now)
        if rec is None:
            return None
        jsonlstore.append_jsonl(LEDGER_PATH, rec)
        return rec
    except Exception:  # noqa: BLE001 —— 解释是副产物，出错绝不拖垮动手
        return None


# ── 读取与展示 ─────────────────────────────────────────────────────────
def recent(limit: int = SHOW_DEFAULT, *, rows: list[dict] | None = None) -> list[dict]:
    """取最近 limit 条补丁说明(账本尾部最新)。"""
    rows = jsonlstore.read_jsonl(LEDGER_PATH) if rows is None else rows
    rows = [r for r in rows if isinstance(r, dict) and "rationale" in r]
    rows.sort(key=lambda r: r.get("ts", 0))
    return rows[-limit:] if limit and limit > 0 else rows


def _ago(ts, now: float) -> str:
    if not isinstance(ts, (int, float)):
        return "?"
    d = (now - ts) / 86400.0
    return f"{d:.1f} 天前" if d >= 1 else f"{d * 24:.1f} 小时前"


_LEVEL_MARK = {"high": "🟥", "low": "🟦", "none": "⬜"}


def render(rec: dict, *, now: float, full: bool = False) -> str:
    """把一条补丁说明渲染成人能读的几行(full=展开回滚原因)。"""
    r = rec.get("rationale", {})
    ci = rec.get("contract_impact", {})
    rb = rec.get("rollback", {})
    mods = r.get("modules") or []
    head = (f"🧾 [{rec.get('executor', '?')}/{rec.get('integrate', '?')}] "
            f"{_ago(rec.get('ts'), now)} · {rec.get('branch', '')}")
    lines = [head,
             f"   📌 依据：{r.get('task', '?')}",
             f"      碰过模块：{'、'.join(mods) if mods else '(无根模块改动)'}",
             f"      判决：{r.get('verdict', '?')}"]
    mark = _LEVEL_MARK.get(ci.get("level", "none"), "⬜")
    cmods = ci.get("touched_contract_modules") or []
    lines.append(f"   {mark} 契约影响：" +
                 (f"动了立约模块 {'、'.join(cmods)} —— {ci.get('note', '')}"
                  if cmods else ci.get("note", "未触碰立约模块")))
    safe = "可安全退" if rb.get("safe") else "⚠️ 退路有代价"
    lines.append(f"   🪂 回滚点（{rb.get('where', '?')}，{safe}）：")
    lines.append(f"      $ {rb.get('command', '?')}")
    if rb.get("alt"):
        lines.append(f"      或： $ {rb['alt']}")
    if full and rb.get("why"):
        lines.append(f"      理由：{rb['why']}")
    return "\n".join(lines)


def _print_report(now: float, *, limit: int, full: bool) -> None:
    rows = recent(limit)
    if not rows:
        print("🧾🖐️  补丁说明账本还空着——等手真动过几爪，这里才长得出可审的解释。")
        return
    print(f"🧾🖐️  自生手补丁可解释层（最近 {len(rows)} 爪）\n")
    for rec in reversed(rows):     # 最新在最上
        print(render(rec, now=now, full=full))
        print()


def manifest(*, limit: int = SHOW_DEFAULT) -> dict:
    """机读：最近若干条补丁说明。"""
    return {"notes": recent(limit)}


def _selfcheck() -> bool:
    """自检：本层关键路径不抛错(供 evidence 的 patchnote 声明当复跑命令)。

    distill 对各种结果形态都能正确判决三件事、渲染不崩——是「补丁可解释」这条能力
    还活着的最小证明。不读真账本、无副作用。
    """
    try:
        known = {"health", "jsonlstore"}   # 注入一组「立约模块」，让判定不依赖 contracts.py 现状
        # publish + 动了立约模块(health) → 高契约影响、退路须是 revert+push(有代价)
        rec = distill({
            "changed": True, "executor": "claude", "integrate": "publish",
            "ok": True, "branch": "crab/x", "base": "main",
            "task": "给 health 补一条诊断",
            "self_test": "自测通过：改完还能正常启动",
            "base_sha": "a" * 40, "merge_sha": "b" * 40,
            "diffstat": " health.py | 3 +-\n patchnote.py | 9 +++",
        }, now=1000.0, known_contracts=known)
        assert rec is not None
        assert set(rec["rationale"]["modules"]) == {"health", "patchnote"}
        assert rec["contract_impact"]["touched_contract_modules"] == ["health"]
        assert rec["contract_impact"]["level"] == "high"
        assert rec["rollback"]["mode"] == "revert-published"
        assert rec["rollback"]["safe"] is False
        assert "revert -m 1 bbbbbbbbb" in rec["rollback"]["command"]
        assert render(rec, now=1000.0, full=True)   # 渲染不崩

        # branch 模式：base 没动 → 退路是删分支、可安全退；碰过模块未立约则 low
        rec2 = distill({
            "changed": True, "executor": "codex", "integrate": "branch",
            "ok": True, "branch": "crab/y", "base": "main",
            "task": "试改 smoke", "base_sha": "c" * 40,
            "diffstat": " smoke.py | 2 +-",
        }, now=1000.0, known_contracts=known)
        assert rec2 and rec2["rollback"]["mode"] == "discard-branch"
        assert rec2["rollback"]["safe"] is True
        assert rec2["contract_impact"]["level"] == "low"  # smoke 未立约则 low

        # merge 模式：本地主干 → revert 合并提交、附带 reset 备选；无根模块则 none
        rec3 = distill({
            "changed": True, "executor": "claude", "integrate": "merge",
            "ok": True, "branch": "crab/z", "base": "main",
            "self_test": "x", "base_sha": "d" * 40, "merge_sha": "e" * 40,
            "diffstat": " README.md | 1 +",   # 非根 .py → 无根模块
        }, now=1000.0, known_contracts=known)
        assert rec3 and rec3["rollback"]["mode"] == "revert-local"
        assert rec3["rollback"].get("alt") and rec3["contract_impact"]["level"] == "none"

        # publish 但 push 失败：已并入本地、未公开 → 退路是 revert-local，绝不是删已删的分支
        rec4 = distill({
            "changed": True, "executor": "claude", "integrate": "publish",
            "ok": False, "branch": "crab/p", "base": "main",
            "self_test": "x", "base_sha": "f" * 40, "merge_sha": "0" * 40,
            "diffstat": " smoke.py | 1 +",
        }, now=1000.0, known_contracts=known)
        assert rec4 and rec4["rollback"]["mode"] == "revert-local"

        # 自测未过(healed)：免疫系统已自动回滚 → 无需再退
        rec5 = distill({
            "changed": True, "executor": "claude", "integrate": "merge",
            "ok": False, "branch": "crab/h", "base": "main",
            "self_test": "语法错误", "healed": True, "base_sha": "9" * 40,
            "diffstat": " smoke.py | 1 +",
        }, now=1000.0, known_contracts=known)
        assert rec5 and rec5["rollback"]["mode"] == "auto-healed"

        # 没改动 / 预演 → 不解释
        assert distill({"changed": False}) is None
        assert distill({"changed": True, "dry_run": True}) is None

        # recent 折叠不崩
        assert len(recent(2, rows=[rec, rec2, rec3])) == 2
        return True
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手补丁可解释层 🧾🖐️")
    ap.add_argument("--last", action="store_true", help="只看最近一爪的完整说明")
    ap.add_argument("-n", "--num", type=int, default=SHOW_DEFAULT,
                    help=f"列最近 N 爪(默认 {SHOW_DEFAULT})")
    ap.add_argument("--json", action="store_true", help="机读：最近若干条解释记录")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检关键路径不抛错(供 evidence 的 patchnote 声明复跑)")
    ap.add_argument("--quiet", action="store_true", help="自检静默：只用退出码说话")
    args = ap.parse_args(argv)
    now = time.time()

    if args.selfcheck:
        ok = _selfcheck()
        if not args.quiet:
            print("🧾🖐️  自检" + ("通过：补丁解释关键路径都还稳。"
                                   if ok else "失败：解释路径出问题了。"))
        sys.exit(0 if ok else 1)

    if args.json:
        print(json.dumps(manifest(limit=args.num), ensure_ascii=False, indent=2))
        return

    if args.last:
        rows = recent(1)
        if not rows:
            print("🧾🖐️  还没有可解释的一爪。")
        else:
            print(render(rows[-1], now=now, full=True))
        return

    _print_report(now, limit=args.num, full=False)


if __name__ == "__main__":
    main()
