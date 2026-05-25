#!/usr/bin/env python3
"""自改前的对抗审查 🥊 —— 在动手之前，先替计划生成反例、滥用场景与失败断言，
逼它过一遍「红队」，而不是带着自信幻觉直接合并。

为什么要有它：planner.py 把目标拆成有依赖、有回退的多步路线，judge.py 在事后裁决
「这一步值不值」，policy.py 定「这一步怎么走」——但它们都默认计划是**善意且诚实**的。
这只螃蟹最危险的失败不是摔得很响，而是**摔得很安静**：

  · 自信幻觉——「我觉得这样更好」，却拿不出一个能证伪它的反例；
  · 古德哈特式假进步——指标涨了、真实能力没涨，因为计划优化的是「被测的那个数」，
    而不是「数背后想代表的东西」，于是刷分和真进步长得一模一样。

红队官不写实现、不替 judge 拍板，它只做一件事：**在计划被相信之前，尽力把它打趴**。
对一段计划文字（或 planner 的当前计划），它扫出风险信号，生成三类对抗物：

  · 反例(counterexample)  —— 一个能让该计划失效/回归的具体场景，「这种输入你扛得住吗」。
  · 滥用场景(abuse)        —— 这个改动/指标会被怎么钻空子、怎么误用、怎么刷分。
  · 失败断言(assertion)    —— 一条可证伪的检查：拿不出证据，就不算改进。

然后判定计划**过没过红队**。关键设计是「逼计划自己回答」：一条挑战，只有当计划文字里
**明确写了对应的缓解**（如反例输入、回退判据、指标背后的真实目标）才算「已答」；
凡是「致命」级且**没答**的挑战存在，就 blocked——不准带着没回答的对抗问题去自改。
这样红队不奖励嘴上漂亮，只奖励把坑写明白：把古德哈特挡在合并之前。

设计原则与 planner/judge 一致：零第三方依赖、纯标准库；只读不动手；审查报告落进被
.gitignore 的 state/redteam/，可回溯绝不反噬——红队自己出错也只吞掉，绝不成为新故障源。

用法:
    python redteam.py "<计划/改动的一段话>"     # 红队审查这段计划，打印报告 + 判定
    python redteam.py --plan                    # 抓 planner 当前在走的计划来审
    python redteam.py --file 计划.md            # 审查文件里的计划文字
    python redteam.py --recent                  # 回看最近几次审查
    python redteam.py --json                    # 机读输出
被 blocked 时退出码非 0（可当自改前的闸门：过不了红队就别合并）。

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_REDTEAM_DIR = _REPO_ROOT / "state" / "redteam"     # 落在被 .gitignore 的 state/ 里
_INDEX = _REDTEAM_DIR / "index.jsonl"

# 三类对抗物
COUNTEREXAMPLE = "counterexample"   # 🎯 一个能让计划失效的具体场景
ABUSE = "abuse"                     # 🩹 钻空子/刷分/误用
ASSERTION = "assertion"             # 📐 一条可证伪的检查
_KIND_MARK = {COUNTEREXAMPLE: "🎯", ABUSE: "🩹", ASSERTION: "📐"}

# 严重度（决定能否过闸）
FATAL = "致命"      # 没回答就 block
SERIOUS = "严重"    # 警告，不单独 block
NOTE = "提醒"       # 仅记一笔
_SEV_RANK = {FATAL: 3, SERIOUS: 2, NOTE: 1}
_SEV_MARK = {FATAL: "🔴", SERIOUS: "🟠", NOTE: "🟡"}


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ── 对抗物模型 ───────────────────────────────────────────────────────
@dataclasses.dataclass
class Challenge:
    """红队抛给计划的一条挑战：你不正面回答它，就别自信地说自己更好了。"""
    kind: str           # counterexample / abuse / assertion
    severity: str       # 致命 / 严重 / 提醒
    title: str          # 一句话挑战
    why: str            # 为什么这是个坑
    must_answer: str    # 计划要拿出什么(反例输入/判据/证据)才算答上
    answer_hints: list  # 计划文字里命中其中任一关键词，即视作「已答」
    trigger: str        # 命中的风险信号(哪个词/模式触发了它)；空=通用必答题
    answered: bool = False   # 审查时回填：计划是否已正面回答

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class RedTeamReport:
    """一次对抗审查的结论：抛出的挑战、哪些没答、过没过红队。"""
    created_at: str
    target: str                 # 被审查的计划文字
    source: str                 # 来源：arg / planner / file
    challenges: list            # list[Challenge]
    verdict: str                # blocked / pass-with-warnings / clear
    summary: str

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        return d

    def to_meta(self) -> dict:
        """给索引用的一行摘要(不含全文)。"""
        return {"created_at": self.created_at, "source": self.source,
                "verdict": self.verdict,
                "target": self.target[:80].replace("\n", " "),
                "n_challenges": len(self.challenges),
                "n_unanswered_fatal": sum(
                    1 for c in self.challenges
                    if _sev_of(c) == FATAL and not _answered_of(c))}


def _sev_of(c) -> str:
    return c.severity if isinstance(c, Challenge) else c.get("severity", "")


def _answered_of(c) -> bool:
    return c.answered if isinstance(c, Challenge) else bool(c.get("answered"))


# ── 攻击模式库 ───────────────────────────────────────────────────────
# 每条规则：在计划里命中 signals(任一正则)，就生成一条针对性挑战。
# answer_hints 是「计划写了这些词就算把坑填上」的判据——逼计划把缓解写明白。
@dataclasses.dataclass
class _Rule:
    signals: list       # 触发正则(命中任一即触发)
    kind: str
    severity: str
    title: str
    why: str
    must_answer: str
    answer_hints: list


_RULES: list[_Rule] = [
    _Rule(
        signals=[r"更快|提速|加速|faster|性能|perf|缓存|cache|并行|并发"],
        kind=COUNTEREXAMPLE, severity=SERIOUS,
        title="提速的代价记在哪了？给一个「更快但更错」的反例",
        why="只盯吞吐/耗时极易古德哈特：缓存可能返回脏数据、并发可能引入竞态，"
            "数字漂亮了，正确性悄悄塌了。",
        must_answer="拿出一个会因这次提速而结果出错的输入，并说明你如何同时守住正确性。",
        answer_hints=["正确性", "一致", "失效", "invalidate", "竞态", "race", "回退", "对比基线"]),
    _Rule(
        signals=[r"删除|移除|去掉|删掉|废弃|deprecat|remove|drop\b"],
        kind=COUNTEREXAMPLE, severity=FATAL,
        title="谁还在用你要删的东西？给一个会被这次删除打断的调用方",
        why="删除是不可逆动作，最怕「我以为没人用」——一个隐藏调用方就能让自改变成自残。",
        must_answer="列出对被删对象的全部引用(grep 过)，或说明为何确定无人依赖。",
        answer_hints=["引用", "调用方", "grep", "无人", "已确认", "搜索", "no longer used"]),
    _Rule(
        signals=[r"重试|retry|重连|reconnect|轮询|poll"],
        kind=ABUSE, severity=SERIOUS,
        title="重试会不会把一次失败放大成一场风暴？",
        why="无上限/无退避的重试，在下游真的挂了时会变成自我 DDoS，且会重复执行非幂等副作用。",
        must_answer="说明重试上限、退避策略，以及被重试的操作是否幂等。",
        answer_hints=["上限", "退避", "backoff", "幂等", "idempot", "最多", "max"]),
    _Rule(
        signals=[r"自动|无人值守|autonomous|无需人工|automatic"],
        kind=ABUSE, severity=FATAL,
        title="自动化跑偏时，谁来踩刹车？",
        why="去掉人工确认会放大每一个错误的影响半径；没有熔断的自动化，错一次就错一千次。",
        must_answer="给出熔断/限频条件与回退路径：什么情况下它该停下来等人。",
        answer_hints=["熔断", "限频", "停下", "回退", "人工", "上限", "kill", "circuit", "rollback"]),
    _Rule(
        signals=[r"指标|分数|评分|metric|score|通过率|准确率|覆盖率|coverage|排行|榜"],
        kind=ABUSE, severity=FATAL,
        title="这个指标会被怎么刷？说出「分涨了但能力没涨」长什么样",
        why="古德哈特定律：一旦某指标成了目标，它就不再是好指标。优化被测的数，"
            "和优化数背后想代表的真实能力，常常长得一模一样。",
        must_answer="指出这个指标背后真正想代表的能力，并给一个能刷高分却没真进步的做法。",
        answer_hints=["背后", "真实", "代表", "刷", "古德哈特", "goodhart", "对照", "holdout", "防刷"]),
    _Rule(
        signals=[r"总是|永不|一定|必然|绝不|100%|always|never|guarante|保证"],
        kind=COUNTEREXAMPLE, severity=SERIOUS,
        title="「总是/永不」这种绝对话，反例在哪？",
        why="绝对断言几乎都有边界情况：空输入、超长输入、并发、时钟回拨——总有一个能戳穿它。",
        must_answer="自己先举出一个最可能戳穿这句绝对话的边界输入，并说明它为何仍成立。",
        answer_hints=["边界", "空", "超长", "并发", "例外", "除非", "edge", "corner"]),
    _Rule(
        signals=[r"写入|落盘|保存|持久化|write|save|persist|文件|落档"],
        kind=COUNTEREXAMPLE, severity=SERIOUS,
        title="写到一半被 kill 了会怎样？",
        why="非原子写入遇到中断/并发会留下半截文件，下次读取直接坏档——记录反而成了故障源。",
        must_answer="说明写入是否原子(临时文件+rename)、坏档如何被容忍或修复。",
        answer_hints=["原子", "临时", "rename", "tmp", "容忍", "吞掉", "坏档", "atomic"]),
    _Rule(
        signals=[r"密钥|token|secret|password|api[_ ]?key|凭证|credential"],
        kind=ABUSE, severity=FATAL,
        title="这条路径会不会把密钥写进日志/案例/提交？",
        why="一旦秘密落进可回溯的产物或公开仓，撤回也来不及——它已经被缓存、被索引。",
        must_answer="说明密钥在日志/落档/输出里如何被打码或根本不落地。",
        answer_hints=["打码", "mask", "脱敏", "不落地", "redact", "末4位", "不写入"]),
    _Rule(
        signals=[r"合并|merge|推送|push|上云|发布|publish|main\b|主干"],
        kind=ASSERTION, severity=FATAL,
        title="合并前，凭什么证明它确实更好而不只是「跑通了」？",
        why="「能跑」不等于「更好」。不带前后对比就合并，正是假进步混进主干的入口。",
        must_answer="给出可验证的前后对照(基线 vs 新版)，而不仅是「自测通过」。",
        answer_hints=["基线", "对照", "对比", "前后", "回归", "baseline", "regression", "diff"]),
]


# ── 通用必答题（每个计划都要过的预先验尸）──────────────────────────────
# trigger 为空，永远附加；这是红队的「最低门槛」，与具体措辞无关。
_UNIVERSAL: list[Challenge] = [
    Challenge(
        kind=COUNTEREXAMPLE, severity=FATAL,
        title="最小反例：什么输入/场景能让这个计划失效？",
        why="说不出一个能证伪自己的反例，就说明还没真正想过它会怎么坏——这是自信幻觉的源头。",
        must_answer="写出一个具体的、会让该计划失败的输入或场景。",
        answer_hints=["反例", "如果", "比如", "假如", "当", "边界", "失败时", "会坏在"],
        trigger=""),
    Challenge(
        kind=ABUSE, severity=FATAL,
        title="古德哈特：这个计划在优化哪个『数』？它和真实目标会背离吗？",
        why="进化最隐蔽的失败是刷分式假进步——优化了被测指标，真实能力原地踏步甚至倒退。",
        must_answer="点明它优化的可测量目标，以及该目标与真实意图可能背离的方式。",
        answer_hints=["真实", "背后", "古德哈特", "goodhart", "代表", "意图", "不只是", "防刷"],
        trigger=""),
    Challenge(
        kind=ASSERTION, severity=FATAL,
        title="回退：如果它其实更糟，怎么发现、怎么退回去？",
        why="没有回退判据的改动，一旦变差就只能将错就错；可逆性是自改的安全带。",
        must_answer="给出『判定它变糟』的判据，以及一键退回的办法。",
        answer_hints=["回退", "revert", "退回", "回滚", "rollback", "判据", "发现", "撤回", "分支"],
        trigger=""),
    Challenge(
        kind=ASSERTION, severity=SERIOUS,
        title="不反噬：这个改动本身会不会成为新的故障源？",
        why="观测者/记录者一旦能让主流程崩，就比它想修的问题更危险。",
        must_answer="说明它出错时如何被隔离(吞异常/降级)，不拖垮调用它的主流程。",
        answer_hints=["吞", "降级", "隔离", "不抛", "绝不", "退化", "try", "容错", "观测者"],
        trigger=""),
]


def _norm(text: str) -> str:
    return (text or "").strip()


def _is_answered(hints: list, plan_lower: str) -> bool:
    """计划文字里命中任一缓解关键词，即视作这条挑战「已正面回答」。"""
    return any(h.lower() in plan_lower for h in hints)


def generate(plan_text: str) -> list[Challenge]:
    """对一段计划文字，生成全部对抗物（通用必答题 + 命中风险信号的针对性挑战）。

    只生成、不判定是否已答——那一步留给 review()，便于单独复用攻击库。
    """
    text = _norm(plan_text)
    out: list[Challenge] = []
    # 通用必答题：每个计划都要过的最低门槛（拷贝一份，避免回填污染模板）。
    for c in _UNIVERSAL:
        out.append(dataclasses.replace(c))
    # 针对性挑战：命中风险信号才追加。
    for rule in _RULES:
        hit = next((m.group(0) for pat in rule.signals
                    for m in [re.search(pat, text, re.I)] if m), None)
        if hit:
            out.append(Challenge(
                kind=rule.kind, severity=rule.severity, title=rule.title,
                why=rule.why, must_answer=rule.must_answer,
                answer_hints=list(rule.answer_hints), trigger=hit))
    return out


def review(plan_text: str, *, source: str = "arg") -> RedTeamReport:
    """红队审查：生成对抗物 → 看计划是否已正面回答每一条 → 判定过没过。

    判定口径：
      · blocked            存在「致命」级且**未回答**的挑战 —— 不准带着没答的对抗问题自改。
      · pass-with-warnings 致命的都答上了，但还有未答的「严重」挑战 —— 可走，先记下风险。
      · clear              所有致命与严重挑战都正面回答了 —— 这计划经得起一轮红队。
    """
    text = _norm(plan_text)
    plan_lower = text.lower()
    challenges = generate(text)
    for c in challenges:
        c.answered = _is_answered(c.answer_hints, plan_lower)

    unanswered = [c for c in challenges if not c.answered]
    fatal_open = [c for c in unanswered if c.severity == FATAL]
    serious_open = [c for c in unanswered if c.severity == SERIOUS]

    if fatal_open:
        verdict = "blocked"
        summary = (f"🔴 未过红队：{len(fatal_open)} 条致命挑战没有正面回答。"
                   f"先在计划里写明对它们的反例/判据/缓解，再来自改。")
    elif serious_open:
        verdict = "pass-with-warnings"
        summary = (f"🟠 险过：致命挑战都答上了，但还有 {len(serious_open)} 条严重挑战待答。"
                   f"可以走，但把这些风险记在案。")
    else:
        verdict = "clear"
        summary = "🟢 过红队：所有致命与严重挑战都被正面回答，这计划经得起一轮对抗。"

    report = RedTeamReport(created_at=_now_iso(), target=text, source=source,
                           challenges=challenges, verdict=verdict, summary=summary)
    _save(report)
    return report


# ── 持久化（落进 .gitignore 的 state/，绝不反噬）─────────────────────
def _save(report: RedTeamReport) -> bool:
    """把审查报告登记进索引；任何写盘异常都吞掉——红队自己不能成为新故障源。"""
    try:
        _REDTEAM_DIR.mkdir(parents=True, exist_ok=True)
        import jsonlstore
        jsonlstore.append_jsonl(_INDEX, report.to_meta())
        return True
    except Exception:
        return False


def recent(limit: int = 10) -> list[dict]:
    """回看最近几次审查的一行摘要（新的在后，符合 jsonl 追加顺序）。"""
    try:
        import jsonlstore
        return jsonlstore.read_jsonl(_INDEX)[-limit:]
    except Exception:
        return []


def manifest() -> dict:
    """🥊 红队清单：审查历史的可发现目录（纯数据，给能力层消费）。"""
    idx = recent(limit=10_000)
    blocked = sum(1 for m in idx if m.get("verdict") == "blocked")
    return {"total": len(idx), "blocked": blocked,
            "dir": str(_REDTEAM_DIR.relative_to(_REPO_ROOT)),
            "recent": idx[-10:]}


# ── 计划文字的来源 ───────────────────────────────────────────────────
def _plan_text_from_planner() -> tuple[str, str] | None:
    """把 planner 当前在走的计划摊成一段可审查的文字。"""
    try:
        import planner
        plan = planner.load_active()
    except Exception:
        return None
    if not plan:
        return None
    lines = [f"目标：{plan.goal}"]
    for s in plan.steps:
        fb = f"（回退：{s.fallback}）" if getattr(s, "fallback", "") else ""
        lines.append(f"- [{s.id}] {s.what}{fb}")
    return "\n".join(lines), "planner"


# ── 渲染 ─────────────────────────────────────────────────────────────
def render_report(r: RedTeamReport) -> str:
    L = [f"🥊 对抗审查 · {r.created_at} · 来源 {r.source}",
         f"   计划：{r.target.splitlines()[0][:72] if r.target else '(空)'}",
         ""]
    answered = [c for c in r.challenges if c.answered]
    open_ = [c for c in r.challenges if not c.answered]
    # 先列「没答上」的——这才是红队的产出重点。
    L.append(f"▸ 未回答的挑战（{len(open_)}）：")
    if not open_:
        L.append("    （全部正面回答了 👏）")
    for c in sorted(open_, key=lambda x: -_SEV_RANK.get(x.severity, 0)):
        mark = f"{_SEV_MARK.get(c.severity, '·')}{_KIND_MARK.get(c.kind, '')}"
        trig = f"  ⟵ 命中“{c.trigger}”" if c.trigger else "  ⟵ 通用必答题"
        L += [f"  {mark} [{c.severity}] {c.title}{trig}",
              f"        为什么：{c.why}",
              f"        要答上：{c.must_answer}"]
    if answered:
        L += ["", f"▸ 已正面回答（{len(answered)}，从略）：",
              "    " + "；".join(c.title[:24] for c in answered)]
    L += ["", f"▸ 判定：{r.verdict}", f"   {r.summary}"]
    return "\n".join(L)


def render_recent(rows: list[dict]) -> str:
    if not rows:
        return "🥊 还没有审查记录。先 `python redteam.py \"<计划>\"` 过一轮红队。"
    L = [f"🥊 最近 {len(rows)} 次对抗审查："]
    for m in rows:
        vmark = {"blocked": "🔴", "pass-with-warnings": "🟠", "clear": "🟢"}.get(
            m.get("verdict"), "·")
        L.append(f"  {vmark} {m.get('created_at')} · {m.get('verdict')} · "
                 f"挑战 {m.get('n_challenges')}（未答致命 "
                 f"{m.get('n_unanswered_fatal')}）\n        {m.get('target', '')}")
    return "\n".join(L)


# ── CLI ─────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 自改前的对抗审查 🥊 —— 生成反例/滥用/失败断言，逼计划过红队")
    ap.add_argument("plan", nargs="?", default="", help="要审查的计划/改动文字")
    ap.add_argument("--plan", dest="from_planner", action="store_true",
                    help="抓 planner 当前在走的计划来审")
    ap.add_argument("--file", metavar="路径", help="审查文件里的计划文字")
    ap.add_argument("--recent", action="store_true", help="回看最近几次审查")
    ap.add_argument("--json", action="store_true", help="机读输出")
    args = ap.parse_args(argv)

    if args.recent:
        rows = recent()
        print(json.dumps(rows, ensure_ascii=False, indent=2)
              if args.json else render_recent(rows))
        return

    # 确定计划文字的来源
    text, source = "", "arg"
    if args.from_planner:
        got = _plan_text_from_planner()
        if not got:
            print("❌ planner 没有在走的计划。先 `python planner.py \"<目标>\" --step ...` 起一份，"
                  "或直接把计划文字作为参数传进来。")
            sys.exit(2)
        text, source = got
    elif args.file:
        try:
            text = pathlib.Path(args.file).read_text("utf-8")
            source = "file"
        except Exception as e:
            print(f"❌ 读不了文件 {args.file!r}：{e}")
            sys.exit(2)
    elif args.plan:
        text = args.plan
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
        source = "stdin"

    if not _norm(text):
        print("❌ 没有可审查的计划。用法："
              "\n   python redteam.py \"把失败命令打包成可复现案例，自测通过就合并到 main\""
              "\n   python redteam.py --plan        # 审 planner 当前计划"
              "\n   python redteam.py --file 计划.md")
        sys.exit(2)

    report = review(text, source=source)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_report(report))
    # 被 blocked 时退出码非 0，方便当自改前的闸门
    sys.exit(1 if report.verdict == "blocked" else 0)


if __name__ == "__main__":
    main()
