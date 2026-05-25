#!/usr/bin/env python3
"""持续规划中枢 🗺️ —— 把一个长期进化目标拆成多步计划：里程碑、依赖、回退条件，
并随每一步的结果动态改写「下一步该做什么」。

为什么要有它：这只螃蟹已经会诊断(errors)、会记忆(memory)、会动手(hands)、
会裁决(judge)、会定姿态(policy)、会听懂别人(dialogue)——**它会判断「这一步值不值」，
却还没有一个面向未来的「接下来一连串该怎么走」的脑子**。于是进化容易变成零散的
单步乱撞：每次心跳挑个顺手的事做，做完再拍脑袋想下一件，目标拆不开、步子排不齐、
某步翻车了也没有预备的退路。策略官(policy)管「这一步怎么走」，裁决官(judge)管
「这一步走完值不值」，而规划官补的是更长的那根线——**把一个大目标摊成有依赖、有
里程碑、有回退的多步路线，并在每一步落地后，依据结果重排剩下的路**：

  - 拆步(steps)：一个长期目标 → 若干可独立验证的小步，每步可声明它依赖哪些前置步。
  - 里程碑(milestones)：标出「走到这就算阶段性站稳了」的关键步，进度据此度量。
  - 依赖(dependencies)：谁得先完成，谁才能开工——据此算出当前真正「能开工的前沿」。
  - 回退条件(fallback)：每步预先写好「万一它栽了，退到哪 / 改走哪条路」，
    失败时不至于满盘皆停，而是顺着回退把路线就地改写。

它只规划、不动手，更不替 judge 拍板合并；读 memory「这类目标以前怎么走砸的」来给
高风险步预警。计划与每一次推进都落进被 .gitignore 的 state/planner/ 下，可回溯但
绝不反噬：读写出错统统吞掉，规划官不能成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python planner.py "<长期目标>" \\
        --step "design|画出接口草图|||先翻已有同类模块照搬" \\
        --step "impl|写实现|design|y|退回 design 重画接口" \\
        --step "verify|补自测并跑 checkup|impl|y|没过就退回 impl"
        # --step 规格：id|做什么|依赖(逗号分隔)|里程碑(y/n)|回退动作
    python planner.py --show              # 看当前计划：前沿、里程碑、回退
    python planner.py --done impl         # 标记某步完成 → 打印改写后的下一步
    python planner.py --fail impl         # 标记某步翻车 → 触发回退、就地改写路线
    python planner.py --recent            # 回看最近落档的计划
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_PLANNER_DIR = _REPO_ROOT / "state" / "planner"     # 落在被 .gitignore 的 state/ 里
_PLANS = _PLANNER_DIR / "plans.jsonl"               # 每次保存的计划快照(可回看)
_ACTIVE = _PLANNER_DIR / "active.json"              # 当前在走的那份计划

# 一步的生命状态（按推进顺序）
PENDING = "pending"     # ⬜ 还没轮到/前置没齐
READY = "ready"         # 🔵 依赖已满足，可以开工（前沿）
DONE = "done"           # ✅ 已完成
FAILED = "failed"       # ❌ 翻车了（触发回退）
BLOCKED = "blocked"     # 🚧 某前置失败，连带卡住
SKIPPED = "skipped"     # ⏭️ 主动跳过（多由回退改写而来）
_STATUS_MARK = {PENDING: "⬜", READY: "🔵", DONE: "✅",
                FAILED: "❌", BLOCKED: "🚧", SKIPPED: "⏭️"}


# ── 一步 ────────────────────────────────────────────────────────────
@dataclasses.dataclass
class Step:
    """计划里的一步：要害是「依赖谁、是不是里程碑、万一栽了退到哪」。"""
    id: str                                 # 步骤短 id（也用作依赖指代）
    what: str = ""                          # 这一步要做什么（人话）
    depends_on: list = dataclasses.field(default_factory=list)  # 前置步 id
    milestone: bool = False                 # 是否阶段性里程碑
    fallback: str = ""                      # 万一失败的回退动作（人话）
    status: str = PENDING                   # 见上面的状态常量
    note: str = ""                          # 推进时记下的一句结果备注

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一份计划 ────────────────────────────────────────────────────────
@dataclasses.dataclass
class Plan:
    """一个长期目标的多步路线：拆步 + 依赖 + 里程碑 + 回退，可随结果就地改写。"""
    goal: str
    steps: list = dataclasses.field(default_factory=list)   # list[Step]
    at: str = ""                            # 最近一次保存的时间戳

    # —— 基础索引 ——
    def by_id(self, sid: str) -> Step | None:
        for s in self.steps:
            if s.id == sid:
                return s
        return None

    def to_dict(self) -> dict:
        return {"at": self.at, "goal": self.goal,
                "steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        steps = [Step(**{**{f.name: f.default for f in dataclasses.fields(Step)
                            if f.default is not dataclasses.MISSING},
                         **{k: v for k, v in (s or {}).items()
                            if k in {f.name for f in dataclasses.fields(Step)}}})
                 for s in (d.get("steps") or [])]
        return cls(goal=str(d.get("goal", "")), steps=steps, at=str(d.get("at", "")))

    # —— 校验：依赖缺失 / 成环，都得先揪出来 ——
    def validate(self) -> list[str]:
        """返回计划的结构性问题（人话），没问题则返回空表。"""
        issues: list[str] = []
        ids = [s.id for s in self.steps]
        seen: set[str] = set()
        for sid in ids:
            if sid in seen:
                issues.append(f"步骤 id 重复：{sid}")
            seen.add(sid)
        idset = set(ids)
        for s in self.steps:
            for dep in s.depends_on:
                if dep not in idset:
                    issues.append(f"`{s.id}` 依赖了不存在的步骤 `{dep}`")
                elif dep == s.id:
                    issues.append(f"`{s.id}` 依赖了自己")
        cycle = self._find_cycle()
        if cycle:
            issues.append("依赖成环：" + " → ".join(cycle))
        return issues

    def _find_cycle(self) -> list[str]:
        """有向依赖图找一条环（DFS 三色法）；无环返回空表。"""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {s.id: WHITE for s in self.steps}
        idset = set(color)
        stack: list[str] = []

        def dfs(u: str) -> list[str]:
            color[u] = GRAY
            stack.append(u)
            dep_of = self.by_id(u)
            for v in (dep_of.depends_on if dep_of else []):
                if v not in idset:
                    continue
                if color[v] == GRAY:                 # 撞回正在访问的节点 → 成环
                    return stack[stack.index(v):] + [v]
                if color[v] == WHITE:
                    got = dfs(v)
                    if got:
                        return got
            color[u] = BLACK
            stack.pop()
            return []

        for sid in color:
            if color[sid] == WHITE:
                got = dfs(sid)
                if got:
                    return got
        return []

    # —— 前沿：当前真正「能开工」的步 ——
    def _deps_done(self, s: Step) -> bool:
        for dep in s.depends_on:
            d = self.by_id(dep)
            if d is None or d.status != DONE:
                return False
        return True

    def refresh(self) -> "Plan":
        """重算每一步的派生状态：依赖齐了的 pending→ready，前置塌了的→blocked。

        只动「派生」状态(pending/ready/blocked)，绝不覆盖 done/failed/skipped 这些
        由推进显式落定的事实。返回自身，便于链式调用。
        """
        for s in self.steps:
            if s.status in (DONE, FAILED, SKIPPED):
                continue
            # 任一前置失败/被卡 → 这步连带 blocked
            blocked = any((d := self.by_id(dep)) is not None
                          and d.status in (FAILED, BLOCKED)
                          for dep in s.depends_on)
            if blocked:
                s.status = BLOCKED
            elif self._deps_done(s):
                s.status = READY
            else:
                s.status = PENDING
        return self

    def frontier(self) -> list[Step]:
        """当前能开工的前沿步：里程碑优先，其次依赖少的先做（路线更快站稳）。"""
        self.refresh()
        ready = [s for s in self.steps if s.status == READY]
        return sorted(ready, key=lambda s: (not s.milestone, len(s.depends_on), s.id))

    def next_step(self) -> Step | None:
        """改写后的「下一步该做什么」——前沿里最该先动的那一步。"""
        front = self.frontier()
        return front[0] if front else None

    # —— 进度 / 里程碑 ——
    def milestones(self) -> list[Step]:
        return [s for s in self.steps if s.milestone]

    def progress(self) -> tuple[int, int]:
        """(已完成步数, 总步数)。"""
        return sum(1 for s in self.steps if s.status == DONE), len(self.steps)

    def is_complete(self) -> bool:
        return bool(self.steps) and all(
            s.status in (DONE, SKIPPED) for s in self.steps)

    # —— 动态改写：一步落地后，重排剩下的路 ——
    def advance(self, step_id: str, ok: bool, note: str = "") -> dict:
        """推进一步并就地改写路线，返回「下一步建议」。

        - ok=True：标记该步 done。
        - ok=False：标记 failed，连带把依赖它的后续步 block 掉，并把这一步预写的
          回退动作端到台面上——路线据此改写，而不是满盘皆停。

        返回 dict：{advanced, ok, note, fallback, blocked, next, complete}。
        找不到该步时返回 {"error": ...}，绝不抛异常打断心跳。
        """
        s = self.by_id(step_id)
        if s is None:
            return {"error": f"计划里没有步骤 `{step_id}`"}
        s.status = DONE if ok else FAILED
        s.note = note or s.note

        out: dict = {"advanced": step_id, "ok": ok, "note": s.note,
                     "fallback": "", "blocked": [], "next": None,
                     "complete": False}
        if not ok:
            # 失败：连带卡住所有(传递)依赖它的步，并端出回退动作
            out["blocked"] = self._block_dependents(step_id)
            out["fallback"] = s.fallback or "（这一步没预写回退动作——先停下，人工决定退路）"
        self.refresh()
        nxt = self.next_step()
        out["next"] = nxt.to_dict() if nxt else None
        out["complete"] = self.is_complete()
        return out

    def _block_dependents(self, step_id: str) -> list[str]:
        """把(传递)依赖 step_id 的所有未落定步标记 blocked，返回被卡住的 id 列表。"""
        blocked: list[str] = []
        changed = True
        bad = {step_id}
        while changed:
            changed = False
            for s in self.steps:
                if s.status in (DONE, FAILED, SKIPPED, BLOCKED):
                    continue
                if any(dep in bad for dep in s.depends_on):
                    s.status = BLOCKED
                    bad.add(s.id)
                    blocked.append(s.id)
                    changed = True
        return blocked

    def reroute(self, failed_id: str, new_steps: list[Step]) -> "Plan":
        """回退改写：把失败步换走，插入一组新步顶上（依赖与原失败步一致的后续会接到新步）。

        典型用法：某步栽了、它的回退动作落成了一两个具体新步，就用本方法把路线
        缝合回去。新步默认继承失败步的依赖；调用方也可在 new_steps 里自带依赖。
        """
        old = self.by_id(failed_id)
        if old is None or not new_steps:
            return self
        for ns in new_steps:
            if not ns.depends_on:
                ns.depends_on = list(old.depends_on)
        # 原本依赖失败步的后续，改为依赖新步里的最后一步（路线重新接上）
        tail = new_steps[-1].id
        for s in self.steps:
            if failed_id in s.depends_on:
                s.depends_on = [tail if dep == failed_id else dep
                                for dep in s.depends_on]
        old.status = SKIPPED
        old.note = (old.note + " ｜ 已被回退改写绕过").strip(" ｜")
        idx = self.steps.index(old)
        self.steps[idx + 1:idx + 1] = new_steps    # 紧贴失败步之后插入
        return self.refresh()

    # —— 报告 ——
    def render(self) -> str:
        """把计划摊成给人看的多行报告：前沿、各步状态、里程碑、回退、改写后的下一步。"""
        self.refresh()
        done, total = self.progress()
        ms = self.milestones()
        ms_done = sum(1 for m in ms if m.status == DONE)
        lines = [f"🗺️  计划 · 目标：{self.goal[:60]}",
                 f"   进度 {done}/{total} 步 · 里程碑 {ms_done}/{len(ms)}", ""]

        issues = self.validate()
        if issues:
            lines.append("   ⚠️ 结构问题（先修好再走）：")
            lines += [f"     - {i}" for i in issues]
            lines.append("")

        lines.append("   步骤：")
        for s in self.steps:
            mark = _STATUS_MARK.get(s.status, "?")
            star = " ⭐" if s.milestone else ""
            dep = f"  ←依赖 {', '.join(s.depends_on)}" if s.depends_on else ""
            lines.append(f"     {mark} {s.id}{star}：{s.what}{dep}")
            if s.fallback:
                lines.append(f"          ↩ 回退：{s.fallback}")
            if s.note:
                lines.append(f"          · {s.note}")
        lines.append("")

        if self.is_complete():
            lines.append("   🎉 全部步骤已落定——这个长期目标走完了。")
            return "\n".join(lines)

        nxt = self.next_step()
        if nxt:
            lines.append(f"   👉 下一步：{nxt.id} —— {nxt.what}")
        else:
            blocked = [s for s in self.steps if s.status == BLOCKED]
            if blocked:
                lines.append("   🚧 前沿空了：有步骤被失败的前置卡住——"
                             "先按回退处理，或 reroute 改写路线。")
            else:
                lines.append("   （暂无可开工的前沿——检查依赖是否还差前置。）")
        return "\n".join(lines)


# ── 从一句目标自动拆步（给个起手式，省得空手起步） ──────────────────────
def draft(goal: str) -> Plan:
    """把一个长期目标拆成一份通用的四步骨架计划：摸清 → 设计 → 实现 → 验证。

    这是「起手式」而非定制方案——每步都预写了回退，调用方该按真实目标改写/细化。
    会软引入 memory：若这类目标以前栽过，给「实现」步的回退里加一句预警。
    """
    goal = (goal or "").strip() or "(未命名长期目标)"
    warn = _recall_warning(goal)
    impl_fallback = "退回 design 重画接口，缩小这一步的范围再试"
    if warn:
        impl_fallback += f"；⚠️ {warn}"
    steps = [
        Step("scope", "摸清现状与边界：翻已有同类模块、列出约束与未知数",
             milestone=False, fallback="问题没问清就先停手求证，别急着设计"),
        Step("design", "画出接口草图与数据流，定下这次要长出的最小本事",
             depends_on=["scope"], milestone=True,
             fallback="照搬领地里最接近的同类模块的形状，先有再好"),
        Step("impl", "写实现：保持纯标准库、克制行数、对齐领地风格",
             depends_on=["design"], milestone=False, fallback=impl_fallback),
        Step("verify", "补自测并跑 checkup/smoke，确认没把自己改坏",
             depends_on=["impl"], milestone=True,
             fallback="没过就退回 impl 修到绿，绝不带着红测合并"),
    ]
    return Plan(goal=goal, steps=steps).refresh()


def _recall_warning(text: str, k: int = 2) -> str:
    """软引入 memory：这类目标以前若栽过，返回一句预警；缺/错则返回空串。"""
    try:
        import memory
        for s, ep in memory.recall(text, k=k):
            if not ep.ok and s >= 0.5:
                return f"记忆里同类目标栽过：{ep.headline()}"
    except Exception:
        pass
    return ""


# ── 落地 / 读取 / 回看 ───────────────────────────────────────────────
def save(plan: Plan, *, activate: bool = True) -> Plan:
    """把计划落进 state/planner/：追加一份快照到 plans.jsonl，并(默认)设为 active。

    任何写入异常都吞掉，绝不反噬——规划官是参谋，落档失败也不能弄死这只生命。
    """
    plan.at = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        _PLANNER_DIR.mkdir(parents=True, exist_ok=True)
        with _PLANS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(plan.to_dict(), ensure_ascii=False) + "\n")
        if activate:
            _ACTIVE.write_text(
                json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8")
    except Exception:
        pass
    return plan


def load_active() -> Plan | None:
    """读出当前在走的那份计划；缺失或坏档都从容返回 None。"""
    if not _ACTIVE.exists():
        return None
    try:
        return Plan.from_dict(json.loads(_ACTIVE.read_text("utf-8", errors="ignore")))
    except Exception:
        return None


def recent(limit: int = 10) -> list[dict]:
    """读出最近落档的计划快照(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _PLANS.exists():
        return []
    out: list[dict] = []
    for line in _PLANS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


# ── 给 crab 调用的便捷入口 ──────────────────────────────────────────
def plan_goal(goal: str, steps: list[Step] | None = None) -> Plan:
    """从一个长期目标(可选自带拆步)生成计划并落档、设为 active，供心跳起步时调用。"""
    plan = Plan(goal=goal, steps=steps).refresh() if steps else draft(goal)
    return save(plan)


def advance_active(step_id: str, ok: bool, note: str = "") -> dict:
    """推进当前 active 计划的一步，落档新状态，返回改写后的下一步建议。"""
    plan = load_active()
    if plan is None:
        return {"error": "还没有在走的计划——先 plan_goal(...) 起一份。"}
    out = plan.advance(step_id, ok, note)
    if "error" not in out:
        save(plan)
    return out


# ── CLI ─────────────────────────────────────────────────────────────
def _parse_step(spec: str) -> Step:
    """解析 --step 规格：id|做什么|依赖(逗号)|里程碑(y/n)|回退动作。

    后面的字段都可省，省了就用默认值；竖线不够也不报错。
    """
    parts = [p.strip() for p in (spec or "").split("|")]
    sid = parts[0] if parts and parts[0] else "(步骤)"
    what = parts[1] if len(parts) > 1 else ""
    deps = [d.strip() for d in parts[2].split(",")] if len(parts) > 2 and parts[2] else []
    milestone = len(parts) > 3 and parts[3].lower() in ("y", "yes", "true", "1")
    fallback = parts[4] if len(parts) > 4 else ""
    return Step(id=sid, what=what, depends_on=deps,
                milestone=milestone, fallback=fallback)


def _cmd_recent(n: int = 10) -> None:
    rows = recent(n)
    if not rows:
        print("🗺️  还没有落档的计划（给我一个目标、或用 plan_goal(...) 后再来看）。")
        return
    print(f"🗺️  最近 {len(rows)} 份计划：")
    for r in rows:
        ts = str(r.get("at", ""))[-8:]
        goal = str(r.get("goal", ""))[:40]
        n_steps = len(r.get("steps") or [])
        done = sum(1 for s in (r.get("steps") or []) if s.get("status") == DONE)
        print(f"  {ts}  {goal}  ({done}/{n_steps} 步)")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="planner.py",
        description="🗺️ 持续规划中枢：把长期目标拆成多步计划(里程碑/依赖/回退)，随结果动态改写下一步",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("goal", nargs="*", help="长期目标描述")
    ap.add_argument("--step", action="append", default=[],
                    help="一步规格：id|做什么|依赖(逗号)|里程碑(y/n)|回退动作")
    ap.add_argument("--show", action="store_true", help="显示当前 active 计划后退出")
    ap.add_argument("--done", metavar="ID", help="标记某步完成 → 改写并打印下一步")
    ap.add_argument("--fail", metavar="ID", help="标记某步翻车 → 触发回退、改写路线")
    ap.add_argument("--note", default="", help="给 --done/--fail 附一句结果备注")
    ap.add_argument("--recent", action="store_true", help="回看最近落档的计划后退出")
    args = ap.parse_args(argv)

    if args.recent:
        _cmd_recent()
        return

    # 推进 active 计划的一步
    if args.done or args.fail:
        sid = args.done or args.fail
        out = advance_active(sid, ok=bool(args.done), note=args.note)
        if "error" in out:
            print(f"🗺️  {out['error']}")
            return
        verb = "✅ 完成" if out["ok"] else "❌ 翻车"
        print(f"🗺️  推进 `{out['advanced']}`：{verb}")
        if not out["ok"]:
            print(f"   ↩ 回退：{out['fallback']}")
            if out["blocked"]:
                print(f"   🚧 连带卡住：{', '.join(out['blocked'])}")
        if out["complete"]:
            print("   🎉 全部步骤已落定——这个长期目标走完了。")
        elif out["next"]:
            print(f"   👉 改写后的下一步：{out['next']['id']} —— {out['next']['what']}")
        else:
            print("   （暂无可开工的前沿——按回退处理或 reroute 改写路线。）")
        return

    if args.show:
        plan = load_active()
        if plan is None:
            print("🗺️  还没有在走的计划——给我一个目标起一份吧。")
            return
        print(plan.render())
        return

    goal = " ".join(args.goal)
    if not goal:
        ap.error("请给一个长期目标描述（或用 --show / --recent / --done / --fail）")

    steps = [_parse_step(s) for s in args.step] or None
    if not steps:
        print("（未给 --step，用通用四步骨架起手；真用时请用 --step 列出你的步骤）\n")
    plan = plan_goal(goal, steps)
    print(plan.render())


if __name__ == "__main__":
    main()
