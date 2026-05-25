#!/usr/bin/env python3
"""需求信号市场 📡 —— 持续从外界真实声音里（GitHub issue / PR / README / 提交讨论）
聚出一个「需求信号市场」，让这只生命据**世界要什么**来校准进化方向，而不是只靠内省越练越窄。

为什么要有它：这只螃蟹已经会**自己想要做什么**（curator 端候选、missionboard 排投资组合、
planner 起路线）——可这些井口全朝**内**：候选从 memory / mentor / dialogue 来，新颖度照着
「跟自己已做的像不像」算。只照镜子的危险是**越练越窄**：在自己擅长、自己想得到的小圈里
反复使劲，做出来的东西越来越自洽、却离**别人真正需要**越来越远（典型的 Goodhart：把
「我觉得好」当成了「真有用」）。

需求信号市场补的正是这层**外部校准**：把外界零散的声音收成可比价的「行情」——

  - 📥 多口外部井，各自从容退化：issue / PR（经瞭望塔 lookout 这只唯一的眼收口调 `gh`，
    没装/没登录就跳过）、
    最近提交讨论（git log 正文）、README（写明的使命与承诺）。任一口井缺席都不报错，
    市场照样从拿得到的声音里出价。
  - 🧮 把零散声音聚成「信号」：相近的诉求归成同一条主题（软调 memory.similarity 做
    中英混合相似，拿不到就退化成关键词词袋撞车），一条信号 = 一群指向同一需求的声音。
  - 💰 按「行情」给信号定价：价 = Σ(来源权重 × 时间衰减)。issue 这类**外人主动开口**的
    最值钱，PR 次之，提交讨论与 README 再次之；越近的声音越重（半衰期约 30 天）。
    复现越多、越新、越来自外部的诉求，出价越高——这正是「该为世界变强在哪」的行情牌。

它只**听与定价**，不动手、更不替 missionboard / judge 拍板：把头部需求**软推**进
missionboard 机会池（撞车自动去重），剩下交给既有的投资组合流控去排。市场行情落进被
.gitignore 的 state/market/，读写出错统统吞掉——听世界的耳朵，绝不能成为新的故障源。

零第三方依赖，纯标准库（外部井经 `gh` / `git` 子进程读取，缺则退化）。

用法:
    python market.py                       # 收一遍行情后打印需求信号市场
    python market.py --harvest             # 只重收外部声音、刷新行情
    python market.py --top 5               # 只看出价最高的 5 条需求信号
    python market.py --no-fetch            # 不调外部井，仅就已存行情重新打印
    python market.py --seed                # 把头部需求软推进 missionboard 机会池
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import math
import pathlib
import re
import subprocess

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_MARKET_DIR = _REPO_ROOT / "state" / "market"           # 落在被 .gitignore 的 state/ 里
_MARKET_FILE = _MARKET_DIR / "market.json"              # 当前行情(聚好的信号，单一真相)
_RAW_FILE = _MARKET_DIR / "raw.jsonl"                   # 历次收来的原始声音(可回溯的流水)

# 各口外部井的「来源权重」——外人主动开口最值钱，自家提交讨论与写明的使命再次之
_SOURCE_WEIGHT = {"issue": 1.0, "pr": 0.8, "commit": 0.4, "readme": 0.3}
_SOURCE_LABEL = {"issue": "🐛 issue", "pr": "🔀 PR", "commit": "📝 提交讨论", "readme": "📖 README"}

_HALF_LIFE_DAYS = 30.0      # 时间衰减半衰期：越近的声音越重，约一个月减半
_CLUSTER_SIM = 0.34         # 两条声音相似度过此线就归为同一条需求信号
_MAX_RAW_KEEP = 400         # 原始流水最多留这么多条，免得 state 无限膨胀

# 这些词太泛，聚主题时当噪声滤掉(中英混排)
_STOP = {"the", "and", "for", "with", "this", "that", "you", "are", "but", "not",
         "add", "fix", "use", "self", "evolve", "进化", "一个", "我要", "我想", "因为",
         "可以", "需要", "把", "让", "的", "了", "和", "与", "在", "是", "它", "我"}


# ── 一条原始声音 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Voice:
    """从某口外部井收来的一条原始声音：是谁说的、说了啥、什么时候说的。"""
    source: str             # issue / pr / commit / readme
    text: str               # 这条声音的正文(标题+摘要)
    ref: str = ""           # 出处标识(issue 号 / 提交短哈希 等)
    at: str = ""            # 这条声音的时间(ISO，缺则按收取时刻)

    def weight(self, now: datetime.datetime | None = None) -> float:
        """这条声音此刻的份量 = 来源权重 × 时间衰减。"""
        base = _SOURCE_WEIGHT.get(self.source, 0.3)
        return base * _recency_decay(self.at, now)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── 一条需求信号(一群指向同一诉求的声音) ───────────────────────────
@dataclasses.dataclass
class Signal:
    """市场上的一条需求信号：一群相近声音聚成的「世界想要什么」，连同它此刻的出价。"""
    theme: str                                              # 一句话主题(取最具代表性的那条声音)
    voices: list = dataclasses.field(default_factory=list)  # list[Voice]，支撑这条信号的声音

    @property
    def price(self) -> float:
        """出价：所有支撑声音的份量之和——复现越多、越新、越外部，价越高。"""
        return round(sum(v.weight() for v in self.voices), 3)

    @property
    def sources(self) -> list[str]:
        """这条信号被哪些口井提到过(去重、按权重降序)——跨井复现是「真需求」的强证据。"""
        seen = {v.source for v in self.voices}
        return sorted(seen, key=lambda s: _SOURCE_WEIGHT.get(s, 0), reverse=True)

    def to_dict(self) -> dict:
        return {"theme": self.theme, "price": self.price,
                "sources": self.sources, "voices": [v.to_dict() for v in self.voices]}

    def render(self) -> str:
        srcs = "、".join(_SOURCE_LABEL.get(s, s) for s in self.sources)
        cross = " 🔁跨井" if len(self.sources) > 1 else ""
        head = f"[{self.price:>5.2f}] {self.theme}（{len(self.voices)} 声 · {srcs}{cross}）"
        sample = self.voices[0].ref if self.voices and self.voices[0].ref else ""
        return head + (f"\n          ↳ 例：{sample}" if sample else "")


# ── 一整个市场 ──────────────────────────────────────────────────────
@dataclasses.dataclass
class Market:
    """需求信号市场：把零散声音聚成的所有信号，按出价排着的一张行情牌。"""
    signals: list = dataclasses.field(default_factory=list)      # list[Signal]
    updated_at: str = ""

    def ranked(self) -> list[Signal]:
        return sorted(self.signals, key=lambda s: s.price, reverse=True)

    def to_dict(self) -> dict:
        return {"updated_at": self.updated_at,
                "signals": [s.to_dict() for s in self.ranked()]}

    def render(self, top: int | None = None) -> str:
        ranked = self.ranked()
        shown = ranked[:top] if top else ranked
        when = (self.updated_at or _now())[:16].replace("T", " ")
        lines = [f"📡 需求信号市场 · {len(ranked)} 条信号 · {when}", ""]
        if not ranked:
            lines.append("   （行情空着——外部井都没声音，或 `gh` 没装/没登录。")
            lines.append("    用 `python market.py --harvest` 重收一遍，或先去仓库开个 issue。）")
            return "\n".join(lines)
        lines.append("   行情牌（出价越高 = 世界越需要、越值得为它变强）：")
        for s in shown:
            lines.append("   " + s.render())
        if top and len(ranked) > top:
            lines.append(f"\n   …… 还有 {len(ranked) - top} 条更轻的信号(用 --top 调多少)。")
        top1 = ranked[0]
        lines.append(f"\n   👉 当下世界最想要：「{top1.theme}」"
                     "——`python market.py --seed` 可软推进 missionboard 机会池。")
        return "\n".join(lines)


# ── 小工具 ──────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _recency_decay(at: str, now: datetime.datetime | None = None) -> float:
    """据声音的年龄做指数衰减(半衰期 30 天)；解析不了时间就当此刻(不衰减)。"""
    now = now or datetime.datetime.now()
    try:
        t = datetime.datetime.fromisoformat(at[:19])
        age = max(0.0, (now - t).total_seconds() / 86400.0)
        return 0.5 ** (age / _HALF_LIFE_DAYS)
    except Exception:
        return 1.0


def _tokens(text: str) -> set[str]:
    """中英混合词袋：英文词 + 单个中文字，滤掉太泛的停用词——给没有 memory 时兜底聚类。"""
    words = re.findall(r"[a-z0-9]{2,}", (text or "").lower())
    hans = re.findall(r"[一-鿿]", text or "")
    return {w for w in (words + hans) if w not in _STOP}


def _similar(a: str, b: str) -> float:
    """两条声音有多像：软调 memory.similarity(中英混合 Jaccard)，拿不到就退化成自家词袋。"""
    try:
        from memory import similarity as _sim
        return _sim(a, b)
    except Exception:
        ta, tb = _tokens(a), _tokens(b)
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        return inter / len(ta | tb) if inter else 0.0


def _run(cmd: list[str], timeout: int = 20) -> str:
    """跑一条只读命令收外部声音；任何失败(没装/没登录/超时)都从容退化成空串。"""
    try:
        p = subprocess.run(cmd, cwd=str(_REPO_ROOT), capture_output=True,
                           text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


# ── 外部井：各自从容退化，缺一口不影响其余 ──────────────────────────
def _harvest_github(kind: str, limit: int = 40) -> list[Voice]:
    """读 issue / PR 的外部声音——收口到瞭望塔(lookout)这只唯一的「眼睛」。

    所有对 `gh` 的调用都归 lookout.harvest 一处闸门：没装 gh、没登录、不是
    GitHub 仓、lookout 缺席都从容返回空，绝不在市场里再各 shell 一遍 gh。
    """
    try:
        import lookout
        rows = lookout.harvest(kind, limit=limit)
    except Exception:
        return []
    src = "issue" if kind == "issue" else "pr"
    voices: list[Voice] = []
    for r in rows:
        title = str(r.get("title", "")).strip()
        body = str(r.get("body", "") or "")[:280].strip()
        if not title:
            continue
        voices.append(Voice(source=src, text=(title + " " + body).strip(),
                            ref=f"#{r.get('number', '?')} {title}"[:80],
                            at=str(r.get("createdAt", ""))))
    return voices


def _harvest_commits(limit: int = 60) -> list[Voice]:
    """读最近提交的标题+正文当「提交讨论」；非 git 仓 / 出错都从容返回空。"""
    out = _run(["git", "log", f"-{limit}", "--no-merges",
                "--pretty=format:%H%x1f%cI%x1f%s%x1f%b%x1e"])
    if not out:
        return []
    voices: list[Voice] = []
    for rec in out.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 3:
            continue
        h, ci, subj = parts[0], parts[1], parts[2]
        body = parts[3] if len(parts) > 3 else ""
        text = (subj + " " + body[:200]).strip()
        if not text:
            continue
        voices.append(Voice(source="commit", text=text,
                           ref=f"{h[:8]} {subj}"[:80], at=ci))
    return voices


def _harvest_readme() -> list[Voice]:
    """读 README 里写明的使命/承诺当一类「世界对它的期待」；缺文件从容返回空。"""
    voices: list[Voice] = []
    for name in ("README.md", "CONTRIBUTING.md"):
        f = _REPO_ROOT / name
        try:
            text = f.read_text("utf-8", errors="ignore")
        except Exception:
            continue
        # 只取标题行(# / ## 开头)——那是写明的意图，信息密度最高
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#"):
                title = s.lstrip("#").strip()
                if len(title) >= 4:
                    voices.append(Voice(source="readme", text=title,
                                       ref=f"{name}: {title}"[:80], at=_now()))
    return voices


def harvest_voices() -> list[Voice]:
    """把所有外部井收来的声音汇成一摊原始素材；任一口井缺席都不影响其余。"""
    voices: list[Voice] = []
    voices += _harvest_github("issue")
    voices += _harvest_github("pr")
    voices += _harvest_commits()
    voices += _harvest_readme()
    return voices


# ── 把零散声音聚成需求信号 ──────────────────────────────────────────
def cluster(voices: list[Voice]) -> list[Signal]:
    """把相近的声音贪心地归成同一条需求信号：每条新声音并进最像的既有信号，
    都不够像就自立一条。代表主题取该信号里最早(或最具体)的那条声音文本。"""
    signals: list[Signal] = []
    # 重的声音先安家，让出价高的诉求优先定主题
    for v in sorted(voices, key=lambda x: x.weight(), reverse=True):
        best, best_sim = None, 0.0
        for s in signals:
            sim = _similar(v.text, s.theme)
            if sim > best_sim:
                best, best_sim = s, sim
        if best is not None and best_sim >= _CLUSTER_SIM:
            best.voices.append(v)
        else:
            signals.append(Signal(theme=_theme_of(v), voices=[v]))
    return signals


def _theme_of(v: Voice) -> str:
    """给一条信号起个一句话主题：取声音正文的头一句/前 60 字，去掉收尾噪声。"""
    text = re.split(r"[。.\n]", v.text.strip(), maxsplit=1)[0].strip()
    return (text or v.text.strip())[:60] or "(未命名需求)"


# ── 落地 / 读取(单一真相，原地更新) ───────────────────────────────
def load() -> Market:
    """读出当前行情；文件缺失/坏档都从容退化成空市场，绝不抛异常打断心跳。"""
    if not _MARKET_FILE.exists():
        return Market()
    try:
        data = json.loads(_MARKET_FILE.read_text("utf-8", errors="ignore"))
    except Exception:
        return Market()
    signals: list[Signal] = []
    for d in (data.get("signals") or []):
        try:
            voices = [Voice(source=str(vd.get("source", "")), text=str(vd.get("text", "")),
                            ref=str(vd.get("ref", "")), at=str(vd.get("at", "")))
                      for vd in (d.get("voices") or [])]
            if voices:
                signals.append(Signal(theme=str(d.get("theme", "")), voices=voices))
        except Exception:
            continue        # 坏掉的那条跳过，别让一条脏数据废掉整张行情
    return Market(signals=signals, updated_at=str(data.get("updated_at", "")))


def save(market: Market) -> Market:
    """把行情原地写回 state/market/market.json；写入异常一律吞掉，绝不反噬。"""
    try:
        _MARKET_DIR.mkdir(parents=True, exist_ok=True)
        _MARKET_FILE.write_text(
            json.dumps(market.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass        # 市场是耳朵，落档失败也绝不弄死这只生命
    return market


def _log_raw(voices: list[Voice]) -> None:
    """把这趟收来的原始声音追加进可回溯的流水，并裁掉过老的条目防止膨胀。"""
    try:
        _MARKET_DIR.mkdir(parents=True, exist_ok=True)
        stamp = _now()
        lines = [json.dumps({"harvested_at": stamp} | v.to_dict(), ensure_ascii=False)
                 for v in voices]
        old = _RAW_FILE.read_text("utf-8", errors="ignore").splitlines() \
            if _RAW_FILE.exists() else []
        kept = (old + lines)[-_MAX_RAW_KEEP:]
        _RAW_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except Exception:
        pass


# ── 软推头部需求进 missionboard(缺席从容退化) ──────────────────────
def seed_missionboard(market: Market, limit: int = 3) -> list[str]:
    """把出价最高的几条需求软推进 missionboard 机会池；missionboard 缺席/撞车都从容跳过。

    这是市场唯一一处「越过耳朵身份去推一把」的动作：只往机会池投，不排�SE位、
    不替 judge 判完工——把「世界要什么」喂给既有的投资组合流控，由它去权衡。
    """
    pushed: list[str] = []
    try:
        import missionboard
        board = missionboard.load()
    except Exception:
        return pushed
    for s in market.ranked()[:max(1, limit)]:
        # 出价越高→价值越高(夹到 0~5)；跨井复现的当更值钱
        value = min(5, 2 + round(s.price) + (1 if len(s.sources) > 1 else 0))
        try:
            before = len(board.missions)
            m = board.add(s.theme, value=value, novelty=3,
                          source="market", why=f"外部需求信号(出价{s.price}，来源：{'/'.join(s.sources)})")
            if len(board.missions) > before:        # 真新增了(没被撞车去重)才记一笔
                pushed.append(m.id)
        except Exception:
            continue
    try:
        missionboard.save(board)
    except Exception:
        pass
    return pushed


# ── 给 crab / CLI 的便捷入口 ────────────────────────────────────────
def tick(fetch: bool = True) -> Market:
    """收一遍外部声音 → 聚成信号 → 落档，供心跳「听一听世界要什么」时调用。

    fetch=False 时不调外部井，仅就已存行情重排重打(给离线 / 省 token 的场景)。
    """
    if not fetch:
        return load()
    voices = harvest_voices()
    _log_raw(voices)
    market = Market(signals=cluster(voices), updated_at=_now())
    return save(market)


# ── CLI ─────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="market.py",
        description="📡 需求信号市场：从 issue/PR/README/提交讨论聚出外界真实需求，按行情给信号定价，校准该为世界变强在哪",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harvest", action="store_true", help="重收外部声音、刷新行情后打印")
    ap.add_argument("--no-fetch", action="store_true", help="不调外部井，仅就已存行情重新打印")
    ap.add_argument("--top", type=int, default=None, metavar="N", help="只看出价最高的 N 条信号")
    ap.add_argument("--seed", action="store_true", help="把头部需求软推进 missionboard 机会池")
    args = ap.parse_args(argv)

    # --no-fetch 只读已存行情；否则(默认 / --harvest)都重收一遍
    market = tick(fetch=not args.no_fetch)

    if args.seed:
        pushed = seed_missionboard(market)
        if pushed:
            print("📡  已把 " + str(len(pushed)) + " 条头部需求软推进 missionboard 机会池："
                  + "、".join(pushed))
        else:
            print("📡  没往 missionboard 推新需求（缺席、行情空、或都已在册）。")
        print("")

    print(market.render(top=args.top))


if __name__ == "__main__":
    main()
