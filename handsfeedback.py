#!/usr/bin/env python3
"""自生手证据回灌 🔁🖐️ —— 把每次亲手改代码后的自测结果，自动喂回证据账本与能力图谱。

为什么要有它：`hands.py` 已经会动手改代码、改完先自测「还能不能正常启动」，通过才合并、
不过就断肢再生。可那次自测的判决，**用完就扔了**——它救了这一次的命，却没沉淀成证据：
  · 我没法回答「`claude` 这只手出的改动，到底多大概率一次过自测」「`codex` 那只手呢」；
  · 能力图谱(`skillgraph`)只从源码静态看「某模块有没有被回归/烟雾点过名」，却看不见
    「这个模块刚被我亲手改过、且改完自测真跑通了」这种**最新鲜的实证**；
  · 信任分(`trustscore`)能把证据折叠成连续可信度，但账本里压根没有「手」这条能力的流水。

本层就是那条回灌的管子：`hands.use_hands` 每跑完一次，把结果交给 `feed()`，它做两件事——

  1) **喂信任分**：往 `evidence` 账本追加一条 name=`hands` 的验证记录(ok=这次自测过没过)，
     于是 `trustscore` 能像对待其它能力一样，给「自生手」算出新鲜度×可复现×覆盖面的信任分。
  2) **喂能力图谱**：把这次动手**碰过哪些模块、自测过没过**记进本层自己的回灌账本，
     `skillgraph` 据此给「最近被亲手改过且自测跑通」的模块亮一枚「亲验」证据。

再把回灌账本按「手」(执行器)折叠成一张**可靠度**表：每只手动了多少次、改动率多少、
自测通过率多少、综合一个 0~1 的可靠分——这样就知道**哪只手真正可靠**。

账本落在被 .gitignore 的 state/ 里，写盘失败绝不反噬生命；喂账本是副产物，
出任何错都被吞掉，绝不拖垮 hands 的动手主流程。零第三方依赖，纯标准库。

用法：
    python handsfeedback.py            # 看每只手的可靠度 + 最近亲验过的模块
    python handsfeedback.py --modules  # 只看最近被亲手改过且自测跑通的模块
    python handsfeedback.py --json     # 机读：每只手的可靠度 + 亲验模块
    python handsfeedback.py --selfcheck --quiet   # 自检(供 evidence 的 hands 声明复跑)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402  —— 复用「读一批 / 追一条」的安全落地层

LEDGER_PATH = REPO_ROOT / "state" / "handsfeedback" / "ledger.jsonl"

# 与 evidence/trustscore 对齐：账本里「自生手」这条能力的主键。
CLAIM_NAME = "hands"

TRAIL_DAYS = 30.0       # 折叠可靠度/亲验只看最近这么多天(更早的手艺与今天无关)
PROVEN_DAYS = 14.0      # 「亲验」的保鲜期：超过这么多天没再亲手验过，就不再算新鲜实证
TRUST_OK = 0.70         # 🟢可靠下限(与 trustscore 一致)
TRUST_DOUBT = 0.40      # 🟡存疑下限(低于此 = 🔴不可靠)


# ── 从 hands 的结果里提炼一条可回灌的记录 ──────────────────────────────
def _touched_modules(diffstat: str) -> list[str]:
    """从 git diff --stat 文案里挑出本次碰过的、领地根目录的 *.py 模块名(stem)。

    diffstat 形如 ` skills/x.md | 6 ++++++` / ` compass.py | 3 +-`，取 `|` 前的路径，
    只认根目录下的 .py(带 / 的是子目录文件，不算根模块)。
    """
    mods: list[str] = []
    for line in (diffstat or "").splitlines():
        path = line.split("|", 1)[0].strip()
        if not path or "=>" in path:   # 跳过小结行与重命名箭头
            continue
        if "/" in path or not path.endswith(".py"):
            continue
        stem = path[:-3]
        if stem and stem not in mods:
            mods.append(stem)
    return mods


def distill(result: dict, *, now: float | None = None) -> dict | None:
    """把一次 use_hands 的结果提炼成回灌记录；不该回灌的返回 None。

    只回灌「真动了手」的那几次——没改动 / 预演 / 没找到爪子，都没有可沉淀的证据。
    self_tested 表示这次跑没跑过自测(branch 模式不自测)；passed 是自测判决
    (hands 在自测没过时会置 healed=True 并回滚，据此判定)。
    """
    if not isinstance(result, dict) or result.get("dry_run"):
        return None
    if not result.get("changed"):
        return None
    self_tested = "self_test" in result
    passed = self_tested and not result.get("healed", False)
    return {
        "ts": time.time() if now is None else now,
        "executor": str(result.get("executor") or "?"),
        "integrate": str(result.get("integrate") or "?"),
        "branch": str(result.get("branch") or ""),
        "self_tested": self_tested,
        "passed": bool(passed),                       # 自测判决(没自测则 False)
        "merged": bool(result.get("ok") and result.get("integrate") != "branch"),
        "modules": _touched_modules(result.get("diffstat", "")),
    }


def feed(result: dict) -> dict | None:
    """回灌入口：把一次 use_hands 结果同时喂给本层账本与 evidence 信任分。

    返回落下的那条记录(没可回灌的返回 None)。全程尽力而为：任何异常都被吞掉，
    绝不反噬 hands 的动手主流程。
    """
    try:
        rec = distill(result)
        if rec is None:
            return None
        jsonlstore.append_jsonl(LEDGER_PATH, rec)
        # 自测过没过 → 喂进 evidence 账本，让 trustscore 给「自生手」算信任分。
        # 只有真跑了自测(self_tested)才喂：branch 模式没判决，喂了是噪声。
        if rec["self_tested"]:
            try:
                import evidence  # 延迟导入：回灌不强依赖证据层在场
                evidence.record({
                    "name": CLAIM_NAME, "ok": rec["passed"], "ts": rec["ts"],
                    "detail": "" if rec["passed"] else f"自生手自测未过({rec['executor']})",
                    "argv": ["<hands self-test>"],
                })
            except Exception:  # noqa: BLE001
                pass
        return rec
    except Exception:  # noqa: BLE001 —— 回灌是副产物，出错绝不拖垮动手
        return None


# ── 折叠：账本 → 每只手的可靠度 ────────────────────────────────────────
def _recent(rows: list[dict], *, now: float, days: float) -> list[dict]:
    return [r for r in rows
            if isinstance(r.get("ts"), (int, float)) and (now - r["ts"]) / 86400.0 <= days]


def _band(score: float) -> str:
    if score >= TRUST_OK:
        return "trusted"
    if score >= TRUST_DOUBT:
        return "doubt"
    return "untrusted"


def reliability(rows: list[dict] | None = None, *, now: float | None = None) -> list[dict]:
    """把回灌账本按「手」(执行器)折叠成可靠度：动了几次、改动率、自测通过率、综合可靠分。

    可靠分 = 自测通过率 × 样本折扣(1-0.5^n，逼着「多验几次才算可靠」)。只在跑过自测的
    那几次上算通过率——branch 模式没判决，不该拉高也不该拖低。按可靠分降序排。
    """
    now = time.time() if now is None else now
    rows = jsonlstore.read_jsonl(LEDGER_PATH) if rows is None else rows
    rows = _recent(rows, now=now, days=TRAIL_DAYS)
    by_hand: dict[str, list[dict]] = {}
    for r in rows:
        by_hand.setdefault(str(r.get("executor") or "?"), []).append(r)

    out = []
    for hand, recs in by_hand.items():
        attempts = len(recs)
        tested = [r for r in recs if r.get("self_tested")]
        n = len(tested)
        passes = sum(1 for r in tested if r.get("passed"))
        merged = sum(1 for r in recs if r.get("merged"))
        pass_rate = passes / n if n else 0.0
        sample_factor = 1.0 - 0.5 ** n if n else 0.0
        score = pass_rate * sample_factor
        out.append({
            "hand": hand, "attempts": attempts, "self_tested": n,
            "passed": passes, "merged": merged,
            "pass_rate": round(pass_rate, 4), "score": round(score, 4),
            "band": _band(score),
        })
    out.sort(key=lambda d: (-d["score"], d["hand"]))
    return out


def proven_modules(rows: list[dict] | None = None, *, now: float | None = None) -> dict[str, dict]:
    """最近(PROVEN_DAYS 内)被亲手改过、且那次改动自测跑通的模块 → 实证小档。

    供 skillgraph 取用，给这些模块亮一枚「亲验」证据：不是静态看谁点过名，
    而是「我刚亲手动过它、改完还跑得通」的最新鲜实证。失败的那次不算亲验。
    """
    now = time.time() if now is None else now
    rows = jsonlstore.read_jsonl(LEDGER_PATH) if rows is None else rows
    rows = _recent(rows, now=now, days=PROVEN_DAYS)
    proven: dict[str, dict] = {}
    for r in rows:
        if not (r.get("self_tested") and r.get("passed")):
            continue
        ts = r.get("ts")
        for mod in r.get("modules") or []:
            cur = proven.get(mod)
            if cur is None or (isinstance(ts, (int, float)) and ts > cur["ts"]):
                proven[mod] = {"ts": ts, "hand": r.get("executor", "?"),
                               "branch": r.get("branch", "")}
    return proven


# ── 展示 ───────────────────────────────────────────────────────────────
_MARKS = {"trusted": "🟢", "doubt": "🟡", "untrusted": "🔴"}
_WORDS = {"trusted": "可靠", "doubt": "存疑", "untrusted": "不可靠"}


def _ago(ts, now: float) -> str:
    if not isinstance(ts, (int, float)):
        return "?"
    d = (now - ts) / 86400.0
    return f"{d:.1f} 天前" if d >= 1 else f"{d * 24:.1f} 小时前"


def _print_report(now: float) -> None:
    rel = reliability(now=now)
    print("🔁🖐️  自生手可靠度（按回灌的自测证据折叠）\n")
    if not rel:
        print("  （回灌账本还空着——等手真动过几次、自测过几回，这里才长得出可靠度。）")
    for d in rel:
        mark, word = _MARKS[d["band"]], _WORDS[d["band"]]
        print(f"  {mark} {d['hand']}（{word} {d['score']:.2f}）"
              f"—— 动手 {d['attempts']} 次 · 自测 {d['self_tested']} 次 · "
              f"通过 {d['passed']} · 合并 {d['merged']}")
        print(f"      自测通过率 {d['pass_rate']:.0%}")
    proven = proven_modules(now=now)
    if proven:
        print(f"\n  ✋ 最近亲验过的模块（{len(proven)} 个，{PROVEN_DAYS:g} 天内改过且自测跑通）：")
        for mod, info in sorted(proven.items()):
            print(f"      {mod}.py —— {info['hand']} 于 {_ago(info['ts'], now)}")
    else:
        print("\n  ✋ 最近没有亲手改过且自测跑通的模块。")


def manifest(*, now: float | None = None) -> dict:
    """机读：每只手的可靠度 + 最近亲验过的模块。"""
    now = time.time() if now is None else now
    return {"reliability": reliability(now=now),
            "proven_modules": proven_modules(now=now),
            "params": {"trail_days": TRAIL_DAYS, "proven_days": PROVEN_DAYS,
                       "trust_ok": TRUST_OK, "trust_doubt": TRUST_DOUBT}}


def _selfcheck() -> bool:
    """自检：本层关键路径不抛错(供 evidence 的 hands 声明当复跑命令)。

    distill 对各种结果形态都能正确判决、folding 不崩——是「自生手回灌」这条能力
    还活着的最小证明。不读真账本、无副作用。
    """
    try:
        # 改动+自测通过 → 应回灌、判 passed、且抽出模块
        r = distill({"changed": True, "executor": "claude", "integrate": "merge",
                     "self_test": "自测通过：改完还能正常启动",
                     "diffstat": " compass.py | 3 +-\n smoke.py | 2 +"}, now=1000.0)
        assert r and r["passed"] and set(r["modules"]) == {"compass", "smoke"}
        # 自测没过(healed) → 应回灌但判未过
        r2 = distill({"changed": True, "executor": "codex", "integrate": "publish",
                      "self_test": "语法错误", "healed": True}, now=1000.0)
        assert r2 and r2["self_tested"] and not r2["passed"]
        # 没改动 / 预演 → 不回灌
        assert distill({"changed": False}) is None
        assert distill({"changed": True, "dry_run": True}) is None
        # 折叠不崩，且通过率/可靠分可算
        rel = reliability(rows=[r, r, r2], now=1000.0)
        assert any(d["hand"] == "claude" and d["passed"] == 2 for d in rel)
        prov = proven_modules(rows=[r], now=1000.0)
        assert "compass" in prov and "smoke" in prov
        return True
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手证据回灌 🔁🖐️")
    ap.add_argument("--modules", action="store_true",
                    help="只看最近被亲手改过且自测跑通的模块")
    ap.add_argument("--json", action="store_true", help="机读：可靠度 + 亲验模块")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检关键路径不抛错(供 evidence 的 hands 声明复跑)")
    ap.add_argument("--quiet", action="store_true", help="自检静默：只用退出码说话")
    args = ap.parse_args(argv)
    now = time.time()

    if args.selfcheck:
        ok = _selfcheck()
        if not args.quiet:
            print("🔁🖐️  自检" + ("通过：回灌关键路径都还稳。" if ok else "失败：回灌路径出问题了。"))
        sys.exit(0 if ok else 1)

    if args.json:
        print(json.dumps(manifest(now=now), ensure_ascii=False, indent=2))
        return

    if args.modules:
        proven = proven_modules(now=now)
        if not proven:
            print("🔁🖐️  最近没有亲手改过且自测跑通的模块。")
        else:
            print(f"✋ 最近亲验过的模块（{len(proven)} 个）：")
            for mod, info in sorted(proven.items()):
                print(f"  {mod}.py —— {info['hand']} 于 {_ago(info['ts'], now)}")
        return

    _print_report(now)


if __name__ == "__main__":
    main()
