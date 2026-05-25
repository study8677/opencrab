#!/usr/bin/env python3
"""摩擦账本 🧱 —— 记录从「需求」到「验证」一路上的卡点、等待与返工，揪出最磨人的那处，
再给它生成一个最小的消除实验。逼自己从「更会评估」转向「更顺手」。

为什么要有它：领地里已经有一排向**质量**看的层——证据(evidence)证「跑得通」、价值
(value)证「对谁有用」、健康(health)证「自检全过」。它们都在答「我做得对不对、好不
好」，却没人答另一个同样要命的问题：**我做得顺不顺？** 同一件事，这次花了十分钟、
下次卡了两小时，差的往往不是能力，是一路上的摩擦——某步老是卡住、某处总在干等、某
块反复返工。摩擦不会让自检变红，所以它**隐形**：绿灯全亮，我却越做越累、越绕越远。

本层把每一次「不顺」当成一条可记录的证据，钉在两个轴上：

  · 阶段(stage) —— 这处摩擦发生在「需求→验证」哪一段：
        intent(读需求) · plan(定方案) · build(动手做) · verify(自测验证) · land(落地合并)
  · 种类(kind)  —— 它是哪一类不顺：
        🚧 blocker(卡点)：被挡住、推不动，要先解决别的才能继续
        ⏳ wait(等待)   ：人没事干、在等某个外部过程(构建/复跑/审查)结束
        🔁 rework(返工) ：做完又推倒重来——错误在太靠下游的地方才暴露

记一条摩擦只要回答：在哪个阶段、哪一类、磨了多久(cost 分钟)、为了什么(topic)。攒够
几条，账本就能把它们**按 阶段×种类 聚类**，用「总耗时 × 出现次数」排出**最磨人的那
一簇**——不是最响的那次抱怨，是长期看偷走我最多时间的那处。

光揪出来还不够，关键是**消除**。对最大那簇摩擦，账本按它的种类给出一个**最小消除实
验**：一句假设(它为什么磨人)、一个动作(最小代价怎么改)、一条验证(下一个窗口怎么量它
真变少了)。实验不替我拍板，但逼我把「这里好烦」变成「我打算这样让它不烦，并这样验证」。

用法:
    python friction.py log --stage verify --kind wait --cost 25 --topic "等全量复跑"
                                       # 记一条摩擦(其余子命令都只读，不落盘)
    python friction.py                 # 摩擦清单 + 按 阶段×种类 排出的最磨人簇
    python friction.py --top           # 只报最磨人的那一簇
    python friction.py --experiment    # 给最磨人的那簇生成一个最小消除实验
    python friction.py --since 14      # 把回看窗口收/放到近 N 天(默认全部)
    python friction.py --quiet         # 只在「攒够样本且有明显主摩擦」时说话(钩子 / CI)
    python friction.py --json          # 机读:导出全部摩擦条目 + 聚类 + 实验

零第三方依赖,纯标准库。账本是观测者:记录写盘失败被吞、读不到就当空,绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import append_jsonl, read_jsonl  # noqa: E402  —— 复用领地统一的 JSONL 存取

LOG_PATH = REPO_ROOT / "state" / "friction.jsonl"

# 攒够这么多条才敢点名「最磨人的一簇」——样本太少时，排第一的多半是偶然，不是规律。
MIN_SAMPLES = 3

# 「需求→验证」的五段,按时间顺序(展示与校验都依赖这个顺序)。
STAGES: dict[str, str] = {
    "intent": "读需求",
    "plan": "定方案",
    "build": "动手做",
    "verify": "自测验证",
    "land": "落地合并",
}

# 三类不顺,每类配一个图标与一句「它到底在偷什么」。
KINDS: dict[str, str] = {
    "blocker": "卡点",
    "wait": "等待",
    "rework": "返工",
}
_KIND_ICON = {"blocker": "🚧", "wait": "⏳", "rework": "🔁"}


@dataclasses.dataclass(frozen=True)
class Friction:
    """一条摩擦:在「需求→验证」某阶段、某一类不顺,磨了多久、为了什么。"""
    stage: str       # STAGES 之一:这处摩擦发生在哪一段
    kind: str        # KINDS 之一:卡点 / 等待 / 返工
    cost: float      # 这次磨掉的分钟数(粗估即可,重要的是相对量级)
    topic: str       # 一句话:为了什么事卡住(便于聚类后回看具体场景)
    ts: str          # ISO8601 记录时刻

    @property
    def cluster(self) -> tuple[str, str]:
        """聚类键:同一阶段、同一类的摩擦归成一簇。"""
        return (self.stage, self.kind)

    def to_meta(self) -> dict:
        return {"stage": self.stage, "kind": self.kind, "cost": self.cost,
                "topic": self.topic, "ts": self.ts}


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _parse(rec: dict) -> Friction | None:
    """把一行 JSONL 还原成 Friction;阶段/种类非法或缺字段 → 跳过(不让脏行带崩聚类)。"""
    stage, kind = rec.get("stage"), rec.get("kind")
    if stage not in STAGES or kind not in KINDS:
        return None
    try:
        cost = float(rec.get("cost", 0) or 0)
    except (TypeError, ValueError):
        cost = 0.0
    return Friction(stage=stage, kind=kind, cost=max(0.0, cost),
                    topic=str(rec.get("topic", "")).strip(),
                    ts=str(rec.get("ts", "")))


def _within(ts: str, since_days: int | None) -> bool:
    """记录是否落在回看窗口内;since 为 None=不限,坏时间戳一律放行(宁可多看)。"""
    if since_days is None or not ts:
        return True
    try:
        when = datetime.datetime.fromisoformat(ts)
    except ValueError:
        return True
    cutoff = datetime.datetime.now(when.tzinfo) - datetime.timedelta(days=since_days)
    return when >= cutoff


def load(since_days: int | None = None) -> list[Friction]:
    """读出窗口内的全部摩擦条目(时间正序);文件缺失/坏行都安全跳过。"""
    out = []
    for rec in read_jsonl(LOG_PATH):
        f = _parse(rec)
        if f is not None and _within(f.ts, since_days):
            out.append(f)
    return out


def record(stage: str, kind: str, cost: float, topic: str) -> bool:
    """记一条摩擦到 JSONL;阶段/种类非法直接拒绝。写盘失败被吞,绝不反噬生命。"""
    if stage not in STAGES:
        raise ValueError(f"阶段须是 {'/'.join(STAGES)} 之一,收到 {stage!r}")
    if kind not in KINDS:
        raise ValueError(f"种类须是 {'/'.join(KINDS)} 之一,收到 {kind!r}")
    f = Friction(stage=stage, kind=kind, cost=max(0.0, float(cost)),
                 topic=topic.strip(), ts=_now_iso())
    return append_jsonl(LOG_PATH, f.to_meta())


@dataclasses.dataclass(frozen=True)
class Cluster:
    """一簇同阶段同类的摩擦:多少次、合计磨了多久、磨人指数。"""
    stage: str
    kind: str
    count: int
    total_cost: float
    topics: list[str]   # 这簇里出现过的具体事由(去重,保留出现顺序)

    @property
    def pain(self) -> float:
        """磨人指数 = 总耗时 × 出现次数:既偷得多、又反复发生的,才最该先治。

        只看总耗时会被「一次性的大坑」带偏;只看次数会高估「频繁但每次很短」的小烦。
        两者相乘,让「又频繁、又昂贵」的那簇自然浮到最前——那才是顺手与否的真瓶颈。
        """
        return self.total_cost * self.count

    def to_meta(self) -> dict:
        return {"stage": self.stage, "kind": self.kind, "count": self.count,
                "total_cost": round(self.total_cost, 1), "pain": round(self.pain, 1),
                "topics": self.topics}


def cluster(items: list[Friction]) -> list[Cluster]:
    """把摩擦按 阶段×种类 聚类,按磨人指数降序——最磨人的一簇排在最前。"""
    buckets: dict[tuple[str, str], list[Friction]] = {}
    for f in items:
        buckets.setdefault(f.cluster, []).append(f)
    clusters = []
    for (stage, kind), fs in buckets.items():
        topics: list[str] = []
        for f in fs:
            if f.topic and f.topic not in topics:
                topics.append(f.topic)
        clusters.append(Cluster(stage=stage, kind=kind, count=len(fs),
                                 total_cost=sum(f.cost for f in fs), topics=topics))
    clusters.sort(key=lambda c: (c.pain, c.count, c.total_cost), reverse=True)
    return clusters


# ── 消除实验:把「这里好烦」变成「我打算这样让它不烦,并这样验证」 ──────────
# 每类摩擦对应一种最廉价的治法思路:
#   卡点 → 把它前移成一道预检,让障碍在更早、更便宜处就暴露;
#   等待 → 把同步的干等改成异步/缓存/预热,让人手不被外部过程绑住;
#   返工 → 在上游加一道验收,让错误在离源头最近、改起来最便宜的地方就被拦下。
_EXPERIMENT_BY_KIND = {
    "blocker": (
        "这个卡点每次都要先停下来解决别的才能继续,说明障碍暴露得太晚。",
        "在「{stage}」这步前面加一道最小预检(命令/清单),把它会卡住的条件提前问一遍。",
        "下个窗口再记摩擦:这一簇的「{kind}」次数应明显下降,或耗时从此段前移、总量变小。",
    ),
    "wait": (
        "这处等待让我在「{stage}」干耗——人闲着、只等外部过程跑完,时间是纯漏掉的。",
        "把这步的同步等待改成异步/缓存/预热其一:要么后台跑、腾出手做别的,要么把上次结果缓存复用。",
        "下个窗口再记摩擦:这一簇「{kind}」的总耗时应明显下降(等待被并行或省掉)。",
    ),
    "rework": (
        "在「{stage}」反复返工,意味着错误在太靠下游的地方才暴露,改起来已经很贵。",
        "在更上游加一道验收(更早的 --check / 契约 / 样例),让这类错误在离源头最近处就被拦下。",
        "下个窗口再记摩擦:这一簇「{kind}」次数应下降,且返工点应从此段上移到更便宜的上游。",
    ),
}


@dataclasses.dataclass(frozen=True)
class Experiment:
    """对最磨人那簇摩擦的一个最小消除实验:假设 → 动作 → 验证。"""
    target: Cluster
    hypothesis: str
    action: str
    verify: str

    def to_meta(self) -> dict:
        return {"target": self.target.to_meta(), "hypothesis": self.hypothesis,
                "action": self.action, "verify": self.verify}


def experiment(top: Cluster) -> Experiment:
    """给最磨人的一簇摩擦生成一个最小消除实验(按它的种类挑治法)。"""
    stage_label = STAGES[top.stage]
    kind_label = KINDS[top.kind]
    hyp_t, act_t, ver_t = _EXPERIMENT_BY_KIND[top.kind]
    fmt = {"stage": stage_label, "kind": kind_label}
    return Experiment(target=top, hypothesis=hyp_t.format(**fmt),
                      action=act_t.format(**fmt), verify=ver_t.format(**fmt))


# ── 展示 ──────────────────────────────────────────────────────────────
def _fmt_cluster(c: Cluster) -> str:
    return (f"{_KIND_ICON[c.kind]} {STAGES[c.stage]}·{KINDS[c.kind]}"
            f"（{c.count} 次 / 共 {c.total_cost:.0f} 分钟 / 磨人指数 {c.pain:.0f}）")


def _print_list(items: list[Friction], clusters: list[Cluster]) -> None:
    if not items:
        print("🧱 摩擦账本还空着——用 `python friction.py log ...` 记下第一处「不顺」。")
        print("   每条只要回答:哪个阶段、哪一类(卡点/等待/返工)、磨了多久、为了什么。")
        return
    total = sum(f.cost for f in items)
    print(f"🧱 opencrab 摩擦账本（{len(items)} 条 / 合计 {total:.0f} 分钟 / {len(clusters)} 簇）\n")
    for c in clusters:
        print(f"  {_fmt_cluster(c)}")
        if c.topics:
            shown = "、".join(c.topics[:3]) + ("…" if len(c.topics) > 3 else "")
            print(f"      事由：{shown}")
    if len(items) < MIN_SAMPLES:
        print(f"\n  样本还少（<{MIN_SAMPLES} 条），先别急着点名主摩擦——再记几条更可信。")
    else:
        print(f"\n  最磨人的一簇 → {_fmt_cluster(clusters[0])}")
        print("  跑 `--experiment` 让它生成一个最小消除实验。")


def _print_experiment(exp: Experiment) -> None:
    print(f"🧱 最磨人的一簇：{_fmt_cluster(exp.target)}\n")
    print("  🔬 最小消除实验")
    print(f"      假设：{exp.hypothesis}")
    print(f"      动作：{exp.action}")
    print(f"      验证：{exp.verify}")
    if exp.target.topics:
        shown = "、".join(exp.target.topics[:3]) + ("…" if len(exp.target.topics) > 3 else "")
        print(f"\n      它具体卡在：{shown}")
    print("\n  实验不替你拍板;它只把「这里好烦」翻成「我打算这样让它不烦,并这样验证」。")


def manifest(since_days: int | None) -> dict:
    """导出纯数据:窗口内全部摩擦 + 聚类 + 主摩擦的消除实验(样本不足则无实验)。"""
    items = load(since_days)
    clusters = cluster(items)
    out = {
        "count": len(items),
        "total_cost": round(sum(f.cost for f in items), 1),
        "min_samples": MIN_SAMPLES,
        "entries": [f.to_meta() for f in items],
        "clusters": [c.to_meta() for c in clusters],
        "experiment": None,
    }
    if len(items) >= MIN_SAMPLES and clusters:
        out["experiment"] = experiment(clusters[0]).to_meta()
    return out


def _has_clear_top(items: list[Friction], clusters: list[Cluster]) -> bool:
    """样本够、且确有一簇排在最前——值得在 --quiet 下打断说话。"""
    return len(items) >= MIN_SAMPLES and bool(clusters)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 摩擦账本 🧱")
    sub = ap.add_subparsers(dest="cmd")

    p_log = sub.add_parser("log", help="记一条摩擦(卡点/等待/返工)")
    p_log.add_argument("--stage", required=True, choices=list(STAGES),
                       help="发生在「需求→验证」哪一段")
    p_log.add_argument("--kind", required=True, choices=list(KINDS),
                       help="哪一类不顺:blocker(卡点)/wait(等待)/rework(返工)")
    p_log.add_argument("--cost", type=float, required=True, help="这次磨掉的分钟数(粗估)")
    p_log.add_argument("--topic", default="", help="一句话:为了什么事卡住")

    ap.add_argument("--since", type=int, default=None, metavar="N",
                    help="只看近 N 天的摩擦(默认:全部)")
    ap.add_argument("--top", action="store_true", help="只报最磨人的那一簇")
    ap.add_argument("--experiment", action="store_true",
                    help="给最磨人的那簇生成一个最小消除实验")
    ap.add_argument("--quiet", action="store_true",
                    help="只在攒够样本且有明显主摩擦时说话(钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出机读:条目 + 聚类 + 实验")
    args = ap.parse_args(argv)

    if args.cmd == "log":
        ok = record(args.stage, args.kind, args.cost, args.topic)
        icon = _KIND_ICON[args.kind]
        where = f"{STAGES[args.stage]}·{KINDS[args.kind]}"
        if ok:
            print(f"🧱 记下一处摩擦 {icon} {where}（{args.cost:.0f} 分钟）。")
        else:
            print(f"⚠️  这条摩擦没落盘(写盘失败已吞),但生命照常——{icon} {where}。")
        return

    items = load(args.since)
    clusters = cluster(items)

    if args.json:
        print(json.dumps(manifest(args.since), ensure_ascii=False, indent=2))
        sys.exit(0)

    has_top = _has_clear_top(items, clusters)

    if args.experiment:
        if not has_top:
            if not args.quiet:
                print(f"🧱 样本还不足 {MIN_SAMPLES} 条,先多记几处摩擦再生成消除实验。")
            sys.exit(1)
        _print_experiment(experiment(clusters[0]))
        sys.exit(0)

    if args.top:
        if not has_top:
            if not args.quiet:
                print(f"🧱 样本还不足 {MIN_SAMPLES} 条,还排不出可信的主摩擦。")
            sys.exit(1)
        print(f"🧱 最磨人的一簇 → {_fmt_cluster(clusters[0])}")
        if clusters[0].topics:
            shown = "、".join(clusters[0].topics[:3]) + ("…" if len(clusters[0].topics) > 3 else "")
            print(f"   事由：{shown}")
        sys.exit(0)

    if args.quiet:
        if has_top:
            print(f"🧱 主摩擦 → {_fmt_cluster(clusters[0])}（跑 `friction.py --experiment` 治它）")
            sys.exit(1)
        sys.exit(0)

    _print_list(items, clusters)
    sys.exit(0)


if __name__ == "__main__":
    main()
