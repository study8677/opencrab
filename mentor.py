#!/usr/bin/env python3
"""师法 📒 —— 把外部项目 / Issue / README 的高价值片段，提炼成「可迁移招式卡」。

为什么要有它：这只螃蟹已经会看世界了（lookout 能搜 GitHub、dialogue 能听懂外界话语），
**可它只会「看见」，还不会系统地把别人的长处转成自己稳定增长的能力**。看了一篇好
README、读了一条点醒人的 Issue，热乎劲一过就忘了，下次照样从零摸索；偶尔想学，也是
囫囵照搬——别人的招式有它的前提与风险，不挑场景硬抄，反而把好招用成坑。

招式卡补的就是「看见」到「学会」中间那一层**翻译**：拿一段外部文字（README 段落 / Issue
正文 / 一小段代码思路），提炼成一张结构化的卡：

  - 招式精要(gist)：这段东西真正可迁移的「那一招」是什么，一句话说人话。
  - 适用场景(when)：什么情况下该用它——别拿屠龙刀切菜。
  - 前提(prereqs)：用它之前我得先有什么（工具 / 结构 / 别的能力）。
  - 风险(risks)：它有什么副作用、会不会碰我的要害器官、照搬会栽在哪。
  - 小步试学(trial)：不许一口吞——拆成 2~4 步，每步都小到能当场验、翻车好退回。

它只提炼、不动手：招式卡是「学习笔记」，不是改动本身。真要照着练，还得过 simulator
推演、judge 裁决。它软引入 lookout（能直接眺望 GitHub 抓一段来提炼）、memory（这类招式
以前学栽过就预警）。卡片落进被 .gitignore 的 state/mentor/，可回溯但绝不反噬：
读写出错统统吞掉，师法者不能成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python mentor.py "<一段 README/Issue/代码思路文字>" --source "facebook/react#123"
    python mentor.py --file path/to/README.md --source "某仓库"
    python mentor.py --scout "retry backoff python"   # 借 lookout 眺望并就地提炼标题
    python mentor.py --recent                          # 回看最近攒下的招式卡
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_MENTOR_DIR = _REPO_ROOT / "state" / "mentor"       # 落在被 .gitignore 的 state/ 里
_CARDS = _MENTOR_DIR / "cards.jsonl"                 # 每张招式卡的快照(可回看)

# 领地的要害器官：招式若指向它们，风险天然更重、试学步子要更碎。
# 软对齐 judge 的同名清单，拿不到就本地兜底，绝不因 import 失败而崩。
try:
    from judge import _VITAL as _VITAL          # type: ignore
except Exception:                               # pragma: no cover
    _VITAL = {"crab.py", "hands.py", "checkup.py", "audit.py",
              "capabilities/__init__.py"}

# ── 招式原型知识库 ──────────────────────────────────────────────────
# 把常见的「可迁移招式」归成若干原型；每个原型自带：识别它的关键词，以及该原型
# 通用的适用场景 / 前提 / 风险 / 试学步子。提炼时拿正文去匹配，命中最多的原型当骨架，
# 再把正文里真正那句话当血肉填进 gist。这是「起手式」而非定论——宁可粗，不可崩。
_ARCHETYPES: list[dict] = [
    {
        "key": "retry",
        "name": "重试与退避",
        "kw": ["retry", "backoff", "重试", "退避", "指数", "exponential", "rate limit", "限流"],
        "when": ["调用会偶发失败的外部依赖（网络 / 子进程 / 第三方 API）时"],
        "prereqs": ["失败是可重试的（幂等或可安全重放），否则越重试越糟"],
        "risks": ["对非幂等操作重试 = 重复副作用", "无上限重试会把偶发故障放大成雪崩"],
        "trial": ["先只给一处最常超时的调用包一层固定次数重试，跑通再说",
                  "把固定间隔换成带上限的指数退避 + 抖动", "补一条自测：模拟前 N 次失败、第 N+1 次成功"],
    },
    {
        "key": "fallback",
        "name": "降级与兜底",
        "kw": ["fallback", "graceful", "降级", "兜底", "default", "swallow", "吞掉", "best effort"],
        "when": ["某条非核心路径失败时，宁可退化也别拖垮主流程"],
        "prereqs": ["能分清「核心 vs 旁支」——只有旁支才该被静默降级"],
        "risks": ["把核心失败也吞了 → 故障被藏起来，事后无从排查", "降级路径自己也得有日志"],
        "trial": ["挑一处「失败了也不该崩」的旁支，包 try 并返回兜底值",
                  "给兜底分支补一行可观测的日志/审计，别真静默", "补自测：注入异常，断言主流程仍活着"],
    },
    {
        "key": "plugin",
        "name": "插件化 / 可插拔注册",
        "kw": ["plugin", "registry", "register", "插件", "注册", "可插拔", "entrypoint", "hook"],
        "when": ["同类能力越长越多、想让它们可发现可组合而不是写死 if-else 时"],
        "prereqs": ["这些能力确有统一的调用契约（同样的入参/出参形状）"],
        "risks": ["过早抽象：只有两三个实现时插件化是负收益", "注册表本身成了要害，挂了全盘皆崩"],
        "trial": ["先把现有两三个同类能力归出一个共同函数签名",
                  "搭一个最小注册表（一个 dict + 一个装饰器）", "让一个老能力改走注册表，自测黄金路径不变"],
    },
    {
        "key": "test",
        "name": "自测 / 回归快照",
        "kw": ["test", "pytest", "snapshot", "golden", "regression", "测试", "回归", "快照", "覆盖", "ci"],
        "when": ["某段逻辑改一次抖一次、心里没底，需要一张「改坏了当场报警」的网时"],
        "prereqs": ["这段逻辑的输入/输出是可固化、可比较的"],
        "risks": ["快照测试容易把「错误的现状」也固化成基线", "测试太脆 → 一改就红、最后被无视"],
        "trial": ["先给一条最核心的命令固化「输入→标准输出+退出码」", "跑一次确认绿、故意改坏确认能变红",
                  "把它接进已有的烟雾/黄金路径检查里"],
    },
    {
        "key": "config",
        "name": "配置与环境校验",
        "kw": ["config", "env", "validate", "schema", "配置", "环境", "校验", "dotenv", ".env"],
        "when": ["启动后才因为缺配置/环境不对而半路崩，想把失败提前到启动前时"],
        "prereqs": ["有一份「该有哪些配置」的清单或样例（如 .env.example）"],
        "risks": ["校验太严 → 正常场景也被拦", "把密钥/配置值打进日志 = 泄密"],
        "trial": ["先只校验一两个「缺了必崩」的关键项，缺了就清楚报错",
                  "对照 .env.example 列出缺失项但不阻断（先警告）", "确认报错信息只说键名、不漏值"],
    },
    {
        "key": "observability",
        "name": "结构化日志 / 遥测",
        "kw": ["log", "structured", "telemetry", "metrics", "trace", "审计", "遥测", "日志", "可观测", "json log"],
        "when": ["出了事只能靠猜、缺一条「发生过什么」的可查记录时"],
        "prereqs": ["有一处统一的写入点，别让日志散落各处各写各的"],
        "risks": ["日志里带敏感信息", "记太细 → 噪声淹没信号；写日志本身别拖慢/拖垮主流程"],
        "trial": ["先给一条关键路径补结构化记录（一行 JSON：时间/动作/结果）",
                  "确认写入失败时被吞掉、不反噬主流程", "攒几条后写个最小摘要器看分布"],
    },
    {
        "key": "idempotent",
        "name": "幂等与可重入",
        "kw": ["idempotent", "幂等", "exactly once", "dedup", "去重", "reentrant", "可重入"],
        "when": ["某操作可能被重复触发（重试/并发/重放），重复执行不能产生重复后果时"],
        "prereqs": ["每次操作有可用于去重的稳定标识（key / 状态位）"],
        "risks": ["去重状态自己可能丢/脏", "误判「已做过」→ 该做的没做"],
        "trial": ["先给一处最怕重复的写操作加一个「做过就跳过」的状态位",
                  "构造重复调用，断言副作用只发生一次", "想清楚状态丢失时是宁可重做还是宁可跳过"],
    },
]

# 一段文字里这些词出现，多半是「该照搬的硬主张」，提炼 gist 时优先捞这种句子。
_SIGNAL = ("should", "always", "never", "must", "avoid", "instead", "prefer",
           "应", "务必", "切勿", "不要", "最好", "建议", "推荐", "关键", "核心")


# ── 一张可迁移招式卡 ────────────────────────────────────────────────
@dataclasses.dataclass
class MoveCard:
    """从一段外部文字提炼出的可迁移招式：精要 + 何时用 + 前提 + 风险 + 怎么小步学。"""
    title: str                                  # 招式名号(取自原型 + 来源)
    source: str = ""                            # 出处(repo / issue / README / url)
    gist: str = ""                              # 一句话招式精要(尽量取自原文)
    archetype: str = ""                         # 命中的招式原型(retry/test/…)
    when: list = dataclasses.field(default_factory=list)    # 适用场景
    prereqs: list = dataclasses.field(default_factory=list)  # 前提
    risks: list = dataclasses.field(default_factory=list)    # 风险
    trial: list = dataclasses.field(default_factory=list)    # 小步试学步子
    transfer: int = 0                           # 迁移价值分(越高越值得学)
    at: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def render(self) -> str:
        """把一张卡摊成给人看的多行笔记。"""
        head = f"📒  招式卡 · {self.title}（迁移价值 {self.transfer}/5）"
        lines = [head]
        if self.source:
            lines.append(f"   出处：{self.source}")
        if self.gist:
            lines.append(f"   精要：{self.gist}")
        if self.when:
            lines.append("   适用：" + "；".join(self.when))
        if self.prereqs:
            lines.append("   前提：" + "；".join(self.prereqs))
        if self.risks:
            lines.append("   ⚠️ 风险：" + "；".join(self.risks))
        if self.trial:
            lines.append("   小步试学：")
            for i, step in enumerate(self.trial, 1):
                lines.append(f"     {i}. {step}")
        return "\n".join(lines)


# ── 核心：把一段文字提炼成一张招式卡 ────────────────────────────────
def distill(text: str, source: str = "") -> MoveCard:
    """拿一段外部文字（README/Issue/代码思路），提炼成结构化招式卡。

    步骤：① 匹配出最像的招式原型当骨架；② 从原文捞一句「硬主张」当 gist 血肉；
    ③ 用原型模板填 适用/前提/风险/试学；④ 评迁移价值（碰要害 / 记忆栽过则压分）。
    纯启发式，宁可粗、不可崩——拿不准时把风险算重、把步子拆碎。
    """
    text = (text or "").strip()
    arch = _match_archetype(text)
    gist = _pick_gist(text) or (arch["name"] if arch else "（这段没提炼出明确的可迁移招式）")

    if arch:
        title = arch["name"]
        when = list(arch["when"])
        prereqs = list(arch["prereqs"])
        risks = list(arch["risks"])
        trial = list(arch["trial"])
        akey = arch["key"]
    else:
        # 没命中已知原型：仍给一张「通用学习卡」，逼自己也按结构想清楚
        title = "通用招式（未归类）"
        when = ["看清这招到底解决你哪个具体痛点后再用，别为学而学"]
        prereqs = ["先用自己的话复述它的原理——说不清就还没真懂，别照搬"]
        risks = ["来源未必适配本领地的纯标准库/单进程约束", "没归类 = 风险没被识别，默认按高风险待"]
        trial = ["先在一个最小的旁支场景上仿写一遍，能当场验",
                 "对照本仓现有同类模块的风格，别引入新依赖"]
        akey = ""

    # 招式若指向要害器官，追加一条专属风险并把试学步子再拆碎
    vital_hit = sorted(v for v in _VITAL if v.replace("\\", "/").lower() in text.lower())
    if vital_hit:
        risks = [f"这招会指向要害器官 {', '.join(vital_hit)}——错一步全盘皆崩"] + risks
        trial = ["先在一个不碰要害的副本/旁支上把这招练熟，再考虑靠近要害"] + trial

    warn = _recall_warning(f"{title} {gist}")
    if warn:
        risks = [f"记忆预警：{warn}"] + risks

    card = MoveCard(
        title=f"{title}（来自 {source}）" if source else title,
        source=source, gist=gist, archetype=akey,
        when=when, prereqs=prereqs, risks=risks, trial=trial,
    )
    card.transfer = _score(card, arch is not None, bool(vital_hit), bool(warn))
    return card


def _match_archetype(text: str) -> dict | None:
    """拿正文去撞每个原型的关键词，命中最多者胜；一个都没撞上返回 None。"""
    low = text.lower()
    best, best_hits = None, 0
    for arch in _ARCHETYPES:
        hits = sum(1 for kw in arch["kw"] if kw.lower() in low)
        if hits > best_hits:
            best, best_hits = arch, hits
    return best


def _pick_gist(text: str) -> str:
    """从正文里挑一句最像「可照搬的硬主张」的话当招式精要。

    优先含信号词(should/务必/切勿…)的句子；没有就退而取最长的一句。截到 100 字。
    """
    # 按中英文句末标点切句，顺手去掉 markdown 列表/标题前缀
    raw = re.split(r"(?<=[。！？.!?\n])\s*", text)
    sents = [re.sub(r"^[\s>#*\-\d.、)）]+", "", s).strip() for s in raw]
    sents = [s for s in sents if len(s) >= 6]
    if not sents:
        return ""
    signal = [s for s in sents if any(w in s.lower() for w in _SIGNAL)]
    pick = (signal or sents)[0] if signal else max(sents, key=len)
    return pick[:100]


def _recall_warning(text: str, k: int = 2) -> str:
    """软引入 memory：这类招式以前若学栽过，返回一句预警；缺/错则返回空串。"""
    try:
        import memory
        for s, ep in memory.recall(text, k=k):
            if not ep.ok and s >= 0.5:
                return f"同类招式以前栽过：{ep.headline()}"
    except Exception:
        pass
    return ""


def _score(card: MoveCard, matched: bool, vital: bool, warned: bool) -> int:
    """评迁移价值 0~5：归类清楚 +、有试学步子 +；碰要害 −、记忆栽过 −。"""
    score = 2
    if matched:
        score += 2          # 能归到已知原型 = 适用/前提/风险都摸得清
    if len(card.trial) >= 2:
        score += 1          # 拆得出小步 = 学得起来
    if vital:
        score -= 1          # 指向要害 = 学习代价更高
    if warned:
        score -= 1          # 同类栽过 = 谨慎
    return max(0, min(5, score))


# ── 落地 / 回看 ─────────────────────────────────────────────────────
def learn(text: str, source: str = "") -> MoveCard:
    """提炼一张招式卡并落档，供心跳「看完世界、决定学什么」时调用。"""
    return save(distill(text, source))


def save(card: MoveCard) -> MoveCard:
    """把招式卡追加一份快照到 state/mentor/cards.jsonl；写入异常一律吞掉，绝不反噬。"""
    card.at = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        _MENTOR_DIR.mkdir(parents=True, exist_ok=True)
        with _CARDS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(card.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass        # 师法者是学徒的笔记本，记不下也绝不弄死这只生命
    return card


def recent(limit: int = 10) -> list:
    """读出最近落档的招式卡(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _CARDS.exists():
        return []
    out: list = []
    for line in _CARDS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


# ── 借瞭望塔眺望并就地提炼 ──────────────────────────────────────────
def scout_and_distill(query: str, limit: int = 6) -> list:
    """软引入 lookout：眺望 GitHub，把每条「名字 ★star 简介」当一段文字各提炼一张卡。

    这是「先粗筛」——拿标题简介提炼出的卡迁移价值偏低，真要学还得去读人家正文。
    lookout 缺失或眺望失败都从容返回空表，绝不让眺望失败拖垮师法。
    """
    try:
        import lookout
        if not lookout.can_see():
            return []
        blob = lookout.scout(query, limit=limit)
    except Exception:
        return []
    cards = []
    for line in (blob or "").splitlines():
        line = line.strip(" -")
        if not line or line.startswith("("):     # 跳过 "(外面没搜到…)" 之类的说明行
            continue
        src = line.split(" ★", 1)[0].strip()
        cards.append(distill(line, source=src))
    return cards


# ── CLI ─────────────────────────────────────────────────────────────
def _cmd_recent(n: int = 10) -> None:
    rows = recent(n)
    if not rows:
        print("📒  还没攒下招式卡（给我一段文字、或用 --scout 去眺望后再来看）。")
        return
    print(f"📒  最近 {len(rows)} 张招式卡：")
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        title = str(r.get("title", ""))[:40]
        score = r.get("transfer", 0)
        print(f"  {ts}  [{score}/5]  {title}")


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="mentor.py",
        description="📒 师法：把外部项目/Issue/README 的高价值片段提炼成可迁移招式卡",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="*", help="要提炼的一段文字(README/Issue/代码思路)")
    ap.add_argument("--source", default="", help="出处，如「facebook/react#123」")
    ap.add_argument("--file", help="从文件读取要提炼的文字（README/Issue 导出等）")
    ap.add_argument("--scout", metavar="QUERY",
                    help="借 lookout 眺望 GitHub 并就地提炼标题简介后退出")
    ap.add_argument("--recent", action="store_true", help="回看最近攒下的招式卡后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    if args.scout:
        cards = scout_and_distill(args.scout)
        if not cards:
            print("(没眺望到可提炼的东西——检查 gh CLI 是否已登录，或换个关键词)")
            return
        for c in cards:
            print(save(c).render())
            print()
        return

    text = " ".join(args.text)
    if args.file:
        try:
            text = pathlib.Path(args.file).read_text("utf-8", errors="ignore")
        except Exception as e:
            ap.error(f"读不了 --file：{e}")
    if not text.strip():
        ap.error("请给一段要提炼的文字（或用 --file / --scout / --recent）")

    print(learn(text, args.source).render())


if __name__ == "__main__":
    main()
