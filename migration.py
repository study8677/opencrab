#!/usr/bin/env python3
"""迁移账本 🪜 —— 给各类 JSONL 账本一个**显式的版本号**与一架**版本→版本的迁移梯子**,
让旧证据不会随格式演化悄悄失效:格式变了,老记录也能被一步步抬到今天的形状来读。

为什么要有它:领地里十几本账本(校准 calibration、不确定 uncertainty、证据 evidence、
情境记忆 episodes、审计 audit……)都是一行一条 JSON 追着写的。今天它们**没有一条带版本号**——
字段就是当下代码默认的样子。可格式一定会变:某天我给校准账本加一个 `gain` 字段、给证据账本
换一种 `kind` 命名。那一刻,**所有旧行都成了「上个格式」的化石**:新代码按新字段去读,旧行
要么缺字段、要么字段含义已变,于是要么读崩、要么被静默误解——长期可读的记忆,就这样断了。

记忆能长期可读,进化才有连续性。所以格式演化不能靠「改读取代码时顺手兼容一下」的口头约定,
得有一架明面上的梯子:

  · 每条记录带一个版本号 `_v`(没有这个字段 → 当作最早的 v1,这是历史事实,不是错误);
  · 每本账本登记它**当前**的版本号,和一串 **vN→vN+1 的迁移函数**(纯函数:旧 dict 进、
    新 dict 出,顺手把 `_v` 抬一级);
  · 读旧行时,沿梯子一级级往上爬,直到它长成当前格式——**一条 v1 的老记录,自动被抬成 v3**。

`migration.py`(裸跑)扫遍 `state/` 下所有 JSONL,报每本账本的**版本分布**与**兼容性**:
哪些行已是当前版、哪些是能被抬上来的旧版、哪些是**来自未来**(版本号比本机代码还高,抬不动——
多半是别的分支写的,得先升级代码)。`check <路径>` 只验一本。`migrate <路径>` 真正把一本账本
里的旧行**就地抬到当前版**(原文件先备份成 `.bak`,绝不毁掉原始证据)。`--stamp` 是最轻的一步:
给那些还没版本号的老行补上 `_v`,**不改任何字段**——只是给「这是 v1」这件历史事实钉一个锚,
将来真要迁移时才有明确的起点。

今天梯子大多只有一级(current=1,没有真实的转换步骤)——这是诚实的现状:格式还没变过。
本层是**先把脚手架搭好**:等哪天真改了某本账本的字段,只需在这里登记一个 vN→vN+1 的函数,
所有历史证据立刻能被自动抬上来,而不必在十几处读取代码里东打一个补丁、西打一个补丁。

用法:
    python migration.py                      # 扫 state/ 下所有 JSONL:版本分布 + 兼容性
    python migration.py list                 # 列已登记的账本:当前版本 / 梯子有几级
    python migration.py check state/calibration.jsonl     # 只验一本账本的兼容性
    python migration.py migrate state/calibration.jsonl   # 就地把旧行抬到当前版(先备份 .bak)
    python migration.py migrate <路径> --stamp            # 最轻:只给无版本号的老行补 `_v`,不改字段
    python migration.py migrate <路径> --dry-run          # 只演示会改多少行,不落盘
    python migration.py --json               # 机读:全部账本的版本分布与兼容性

零第三方依赖,纯标准库。账本是观测者:读不到当空、写盘失败被吞、迁移先备份;
看不懂的「未来版本」绝不强行改写——宁可报一句「我读不懂,先去升级代码」,也不毁坏原始证据。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import shutil
import sys
from collections import Counter
from typing import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import read_jsonl  # noqa: E402  —— 复用领地统一的 JSONL 读取(坏行/缺失都安全)

STATE_DIR = REPO_ROOT / "state"

# 记录里标记版本的字段名。没有这个字段的老行 → 当作 v1(历史事实,不是脏数据)。
VERSION_KEY = "_v"
BASE_VERSION = 1

# 一级迁移步骤:旧 dict 进、新 dict 出。约定它**不就地改**入参,返回的新 dict
# 不必自己写 `_v`——爬梯子时由本层统一盖上目标版本号(见 `_climb`)。
Step = Callable[[dict], dict]


@dataclasses.dataclass(frozen=True)
class Schema:
    """一本账本的版本契约:当前是第几版,以及从 v1 往上每一级的迁移函数。

    `steps[i]` 把 v(i+1) 抬成 v(i+2)。因此 current 必然等于 len(steps)+1——
    构造时强校验,免得登记错位(梯子级数和版本号对不上)。
    """
    name: str                      # 逻辑账本名(给人看 / 给 SCHEMAS 当键)
    steps: tuple[Step, ...] = ()   # vN→vN+1 的迁移函数,按版本顺序排

    @property
    def current(self) -> int:
        return BASE_VERSION + len(self.steps)

    def step_from(self, v: int) -> Step:
        """取「把 vN 抬成 vN+1」的那一级函数(v 必在 [1, current) 内,调用方先保证)。"""
        return self.steps[v - BASE_VERSION]


# ── 账本登记处 ────────────────────────────────────────────────────────────
# 每本账本登记它的迁移梯子。今天都只有 current=1(没有真实转换)——格式还没变过,
# 这是诚实的现状。将来真改了某本的字段,就在这里给它的 steps 追加一个 vN→vN+1 函数,
# 所有历史证据立刻能被自动抬上来。键是「逻辑账本名」,由文件路径推出(见 `schema_for`)。
#
# 举例(等真要迁移时,形如):
#     "calibration": Schema("calibration", steps=(
#         lambda r: {**r, "gain": 0.0},   # v1→v2:补默认 gain 字段
#     )),
SCHEMAS: dict[str, Schema] = {
    "calibration": Schema("calibration"),
    "uncertainty": Schema("uncertainty"),
    "counterfactual": Schema("counterfactual"),
    "friction": Schema("friction"),
    "intake": Schema("intake"),
    "intake_inbox": Schema("intake_inbox"),
    "evidence": Schema("evidence"),       # state/evidence/ledger.jsonl
    "episodes": Schema("episodes"),       # state/memory/episodes.jsonl
    "audit": Schema("audit"),             # state/audit/*.jsonl(按日分文件)
}

# 没登记过的账本一律给一个 current=1 的默认契约:兼容性照样能查,只是没有可走的梯子。
_DEFAULT = Schema("(未登记)")


def schema_for(path: pathlib.Path) -> Schema:
    """由文件路径推出它该用哪本账本的迁移契约。

    规则尽量贴合领地里的实际命名:`state/<name>.jsonl` 用 `<name>`;
    `state/evidence/ledger.jsonl` 归到 `evidence`;`state/memory/episodes.jsonl` 归到
    `episodes`;`state/audit/<日期>.jsonl` 不论哪天都归到 `audit`。认不出 → 默认契约。
    """
    stem = path.stem
    parent = path.parent.name
    if parent == "evidence":
        return SCHEMAS.get("evidence", _DEFAULT)
    if parent == "memory":
        return SCHEMAS.get(stem, _DEFAULT)
    if parent == "audit":
        return SCHEMAS.get("audit", _DEFAULT)
    return SCHEMAS.get(stem, _DEFAULT)


def record_version(rec: dict) -> int:
    """读一条记录的版本号;没有 `_v` 字段 → BASE_VERSION(老行的历史事实)。

    版本号非法(负数 / 非整数)也兜底成 BASE_VERSION——宁可当最老的来对待、走一遍梯子,
    也不凭一个坏值就判它「来自未来」而拒读。
    """
    raw = rec.get(VERSION_KEY, BASE_VERSION)
    try:
        v = int(raw)
        return v if v >= BASE_VERSION else BASE_VERSION
    except (TypeError, ValueError):
        return BASE_VERSION


# ── 爬梯子:把一条旧记录抬到当前版 ─────────────────────────────────────────
def _climb(rec: dict, schema: Schema) -> tuple[dict, int]:
    """把一条记录沿梯子抬到当前版,返回 (新记录, 实际走了几级)。

    已是当前版 → 原样返回(0 级)。来自未来(版本 > current) → 抬不动,**原样返回**
    (由调用方据版本号识别并另行报警,这里绝不强行改写未来格式)。
    每抬一级,统一把 `_v` 盖成目标版本号——迁移函数自己不必操心版本字段。
    """
    v = record_version(rec)
    if v >= schema.current:
        return rec, 0
    cur = rec
    climbed = 0
    while v < schema.current:
        cur = {**schema.step_from(v)(cur), VERSION_KEY: v + 1}
        v += 1
        climbed += 1
    return cur, climbed


def migrate_record(rec: dict, schema: Schema) -> tuple[dict, int]:
    """对外的单条迁移入口(等同 `_climb`,留个稳定名字给别的模块复用)。"""
    return _climb(rec, schema)


# ── 兼容性报告 ────────────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Report:
    """一本账本的兼容性体检:版本分布、要抬几行、有没有读不懂的未来行。"""
    path: pathlib.Path
    schema: Schema
    total: int                 # 总记录数(坏行已被 read_jsonl 跳过,不计入)
    dist: dict[int, int]       # 版本号 → 行数
    outdated: int              # 低于当前版、能被抬上来的行数
    from_future: int           # 版本号 > 当前版、抬不动的行数(得先升级代码)
    unstamped: int             # 没有 `_v` 字段的老行数(== dist 里 v1 中无显式版本的部分)

    @property
    def current(self) -> int:
        return self.schema.current

    @property
    def ok(self) -> bool:
        """兼容 == 没有任何「来自未来」的行(旧行能抬,不算不兼容)。"""
        return self.from_future == 0

    def to_meta(self) -> dict:
        return {
            "path": str(self.path.relative_to(REPO_ROOT)) if self.path.is_relative_to(REPO_ROOT)
                    else str(self.path),
            "schema": self.schema.name,
            "current_version": self.current,
            "total": self.total,
            "version_dist": {str(k): v for k, v in sorted(self.dist.items())},
            "outdated": self.outdated,
            "from_future": self.from_future,
            "unstamped": self.unstamped,
            "ok": self.ok,
        }


def check_file(path: pathlib.Path) -> Report:
    """读一本账本,统计版本分布与兼容性(纯只读,绝不动文件)。"""
    schema = schema_for(path)
    records = read_jsonl(path)
    dist: Counter[int] = Counter()
    outdated = from_future = unstamped = 0
    for rec in records:
        v = record_version(rec)
        dist[v] += 1
        if VERSION_KEY not in rec:
            unstamped += 1
        if v < schema.current:
            outdated += 1
        elif v > schema.current:
            from_future += 1
    return Report(
        path=path, schema=schema, total=len(records), dist=dict(dist),
        outdated=outdated, from_future=from_future, unstamped=unstamped,
    )


def discover_ledgers() -> list[pathlib.Path]:
    """找出 state/ 下所有 JSONL 账本(按路径排序,稳定可复现)。"""
    if not STATE_DIR.exists():
        return []
    return sorted(STATE_DIR.rglob("*.jsonl"))


# ── 真正迁移:就地把旧行抬到当前版(先备份) ──────────────────────────────────
@dataclasses.dataclass(frozen=True)
class MigrateResult:
    """一次迁移的结果:抬了几行、补了几个版本号、有没有抬不动的未来行、是否落盘。"""
    path: pathlib.Path
    climbed: int            # 真正沿梯子抬过的行数
    stamped: int            # 仅补了 `_v` 的行数(--stamp 模式 / 抬级时也会顺带盖上)
    from_future: int        # 抬不动、原样保留的未来行数
    total: int
    wrote: bool             # 是否真的写回了文件
    backup: pathlib.Path | None  # 备份文件路径(.bak),没写则为 None

    def to_meta(self) -> dict:
        return {
            "path": str(self.path),
            "climbed": self.climbed, "stamped": self.stamped,
            "from_future": self.from_future, "total": self.total,
            "wrote": self.wrote,
            "backup": str(self.backup) if self.backup else None,
        }


def migrate_file(path: pathlib.Path, *, stamp_only: bool = False,
                 dry_run: bool = False) -> MigrateResult:
    """把一本账本里的旧行抬到当前版,整本重写回去(原文件先备份成 `.bak`)。

    · stamp_only=True:不爬梯子,只给没有 `_v` 的老行补上 BASE_VERSION——一字不改字段,
      只钉一个版本锚(将来迁移的起点)。
    · 来自未来的行:抬不动,原样保留并计数(不是错误,是提醒「该升级代码了」)。
    · dry_run=True:全程不落盘,只算「会改多少行」,返回 wrote=False。
    · 没有任何行需要改 → 不写、不备份(避免凭空生成 .bak 噪音)。
    写盘失败被吞:返回 wrote=False,原文件原封不动——账本是观测者,迁移失败绝不反噬生命。
    """
    schema = schema_for(path)
    records = read_jsonl(path)
    out: list[dict] = []
    climbed = stamped = from_future = 0
    for rec in records:
        v = record_version(rec)
        if v > schema.current:
            from_future += 1
            out.append(rec)
            continue
        if stamp_only:
            if VERSION_KEY not in rec:
                out.append({**rec, VERSION_KEY: BASE_VERSION})
                stamped += 1
            else:
                out.append(rec)
            continue
        new_rec, steps = _climb(rec, schema)
        if steps:
            climbed += 1
        elif VERSION_KEY not in rec:
            # 已是当前版但没盖版本号(current==1 的常态):顺手补上锚。
            new_rec = {**rec, VERSION_KEY: v}
            stamped += 1
        out.append(new_rec)

    changed = climbed + stamped
    if changed == 0 or dry_run:
        return MigrateResult(path=path, climbed=climbed, stamped=stamped,
                             from_future=from_future, total=len(records),
                             wrote=False, backup=None)

    backup = path.with_suffix(path.suffix + ".bak")
    try:
        if path.exists():
            shutil.copy2(path, backup)
        body = "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out)
        path.write_text(body, encoding="utf-8")
        return MigrateResult(path=path, climbed=climbed, stamped=stamped,
                             from_future=from_future, total=len(records),
                             wrote=True, backup=backup)
    except Exception:
        # 写盘出错:原文件未动(write_text 是最后一步;备份若已生成则留着无害)。
        return MigrateResult(path=path, climbed=climbed, stamped=stamped,
                             from_future=from_future, total=len(records),
                             wrote=False, backup=None)


# ── 展示 ──────────────────────────────────────────────────────────────────
def _fmt_dist(dist: dict[int, int]) -> str:
    if not dist:
        return "(空)"
    return "  ".join(f"v{v}×{n}" for v, n in sorted(dist.items()))


def _print_report(r: Report, *, indent: str = "") -> None:
    rel = r.path.relative_to(REPO_ROOT) if r.path.is_relative_to(REPO_ROOT) else r.path
    flag = "✅" if r.ok else "⚠️"
    print(f"{indent}{flag} {rel}  「{r.schema.name}」当前 v{r.current}  共 {r.total} 行")
    print(f"{indent}    版本分布:{_fmt_dist(r.dist)}")
    bits = []
    if r.outdated:
        bits.append(f"{r.outdated} 行可抬到 v{r.current}")
    if r.unstamped:
        bits.append(f"{r.unstamped} 行还没版本号(可 `--stamp` 钉锚)")
    if r.from_future:
        bits.append(f"⚠️ {r.from_future} 行来自未来(v>{r.current},得先升级代码才读得懂)")
    if bits:
        print(f"{indent}    " + " / ".join(bits))


def _print_scan() -> None:
    ledgers = discover_ledgers()
    if not ledgers:
        print("🪜 state/ 下还没有任何 JSONL 账本——领地刚开张,等账本写起来再回头查兼容性。")
        return
    reports = [check_file(p) for p in ledgers]
    n_future = sum(r.from_future for r in reports)
    n_outdated = sum(r.outdated for r in reports)
    n_unstamped = sum(r.unstamped for r in reports)
    print(f"🪜 opencrab 迁移账本——扫了 {len(reports)} 本 JSONL\n")
    for r in reports:
        _print_report(r, indent="  ")
        print()
    if n_future:
        print(f"⚠️ 有 {n_future} 行来自未来版本——本机代码读不懂,先升级代码再说,别强行迁移。")
    if n_outdated:
        print(f"🪜 有 {n_outdated} 行可被抬到当前版:`migration.py migrate <路径>`(会先备份 .bak)。")
    if n_unstamped:
        print(f"🔖 有 {n_unstamped} 行还没显式版本号——`migrate <路径> --stamp` 只钉锚、不改字段。")
    if not (n_future or n_outdated or n_unstamped):
        print("✅ 所有账本都已是当前格式且带版本锚——记忆长期可读,进化有连续性。")


def _print_list() -> None:
    print("🪜 已登记的账本迁移契约(梯子级数 == 当前版本 − 1)\n")
    for name, sc in sorted(SCHEMAS.items()):
        rungs = len(sc.steps)
        tail = "无真实转换(格式还没变过)" if rungs == 0 else f"{rungs} 级 vN→vN+1 迁移"
        print(f"  · {name:<14} 当前 v{sc.current}  —— {tail}")
    print("\n  将来某本账本真改了字段,就在 SCHEMAS 里给它的 steps 追加一个迁移函数——")
    print("  所有历史证据立刻能被自动抬到新格式,不必在十几处读取代码里东补一块西补一块。")


def _print_migrate(res: MigrateResult, *, dry_run: bool) -> None:
    rel = res.path.relative_to(REPO_ROOT) if res.path.is_relative_to(REPO_ROOT) else res.path
    if res.climbed == 0 and res.stamped == 0:
        msg = "已是当前格式且带版本锚,无需迁移" if res.from_future == 0 else "可迁移的行为 0"
        print(f"🪜 {rel}:{msg}。")
        if res.from_future:
            print(f"   ⚠️ 另有 {res.from_future} 行来自未来,原样保留——先升级代码。")
        return
    did = []
    if res.climbed:
        did.append(f"{res.climbed} 行抬到当前版")
    if res.stamped:
        did.append(f"{res.stamped} 行补版本锚")
    summary = " / ".join(did)
    if dry_run:
        print(f"🪜 [演示] {rel}:将会 {summary}(未落盘,加 --dry-run 之外的命令才真改)。")
    elif res.wrote:
        print(f"🪜 {rel}:已 {summary}。原文件已备份 → {res.backup.name}")
    else:
        print(f"⚠️ {rel}:迁移未落盘(写盘失败已吞),原文件原封不动——生命照常。")
    if res.from_future:
        print(f"   ⚠️ 另有 {res.from_future} 行来自未来(抬不动),原样保留——先升级代码。")


def manifest() -> dict:
    """导出机读:全部账本的版本分布与兼容性 + 已登记契约。"""
    reports = [check_file(p) for p in discover_ledgers()]
    return {
        "ledgers": [r.to_meta() for r in reports],
        "schemas": {n: {"current": s.current, "rungs": len(s.steps)}
                    for n, s in sorted(SCHEMAS.items())},
        "any_from_future": any(r.from_future for r in reports),
        "total_outdated": sum(r.outdated for r in reports),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 迁移账本 🪜")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列已登记的账本契约:当前版本 / 梯子级数")

    p_check = sub.add_parser("check", help="只验一本账本的版本分布与兼容性(只读)")
    p_check.add_argument("path", help="账本路径(如 state/calibration.jsonl)")

    p_mig = sub.add_parser("migrate", help="就地把一本账本的旧行抬到当前版(先备份 .bak)")
    p_mig.add_argument("path", help="账本路径")
    p_mig.add_argument("--stamp", action="store_true",
                       help="最轻:只给无版本号的老行补 `_v`,不改任何字段")
    p_mig.add_argument("--dry-run", action="store_true", help="只演示会改多少行,不落盘")

    ap.add_argument("--json", action="store_true",
                    help="机读:全部账本的版本分布与兼容性")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        sys.exit(0)

    if args.cmd == "list":
        _print_list()
        return

    if args.cmd == "check":
        path = pathlib.Path(args.path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.exists():
            print(f"⚠️  账本不存在:{args.path}（读不到就当空,没什么可查的)。")
            sys.exit(2)
        r = check_file(path)
        _print_report(r)
        sys.exit(0 if r.ok else 1)

    if args.cmd == "migrate":
        path = pathlib.Path(args.path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.exists():
            print(f"⚠️  账本不存在:{args.path}（没东西可迁移)。")
            sys.exit(2)
        res = migrate_file(path, stamp_only=args.stamp, dry_run=args.dry_run)
        _print_migrate(res, dry_run=args.dry_run)
        sys.exit(0)

    _print_scan()


if __name__ == "__main__":
    main()
