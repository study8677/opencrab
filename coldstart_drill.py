#!/usr/bin/env python3
"""opencrab 账本冷启动一致性演练 🧊🔒

回答一个问题：当我带着**一本来历不明的账本**重新醒来时，能不能各按其分地处置？

记忆与证据若不可信，自主进化就失去了根——所以每次冷启动，账本封印(ledgerseal)
都得在三种处境下各自做对一件事：

  · 🧊 空账本 → **自建**：从零没有任何基准时，`--seal` 能给(哪怕空的)账本立起一条
    可复算、可校验的哈希链基准——空账本也有确定的链头，不是「无从封印」。
  · ⏳ 旧基准 → **迁移**：基准是旧封印格式(_SEED 换代)时，认成「旧版本」而**不是**
    「篡改」，`--seal` 无需 `--force` 即可迁移重封到当前格式——正当换代不该被误报成伪。
  · 🔴 改过了 → **拒伪**：历史某行被改时判「篡改」、让退出码红，且非 `--force`
    **拒绝重封**——绝不把一次篡改在重封里悄悄洗白成「完好」。

判准：三态各得三种**互不相同**的判决(unsealed / stale / tamper)，自建与迁移让账本
重新可信、拒伪守住基准不被洗白。全程把 ledgerseal 的 STATE / SEAL_PATH 临时改指到
隔离临时目录，跑的是**真**的 seal()/verify() 管子，**绝不碰真账本与真基准**；跑完
原样还原。每场演练的结论追加进 state/coldstart_drill.jsonl，供事后复盘。

用法:
    python coldstart_drill.py            # 跑三态，逐态打印判决
    python coldstart_drill.py --quiet    # 只在有腿没跑通时说话(适合钩子 / CI)
    python coldstart_drill.py --json     # 机读演练报告
    python coldstart_drill.py --selfcheck # 自检：三态判决各得其位(供 evidence 回灌)

退出码：0 = 三态全做对；1 = 有腿没跑通。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import pathlib
import sys
import tempfile
import time

import ledgerseal
import jsonlstore

REPO_ROOT = pathlib.Path(__file__).resolve().parent
# 日志落在真 state/，与 ledgerseal.STATE 在演练中被临时改指无关。
DRILL_LOG = REPO_ROOT / "state" / "coldstart_drill.jsonl"

# 演练用的审计账本键(_targets 以文件名 stem 作键)。
_BOOK_KEY = "audit/coldstart-drill"
_OLD_VERSION = "opencrab-ledgerseal-v0"   # 一个「旧封印格式」的标记，触发 ⏳ 旧版本


@dataclasses.dataclass(frozen=True)
class Leg:
    """演练一条腿(一种冷启动处境)的结论。"""
    name: str
    ok: bool
    detail: str

    def to_meta(self) -> dict:
        return {"leg": self.name, "ok": self.ok, "detail": self.detail}


@contextlib.contextmanager
def _temp_state(d: pathlib.Path):
    """把 ledgerseal 的 STATE / SEAL_PATH 临时改指到隔离目录，跑完原样还原。

    seal()/verify()/_targets()/_load_seals 都在调用时按模块全局取这两个名字，
    故改指即可让真管子在临时目录里跑，绝不触碰真账本与真基准。
    """
    saved_state, saved_seal = ledgerseal.STATE, ledgerseal.SEAL_PATH
    ledgerseal.STATE = d
    ledgerseal.SEAL_PATH = d / "ledgerseal" / "seals.json"
    try:
        yield
    finally:
        ledgerseal.STATE = saved_state
        ledgerseal.SEAL_PATH = saved_seal


def _write_book(rows: list[str]) -> pathlib.Path:
    """在当前(临时)STATE 下写一本审计账本，返回其路径。"""
    book = ledgerseal.STATE / "audit" / "coldstart-drill.jsonl"
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(("\n".join(rows) + "\n") if rows else "", "utf-8")
    return book


def _report_for(key: str) -> ledgerseal.Report | None:
    """从一次 verify() 里挑出某本账本的体检报告。"""
    for r in ledgerseal.verify():
        if r.key == key:
            return r
    return None


def _sample_rows(n: int = 5) -> list[str]:
    return [json.dumps({"i": i, "ev": f"step-{i}"}, ensure_ascii=False) for i in range(n)]


def drill_empty_selfbuild() -> Leg:
    """🧊 空账本 → 自建：冷启动无基准时，`--seal` 给空账本立起可校验的基准。"""
    try:
        with tempfile.TemporaryDirectory() as d:
            with _temp_state(pathlib.Path(d)):
                _write_book([])   # 空账本：文件在、0 行

                before = _report_for(_BOOK_KEY)
                if before is None or before.state != ledgerseal.ST_UNSEALED:
                    return Leg("empty", False,
                               f"冷启动空账本本该判 unsealed(待自建)，实得 "
                               f"{before.state if before else '没找到这本账本'}")

                _reports, sealed = ledgerseal.seal()
                if _BOOK_KEY not in sealed:
                    return Leg("empty", False, "空账本没能被 `--seal` 自建出基准")
                if not ledgerseal.SEAL_PATH.exists():
                    return Leg("empty", False, "自建后没落下 seals.json 基准文件")

                after = _report_for(_BOOK_KEY)
                if after is None or after.state != ledgerseal.ST_INTACT or after.count != 0:
                    return Leg("empty", False,
                               f"自建后空账本本该判 intact(0 行可校验)，实得 "
                               f"{after.state if after else '没找到'}")
            return Leg("empty", True,
                       "冷启动无基准时判 unsealed，`--seal` 给空账本(0 行)自建出可复算的"
                       "哈希链基准、随即判 intact——空账本也有确定的根。")
    except Exception as e:  # noqa: BLE001
        return Leg("empty", False, f"{type(e).__name__}: {e}")


def drill_oldversion_migrate() -> Leg:
    """⏳ 旧基准 → 迁移：旧封印格式判 stale(非篡改)，`--seal` 免 force 迁移重封。"""
    try:
        with tempfile.TemporaryDirectory() as d:
            with _temp_state(pathlib.Path(d)):
                _write_book(_sample_rows())
                ledgerseal.seal()   # 先立当前版本基准

                # 把基准降级成「旧封印格式」：只改 version，账本内容一字未动。
                seals = ledgerseal._load_seals()
                if _BOOK_KEY not in seals:
                    return Leg("oldversion", False, "立基准后 seals.json 里没有这本账本")
                seals[_BOOK_KEY]["version"] = _OLD_VERSION
                ledgerseal._save_seals(seals)

                stale = _report_for(_BOOK_KEY)
                if stale is None or stale.state != ledgerseal.ST_STALE:
                    return Leg("oldversion", False,
                               f"旧封印格式本该判 stale(旧版本)，实得 "
                               f"{stale.state if stale else '没找到'}")
                if stale.alarm:
                    return Leg("oldversion", False,
                               "旧版本被当成断链报警了——正当换代不该惊动退出码")

                # 迁移：无需 --force 即可重封到当前格式。
                _reports, sealed = ledgerseal.seal()
                if _BOOK_KEY not in sealed:
                    return Leg("oldversion", False, "旧版本基准没能被 `--seal` 迁移重封")
                migrated = _report_for(_BOOK_KEY)
                if migrated is None or migrated.state != ledgerseal.ST_INTACT:
                    return Leg("oldversion", False,
                               f"迁移重封后本该判 intact，实得 "
                               f"{migrated.state if migrated else '没找到'}")
            return Leg("oldversion", True,
                       "账本未改、只是基准是旧封印格式时判 stale(非篡改、不报警)，"
                       "`--seal` 无需 --force 即迁移重封、随即判 intact——换代不被误报成伪。")
    except Exception as e:  # noqa: BLE001
        return Leg("oldversion", False, f"{type(e).__name__}: {e}")


def drill_corrupted_reject() -> Leg:
    """🔴 改过了 → 拒伪：篡改判 tamper、报警，且非 --force 拒绝重封洗白。"""
    try:
        with tempfile.TemporaryDirectory() as d:
            with _temp_state(pathlib.Path(d)):
                rows = _sample_rows()
                book = _write_book(rows)
                ledgerseal.seal()
                sealed_head = ledgerseal._load_seals()[_BOOK_KEY]["head"]

                # 篡改中间一行(行数不变 → 只能靠链头识破)。
                tampered = rows[:2] + [json.dumps({"i": 2, "ev": "EVIL"})] + rows[3:]
                book.write_text("\n".join(tampered) + "\n", "utf-8")

                rep = _report_for(_BOOK_KEY)
                if rep is None or rep.state != ledgerseal.ST_TAMPER or not rep.alarm:
                    return Leg("corrupted", False,
                               f"改了中间一行本该判 tamper 并报警，实得 "
                               f"{rep.state if rep else '没找到'}")

                # 拒伪：非 --force 不得重封，基准链头必须分毫不动。
                _reports, sealed = ledgerseal.seal(force=False)
                if _BOOK_KEY in sealed:
                    return Leg("corrupted", False,
                               "篡改的账本被无条件重封了——篡改被洗白成「完好」")
                if ledgerseal._load_seals()[_BOOK_KEY]["head"] != sealed_head:
                    return Leg("corrupted", False, "拒封时基准链头竟被改动")
                if (again := _report_for(_BOOK_KEY)) is None or again.state != ledgerseal.ST_TAMPER:
                    return Leg("corrupted", False, "拒封后篡改判决竟消失了")

                # 明示认账(--force)后才允许重封。
                _reports, forced = ledgerseal.seal(force=True)
                if _BOOK_KEY not in forced:
                    return Leg("corrupted", False, "--force 明示认账后仍拒绝重封")
            return Leg("corrupted", True,
                       "改了中间一行判 tamper 并报警；非 --force `--seal` 拒绝重封、"
                       "基准链头分毫不动(篡改洗不白)，唯 --force 明示认账才许重封。")
    except Exception as e:  # noqa: BLE001
        return Leg("corrupted", False, f"{type(e).__name__}: {e}")


def run() -> list[Leg]:
    return [drill_empty_selfbuild(), drill_oldversion_migrate(), drill_corrupted_reject()]


def _record(legs: list[Leg]) -> None:
    """把整场演练结论追加进流水账(写盘失败被吞，绝不反噬)。"""
    try:
        jsonlstore.append_jsonl(DRILL_LOG, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "coldstart_drill",
            "ok": all(l.ok for l in legs),
            "legs": [l.to_meta() for l in legs],
        })
    except Exception:
        pass


def _print(legs: list[Leg]) -> None:
    print("🧊🔒 opencrab 账本冷启动一致性演练\n")
    for l in legs:
        print(f"  {'✅' if l.ok else '❌'} {l.name}：{l.detail}")
    print()
    if all(l.ok for l in legs):
        print("🧊 守约：空账本自建得起、旧基准迁移得动、改过的拒伪不洗白——"
              "冷启动后我仍认得出自己的账。")
    else:
        print("⚠️  冷启动演练有腿没跑通：账本三态没各按其分处置，"
              "先把这条根修稳再大胆蜕壳——记忆与证据不可信，进化就失了根。")


def selfcheck(quiet: bool = False) -> bool:
    """自检：三态判决各得其位、且互不相同(供 evidence 回灌)。"""
    legs = run()
    failures = [f"{l.name}：{l.detail}" for l in legs if not l.ok]
    ok = not failures
    if not quiet:
        if ok:
            print("✅ coldstart_drill selfcheck：空账本自建、旧基准迁移、改过拒伪——"
                  "冷启动三态各得其位、互不相同。")
        else:
            print("❌ coldstart_drill selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 账本冷启动一致性演练 🧊🔒")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有腿没跑通时说话(适合钩子 / CI)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true", help="导出机读演练报告")
    g.add_argument("--selfcheck", action="store_true",
                   help="自检：三态判决各得其位(供 evidence 回灌)")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)

    legs = run()
    _record(legs)
    ok = all(l.ok for l in legs)
    if args.json:
        print(json.dumps({"ok": ok, "legs": [l.to_meta() for l in legs]},
                         ensure_ascii=False, indent=2))
    elif not (args.quiet and ok):
        _print(legs)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
