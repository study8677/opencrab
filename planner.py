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
    """这类目标以前若栽过，返回一句预警；缺/错则返回空串。

    收口到 policy 的单一记忆校准闸门（`policy.recall_seeds`）——「同类干法栽没栽过」
    的判断全仓只此一处，planner 不再自己捞一遍 memory。policy 缺席就从容退化空串。
    """
    try:
        import policy
        seeds, burned = policy.recall_seeds(text, k=k)
        if burned and seeds:
            return "记忆里同类目标栽过：" + seeds[0].lstrip("⚠️ 上次栽过 —").strip()
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


# ══════════════════════════════════════════════════════════════════════
# 使命看板 🗂️ —— 泳道状态（原 missionboard.py 并入：计划与看板同源，归一处管）
#
# 规划官管「一个长期目标的多步路线」，看板管「很多件长期使命的整体节奏」：哪些只是
# 机会、哪些正在做、哪些被依赖卡住、哪些已验过收了。两者本就同源——看板头号「进行中」
# 使命，正是交给上面 plan_goal 起一条路线的目标——故并入同一中枢，免得隔层来回搬运。
# ══════════════════════════════════════════════════════════════════════

_BOARD_DIR = _REPO_ROOT / "state" / "missionboard"      # 落在被 .gitignore 的 state/ 里
_BOARD_FILE = _BOARD_DIR / "board.json"                 # 当前看板(单一真相，原地更新)

# 四道泳道(顺序即「价值流」方向)。BLOCKED 复用上面的步骤状态常量(同为 "blocked")。
POOL, DOING, VERIFIED = "pool", "doing", "verified"
_LANES = [POOL, DOING, BLOCKED, VERIFIED]
_LANE_LABEL = {POOL: "🌊 机会池", DOING: "🔨 进行中", BLOCKED: "🧱 阻塞", VERIFIED: "✅ 已验证"}

_DEFAULT_WIP = 2        # 同时开工(进行中)默认上限——治「贪多 / 局部打转」的那道闸
_W_VALUE, _W_NOVELTY = 2, 1     # 进场排序权重：价值比新颖度更要紧


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _clamp(n: object) -> int:
    """把分数夹到 0~5,解析不了就给中性 3——绝不因脏输入抛异常。"""
    try:
        return max(0, min(5, int(n)))      # type: ignore[arg-type]
    except Exception:
        return 3


def _clamp_wip(n: object) -> int:
    try:
        return max(1, int(n))       # type: ignore[arg-type]
    except Exception:
        return _DEFAULT_WIP


def _slug(title: str, taken: set | None = None) -> str:
    """据标题生成稳定短 id:取英文/数字词,没有就用时间尾做兜底;撞号自动加序。"""
    import re
    taken = taken or set()
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    base = "-".join(words)[:32].strip("-")
    if not base:                            # 全中文/无可用字符:用时间尾做兜底
        base = "m" + _now()[-6:].replace(":", "")
    sid, i = base, 2
    while sid in taken:
        sid = f"{base}-{i}"
        i += 1
    return sid


# ── 一件使命 ────────────────────────────────────────────────────────
@dataclasses.dataclass
class Mission:
    """看板上的一件长期使命：它值不值得做(value)、新不新鲜(novelty)、要等哪几件先验过(deps)。"""
    id: str                                     # 稳定短 id(据标题生成，用于声明依赖)
    title: str                                  # 一句话使命(将来可直接当 plan_goal 目标)
    value: int = 3                              # 💎 价值 0~5
    novelty: int = 3                            # 🌱 新颖度 0~5
    deps: list = dataclasses.field(default_factory=list)    # 依赖的使命 id(须全验过才解锁)
    lane: str = POOL                            # 当前所在泳道
    source: str = ""                            # 来源:手动 / curator / ...
    why: str = ""                               # 为什么提它
    at: str = ""                                # 纳入时间
    moved_at: str = ""                          # 上次流转时间

    @property
    def priority(self) -> int:
        """进场排序分——机会池择优进「进行中」据此降序。"""
        return _W_VALUE * self.value + _W_NOVELTY * self.novelty

    def to_dict(self) -> dict:
        return dataclasses.asdict(self) | {"priority": self.priority}

    def render(self) -> str:
        deps = ("，依赖 " + "、".join(self.deps)) if self.deps else ""
        head = f"[{self.priority:>2}] {self.id}  {self.title}（值{self.value} 新{self.novelty}{deps}）"
        return head + (f"\n        ↳ {self.why}" if self.why else "")


# ── 一张看板 ────────────────────────────────────────────────────────
@dataclasses.dataclass
class Board:
    """一整张使命看板：所有在册使命 + 同时开工上限。流转/纳入/验证都落在这张表上。"""
    missions: list = dataclasses.field(default_factory=list)     # list[Mission]
    wip: int = _DEFAULT_WIP

    # —— 查询 ——
    def by_id(self, mid: str) -> Mission | None:
        return next((m for m in self.missions if m.id == mid), None)

    def in_lane(self, lane: str) -> list[Mission]:
        ms = [m for m in self.missions if m.lane == lane]
        return sorted(ms, key=lambda m: m.priority, reverse=True)

    def _deps_verified(self, m: Mission) -> bool:
        """它依赖的使命是否都已验过？缺失的依赖 id 视为「尚未验过」(保守压回阻塞)。"""
        for d in m.deps:
            dep = self.by_id(d)
            if dep is None or dep.lane != VERIFIED:
                return False
        return True

    # —— 核心:自动流转 ——
    def flow(self) -> list[str]:
        """据依赖与 WIP 上限重排泳道，返回这趟发生的流转人话。

        规则(已验证是终点，从不自动判完工)：
          1. 依赖没全验过的非终点使命 → 压回 🧱 阻塞；
          2. 依赖齐了的为「就绪」，有资格进 🔨 进行中；
          3. 进行中名额 = wip：已在做的就绪使命优先留场(免得来回横跳)，
             余下名额按 价值×2+新颖度 从就绪机会里择优补；溢出的退回 🌊 机会池等位。
        """
        moves: list[str] = []
        wip = max(0, int(self.wip))

        # 1) 先把所有非终点使命按「就绪与否」粗分:没就绪的直接判阻塞
        ready: list[Mission] = []
        for m in self.missions:
            if m.lane == VERIFIED:
                continue
            if self._deps_verified(m):
                ready.append(m)
            elif m.lane != BLOCKED:
                self._move(m, BLOCKED, moves)

        # 2) 就绪的里挑谁进场:已在做的排前(留场优先)，再按 priority,稳定择优
        ready.sort(key=lambda m: (m.lane == DOING, m.priority), reverse=True)
        for i, m in enumerate(ready):
            target = DOING if i < wip else POOL
            if m.lane != target:
                self._move(m, target, moves)
        return moves

    def _move(self, m: Mission, lane: str, moves: list[str]) -> None:
        if m.lane == lane:
            return
        moves.append(f"{m.id}：{_LANE_LABEL[m.lane]} → {_LANE_LABEL[lane]}")
        m.lane = lane
        m.moved_at = _now()

    # —— 变更 ——
    def add(self, title: str, *, value: int = 3, novelty: int = 3,
            deps: list | None = None, source: str = "manual", why: str = "") -> Mission:
        """纳入一件新使命到机会池；标题撞车则不重复纳入，返回既有那件。"""
        title = (title or "").strip() or "(未命名使命)"
        mid = _slug(title, taken={m.id for m in self.missions})
        dup = next((m for m in self.missions
                    if m.title == title or m.id == mid), None)
        if dup is not None:
            return dup
        m = Mission(id=mid, title=title, value=_clamp(value), novelty=_clamp(novelty),
                    deps=[d for d in (deps or []) if d], source=source, why=why,
                    lane=POOL, at=_now(), moved_at=_now())
        self.missions.append(m)
        return m

    def verify(self, mid: str) -> Mission | None:
        """把某使命标为已验证(收口)——这是看板上唯一进 ✅ 的途径,须由外部拍板触发。"""
        m = self.by_id(mid)
        if m is not None and m.lane != VERIFIED:
            m.lane = VERIFIED
            m.moved_at = _now()
        return m

    def to_dict(self) -> dict:
        return {"wip": self.wip, "missions": [m.to_dict() for m in self.missions]}

    def render(self) -> str:
        lines = [f"🗂️  使命看板 · 同时开工上限 {self.wip} · {_now()[:10]}", ""]
        if not self.missions:
            lines.append("   （看板空着——用 --add 纳入第一件使命，或 --seed 从 curator 候选纳入。）")
            return "\n".join(lines)
        doing_n = len(self.in_lane(DOING))
        for lane in _LANES:
            ms = self.in_lane(lane)
            cap = f"（{doing_n}/{self.wip}）" if lane == DOING else f"（{len(ms)}）"
            lines.append(f"   {_LANE_LABEL[lane]}{cap}：")
            if not ms:
                lines.append("      —")
            for m in ms:
                lines.append("      " + m.render())
            lines.append("")
        top = self.in_lane(DOING)
        if top:
            lines.append(f"   👉 当下主攻：「{top[0].title}」"
                         "——`python planner.py --kickoff` 可起一条路线。")
        elif self.in_lane(POOL):
            lines.append("   👉 进行中是空的——下次流转会从机会池择优补位；或先 --verify 收口腾位。")
        return "\n".join(lines)


# ── 看板落地 / 读取(单一真相,原地更新) ──────────────────────────────
def load_board() -> Board:
    """读出当前看板;文件缺失/坏档都从容退化成一张空看板,绝不抛异常打断心跳。"""
    if not _BOARD_FILE.exists():
        return Board()
    try:
        data = json.loads(_BOARD_FILE.read_text("utf-8", errors="ignore"))
    except Exception:
        return Board()
    missions: list[Mission] = []
    for d in (data.get("missions") or []):
        try:
            missions.append(Mission(
                id=str(d.get("id") or _slug(str(d.get("title", "")))),
                title=str(d.get("title", "")),
                value=_clamp(d.get("value", 3)), novelty=_clamp(d.get("novelty", 3)),
                deps=[str(x) for x in (d.get("deps") or [])],
                lane=d.get("lane") if d.get("lane") in _LANES else POOL,
                source=str(d.get("source", "")), why=str(d.get("why", "")),
                at=str(d.get("at", "")), moved_at=str(d.get("moved_at", ""))))
        except Exception:
            continue        # 坏掉的那条跳过,别让一条脏数据废掉整张看板
    return Board(missions=missions, wip=_clamp_wip(data.get("wip", _DEFAULT_WIP)))


def save_board(board: Board) -> Board:
    """把看板原地写回 state/missionboard/board.json;写入异常一律吞掉,绝不反噬。"""
    try:
        _BOARD_DIR.mkdir(parents=True, exist_ok=True)
        _BOARD_FILE.write_text(
            json.dumps(board.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass        # 看板是参谋,落档失败也绝不弄死这只生命
    return board


# ── 从 curator 候选纳入新机会(软引入,缺席从容退化) ─────────────────
def seed_from_curator(board: Board, limit: int = 3) -> list[Mission]:
    """把 curator 排名最高的几条候选纳入机会池;curator 缺席/无候选都从容跳过。"""
    added: list[Mission] = []
    try:
        import curator
        cands = curator.next_actions(n=max(1, limit))
    except Exception:
        return added
    for c in cands:
        before = len(board.missions)
        m = board.add(getattr(c, "title", "") or "", value=getattr(c, "value", 3),
                      novelty=getattr(c, "novelty", 3),
                      source=f"curator/{getattr(c, 'source', '')}".rstrip("/"),
                      why=getattr(c, "why", ""))
        if len(board.missions) > before:        # 真新增了(没被撞车去重)才记一笔
            added.append(m)
    return added


# ── 新颖度复核:跟在册使命撞车就压分(软引入 memory,缺席退化) ─────────
def _refresh_novelty(board: Board) -> None:
    """据「跟已在册使命有多像」就地压低新机会的新颖度——免得反复纳入同一类事。

    软引入 memory.similarity 做中英混合词袋相似;拿不到就退化成「标题完全相同才算撞车」。
    仅对机会池里的使命复核(已开工/已验证的不动)。
    """
    pool = [m for m in board.missions if m.lane == POOL]
    others = [m for m in board.missions if m.lane != POOL]
    if not pool or not others:
        return
    try:
        from memory import similarity as _sim
    except Exception:
        _sim = None
    for m in pool:
        if _sim is not None:
            top = max((_sim(m.title, o.title) for o in others), default=0.0)
        else:
            top = 1.0 if any(m.title == o.title for o in others) else 0.0
        m.novelty = max(0, min(m.novelty, round(m.novelty * (1.0 - top))))


# ── 给 crab / CLI 的看板便捷入口 ────────────────────────────────────
def tick(wip: int | None = None) -> Board:
    """读看板 → (可选改 WIP) → 自动流转 → 落档,供心跳「摆一摆整体节奏」时调用。"""
    board = load_board()
    if wip is not None:
        board.wip = _clamp_wip(wip)
    _refresh_novelty(board)
    board.flow()
    return save_board(board)


def kickoff() -> dict:
    """把头号「进行中」使命当目标交给 plan_goal 起一份计划(主动推进当下主攻)。

    这是看板唯一一处「越过参谋身份去推一把」的动作,且仍只起计划(不动手改代码、
    不替 judge 拍板)。没有进行中使命时从容返回说明,绝不抛异常打断心跳。
    """
    board = tick()
    doing = board.in_lane(DOING)
    if not doing:
        return {"ok": False, "reason": "进行中是空的,没有可发起的使命"}
    top = doing[0]
    try:
        plan = plan_goal(top.title)
        return {"ok": True, "goal": top.title, "id": top.id, "steps": len(plan.steps)}
    except Exception as e:
        return {"ok": False, "reason": f"起计划没接上：{e}", "goal": top.title}


# ══════════════════════════════════════════════════════════════════════
# 分工协作派遣台 🐜 —— 把一个目标横切成可并行的子任务，分派给几只「临时分身代理」
# 各自检索/实现/验证，再把它们带回的冲突与共识汇成一份方案（原 delegate.py 并入）。
#
# 为什么并到这里：分工本就是「计划」的一部分——竞技场(arena)是**择优**一份方案，派遣台
# 是**分工**让几只分身并行覆盖更多面，而两者的产物最终都要落成规划官的多步路线（派遣台
# 的 delegate_kickoff 正是把汇总方案交给上面的 plan_goal）。同源归一处，免得隔层搬运、
# 也少一条重复的「拆任务→排次序」链路。
#
# 它只把活拆开、把料拼拢、排出次序，**不动手写码、更不替 judge 拍板**。软引入
# memory/lookout/arena：哪个上游缺席都从容退化，绝不因某个依赖缺位而崩。每次派遣落进被
# .gitignore 的 state/delegate/，读写出错统统吞掉，派遣台不能成为新的故障源。
# ══════════════════════════════════════════════════════════════════════

_DELEGATE_DIR = _REPO_ROOT / "state" / "delegate"   # 落在被 .gitignore 的 state/ 里
_RUNS = _DELEGATE_DIR / "runs.jsonl"                 # 每次派遣的快照(可回看)

# 领地的要害器官：分身要碰它们，风险天然更重。软对齐 judge/arena 的同名清单，
# 拿不到就用本地兜底，绝不因 import 失败而崩。
try:
    from judge import _VITAL as _VITAL              # type: ignore
except Exception:                                   # pragma: no cover
    _VITAL = {"crab.py", "hands.py", "checkup.py", "audit.py",
              "capabilities/__init__.py"}

_BIG_LINES = 400        # 「巨改」阈值(与 arena 对齐)
_WIDE_FILES = 12        # 改动面「失控」阈值
_ROLES = ["scout", "maker", "guard", "navigator"]


# ── 一条证据（各分身下井检索时打上来的料） ──────────────────────────
@dataclasses.dataclass
class Evidence:
    """某只分身检索到的一条料：来自 memory 的成败往事、或 mentor 的可迁移招式。"""
    kind: str                   # success / failure / move
    text: str                   # 人话证据
    weight: float = 0.5         # 相关度/份量 0~1

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一块子任务（横切目标得来的一片活） ──────────────────────────────
@dataclasses.dataclass
class Subtask:
    """目标横切出的一块可并行的活：谁(role)、干什么(brief)、要等哪几块先完成(deps)。"""
    role: str                                   # 分身代号(scout/maker/guard/navigator)
    title: str                                  # 这只分身的名号(带 emoji)
    brief: str = ""                             # 这块活要干什么(人话)
    deps: list = dataclasses.field(default_factory=list)    # 依赖的子任务 role

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一份回执（一只分身干完带回来的料 + 立场） ───────────────────────
@dataclasses.dataclass
class Finding:
    """某只临时分身跑完「检索→实现→验证」带回的回执：它查到的料、它那段的做法/规模，
    以及它在几条共享轴(规模/碰要害/补自测/可逆)上的立场——汇总靠这些立场找冲突与共识。"""
    role: str
    title: str
    summary: str = ""                           # 这只分身这一段的结论(人话)
    approach: str = ""                          # 它那段具体怎么干
    # —— 共享轴上的立场（汇总据此找冲突/共识） ——
    est_lines: int = 0
    touches: list = dataclasses.field(default_factory=list)
    wants_selftest: bool = True                 # 它主张这事该不该补自测
    reversible: bool = True                     # 它那段是否可逆
    cites: list = dataclasses.field(default_factory=list)   # list[Evidence]
    # —— 自验产物(由 _verify 填) ——
    risk: int = 0
    risk_notes: list = dataclasses.field(default_factory=list)

    def touches_vital(self) -> list:
        return sorted(f for f in self.touches if f.replace("\\", "/") in _VITAL)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["cites"] = [e.to_dict() for e in self.cites]
        d["touches_vital"] = self.touches_vital()
        return d

    def render(self) -> str:
        head = f"   {self.title}（约{self.est_lines}行 风险-{self.risk}）"
        lines = [head]
        if self.summary:
            lines.append(f"      结论：{self.summary}")
        if self.approach:
            lines.append(f"      做法：{self.approach}")
        for ev in self.cites:
            mark = {"success": "✅", "failure": "⚠️", "move": "📒"}.get(ev.kind, "·")
            lines.append(f"      {mark} {ev.text}")
        for n in self.risk_notes:
            lines.append(f"      ⚠️ {n}")
        return "\n".join(lines)


# ── 把目标横切成可并行的子任务 ──────────────────────────────────────
def decompose(goal: str, roles: list | None = None) -> list[Subtask]:
    """把一个进化目标横切成几块子任务：检索 / 实现 / 验证 / 集成。
    彼此声明依赖（实现等检索、验证等实现、集成等验证）——无依赖的几块即「可并行」那部分。"""
    blueprint = {
        "scout": Subtask("scout", "🔍 探子", "下井检索同类的成败往事与可借招式，圈出已知坑"),
        "maker": Subtask("maker", "🔨 工匠", "据探子的料写实现：聚焦的新模块、对齐既有风格",
                          deps=["scout"]),
        "guard": Subtask("guard", "🛡 守卫", "给实现补自测、划风险闸：碰要害否、可逆否",
                          deps=["maker"]),
        "navigator": Subtask("navigator", "🧭 向导", "把验证过的实现接进既有模块、对齐约束",
                             deps=["guard"]),
    }
    names = roles or list(blueprint)
    out: list[Subtask] = []
    for n in names:
        st = blueprint.get(n)
        if st is None:
            continue
        # 被裁掉的依赖不该留成悬空引用——只保留同场在册的依赖。
        st = dataclasses.replace(st, deps=[d for d in st.deps if d in names])
        out.append(st)
    return out


# ── 证据池：从记忆/招式井各打一桶水（与 arena 同源，缺席从容退化） ──
def _gather_evidence(goal: str) -> list[Evidence]:
    """汇一池证据供各分身分领：memory 里同类的成/败往事 + mentor 里高迁移的可借招式。
    任一口井缺席/出错都从容跳过，返回能打上来的部分。"""
    pool: list[Evidence] = []
    try:
        import memory
        for s, ep in memory.recall(goal, k=4):
            if s < 0.4:
                continue
            if ep.ok:
                pool.append(Evidence("success", f"记忆：同类做过且成功 — {ep.headline()}", s))
            else:
                pool.append(Evidence("failure", f"记忆：同类栽过 — {ep.headline()}", s))
    except Exception:
        pass
    try:
        import lookout
        for c in lookout.recent(20):
            if int(c.get("transfer", 0)) >= 4:
                title = str(c.get("title", "")).split("（来自")[0].strip()[:36]
                pool.append(Evidence("move", f"招式：有现成高迁移招式可借 — {title}", 0.6))
    except Exception:
        pass
    return pool


# ── 一只分身干一块活：检索 → 实现 → 验证 ────────────────────────────
def dispatch(st: Subtask, pool: list[Evidence], *, goal: str = "",
             constraints: list | None = None) -> Finding:
    """派一只临时分身跑完它那块子任务的小循环：先从证据池领它关心的料(检索)，
    再据角色给出它那段的做法与规模(实现)，最后过沙盘/本地兜底算这段的风险(验证)。"""
    constraints = constraints or []
    f = _draft_finding(st, pool, goal=goal)
    _verify_finding(f, goal=goal, constraints=constraints)
    return f


def _draft_finding(st: Subtask, pool: list[Evidence], *, goal: str) -> Finding:
    """据角色出一份回执雏形：领它最该看的那类证据，给出它那段的做法/规模/立场。"""
    role = st.role
    if role == "scout":     # 🔍 探子：只检索、不写码——把坑和可借的路子摊清楚
        cites = ([e for e in pool if e.kind == "failure"][:2]
                 + [e for e in pool if e.kind == "move"][:1])
        warned = "；".join(e.text.split("—", 1)[-1].strip() for e in cites
                          if e.kind == "failure") or "没翻到同类栽过的记录"
        return Finding(role, st.title,
                       summary=f"先看清坑：{warned}",
                       approach="只检索不动手，把已知坑与可借招式交给工匠",
                       est_lines=0, cites=cites)
    if role == "maker":     # 🔨 工匠：据料写一个聚焦的新模块，纯标准库、对齐风格
        cites = [e for e in pool if e.kind in ("move", "success")][:2]
        return Finding(role, st.title,
                       summary="写一个聚焦的新模块承接目标，纯标准库、对齐既有风格",
                       approach="从零写实现，复用领地里最近同类模块的骨架",
                       est_lines=300, wants_selftest=True, reversible=True, cites=cites)
    if role == "guard":     # 🛡 守卫：补自测、划风险闸——安全轴上它最较真
        return Finding(role, st.title,
                       summary="这事必须带自测、保持可逆，且不该碰要害器官",
                       approach="补 __main__ 自测、列回退路径，给高风险点设闸",
                       est_lines=60, wants_selftest=True, reversible=True)
    if role == "navigator":  # 🧭 向导：接线集成，可能要轻碰主循环
        cites = [e for e in pool if e.kind == "move"][:1]
        return Finding(role, st.title,
                       summary="把新本事接进既有调用链，并对齐硬约束",
                       approach="在 crab.py 心跳处补一处软引入式调用，缺席能退化",
                       est_lines=40, touches=["crab.py"],
                       wants_selftest=True, reversible=True, cites=cites)
    # 未知角色：给一份中性回执，绝不抛异常打断派遣
    return Finding(role, st.title or role, summary="(未知角色，按中性处理)", est_lines=80)


def _verify_finding(f: Finding, *, goal: str, constraints: list) -> None:
    """这只分身自验它那段的风险：优先借 simulator 沙盘脑子，装不上就本地兜底。"""
    try:
        import simulator
        sb = simulator.Sandbox(
            name=f.title, approach=f.approach,
            new_modules=1 if f.role == "maker" else 0,
            est_lines=f.est_lines, touches=list(f.touches),
            has_selftest=f.wants_selftest, reversible=f.reversible)
        simulator.appraise(sb, goal=goal, constraints=constraints)
        f.risk = sb.risk
        f.risk_notes = list(sb.failure_chain)
        return
    except Exception:
        pass
    _verify_finding_local(f)


def _verify_finding_local(f: Finding) -> None:
    """沙盘缺席时的本地兜底自验（与 simulator 口径大体对齐，保守取重）。"""
    vital = f.touches_vital()
    risk = (2 if vital else 0) + (0 if f.wants_selftest else 2) \
        + (0 if f.reversible else 1) + (1 if f.est_lines >= _BIG_LINES else 0)
    notes: list = []
    if vital:
        notes.append(f"动了要害器官 {', '.join(vital)}")
    if not f.wants_selftest:
        notes.append("没有自测兜底 → 回归不会被当场发现")
    if not f.reversible:
        notes.append("难回退 → 翻车成本高")
    f.risk = risk
    f.risk_notes = notes


# ── 一次派遣：汇总各分身的回执，理出冲突/共识/最终次序 ───────────────
@dataclasses.dataclass
class Delegation:
    """一次分工派遣：同一目标横切出的子任务 + 各分身回执 + 冲突 + 共识 + 落地次序。"""
    goal: str
    constraints: list = dataclasses.field(default_factory=list)
    subtasks: list = dataclasses.field(default_factory=list)     # list[Subtask]
    findings: list = dataclasses.field(default_factory=list)     # list[Finding]
    at: str = ""

    def conflicts(self) -> list[str]:
        """摊出分身们各执一词的轴：规模 / 碰要害 / 补自测 / 可逆。"""
        fs = self.findings
        coders = [f for f in fs if f.est_lines]     # 只让真要写码的分身参与规模分歧
        out: list[str] = []

        def _bucket(n: int) -> str:
            return "小" if n < 150 else ("中" if n < _BIG_LINES else "大")
        if len({_bucket(f.est_lines) for f in coders}) > 1:
            spread = ", ".join(f"{f.title.split()[-1]}{f.est_lines}行" for f in coders)
            out.append(f"改动规模有分歧：{spread}")
        if len({bool(f.touches_vital()) for f in fs}) > 1:
            who = [f.title.split()[-1] for f in fs if f.touches_vital()]
            out.append(f"是否碰要害器官有分歧：{'、'.join(who)} 要碰，其余不碰")
        if len({f.wants_selftest for f in fs}) > 1:
            who = [f.title.split()[-1] for f in fs if not f.wants_selftest]
            out.append(f"要不要补自测有分歧：{'、'.join(who)} 想省")
        if len({f.reversible for f in fs}) > 1:
            who = [f.title.split()[-1] for f in fs if not f.reversible]
            out.append(f"可逆性有分歧：{'、'.join(who)} 的那段难回退")
        return out

    def consensus(self) -> list[str]:
        """摊出分身们都同意的点——共识是拼方案时最稳的地基。"""
        fs = self.findings
        if len(fs) < 2:
            return []
        out: list[str] = []
        if all(f.wants_selftest for f in fs):
            out.append("各分身都同意这事该带自测")
        if all(f.reversible for f in fs):
            out.append("各分身都同意保持可逆")
        if all(not f.touches_vital() for f in fs):
            out.append("各分身都同意不碰要害器官")
        return out

    def resolutions(self) -> list[str]:
        """冲突一律从稳收口：安全轴(自测/要害/可逆)上守卫的稳健主张优先。"""
        fs = self.findings
        out: list[str] = []
        if any(not f.wants_selftest for f in fs):
            out.append("自测分歧 → 从稳：最终方案一律带自测")
        vital = sorted({v for f in fs for v in f.touches_vital()})
        if vital:
            out.append(f"碰要害分歧 → 从稳：最终方案不碰 {', '.join(vital)}，"
                       "集成改走软引入/缺席退化")
        if any(not f.reversible for f in fs):
            out.append("可逆分歧 → 从稳：最终方案保留回退路径")
        return out

    def total_lines(self) -> int:
        return sum(f.est_lines for f in self.findings)

    def total_risk(self) -> int:
        """从稳收口后的总风险：去掉「碰要害/省自测/不可逆」这些会被收口掉的扣分。"""
        return sum(max(0, f.risk
                       - (2 if f.touches_vital() else 0)
                       - (0 if f.wants_selftest else 2)
                       - (0 if f.reversible else 1)) for f in self.findings)

    def order(self) -> list[Subtask]:
        """据子任务声明的依赖排出推进次序（稳定拓扑序，遇环则按原序兜底不死循环）。"""
        done: list[str] = []
        remaining = list(self.subtasks)
        ordered: list[Subtask] = []
        while remaining:
            progressed = False
            for st in list(remaining):
                if all(d in done for d in st.deps):
                    ordered.append(st)
                    done.append(st.role)
                    remaining.remove(st)
                    progressed = True
            if not progressed:                  # 依赖成环：把剩下的按原序接上，绝不卡死
                ordered.extend(remaining)
                break
        return ordered

    def plan_steps(self):
        """把汇总后的子任务拼成 planner 的多步：依赖照搬、安全轴从稳写进回退。"""
        steps = []
        for st in self.order():
            f = next((x for x in self.findings if x.role == st.role), None)
            what = f.summary if (f and f.summary) else st.brief
            fb = "退回上一步重做" if st.deps else "缩小这块的范围、先做更小验证"
            if st.role == "guard":
                fb = "没过就退回工匠那段重写"
            steps.append(Step(id=st.role, what=what, depends_on=list(st.deps),
                              milestone=(st.role in ("maker", "guard")), fallback=fb))
        return steps

    def to_dict(self) -> dict:
        return {"at": self.at, "goal": self.goal, "constraints": list(self.constraints),
                "subtasks": [s.to_dict() for s in self.subtasks],
                "findings": [f.to_dict() for f in self.findings],
                "conflicts": self.conflicts(), "consensus": self.consensus(),
                "resolutions": self.resolutions(),
                "order": [s.role for s in self.order()],
                "total_lines": self.total_lines(), "total_risk": self.total_risk()}

    def render(self) -> str:
        lines = [f"🐜  分工派遣 · 目标：{self.goal[:60]}"]
        if self.constraints:
            lines.append("   约束：" + " ｜ ".join(self.constraints))
        lines.append("")
        if not self.findings:
            lines.append("   （没有派出任何分身——先用 --roles 选几只、或别把它们都筛掉。）")
            return "\n".join(lines)

        lines.append("   分身回执：")
        for f in self.findings:
            lines.append(f.render())
            lines.append("")

        con, cf, res = self.consensus(), self.conflicts(), self.resolutions()
        if con:
            lines.append("   🤝 共识：" + "；".join(con))
        if cf:
            lines.append("   ⚔️ 冲突：")
            for c in cf:
                lines.append(f"      · {c}")
        if res:
            lines.append("   🧷 从稳收口：")
            for r in res:
                lines.append(f"      · {r}")
        lines.append("")

        seq = " → ".join(s.title.split()[-1] for s in self.order())
        lines.append(f"   👉 落地次序：{seq}")
        lines.append(f"      合计约 {self.total_lines()} 行、收口后总风险 -{self.total_risk()}；"
                     "用 --delegate --kickoff 把这份方案交给 planner 起计划。")
        return "\n".join(lines)


# ── 核心：开一次派遣 ────────────────────────────────────────────────
def delegate(goal: str, roles: list | None = None,
             constraints: list | None = None) -> Delegation:
    """把目标横切成子任务，派几只临时分身分头跑「检索→实现→验证」，汇成一次派遣。

    任一分身/任一证据井缺席都从容跳过；只要还有一只分身干得了活，派遣照常成。
    """
    goal = (goal or "").strip() or "(未命名目标)"
    constraints = constraints or []
    subtasks = decompose(goal, roles)
    pool = _gather_evidence(goal)
    findings = [dispatch(st, pool, goal=goal, constraints=constraints) for st in subtasks]
    return Delegation(goal=goal, constraints=constraints,
                      subtasks=subtasks, findings=findings)


# ── 派遣的落地 / 回看 ───────────────────────────────────────────────
def save_delegation(d: Delegation) -> Delegation:
    """把一次派遣追加一份快照到 state/delegate/runs.jsonl；写入异常一律吞掉，绝不反噬。"""
    d.at = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        _DELEGATE_DIR.mkdir(parents=True, exist_ok=True)
        with _RUNS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(d.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass        # 派遣台是参谋，落档失败也绝不弄死这只生命
    return d


def run_delegation(goal: str, roles: list | None = None,
                   constraints: list | None = None) -> Delegation:
    """开一次派遣并落档，供心跳动手前「把大事拆开、几个自己并行覆盖更多面」时调用。"""
    return save_delegation(delegate(goal, roles, constraints))


def recent_delegations(limit: int = 10) -> list[dict]:
    """读出最近落档的派遣快照(时间正序)；文件缺失或坏行都从容跳过。"""
    if not _RUNS.exists():
        return []
    out: list[dict] = []
    for line in _RUNS.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:] if limit else out


def delegate_kickoff(goal: str, roles: list | None = None,
                     constraints: list | None = None) -> dict:
    """把汇总后的最终方案(从稳收口的多步)直接交给 plan_goal 落成一份计划。

    这是派遣台唯一一处「越过参谋身份去推一把」的动作，且仍只起计划（不动手改代码、
    不替 judge 拍板）。没派出分身时从容返回说明，绝不抛异常打断心跳。
    """
    d = save_delegation(delegate(goal, roles, constraints))
    if not d.findings:
        return {"ok": False, "reason": "没有派出任何分身，无从汇总"}
    steps = d.plan_steps()
    if not steps:
        return {"ok": False, "reason": "汇总后没拼出可落地的步骤"}
    try:
        plan = plan_goal(goal, steps)
        return {"ok": True, "goal": goal, "steps": len(plan.steps),
                "order": [s.role for s in d.order()]}
    except Exception as e:
        return {"ok": False, "reason": f"起计划没接上：{e}"}


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


def _cmd_board(args) -> None:
    """使命看板 CLI（原 missionboard.py 并入）：纳入/验证/播种/发起 + 自动流转后打印。"""
    if args.kickoff:
        out = kickoff()
        if out.get("ok"):
            print(f"🗂️  已发起:已就「{out['goal']}」起了一份 {out['steps']} 步的计划。")
            print("    用 `python planner.py --show` 看路线。")
        else:
            print(f"🗂️  没能发起：{out.get('reason', '未知原因')}")
        return

    board = load_board()
    if args.wip is not None:
        board.wip = _clamp_wip(args.wip)
    if args.add:
        m = board.add(args.add, value=args.value, novelty=args.novelty,
                      deps=args.dep, why=args.why)
        print(f"🗂️  已纳入机会池：{m.id}  {m.title}")
    if args.verify:
        m = board.verify(args.verify)
        print(f"🗂️  已验证收口：{m.id}" if m else f"🗂️  没找到使命 `{args.verify}`，无从验证。")
    if args.seed:
        added = seed_from_curator(board)
        if added:
            print("🗂️  从 curator 纳入 " + str(len(added)) + " 件新机会："
                  + "、".join(m.id for m in added))
        else:
            print("🗂️  curator 没给出可纳入的新候选（缺席或都已在册）。")

    _refresh_novelty(board)
    moves = board.flow()
    save_board(board)
    if moves:
        print("🗂️  本趟流转：")
        for mv in moves:
            print(f"     · {mv}")
        print("")
    print(board.render())


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
    # —— 使命看板 🗂️（原 missionboard.py 并入）——
    ap.add_argument("--board", action="store_true", help="自动流转后打印整张使命看板")
    ap.add_argument("--add", metavar="TITLE", help="纳入一件新使命到机会池")
    ap.add_argument("--value", type=int, default=3, help="新使命的价值 0~5(配合 --add)")
    ap.add_argument("--novelty", type=int, default=3, help="新使命的新颖度 0~5(配合 --add)")
    ap.add_argument("--dep", action="append", default=[], metavar="ID",
                    help="新使命依赖的使命 id(可多次;依赖须全验过才解锁,配合 --add)")
    ap.add_argument("--why", default="", help="为什么提这件使命(配合 --add)")
    ap.add_argument("--wip", type=int, default=None, help="把同时开工(进行中)上限改成 N")
    ap.add_argument("--verify", metavar="ID", help="把某使命标为已验证(收口腾位)")
    ap.add_argument("--seed", action="store_true", help="从 curator 候选清单纳入新机会")
    ap.add_argument("--kickoff", action="store_true",
                    help="把头号「进行中」使命交给 plan_goal 起一份计划；"
                         "配合 --delegate 则把汇总的分工方案交给 plan_goal 起计划")
    # —— 分工协作派遣台 🐜（原 delegate.py 并入）——
    ap.add_argument("--delegate", action="store_true",
                    help="把目标横切成可并行子任务，派几只临时分身分头检索/实现/验证后汇总")
    ap.add_argument("--roles", default="",
                    help=f"只派指定分身（逗号分隔，可选 {'/'.join(_ROLES)}；默认全派；配合 --delegate）")
    ap.add_argument("--constraint", action="append", default=[],
                    help="一条硬约束（可多次），如「纯标准库」「别碰 crab.py」（配合 --delegate）")
    args = ap.parse_args(argv)

    # 分工派遣 🐜：任一派遣动作触发就走派遣分支（在计划/看板分支之前截下）
    if args.delegate:
        _cmd_delegate(args)
        return

    if args.recent:
        _cmd_recent()
        return

    # 使命看板：任一看板动作触发，则走看板分支（不与计划路线混淆）
    if (args.board or args.add or args.verify or args.seed or args.kickoff
            or args.wip is not None):
        _cmd_board(args)
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
