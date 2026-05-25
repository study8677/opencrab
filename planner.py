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
