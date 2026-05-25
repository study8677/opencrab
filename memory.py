#!/usr/bin/env python3
"""情境记忆 🧠 —— 把每次「自检 / 演化 / 失败」沉淀成短期记忆，下次决策前检索相似往事。

为什么要有它：这只螃蟹已经会看(lookout)、会验(checkup)、会改(hands)、会归类失败
(errors)，但它**不会系统地记住教训**——同一个坑可能一摔再摔，同一条死路可能反复试。
审计(audit)记下了「发生过什么」，可那是流水账，决策时没人去翻；技能卡(skills)是蜕壳时
才蒸馏的长期结晶，太慢、太粗。中间缺一层**短期情境记忆**：把每次心跳的
「情境(situation) → 行动(action) → 结果(result)」存成一条可检索的案例，
下次形成意图前，先按当下情境捞出最像的几条往事，尤其是**栽过的跟头**，
拼成一段「别再这么干」的行动提示喂回大脑。于是它从「每次从零开始」变成「带着记忆决策」。

设计：
- 一条记忆是一个 Episode：情境 / 行动 / 结果 / 成败 / 错误码 / 标签 + 时间戳。
- 检索靠零依赖的词袋相似度(中英混合：英文/代码词 + 中文字 bigram)，不需要向量库或网络。
- 落在被 .gitignore 的 state/memory/episodes.jsonl；超量自动蜕掉最老的(短期记忆，不无限膨胀)。
- 绝不反噬：记忆是观测者，读写出错都被吞掉，绝不成为新的故障源。

零第三方依赖，纯标准库。

用法:
    python memory.py                # 看最近沉淀的几条情境记忆
    python memory.py <情境文本>     # 按这段情境检索相似往事，并打印行动提示
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import re

import jsonlstore

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_MEM_DIR = _REPO_ROOT / "state" / "memory"      # 落在被 .gitignore 的 state/ 里
_EPISODES = _MEM_DIR / "episodes.jsonl"

MAX_EPISODES = 300        # 短期记忆容量上限：超了就蜕掉最老的
_TRIM_SLACK = 60          # 攒到 上限+余量 才真正重写文件，省得每条都全量改写
MIN_SIMILARITY = 0.06     # 低于此相似度视作「不相干」，不召回(免得硬凑噪声)


# ── 一条情境记忆 ────────────────────────────────────────────────────
@dataclasses.dataclass
class Episode:
    """一次经历的「情境-行动-结果」三联，外加成败与可选的错误码/标签。"""
    at: str                      # ISO 时间戳
    situation: str               # 当时的处境(意图 / 领地现状 / 触发场景)
    action: str                  # 我做了什么
    result: str                  # 结果(变更摘要 / 失败现场 / 自测输出)
    ok: bool = True              # 这次到底成没成
    code: str = ""               # 可选：errors.classify 给出的错误码(失败时)
    tags: tuple[str, ...] = ()   # 自由标签(给过滤/检索用)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self) | {"tags": list(self.tags)}

    @classmethod
    def from_dict(cls, d: dict) -> "Episode":
        return cls(
            at=str(d.get("at", "")),
            situation=str(d.get("situation", "")),
            action=str(d.get("action", "")),
            result=str(d.get("result", "")),
            ok=bool(d.get("ok", True)),
            code=str(d.get("code", "")),
            tags=tuple(d.get("tags", ()) or ()),
        )

    def headline(self) -> str:
        """一行人话摘要：成败标记 + 情境首句。"""
        mark = "✅" if self.ok else "❌"
        head = self.situation.split("\n")[0].strip()[:60] or "(无情境)"
        tail = f" [{self.code}]" if self.code else ""
        return f"{mark} {head}{tail}"


# ── 相似度：零依赖的中英混合词袋 ────────────────────────────────────
_WORD_RE = re.compile(r"[a-z0-9_]+")
_HAN_RE = re.compile(r"[一-鿿]")


def _tokens(text: str) -> set[str]:
    """把一段中英混合文本切成 token 集合：英文/代码词 + 中文字及其 bigram。

    没有分词器，也不上向量：中文用「单字 + 相邻二字组」近似词，英文按词，
    足够把「合并冲突」「自测没过」这类高复现情境聚到一起。
    """
    low = text.lower()
    toks: set[str] = set(_WORD_RE.findall(low))
    han = _HAN_RE.findall(low)
    toks |= set(han)
    toks |= {a + b for a, b in zip(han, han[1:])}
    return toks


def similarity(a: str, b: str) -> float:
    """两段文本的 Jaccard 相似度(0~1)；空集返回 0。"""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / len(ta | tb) if inter else 0.0


# ── 落地 / 读取 ─────────────────────────────────────────────────────
def _read_raw() -> list[dict]:
    """读出全部原始记忆字典(时间正序)；坏行跳过，文件缺失返回空。"""
    return jsonlstore.read_jsonl(_EPISODES)


def load(limit: int | None = None) -> list[Episode]:
    """读出情境记忆(时间正序)；limit 则只取最近 limit 条。"""
    raw = _read_raw()
    if limit:
        raw = raw[-limit:]
    return [Episode.from_dict(d) for d in raw]


def _trim_if_needed() -> None:
    """超过容量上限+余量时，重写文件只留最近 MAX_EPISODES 条(蜕掉最老的)。"""
    raw = _read_raw()
    if len(raw) <= MAX_EPISODES + _TRIM_SLACK:
        return
    kept = raw[-MAX_EPISODES:]
    try:
        _EPISODES.write_text(
            "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in kept), "utf-8")
    except Exception:
        pass   # 记忆是观测者，整理不成也绝不弄死生命


def remember(situation: str, action: str, result: str, *,
             ok: bool = True, code: str = "", tags: tuple[str, ...] = ()) -> Episode:
    """沉淀一条「情境-行动-结果」记忆并落盘；任何写入异常都被吞掉，绝不反噬。"""
    ep = Episode(at=datetime.datetime.now().isoformat(timespec="seconds"),
                 situation=situation.strip(), action=action.strip(),
                 result=result.strip(), ok=ok, code=code, tags=tuple(tags))
    if jsonlstore.append_jsonl(_EPISODES, ep.to_dict()):
        _trim_if_needed()   # 落盘成功才考虑蜕掉最老的；写盘出错被吞，记忆绝不反噬
    return ep


# ── 检索 / 提示 ─────────────────────────────────────────────────────
def recall(situation: str, k: int = 3,
           min_similarity: float = MIN_SIMILARITY) -> list[tuple[float, Episode]]:
    """按当下情境检索最像的 k 条往事，返回 (相似度, Episode) 降序列表。

    相似度相同时，让**失败**的往事优先(教训比顺风更值得拎出来),
    再按时间更近优先。
    """
    scored: list[tuple[float, Episode]] = []
    for ep in load():
        s = similarity(situation, ep.situation)
        if s >= min_similarity:
            scored.append((s, ep))
    scored.sort(key=lambda it: (it[0], not it[1].ok, it[1].at), reverse=True)
    return scored[:k]


def advise(situation: str, k: int = 3) -> str:
    """据相似往事拼一段「少犯重复错」的行动提示，喂回决策前的大脑。

    没有相干往事时返回空串(让调用方自然略过这一段)。失败的往事会被
    显式标成「⚠️ 上次栽过」，并带上错误码与当时结果，提醒别重蹈覆辙。
    """
    hits = recall(situation, k=k)
    if not hits:
        return ""
    lines = ["🧠 相似往事（带着记忆决策，别重蹈覆辙）："]
    for s, ep in hits:
        warn = "⚠️ 上次栽过 — " if not ep.ok else ""
        act = ep.action.split("\n")[0].strip()[:50]
        res = ep.result.split("\n")[0].strip()[:60]
        code = f"（{ep.code}）" if ep.code else ""
        lines.append(f"  - {warn}{ep.headline()}（相似 {s:.0%}）{code}")
        if act:
            lines.append(f"      当时做了：{act}")
        if res:
            lines.append(f"      结果：{res}")
    fails = [ep for _, ep in hits if not ep.ok]
    if fails:
        lines.append("  → 复盘上面栽过的跟头，这次换条路或先补上当时缺的前提，别再撞同一堵墙。")
    return "\n".join(lines)


def stats() -> dict:
    """记忆概览：总条数 / 成败计数 / 出现过的错误码。"""
    eps = load()
    fails = [e for e in eps if not e.ok]
    codes: dict[str, int] = {}
    for e in fails:
        if e.code:
            codes[e.code] = codes.get(e.code, 0) + 1
    return {"total": len(eps), "ok": len(eps) - len(fails),
            "fail": len(fails), "codes": codes}


# ── CLI ─────────────────────────────────────────────────────────────
def _print_recent(n: int = 10) -> None:
    eps = load(limit=n)
    st = stats()
    print(f"🧠 情境记忆 · 共 {st['total']} 条（✅{st['ok']} / ❌{st['fail']}）")
    if st["codes"]:
        print("   栽过的错误码：" + "，".join(f"{c}×{n}" for c, n in
                                          sorted(st["codes"].items())))
    if not eps:
        print("   （还没有记忆——心跳一次、或在代码里 remember(...) 后再来看。）")
        return
    print(f"\n最近 {len(eps)} 条：")
    for ep in reversed(eps):
        print(f"  {ep.at[-8:]} {ep.headline()}")


def main(argv: list[str] | None = None) -> None:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        _print_recent()
        return
    situation = " ".join(argv)
    hits = recall(situation)
    print(f"🧠 按情境检索：「{situation[:50]}」\n")
    if not hits:
        print("   没捞到相干往事（记忆还太少，或这是个全新情境）。")
        return
    print(advise(situation))


if __name__ == "__main__":
    main()
