#!/usr/bin/env python3
"""师法外物的教练 📒→🧪 —— 把瞭望塔提炼的「招式卡」翻译成「可验收的小实验」。

瞭望塔(lookout)解决了「看见 → 记下来」：从同类项目的 README/Issue/代码思路里
提炼出一张张招式卡（精要/适用/前提/风险/小步试学）。可只攒卡不练，等于把
学习停在了「我知道有这么个招」——招式卡上的「小步试学」是一句愿望，不是一次
能被判定成败的行动。于是常见的失灵是：卡攒了一摞，回头看全是「以后该试试」，
没有一张真的落地过，因为没人把它变成「做什么 + 做到什么程度算学会了」。

教练补的正是这层**翻译**：`forge` 拿一张招式卡，转成一个结构化小实验——

  - 🎯 假设(hypothesis)：练这招，期望在领地里改善什么（一句可证伪的话）；
  - 🪜 步子(steps)：直接复用卡上的「小步试学」，必要时再拆碎；
  - ✅ 验收(accept)：**这次试学怎么算成功**——每条都要可观测、可判定，
    而不是「感觉变好了」。这是教练最核心的产物：把模糊的练习收口成一道考题；
  - ↩️ 回退(rollback)：万一练崩了怎么收手，先想好退路再下场；
  - 🧮 工时(effort)：粗估这次试学的成本档位，好让上层排期。

它只出考卷、不替谁动手，更不裁决：实验是「该怎么练 + 练成什么样」的训练计划，
真要照着练还得过 arena 推演、judge 拍板。教练软引入 lookout：拿不到招式卡就
从容跳过，绝不因上游缺席而崩。实验落进被 .gitignore 的 state/mentor/experiments.jsonl，
可回溯但绝不反噬：读写出错统统吞掉，教练不能成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python mentor.py                 # 把最近的高迁移招式卡批量转成小实验并打印
    python mentor.py --top 3         # 只转排名最高的 3 张卡
    python mentor.py --all           # 不只高迁移，最近所有卡都转
    python mentor.py --min-transfer 3  # 把「高迁移」的门槛放宽到 3/5
    python mentor.py --recent        # 回看最近落档的实验
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_MENTOR_DIR = _REPO_ROOT / "state" / "mentor"          # 与 lookout 共用同一口井
_EXPERIMENTS = _MENTOR_DIR / "experiments.jsonl"       # 每个小实验的快照(可回看 + 去重)

_DEFAULT_MIN_TRANSFER = 4      # 默认只把迁移价值 ≥4/5 的卡转成实验——先练最值得练的
_DEFAULT_TOP = 5               # 默认最多端出 5 个实验，免得一次摊太多无人下场


# 招式原型 → 这一招「练成了」该长什么样的验收骨架。
# 验收标准的灵魂是**可判定**：每条都得能用一次命令 / 一眼对比 / 一个布尔值收尾，
# 不能是「代码更健壮了」这种没法判真假的话。按关键词软匹配卡的原型/精要/名号，
# 命中则套用，命中不了走通用兜底——宁可粗，不可崩。
_PLAYBOOK = [
    {
        "kw": ("retry", "重试", "退避", "backoff", "幂等重放"),
        "hypothesis": "给最常超时的那处外部调用包一层有上限的重试，偶发失败不再直接冒泡成事故。",
        "accept": [
            "注入一次可控的瞬时失败，调用最终成功返回（而非抛错）",
            "重试次数有硬上限，持续失败时按上限停手并落一条可查日志，不无限重试",
            "对已成功的调用不重试——成功路径的行为零变化（回归/快照仍绿）",
        ],
        "rollback": "重试是一层薄包装，出问题摘掉包装即恢复原调用，无数据迁移。",
    },
    {
        "kw": ("降级", "degrade", "兜底", "fallback", "静默"),
        "hypothesis": "给一条非核心旁支加兜底降级，它失败时主流程照常走完而不被拖垮。",
        "accept": [
            "强制让该旁支失败，主流程仍正常产出结果（端到端跑通）",
            "降级被触发时落一条日志，事后能查到「这里降级过」，而非无声吞掉",
            "核心路径的失败绝不被这层兜底吞掉——故意让核心失败，仍能看见报错",
        ],
        "rollback": "降级仅包在旁支上，去掉 try 兜底即回到原行为。",
    },
    {
        "kw": ("plugin", "registry", "注册", "插件", "可插拔", "entrypoint", "hook"),
        "hypothesis": "把两三个同类能力归到一个共同签名 + 注册表，新增一个不必再改散落的 if-else。",
        "accept": [
            "现有同类能力全部经注册表调用，外部行为与改造前逐一对齐（回归绿）",
            "新增一个最小实现，仅注册即生效，无需改动调用方分支",
            "注册表缺项 / 重名时有清晰报错，不静默吞掉",
        ],
        "rollback": "抽象只是收口调用入口，保留原实现即可随时回退到直连。",
    },
    {
        "kw": ("snapshot", "快照", "golden", "回归", "regression", "基线"),
        "hypothesis": "给一条最核心命令固化「输入→标准输出+退出码」，改坏它能当场变红。",
        "accept": [
            "固化基线后跑一次确认绿",
            "故意改坏被测逻辑，快照断言能变红（证明这张网真兜得住）",
            "改回后恢复绿，基线本身可一条命令重生成，不靠手抄",
        ],
        "rollback": "快照是新增测试件，不动产线代码，删测试即除。",
    },
    {
        "kw": ("config", "配置", "env", "校验", "validate", "preflight", "启动前"),
        "hypothesis": "在启动前校验一两个「缺了必崩」的关键配置，把半路崩溃提前成启动即报错。",
        "accept": [
            "缺关键项时启动即给出指名道姓的清晰报错（而非半路才崩）",
            "配置齐全时启动行为零变化",
            "报错信息不打印密钥/敏感值本身，只说「缺哪项」",
        ],
        "rollback": "校验是启动前一道前置检查，删掉即恢复原启动流程。",
    },
    {
        "kw": ("log", "日志", "observ", "trace", "审计", "结构化记录"),
        "hypothesis": "给一条关键路径补一行结构化记录（时间/动作/结果），出事时有据可查。",
        "accept": [
            "走一遍该路径，落档的记录可被读回并解析（合法 JSON 行）",
            "记录里不含密钥/敏感字段",
            "写记录失败被吞掉，绝不拖慢或拖垮主流程（故意让写盘失败，主流程仍走完）",
        ],
        "rollback": "记录是只增不改的观测点，摘掉写入调用即除。",
    },
    {
        "kw": ("idempot", "幂等", "去重", "重复触发", "状态位"),
        "hypothesis": "给一处最怕重复的写操作加「做过就跳过」的状态位，重复触发不再产生重复后果。",
        "accept": [
            "连续触发两次同一操作，副作用只发生一次",
            "去重标识稳定可复算，重启后仍认得「这件做过了」",
            "误判风险有边界——状态丢失时宁可重做也不漏做，并能落日志",
        ],
        "rollback": "状态位是附加的去重旁路，清掉它即回到原始「每次都做」。",
    },
]

# 通用兜底：没归类的招式也逼自己写出一道能判定的考题，而不是放任「以后试试」。
_GENERIC = {
    "hypothesis": "在一个最小旁支场景上仿写这招，验证它确实解决了某个具体痛点（而非为学而学）。",
    "accept": [
        "用一句话说清「练成的标志」是什么，且这句话能被一次运行/一眼对比判定真假",
        "仿写只落在最小旁支，跑通且现有回归/快照仍绿",
        "不引入新的第三方依赖，风格对齐本仓现有同类模块",
    ],
    "rollback": "仿写局限在最小旁支，整段删除即恢复原状，无遗留。",
}


def _match_playbook(card: dict) -> dict:
    """按关键词把招式卡软匹配到一套验收骨架；匹配不上走通用兜底。"""
    hay = " ".join(str(card.get(k, "")) for k in ("archetype", "gist", "title")).lower()
    for play in _PLAYBOOK:
        if any(kw.lower() in hay for kw in play["kw"]):
            return play
    return _GENERIC


def _effort_of(card: dict, steps: list) -> str:
    """粗估这次试学的工时档位：碰要害 / 步子多则更重。纯启发，给上层排期参考。"""
    risks = " ".join(str(r) for r in card.get("risks", []))
    vital = "要害" in risks or "核心" in risks
    n = len(steps)
    if vital or n >= 4:
        return "重（碰要害或步子多，拆开分多次练）"
    if n >= 2:
        return "中（一两个工作时段能跑完一轮）"
    return "轻（一次小改即可验）"


# ── 一个可验收的小实验 ──────────────────────────────────────────────
@dataclasses.dataclass
class Experiment:
    """把一张招式卡翻译成的训练计划：假设 + 步子 + 验收 + 回退 + 工时。"""
    title: str                                              # 实验名号(承自招式卡)
    from_card: str = ""                                     # 源招式卡名号(可回溯)
    source: str = ""                                        # 招式的外部出处
    hypothesis: str = ""                                    # 一句可证伪的期望
    steps: list = dataclasses.field(default_factory=list)   # 怎么做(承自卡的小步试学)
    accept: list = dataclasses.field(default_factory=list)  # 验收标准(可观测/可判定)
    rollback: str = ""                                      # 练崩了怎么退
    effort: str = ""                                        # 工时档位
    transfer: int = 0                                       # 承自卡的迁移价值分
    at: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def render(self) -> str:
        """把一个实验摊成给人看的多行训练计划。"""
        lines = [f"🧪  小实验 · {self.title}（迁移价值 {self.transfer}/5 · 工时 {self.effort}）"]
        if self.source:
            lines.append(f"   学自：{self.source}")
        if self.hypothesis:
            lines.append(f"   🎯 假设：{self.hypothesis}")
        if self.steps:
            lines.append("   🪜 步子：")
            for i, step in enumerate(self.steps, 1):
                lines.append(f"     {i}. {step}")
        if self.accept:
            lines.append("   ✅ 验收标准（每条都要能判定真假）：")
            for c in self.accept:
                lines.append(f"     □ {c}")
        if self.rollback:
            lines.append(f"   ↩️ 回退：{self.rollback}")
        return "\n".join(lines)


# ── 核心：把一张招式卡转成一个小实验 ────────────────────────────────
def forge(card: dict) -> Experiment:
    """拿一张招式卡（lookout 的 MoveCard.to_dict），锻成一个可验收的小实验。

    步骤：① 按原型/精要软匹配出一套验收骨架；② 步子直接复用卡上的「小步试学」；
    ③ 假设取骨架的可证伪期望；④ 把卡的风险翻成「验收时要额外盯住」的反例条款；
    ⑤ 粗估工时。纯启发式，宁可粗、不可崩——拿不准就把验收订得更严、步子拆更碎。
    """
    title = str(card.get("title", "")).split("（来自")[0].strip()[:50] or "(无名招式)"
    play = _match_playbook(card)
    steps = [str(s) for s in card.get("trial", []) if str(s).strip()]
    if not steps:
        steps = ["先在最小旁支仿写一遍，确保能当场验、且不引入新依赖"]

    accept = list(play["accept"])
    # 把卡里点过名的风险，反过来当成验收时必须排除的反例——风险不只是警告，是考题。
    for r in card.get("risks", [])[:2]:
        r = str(r).strip()
        if r:
            accept.append(f"未触发该招的已知风险：{r}")

    return Experiment(
        title=title,
        from_card=title,
        source=str(card.get("source", "")),
        hypothesis=play["hypothesis"],
        steps=steps,
        accept=accept,
        rollback=play["rollback"],
        effort=_effort_of(card, steps),
        transfer=int(card.get("transfer", 0) or 0),
        at=datetime.datetime.now().isoformat(timespec="seconds"),
    )


def _read_jsonl(path: pathlib.Path) -> list:
    """容错读 JSONL：文件缺失/空行/坏行都从容跳过，读取永不抛错。"""
    if not path.exists():
        return []
    out: list = []
    for line in path.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _append(exp: Experiment) -> bool:
    """把一个实验追加成 JSONL 一行；建目录/写盘出错统统吞掉，教练绝不反噬。"""
    try:
        _MENTOR_DIR.mkdir(parents=True, exist_ok=True)
        with _EXPERIMENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(exp.to_dict(), ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def recent(limit: int = 10) -> list:
    """回看最近落档的小实验(时间正序)。"""
    rows = _read_jsonl(_EXPERIMENTS)
    return rows[-limit:] if limit else rows


def forge_from_cards(min_transfer: int = _DEFAULT_MIN_TRANSFER,
                     top: int = _DEFAULT_TOP,
                     take_all: bool = False,
                     persist: bool = True) -> list:
    """从瞭望塔最近的招式卡里挑出值得练的，批量锻成小实验。

    软引入 lookout：拿不到招式卡（没装 gh / 还没攒卡 / import 失败）就返回空，
    绝不因上游缺席而崩。默认只转迁移价值 ≥ min_transfer 的卡，按价值降序、同分时
    新攒的优先——先练最值得练的。已落过档的同名实验不重复落盘（按 title 去重）。
    """
    try:
        import lookout
        cards = lookout.recent(40)
    except Exception:
        return []

    if not take_all:
        cards = [c for c in cards if int(c.get("transfer", 0) or 0) >= min_transfer]
    # 价值降序；recent 是时间正序，故同分时倒序取以让新卡靠前
    cards = sorted(enumerate(cards), key=lambda it: (int(it[1].get("transfer", 0) or 0), it[0]),
                   reverse=True)
    cards = [c for _, c in cards][:top] if top else [c for _, c in cards]

    done = {str(r.get("title", "")) for r in _read_jsonl(_EXPERIMENTS)} if persist else set()
    out: list = []
    for card in cards:
        exp = forge(card)
        if persist and exp.title not in done:
            _append(exp)
            done.add(exp.title)
        out.append(exp)
    return out


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="mentor.py",
        description="师法外物的教练 📒→🧪：把招式卡转成可验收的小实验。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=_DEFAULT_TOP, metavar="N",
                    help=f"最多锻出几个实验(默认 {_DEFAULT_TOP})")
    ap.add_argument("--all", action="store_true",
                    help="不限迁移价值，最近所有招式卡都转")
    ap.add_argument("--min-transfer", type=int, default=_DEFAULT_MIN_TRANSFER, metavar="N",
                    help=f"「高迁移」门槛(默认 {_DEFAULT_MIN_TRANSFER}/5)")
    ap.add_argument("--recent", action="store_true",
                    help="回看最近落档的实验后退出")
    ap.add_argument("--no-persist", action="store_true",
                    help="只打印不落档(干跑)")
    args = ap.parse_args(argv)

    if args.recent:
        rows = recent(args.top)
        if not rows:
            print("（还没攒下任何小实验——先 python mentor.py 把招式卡转成实验）")
            return
        for r in rows:
            print(Experiment(**{k: r.get(k) for k in Experiment.__dataclass_fields__
                                if r.get(k) is not None}).render())
            print()
        return

    exps = forge_from_cards(min_transfer=args.min_transfer, top=args.top,
                            take_all=args.all, persist=not args.no_persist)
    if not exps:
        print("（瞭望塔还没攒下可转的招式卡——先 python lookout.py --scout <方向> 去看看外面）")
        return
    for exp in exps:
        print(exp.render())
        print()
    if not args.no_persist:
        print(f"📒→🧪 已把 {len(exps)} 张招式卡锻成小实验，落档 {_EXPERIMENTS}")


if __name__ == "__main__":
    main()
