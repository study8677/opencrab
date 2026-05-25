#!/usr/bin/env python3
"""自改哨兵 🛰️🚨 —— 运行前钉住基线、运行后比对关键文件/指标/异常模式，主动喊「停手/回滚/复盘」。

为什么要有它：这套领地每天自改一个模块。`rollback.py` 备好了退路、`health.py` 在事后
把关——可它们都是**被动**的：要么我先想起来跑一遍，要么坏了才发现。真正的危险是**自改
失控而我浑然不觉**：误删了 `intent.py` 的红线、把半个仓库的模块清空了、一次改动横扫了
几十个文件、真相源(journal/state)被悄悄抹掉。等下次复盘才看见，往往已经 push 出去了。

哨兵把「主动盯梢」收成一条最短回路：

  · 🎯 **布哨(arm)**：自改动手前，钉住一份基线读数——关键文件还在不在、多大、什么内容指纹，
    根目录有多少个模块、多少行代码，journal/state 里有多少真相文件，工作区脏了几条。
  · 🛰️ **巡查(check)**：自改收尾后再读一遍，和基线逐项比对，命中异常模式就发哨兵警报，
    每条都带一个**该怎么办**：继续 / 复盘 / 回滚 / 停手。
  · 🧾 **留证据**：每次布哨/巡查都追加一条 JSONL，事后能复盘「那天哨兵喊了吗、喊得对吗」。

异常模式(从轻到重)：
  · 🟡 复盘(review)  —— 一次改动横扫太多文件、总代码量骤减：未必坏，但值得停下看一眼。
  · 🟠 回滚(rollback)—— 模块数量减少、真相源文件变少、关键文件体积腰斩：很可能误伤，退回去。
  · 🔴 停手(stop)    —— 关键文件(intent/rollback/health/crab…)被删除：红线层没了，立刻停。

关键约束：哨兵**只读不写工作区**——它是观测者，绝不成为新的故障源(同 jsonlstore 的信条)。
它**不自动回滚**，只发警报；要不要退回去，由人(或显式跑 rollback.py)定夺。零第三方依赖。

用法：
    python sentinel.py --arm ["自改 foo.py"]   # 自改前布哨：钉基线
    python sentinel.py --check                  # 自改后巡查：比对最近基线、发警报、记证据
    python sentinel.py --patrol                 # 即时巡查：拿工作区 vs HEAD 直接比(无需布哨)
    python sentinel.py --json                   # 导出当前读数(给外部工具消费)
    python sentinel.py                          # 自检(临时仓库里布哨→搅乱→巡查，断言警报如约响)

退出码：0 = 自检全过 / 巡查未触顶级警报；1 = 自检漂了 / 巡查喊了「回滚」或「停手」。
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402  单一真相源：读一批 / 追一条 JSONL

STATE_DIR = REPO_ROOT / "state" / "sentinel"     # 基线读数与证据都落这里
BASELINE_LOG = STATE_DIR / "baselines.jsonl"      # 每次 arm 钉下的基线(取最近一条比对)
EVIDENCE_LOG = STATE_DIR / "evidence.jsonl"       # arm/check 的流水账，事后可复盘

# 关键文件：红线层与退路层——它们要是没了或腰斩，自改就该立刻停手/退回。
PROTECTED = ("intent.py", "rollback.py", "health.py", "crab.py", "jsonlstore.py")
# 真相源目录：journal(航海日志) 与 state(各模块落地数据)，删一条都该警觉(见 intent 红线)。
TRUTH_DIRS = ("journal", "state")

# 阈值：调一处就够，别散在判断里。
SHRINK_RATIO = 0.5    # 关键文件体积 < 基线一半 → 回滚
LOC_DROP_RATIO = 0.3  # 根目录总代码量跌掉三成以上 → 复盘
SPRAWL_FILES = 14     # 一次改动横扫这么多文件以上 → 复盘(范围蔓延)

# 警报级别 → (排序权重, 人话, 该怎么办)
LEVELS = {
    "ok":       (0, "🟢 平安", "继续"),
    "review":   (1, "🟡 复盘", "停下看一眼再继续"),
    "rollback": (2, "🟠 回滚", "很可能误伤，退回上一个好状态"),
    "stop":     (3, "🔴 停手", "红线/退路受损，立刻停手"),
}


def _git(args: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    """在 cwd 跑一条 git，返回 (退出码, stdout+stderr)；git 缺失也收敛成非零，不抛。"""
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd),
                           capture_output=True, text=True)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "git not found"


def _sha8(data: bytes) -> str:
    """内容指纹(短)：只为「变没变」，不为防篡改，sha1 足够且快。"""
    return hashlib.sha1(data).hexdigest()[:12]


def _file_stat(path: pathlib.Path) -> dict:
    """一个关键文件的读数：在不在、多大、内容指纹。缺失/读不了都收敛成 exists=False。"""
    try:
        data = path.read_bytes()
        return {"exists": True, "size": len(data), "sha": _sha8(data)}
    except Exception:
        return {"exists": False, "size": 0, "sha": ""}


def _count_truth_files(repo: pathlib.Path) -> int:
    """数 journal/ 与 state/ 下的文件总数——真相源「变少」是危险信号。"""
    total = 0
    for d in TRUTH_DIRS:
        root = repo / d
        if root.is_dir():
            total += sum(1 for p in root.rglob("*") if p.is_file())
    return total


@dataclasses.dataclass(frozen=True)
class Reading:
    """某一刻的哨兵读数：自改前后各取一份，逐项比对就知道发生了什么。

    · ts          —— 读数时刻(可读时间戳)。
    · head        —— 当时 HEAD 短 sha(纯为复盘对齐)。
    · protected   —— 关键文件名 → {exists, size, sha}。
    · module_count—— 根目录 *.py 模块数(误删模块会让它掉)。
    · total_loc   —— 根目录所有 *.py 的总行数(批量删除会让它骤减)。
    · truth_files —— journal/+state/ 下文件总数(真相源被抹会让它掉)。
    · dirty       —— 工作区未提交改动条数(porcelain 行数)。
    """
    ts: str
    head: str
    protected: dict
    module_count: int
    total_loc: int
    truth_files: int
    dirty: int

    def to_meta(self) -> dict:
        return dataclasses.asdict(self)


def snapshot(repo: pathlib.Path = REPO_ROOT) -> Reading:
    """读一份当前哨兵读数。纯只读——只摸文件大小/内容与 git 状态，绝不动工作区。"""
    rc, head = _git(["rev-parse", "--short", "HEAD"], repo)
    head = head.strip() if rc == 0 else "?"
    protected = {name: _file_stat(repo / name) for name in PROTECTED}
    py_files = sorted(repo.glob("*.py"))
    total_loc = 0
    for p in py_files:
        try:
            total_loc += len(p.read_text("utf-8", errors="ignore").splitlines())
        except Exception:
            continue
    _, status = _git(["status", "--porcelain"], repo)
    dirty = len([ln for ln in status.splitlines() if ln.strip()])
    return Reading(
        ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
        head=head,
        protected=protected,
        module_count=len(py_files),
        total_loc=total_loc,
        truth_files=_count_truth_files(repo),
        dirty=dirty,
    )


@dataclasses.dataclass(frozen=True)
class Alert:
    """一条哨兵警报：哪条规则响了、什么级别、该怎么办。"""
    level: str   # ok / review / rollback / stop
    code: str    # 机器可读的规则标识
    message: str # 人话：发生了什么


def inspect(before: Reading, after: Reading) -> list[Alert]:
    """逐项比对前后读数，命中异常模式就攒一条警报。无异常则回一条 ok。

    判据从重到轻：关键文件被删(停手) > 关键文件腰斩/模块变少/真相源减少(回滚) >
    横扫太多文件/总代码量骤减(复盘)。只看「向坏的方向变」，纯加文件/加代码不触警报。
    """
    alerts: list[Alert] = []

    # 🔴 停手：关键文件从「在」变「不在」——红线/退路层没了。
    for name in PROTECTED:
        b, a = before.protected.get(name, {}), after.protected.get(name, {})
        if b.get("exists") and not a.get("exists"):
            alerts.append(Alert("stop", "protected_deleted",
                                f"关键文件 {name} 被删除"))

    # 🟠 回滚：关键文件还在但体积腰斩——很可能被误改空。
    for name in PROTECTED:
        b, a = before.protected.get(name, {}), after.protected.get(name, {})
        if (b.get("exists") and a.get("exists") and b.get("size", 0) > 0
                and a["size"] < b["size"] * SHRINK_RATIO):
            pct = round((1 - a["size"] / b["size"]) * 100)
            alerts.append(Alert("rollback", "protected_shrank",
                                f"关键文件 {name} 体积骤减 {pct}%"
                                f"（{b['size']}→{a['size']} 字节）"))

    # 🟠 回滚：根目录模块数量减少——可能误删了整个模块。
    if after.module_count < before.module_count:
        alerts.append(Alert("rollback", "modules_lost",
                            f"模块数量减少：{before.module_count}→"
                            f"{after.module_count}（疑似误删模块）"))

    # 🟠 回滚：真相源文件变少——违反 intent 的 keep-truth-sources 红线。
    if after.truth_files < before.truth_files:
        alerts.append(Alert("rollback", "truth_shrank",
                            f"真相源文件减少：{before.truth_files}→"
                            f"{after.truth_files}（journal/state 被抹？违反红线）"))

    # 🟡 复盘：总代码量骤减——未必坏(可能是重构瘦身)，但值得停下看一眼。
    if before.total_loc > 0 and after.total_loc < before.total_loc * (1 - LOC_DROP_RATIO):
        pct = round((1 - after.total_loc / before.total_loc) * 100)
        alerts.append(Alert("review", "loc_drop",
                            f"根目录总代码量骤减 {pct}%"
                            f"（{before.total_loc}→{after.total_loc} 行）"))

    # 🟡 复盘：工作区脏度暴涨——一次改动横扫太多文件，范围可能蔓延了。
    if after.dirty >= SPRAWL_FILES and after.dirty > before.dirty:
        alerts.append(Alert("review", "scope_sprawl",
                            f"工作区有 {after.dirty} 条未提交改动"
                            f"（≥{SPRAWL_FILES}，范围蔓延？）"))

    if not alerts:
        alerts.append(Alert("ok", "clear", "关键文件/指标/真相源均未见异常变化"))
    return alerts


def verdict(alerts: list[Alert]) -> Alert:
    """从一批警报里挑级别最高的那条作为总结论——哨兵只按最坏的喊。"""
    return max(alerts, key=lambda a: LEVELS[a.level][0])


def _record(obj: dict, state_dir: pathlib.Path) -> None:
    """把一条 arm/check 证据追加进流水账(带时间戳)；写盘失败被吞，绝不反噬。"""
    jsonlstore.append_jsonl(state_dir / EVIDENCE_LOG.name,
                            {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **obj})


def arm(repo: pathlib.Path = REPO_ROOT,
        label: str = "", state_dir: pathlib.Path | None = None) -> Reading:
    """布哨：自改前钉一份基线读数，落进 baselines.jsonl(巡查时取最近一条比对)。"""
    sd = state_dir or STATE_DIR
    sd.mkdir(parents=True, exist_ok=True)
    r = snapshot(repo)
    meta = {**r.to_meta(), "label": label}
    jsonlstore.append_jsonl(sd / BASELINE_LOG.name, meta)
    _record({"event": "arm", "head": r.head, "label": label,
             "modules": r.module_count, "loc": r.total_loc}, sd)
    return r


def _latest_baseline(state_dir: pathlib.Path) -> Reading | None:
    """取最近一条基线;没有/坏行 → None(巡查时退化为「拿 HEAD 比」)。"""
    recs = jsonlstore.read_jsonl(state_dir / BASELINE_LOG.name)
    for rec in reversed(recs):
        rec.pop("label", None)
        try:
            return Reading(**rec)
        except TypeError:
            continue
    return None


def check(repo: pathlib.Path = REPO_ROOT,
          state_dir: pathlib.Path | None = None) -> tuple[Reading, list[Alert]]:
    """巡查：取当前读数 vs 最近基线，发警报、记证据。无基线则退化为 patrol(vs HEAD)。"""
    sd = state_dir or STATE_DIR
    before = _latest_baseline(sd)
    after = snapshot(repo)
    if before is None:
        before = _head_reading(repo)
    alerts = inspect(before, after)
    top = verdict(alerts)
    _record({"event": "check", "head": after.head, "level": top.level,
             "alerts": [dataclasses.asdict(a) for a in alerts]}, sd)
    return after, alerts


def _head_reading(repo: pathlib.Path) -> Reading:
    """把「上一个提交(HEAD)」当成基线读出来——给 patrol / 无基线巡查用。

    临时把 HEAD 版本的关键文件与 *.py 取出来计数，只读 git 对象、不碰工作区。
    """
    rc, head = _git(["rev-parse", "--short", "HEAD"], repo)
    head = head.strip() if rc == 0 else "?"
    protected = {}
    for name in PROTECTED:
        rc, content = _git(["show", f"HEAD:{name}"], repo)
        if rc == 0:
            data = content.encode("utf-8", errors="ignore")
            protected[name] = {"exists": True, "size": len(data),
                               "sha": _sha8(data)}
        else:
            protected[name] = {"exists": False, "size": 0, "sha": ""}
    rc, listing = _git(["ls-tree", "--name-only", "HEAD"], repo)
    py = [ln for ln in listing.splitlines() if ln.strip().endswith(".py")]
    total_loc = 0
    for name in py:
        rc, content = _git(["show", f"HEAD:{name}"], repo)
        if rc == 0:
            total_loc += len(content.splitlines())
    return Reading(ts="HEAD", head=head, protected=protected,
                   module_count=len(py), total_loc=total_loc,
                   truth_files=_count_truth_files(repo), dirty=0)


def patrol(repo: pathlib.Path = REPO_ROOT,
           state_dir: pathlib.Path | None = None) -> tuple[Reading, list[Alert]]:
    """即时巡查：拿当前工作区 vs HEAD 直接比，不依赖布哨。记一条证据。"""
    sd = state_dir or STATE_DIR
    before = _head_reading(repo)
    after = snapshot(repo)
    alerts = inspect(before, after)
    top = verdict(alerts)
    _record({"event": "patrol", "head": after.head, "level": top.level,
             "alerts": [dataclasses.asdict(a) for a in alerts]}, sd)
    return after, alerts


def _print_alerts(after: Reading, alerts: list[Alert]) -> Alert:
    """把一次巡查结论打印成人话，返回总结论(供 main 决定退出码)。"""
    top = verdict(alerts)
    _, label, action = LEVELS[top.level]
    print(f"🛰️ 哨兵巡查 @ HEAD={after.head}（{after.module_count} 个模块，"
          f"{after.total_loc} 行，{after.dirty} 条未提交）\n")
    for a in alerts:
        mark = LEVELS[a.level][1]
        print(f"  {mark} [{a.code}] {a.message}")
    print(f"\n总结论：{label} —— {action}")
    return top


def _selfcheck() -> tuple[bool, str]:
    """临时 git 仓库里走完整流程：布哨 → 搅乱(删关键文件) → 巡查，断言警报如约响。"""
    try:
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d)
            repo = base / "repo"
            repo.mkdir()
            cfg = ["-c", "user.email=t@t", "-c", "user.name=t"]
            _git(["init", "-q"], repo)
            # 造出关键文件与几个模块、一点真相源。
            for name in PROTECTED:
                (repo / name).write_text("# " + name + "\nx = 1\n" * 50, "utf-8")
            (repo / "extra.py").write_text("y = 2\n", "utf-8")
            (repo / "journal").mkdir()
            (repo / "journal" / "log.md").write_text("day1\n", "utf-8")
            _git([*cfg, "add", "-A"], repo)
            _git([*cfg, "commit", "-q", "-m", "v1"], repo)

            sd = base / "state"
            before = arm(repo, label="自检", state_dir=sd)
            if before.module_count < len(PROTECTED):
                return False, f"布哨没数全模块：{before.module_count}"

            # 搅乱：删一个关键文件 + 删真相源 + 把另一个关键文件改空。
            (repo / "intent.py").unlink()
            (repo / "journal" / "log.md").unlink()
            (repo / "health.py").write_text("# gutted\n", "utf-8")

            after, alerts = check(repo, state_dir=sd)
            codes = {a.code for a in alerts}
            if "protected_deleted" not in codes:
                return False, f"删关键文件没触发 stop 警报：{codes}"
            if "protected_shrank" not in codes:
                return False, f"关键文件改空没触发 rollback 警报：{codes}"
            if "truth_shrank" not in codes:
                return False, f"删真相源没触发 rollback 警报：{codes}"
            top = verdict(alerts)
            if top.level != "stop":
                return False, f"总结论应是 stop，实得 {top.level}"
            if not _latest_baseline(sd):
                return False, "基线没落进 baselines.jsonl"

            # 反向：未搅乱(纯加文件)不该触顶级警报。
            clean = inspect(before, before)
            if verdict(clean).level != "ok":
                return False, "前后一致却报了警，哨兵太敏感了"
        return True, "布哨→删关键文件/真相源/改空→巡查，stop/rollback 警报如约响，且无误报。"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自改哨兵：布哨 / 巡查 / 警报 🛰️")
    ap.add_argument("--arm", nargs="?", const="", metavar="说明",
                    help="自改前布哨：钉一份基线读数(可附一句这次要干什么)")
    ap.add_argument("--check", action="store_true",
                    help="自改后巡查：比对最近基线、发警报、记证据")
    ap.add_argument("--patrol", action="store_true",
                    help="即时巡查：拿工作区 vs HEAD 直接比(无需布哨)")
    ap.add_argument("--json", action="store_true", help="导出当前读数(给外部工具消费)")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(snapshot().to_meta(), ensure_ascii=False, indent=2))
        return
    if args.arm is not None:
        r = arm(label=args.arm)
        print(f"🛰️ 已布哨 @ HEAD={r.head}：{r.module_count} 个模块、{r.total_loc} 行、"
              f"{r.truth_files} 个真相源文件、{r.dirty} 条未提交。")
        print("   自改收尾后跑 `python sentinel.py --check` 让哨兵巡查。")
        return
    if args.patrol:
        after, alerts = patrol()
        top = _print_alerts(after, alerts)
        sys.exit(1 if LEVELS[top.level][0] >= LEVELS["rollback"][0] else 0)
    if args.check:
        after, alerts = check()
        top = _print_alerts(after, alerts)
        sys.exit(1 if LEVELS[top.level][0] >= LEVELS["rollback"][0] else 0)

    ok, detail = _selfcheck()
    mark = "✅" if ok else "❌"
    print(f"🛰️ opencrab 自改哨兵自检\n\n  {mark} {detail}\n")
    if ok:
        print("🛰️ 守约：自改失控的样子(删红线/抹真相/腰斩模块)，哨兵都能当场喊出来。")
    else:
        print("⚠️  哨兵自检漂了，先把它修好——盯梢的人自己先靠得住，才敢放手自改。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
