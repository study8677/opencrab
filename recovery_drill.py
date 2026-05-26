#!/usr/bin/env python3
"""opencrab 灾后续航演练 🪂🔒

把三件退路工具串成**一场演练**，回答一个问题：摔倒之后，我能自己爬回主线、
并留下能复盘的证据吗？

- 账本损坏腿(ledgerseal)：在临时目录里造一本带哈希链的账本，封印基准后分别
  「改中间一行」「删尾一行」，断言 ledgerseal 都认得出 → 证明篡改瞒不过封印。
- 半截自改腿(rollback)：拿最新快照(没有就现存一个)做恢复演练——在临时克隆里
  造一个搅乱提交模拟「自改把状态推到别处」，跑回滚脚本，断言 HEAD 真退回快照。

全程只在临时目录 / 临时克隆里动手，**绝不碰真账本与工作区**——演练不能成为新故障源。
每条腿的结论都追加进 state/recovery_drill.jsonl，供事后复盘。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import tempfile
import time

import ledgerseal
import rollback
import jsonlstore

DRILL_LOG = rollback.STATE_DIR / "recovery_drill.jsonl"


@dataclasses.dataclass(frozen=True)
class Leg:
    """演练一条腿的结论。"""
    name: str
    ok: bool
    detail: str

    def to_meta(self) -> dict:
        return {"leg": self.name, "ok": self.ok, "detail": self.detail}


def _seal_of(lines: list[str]) -> dict:
    """按 ledgerseal 的格式，给一组行立一个封印基准。"""
    return {"count": len(lines), "head": ledgerseal.chain_head(lines)}


def drill_ledger() -> Leg:
    """账本损坏腿：封印一本临时账本，再分别篡改 / 删尾，断言都被认出。"""
    try:
        with tempfile.TemporaryDirectory() as d:
            book = pathlib.Path(d) / "audit.jsonl"
            rows = [json.dumps({"i": i, "ev": f"step-{i}"},
                               ensure_ascii=False) for i in range(5)]
            book.write_text("\n".join(rows) + "\n", "utf-8")
            seals = {"audit": _seal_of(rows)}

            # 基准当下：必须判 intact。
            base = ledgerseal.verify_one("audit", book, seals)
            if base.state != ledgerseal.ST_INTACT:
                return Leg("ledger", False,
                           f"刚封印就判成 {base.state}，封印基准不可信")

            # 篡改中间一行 → 必须 TAMPER。
            tampered = rows[:2] + [json.dumps({"i": 2, "ev": "EVIL"})] + rows[3:]
            book.write_text("\n".join(tampered) + "\n", "utf-8")
            r_tamper = ledgerseal.verify_one("audit", book, seals)

            # 删掉尾行 → 必须 TRUNC。
            book.write_text("\n".join(rows[:3]) + "\n", "utf-8")
            r_trunc = ledgerseal.verify_one("audit", book, seals)

            if r_tamper.state != ledgerseal.ST_TAMPER:
                return Leg("ledger", False,
                           f"改了中间一行，却判成 {r_tamper.state}——篡改瞒过了封印")
            if r_trunc.state != ledgerseal.ST_TRUNC:
                return Leg("ledger", False,
                           f"删了尾行，却判成 {r_trunc.state}——截断瞒过了封印")
            return Leg("ledger", True,
                       "封印一本临时账本后，改中间一行被判 tamper、删尾被判 "
                       "truncated——账本损坏瞒不过封印。")
    except Exception as e:
        return Leg("ledger", False, f"{type(e).__name__}: {e}")


def drill_rollback() -> Leg:
    """半截自改腿：拿最新快照(没有就现存一个)做恢复演练。"""
    try:
        snaps = rollback.list_snapshots()
        if snaps:
            snap = snaps[-1]
            origin = f"复用最新快照 {snap.id}"
        else:
            snap = rollback.snapshot(label="recovery_drill 自存：演练半截自改恢复")
            origin = f"现存快照 {snap.id}"
        reh = rollback.rehearse(snap)
        return Leg("rollback", reh.ok, f"{origin}；{reh.detail}")
    except Exception as e:
        return Leg("rollback", False, f"{type(e).__name__}: {e}")


def run() -> list[Leg]:
    return [drill_ledger(), drill_rollback()]


def _record(legs: list[Leg]) -> None:
    """把整场演练的结论追加进流水账(写盘失败被吞，绝不反噬)。"""
    try:
        jsonlstore.append_jsonl(DRILL_LOG, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "recovery_drill",
            "ok": all(l.ok for l in legs),
            "legs": [l.to_meta() for l in legs],
        })
    except Exception:
        pass


def _print(legs: list[Leg]) -> None:
    print("🪂🔒 opencrab 灾后续航演练\n")
    for l in legs:
        print(f"  {'✅' if l.ok else '❌'} {l.name}：{l.detail}")
    print()
    if all(l.ok for l in legs):
        print("🪂 守约：账本损坏认得出、半截自改退得回——摔倒了能自己爬回主线。")
    else:
        print("⚠️  续航演练有腿没跑通，先把退路修好再大胆蜕壳——没退路别乱自改。")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 灾后续航演练 🪂🔒")
    ap.add_argument("--json", action="store_true", help="导出机读演练报告")
    args = ap.parse_args(argv)

    legs = run()
    _record(legs)
    if args.json:
        print(json.dumps({"ok": all(l.ok for l in legs),
                          "legs": [l.to_meta() for l in legs]},
                         ensure_ascii=False, indent=2))
    else:
        _print(legs)
    sys.exit(0 if all(l.ok for l in legs) else 1)


if __name__ == "__main__":
    main()
