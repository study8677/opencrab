#!/usr/bin/env python3
"""信任分 🎚️ —— 给每条能力证据按新鲜度 × 可复现性 × 覆盖面打一个 0~1 的信任分，
低分的自动排进「复验队列」，让生命先去补最不可信的那几块。

为什么要有它：`evidence.py` 已经把「我会什么」钉成一本可证、有时效的账本，但它的
判定是**离散**的——🟢新鲜 / 🟡过期 / 🔴失守 / ⚪未证，四挡而已。可现实里「可信」
不是开关：
  · 一条**昨天刚验过**的证据，和一条**还差一天到期**的，都算「🟢新鲜」，可信度其实差很远；
  · 一条**只验过一次就通过**的声明，和一条**连验十次次次通过**的，同样是「🟢」，
    但后者「能复现」，前者只是「碰巧那次成了」——能力越多，越要分清这俩；
  · 一条偶尔翻车的 flaky 证据，最近一次恰好跑通就显示🟢，但它根本不稳。

本层不替代账本，而是站在账本之上，把同一批记录折叠成一个**连续的信任分**，由三条
彼此正交、都能**从账本流水里直接算出**的维度合成：

  · 新鲜度(freshness)  —— 距上次验证多久 ÷ 时效。刚验过≈1，临近到期→0，过期/失守/未证=0。
                          回答「这份证据还热乎吗」。
  · 可复现性(reproducibility) —— 滑窗内验证的**通过率与稳定度**：单次通过给不满分(还没
                          复现过)，连续多次通过才逼近 1；近一次失败 / 来回翻车(flaky)重罚。
                          回答「再跑一遍还会成吗」。
  · 覆盖面(coverage)   —— 滑窗内**独立验证样本的数量与时间跨度**:只验过一两次是窄证，
                          跨多天、多次验过才算把这块能力探得够广。回答「探得够全吗」。

合成用**加权几何均值**(而非算术均值)：任何一维趋近 0，总分就被拽下来——这是故意的。
「再热乎的证据，若从没复现过，也不该被当成铁了的能力」，一票否决比四舍五入更诚实。

信任分再分三档：🟢可信(≥0.70) / 🟡存疑(≥0.40) / 🔴不可信(<0.40)。任何 🔴/🟡 都让
退出码非零，可挂钩子 / CI 当门禁。低于复验线的，按「风险 × 不可信度」排进**复验队列**
(state/ 下的快照，每次扫描重写)——`--reverify` 会照队列真的去复跑 evidence 的验证命令，
把最不可信的能力先重新证一遍。

用法：
    python trustscore.py                # 给每条能力打信任分，并刷新复验队列
    python trustscore.py --quiet        # 只在有存疑/不可信时说话(适合钩子 / CI)
    python trustscore.py --queue        # 只看当前复验队列(谁最该被重证)
    python trustscore.py --reverify [N] # 照队列复跑最不可信的前 N 条(默认 3)，再重新打分
    python trustscore.py --json         # 机读：每条声明的三维分 + 合成信任分 + 档位

零第三方依赖，纯标准库。信任分与队列落在被 .gitignore 的 state/ 里，写盘失败绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import evidence    # noqa: E402  —— 声明清单与账本的单一真相源，本层只读不改
import jsonlstore  # noqa: E402  —— 复用「读一批 / 追一条」的落地层

QUEUE_PATH = REPO_ROOT / "state" / "trustscore" / "reverify.jsonl"

# ── 评分参数：都标了「为什么是这个数」，调起来心里有底 ──────────────────
TRAIL_DAYS = 30.0      # 滑窗：只看最近这么多天的验证记录(更早的证据已与今天无关)
WINDOW_MAX = 12        # 滑窗内最多取这么多条最近记录(再多边际意义递减，也省得偏向老活跃声明)
COVERAGE_SAT = 6       # 覆盖面饱和点：验到约这么多次独立样本就算探得够全(1-e^-n/k 到 ~0.86)
TRUST_OK = 0.70        # 🟢可信下限
TRUST_DOUBT = 0.40     # 🟡存疑下限(低于此 = 🔴不可信)
REVERIFY_FLOOR = TRUST_OK   # 低于这条线就排进复验队列(存疑与不可信都该重证)

# 三维权重：可复现性最重(「能不能再跑成」是信任的核心)，新鲜度次之，覆盖面再次。
W_FRESH, W_REPRO, W_COVER = 1.0, 1.3, 0.8


@dataclasses.dataclass(frozen=True)
class Trust:
    """一条声明折叠后的信任画像：三维分 + 合成信任分 + 档位。"""
    name: str
    freshness: float       # 新鲜度 ∈ [0,1]
    reproducibility: float # 可复现性 ∈ [0,1]
    coverage: float        # 覆盖面 ∈ [0,1]
    score: float           # 合成信任分 ∈ [0,1]
    samples: int           # 滑窗内参与计算的验证样本数
    risk: float            # 这块能力的风险权重(来自 evidence 声明)
    state: str             # evidence 的离散状态(fresh/stale/broken/unproven)，便于对照

    _MARKS = {"trusted": "🟢", "doubt": "🟡", "untrusted": "🔴"}
    _WORDS = {"trusted": "可信", "doubt": "存疑", "untrusted": "不可信"}

    @property
    def band(self) -> str:
        if self.score >= TRUST_OK:
            return "trusted"
        if self.score >= TRUST_DOUBT:
            return "doubt"
        return "untrusted"

    @property
    def mark(self) -> str:
        return self._MARKS[self.band]

    @property
    def word(self) -> str:
        return self._WORDS[self.band]

    @property
    def trusted(self) -> bool:
        return self.band == "trusted"

    @property
    def urgency(self) -> float:
        """该不该先被重证：越不可信、风险越高，越靠前。"""
        return (1.0 - self.score) * self.risk

    def to_meta(self) -> dict:
        return {"name": self.name, "freshness": round(self.freshness, 4),
                "reproducibility": round(self.reproducibility, 4),
                "coverage": round(self.coverage, 4), "score": round(self.score, 4),
                "band": self.band, "samples": self.samples, "risk": self.risk,
                "state": self.state}


# ── 三维打分：每一维都只从账本流水里算，不引入账本之外的臆测 ──────────────
def _recent_rows(rows: list[dict], name: str, *, now: float) -> list[dict]:
    """取某条声明在滑窗内、按时间正序的最近若干条验证记录。"""
    picked = []
    for r in rows:
        if r.get("name") != name:
            continue
        ts = r.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        if (now - ts) / 86400.0 <= TRAIL_DAYS:
            picked.append(r)
    picked.sort(key=lambda r: r.get("ts", 0.0))
    return picked[-WINDOW_MAX:]


def freshness(status: evidence.Status) -> float:
    """新鲜度：刚验过≈1，线性衰减到时效处归 0；过期/失守/未证一律 0。"""
    if status.state != "fresh" or status.age_days is None or status.ttl_days <= 0:
        return 0.0
    return max(0.0, 1.0 - status.age_days / status.ttl_days)


def reproducibility(window: list[dict]) -> float:
    """可复现性：滑窗通过率 × 样本可信折扣 × flaky 惩罚 × 近次失败惩罚。

    · 一条样本都没有 → 0(谈不上复现)。
    · 单次通过封顶 0.5：跑成过一次，但还没「再现」，不该被当成铁证。
    · 来回翻车(ok/fail 交替)按翻转次数线性扣分——不稳本身就是不可信。
    · 最近一次失败直接腰斩：刚塌过的能力，历史再漂亮也先别信。
    """
    n = len(window)
    if n == 0:
        return 0.0
    oks = [bool(r.get("ok")) for r in window]
    pass_rate = sum(oks) / n
    # 样本折扣:单次→0.5，两次→0.75，之后趋近 1(1 - 0.5^n)，逼着「多验几次才算复现」。
    sample_factor = 1.0 - 0.5 ** n
    # flaky 惩罚:统计相邻记录的状态翻转，翻得越多扣得越狠(最多扣到 0)。
    flips = sum(1 for a, b in zip(oks, oks[1:]) if a != b)
    flaky_factor = max(0.0, 1.0 - flips / max(1, n - 1))
    score = pass_rate * sample_factor * flaky_factor
    if not oks[-1]:        # 最近一次没跑通 → 腰斩
        score *= 0.5
    return max(0.0, min(1.0, score))


def coverage(window: list[dict], *, now: float) -> float:
    """覆盖面：独立样本数的饱和量(1-e^-n/k) × 时间跨度因子。

    只验过一两次、还都挤在同一天的，是窄证；跨多天、多次验过，才算把这块能力
    在不同时刻、不同环境下探得够广。两个因子相乘:数量与跨度缺一不可。
    """
    n = len(window)
    if n == 0:
        return 0.0
    count_factor = 1.0 - math.exp(-n / COVERAGE_SAT)
    tss = [r.get("ts") for r in window if isinstance(r.get("ts"), (int, float))]
    span_days = (max(tss) - min(tss)) / 86400.0 if len(tss) >= 2 else 0.0
    # 跨度因子:跨 0 天(都在同一刻)→0.5 起步，跨满半个滑窗→1.0，封顶 1。
    span_factor = min(1.0, 0.5 + 0.5 * span_days / (TRAIL_DAYS / 2))
    return max(0.0, min(1.0, count_factor * span_factor))


def _geom_mean(values: list[float], weights: list[float]) -> float:
    """加权几何均值:任一维趋近 0 总分就被拽向 0(一票否决，故意如此)。"""
    wsum = sum(weights)
    if wsum <= 0:
        return 0.0
    acc = 0.0
    for v, w in zip(values, weights):
        if v <= 0.0:
            return 0.0
        acc += w * math.log(v)
    return math.exp(acc / wsum)


def score_claim(claim: evidence.Claim, status: evidence.Status,
                window: list[dict], *, now: float) -> Trust:
    """把一条声明的三维分合成信任分。"""
    f = freshness(status)
    r = reproducibility(window)
    c = coverage(window, now=now)
    s = _geom_mean([f, r, c], [W_FRESH, W_REPRO, W_COVER])
    return Trust(name=claim.name, freshness=f, reproducibility=r, coverage=c,
                 score=s, samples=len(window), risk=claim.risk, state=status.state)


def assess(claims: list[evidence.Claim] | None = None, *,
           rows: list[dict] | None = None, now: float | None = None) -> list[Trust]:
    """读 evidence 的声明 + 账本，给每条打信任分(全程只读，不复跑、不落盘)。"""
    now = time.time() if now is None else now
    claims = evidence.CLAIMS if claims is None else claims
    rows = jsonlstore.read_jsonl(evidence.LEDGER_PATH) if rows is None else rows
    statuses = {s.name: s for s in evidence.status(claims, rows=rows, now=now)}
    out = []
    for c in claims:
        st = statuses.get(c.name) or evidence.classify(c, None, now=now)
        window = _recent_rows(rows, c.name, now=now)
        out.append(score_claim(c, st, window, now=now))
    out.sort(key=lambda t: (t.score, t.name))   # 最不可信的排最前
    return out


# ── 复验队列:低于信任线的，按紧迫度排成快照，供复跑消费 ────────────────────
def build_queue(trusts: list[Trust]) -> list[dict]:
    """挑出低于复验线的声明,按紧迫度(不可信度×风险)降序排成队列条目。"""
    low = [t for t in trusts if t.score < REVERIFY_FLOOR]
    low.sort(key=lambda t: (-t.urgency, t.name))
    return [{"name": t.name, "score": round(t.score, 4), "band": t.band,
             "urgency": round(t.urgency, 4), "risk": t.risk,
             "reason": _why(t)} for t in low]


def _why(t: Trust) -> str:
    """一句话点出这条信任分主要被哪一维拖低,让队列读得懂「为啥要复验它」。"""
    dims = {"新鲜度": t.freshness, "可复现性": t.reproducibility, "覆盖面": t.coverage}
    weak = min(dims, key=dims.get)
    return f"{weak}最弱({dims[weak]:.2f})"


def write_queue(queue: list[dict]) -> bool:
    """把复验队列写成快照(整文件重写,不是追加日志:它只描述「此刻」谁该重证)。

    写盘尽力而为,失败被吞掉,绝不反噬生命。
    """
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE_PATH.open("w", encoding="utf-8") as f:
            for item in queue:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return True
    except Exception:   # noqa: BLE001 —— 队列是副产物,写不出也不该拖垮打分
        return False


def read_queue() -> list[dict]:
    """读出当前复验队列(缺失/坏行容忍,永不抛错)。"""
    return jsonlstore.read_jsonl(QUEUE_PATH)


def reverify(budget: int = 3, *, now: float | None = None) -> dict:
    """照队列复跑最不可信的前 budget 条:真的去跑 evidence 的验证命令,落账后重新打分。

    返回本轮纪要:复跑了哪些、各自通过否、复跑后信任分变化。全程尽力而为。
    """
    now = time.time() if now is None else now
    before = assess(now=now)
    queue = build_queue(before)
    by_name = {c.name: c for c in evidence.CLAIMS}
    before_by = {t.name: t for t in before}
    picked = [item["name"] for item in queue[:max(0, budget)]]
    results = []
    for name in picked:
        claim = by_name.get(name)
        if claim is None:
            continue
        rec = evidence.verify(claim)   # 真的复跑 + 落账
        results.append({"name": name, "ok": rec["ok"]})
    after = assess()                   # 复跑后重新打分(读到刚落的新记录)
    after_by = {t.name: t for t in after}
    deltas = [{"name": n,
               "before": round(before_by[n].score, 4) if n in before_by else None,
               "after": round(after_by[n].score, 4) if n in after_by else None}
              for n in picked]
    write_queue(build_queue(after))    # 刷新队列(刚重证过的多半已出队)
    return {"budget": budget, "reverified": picked,
            "failed": [r["name"] for r in results if not r["ok"]],
            "deltas": deltas}


# ── 展示 ──────────────────────────────────────────────────────────────
def _bar(v: float, width: int = 10) -> str:
    filled = int(round(v * width))
    return "█" * filled + "·" * (width - filled)


def _print_assessment(trusts: list[Trust], queue: list[dict]) -> None:
    print(f"🎚️  opencrab 能力信任分（{len(trusts)} 条声明）\n")
    by_name = {c.name: c for c in evidence.CLAIMS}
    for t in trusts:
        asserts = by_name[t.name].asserts if t.name in by_name else ""
        print(f"  {t.mark} {t.name}（{t.word} {t.score:.2f}）—— {asserts}")
        print(f"      新鲜度 {_bar(t.freshness)} {t.freshness:.2f}   "
              f"可复现 {_bar(t.reproducibility)} {t.reproducibility:.2f}   "
              f"覆盖面 {_bar(t.coverage)} {t.coverage:.2f}")
        print(f"      样本 {t.samples} 条 · 风险 {t.risk:g} · 账本状态 {t.state}")
    counts = {"trusted": 0, "doubt": 0, "untrusted": 0}
    for t in trusts:
        counts[t.band] += 1
    bar = "  ".join(f"{Trust._MARKS[k]}{counts[k]}"
                    for k in ("trusted", "doubt", "untrusted"))
    print(f"\n  小结：{bar}")
    if queue:
        print(f"\n  🔁 复验队列（{len(queue)} 条，按紧迫度排序）：")
        for item in queue:
            print(f"      {item['name']}（信任 {item['score']:.2f}，{item['reason']}）")
        print("    跑 `python trustscore.py --reverify` 照队列重证最不可信的几条。")
    else:
        print("\n🎚️  每条能力的证据都够可信，复验队列为空。")


def manifest() -> dict:
    """导出纯数据：每条声明的三维分 + 信任分 + 当前复验队列(给 health / 外部消费)。"""
    trusts = assess()
    return {"trust": [t.to_meta() for t in trusts],
            "queue": build_queue(trusts),
            "params": {"trail_days": TRAIL_DAYS, "window_max": WINDOW_MAX,
                       "trust_ok": TRUST_OK, "trust_doubt": TRUST_DOUBT,
                       "reverify_floor": REVERIFY_FLOOR,
                       "weights": {"freshness": W_FRESH, "reproducibility": W_REPRO,
                                   "coverage": W_COVER}}}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 能力信任分 🎚️")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有存疑/不可信时输出(适合钩子 / CI)")
    ap.add_argument("--queue", action="store_true",
                    help="只看当前复验队列(谁最该被重证)")
    ap.add_argument("--reverify", nargs="?", type=int, const=3, metavar="N",
                    help="照队列复跑最不可信的前 N 条(默认 3)，再重新打分")
    ap.add_argument("--json", action="store_true", help="导出机读信任分清单")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if args.queue:
        queue = read_queue()
        if not queue:
            print("🎚️  复验队列为空——每条能力的证据都在信任线之上。")
        else:
            print(f"🔁 复验队列（{len(queue)} 条，按紧迫度排序）：\n")
            for item in queue:
                print(f"  {item['name']}（信任 {item.get('score')}，"
                      f"{item.get('reason', '')}）")
        return

    if args.reverify is not None:
        rep = reverify(args.reverify)
        if not args.quiet:
            done = rep["reverified"]
            print(f"🔁 照队列复验 {len(done)} 条（{'、'.join(done) or '队列为空'}）")
            for d in rep["deltas"]:
                b, a = d["before"], d["after"]
                arrow = f"{b:.2f} → {a:.2f}" if b is not None and a is not None else "—"
                print(f"  {d['name']}：信任 {arrow}")
            if rep["failed"]:
                print(f"  🔴 复跑仍失守：{'、'.join(rep['failed'])}")
            print()

    trusts = assess()
    queue = build_queue(trusts)
    write_queue(queue)              # 每次扫描刷新队列快照
    all_trusted = all(t.trusted for t in trusts)
    if not (args.quiet and all_trusted):
        _print_assessment(trusts, queue)
    sys.exit(0 if all_trusted else 1)


if __name__ == "__main__":
    main()
