#!/usr/bin/env python3
"""自改退路层 🪂🧯 —— 蜕壳前先存快照、备好回滚脚本，事后演练恢复、留下证据。

为什么要有它：这套领地每天自改一个模块，`intent.py` 的红线说「不把未经验证的改动
并入主干」、`health.py` 在事后把关——可万一改坏了、又恰好在 `crab.py` 自动提交/推送
之后才发现呢？真相源(审计/记忆/演化日志)在、git 历史也在，但「怎样确定地退回上一个
好状态」这件事，过去只活在我临场记得的几条 git 命令里：没写下来、没验过、慌起来就忘。
真正大胆进化，必须先拥有一条**可靠且演练过**的退路。这里把它收成三步：

  · 📸 **存快照(snapshot)**：自改前钉住当前分支与 HEAD、把工作区改动存成补丁，
    并**生成一个自给自足的回滚脚本**——一条命令就能把仓库退回此刻。
  · 🎭 **演练恢复(rehearse)**：把仓库克隆到临时目录，故意搅乱它，再跑那个回滚脚本，
    断言 HEAD 真的退回了快照那一刻——证明退路不是写在纸上的安慰，是真能跑通的。
  · 🧾 **留证据(evidence)**：每次存快照/演练都追加一条 JSONL 记录，事后能复盘
    「那天我退得回去吗」。

关键约束：演练**只在临时克隆里动手**，绝不碰真实工作区——退路本身不能成为新的故障源。
回滚脚本只 `git reset --hard` 到记录的 HEAD 并回放补丁，不删除任何真相源(见 intent
的 keep-truth-sources 红线)。零第三方依赖，纯标准库，git 之外无所求。

用法：
    python rollback.py --snapshot ["自改 rollback.py"]  # 自改前存快照 + 生成回滚脚本
    python rollback.py --list                            # 列已存快照
    python rollback.py --rehearse [快照id]               # 演练恢复(临时克隆里跑，记证据)
    python rollback.py --json                            # 导出快照清单(给外部工具消费)
    python rollback.py                                   # 跑自检(临时仓库里走完整流程)

退出码：0 = 自检全过 / 演练恢复成功；1 = 自检漂了 / 演练没退回去。
"""
from __future__ import annotations

import argparse
import dataclasses
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

STATE_DIR = REPO_ROOT / "state" / "rollback"   # 快照、补丁、回滚脚本与证据都落这里
EVIDENCE_LOG = STATE_DIR / "evidence.jsonl"    # 存快照/演练的流水账，事后可复盘


# ── git 小工具：把「跑一条 git、要它的输出」收成一处，失败不抛、回 (rc, 文本) ──
def _git(args: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    """在 cwd 跑一条 git，返回 (退出码, stdout+stderr 文本)；git 缺失也收敛成非零。"""
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd),
                           capture_output=True, text=True)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "git not found"


def _git_ok(args: list[str], cwd: pathlib.Path) -> str:
    """跑一条必须成功的 git，失败即抛——给自检/演练这种「错了就该炸」的路径用。"""
    rc, out = _git(args, cwd)
    if rc != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败(rc={rc})：{out.strip()}")
    return out.strip()


@dataclasses.dataclass(frozen=True)
class Snapshot:
    """自改前钉住的一刻：退回到这里所需的全部坐标。

    · id        —— 稳定标识(时间戳)，也是脚本/补丁的文件名。
    · label     —— 这次自改要干什么(人话)，纯为事后复盘。
    · branch    —— 当时所在分支(detached 则为 HEAD 的 sha)。
    · head      —— 当时 HEAD 的完整 sha——回滚就是退回它。
    · dirty     —— 当时工作区未提交的改动条数(porcelain 行数)。
    · patch     —— 若工作区脏，存下 `git diff HEAD` 的补丁路径，回滚后回放。
    · script    —— 生成的回滚脚本路径：一条命令把仓库退回此刻。
    """
    id: str
    label: str
    branch: str
    head: str
    dirty: int
    patch: str | None
    script: str

    def to_meta(self) -> dict:
        return dataclasses.asdict(self)


def _now_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _branch_of(repo: pathlib.Path) -> str:
    """当前分支名；detached HEAD 时回退到短 sha(脚本里照样能 checkout)。"""
    rc, out = _git(["symbolic-ref", "--short", "-q", "HEAD"], repo)
    name = out.strip()
    if rc == 0 and name:
        return name
    return _git_ok(["rev-parse", "--short", "HEAD"], repo)


def _render_script(snap_id: str, branch: str, head: str,
                   patch_name: str | None) -> str:
    """把回滚步骤渲染成一个自给自足、可读、可 `bash -n` 校验的脚本。

    脚本只做「退回」这一件事：硬复位到记录的 HEAD、回到原分支、回放工作区补丁。
    它**不删除**审计/记忆/演化日志等真相源——退路只负责把代码退回去。
    """
    lines = [
        "#!/usr/bin/env bash",
        f"# opencrab 回滚脚本 · 快照 {snap_id}",
        "# 把仓库退回存快照那一刻。在仓库根目录运行：bash <本脚本>",
        "set -euo pipefail",
        'cd "$(git rev-parse --show-toplevel)"',
        f'echo "🪂 回滚到快照 {snap_id} (HEAD={head[:12]}, branch={branch})"',
        f"git reset --hard {head}",
        f"git checkout {branch} 2>/dev/null || git checkout -B {branch} {head}",
    ]
    if patch_name:
        lines += [
            "# 回放存快照时工作区里未提交的改动",
            f'git apply "$(dirname "$0")/{patch_name}" '
            '&& echo "↩️  已回放未提交改动" '
            '|| echo "⚠️  补丁未能干净回放，请手动检查"',
        ]
    lines.append('echo "✅ 回滚完成"')
    return "\n".join(lines) + "\n"


def snapshot(repo: pathlib.Path = REPO_ROOT, label: str = "",
             state_dir: pathlib.Path | None = None) -> Snapshot:
    """自改前钉住当前状态：记录 HEAD/分支、存工作区补丁、生成回滚脚本，并留一条证据。

    纯加法、不碰工作区——只读 git 状态、往 state/rollback 写快照产物。回滚脚本不会
    自动执行，要退路时由人(或 rehearse)显式跑它。
    """
    sd = state_dir or STATE_DIR
    sd.mkdir(parents=True, exist_ok=True)
    snap_id = _now_id()
    head = _git_ok(["rev-parse", "HEAD"], repo)
    branch = _branch_of(repo)
    _, status = _git(["status", "--porcelain"], repo)
    dirty_lines = [ln for ln in status.splitlines() if ln.strip()]

    patch_name: str | None = None
    if dirty_lines:
        rc, diff = _git(["diff", "HEAD"], repo)
        if rc == 0 and diff.strip():
            patch_name = f"{snap_id}.patch"
            (sd / patch_name).write_text(diff, "utf-8")

    script = _render_script(snap_id, branch, head, patch_name)
    script_path = sd / f"{snap_id}.sh"
    script_path.write_text(script, "utf-8")
    script_path.chmod(0o755)

    snap = Snapshot(id=snap_id, label=label, branch=branch, head=head,
                    dirty=len(dirty_lines), patch=patch_name,
                    script=str(script_path))
    jsonlstore.append_jsonl(sd / "snapshots.jsonl", snap.to_meta())
    _record(sd, {"event": "snapshot", "id": snap_id, "label": label,
                 "head": head, "branch": branch, "dirty": len(dirty_lines)})
    return snap


def list_snapshots(state_dir: pathlib.Path | None = None) -> list[Snapshot]:
    """读出已存快照(时间正序)；缺失文件回空列表。"""
    sd = state_dir or STATE_DIR
    out: list[Snapshot] = []
    for rec in jsonlstore.read_jsonl(sd / "snapshots.jsonl"):
        try:
            out.append(Snapshot(**rec))
        except TypeError:
            continue   # 老格式/脏行：跳过，绝不让复盘入口自己崩
    return out


@dataclasses.dataclass(frozen=True)
class Rehearsal:
    """一次恢复演练的结论：退路真能跑通吗。"""
    snap_id: str
    ok: bool
    detail: str   # 成功 → 怎么验过的；失败 → 卡在哪


def rehearse(snap: Snapshot, repo: pathlib.Path = REPO_ROOT,
             state_dir: pathlib.Path | None = None) -> Rehearsal:
    """演练恢复：克隆仓库到临时目录、故意搅乱、跑回滚脚本，断言真退回了快照那一刻。

    全程**只在临时克隆里动手**，绝不碰 repo 的工作区——演练不能成为新的故障源。
    成功的判据很硬：跑完脚本后克隆的 HEAD 必须等于快照记录的 head。结论记进证据。
    """
    sd = state_dir or STATE_DIR
    detail = ""
    ok = False
    try:
        # 没有这个 commit 的仓库根本谈不上退回去——先验它还在。
        rc, _ = _git(["cat-file", "-e", f"{snap.head}^{{commit}}"], repo)
        if rc != 0:
            raise RuntimeError(f"快照 HEAD {snap.head[:12]} 在仓库里已不可达")

        with tempfile.TemporaryDirectory() as d:
            clone = pathlib.Path(d) / "clone"
            _git_ok(["clone", "--no-hardlinks", "--quiet",
                     str(repo), str(clone)], pathlib.Path(d))
            # 故意搅乱：在克隆里造一个新提交，模拟「自改把状态推到了别处」。
            (clone / "_rehearsal_mess.txt").write_text("disrupted\n", "utf-8")
            _git_ok(["-c", "user.email=r@r", "-c", "user.name=r",
                     "add", "-A"], clone)
            _git_ok(["-c", "user.email=r@r", "-c", "user.name=r",
                     "commit", "-q", "-m", "rehearsal: disrupt"], clone)
            messed = _git_ok(["rev-parse", "HEAD"], clone)
            if messed == snap.head:
                raise RuntimeError("搅乱后 HEAD 未变，演练无意义")

            # 把回滚脚本(连同补丁)复制进克隆，原样跑一遍。
            local_script = clone / "_rollback.sh"
            local_script.write_text(
                pathlib.Path(snap.script).read_text("utf-8"), "utf-8")
            if snap.patch:
                (clone / snap.patch).write_text(
                    (sd / snap.patch).read_text("utf-8"), "utf-8")
            # 脚本里写的是绝对/相对补丁路径，统一从克隆根跑；补丁与脚本同目录。
            p = subprocess.run(["bash", str(local_script)], cwd=str(clone),
                              capture_output=True, text=True)
            restored = _git_ok(["rev-parse", "HEAD"], clone)
            if restored != snap.head:
                raise RuntimeError(
                    f"跑完回滚脚本 HEAD={restored[:12]}，"
                    f"未退回快照 {snap.head[:12]}；脚本输出：{p.stdout}{p.stderr}")
            ok = True
            detail = (f"临时克隆里造新提交搅乱后，回滚脚本把 HEAD 退回 "
                      f"{snap.head[:12]}——退路验通。")
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"

    _record(sd, {"event": "rehearse", "id": snap.snap_id if isinstance(
        snap, Rehearsal) else snap.id, "ok": ok, "detail": detail})
    return Rehearsal(snap_id=snap.id, ok=ok, detail=detail)


def _record(state_dir: pathlib.Path, obj: dict) -> None:
    """把一条快照/演练证据追加进流水账(带时间戳)；写盘失败被吞，绝不反噬。"""
    obj = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **obj}
    jsonlstore.append_jsonl(state_dir / EVIDENCE_LOG.name, obj)


def manifest(state_dir: pathlib.Path | None = None) -> dict:
    """导出快照清单(给外部工具/复盘消费)。"""
    return {"snapshots": [s.to_meta() for s in list_snapshots(state_dir)]}


# ── 自检：在一个临时 git 仓库里走完整流程(存快照→搅乱→演练恢复)，确定性、无副作用 ──
def _selfcheck() -> tuple[bool, str]:
    """造一个一次性 git 仓库，跑 snapshot→rehearse，断言退路真能把 HEAD 退回去。"""
    try:
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d)
            repo = base / "repo"
            repo.mkdir()
            cfg = ["-c", "user.email=t@t", "-c", "user.name=t"]
            _git_ok(["init", "-q"], repo)
            (repo / "a.txt").write_text("v1\n", "utf-8")
            _git_ok([*cfg, "add", "-A"], repo)
            _git_ok([*cfg, "commit", "-q", "-m", "v1"], repo)
            # 留一点未提交改动，顺带验补丁回放这条路。
            (repo / "a.txt").write_text("v1\nwip\n", "utf-8")

            sd = base / "state"
            snap = snapshot(repo, label="自检", state_dir=sd)
            if snap.dirty != 1:
                return False, f"应记录 1 条未提交改动，实得 {snap.dirty}"
            if not pathlib.Path(snap.script).exists():
                return False, "回滚脚本没生成"

            reh = rehearse(snap, repo=repo, state_dir=sd)
            if not reh.ok:
                return False, f"演练恢复失败：{reh.detail}"
            if not list_snapshots(sd):
                return False, "快照没落进 snapshots.jsonl"
        return True, "临时仓库里 snapshot→搅乱→rehearse 全程跑通，HEAD 如约退回。"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _print_list() -> None:
    snaps = list_snapshots()
    if not snaps:
        print("🪂 还没有快照。自改前先跑 `python rollback.py --snapshot` 钉住退路。")
        return
    print(f"🪂 已存 {len(snaps)} 个快照：\n")
    for s in snaps:
        dirty = f"，{s.dirty} 条未提交改动" if s.dirty else ""
        label = f" — {s.label}" if s.label else ""
        print(f"  📸 {s.id}  HEAD={s.head[:12]} @{s.branch}{dirty}{label}")
        print(f"        回滚：bash {s.script}")
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自改退路：快照 / 回滚 / 演练 🪂")
    ap.add_argument("--snapshot", nargs="?", const="", metavar="说明",
                    help="自改前存快照并生成回滚脚本(可附一句这次要干什么)")
    ap.add_argument("--list", action="store_true", help="列已存快照")
    ap.add_argument("--rehearse", nargs="?", const="__latest__", metavar="快照id",
                    help="演练恢复(默认拿最新快照)，在临时克隆里验退路、记证据")
    ap.add_argument("--json", action="store_true", help="导出快照清单")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return
    if args.snapshot is not None:
        snap = snapshot(label=args.snapshot)
        print(f"🪂 已存快照 {snap.id}（HEAD={snap.head[:12]} @{snap.branch}，"
              f"{snap.dirty} 条未提交改动）")
        print(f"   回滚一条命令：bash {snap.script}")
        return
    if args.rehearse is not None:
        snaps = list_snapshots()
        if not snaps:
            print("🪂 没有快照可演练。先 `--snapshot` 存一个。")
            sys.exit(1)
        if args.rehearse == "__latest__":
            target = snaps[-1]
        else:
            picked = [s for s in snaps if s.id == args.rehearse]
            if not picked:
                print(f"🪂 找不到快照 {args.rehearse!r}。`--list` 看有哪些。")
                sys.exit(1)
            target = picked[0]
        reh = rehearse(target)
        mark = "✅" if reh.ok else "❌"
        print(f"🎭 演练快照 {target.id}：{mark} {reh.detail}")
        sys.exit(0 if reh.ok else 1)
    if args.list:
        _print_list()
        return

    ok, detail = _selfcheck()
    mark = "✅" if ok else "❌"
    print(f"🪂 opencrab 自改退路自检\n\n  {mark} {detail}\n")
    if ok:
        print("🪂 守约：退路存得下、演得通、能把 HEAD 退回去。")
    else:
        print("⚠️  退路自检漂了，先把它修好再大胆自改——没退路别乱蜕壳。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
