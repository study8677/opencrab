#!/usr/bin/env python3
"""事后裁决官 ⚖️ —— 对每一次自我进化做「值不值得并进主干」的复盘判决。

为什么要有它：这只螃蟹已经会看健康(checkup)、会记教训(memory)、会眺望(lookout)、
会动手(hands)，可它**不会系统地判断「这次进化到底值不值」**。每次心跳都把改动
丢在分支上「养着」，凭一句模糊的「确认真让自己更好再并主干」就拍板——可「更好」
从没被量过。于是好改动和噪声改动一样躺在分支里，靠感觉合并，迟早把领地越养越肿。

裁决官补的就是这一层：拿变更前后的两张快照 + 爪子的产出(diffstat / 自测结果)，
沿四个维度算「净收益」，给出一句能落地的判词——**该并、该再养养、还是该退回**：

  - 能力(capability)：长出新本事了吗？(新 .py / 新技能 / 新日志)——越长越好。
  - 风险(risk)：动了要害器官吗？自测过了吗？改动面是不是大到失控？——越低越好。
  - 复杂度(complexity)：净增了多少行？是凭空堆码还是真长功能？——克制为美。
  - 验证覆盖(verification)：这次改动被自测/自检兜住了吗？——没人兜的改动不敢并。

它绝不为「好看的数字」放水(古德哈特陷阱)：自测没过 = 一票否决，要害器官被动且
没验证 = 压成「再养养」。判决落进被 .gitignore 的 state/judge/verdicts.jsonl，
可回溯，但绝不反噬——读写出错统统吞掉，裁决官不能成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python judge.py            # 裁决当前分支 vs 主干(git diff)，打印判词
    python judge.py --base main --head HEAD
    python judge.py --recent   # 回看最近几次落档的判决
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import subprocess

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_JUDGE_DIR = _REPO_ROOT / "state" / "judge"        # 落在被 .gitignore 的 state/ 里
_VERDICTS = _JUDGE_DIR / "verdicts.jsonl"

# 领地的要害器官：动它们风险天然更高，没自测兜底就别想轻易并主干。
_VITAL = {"crab.py", "hands.py", "checkup.py", "audit.py", "capabilities/__init__.py"}

# 单文件「巨改」阈值：一口气改这么多行，复审成本与回归风险都陡升。
_BIG_FILE_LINES = 400
# 单次改动「失控面」阈值：碰这么多文件，多半一次想干太多事。
_WIDE_FILES = 12

# 三种判决
MERGE = "merge"      # ✅ 净收益清楚，且有验证兜底 —— 可并进主干
HOLD = "hold"        # 🟡 方向对但还没站稳 —— 留分支再养养 / 补验证
REJECT = "reject"    # ❌ 净亏或没人兜底 —— 退回，别污染主干


# ── 一次裁决的产物 ──────────────────────────────────────────────────
@dataclasses.dataclass
class Verdict:
    """一次进化的事后判决：四维评分 + 净收益 + 一句能落地的判词。"""
    decision: str                       # MERGE / HOLD / REJECT
    net: int                            # 四维净收益(可正可负)
    scores: dict                        # {维度: 分} —— 能力/风险/复杂度/验证
    reasons: list                       # 每条评分背后的人话理由
    headline: str                       # 一句话判词
    at: str = ""                        # ISO 时间戳(落档时补上)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def render(self) -> str:
        """把判决摊成给人看的多行报告。"""
        mark = {MERGE: "✅ 可并主干", HOLD: "🟡 留分支再养养",
                REJECT: "❌ 退回，别并"}.get(self.decision, self.decision)
        lines = [f"⚖️  裁决：{mark}（净收益 {self.net:+d}）", f"   {self.headline}", ""]
        lines.append("   四维评分：")
        for dim, label in _DIM_LABELS.items():
            lines.append(f"     {label:<10} {self.scores.get(dim, 0):+d}")
        if self.reasons:
            lines.append("   依据：")
            lines += [f"     - {r}" for r in self.reasons]
        return "\n".join(lines)


_DIM_LABELS = {"capability": "能力", "risk": "风险",
               "complexity": "复杂度", "verification": "验证覆盖"}


# ── 解析 diffstat：从爪子产出里量出「改了什么、改了多少」 ──────────────
_SUMMARY_RE = re.compile(
    r"(\d+)\s+files?\s+changed"
    r"(?:,\s*(\d+)\s+insertions?\(\+\))?"
    r"(?:,\s*(\d+)\s+deletions?\(-\))?")
_FILE_RE = re.compile(r"^\s*(\S+)\s*\|\s*(\d+)\s")


@dataclasses.dataclass
class DiffStat:
    """一次改动的体量：碰了哪些文件、各加减多少行、汇总增删。"""
    files: dict                         # 路径 -> 该文件变动行数(diffstat 的中间那列)
    insertions: int = 0
    deletions: int = 0

    @property
    def n_files(self) -> int:
        return len(self.files)

    @property
    def churn(self) -> int:
        """总「翻动量」= 增 + 删，衡量复审成本与回归面。"""
        return self.insertions + self.deletions

    def touches_vital(self) -> list:
        """这次碰到的要害器官(规范化成正斜杠路径再比对)。"""
        return sorted(f for f in self.files
                      if f.replace("\\", "/") in _VITAL)


def parse_diffstat(text: str) -> DiffStat:
    """把 `git diff --stat` / 爪子记下的 diffstat 文本解析成 DiffStat。

    容忍残缺：解析不出的行直接跳过，汇总行缺增/删时按 0 计。
    """
    files: dict = {}
    ins = dels = 0
    for line in (text or "").splitlines():
        m = _SUMMARY_RE.search(line)
        if m:
            ins = int(m.group(2) or 0)
            dels = int(m.group(3) or 0)
            continue
        fm = _FILE_RE.match(line)
        if fm:
            files[fm.group(1)] = int(fm.group(2))
    return DiffStat(files=files, insertions=ins, deletions=dels)


def _git_diffstat(base: str, head: str) -> str:
    """跑一条只读 git，拿 base..head 的 diffstat；失败返回空串。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "diff", "--stat", f"{base}...{head}"],
            capture_output=True, text=True, timeout=15)
        return out.stdout.strip()
    except Exception:
        return ""


# ── 核心：四维评分 → 判决 ───────────────────────────────────────────
def judge(before: dict | None, after: dict | None, diff: DiffStat, *,
          selftest_ok: bool | None = None,
          checkup_ok: bool | None = None) -> Verdict:
    """沿能力/风险/复杂度/验证四维给这次进化打分，凝成一句判词。

    入参都可缺省：拿不到快照就只凭 diff 与验证结果判，宁可保守(偏 HOLD)，
    也绝不在信息不足时轻率说「可并」。

    - selftest_ok: 爪子自测过没过(None=没自测)。一票否决靠它。
    - checkup_ok:  跑没跑过 checkup 自检(None=没跑)。
    """
    before = before or {}
    after = after or {}
    scores: dict = {}
    reasons: list = []

    # ① 能力：长出新本事了吗(新文件/新技能/新日志都算往外长)
    cap = 0
    d_py = after.get("py_files", 0) - before.get("py_files", 0)
    d_skill = after.get("skills", 0) - before.get("skills", 0)
    if d_py > 0:
        cap += 2
        reasons.append(f"长出 {d_py} 个新模块（能力 +2）")
    elif d_py < 0:
        cap -= 1
        reasons.append(f"少了 {-d_py} 个模块——是瘦身还是误删？（能力 -1）")
    if d_skill > 0:
        cap += 1
        reasons.append(f"沉淀 {d_skill} 张新技能卡（能力 +1）")
    if cap == 0 and diff.churn:
        # 没新模块/技能，但确有改动：算「打磨现有能力」，给半分认可
        cap += 1
        reasons.append("打磨现有能力（无新模块，能力 +1）")
    scores["capability"] = cap

    # ② 风险：动要害 + 改动面失控 + 自测没过
    risk = 0
    vital = diff.touches_vital()
    if vital:
        risk -= 1
        reasons.append(f"动了要害器官 {', '.join(vital)}（风险 -1）")
    if diff.n_files >= _WIDE_FILES:
        risk -= 1
        reasons.append(f"一次碰了 {diff.n_files} 个文件，面太宽（风险 -1）")
    big = [f for f, n in diff.files.items() if n >= _BIG_FILE_LINES]
    if big:
        risk -= 1
        reasons.append(f"单文件巨改：{', '.join(big)}（风险 -1）")
    if selftest_ok is False:
        risk -= 3
        reasons.append("自测没过——这是硬伤（风险 -3）")
    scores["risk"] = risk

    # ③ 复杂度：净增行越多越要警惕「凭空堆码」；删多于增的瘦身值得鼓励
    cx = 0
    net_lines = diff.insertions - diff.deletions
    if net_lines <= 0 and diff.churn:
        cx += 1
        reasons.append(f"净行数 {net_lines:+d}，越改越精炼（复杂度 +1）")
    elif net_lines > _BIG_FILE_LINES * 2:
        cx -= 1
        reasons.append(f"净增 {net_lines} 行，复杂度膨胀（复杂度 -1）")
    scores["complexity"] = cx

    # ④ 验证覆盖：有没有人兜住这次改动
    ver = 0
    if selftest_ok is True:
        ver += 2
        reasons.append("自测通过，改动有兜底（验证 +2）")
    elif selftest_ok is None:
        ver -= 1
        reasons.append("没跑自测，改动没人兜（验证 -1）")
    if checkup_ok is True:
        ver += 1
        reasons.append("checkup 自检通过（验证 +1）")
    elif checkup_ok is False:
        ver -= 2
        reasons.append("checkup 自检没过（验证 -2）")
    scores["verification"] = ver

    net = sum(scores.values())
    decision, headline = _decide(net, scores, diff, selftest_ok, checkup_ok)
    return Verdict(decision=decision, net=net, scores=scores,
                   reasons=reasons, headline=headline)


def _decide(net: int, scores: dict, diff: DiffStat,
            selftest_ok: bool | None, checkup_ok: bool | None) -> tuple[str, str]:
    """把四维评分收敛成一条判决 + 一句判词。硬规则先行，再看净收益。"""
    # 硬否决：自测/自检明确没过，绝不并主干(不给数字开后门)
    if selftest_ok is False or checkup_ok is False:
        return REJECT, "验证没过就是没站稳——退回分支修好再来，别拿主干当试验场。"
    # 没有任何实质改动：无可裁决
    if not diff.files:
        return HOLD, "这次没改动任何文件，无从裁决净收益，先留着观察。"
    # 动了要害器官却没自测兜底：宁可再养养
    if diff.touches_vital() and selftest_ok is not True:
        return HOLD, "改到了要害器官却没自测兜底，先补上验证再谈合并。"
    if net >= 3:
        return MERGE, "能力净增清楚、又有验证兜底，这次进化值得并进主干。"
    if net >= 1:
        return HOLD, "方向对、净收益偏薄，留分支再养养或补强验证后再并。"
    return REJECT, "净收益不正——复杂度/风险吃掉了能力增益，退回重想。"


# ── 落地 / 回看 ─────────────────────────────────────────────────────
def record(verdict: Verdict, *, intent: str = "", branch: str = "") -> Verdict:
    """把判决落进 state/judge/verdicts.jsonl；任何写入异常都吞掉，绝不反噬。"""
    verdict.at = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        _JUDGE_DIR.mkdir(parents=True, exist_ok=True)
        row = verdict.to_dict() | {"intent": intent.split("\n")[0][:120],
                                   "branch": branch}
        with _VERDICTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass   # 裁决官是观测者，落档失败也绝不弄死这只生命
    return verdict


def recent(limit: int = 10) -> list:
    """读出最近落档的判决(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _VERDICTS.exists():
        return []
    out: list = []
    for line in _VERDICTS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


# ── 给 crab 调用的便捷入口：从一次心跳的产物直接出判词 ────────────────
def judge_proposal(intent: str, before: dict | None, after: dict | None,
                   proposal: dict | None) -> Verdict:
    """从 crab 一次心跳的 (意图, 前快照, 后快照, 爪子 proposal) 直接裁决并落档。

    proposal 里能认得的字段都尽量用上，认不得就当缺省——保持对 hands 产物
    结构演变的宽容。
    """
    proposal = proposal or {}
    diff = parse_diffstat(proposal.get("diffstat", ""))
    # hands 自测结果的几种可能命名，能认一个是一个
    selftest = proposal.get("selftest_ok")
    if selftest is None:
        selftest = proposal.get("tests_ok")
    v = judge(before, after, diff,
              selftest_ok=selftest,
              checkup_ok=proposal.get("checkup_ok"))
    return record(v, intent=intent, branch=proposal.get("branch", ""))


# ── CLI ─────────────────────────────────────────────────────────────
def _cmd_recent(n: int = 10) -> None:
    rows = recent(n)
    if not rows:
        print("⚖️  还没有落档的判决（心跳一次、或用 judge_proposal(...) 后再来看）。")
        return
    print(f"⚖️  最近 {len(rows)} 次裁决：")
    mark = {MERGE: "✅", HOLD: "🟡", REJECT: "❌"}
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        head = (r.get("intent") or r.get("headline", ""))[:46]
        print(f"  {ts} {mark.get(r.get('decision'), '?')} 净{r.get('net', 0):+d}  {head}")


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="judge.py",
        description="⚖️ 事后裁决官：判这次进化值不值得并进主干",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="main", help="对比基准(默认 main)")
    ap.add_argument("--head", default="HEAD", help="待裁决的版本(默认 HEAD)")
    ap.add_argument("--recent", action="store_true", help="回看最近落档的判决后退出")
    ap.add_argument("--no-checkup", action="store_true",
                    help="跳过现场 checkup 自检(默认会跑一次给验证维度打分)")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    diff = parse_diffstat(_git_diffstat(args.base, args.head))
    if not diff.files:
        print(f"⚖️  {args.base}...{args.head} 之间没有改动，无从裁决。")
        return

    # 现场跑一次 checkup，给验证维度一个真实信号(可 --no-checkup 关掉)
    checkup_ok: bool | None = None
    if not args.no_checkup:
        try:
            import checkup
            checkup_ok = checkup.main(["--quiet"]) in (0, None)
        except SystemExit as e:        # checkup 用退出码表态
            checkup_ok = (e.code in (0, None))
        except Exception:
            checkup_ok = None

    try:
        from capabilities import cap_snapshot
        after = cap_snapshot.take()
    except Exception:
        after = None
    # 命令行裁决里没有「改动前快照」，只凭 diff + 验证判，自然偏保守。
    v = judge(None, after, diff, checkup_ok=checkup_ok)
    print(f"⚖️  裁决 {args.base}...{args.head}：碰 {diff.n_files} 文件 · "
          f"+{diff.insertions}/-{diff.deletions} 行\n")
    print(v.render())


if __name__ == "__main__":
    main()
