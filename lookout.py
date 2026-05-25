#!/usr/bin/env python3
"""
opencrab 的瞭望塔 🔭 —— 「看外面 + 把看到的学进来」这件事的单一入口：借本机
已登录的 gh CLI 看 GitHub 找灵感，并把高价值片段就地提炼成「可迁移招式卡」。

它一直闭门造车、只盯着自己（自检/诊断/审计）。瞭望塔让它在决定
"今天做什么"之前，先看看 GitHub 上同类项目在做什么，从外部世界
汲取真正新颖的方向，而不是在自我维护里反复打磨。

可只会「看见」还不够——看了一篇好 README、读了一条点醒人的 Issue，热乎劲一过
就忘了，下次照样从零摸索。所以瞭望塔不止有眼睛，还自带「看见→学会」那层**翻译**：
`distill` 把一段外部文字（README 段落 / Issue 正文 / 一小段代码思路）提炼成一张
结构化招式卡——精要(gist)/适用(when)/前提(prereqs)/风险(risks)/小步试学(trial)——
落进被 .gitignore 的 state/mentor/cards.jsonl，可回看但绝不反噬：读写出错统统吞掉。

它只提炼、不动手：招式卡是「学习笔记」，不是改动本身；真要照着练，还得过 arena
推演、judge 裁决。外界学习于是收口成一条链路：瞭望塔(lookout)既是最底层那只
「眼睛」（所有 gh 调用收口到 `gh_json` 单一闸门 + `can_see` 单一探活），又是把看到的
转成稳定本事的「学徒笔记本」。上层的需求信号市场(market 听 issue/PR)、策展(curator)、
竞技场(arena)不再各自 shell gh 或各自提炼，而是软引入这里，缺 gh 就一处退化。

零第三方依赖：借本机已登录的 gh CLI 搜 GitHub，纯标准库提炼招式卡。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import shutil
import subprocess

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_MENTOR_DIR = _REPO_ROOT / "state" / "mentor"       # 落在被 .gitignore 的 state/ 里
_CARDS = _MENTOR_DIR / "cards.jsonl"                 # 每张招式卡的快照(可回看)

# ── 需求信号市场的落地点(原 market.py，已并入瞭望塔) ────────────────
_MARKET_DIR = _REPO_ROOT / "state" / "market"        # 同样落在被 .gitignore 的 state/ 里
_MARKET_FILE = _MARKET_DIR / "market.json"           # 当前行情(聚好的信号，单一真相)
_RAW_FILE = _MARKET_DIR / "raw.jsonl"                # 历次收来的原始声音(可回溯的流水)

# 各口外部井的「来源权重」——外人主动开口最值钱，自家提交讨论与写明的使命再次之
_SOURCE_WEIGHT = {"issue": 1.0, "pr": 0.8, "commit": 0.4, "readme": 0.3}
_SOURCE_LABEL = {"issue": "🐛 issue", "pr": "🔀 PR", "commit": "📝 提交讨论", "readme": "📖 README"}

_HALF_LIFE_DAYS = 30.0      # 时间衰减半衰期：越近的声音越重，约一个月减半
_CLUSTER_SIM = 0.34         # 两条声音相似度过此线就归为同一条需求信号
_MAX_RAW_KEEP = 400         # 原始流水最多留这么多条，免得 state 无限膨胀

# 这些词太泛，聚主题时当噪声滤掉(中英混排)
_STOP = {"the", "and", "for", "with", "this", "that", "you", "are", "but", "not",
         "add", "fix", "use", "self", "evolve", "进化", "一个", "我要", "我想", "因为",
         "可以", "需要", "把", "让", "的", "了", "和", "与", "在", "是", "它", "我"}

# 领地的要害器官：招式若指向它们，风险天然更重、试学步子要更碎。
# 软对齐 judge 的同名清单，拿不到就本地兜底，绝不因 import 失败而崩。
try:
    from judge import _VITAL as _VITAL          # type: ignore
except Exception:                               # pragma: no cover
    _VITAL = {"crab.py", "hands.py", "checkup.py", "audit.py",
              "capabilities/__init__.py"}


def can_see() -> bool:
    """瞭望塔能不能用（gh CLI 在不在）。看外面的能力探活，全仓只此一处。"""
    return shutil.which("gh") is not None


def gh_json(args: list[str], timeout: int = 30) -> tuple[list, str]:
    """对 gh 的单一闸门：跑一条 `gh <args> --json …` 只读命令，返回 (行, 说明)。

    所有「看外面」的 gh 调用都收口到这里——没装/没登录/超时/坏档都从容返回
    `([], 一句人话说明)`，绝不抛异常，让任何上层调用方都能一处退化。
    """
    if not can_see():
        return [], "(瞭望塔失明：未找到 gh CLI)"
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
        if out.returncode != 0:
            return [], f"(gh 失败：{(out.stderr or '').strip()[:90]})"
        rows = json.loads(out.stdout or "[]")
        return (rows if isinstance(rows, list) else []), ""
    except Exception as e:
        return [], f"(gh 出错：{e})"


def scout(query: str, limit: int = 6) -> str:
    """搜 GitHub 仓库，返回 名字 ★star 简介 的摘要。失败不抛异常，返回说明。"""
    repos, note = gh_json(
        ["search", "repos", query, "--limit", str(limit), "--sort", "stars",
         "--json", "fullName,stargazersCount,description"])
    if note:
        return note
    if not repos:
        return "(外面没搜到相关项目)"
    lines = []
    for r in repos:
        desc = (r.get("description") or "").strip().replace("\n", " ")[:72]
        lines.append(f"    - {r.get('fullName','?')} ★{r.get('stargazersCount',0)} {desc}")
    return "\n".join(lines)


def search_code(query: str, limit: int = 5) -> str:
    """更深一层：搜 GitHub 上的代码片段（看别人具体怎么实现）。"""
    hits, note = gh_json(
        ["search", "code", query, "--limit", str(limit), "--json", "repository,path"])
    if note:
        return note
    lines = [f"    - {h.get('repository',{}).get('nameWithOwner','?')}/{h.get('path','?')}"
             for h in hits]
    return "\n".join(lines) or "(没搜到相关代码)"


def harvest(kind: str, limit: int = 40) -> list[dict]:
    """收一类外部声音的原始行：`gh <issue|pr> list`，返回 number/title/body/createdAt。

    这是市场(market)收 issue/PR 行情时的取水口——收口到瞭望塔，免得它再各 shell
    一遍 gh。没装/没登录/不是 GitHub 仓都从容返回空表。
    """
    if kind not in ("issue", "pr"):
        return []
    rows, _ = gh_json([kind, "list", "--state", "all", "--limit", str(limit),
                       "--json", "number,title,body,createdAt"])
    return rows


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
        pass        # 招式卡是学徒的笔记本，记不下也绝不弄死这只生命
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


def scout_and_distill(query: str, limit: int = 6) -> list:
    """眺望 GitHub，把每条「名字 ★star 简介」当一段文字各提炼一张卡。

    这是「先粗筛」——拿标题简介提炼出的卡迁移价值偏低，真要学还得去读人家正文。
    眺望失败都从容返回空表，绝不让眺望失败拖垮提炼。
    """
    if not can_see():
        return []
    blob = scout(query, limit=limit)
    cards = []
    for line in (blob or "").splitlines():
        line = line.strip(" -")
        if not line or line.startswith("("):     # 跳过 "(外面没搜到…)" 之类的说明行
            continue
        src = line.split(" ★", 1)[0].strip()
        cards.append(distill(line, source=src))
    return cards


# ╔══════════════════════════════════════════════════════════════════╗
# ║ 需求信号市场 📡（原 market.py，并入瞭望塔）                          ║
# ║ 把外界零散声音(issue/PR/README/提交讨论)聚成可比价的「行情」，校准   ║
# ║ 这只生命「该为世界变强在哪」，而不是只照镜子越练越窄。它只听与定价， ║
# ║ 软推头部需求进 missionboard，读写出错统统吞掉——耳朵绝不成故障源。   ║
# ╚══════════════════════════════════════════════════════════════════╝
def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _recency_decay(at: str, now: datetime.datetime | None = None) -> float:
    """据声音的年龄做指数衰减(半衰期 30 天)；解析不了时间就当此刻(不衰减)。"""
    now = now or datetime.datetime.now()
    try:
        t = datetime.datetime.fromisoformat(at[:19])
        age = max(0.0, (now - t).total_seconds() / 86400.0)
        return 0.5 ** (age / _HALF_LIFE_DAYS)
    except Exception:
        return 1.0


def _tokens(text: str) -> set[str]:
    """中英混合词袋：英文词 + 单个中文字，滤掉太泛的停用词——给没有 memory 时兜底聚类。"""
    words = re.findall(r"[a-z0-9]{2,}", (text or "").lower())
    hans = re.findall(r"[一-鿿]", text or "")
    return {w for w in (words + hans) if w not in _STOP}


def _similar(a: str, b: str) -> float:
    """两条声音有多像：软调 memory.similarity(中英混合 Jaccard)，拿不到就退化成自家词袋。"""
    try:
        from memory import similarity as _sim
        return _sim(a, b)
    except Exception:
        ta, tb = _tokens(a), _tokens(b)
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        return inter / len(ta | tb) if inter else 0.0


def _run(cmd: list[str], timeout: int = 20) -> str:
    """跑一条只读命令收外部声音；任何失败(没装/没登录/超时)都从容退化成空串。"""
    try:
        p = subprocess.run(cmd, cwd=str(_REPO_ROOT), capture_output=True,
                           text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


# ── 一条原始声音 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Voice:
    """从某口外部井收来的一条原始声音：是谁说的、说了啥、什么时候说的。"""
    source: str             # issue / pr / commit / readme
    text: str               # 这条声音的正文(标题+摘要)
    ref: str = ""           # 出处标识(issue 号 / 提交短哈希 等)
    at: str = ""            # 这条声音的时间(ISO，缺则按收取时刻)

    def weight(self, now: datetime.datetime | None = None) -> float:
        """这条声音此刻的份量 = 来源权重 × 时间衰减。"""
        base = _SOURCE_WEIGHT.get(self.source, 0.3)
        return base * _recency_decay(self.at, now)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一条需求信号(一群指向同一诉求的声音) ───────────────────────────
@dataclasses.dataclass
class Signal:
    """市场上的一条需求信号：一群相近声音聚成的「世界想要什么」，连同它此刻的出价。"""
    theme: str                                              # 一句话主题(取最具代表性的那条声音)
    voices: list = dataclasses.field(default_factory=list)  # list[Voice]，支撑这条信号的声音

    @property
    def price(self) -> float:
        """出价：所有支撑声音的份量之和——复现越多、越新、越外部，价越高。"""
        return round(sum(v.weight() for v in self.voices), 3)

    @property
    def sources(self) -> list[str]:
        """这条信号被哪些口井提到过(去重、按权重降序)——跨井复现是「真需求」的强证据。"""
        seen = {v.source for v in self.voices}
        return sorted(seen, key=lambda s: _SOURCE_WEIGHT.get(s, 0), reverse=True)

    def to_dict(self) -> dict:
        return {"theme": self.theme, "price": self.price,
                "sources": self.sources, "voices": [v.to_dict() for v in self.voices]}

    def render(self) -> str:
        srcs = "、".join(_SOURCE_LABEL.get(s, s) for s in self.sources)
        cross = " 🔁跨井" if len(self.sources) > 1 else ""
        head = f"[{self.price:>5.2f}] {self.theme}（{len(self.voices)} 声 · {srcs}{cross}）"
        sample = self.voices[0].ref if self.voices and self.voices[0].ref else ""
        return head + (f"\n          ↳ 例：{sample}" if sample else "")


# ── 一整个市场 ──────────────────────────────────────────────────────
@dataclasses.dataclass
class Market:
    """需求信号市场：把零散声音聚成的所有信号，按出价排着的一张行情牌。"""
    signals: list = dataclasses.field(default_factory=list)      # list[Signal]
    updated_at: str = ""

    def ranked(self) -> list[Signal]:
        return sorted(self.signals, key=lambda s: s.price, reverse=True)

    def to_dict(self) -> dict:
        return {"updated_at": self.updated_at,
                "signals": [s.to_dict() for s in self.ranked()]}

    def render(self, top: int | None = None) -> str:
        ranked = self.ranked()
        shown = ranked[:top] if top else ranked
        when = (self.updated_at or _now())[:16].replace("T", " ")
        lines = [f"📡 需求信号市场 · {len(ranked)} 条信号 · {when}", ""]
        if not ranked:
            lines.append("   （行情空着——外部井都没声音，或 `gh` 没装/没登录。")
            lines.append("    用 `python lookout.py --market --harvest` 重收一遍，或先去仓库开个 issue。）")
            return "\n".join(lines)
        lines.append("   行情牌（出价越高 = 世界越需要、越值得为它变强）：")
        for s in shown:
            lines.append("   " + s.render())
        if top and len(ranked) > top:
            lines.append(f"\n   …… 还有 {len(ranked) - top} 条更轻的信号(用 --top 调多少)。")
        top1 = ranked[0]
        lines.append(f"\n   👉 当下世界最想要：「{top1.theme}」"
                     "——`python lookout.py --market --seed` 可软推进 missionboard 机会池。")
        return "\n".join(lines)


# ── 外部井：各自从容退化，缺一口不影响其余 ──────────────────────────
def _harvest_github(kind: str, limit: int = 40) -> list[Voice]:
    """读 issue / PR 的外部声音——直接走本模块的 `harvest` 闸门(瞭望塔即唯一的眼睛)。

    没装 gh、没登录、不是 GitHub 仓都从容返回空，绝不在市场里再各 shell 一遍 gh。
    """
    try:
        rows = harvest(kind, limit=limit)
    except Exception:
        return []
    src = "issue" if kind == "issue" else "pr"
    voices: list[Voice] = []
    for r in rows:
        title = str(r.get("title", "")).strip()
        body = str(r.get("body", "") or "")[:280].strip()
        if not title:
            continue
        voices.append(Voice(source=src, text=(title + " " + body).strip(),
                            ref=f"#{r.get('number', '?')} {title}"[:80],
                            at=str(r.get("createdAt", ""))))
    return voices


def _harvest_commits(limit: int = 60) -> list[Voice]:
    """读最近提交的标题+正文当「提交讨论」；非 git 仓 / 出错都从容返回空。"""
    out = _run(["git", "log", f"-{limit}", "--no-merges",
                "--pretty=format:%H%x1f%cI%x1f%s%x1f%b%x1e"])
    if not out:
        return []
    voices: list[Voice] = []
    for rec in out.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 3:
            continue
        h, ci, subj = parts[0], parts[1], parts[2]
        body = parts[3] if len(parts) > 3 else ""
        text = (subj + " " + body[:200]).strip()
        if not text:
            continue
        voices.append(Voice(source="commit", text=text,
                           ref=f"{h[:8]} {subj}"[:80], at=ci))
    return voices


def _harvest_readme() -> list[Voice]:
    """读 README 里写明的使命/承诺当一类「世界对它的期待」；缺文件从容返回空。"""
    voices: list[Voice] = []
    for name in ("README.md", "CONTRIBUTING.md"):
        f = _REPO_ROOT / name
        try:
            text = f.read_text("utf-8", errors="ignore")
        except Exception:
            continue
        # 只取标题行(# / ## 开头)——那是写明的意图，信息密度最高
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#"):
                title = s.lstrip("#").strip()
                if len(title) >= 4:
                    voices.append(Voice(source="readme", text=title,
                                       ref=f"{name}: {title}"[:80], at=_now()))
    return voices


def harvest_voices() -> list[Voice]:
    """把所有外部井收来的声音汇成一摊原始素材；任一口井缺席都不影响其余。"""
    voices: list[Voice] = []
    voices += _harvest_github("issue")
    voices += _harvest_github("pr")
    voices += _harvest_commits()
    voices += _harvest_readme()
    return voices


# ── 把零散声音聚成需求信号 ──────────────────────────────────────────
def cluster(voices: list[Voice]) -> list[Signal]:
    """把相近的声音贪心地归成同一条需求信号：每条新声音并进最像的既有信号，
    都不够像就自立一条。代表主题取该信号里最早(或最具体)的那条声音文本。"""
    signals: list[Signal] = []
    # 重的声音先安家，让出价高的诉求优先定主题
    for v in sorted(voices, key=lambda x: x.weight(), reverse=True):
        best, best_sim = None, 0.0
        for s in signals:
            sim = _similar(v.text, s.theme)
            if sim > best_sim:
                best, best_sim = s, sim
        if best is not None and best_sim >= _CLUSTER_SIM:
            best.voices.append(v)
        else:
            signals.append(Signal(theme=_theme_of(v), voices=[v]))
    return signals


def _theme_of(v: Voice) -> str:
    """给一条信号起个一句话主题：取声音正文的头一句/前 60 字，去掉收尾噪声。"""
    text = re.split(r"[。.\n]", v.text.strip(), maxsplit=1)[0].strip()
    return (text or v.text.strip())[:60] or "(未命名需求)"


# ── 落地 / 读取(单一真相，原地更新) ───────────────────────────────
def market_load() -> Market:
    """读出当前行情；文件缺失/坏档都从容退化成空市场，绝不抛异常打断心跳。"""
    if not _MARKET_FILE.exists():
        return Market()
    try:
        data = json.loads(_MARKET_FILE.read_text("utf-8", errors="ignore"))
    except Exception:
        return Market()
    signals: list[Signal] = []
    for d in (data.get("signals") or []):
        try:
            voices = [Voice(source=str(vd.get("source", "")), text=str(vd.get("text", "")),
                            ref=str(vd.get("ref", "")), at=str(vd.get("at", "")))
                      for vd in (d.get("voices") or [])]
            if voices:
                signals.append(Signal(theme=str(d.get("theme", "")), voices=voices))
        except Exception:
            continue        # 坏掉的那条跳过，别让一条脏数据废掉整张行情
    return Market(signals=signals, updated_at=str(data.get("updated_at", "")))


def market_save(market: Market) -> Market:
    """把行情原地写回 state/market/market.json；写入异常一律吞掉，绝不反噬。"""
    try:
        _MARKET_DIR.mkdir(parents=True, exist_ok=True)
        _MARKET_FILE.write_text(
            json.dumps(market.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass        # 市场是耳朵，落档失败也绝不弄死这只生命
    return market


def _log_raw(voices: list[Voice]) -> None:
    """把这趟收来的原始声音追加进可回溯的流水，并裁掉过老的条目防止膨胀。"""
    try:
        _MARKET_DIR.mkdir(parents=True, exist_ok=True)
        stamp = _now()
        lines = [json.dumps({"harvested_at": stamp} | v.to_dict(), ensure_ascii=False)
                 for v in voices]
        old = _RAW_FILE.read_text("utf-8", errors="ignore").splitlines() \
            if _RAW_FILE.exists() else []
        kept = (old + lines)[-_MAX_RAW_KEEP:]
        _RAW_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except Exception:
        pass


# ── 软推头部需求进 missionboard(缺席从容退化) ──────────────────────
def seed_missionboard(market: Market, limit: int = 3) -> list[str]:
    """把出价最高的几条需求软推进 missionboard 机会池；missionboard 缺席/撞车都从容跳过。

    这是市场唯一一处「越过耳朵身份去推一把」的动作：只往机会池投，不排位、
    不替 judge 判完工——把「世界要什么」喂给既有的投资组合流控，由它去权衡。
    """
    pushed: list[str] = []
    try:
        import planner
        board = planner.load_board()
    except Exception:
        return pushed
    for s in market.ranked()[:max(1, limit)]:
        # 出价越高→价值越高(夹到 0~5)；跨井复现的当更值钱
        value = min(5, 2 + round(s.price) + (1 if len(s.sources) > 1 else 0))
        try:
            before = len(board.missions)
            m = board.add(s.theme, value=value, novelty=3,
                          source="market", why=f"外部需求信号(出价{s.price}，来源：{'/'.join(s.sources)})")
            if len(board.missions) > before:        # 真新增了(没被撞车去重)才记一笔
                pushed.append(m.id)
        except Exception:
            continue
    try:
        planner.save_board(board)
    except Exception:
        pass
    return pushed


def market_tick(fetch: bool = True) -> Market:
    """收一遍外部声音 → 聚成信号 → 落档，供心跳「听一听世界要什么」时调用。

    fetch=False 时不调外部井，仅就已存行情重排重打(给离线 / 省 token 的场景)。
    """
    if not fetch:
        return market_load()
    voices = harvest_voices()
    _log_raw(voices)
    market = Market(signals=cluster(voices), updated_at=_now())
    return market_save(market)


# ── CLI ─────────────────────────────────────────────────────────────
def _cmd_market(args: argparse.Namespace) -> None:
    """`lookout.py --market …`：收行情 / 看行情 / 软推 missionboard。"""
    market = market_tick(fetch=not args.no_fetch)
    if args.seed:
        pushed = seed_missionboard(market)
        if pushed:
            print("📡  已把 " + str(len(pushed)) + " 条头部需求软推进 missionboard 机会池："
                  + "、".join(pushed))
        else:
            print("📡  没往 missionboard 推新需求（缺席、行情空、或都已在册）。")
        print("")
    print(market.render(top=args.top))


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
        prog="lookout.py",
        description="🔭 瞭望塔：看 GitHub 找灵感，并把高价值片段提炼成可迁移招式卡",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="*", help="要提炼的一段文字(README/Issue/代码思路)")
    ap.add_argument("--source", default="", help="出处，如「facebook/react#123」")
    ap.add_argument("--file", help="从文件读取要提炼的文字（README/Issue 导出等）")
    ap.add_argument("--scout", metavar="QUERY",
                    help="眺望 GitHub 并就地提炼标题简介后退出")
    ap.add_argument("--look", metavar="QUERY",
                    help="只眺望 GitHub 仓库（名字 ★star 简介），不提炼")
    ap.add_argument("--recent", action="store_true", help="回看最近攒下的招式卡后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    if args.look:
        print(f"🔭 眺望「{args.look}」:\n{scout(args.look)}")
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
        # 没给文字也没给子命令：退回老瞭望塔的默认行为，眺望一句默认查询
        q = "autonomous self-improving AI agent"
        print(f"🔭 眺望「{q}」:\n{scout(q)}")
        return

    print(learn(text, args.source).render())


if __name__ == "__main__":
    main()
