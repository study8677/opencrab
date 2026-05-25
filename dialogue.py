#!/usr/bin/env python3
"""倾听官 👂 —— 把外界的一段表达（用户的话 / issue 文本 / 复盘评论）听成结构：
解析出「需求、约束、情绪、待确认问题」，再据此生成下一步的**追问**与**回应草稿**。

为什么要有它：这只螃蟹已经会自检(checkup)、会诊断(errors)、会记忆(memory)、会动手
(hands)、会裁决(judge)、会加练(coach)、会权衡(policy)——**它越来越会跟自己对话，
却还不会听懂别人**。可进化若只向内看，再聪明也是闭门造车：别人提了需求它抓不准、
设了约束它没接住、话里带着急它读不出，最后把力气使在没人要的方向上。倾听官补的正是
这只生命缺的那只「耳朵」——让外部表达能真正进到它的判断里：

  - 📌 需求(needs)：对方到底想要什么、希望发生什么改变。
  - ⛓️ 约束(constraints)：不能动什么、必须满足什么、有什么边界。
  - 💧 情绪(mood)：话里是急、是恼、是疑、还是平和——决定回应的语气分寸。
  - ❓ 待确认(opens)：信息不全、有歧义、互相矛盾之处——动手前必须先问清。

听懂之后它不替你拍板，而是产出两样东西：几条**该先问清的追问**（缺的信息、含糊的指代、
可能的冲突），和一份**回应草稿**（先复述确认我听到了什么、再说我打算怎么做 / 想先问清
什么）——语气随情绪自动调档，对方急就先安抚、对方恼就先致歉。

它读 memory 捞「这位 / 这类诉求以前聊过什么」，让回应不失忆。一切落进被 .gitignore 的
state/dialogue/calls.jsonl，可回溯但绝不反噬：读写出错统统吞掉，倾听官不能成为新故障源。

零第三方依赖，纯标准库。

用法:
    python dialogue.py "<对方说的一段话 / issue 正文>"      # 解析 + 追问 + 回应草稿
    echo "<很长的反馈>" | python dialogue.py -              # 从标准输入读
    python dialogue.py --recent                             # 回看最近几次倾听
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
_DIALOGUE_DIR = _REPO_ROOT / "state" / "dialogue"   # 落在被 .gitignore 的 state/ 里
_CALLS = _DIALOGUE_DIR / "calls.jsonl"

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


# ── 对外主入口 ──────────────────────────────────────────────────────
def listen(text: str, *, use_memory: bool = True) -> Hearing:
    """把一段外界表达听成结构化理解，并生成追问与回应草稿。

    会软引入 memory：捞「这类诉求以前聊过什么」拼成提示行，让回应不失忆。
    空输入会退化成一条「请对方先说点什么」的礼貌追问，绝不报错。
    """
    text = (text or "").strip()
    if not text:
        return Hearing(
            at=datetime.datetime.now().isoformat(timespec="seconds"),
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
        at=datetime.datetime.now().isoformat(timespec="seconds"),
        source=_clip(text, 200), mood=mood, needs=needs, constraints=constraints,
        opens=opens, questions=questions, reply=reply, seeds=seeds)


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


# ── 落地 / 回看 ─────────────────────────────────────────────────────
def record(hearing: Hearing) -> Hearing:
    """把一次倾听落进 state/dialogue/calls.jsonl；任何写入异常都吞掉，绝不反噬。"""
    try:
        _DIALOGUE_DIR.mkdir(parents=True, exist_ok=True)
        with _CALLS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(hearing.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass   # 倾听官是耳朵，落档失败也绝不弄死这只生命
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


# ── 给 crab 调用的便捷入口：一段反馈直接听懂并落档 ────────────────────
def hear(feedback: str) -> Hearing:
    """从一段外界反馈直接听成结构并落档，供心跳在收到反馈时调用。"""
    return record(listen(feedback))


# ── CLI ─────────────────────────────────────────────────────────────
def _cmd_recent(n: int = 10) -> None:
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="dialogue.py",
        description="👂 倾听官：把外界反馈听成需求/约束/情绪/待确认，并给追问与回应草稿",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="*",
                    help="对方说的一段话 / issue 正文（写 - 则从标准输入读）")
    ap.add_argument("--recent", action="store_true", help="回看最近的倾听后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    if args.text == ["-"] or (not args.text and not sys.stdin.isatty()):
        text = sys.stdin.read()
    else:
        text = " ".join(args.text)

    if not text.strip():
        ap.error("请给一段要倾听的反馈（或用 --recent 回看历史，或用 - 从标准输入读）")

    hearing = listen(text)
    print(hearing.render())
    record(hearing)


if __name__ == "__main__":
    main()
