#!/usr/bin/env python3
"""策展编排官 🧭 —— 把记忆、导师招式卡、计划与外界反馈自动汇编成
「本周进化简报 + 候选行动清单」，按新颖度 / 价值 / 可做性排序，主动给自己发起下一轮任务。

为什么要有它：这只螃蟹已经会看世界(lookout)、会听懂别人(dialogue)、会师法外物
(mentor)、会规划长线(planner)、会记住教训(memory)——**它会观察、也会规划了，可这些
本事各自为政，攒下的信息散在四处，没人定期把它们端到一张桌上、变成「接下来到底先做
哪件」的行动节奏**。于是常见的失灵是：招式卡学了一摞没回头练，反馈听懂了没排进计划，
记忆里同一个坑标了红也没人主动去补——信息越攒越多，行动却还是走一步看一步。

策展官补的正是这层**编排**：周期性地把四口井的水汇到一处，提炼成一份简报，并据此
生成一批候选行动，每条都打三个分再排序——

  - 🌱 新颖度(novelty)：这事是不是老调重弹？跟最近已提过的候选撞车就压分，免得反复
    推同一件、把自己困在原地。
  - 💎 价值(value)：做了能补上多大的窟窿？反复栽的失败、积压的外部需求、高迁移招式
    天然更值钱。
  - 🔧 可做性(doability)：现在就能动手吗？计划里已就绪的前沿步最好下手，碰要害 / 缺
    前提的往后排。

它只策展、不动手，更不替 judge 拍板——简报是「这周该把劲往哪使」的参谋意见。它软引入
memory / mentor / planner / dialogue：哪口井打不上水都从容跳过，绝不因某个上游缺席而崩。
简报与候选清单落进被 .gitignore 的 state/curator/，可回溯但绝不反噬：读写出错统统吞掉，
策展官不能成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python curator.py                 # 汇编并打印本周进化简报 + 候选行动清单
    python curator.py --days 14       # 把「最近」的窗口放宽到 14 天
    python curator.py --top 5         # 只看排序最高的 5 条候选
    python curator.py --kickoff       # 把头号候选直接交给 planner 起一份计划（主动发起下一轮）
    python curator.py --recent        # 回看最近落档的几份简报
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_CURATOR_DIR = _REPO_ROOT / "state" / "curator"     # 落在被 .gitignore 的 state/ 里
_BOARD = _CURATOR_DIR / "briefs.jsonl"              # 每份简报的快照(可回看 + 算新颖度)

_DEFAULT_DAYS = 7       # 「本周」默认窗口
_DEFAULT_TOP = 8        # 候选清单默认只端出排名最高的前 N 条

# 排序权重：价值与可做性比新颖度更要紧——宁可踏实补窟窿，也别为新鲜而新鲜。
_W_NOVELTY, _W_VALUE, _W_DOABILITY = 1, 2, 2


# ── 一条候选行动 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Candidate:
    """一条「下一轮可以做」的候选：从哪口井来、为什么值得做、三个维度各打几分。"""
    title: str                  # 一句话说清这件事(将来可直接当 planner 的目标)
    source: str = ""            # 来源井：memory / mentor / planner / dialogue
    why: str = ""               # 为什么提它(理由/证据)
    novelty: int = 3            # 🌱 新颖度 0~5
    value: int = 3              # 💎 价值 0~5
    doability: int = 3          # 🔧 可做性 0~5

    @property
    def score(self) -> int:
        """加权总分——候选清单据此降序排列。"""
        return (_W_NOVELTY * self.novelty + _W_VALUE * self.value
                + _W_DOABILITY * self.doability)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self) | {"score": self.score}

    def render(self) -> str:
        src = {"memory": "🧠记忆", "mentor": "📒招式", "planner": "🗺️计划",
               "dialogue": "👂反馈"}.get(self.source, self.source or "—")
        head = (f"[{self.score:>2}] {self.title}  "
                f"（{src}｜新{self.novelty} 值{self.value} 做{self.doability}）")
        return head + (f"\n        ↳ {self.why}" if self.why else "")


# ── 一份进化简报 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Brief:
    """一次策展产出：窗口内各口井的信号概览 + 排好序的候选行动清单。"""
    at: str
    days: int
    signals: dict = dataclasses.field(default_factory=dict)      # 各口井的概览计数/摘要
    candidates: list = dataclasses.field(default_factory=list)   # list[Candidate]，已排序

    def to_dict(self) -> dict:
        return {"at": self.at, "days": self.days, "signals": self.signals,
                "candidates": [c.to_dict() for c in self.candidates]}

    def render(self, top: int = _DEFAULT_TOP) -> str:
        lines = [f"🧭  本周进化简报 · 近 {self.days} 天 · {self.at[:10]}", ""]

        sig = self.signals
        lines.append("   信号概览：")
        lines.append(f"     🧠 记忆：{sig.get('mem_total', 0)} 条"
                     f"（近窗失败 {sig.get('mem_recent_fail', 0)}）"
                     + (f"，反复栽：{sig['mem_top_code']}" if sig.get("mem_top_code") else ""))
        lines.append(f"     📒 招式：攒下 {sig.get('mentor_total', 0)} 张"
                     f"（高迁移待练 {sig.get('mentor_hi', 0)}）")
        lines.append(f"     🗺️ 计划：" + (sig.get("planner_state") or "（暂无在走的计划）"))
        lines.append(f"     👂 反馈：近窗 {sig.get('dialogue_recent', 0)} 次"
                     f"（积压需求 {sig.get('dialogue_needs', 0)}）")
        lines.append("")

        if not self.candidates:
            lines.append("   候选行动：（四口井都还没打上水——先去 lookout/dialogue/mentor"
                         " 攒点料，下次再来策展。）")
            return "\n".join(lines)

        shown = self.candidates[:top]
        lines.append(f"   候选行动清单（共 {len(self.candidates)} 条，按 值×2+做×2+新 排序）：")
        for i, c in enumerate(shown, 1):
            lines.append(f"   {i:>2}. " + c.render())
        if len(self.candidates) > len(shown):
            lines.append(f"      …… 还有 {len(self.candidates) - len(shown)} 条（--top 看更多）")
        lines.append("")
        top1 = self.candidates[0]
        lines.append(f"   👉 主动发起下一轮：先做「{top1.title}」"
                     f"——`python curator.py --kickoff` 可直接交给 planner 起计划。")
        return "\n".join(lines)


# ── 时间窗口工具 ────────────────────────────────────────────────────
def _within(at: str, since: datetime.datetime) -> bool:
    """ISO 时间戳是否落在窗口内；解析不了就当它在窗口内（宁可多收，不漏信号）。"""
    try:
        return datetime.datetime.fromisoformat(at) >= since
    except Exception:
        return True


# ── 四口井：各自打水、提炼候选 ──────────────────────────────────────
def _from_planner(signals: dict) -> list[Candidate]:
    """计划井：在走计划的「就绪前沿步」最该先动；前沿空了/卡住也提一条收拾残局的候选。"""
    out: list[Candidate] = []
    try:
        import planner
        plan = planner.load_active()
    except Exception:
        return out
    if plan is None:
        signals["planner_state"] = "（暂无在走的计划）"
        return out
    done, total = plan.progress()
    nxt = plan.next_step()
    signals["planner_state"] = f"《{plan.goal[:24]}》{done}/{total} 步"
    if nxt is not None:
        out.append(Candidate(
            title=f"推进计划下一步：{nxt.what[:50]}",
            source="planner",
            why=f"目标《{plan.goal[:24]}》的就绪前沿步 `{nxt.id}`，依赖已满足、现在就能动",
            novelty=4, value=4,
            doability=5 if not nxt.milestone else 4))   # 里程碑步更重，可做性略降
    elif not plan.is_complete():
        out.append(Candidate(
            title=f"清理计划阻塞：《{plan.goal[:24]}》前沿空了",
            source="planner",
            why="有步骤被失败的前置卡住——按回退处理或 reroute 改写路线，别让整条线停摆",
            novelty=3, value=4, doability=3))
    return out


def _from_dialogue(signals: dict, since: datetime.datetime) -> list[Candidate]:
    """反馈井：窗口内听懂的外部需求最该优先接住——别人提的事比自己想的更值得做。"""
    out: list[Candidate] = []
    try:
        import dialogue
        rows = [r for r in dialogue.recent(50) if _within(str(r.get("at", "")), since)]
    except Exception:
        return out
    signals["dialogue_recent"] = len(rows)
    needs: list[str] = []
    upset = False
    for r in rows:
        needs.extend(str(n) for n in (r.get("needs") or []))
        if r.get("mood") in ("upset", "anxious"):
            upset = True
    needs = _dedup(needs)
    signals["dialogue_needs"] = len(needs)
    for need in needs[:3]:                       # 最多端出 3 条最新积压需求
        out.append(Candidate(
            title=f"回应外部需求：{need[:50]}",
            source="dialogue",
            why="近窗倾听到的外部诉求，尚未排进计划"
                + ("；且对方语气偏急/不满，宜尽快接住" if upset else ""),
            novelty=4,
            value=5 if upset else 4,            # 情绪偏负 = 更该优先安抚
            doability=3))                        # 外部需求往往还需追问澄清，可做性中等
    return out


def _from_mentor(signals: dict) -> list[Candidate]:
    """招式井：学了却没练的高迁移招式卡——把「看见」变「学会」，欠的债该还。"""
    out: list[Candidate] = []
    try:
        import mentor
        cards = mentor.recent(30)
    except Exception:
        return out
    signals["mentor_total"] = len(cards)
    hi = [c for c in cards if int(c.get("transfer", 0)) >= 4]
    signals["mentor_hi"] = len(hi)
    # 迁移价值高的先练；同分时新攒的优先（recent 是时间正序，倒着取）
    for card in sorted(hi, key=lambda c: int(c.get("transfer", 0)), reverse=True)[:3]:
        title = str(card.get("title", "")).split("（来自")[0].strip()[:40] or "(无名招式)"
        out.append(Candidate(
            title=f"小步试学招式：{title}",
            source="mentor",
            why=f"迁移价值 {card.get('transfer')}/5 的招式卡，学了还没在领地里练过",
            novelty=4,
            value=int(card.get("transfer", 3)),
            doability=4))                        # 招式卡自带拆好的小步试学，下手成本低
    return out


def _from_memory(signals: dict, since: datetime.datetime) -> list[Candidate]:
    """记忆井：反复栽的同一个坑——补一道防线，别让同类失败一摔再摔。"""
    out: list[Candidate] = []
    try:
        import memory
        st = memory.stats()
        recent_eps = memory.load(limit=80)
    except Exception:
        return out
    signals["mem_total"] = st.get("total", 0)
    signals["mem_recent_fail"] = sum(
        1 for e in recent_eps if not e.ok and _within(e.at, since))
    codes = st.get("codes") or {}
    if not codes:
        return out
    top_code, hits = max(codes.items(), key=lambda kv: kv[1])
    signals["mem_top_code"] = f"{top_code}×{hits}"
    if hits >= 2:                                # 同一错误码栽过 ≥2 次才值得专门补防线
        out.append(Candidate(
            title=f"给反复栽的 `{top_code}` 补一道防线",
            source="memory",
            why=f"记忆里 `{top_code}` 类失败已栽过 {hits} 次——补前置校验或回归测试，断了这条复发路",
            novelty=3,
            value=min(5, 3 + hits),             # 栽得越多越值钱
            doability=3))
    return out


def _dedup(items: list[str]) -> list[str]:
    """去重保序——同一诉求被反复说时只留一条。"""
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        k = (x or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


# ── 新颖度：跟最近已提过的候选撞车就压分 ────────────────────────────
def _past_titles(limit: int = 5) -> list[str]:
    """读出最近几份简报里提过的候选标题，用来判新候选是不是老调重弹。"""
    titles: list[str] = []
    for b in recent(limit):
        for c in (b.get("candidates") or []):
            t = str(c.get("title", "")).strip()
            if t:
                titles.append(t)
    return titles


def _apply_novelty(cands: list[Candidate]) -> None:
    """据「跟历史候选有多像」就地改写每条候选的新颖度：越像越老、分越低。

    软引入 memory.similarity 做中英混合词袋相似；拿不到就退化成「标题完全相同才算撞车」。
    """
    past = _past_titles()
    if not past:
        return
    try:
        from memory import similarity as _sim
    except Exception:
        _sim = None
    for c in cands:
        if _sim is not None:
            top = max((_sim(c.title, p) for p in past), default=0.0)
        else:
            top = 1.0 if c.title in past else 0.0
        # 相似度 0→保持新颖，1→压到最低；线性映到 [0, c.novelty]
        c.novelty = max(0, min(c.novelty, round(c.novelty * (1.0 - top))))


# ── 核心：汇编一份简报 ──────────────────────────────────────────────
def curate(days: int = _DEFAULT_DAYS) -> Brief:
    """把四口井汇成一份简报：收集信号 → 提炼候选 → 算新颖度 → 排序。

    任一口井缺席/出错都从容跳过；只要还有别的井有水，简报照常出。
    """
    days = max(1, int(days or _DEFAULT_DAYS))
    since = datetime.datetime.now() - datetime.timedelta(days=days)
    signals: dict = {}

    cands: list[Candidate] = []
    cands += _from_planner(signals)
    cands += _from_dialogue(signals, since)
    cands += _from_mentor(signals)
    cands += _from_memory(signals, since)

    _apply_novelty(cands)
    cands.sort(key=lambda c: (c.score, c.value, c.doability), reverse=True)

    return Brief(at=datetime.datetime.now().isoformat(timespec="seconds"),
                 days=days, signals=signals, candidates=cands)


# ── 落地 / 回看 ─────────────────────────────────────────────────────
def save(brief: Brief) -> Brief:
    """把简报追加一份快照到 state/curator/briefs.jsonl；写入异常一律吞掉，绝不反噬。"""
    try:
        _CURATOR_DIR.mkdir(parents=True, exist_ok=True)
        with _BOARD.open("a", encoding="utf-8") as f:
            f.write(json.dumps(brief.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass   # 策展官是参谋，落档失败也绝不弄死这只生命
    return brief


def recent(limit: int = 10) -> list[dict]:
    """读出最近落档的简报(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _BOARD.exists():
        return []
    out: list[dict] = []
    for line in _BOARD.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


# ── 给 crab 调用的便捷入口 ──────────────────────────────────────────
def brief(days: int = _DEFAULT_DAYS) -> Brief:
    """汇编一份简报并落档，供心跳「这周该把劲往哪使」时调用。"""
    return save(curate(days))


def next_actions(n: int = 3, days: int = _DEFAULT_DAYS) -> list[Candidate]:
    """直接返回排名最高的 n 条候选行动，供心跳挑下一件事做。"""
    return curate(days).candidates[:max(1, n)]


def kickoff(days: int = _DEFAULT_DAYS) -> dict:
    """主动发起下一轮：把头号候选当目标交给 planner 起一份计划。

    这是策展官唯一一处「越过参谋身份去推一把」的动作，且仍只动 planner（不动手改代码、
    不替 judge 拍板）。planner 缺席或没有候选时从容返回说明，绝不抛异常打断心跳。
    """
    b = save(curate(days))
    if not b.candidates:
        return {"ok": False, "reason": "四口井都没打上水，没有可发起的候选"}
    top = b.candidates[0]
    try:
        import planner
        plan = planner.plan_goal(top.title)
        return {"ok": True, "goal": top.title, "source": top.source,
                "steps": len(plan.steps)}
    except Exception as e:
        return {"ok": False, "reason": f"planner 没接上：{e}", "goal": top.title}


# ── CLI ─────────────────────────────────────────────────────────────
def _cmd_recent(n: int = 10) -> None:
    rows = recent(n)
    if not rows:
        print("🧭  还没有落档的简报（跑一次 `python curator.py` 汇编后再来看）。")
        return
    print(f"🧭  最近 {len(rows)} 份简报：")
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        cands = r.get("candidates") or []
        top = str(cands[0].get("title", ""))[:40] if cands else "（无候选）"
        print(f"  {ts}  候选 {len(cands)} 条  头号：{top}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="curator.py",
        description="🧭 策展编排官：把记忆/招式/计划/反馈汇成进化简报与候选行动清单，主动发起下一轮",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=_DEFAULT_DAYS,
                    help=f"「最近」的天数窗口（默认 {_DEFAULT_DAYS}）")
    ap.add_argument("--top", type=int, default=_DEFAULT_TOP,
                    help=f"候选清单只显示排名最高的前 N 条（默认 {_DEFAULT_TOP}）")
    ap.add_argument("--kickoff", action="store_true",
                    help="把头号候选直接交给 planner 起一份计划（主动发起下一轮）")
    ap.add_argument("--recent", action="store_true", help="回看最近落档的简报后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    if args.kickoff:
        out = kickoff(args.days)
        if out.get("ok"):
            print(f"🧭  已发起下一轮：planner 已就「{out['goal']}」起了一份 {out['steps']} 步的计划。")
            print("    用 `python planner.py --show` 看路线。")
        else:
            print(f"🧭  没能发起下一轮：{out.get('reason', '未知原因')}")
        return

    print(brief(args.days).render(top=args.top))


if __name__ == "__main__":
    main()
