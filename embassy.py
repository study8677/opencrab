#!/usr/bin/env python3
"""对外协作使馆 🤝 —— 把这只生命的进化目标自动整理成可发布的 GitHub Issue / Discussion /
PR 评论**草稿**，并把外界回到这些话题上的回复吸收成「下一步行动」，软推回使命看板。
使馆同时是这只生命的那只**耳朵 👂**：把外界的一段表达（用户的话 / issue 文本 / 复盘评论）
听成结构——需求、约束、情绪、待确认问题，再据此生成下一步的**追问**与**回应草稿**。
倾听与对外协作本是同一条链路（先听懂、再开口），合在一处少一层模块边界、少一份格式漂移。

为什么要有它：这只螃蟹已经会**看世界**（market 把外界声音聚成需求行情）、会**内部编排**
（missionboard 排投资组合、planner 起路线、delegate 拆并行）——可这两端之间缺一座桥：它
**听得见**世界，却还不会稳定地**主动开口**向世界发起一次高质量协作。于是常见的失灵是
**闷头进化**：自认为重要的方向从不拿出去问一句，做完才发现没人需要、或早有人踩过坑；
偶尔想发声，又是一句没头没尾的「我想做 X」，既不讲清动机、也不给回应的人一个抓手。

使馆补的正是这层**对外协作的礼仪与闭环**：

  - ✍️ 把进化目标整理成**可发布的草稿**：从 missionboard（进行中/机会池）与 market（头部
    需求信号）取题，按题目的形态择体裁——拿不准、想征集意见的 → 💬 Discussion；挂在某条
    既有 issue/PR 上的 → 💭 PR/issue 评论；要正式立项推进的 → 🐛 Issue。每份草稿都带齐
    「背景—我想做什么—想请教/请帮的点」三段式，让接收方一眼能接得住。
  - 👂 把回复**吸收成下一步行动**：软调 `gh` 读这些话题上**别人**留下的评论（滤掉自言自语），
    把表态/异议/补充蒸馏成一句句「下一步」，软推回 missionboard 机会池（来源记 embassy），
    让真实反馈进到既有的投资组合流控里去排——协作这才形成闭环，而非自说自话。

它只**起草与吸收**，**绝不替你按下发布键**：发布是**对外动作**，须由人（或将来明确授权的
通道）拍板——使馆备好措辞得体的草稿摆在案上，发不发、怎么发，留给外面那只手。草稿与吸收
记录落进被 .gitignore 的 state/embassy/，读写出错统统吞掉——对外的嘴，绝不能成为新的故障源。

零第三方依赖，纯标准库（读 issue/PR 评论经 `gh` 子进程，缺则从容退化）。

用法:
    python embassy.py                      # 据当前目标整理草稿后打印使馆案头
    python embassy.py --draft              # 重新据 missionboard/market 起草并打印
    python embassy.py --show ID            # 看某份草稿的完整可发布正文
    python embassy.py --absorb             # 读外界回复，蒸馏成下一步软推回 missionboard
    python embassy.py --top 5              # 只看最该先发出去的 5 份草稿
    python embassy.py --listen "<一段话>"  # 👂 把一段外界表达听成需求/约束/情绪 + 追问 + 回应草稿
    echo "<很长的反馈>" | python embassy.py --listen -   # 从标准输入读
    python embassy.py --heard              # 👂 回看最近几次倾听
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import subprocess
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_EMBASSY_DIR = _REPO_ROOT / "state" / "embassy"         # 落在被 .gitignore 的 state/ 里
_DRAFTS_FILE = _EMBASSY_DIR / "drafts.json"             # 当前案头的草稿(单一真相，原地更新)
_ABSORB_FILE = _EMBASSY_DIR / "absorbed.jsonl"          # 历次吸收来的外界回复(可回溯流水)
_DIALOGUE_DIR = _REPO_ROOT / "state" / "dialogue"       # 倾听落档(亦在被 .gitignore 的 state/ 里)
_CALLS = _DIALOGUE_DIR / "calls.jsonl"

# 三种体裁——按「想从世界拿到什么」分：征意见、挂讨论、正式立项
ISSUE, DISCUSSION, COMMENT = "issue", "discussion", "comment"
_KIND_LABEL = {ISSUE: "🐛 Issue", DISCUSSION: "💬 Discussion", COMMENT: "💭 评论"}

_MAX_DRAFTS = 12            # 案头最多摆这么多份草稿，多了人也发不过来——只留最该发的
_MAX_ABSORB_KEEP = 300      # 吸收流水最多留这么多条，免得 state 无限膨胀
_RECENT_COMMENT_DAYS = 45   # 只吸收这些天内的外界评论——太老的反馈多半已经过时

# 这些词样子像「拿不准/想征集」的信号，命中就把体裁判成 Discussion
_ASK_HINTS = ("?", "？", "怎么", "如何", "是否", "要不要", "该不该", "请教", "建议",
              "探讨", "讨论", "意见", "design", "rfc", "proposal", "should", "how")


# ── 一份对外草稿 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Draft:
    """案头一份可发布的对外草稿：发去哪种体裁、标题、正文，源自哪个进化目标。"""
    id: str                     # 稳定短 id(据标题生成，用于 --show / 吸收时回指)
    kind: str                   # issue / discussion / comment
    title: str                  # 一句话标题
    body: str                   # 三段式可发布正文(背景—想做什么—想请教/请帮)
    goal: str = ""              # 源自哪个进化目标(missionboard 标题 / market 信号主题)
    source: str = ""            # 取题来源:missionboard / market
    ref: str = ""               # 若挂在既有 issue/PR 上，记其出处(评论体裁用)
    at: str = ""                # 起草时间
    weight: float = 1.0         # 该先发谁——值越高越该先发出去

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def render_full(self) -> str:
        """完整可发布形态——把这份草稿原样誊出来，复制即可贴去 GitHub。"""
        head = f"{_KIND_LABEL.get(self.kind, self.kind)}  ·  {self.id}"
        if self.ref:
            head += f"  （挂在 {self.ref}）"
        return f"{head}\n\n# {self.title}\n\n{self.body}"

    def render(self) -> str:
        """案头一行速览——发什么体裁、标题、源自哪个目标。"""
        tag = _KIND_LABEL.get(self.kind, self.kind)
        return (f"[{self.weight:>4.1f}] {tag}  {self.id}\n"
                f"          ↳ {self.title}（源自{self.source}：{self.goal[:40]}）")


# ── 整座使馆案头 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Embassy:
    """对外协作使馆的案头：所有待发草稿，按「该先发谁」排着。"""
    drafts: list = dataclasses.field(default_factory=list)       # list[Draft]
    updated_at: str = ""

    def ranked(self) -> list[Draft]:
        return sorted(self.drafts, key=lambda d: d.weight, reverse=True)

    def by_id(self, did: str) -> Draft | None:
        return next((d for d in self.drafts if d.id == did), None)

    def to_dict(self) -> dict:
        return {"updated_at": self.updated_at,
                "drafts": [d.to_dict() for d in self.ranked()]}

    def render(self, top: int | None = None) -> str:
        ranked = self.ranked()
        shown = ranked[:top] if top else ranked
        when = (self.updated_at or _now())[:16].replace("T", " ")
        lines = [f"🤝 对外协作使馆 · 案头 {len(ranked)} 份草稿 · {when}", ""]
        if not ranked:
            lines.append("   （案头空着——missionboard/market 都没给出可对外发起的目标。")
            lines.append("    用 `python embassy.py --draft` 重新取题起草，或先去喂饱看板。）")
            return "\n".join(lines)
        lines.append("   待发草稿（值越高 = 越该先发出去）：")
        for d in shown:
            lines.append("   " + d.render())
        if top and len(ranked) > top:
            lines.append(f"\n   …… 还有 {len(ranked) - top} 份更次要的草稿(用 --top 调多少)。")
        top1 = ranked[0]
        lines.append(f"\n   👉 最该先开口：「{top1.title}」"
                     f"——`python embassy.py --show {top1.id}` 看可发布全文。")
        lines.append("   （使馆只起草，绝不替你按发布键；发出后用 `--absorb` 把回复吸收成下一步。）")
        return "\n".join(lines)


# ── 小工具 ──────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _slug(title: str, taken: set | None = None) -> str:
    """据标题生成稳定短 id：取英文/数字词，全中文则用时间尾兜底；撞号自动加序。"""
    taken = taken or set()
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    base = "-".join(words)[:28].strip("-") or ("d" + _now()[-6:].replace(":", ""))
    sid, i = base, 2
    while sid in taken:
        sid, i = f"{base}-{i}", i + 1
    return sid


def _run(cmd: list[str], timeout: int = 20) -> str:
    """跑一条只读命令收外界回复；任何失败(没装/没登录/超时)都从容退化成空串。"""
    try:
        p = subprocess.run(cmd, cwd=str(_REPO_ROOT), capture_output=True,
                           text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


def _pick_kind(goal: str, ref: str) -> str:
    """据目标的形态择体裁：挂在既有 issue/PR 上→评论；像在征意见→讨论；否则→正式立项。"""
    if ref:
        return COMMENT
    low = (goal or "").lower()
    if any(h in goal or h in low for h in _ASK_HINTS):
        return DISCUSSION
    return ISSUE


def _compose_body(goal: str, why: str, kind: str) -> str:
    """把一个进化目标铺成措辞得体的三段式正文，让接收方一眼能接得住、好回应。"""
    background = (why or "").strip() or "这是我（一只持续自我进化的程序）正在权衡的一个方向。"
    if kind == DISCUSSION:
        ask = "我拿不太准这个方向值不值得投入、有没有更好的切法——想听听你会怎么取舍，或踩过哪些坑。"
    elif kind == COMMENT:
        ask = "我打算顺着这条线往前推一步，先同步我的想法；如果方向有偏，请直接指出。"
    else:
        ask = "我打算立项推进。若你也需要、或愿意一起，欢迎在下面留个 👍 或补充你最在意的点。"
    return ("**背景**\n" + background
            + "\n\n**我想做什么**\n" + (goal or "").strip()
            + "\n\n**想请教 / 想请帮的点**\n" + ask
            + "\n\n_（本贴由 opencrab 使馆自动起草，欢迎拍砖。）_")


def _draft_weight(value: int, novelty: int, kind: str) -> float:
    """该先发谁：价值×2 + 新颖度为底，正式立项(issue)比闲聊式讨论略重——先把要紧的发出去。"""
    base = 2.0 * _num(value, 3) + _num(novelty, 3)
    bump = {ISSUE: 1.0, DISCUSSION: 0.0, COMMENT: 0.5}.get(kind, 0.0)
    return round(base + bump, 1)


def _num(n: object, default: int) -> int:
    try:
        return int(n)       # type: ignore[arg-type]
    except Exception:
        return default


# ── 取题：从内部编排台与外部行情各取一摊进化目标 ────────────────────
@dataclasses.dataclass
class _Goal:
    """一个待对外发起的进化目标：标题、动机、价值/新颖度、可能挂靠的既有出处。"""
    title: str
    why: str = ""
    value: int = 3
    novelty: int = 3
    source: str = ""
    ref: str = ""


def _goals_from_missionboard() -> list[_Goal]:
    """从使命看板取「进行中 + 机会池」的使命当对外目标；缺席/出错从容返回空。"""
    goals: list[_Goal] = []
    try:
        import planner
        board = planner.load_board()
        ms = board.in_lane(planner.DOING) + board.in_lane(planner.POOL)
    except Exception:
        return goals
    for m in ms:
        goals.append(_Goal(title=getattr(m, "title", "") or "", why=getattr(m, "why", ""),
                           value=getattr(m, "value", 3), novelty=getattr(m, "novelty", 3),
                           source="missionboard"))
    return goals


def _goals_from_market(limit: int = 3) -> list[_Goal]:
    """从需求行情取头部信号当对外目标(世界已经在喊的，最值得公开发起)；缺席从容返回空。"""
    goals: list[_Goal] = []
    try:
        import lookout
        mkt = lookout.market_load()
        signals = mkt.ranked()[:max(1, limit)]
    except Exception:
        return goals
    for s in signals:
        srcs = getattr(s, "sources", []) or []
        # 头部信号多来自既有 issue/PR——若有具体出处，挂上去当评论更礼貌、更接得住
        ref = ""
        for v in getattr(s, "voices", []):
            if getattr(v, "source", "") in ("issue", "pr") and getattr(v, "ref", ""):
                ref = v.ref
                break
        goals.append(_Goal(title=getattr(s, "theme", "") or "",
                           why=f"外部需求信号(出价{getattr(s, 'price', 0)}，来源：{'/'.join(srcs)})",
                           value=min(5, 3 + (1 if len(srcs) > 1 else 0)), novelty=3,
                           source="market", ref=ref))
    return goals


def compose_drafts() -> Embassy:
    """取题 → 择体裁 → 铺三段式正文 → 排「该先发谁」，攒成一案头可发布草稿。

    同名目标只起草一次(missionboard 优先于 market，因带得动机更全)。攒不满也不报错——
    内部编排台和外部行情都空时，案头本就该是空的。
    """
    goals = _goals_from_missionboard() + _goals_from_market()
    drafts: list[Draft] = []
    seen: set[str] = set()
    taken: set[str] = set()
    for g in goals:
        title = (g.title or "").strip()
        key = title.lower()
        if not title or key in seen:
            continue        # 同名目标只发一次——missionboard 先到的留下
        seen.add(key)
        kind = _pick_kind(title, g.ref)
        did = _slug(title, taken)
        taken.add(did)
        drafts.append(Draft(
            id=did, kind=kind, title=title, body=_compose_body(title, g.why, kind),
            goal=title, source=g.source, ref=g.ref, at=_now(),
            weight=_draft_weight(g.value, g.novelty, kind)))
    drafts.sort(key=lambda d: d.weight, reverse=True)
    return Embassy(drafts=drafts[:_MAX_DRAFTS], updated_at=_now())


# ── 落地 / 读取(单一真相，原地更新) ───────────────────────────────
def load() -> Embassy:
    """读出案头草稿；文件缺失/坏档都从容退化成空案头，绝不抛异常打断心跳。"""
    if not _DRAFTS_FILE.exists():
        return Embassy()
    try:
        data = json.loads(_DRAFTS_FILE.read_text("utf-8", errors="ignore"))
    except Exception:
        return Embassy()
    drafts: list[Draft] = []
    for d in (data.get("drafts") or []):
        try:
            title = str(d.get("title", ""))
            if not title:
                continue
            drafts.append(Draft(
                id=str(d.get("id") or _slug(title)), kind=str(d.get("kind", ISSUE)),
                title=title, body=str(d.get("body", "")), goal=str(d.get("goal", "")),
                source=str(d.get("source", "")), ref=str(d.get("ref", "")),
                at=str(d.get("at", "")), weight=float(d.get("weight", 1.0))))
        except Exception:
            continue        # 坏掉的那份跳过，别让一条脏数据废掉整座案头
    return Embassy(drafts=drafts, updated_at=str(data.get("updated_at", "")))


def save(embassy: Embassy) -> Embassy:
    """把案头原地写回 state/embassy/drafts.json；写入异常一律吞掉，绝不反噬。"""
    try:
        _EMBASSY_DIR.mkdir(parents=True, exist_ok=True)
        _DRAFTS_FILE.write_text(
            json.dumps(embassy.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass        # 使馆是嘴，落档失败也绝不弄死这只生命
    return embassy


# ── 吸收外界回复 → 蒸馏成下一步 → 软推回 missionboard ───────────────
def _read_replies(limit: int = 20) -> list[dict]:
    """软调 `gh` 读本仓 issue/PR 上**别人**留下的近期评论；没装/没登录/非 GitHub 仓都从容返回空。"""
    replies: list[dict] = []
    me = _run(["gh", "api", "user", "--jq", ".login"]).strip()
    for kind in ("issue", "pr"):
        out = _run(["gh", kind, "list", "--state", "all", "--limit", str(limit),
                    "--json", "number,title,comments"])
        if not out:
            continue
        try:
            rows = json.loads(out)
        except Exception:
            continue
        for r in rows:
            ref = f"{kind} #{r.get('number', '?')} {r.get('title', '')}"[:80]
            for c in (r.get("comments") or []):
                author = ((c.get("author") or {}).get("login") or "").strip()
                body = str(c.get("body", "") or "").strip()
                at = str(c.get("createdAt", ""))
                if not body or (me and author == me):
                    continue        # 滤掉自言自语——只吸收外界的回声
                if not _is_recent(at):
                    continue
                replies.append({"ref": ref, "author": author, "body": body, "at": at})
    return replies


def _is_recent(at: str) -> bool:
    """这条评论是不是近 _RECENT_COMMENT_DAYS 天内的？解析不了时间就当近期(宁可多吸收)。"""
    try:
        t = datetime.datetime.fromisoformat(at[:19])
        return (datetime.datetime.now() - t).days <= _RECENT_COMMENT_DAYS
    except Exception:
        return True


def _next_step_of(reply: dict) -> str:
    """把一条外界回复蒸馏成一句「下一步行动」——取首句、冠以动词，让它能直接当使命标题。"""
    body = re.split(r"[。.\n]", reply.get("body", "").strip(), maxsplit=1)[0].strip()
    body = body[:60] or reply.get("body", "").strip()[:60]
    who = reply.get("author", "") or "外界"
    return f"回应 @{who} 的反馈：{body}" if body else ""


def absorb_replies() -> list[str]:
    """读外界回复 → 蒸馏成下一步 → 软推回 missionboard 机会池(来源记 embassy)。

    这是使馆唯一一处「把外面的声音引回内部」的动作：只往机会池投，不排位、不替 judge
    判完工——让真实反馈进到既有的投资组合流控里去排。gh / missionboard 缺席、撞车去重，
    统统从容跳过；吸收记录追加进可回溯流水并裁老防膨胀。返回这趟真新推进看板的下一步。
    """
    replies = _read_replies()
    if replies:
        _log_absorbed(replies)
    pushed: list[str] = []
    try:
        import planner
        board = planner.load_board()
    except Exception:
        return pushed
    for rp in replies:
        step = _next_step_of(rp)
        if not step:
            continue
        try:
            before = len(board.missions)
            m = board.add(step, value=3, novelty=4, source="embassy",
                          why=f"吸收自外界回复（{rp.get('ref', '')}）")
            if len(board.missions) > before:        # 真新增了(没被撞车去重)才记一笔
                pushed.append(m.id)
        except Exception:
            continue
    try:
        planner.save_board(board)
    except Exception:
        pass
    return pushed


def _log_absorbed(replies: list[dict]) -> None:
    """把这趟吸收的外界回复追加进可回溯流水，并裁掉过老条目防止膨胀。"""
    try:
        _EMBASSY_DIR.mkdir(parents=True, exist_ok=True)
        stamp = _now()
        lines = [json.dumps({"absorbed_at": stamp} | rp, ensure_ascii=False) for rp in replies]
        old = _ABSORB_FILE.read_text("utf-8", errors="ignore").splitlines() \
            if _ABSORB_FILE.exists() else []
        kept = (old + lines)[-_MAX_ABSORB_KEEP:]
        _ABSORB_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except Exception:
        pass


# ── 给 crab / CLI 的便捷入口 ────────────────────────────────────────
def tick(redraft: bool = True) -> Embassy:
    """据当前目标整理草稿并落档，供心跳「攒一案头该对外发起什么」时调用。

    redraft=False 时不重新取题，仅读出已存案头(给省 token / 离线的场景)。
    """
    if not redraft:
        return load()
    return save(compose_drafts())


# ══ 倾听官 👂：把外界一段表达听成结构 + 追问 + 回应草稿 ════════════════
# 听懂别人与对外开口同属一条协作链路：先听清需求/约束/情绪/待确认，再据此追问与回应。
# 一切落进被 .gitignore 的 state/dialogue/calls.jsonl，读写出错统统吞掉，耳朵不能成为新故障源。

# 情绪档（按需要安抚的程度排序，回应语气据此调档）
CALM = "calm"          # 🙂 平和：正常陈述
ANXIOUS = "anxious"    # 😟 着急：催进度、有时间压力
CONFUSED = "confused"  # 🤔 困惑：没看懂、需要解释
UPSET = "upset"        # 😣 不满：受挫、抱怨、生气
_MOOD_LABELS = {CALM: "🙂 平和", ANXIOUS: "😟 着急",
                CONFUSED: "🤔 困惑", UPSET: "😣 不满"}

# 各情绪的口语线索（命中即倾向该情绪；UPSET/ANXIOUS 优先于 CONFUSED/CALM）
_MOOD_HINTS = {
    UPSET: ("不行", "太差", "失望", "气", "怒", "烂", "垃圾", "受不了", "又坏", "还是不",
            "怎么又", "根本", "bad", "terrible", "awful", "angry", "unacceptable", "broken"),
    ANXIOUS: ("急", "尽快", "马上", "立刻", "赶紧", "催", "deadline", "asap", "urgent",
              "今天就", "等不了", "还要多久", "什么时候能"),
    CONFUSED: ("不懂", "不明白", "看不懂", "为什么", "怎么会", "搞不清", "是不是", "?", "？",
               "confus", "unclear", "not sure", "how do", "what does"),
}

# 需求线索：句子里出现这些词，多半在表达「想要 / 希望」
_NEED_HINTS = ("希望", "想要", "想让", "需要", "能不能", "可不可以", "请", "麻烦", "最好",
               "应该", "得", "要加", "要做", "支持", "增加", "改成", "want", "need",
               "please", "could you", "should", "add", "support", "feature")
# 约束线索：句子里出现这些词，多半在划「边界 / 不能动」
_CONSTRAINT_HINTS = ("不要", "不能", "别", "禁止", "必须", "一定要", "只能", "不准", "保持",
                     "兼容", "不许", "限制", "最多", "至少", "without", "must", "don't",
                     "do not", "keep", "only", "cannot", "never", "limit")
# 待确认线索：含糊指代 / 信息缺口
_VAGUE_WORDS = ("那个", "这个", "之前", "上次", "那样", "差不多", "一些", "若干", "等等",
                "类似", "诸如此类", "you know", "that thing", "somehow", "or so")


# ── 一句被听出来的要点 ──────────────────────────────────────────────
@dataclasses.dataclass
class Point:
    """从原文里听出的一条要点：归到哪一类(kind) + 原话片段(text)。"""
    kind: str        # "need" / "constraint" / "open"
    text: str        # 引发判断的原话片段（压长后）

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一次完整的倾听 ──────────────────────────────────────────────────
@dataclasses.dataclass
class Hearing:
    """对一段外界表达的完整理解：需求 / 约束 / 情绪 / 待确认 + 追问 + 回应草稿。"""
    at: str                          # ISO 时间戳
    source: str                      # 原文（压长后留作回溯）
    mood: str                        # CALM / ANXIOUS / CONFUSED / UPSET
    needs: list                      # list[str] 听出的需求
    constraints: list                # list[str] 听出的约束
    opens: list                      # list[str] 待确认/有歧义之处
    questions: list                  # list[str] 建议的追问
    reply: str                       # 回应草稿
    seeds: list = dataclasses.field(default_factory=list)  # 相似往事提示行

    def to_dict(self) -> dict:
        return {"at": self.at, "source": self.source, "mood": self.mood,
                "needs": list(self.needs), "constraints": list(self.constraints),
                "opens": list(self.opens), "questions": list(self.questions),
                "reply": self.reply, "seeds": list(self.seeds)}

    def render(self) -> str:
        """把这次倾听摊成给人看的多行报告。"""
        lines = [f"👂  倾听 · 情绪：{_MOOD_LABELS.get(self.mood, self.mood)}", ""]

        def _block(title: str, items: list, empty: str) -> None:
            lines.append(f"   {title}")
            if items:
                lines.extend(f"     · {x}" for x in items)
            else:
                lines.append(f"     （{empty}）")

        _block("📌 需求：", self.needs, "没听出明确诉求——这本身就该追问")
        _block("⛓️ 约束：", self.constraints, "没听到边界，动手前最好确认有没有")
        _block("❓ 待确认：", self.opens, "暂无明显歧义")
        lines.append("")
        lines.append("   🗣️ 建议追问：")
        if self.questions:
            lines.extend(f"     {i}. {q}" for i, q in enumerate(self.questions, 1))
        else:
            lines.append("     （信息够清楚，可直接回应）")
        lines += ["", "   ✍️ 回应草稿："]
        lines.extend(f"     {ln}" for ln in self.reply.splitlines())
        if self.seeds:
            lines.append("   带着记忆听：")
            lines.extend(f"     {s}" for s in self.seeds)
        return "\n".join(lines)


# ── 解析：一段表达 → 要点 ───────────────────────────────────────────
def _split_sentences(text: str) -> list[str]:
    """把整段文本切成句子（中英文标点 + 换行都算断句），压掉空白。"""
    parts = re.split(r"[。！？\.\!\?\n;；]+", text or "")
    return [p.strip() for p in parts if p.strip()]


def _sense_mood(text: str) -> str:
    """读情绪：不满 > 着急 > 困惑 > 平和（越需要安抚的越优先命中）。"""
    low = (text or "").lower()
    for mood in (UPSET, ANXIOUS, CONFUSED):
        if any(h in low for h in _MOOD_HINTS[mood]):
            return mood
    return CALM


def _classify_sentence(sent: str) -> str | None:
    """判一个句子主要在表达需求、约束，还是含糊待确认；都不像则返回 None。

    约束优先于需求（"必须兼容旧接口" 既像需求又像约束，按更硬的边界归类）。
    """
    low = sent.lower()
    if any(h in low for h in _CONSTRAINT_HINTS):
        return "constraint"
    if any(h in low for h in _NEED_HINTS):
        return "need"
    if any(v in low for v in _VAGUE_WORDS):
        return "open"
    return None


def _dedup_keep_order(items: list[str]) -> list[str]:
    """去重但保留先后顺序（同一诉求被反复说时只留一条）。"""
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        key = x.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _clip(s: str, n: int = 80) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _parse(text: str) -> tuple[list[str], list[str], list[str]]:
    """把整段表达解析成（需求, 约束, 待确认）三组要点。

    逐句归类；含糊指代的句子额外收进「待确认」。一句话都没归上类时，
    把整段当成一条「需求待澄清」，逼自己追问而不是默默猜。
    """
    needs: list[str] = []
    constraints: list[str] = []
    opens: list[str] = []
    for sent in _split_sentences(text):
        kind = _classify_sentence(sent)
        clipped = _clip(sent)
        if kind == "constraint":
            constraints.append(clipped)
        elif kind == "need":
            needs.append(clipped)
        elif kind == "open":
            opens.append(clipped)
        # 句子虽已归到需求/约束，但仍带含糊指代 → 再标一条待确认
        if kind in ("need", "constraint") and any(
                v in sent.lower() for v in _VAGUE_WORDS):
            opens.append(f"指代不清：{clipped}")
    if not (needs or constraints) and text.strip():
        needs.append(_clip(text))
        opens.append("整段没听出明确诉求或边界——需要请对方说清最想要的改变")
    return (_dedup_keep_order(needs), _dedup_keep_order(constraints),
            _dedup_keep_order(opens))


# ── 生成：理解 → 追问 ───────────────────────────────────────────────
def _make_questions(needs: list[str], constraints: list[str],
                    opens: list[str], mood: str) -> list[str]:
    """据缺口生成最该先问清的几条追问：歧义、缺约束、需求过多需排序、矛盾。"""
    qs: list[str] = []
    for o in opens[:2]:
        qs.append(f"想先确认下「{o}」具体指什么？")
    if needs and not constraints:
        qs.append("这件事有没有不能碰的边界、或必须保持兼容的地方？")
    if len(needs) > 2:
        qs.append("这几条诉求里，哪一条最要紧、希望先做？")
    if mood == CONFUSED:
        qs.append("是哪一步没说清楚？我可以拆开再讲一遍。")
    if not needs and not opens:
        qs.append("我理解得对吗——你主要是想确认/反馈，暂时不需要我改动？")
    return _dedup_keep_order(qs)[:4]


# ── 生成：理解 → 回应草稿 ───────────────────────────────────────────
def _mood_opener(mood: str) -> str:
    """回应开场白随情绪调档：先接住情绪，再谈事。"""
    return {
        UPSET: "抱歉给你添了麻烦，我先认真理一下你说的——",
        ANXIOUS: "收到，我知道这事比较急，先跟你对一下我的理解——",
        CONFUSED: "我把它说得更清楚些，先确认我们说的是同一件事——",
        CALM: "谢谢反馈，先复述一下我听到的——",
    }.get(mood, "先复述一下我听到的——")


def _draft_reply(needs: list[str], constraints: list[str],
                 questions: list[str], mood: str) -> str:
    """拼一份回应草稿：接住情绪 → 复述需求/约束 → 说下一步(先问清 or 开做)。

    刻意先复述再承诺：让对方确认「我没听岔」，比急着保证「我能做到」更要紧。
    """
    lines = [_mood_opener(mood)]
    if needs:
        lines.append("你想要的是：" + "；".join(needs[:3]) + "。")
    if constraints:
        lines.append("需要守住的边界：" + "；".join(constraints[:3]) + "。")
    if not needs and not constraints:
        lines.append("（我还没完全抓准你的诉求，所以想先问清，免得做偏。）")
    if questions:
        lines.append("动手前想先问清：")
        lines.extend(f"  - {q}" for q in questions[:3])
        lines.append("等你确认后我再开始，避免做错方向返工。")
    else:
        lines.append("理解没问题的话，我就按上面这样推进，做完同步给你。")
    return "\n".join(lines)


# ── 对外主入口：把一段外界表达听成结构 ──────────────────────────────
def listen(text: str, *, use_memory: bool = True) -> Hearing:
    """把一段外界表达听成结构化理解，并生成追问与回应草稿。

    会软引入 memory：捞「这类诉求以前聊过什么」拼成提示行，让回应不失忆。
    空输入会退化成一条「请对方先说点什么」的礼貌追问，绝不报错。
    """
    text = (text or "").strip()
    if not text:
        return Hearing(
            at=_now(),
            source="", mood=CALM, needs=[], constraints=[],
            opens=["对方还没说任何内容"],
            questions=["方便说说你想让我做什么、或哪里不对劲吗？"],
            reply="我在听——方便具体说说你的需求或遇到的问题吗？")

    mood = _sense_mood(text)
    needs, constraints, opens = _parse(text)
    questions = _make_questions(needs, constraints, opens, mood)
    reply = _draft_reply(needs, constraints, questions, mood)
    seeds = _recall_seeds(text) if use_memory else []
    return Hearing(
        at=_now(), source=_clip(text, 200), mood=mood, needs=needs,
        constraints=constraints, opens=opens, questions=questions,
        reply=reply, seeds=seeds)


def _recall_seeds(text: str, k: int = 2) -> list[str]:
    """软引入 memory：捞相似往事拼成几行提示；缺/错则返回空列表。"""
    try:
        import memory
        lines = []
        for s, ep in memory.recall(text, k=k):
            warn = "⚠️ 上次栽过 — " if not ep.ok else ""
            lines.append(f"{warn}{ep.headline()}（相似 {s:.0%}）")
        return lines
    except Exception:
        return []


# ── 倾听落地 / 回看 ─────────────────────────────────────────────────
def record(hearing: Hearing) -> Hearing:
    """把一次倾听落进 state/dialogue/calls.jsonl；任何写入异常都吞掉，绝不反噬。"""
    try:
        _DIALOGUE_DIR.mkdir(parents=True, exist_ok=True)
        with _CALLS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(hearing.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass   # 倾听是耳朵，落档失败也绝不弄死这只生命
    return hearing


def recent(limit: int = 10) -> list[dict]:
    """读出最近落档的倾听(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _CALLS.exists():
        return []
    out: list[dict] = []
    for line in _CALLS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


def hear(feedback: str) -> Hearing:
    """从一段外界反馈直接听成结构并落档，供心跳在收到反馈时调用。"""
    return record(listen(feedback))


def _cmd_heard(n: int = 10) -> None:
    """CLI：回看最近几次倾听。"""
    rows = recent(n)
    if not rows:
        print("👂  还没有落档的倾听（给我一段反馈，或调 hear(...) 后再来看）。")
        return
    print(f"👂  最近 {len(rows)} 次倾听：")
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        mark = {CALM: "🙂", ANXIOUS: "😟", CONFUSED: "🤔", UPSET: "😣"}
        mood = mark.get(r.get("mood", ""), "?")
        n_need = len(r.get("needs") or [])
        n_open = len(r.get("opens") or [])
        head = str((r.get("needs") or [r.get("source", "")])[0])[:36]
        print(f"  {ts} {mood}  需求{n_need}/待确认{n_open}  {head}")


# ── CLI ─────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="embassy.py",
        description="🤝 对外协作使馆：把进化目标整理成可发布的 GitHub Issue/Discussion/PR 评论草稿，并把回复吸收成下一步",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draft", action="store_true", help="重新据 missionboard/market 取题起草后打印")
    ap.add_argument("--no-draft", action="store_true", help="不重新取题，仅读出已存案头")
    ap.add_argument("--show", metavar="ID", help="看某份草稿的完整可发布正文")
    ap.add_argument("--absorb", action="store_true",
                    help="读外界回复，蒸馏成下一步软推回 missionboard")
    ap.add_argument("--top", type=int, default=None, metavar="N", help="只看最该先发的 N 份草稿")
    args = ap.parse_args(argv)

    if args.absorb:
        pushed = absorb_replies()
        if pushed:
            print("🤝  已把 " + str(len(pushed)) + " 条外界反馈蒸馏成下一步软推回 missionboard："
                  + "、".join(pushed))
        else:
            print("🤝  没吸收到可推进的新反馈（缺 gh、无外界评论、或都已在册）。")
        print("")

    # --no-draft 只读已存案头；否则(默认 / --draft)都重新取题起草
    embassy = tick(redraft=not args.no_draft)

    if args.show:
        d = embassy.by_id(args.show)
        if d is None:
            print(f"🤝  案头没有草稿 `{args.show}`。用 `python embassy.py` 看现有草稿清单。")
        else:
            print(d.render_full())
        return

    print(embassy.render(top=args.top))


if __name__ == "__main__":
    main()
