#!/usr/bin/env python3
"""进化剧本层 📖 —— 把反复用到的进化目标，编成可执行、可验收、可回滚、带证据入口的剧本。

为什么要有它：这套领地里「怎么干一件事」的经验，过去散在各模块的脑子里——
新增一个模块要先存快照、写契约、补烟雾用例、过 health 再并入；修一条回归得先复现、
再定位、改完跑 regression 验收；能力证据过期了要回 evidence 复证……这些套路我**每次
都隐隐记得**，却没有一处把它写成「照着做就对」的清单。经验若只活在记忆里，就会随上下文
丢失、换个分支就忘、慌起来漏步骤。

本层把常见进化目标钉成一本本**剧本(Playbook)**，每本回答四个问题：

  · 🪜 **步骤(steps)** —— 照着做的有序动作；能自动跑的配一条 argv，手动的只留提示。
  · ✅ **验收(acceptance)** —— 一条「跑得通才算干完」的命令，退出码 0 = 这本剧本达成了。
  · 🪂 **回滚(rollback)** —— 万一搞砸，怎么确定地退回去(多半指向 `rollback.py` 的退路)。
  · 🧾 **证据入口(evidence)** —— 干完后这条能力的证据记在哪(指向 `evidence.py` 的声明名)。

剧本写在代码里，是单一真相源(像 contracts / evidence)。它不替你执行整套自改——那是
`crab.py` 的活；它是**事前查得到、事中照得做、事后对得上**的行动说明书。每本剧本点名的
命令与证据都必须**真实存在**：`--quiet` 会校验完整性(引用的 .py 在不在、证据声明对不对得上)，
任意一处对不上就让退出码非零，可挂进钩子 / CI 当门禁——剧本不能教人跑一条根本不存在的命令。

用法：
    python playbook.py                 # 列全部剧本：每本一行目标小结
    python playbook.py NAME            # 摊开一本剧本：步骤 / 验收 / 回滚 / 证据
    python playbook.py NAME --check    # 跑这本剧本的验收命令，报「达成 / 未达成」
    python playbook.py --quiet         # 只在剧本有破损时说话(完整性门禁，适合钩子 / CI)
    python playbook.py --json          # 机读：导出全部剧本

零第三方依赖，纯标准库。校验只读不改盘，验收命令起不来也只是「这次没验成」，绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ACCEPT_TIMEOUT = 180          # 验收命令的墙钟上限(秒)：剧本不该把生命拖死
_PY = [sys.executable]


@dataclasses.dataclass(frozen=True)
class Step:
    """剧本里的一步：一句要做什么 + 可选的、能当场跑的命令。"""
    title: str                # 这一步干什么(一句话)
    hint: str = ""            # 补充说明 / 为什么这么做
    argv: list[str] | None = None   # 能自动跑就配命令；纯手动的步留 None

    def to_meta(self) -> dict:
        return {"title": self.title, "hint": self.hint, "argv": self.argv}


@dataclasses.dataclass(frozen=True)
class Playbook:
    """一本进化剧本：一个常见目标 + 步骤 + 验收 + 回滚 + 证据入口。"""
    name: str                 # 剧本名(主键)
    goal: str                 # 这本剧本要达成什么
    when: str                 # 什么时候该翻开它
    steps: list[Step]         # 有序动作
    acceptance: list[str]     # 验收命令(argv)：退出码 0 = 达成
    rollback: str             # 搞砸了怎么退回去(多半指向 rollback.py)
    evidence: str             # 干完后证据记在哪(evidence.py 的声明名，或一句说明)

    def to_meta(self) -> dict:
        return {"name": self.name, "goal": self.goal, "when": self.when,
                "steps": [s.to_meta() for s in self.steps],
                "acceptance": self.acceptance, "rollback": self.rollback,
                "evidence": self.evidence}


# ── 剧本清单：单一真相源 ──────────────────────────────────────────────
# 每本都把领地里**真实存在、能当场跑**的命令编进步骤与验收；证据入口点名 evidence.py
# 里真实的声明。把一类经验沉淀成可复用行动，就在这里新增一本。
PLAYBOOKS: list[Playbook] = [
    Playbook(
        name="add-module",
        goal="新增一个进化模块：从构思到安全并入主干",
        when="想给领地添一块新能力(一个新的 *.py 层)时",
        steps=[
            Step("自改前存快照、备好回滚脚本",
                 "先有退路再动手——这是 intent 的红线",
                 _PY + ["rollback.py", "--snapshot", "新增模块"]),
            Step("写模块本体",
                 "纯标准库、零第三方依赖；观测者绝不反噬生命；带 --quiet/--json"),
            Step("给它补一条能当场复跑的契约/烟雾用例",
                 "新能力要能被 contracts / smoke 点名守住"),
            Step("把它的「跑得通」证明登记进证据账本",
                 "在 evidence.py 的 CLAIMS 里加一条声明 + 验证命令"),
            Step("过一遍领地自检",
                 "语法/导入/结构/契约/烟雾全绿才算稳",
                 _PY + ["health.py", "--quiet"]),
        ],
        acceptance=_PY + ["health.py", "--quiet"],
        rollback="跑 `python rollback.py --rehearse` 验证退路，必要时执行回滚脚本退回快照",
        evidence="health",
    ),
    Playbook(
        name="fix-regression",
        goal="修一条回归失败：从复现到验收回绿",
        when="regression / smoke / contracts 报出某条历史用例重新破了时",
        steps=[
            Step("先跑一遍回归，看清到底哪条破了",
                 "拿到失败现场再动手，别凭印象猜",
                 _PY + ["regression.py"]),
            Step("自改前存快照", "修 bug 也是自改，先备退路",
                 _PY + ["rollback.py", "--snapshot", "修回归"]),
            Step("定位并改正", "改最小的面，别顺手重构放大爆炸半径"),
            Step("跑验收：那条用例回绿、且没带新破其它",
                 "regression 全过才算修干净",
                 _PY + ["regression.py", "--quiet"]),
        ],
        acceptance=_PY + ["regression.py", "--quiet"],
        rollback="改不动就 `python rollback.py --rehearse` 后执行回滚脚本，退回干净状态再想",
        evidence="regression",
    ),
    Playbook(
        name="refresh-evidence",
        goal="刷新过期/失守的能力证据：让「我会什么」重新算数",
        when="evidence.py 报出 🟡过期 / 🔴失守 / ⚪未证 的声明时",
        steps=[
            Step("看清哪几条声明证据不足",
                 "账本会标出每条的新鲜度",
                 _PY + ["evidence.py"]),
            Step("逐条复证：真的把验证命令跑一遍、追进账本",
                 "🔴失守说明能力真塌了，得先修回来再复证",
                 _PY + ["evidence.py", "--verify"]),
            Step("修复任何复证没跑通的能力", "证据不是补签字，是把东西修到真能跑"),
        ],
        acceptance=_PY + ["evidence.py", "--quiet"],
        rollback="无需回滚——本剧本只复跑验证、只追加账本，不改动任何代码",
        evidence="evidence 账本本身：复证后全 🟢 即达成",
    ),
    Playbook(
        name="safe-self-edit",
        goal="安全地自改一个模块：快照 → 改 → 验收 → 兜底回滚",
        when="每天那次自我进化、要动任何已有模块时(通用打底剧本)",
        steps=[
            Step("自改前存快照、生成回滚脚本",
                 "未经验证的改动不并入主干——先有退路",
                 _PY + ["rollback.py", "--snapshot"]),
            Step("演练一次回滚，确认退路真能跑通",
                 "退路写在纸上不算数，临时克隆里验过才算",
                 _PY + ["rollback.py", "--rehearse"]),
            Step("做改动", "面越小越好；保持零依赖、观测者不反噬生命的底线"),
            Step("过领地自检验收",
                 "全绿再交给 crab 提交/推送",
                 _PY + ["health.py", "--quiet"]),
        ],
        acceptance=_PY + ["health.py", "--quiet"],
        rollback="自检没过别提交；执行快照目录里的回滚脚本，`git reset --hard` 退回 HEAD",
        evidence="health",
    ),
]

_BY_NAME = {p.name: p for p in PLAYBOOKS}


# ── 完整性校验：剧本点名的命令 / 证据必须真实存在 ─────────────────────
def _referenced_pyfile(argv: list[str] | None) -> str | None:
    """从一条 argv 里认出它指向的领地 .py 文件名(认不出则 None)。

    形如 [python, "foo.py", ...] → "foo.py"；`-m`、`-c` 等非文件入口不算。
    """
    if not argv or len(argv) < 2:
        return None
    cand = argv[1]
    if cand.endswith(".py") and "/" not in cand and "\\" not in cand:
        return cand
    return None


def _evidence_claim_names() -> set[str] | None:
    """取 evidence.py 里登记的声明名集合；evidence 不可用时返回 None(跳过这项校验)。"""
    try:
        import evidence  # noqa: PLC0415  —— 仅在校验时按需导入，无副作用
        return {c.name for c in evidence.CLAIMS}
    except Exception:  # noqa: BLE001  —— 拿不到就不强校验，校验者绝不反噬
        return None


def check_integrity(playbooks: list[Playbook] | None = None) -> list[str]:
    """校验每本剧本是否「言之有物」：引用的 .py 在不在、证据声明对不对得上。

    返回问题清单(空 = 全都对得上)。全程只读，绝不改盘、不跑命令。
    """
    playbooks = PLAYBOOKS if playbooks is None else playbooks
    claim_names = _evidence_claim_names()
    problems: list[str] = []

    for pb in playbooks:
        # 步骤与验收里点名的每个 .py 都得真实存在
        argvs = [s.argv for s in pb.steps] + [pb.acceptance]
        for argv in argvs:
            fname = _referenced_pyfile(argv)
            if fname and not (REPO_ROOT / fname).exists():
                problems.append(f"{pb.name}：点名了不存在的命令 `{fname}`")
        # 验收命令不能为空——没有验收的剧本说不清「干完没」
        if not pb.acceptance:
            problems.append(f"{pb.name}：缺验收命令(说不清何时算达成)")
        # 证据入口若写成「某条 evidence 声明名」，那条声明得真存在
        if claim_names is not None and pb.evidence in _LOOKS_LIKE_CLAIM:
            if pb.evidence not in claim_names:
                problems.append(
                    f"{pb.name}：证据入口点名了 evidence 里没有的声明 `{pb.evidence}`")
    return problems


# evidence 入口写成单个标识符(无空格/无标点)时，按「声明名」对账；否则视作自由说明，不强校验。
_LOOKS_LIKE_CLAIM = {p.evidence for p in PLAYBOOKS
                     if p.evidence and " " not in p.evidence and "：" not in p.evidence}


# ── 验收：跑一本剧本的验收命令 ────────────────────────────────────────
def run_acceptance(pb: Playbook) -> tuple[bool, str]:
    """跑一本剧本的验收命令，返回 (是否达成, 现场原文)。命令起不来也只是「这次没达成」。"""
    try:
        proc = subprocess.run(
            pb.acceptance, cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=ACCEPT_TIMEOUT,
        )
        ok = proc.returncode == 0
        detail = "" if ok else (proc.stderr or proc.stdout or "").strip()[-500:]
        return ok, detail
    except subprocess.TimeoutExpired:
        return False, f"验收命令超过 {ACCEPT_TIMEOUT}s 未结束"
    except Exception as e:  # noqa: BLE001  —— 验收是观测者，起不来也只是没验成
        return False, f"{type(e).__name__}: {e}"


# ── 展示 ──────────────────────────────────────────────────────────────
def _fmt_argv(argv: list[str] | None) -> str:
    if not argv:
        return ""
    # 把 [python, "foo.py", ...] 显示成 `python foo.py ...`，省掉解释器绝对路径
    return "python " + " ".join(argv[1:]) if argv[0] == sys.executable else " ".join(argv)


def _print_list(playbooks: list[Playbook]) -> None:
    print(f"📖 opencrab 进化剧本（{len(playbooks)} 本）\n")
    for pb in playbooks:
        print(f"  • {pb.name} —— {pb.goal}")
        print(f"      何时翻开：{pb.when}")
    print(f"\n  摊开某本：python playbook.py NAME ；验收某本：python playbook.py NAME --check")


def _print_one(pb: Playbook) -> None:
    print(f"📖 {pb.name} —— {pb.goal}\n")
    print(f"  何时翻开：{pb.when}\n")
    print("  🪜 步骤：")
    for i, s in enumerate(pb.steps, 1):
        print(f"    {i}. {s.title}")
        if s.hint:
            print(f"       （{s.hint}）")
        if s.argv:
            print(f"       $ {_fmt_argv(s.argv)}")
    print(f"\n  ✅ 验收：$ {_fmt_argv(pb.acceptance)}  （退出码 0 = 达成）")
    print(f"  🪂 回滚：{pb.rollback}")
    print(f"  🧾 证据入口：{pb.evidence}")


def manifest() -> dict:
    """导出纯数据：全部剧本(给 health / 外部工具消费)。"""
    return {"playbooks": [p.to_meta() for p in PLAYBOOKS]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 进化剧本 📖")
    ap.add_argument("name", nargs="?", help="要摊开/验收的剧本名(省略=列全部)")
    ap.add_argument("--check", action="store_true",
                    help="跑指定剧本的验收命令，报达成/未达成")
    ap.add_argument("--quiet", action="store_true",
                    help="只在剧本有破损时输出(完整性门禁，适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出全部剧本(机读)")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    # --quiet：完整性门禁。每本剧本都言之有物才算过，有破损即非零退出。
    if args.quiet:
        problems = check_integrity()
        if problems:
            print("⚠️  剧本完整性有破损：")
            for p in problems:
                print(f"  · {p}")
            sys.exit(1)
        sys.exit(0)

    # 指定了剧本名：摊开它，或跑它的验收
    if args.name:
        pb = _BY_NAME.get(args.name)
        if pb is None:
            print(f"⚠️  没有名为 {args.name!r} 的剧本；可选："
                  f"{'、'.join(_BY_NAME)}")
            sys.exit(2)
        if args.check:
            print(f"📖 验收剧本 {pb.name}：$ {_fmt_argv(pb.acceptance)}\n")
            ok, detail = run_acceptance(pb)
            if ok:
                print(f"  ✅ 达成 —— {pb.goal}")
                sys.exit(0)
            print(f"  ❌ 未达成 —— {pb.goal}")
            if detail:
                print(f"     现场：{detail.splitlines()[-1][:160]}")
            print(f"     退路：{pb.rollback}")
            sys.exit(1)
        _print_one(pb)
        return

    # 无参数：列全部剧本，并顺带提示完整性
    _print_list(PLAYBOOKS)
    problems = check_integrity()
    if problems:
        print(f"\n⚠️  {len(problems)} 处剧本破损，跑 `python playbook.py --quiet` 看详情")
        sys.exit(1)


if __name__ == "__main__":
    main()
