#!/usr/bin/env python3
"""使命看板 🗂️ —— 把长期使命拆成「机会池 → 进行中 → 阻塞 → 已验证」四道泳道，
按价值 / 新颖度 / 依赖自动流转，并硬性限制同时开工数，免得这只生命总在局部反复打转。

为什么要有它：这只螃蟹已经会**规划单条路线**(planner)、会**汇编候选行动**(curator)、
会**把一件事拆开并行**(delegate)——可这些本事都盯着「眼下这一件」：planner 走一条线、
curator 端一份清单、delegate 拆一个目标。它始终缺一张能横跨**很多件长期使命**、管住
**整体节奏**的台子：哪些只是机会、哪些正在做、哪些被依赖卡住、哪些已经验过收了。于是
常见的失灵是**贪多**与**打转**：同时上手七八件，每件都做一半；或反复在同一个局部使劲，
新的机会进不来、卡住的事没人挪走。

使命看板补的正是这层**进化投资组合的流控**：

  - 🪧 四道泳道：🌊 机会池(还没动) → 🔨 进行中(正在做) → 🧱 阻塞(被未完成的依赖卡住)
    → ✅ 已验证(做完且收过)。验证是**外部动作**(judge/人来拍板)，看板从不自动判完工。
  - 🚦 限同时开工(WIP)：进行中的位子有限(默认 2)，腾不出位子，机会池里再值钱的事也得排队
    ——这正是治「总在局部打转 / 同时上手太多」的那道闸。
  - 🔁 自动流转：依赖没全验过的使命一律压回阻塞；依赖齐了就有资格进场；进场名额按
    价值×2 + 新颖度 排序择优，已在做的优先留场免得来回横跳，溢出的退回机会池等位。

它只排布、不动手，更不替 judge 拍板——看板是「整体节奏该怎么摆」的参谋台。软引入
curator / memory：拿不到就从容退化(没有候选可纳、新颖度退成「标题撞车才算老」)，绝不
因某个上游缺席而崩。看板状态落进被 .gitignore 的 state/missionboard/，可回溯但绝不反噬：
读写出错统统吞掉，看板不能成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python missionboard.py                          # 自动流转后打印整张看板
    python missionboard.py --add "上线遥测面板" --value 5 --novelty 3
    python missionboard.py --add "补回归测试" --dep telemetry-panel   # 声明依赖
    python missionboard.py --wip 3                  # 临时把同时开工上限调成 3
    python missionboard.py --verify telemetry-panel # 把某使命标为已验证(收口)
    python missionboard.py --seed                   # 从 curator 候选清单纳入新机会
    python missionboard.py --kickoff                # 把头号「进行中」使命交给 planner 起计划
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_BOARD_DIR = _REPO_ROOT / "state" / "missionboard"      # 落在被 .gitignore 的 state/ 里
_BOARD_FILE = _BOARD_DIR / "board.json"                 # 当前看板(单一真相，原地更新)

# 四道泳道(顺序即「价值流」方向)
POOL, DOING, BLOCKED, VERIFIED = "pool", "doing", "blocked", "verified"
_LANES = [POOL, DOING, BLOCKED, VERIFIED]
_LANE_LABEL = {POOL: "🌊 机会池", DOING: "🔨 进行中", BLOCKED: "🧱 阻塞", VERIFIED: "✅ 已验证"}

_DEFAULT_WIP = 2        # 同时开工(进行中)默认上限——治「贪多 / 局部打转」的那道闸
_W_VALUE, _W_NOVELTY = 2, 1     # 进场排序权重：价值比新颖度更要紧


# ── 一件使命 ────────────────────────────────────────────────────────
@dataclasses.dataclass
class Mission:
    """看板上的一件长期使命：它值不值得做(value)、新不新鲜(novelty)、要等哪几件先验过(deps)。"""
    id: str                                     # 稳定短 id(据标题生成，用于声明依赖)
    title: str                                  # 一句话使命(将来可直接当 planner 目标)
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
                         "——`python missionboard.py --kickoff` 可交给 planner 起计划。")
        elif self.in_lane(POOL):
            lines.append("   👉 进行中是空的——下次流转会从机会池择优补位；或先 --verify 收口腾位。")
        return "\n".join(lines)


# ── 小工具 ──────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _clamp(n: object) -> int:
    """把分数夹到 0~5,解析不了就给中性 3——绝不因脏输入抛异常。"""
    try:
        return max(0, min(5, int(n)))      # type: ignore[arg-type]
    except Exception:
        return 3


def _slug(title: str, taken: set | None = None) -> str:
    """据标题生成稳定短 id:取英文/数字词,没有就用拼音首字之外的兜底;撞号自动加序。"""
    taken = taken or set()
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    base = "-".join(words)[:32].strip("-")
    if not base:                            # 全中文/无可用字符:用长度+时间尾做兜底
        base = "m" + _now()[-6:].replace(":", "")
    sid, i = base, 2
    while sid in taken:
        sid = f"{base}-{i}"
        i += 1
    return sid


# ── 落地 / 读取(单一真相,原地更新) ─────────────────────────────────
def load() -> Board:
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


def _clamp_wip(n: object) -> int:
    try:
        return max(1, int(n))       # type: ignore[arg-type]
    except Exception:
        return _DEFAULT_WIP


def save(board: Board) -> Board:
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


# ── 给 crab / CLI 的便捷入口 ────────────────────────────────────────
def tick(wip: int | None = None) -> Board:
    """读看板 → (可选改 WIP) → 自动流转 → 落档,供心跳「摆一摆整体节奏」时调用。"""
    board = load()
    if wip is not None:
        board.wip = _clamp_wip(wip)
    _refresh_novelty(board)
    board.flow()
    return save(board)


def kickoff() -> dict:
    """把头号「进行中」使命当目标交给 planner 起一份计划(主动推进当下主攻)。

    这是看板唯一一处「越过参谋身份去推一把」的动作,且仍只动 planner(不动手改代码、
    不替 judge 拍板)。没有进行中使命 / planner 缺席时从容返回说明,绝不抛异常打断心跳。
    """
    board = tick()
    doing = board.in_lane(DOING)
    if not doing:
        return {"ok": False, "reason": "进行中是空的,没有可发起的使命"}
    top = doing[0]
    try:
        import planner
        plan = planner.plan_goal(top.title)
        return {"ok": True, "goal": top.title, "id": top.id, "steps": len(plan.steps)}
    except Exception as e:
        return {"ok": False, "reason": f"planner 没接上：{e}", "goal": top.title}


# ── CLI ─────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="missionboard.py",
        description="🗂️ 使命看板：把长期使命拆成机会池/进行中/阻塞/已验证四道泳道,按价值×新颖×依赖自动流转并限同时开工数",
        formatter_class=argparse.RawDescriptionHelpFormatter)
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
                    help="把头号「进行中」使命交给 planner 起一份计划")
    args = ap.parse_args(argv)

    if args.kickoff:
        out = kickoff()
        if out.get("ok"):
            print(f"🗂️  已发起:planner 已就「{out['goal']}」起了一份 {out['steps']} 步的计划。")
            print("    用 `python planner.py --show` 看路线。")
        else:
            print(f"🗂️  没能发起：{out.get('reason', '未知原因')}")
        return

    board = load()
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
    save(board)
    if moves:
        print("🗂️  本趟流转：")
        for mv in moves:
            print(f"     · {mv}")
        print("")
    print(board.render())


if __name__ == "__main__":
    main()
