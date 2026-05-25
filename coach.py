#!/usr/bin/env python3
"""训练教练 🏋️ —— 把一次失败 / 一个目标，转成一个「可执行的训练回合」，把经验练成本事。

为什么要有它：这只螃蟹已经会诊断(errors)、会记忆(memory)、会裁决(judge)，但它
**还不会把经验系统地训练成新本事**。诊断告诉它「这是什么错」，记忆替它存下「上次
栽在哪」，裁决判它「这次改动值不值」——可这三者都停在「认识」层面：知道了，下次却
未必真做得更好。中间缺一层**刻意练习**：把一次具体的失败 / 一个明确的目标，拆成
几道小到能立刻动手的练习，配一份能自评的评分标准，再留几道逼自己复盘的问题，
最后据成绩给出「下一轮该练什么、练到多难」的升级建议——形成

    失败/目标 → 训练回合 → 自评打分 → 复盘 → 升级 → 下一回合

的持续学习闭环。于是它不再是「摔了记一笔」，而是「摔了就针对性加练，直到不再摔」。

设计：
- 一个训练回合是一个 Round：主题 / 来源(失败 or 目标) / 难度 + 几道 Drill(练什么、
  怎么算过) + 一份 Rubric(各项权重) + 几道复盘问题 + 一句下一轮升级建议。
- 失败来源会先过 errors.classify 认出错码、借 memory.recall 捞相似往事，让练习对症。
- 自评(grade)按通过的练习加权算分，分高就升难度、分低就配脚手架重练。
- 落在被 .gitignore 的 state/coach/rounds.jsonl，可回溯；读写出错统统吞掉，绝不反噬。

零第三方依赖，纯标准库。

用法:
    python coach.py <目标或失败描述>     # 据此生成一个训练回合并打印
    python coach.py --recent             # 回看最近开过的训练回合
    python coach.py --level 3 <描述>     # 指定起始难度(1~3)
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_COACH_DIR = _REPO_ROOT / "state" / "coach"        # 落在被 .gitignore 的 state/ 里
_ROUNDS = _COACH_DIR / "rounds.jsonl"

# 难度档：1=照着做 2=独立做 3=做给别人用
MIN_LEVEL, MAX_LEVEL = 1, 3
_LEVEL_LABELS = {1: "①入门·照着做", 2: "②独立·自己做", 3: "③精通·做给别人用"}

# 判定回合是否「来自一次失败」的口语线索(没命中错码时的兜底信号)
_FAIL_HINTS = ("失败", "报错", "没过", "挂了", "出错", "崩", "异常", "踩坑", "翻车",
               "error", "fail", "traceback", "exception", "broke", "regress")


# ── 一道小练习 / 一条评分项 ─────────────────────────────────────────
@dataclasses.dataclass
class Drill:
    """一道小到能立刻动手的练习：练什么(aim) + 怎么算过(check) + 计分权重。"""
    name: str                    # 练习短名(也用作评分时的标识)
    aim: str                     # 一句话：这道练的是什么本事
    check: str                   # 可观测的过关判据(自己就能验)
    weight: int = 1              # 计分权重(越是要害练习越重)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一个训练回合 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Round:
    """一个可执行的训练回合：练习 + 评分标准 + 复盘问题 + 下一轮升级建议。"""
    at: str                      # ISO 时间戳
    topic: str                   # 这回合练的主题(从来源文本提炼)
    kind: str                    # "failure"(对着失败补练) / "goal"(对着目标进阶)
    level: int                   # 难度档(1~3)
    drills: list                 # list[Drill]
    retro: list                  # 复盘问题(逼自己想清楚为什么)
    next_hint: str               # 下一轮升级建议(打分前先给个方向)
    code: str = ""               # 失败来源时的错码(errors.classify 给)
    seeds: list = dataclasses.field(default_factory=list)  # 相似往事提示行

    @property
    def total_weight(self) -> int:
        return sum(d.weight for d in self.drills) or 1

    def to_dict(self) -> dict:
        return {"at": self.at, "topic": self.topic, "kind": self.kind,
                "level": self.level, "drills": [d.to_dict() for d in self.drills],
                "retro": list(self.retro), "next_hint": self.next_hint,
                "code": self.code, "seeds": list(self.seeds)}

    def render(self) -> str:
        """把训练回合摊成给人看的多行训练单。"""
        tag = "🩹 对着失败补练" if self.kind == "failure" else "🚀 对着目标进阶"
        code = f"  [{self.code}]" if self.code else ""
        lines = [f"🏋️  训练回合 · {tag}{code}",
                 f"   主题：{self.topic}",
                 f"   难度：{_LEVEL_LABELS.get(self.level, self.level)}", ""]
        lines.append("   小练习（练什么 → 怎么算过）：")
        for i, d in enumerate(self.drills, 1):
            lines.append(f"     {i}. {d.aim}")
            lines.append(f"        ✔ 过关：{d.check}（权重 {d.weight}）")
        lines += ["", "   评分标准：通过的练习按权重计分，"
                  f"满分 {self.total_weight}，拿到 ≥{_pass_mark(self)} 算这回合达标。"]
        if self.retro:
            lines.append("   复盘问题（逼自己想清楚）：")
            lines += [f"     - {q}" for q in self.retro]
        lines.append(f"   下一轮：{self.next_hint}")
        if self.seeds:
            lines.append("   带着记忆练：")
            lines += [f"     {s}" for s in self.seeds]
        return "\n".join(lines)


def _pass_mark(rnd: Round) -> int:
    """达标线：总权重的六成（向上取整），保证至少要过要害练习。"""
    return -(-rnd.total_weight * 6 // 10)


# ── 生成：失败/目标 → 训练回合 ──────────────────────────────────────
def _looks_like_failure(text: str, code: str) -> bool:
    """判这段描述是「补练一次失败」还是「奔一个目标进阶」。"""
    if code:                                  # errors 认出了具体错码 → 多半是失败
        return True
    low = text.lower()
    return any(h in low for h in _FAIL_HINTS)


def _topic_of(text: str) -> str:
    """从来源文本提炼一句训练主题(取首句、压长)。"""
    head = (text or "").strip().split("\n")[0].strip()
    return head[:60] or "(未命名主题)"


def _failure_drills(hint: str) -> list[Drill]:
    """对着失败补练：复现 → 定根因 → 最小修 → 加验证守住 → 沉淀记忆。

    这套顺序刻意把「加一道验证守住」摆在修复之后、记忆之前——光修好不算练成，
    得留下一个下次会自己报警的守卫，才算把这个坑真正填上。
    """
    drills = [
        Drill("复现", "稳定复现这次失败，能一句话说清触发条件", "能给出可重复的复现步骤", 1),
        Drill("根因", "定位到根因而非表象，区分「症状」与「病因」", "能指名道姓说出是哪行/哪个前提出的问题", 2),
        Drill("最小修", "做最小改动让它过，不顺手乱动别处", "改动面尽量小，且失败不再出现", 2),
        Drill("加守卫", "补一道验证/自测，让这个坑下次自己报警", "新增一个能复现旧失败的检查并使其通过", 3),
        Drill("沉记忆", "把这次的情境-行动-结果记进 memory，供下次检索", "remember(...) 落一条带错码的记忆", 1),
    ]
    if hint:
        drills[1] = dataclasses.replace(drills[1], check=f"根因对得上诊断建议：{hint[:40]}")
    return drills


def _goal_drills() -> list[Drill]:
    """奔目标进阶：拆最小可交付 → 实现 → 自测兜住 → 留下痕迹(日志/文档)。"""
    return [
        Drill("拆解", "把目标拆成一个最小可交付的切片，别一口吃成胖子", "能说出本回合只做哪一小块、为何够用", 1),
        Drill("实现", "把这一小块真正做出来、能跑", "代码可运行，产出符合切片定义", 2),
        Drill("自测", "给它配上自测，证明它真做到了", "自测通过，且能覆盖核心路径", 3),
        Drill("留痕", "写一行日志/文档说清「为什么这么做」", "EVOLUTION/journal 或文件 docstring 里留下意图", 1),
    ]


def _retro_questions(kind: str) -> list[str]:
    """复盘问题：失败侧逼问「为何当时没接住」，目标侧逼问「是否真达成」。"""
    if kind == "failure":
        return ["当时为什么没接住这个失败？缺的是验证、是记忆，还是判断？",
                "下次什么信号一出现，就该警觉同类问题正在发生？",
                "这道守卫真能复现旧失败吗，还是只是看着像在测？"]
    return ["这一小块真的是最小可交付吗，能不能再砍？",
            "自测覆盖的是核心路径，还是只挑了好测的？",
            "半年后的自己看这行留痕，能立刻懂为什么这么做吗？"]


def _next_hint(kind: str, level: int) -> str:
    """打分前先给个方向；打分后 next_level() 会据成绩再校准。"""
    if level >= MAX_LEVEL:
        return "已在最高难度——把这次练成的本事蒸馏成一张技能卡 / 一道常驻自检。"
    nxt = _LEVEL_LABELS.get(level + 1, "")
    if kind == "failure":
        return f"补练达标后，升到「{nxt}」：不光修好，还要主动找出同类潜在坑并提前守住。"
    return f"达标后升到「{nxt}」：把这块做到不用看着也能稳定交付。"


def coach(text: str, *, level: int = 1, use_memory: bool = True) -> Round:
    """把一段「失败现场」或「目标描述」转成一个可执行的训练回合。

    - 失败现场：先过 errors.classify 认错码、取修复建议，让练习对症；
      再借 memory.recall 捞相似往事，提醒「上次栽过别再撞」。
    - 目标描述：拆成最小可交付的进阶练习。

    两条外部依赖(errors / memory)都软引入：缺了或出错就降级成通用练习，绝不报错。
    """
    level = max(MIN_LEVEL, min(MAX_LEVEL, level))
    text = (text or "").strip()

    code, hint = _classify(text)
    kind = "failure" if _looks_like_failure(text, code) else "goal"

    drills = _failure_drills(hint) if kind == "failure" else _goal_drills()
    seeds = _recall_seeds(text) if (use_memory and kind == "failure") else []

    return Round(
        at=datetime.datetime.now().isoformat(timespec="seconds"),
        topic=_topic_of(text), kind=kind, level=level,
        drills=drills, retro=_retro_questions(kind),
        next_hint=_next_hint(kind, level), code=code, seeds=seeds)


def _classify(text: str) -> tuple[str, str]:
    """软引入 errors：认出错码与修复建议；缺/错则返回空，让上层降级。"""
    try:
        import errors
        spec = errors.classify(note=text, message=text, raw=text)
        if spec and getattr(spec, "code", ""):
            return spec.code, getattr(spec, "hint", "")
    except Exception:
        pass
    return "", ""


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


# ── 自评：通过的练习 → 成绩单 + 升级建议 ────────────────────────────
@dataclasses.dataclass
class Scorecard:
    """一个训练回合的自评结果：得分 / 满分 / 是否达标 + 下一轮升级建议。"""
    earned: int
    total: int
    passed: list                 # 通过的练习名
    missed: list                 # 没过的练习名
    cleared: bool                # 是否达到达标线
    next_level: int              # 建议的下一轮难度
    advice: str                  # 一句下一轮该练什么的建议

    def render(self) -> str:
        mark = "✅ 达标" if self.cleared else "🔁 未达标"
        lines = [f"🏋️  自评：{mark}  得分 {self.earned}/{self.total}"]
        if self.passed:
            lines.append("   练成：" + "、".join(self.passed))
        if self.missed:
            lines.append("   待补：" + "、".join(self.missed))
        lines.append(f"   下一轮（难度 {self.next_level}）：{self.advice}")
        return "\n".join(lines)


def grade(rnd: Round, passed: set[str] | list[str]) -> Scorecard:
    """按通过的练习名加权算分，判是否达标，并据成绩校准下一轮难度。

    passed 里写得下哪几道练习的 name，就按其权重计分；认不得的名字忽略。
    分高(达标且接近满分)→ 升一档难度；分低 → 留在原档配脚手架重练。
    """
    passed_set = {str(p) for p in passed}
    earned = sum(d.weight for d in rnd.drills if d.name in passed_set)
    total = rnd.total_weight
    got = sorted(d.name for d in rnd.drills if d.name in passed_set)
    lost = sorted(d.name for d in rnd.drills if d.name not in passed_set)
    cleared = earned >= _pass_mark(rnd)

    # 满分通关才升档；达标但有遗漏 → 原档把遗漏补齐；没达标 → 原档配脚手架重练
    if cleared and earned >= total and rnd.level < MAX_LEVEL:
        nxt = rnd.level + 1
        advice = f"满分通关，升到「{_LEVEL_LABELS.get(nxt, nxt)}」，挑更难的同类题。"
    elif cleared:
        nxt = rnd.level
        advice = "达标但有遗漏，原难度把「" + "、".join(lost or ["收尾项"]) + "」补齐再升。"
    else:
        nxt = rnd.level
        advice = "未达标，留在原难度、对着「" + "、".join(lost or ["全部"]) + \
                 "」配脚手架(看记忆/诊断建议)重练一轮。"
    return Scorecard(earned=earned, total=total, passed=got, missed=lost,
                     cleared=cleared, next_level=nxt, advice=advice)


# ── 落地 / 回看 ─────────────────────────────────────────────────────
def record(rnd: Round, *, scorecard: Scorecard | None = None) -> Round:
    """把训练回合(可带自评成绩)落进 state/coach/rounds.jsonl；写入异常一律吞掉。"""
    try:
        _COACH_DIR.mkdir(parents=True, exist_ok=True)
        row = rnd.to_dict()
        if scorecard is not None:
            row["score"] = {"earned": scorecard.earned, "total": scorecard.total,
                            "cleared": scorecard.cleared}
        with _ROUNDS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass   # 教练是陪练者，落档失败也绝不弄死这只生命
    return rnd


def recent(limit: int = 10) -> list[dict]:
    """读出最近落档的训练回合(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _ROUNDS.exists():
        return []
    out: list[dict] = []
    for line in _ROUNDS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


# ── 给 crab 调用的便捷入口：一次失败直接转成训练回合并落档 ────────────
def train_on_failure(situation: str, *, level: int = 1) -> Round:
    """从一次失败现场直接开一个对症训练回合并落档，供心跳在失败后调用。"""
    rnd = coach(situation, level=level)
    return record(rnd)


# ── CLI ─────────────────────────────────────────────────────────────
def _cmd_recent(n: int = 10) -> None:
    rows = recent(n)
    if not rows:
        print("🏋️  还没有开过训练回合（给我一段失败或目标，或调 train_on_failure(...) 后再来看）。")
        return
    print(f"🏋️  最近 {len(rows)} 个训练回合：")
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        tag = "🩹" if r.get("kind") == "failure" else "🚀"
        lv = r.get("level", "?")
        topic = str(r.get("topic", ""))[:42]
        sc = r.get("score")
        tail = ""
        if sc:
            tail = f"  → {sc.get('earned')}/{sc.get('total')}" + \
                   ("✅" if sc.get("cleared") else "🔁")
        print(f"  {ts} {tag} 难度{lv}  {topic}{tail}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="coach.py",
        description="🏋️ 训练教练：把一次失败/一个目标转成可执行的训练回合",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="*", help="失败现场 或 目标描述")
    ap.add_argument("--level", type=int, default=1,
                    help=f"起始难度 {MIN_LEVEL}~{MAX_LEVEL}(默认 1)")
    ap.add_argument("--recent", action="store_true", help="回看最近的训练回合后退出")
    args = ap.parse_args(argv)

    if args.recent or not args.text:
        _cmd_recent()
        return

    rnd = coach(" ".join(args.text), level=args.level)
    print(rnd.render())
    record(rnd)


if __name__ == "__main__":
    main()
