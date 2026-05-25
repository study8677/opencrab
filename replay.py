#!/usr/bin/env python3
"""失败案例打包与一键复现 🎞️ —— 把一次摔倒固化成可重跑、可验证、可修好的案例。

为什么要有它：errors.py 能把失败**分流**成错误码，audit.py 能把一次进程的
**决策链**重放；但两者都答不上最要命的那一问——「这条具体命令，换个时间、
换台机器，还能不能原样跑出同样的错？修过之后到底好没好？」

最怕的失败，是「当时报错了，复现不出来」：日志早被刷走、环境记不清、输入丢了，
于是只能瞎猜着改，改完也不知道修没修好。这里把一次失败的**完整现场**——失败的
命令、与复现相关的环境摘要、喂进去的输入、当时的 stdout/stderr/退出码、外加
errors.py 的分流结果——打包成一个自包含的**案例**，落在 `state/replay/<案例号>/`：

  · case.json   案例清单(命令/环境/输入/日志/分流，单一真相源)
  · repro.sh    一键复现脚本：原样重跑那条命令
  · stdout.log / stderr.log   当时的原始输出

之后 `--replay` 就能把案例放回**同样的命令与环境**里重跑，对比新旧结局给出判定：
  reproduced(还是原样错) / fixed(不再报错了) / changed(错法变了)。
`--replay-all` 把全部案例当回归套跑一遍，一眼看出哪些已经修好、哪些还在摔。

设计原则与 audit/errors 一致：零第三方依赖、纯标准库；密钥一律打码；
捕获与读写永不反噬——记录是观测者，不能成为新的故障源。

用法:
    python replay.py                          # 列出全部已捕获的复现案例
    python replay.py --show <案例号>          # 摊开一个案例(命令/环境/输入/日志/分流)
    python replay.py --replay <案例号>        # 重跑这个案例，判定 reproduced/fixed/changed
    python replay.py --replay-all             # 全部重跑(回归式)，看哪些已修好
    python replay.py --capture [--title T] -- <命令...>   # 现场捕获：跑一条命令，失败则存成案例
    python replay.py --json                   # 机读(配合 --show/--replay/--replay-all)

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import pathlib
import platform
import subprocess
import sys

import errors
import jsonlstore

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
REPLAY_DIR = _REPO_ROOT / "state" / "replay"
INDEX = REPLAY_DIR / "index.jsonl"

# 环境摘要里只收与「能不能复现」真正相关的变量；密钥型一律打码。
_ENV_PREFIX = "OPENCRAB_"
_SECRET_HINT = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="milliseconds")


def _mask(key: str, val: str) -> str:
    """密钥型变量打码：只留是否设过 + 末 4 位，绝不把秘密写进案例文件。"""
    if any(h in key.upper() for h in _SECRET_HINT) and val:
        return f"***(末4位 {val[-4:]})" if len(val) > 4 else "***"
    return val


def _git(*args: str) -> str:
    """跑一条只读 git 命令取一行结果；不在仓库/出错都退化成 '?'，绝不抛。"""
    try:
        r = subprocess.run(["git", "-C", str(_REPO_ROOT), *args],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


def env_summary() -> dict:
    """抓一份「与复现相关」的环境摘要：解释器/平台/git 位点 + 打码后的 OPENCRAB_* 变量。"""
    opencrab = {k: _mask(k, v) for k, v in sorted(os.environ.items())
                if k.startswith(_ENV_PREFIX)}
    return {
        "python": ".".join(map(str, sys.version_info[:3])),
        "platform": platform.platform(),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "opencrab": opencrab,
    }


# ── 案例模型 ─────────────────────────────────────────────────────────
@dataclasses.dataclass
class Case:
    """一个自包含的失败复现案例：失败命令 + 环境摘要 + 输入 + 日志 + 分流。"""
    case_id: str
    created_at: str
    title: str                  # 人话一句：这是什么失败
    command: list[str]          # 失败的命令(argv，原样可重跑)
    cwd: str                    # 工作目录(相对仓库根，'.' 即根)
    env: dict                   # 环境摘要(env_summary 的快照)
    stdin: str | None           # 喂给命令的输入(没有则 None)
    exit_code: int | None       # 当时的退出码
    stdout: str                 # 当时的标准输出
    stderr: str                 # 当时的标准错误
    error: dict                 # errors.triage 的分流结果(code/domain/title/hint)
    note: str = ""              # 额外备注

    def dir(self) -> pathlib.Path:
        return REPLAY_DIR / self.case_id

    def to_meta(self) -> dict:
        """给索引/清单用的一行摘要(不含厚重日志)。"""
        return {"case_id": self.case_id, "created_at": self.created_at,
                "title": self.title, "command": " ".join(self.command),
                "error_code": self.error.get("code"),
                "exit_code": self.exit_code}

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _run(command: list[str], cwd: pathlib.Path, env: dict | None,
         stdin: str | None, timeout: int) -> tuple[int | None, str, str]:
    """跑一条命令并捕获 (退出码, stdout, stderr)；超时/起不来也退化成结果，绝不抛。"""
    try:
        r = subprocess.run(command, cwd=str(cwd),
                           env={**os.environ, **env} if env else None,
                           input=stdin, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        return None, e.stdout or "", (e.stderr or "") + f"\n[复现超时：>{timeout}s]"
    except Exception as e:
        return None, "", f"[命令起不来：{e!r}]"


def _new_case_id() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]


# ── 捕获 / 持久化 ────────────────────────────────────────────────────
def capture(command: list[str], *, exit_code: int | None, stdout: str,
            stderr: str, title: str = "", cwd: str = ".",
            stdin: str | None = None, env: dict | None = None,
            note: str = "") -> Case:
    """把一次失败的现场打包成案例并落盘；返回 Case。

    现场字段大多可选：只要给得出失败命令与它的输出/退出码，就能存成可重跑的案例。
    分流(error)自动由 errors.triage 从 stderr/退出码派生，省得调用方自己填。
    """
    spec = errors.triage(stderr=stderr, exit_code=exit_code,
                         message=" ".join(command))
    case = Case(
        case_id=_new_case_id(),
        created_at=_now_iso(),
        title=title.strip() or (stderr.strip().splitlines()[-1][:80]
                                if stderr.strip() else " ".join(command)[:80]),
        command=list(command),
        cwd=cwd,
        env=env if env is not None else env_summary(),
        stdin=stdin,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        error=spec,
        note=note,
    )
    save_case(case)
    return case


def capture_run(command: list[str], *, title: str = "", cwd: str = ".",
                stdin: str | None = None, env: dict | None = None,
                timeout: int = 300, note: str = "") -> tuple[Case | None, int | None]:
    """现场跑一条命令；**只在它失败(退出码非 0 或起不来)时**存成案例。

    返回 (案例 or None, 退出码)。命令成功(退出码 0)时不留案例，返回 (None, 0)——
    复现库只收摔倒的现场，不被成功跑过的命令灌满。
    """
    workdir = (_REPO_ROOT / cwd).resolve()
    code, out, err = _run(command, workdir, env, stdin, timeout)
    if code == 0:
        return None, 0
    case = capture(command, exit_code=code, stdout=out, stderr=err,
                   title=title, cwd=cwd, stdin=stdin,
                   env=env_summary() if env is None else {**env_summary(), "extra": env},
                   note=note)
    return case, code


def repro_script(case: Case) -> str:
    """生成一键复现脚本(bash)：cd 到工作目录、原样重跑那条命令。"""
    quoted = " ".join(_shquote(a) for a in case.command)
    lines = [
        "#!/usr/bin/env bash",
        f"# 复现案例 {case.case_id} · {case.title}",
        f"# 捕获于 {case.created_at} · 原退出码 {case.exit_code}"
        f" · 分流 {case.error.get('code')}",
        "set -x",
        f'cd "$(dirname "$0")/{_rel_to_case(case.cwd)}" || exit 1',
    ]
    if case.stdin is not None:
        heredoc = "OPENCRAB_REPRO_STDIN"
        lines.append(f"{quoted} <<'{heredoc}'\n{case.stdin}\n{heredoc}")
    else:
        lines.append(quoted)
    return "\n".join(lines) + "\n"


def _rel_to_case(cwd: str) -> str:
    """案例目录在 state/replay/<id>/，回到仓库根要上跳三层，再进 cwd。"""
    base = "../../.."
    return base if cwd in (".", "") else f"{base}/{cwd}"


def _shquote(s: str) -> str:
    if s and all(c.isalnum() or c in "-_./=:" for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def save_case(case: Case) -> bool:
    """把案例写成自包含目录(case.json + repro.sh + 原始日志)并登记进索引。

    任何写盘异常都被吞掉——捕获失败的现场，本身绝不能成为新的失败。
    """
    try:
        d = case.dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "case.json").write_text(
            json.dumps(case.to_dict(), ensure_ascii=False, indent=2), "utf-8")
        (d / "stdout.log").write_text(case.stdout, "utf-8")
        (d / "stderr.log").write_text(case.stderr, "utf-8")
        repro = d / "repro.sh"
        repro.write_text(repro_script(case), "utf-8")
        repro.chmod(0o755)
        jsonlstore.append_jsonl(INDEX, case.to_meta())
        return True
    except Exception:
        return False   # 记录是观测者，不能成为新的故障源


def load_case(case_id: str) -> Case | None:
    """按案例号(支持末段短号匹配)读回完整案例；缺失/坏档返回 None。"""
    cid = _resolve_id(case_id)
    if not cid:
        return None
    try:
        data = json.loads((REPLAY_DIR / cid / "case.json").read_text("utf-8"))
        return Case(**data)
    except Exception:
        return None


def _resolve_id(case_id: str) -> str | None:
    """把用户给的(可能是末段短号)解析成真实存在的案例号。"""
    if (REPLAY_DIR / case_id / "case.json").exists():
        return case_id
    for meta in reversed(load_index()):          # 新的优先
        cid = meta.get("case_id", "")
        if cid.endswith(case_id):
            return cid
    return None


def load_index() -> list[dict]:
    """读案例索引(时间正序的一行摘要列表)。"""
    return jsonlstore.read_jsonl(INDEX)


# ── 重放 / 判定 ──────────────────────────────────────────────────────
@dataclasses.dataclass
class ReplayResult:
    """一次重放的结局：把新跑的结果与案例当时的结果对比后给出判定。"""
    case_id: str
    replayed_at: str
    exit_code: int | None
    error_code: str             # 新一次的分流码
    verdict: str                # reproduced / fixed / changed
    detail: str                 # 人话一句

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


_VERDICT_MARK = {"reproduced": "🔁", "fixed": "✅", "changed": "🌓"}


def replay(case: Case, timeout: int = 300) -> ReplayResult:
    """把案例放回**同样的命令与输入**里重跑，对比新旧结局给出判定。

    判定口径(以「错法」而非字节级输出为准，因为大脑/时间本就不确定)：
      · fixed       原来失败、现在退出码 0 —— 修好了。
      · reproduced  现在仍失败，且分流码与当初一致 —— 同一个病还在。
      · changed     仍失败但错法变了(分流码不同)，或原本就成功的案例 —— 现场已漂移。
    重跑只复刻命令与 stdin；不强行回灌当时的环境变量(那可能含已失效的密钥)，
    而是用此刻的真实环境，正是要看「在今天的代码与环境下还错不错」。
    """
    workdir = (_REPO_ROOT / case.cwd).resolve()
    code, _out, err = _run(case.command, workdir, None, case.stdin, timeout)
    new_code = errors.triage(stderr=err, exit_code=code,
                            message=" ".join(case.command)).get("code")
    old_code = case.error.get("code")

    if code == 0 and case.exit_code != 0:
        verdict, detail = "fixed", "原来失败，现在退出码 0 —— 修好了 🎉"
    elif code != 0 and case.exit_code == 0:
        verdict, detail = "changed", "案例当时是成功的，如今却失败了 —— 出现回归"
    elif code != 0 and new_code == old_code:
        verdict = "reproduced"
        detail = f"仍失败、分流码不变({new_code}) —— 同一个病还在，可照 hint 修"
    else:
        verdict = "changed"
        detail = f"仍失败但错法变了({old_code} → {new_code}) —— 现场已漂移"

    return ReplayResult(case_id=case.case_id, replayed_at=_now_iso(),
                        exit_code=code, error_code=new_code or "?",
                        verdict=verdict, detail=detail)


def replay_all(timeout: int = 300) -> list[ReplayResult]:
    """把全部案例当回归套依次重跑。"""
    out: list[ReplayResult] = []
    for meta in load_index():
        case = load_case(meta.get("case_id", ""))
        if case:
            out.append(replay(case, timeout))
    return out


def manifest() -> dict:
    """🎞️ 复现库清单：已捕获案例的可发现目录(纯数据，给能力层消费)。"""
    idx = load_index()
    return {"total": len(idx), "dir": str(REPLAY_DIR.relative_to(_REPO_ROOT)),
            "cases": idx}


# ── 渲染(给 CLI / 能力复用)────────────────────────────────────────────
def _short(cid: str) -> str:
    return cid[-15:] if len(cid) > 15 else cid


def render_list(idx: list[dict]) -> str:
    L = [f"🎞️ 失败复现库 · 共 {len(idx)} 个案例"]
    if not idx:
        L.append(f"   还没有案例(state/replay/ 为空)。")
        L.append("   现场捕获：python replay.py --capture -- <会失败的命令>")
        return "\n".join(L)
    for m in idx:
        L.append(f"  {_short(m.get('case_id', '?'))} · "
                 f"[{m.get('error_code', '?')}] 退出码 {m.get('exit_code')}\n"
                 f"        {m.get('title', '')}\n"
                 f"        $ {m.get('command', '')}")
    L.append("\n  用 `--show <案例号>` 摊开现场，`--replay <案例号>` 重跑验证，"
             "`--replay-all` 跑全套回归。")
    return "\n".join(L)


def render_case(c: Case) -> str:
    e = c.error
    L = [f"🎞️ 复现案例 · {c.case_id}",
         f"   {c.title}",
         f"   捕获于 {c.created_at} · 退出码 {c.exit_code} · "
         f"分流 {e.get('code')}（{e.get('domain')}）",
         "",
         f"▸ 命令：$ {' '.join(c.command)}",
         f"▸ 工作目录：{c.cwd}",
         "▸ 环境摘要：" + f"py{c.env.get('python')} · {c.env.get('git_branch')}"
         f"@{c.env.get('git_commit')} · {c.env.get('platform')}",
         "▸ OPENCRAB_* ：" + ("、".join(f"{k}={v}" for k, v in
                              c.env.get("opencrab", {}).items()) or "（无）")]
    if c.stdin is not None:
        L += ["", "▸ 输入(stdin)：", _indent(c.stdin)]
    L += ["", f"▸ 分流提示：{e.get('title')} —— 修复：{e.get('hint')}",
          "", "▸ 当时的 stderr(尾部)：", _indent(_tail(c.stderr))]
    L += ["", f"▸ 一键复现：bash {c.dir().relative_to(_REPO_ROOT)}/repro.sh",
          f"   或验证修没修好：python replay.py --replay {_short(c.case_id)}"]
    if c.note:
        L += ["", f"▸ 备注：{c.note}"]
    return "\n".join(L)


def render_result(r: ReplayResult) -> str:
    mark = _VERDICT_MARK.get(r.verdict, "·")
    return (f"  {mark} {_short(r.case_id)} · {r.verdict} · "
            f"退出码 {r.exit_code} · [{r.error_code}]\n        {r.detail}")


def _indent(s: str, prefix: str = "    | ") -> str:
    s = s.strip()
    return "\n".join(prefix + ln for ln in s.splitlines()) if s else "    （空）"


def _tail(s: str, n: int = 12) -> str:
    lines = s.strip().splitlines()
    return "\n".join(lines[-n:])


# ── CLI ─────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 失败案例打包与一键复现 🎞️ —— 把摔倒固化成可重跑可验证的案例")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--show", metavar="案例号", help="摊开一个案例的完整现场")
    g.add_argument("--replay", metavar="案例号", help="重跑这个案例，判定是否已修好")
    g.add_argument("--replay-all", action="store_true", help="全部案例回归式重跑")
    g.add_argument("--capture", action="store_true",
                   help="现场捕获：跑 -- 后的命令，失败则存成案例")
    ap.add_argument("--title", default="", help="(配合 --capture)给案例起个人话标题")
    ap.add_argument("--timeout", type=int, default=300, help="重跑/捕获的超时秒数")
    ap.add_argument("--json", action="store_true", help="机读输出")
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="(配合 --capture)-- 之后是要捕获的命令")
    args = ap.parse_args(argv)

    if args.capture:
        cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
        if not cmd:
            print("❌ --capture 需要在 -- 之后给出要跑的命令，例如："
                  "\n   python replay.py --capture -- python crab.py once")
            sys.exit(2)
        case, code = capture_run(cmd, title=args.title, timeout=args.timeout)
        if case is None:
            print(f"✅ 命令退出码 0，没有失败现场可捕获：$ {' '.join(cmd)}")
            return
        if args.json:
            print(json.dumps(case.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"🎞️ 已捕获案例 {case.case_id}（退出码 {code}）\n")
            print(render_case(case))
        return

    if args.show:
        case = load_case(args.show)
        if not case:
            print(f"❌ 找不到案例 {args.show!r}。用 `python replay.py` 看全部案例号。")
            sys.exit(1)
        print(json.dumps(case.to_dict(), ensure_ascii=False, indent=2)
              if args.json else render_case(case))
        return

    if args.replay:
        case = load_case(args.replay)
        if not case:
            print(f"❌ 找不到案例 {args.replay!r}。")
            sys.exit(1)
        r = replay(case, args.timeout)
        if args.json:
            print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"🎞️ 重放案例 {case.case_id}：")
            print(render_result(r))
        sys.exit(0 if r.verdict in ("fixed", "reproduced") else 1)

    if args.replay_all:
        results = replay_all(args.timeout)
        if args.json:
            print(json.dumps([r.to_dict() for r in results],
                            ensure_ascii=False, indent=2))
            return
        if not results:
            print("🎞️ 复现库为空，没有可回归的案例。")
            return
        n_fixed = sum(r.verdict == "fixed" for r in results)
        print(f"🎞️ 回归式重放 · 共 {len(results)} 个案例 · "
              f"已修好 {n_fixed} · 仍在摔 {len(results) - n_fixed}")
        for r in results:
            print(render_result(r))
        return

    # 无参数：列出全部案例
    idx = load_index()
    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
    else:
        print(render_list(idx))


if __name__ == "__main__":
    main()
