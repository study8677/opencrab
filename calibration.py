#!/usr/bin/env python3
"""校准账本 📐 —— 把每个计划拍板那刻的**置信度**、**预期收益**，和事后**真实结果**
钉在同一条记录上,逼出一张**偏差清单**:我哪一次把握喊高了、收益吹大了,差在哪、差多少。

为什么要有它:领地里已有不确定账本(uncertainty)在事后校准我的**置信度**——声称
90% 的判断,真有 9 成应验吗。可置信度只是判断的一半。拍板时我赌的从来是两件事:**这事
我有几成把握**,和**它做成了能值多少**。前者错了叫「自信过头」,后者错了叫「画大饼」——
两种偏差合起来,才是「我这次值不值得做」的真实误差。只盯命中率不看收益,会把一堆「赌对了
却根本不值」的判断当成功;只看收益不看把握,又会拿运气当本事。

本层把每个计划拍板当场答清三件事,事后再补一件:

  · 赌的是什么(plan)        —— 这次要做的那件事 / 那个判断。
  · 有几成把握(confidence)  —— 0–100,赌它**做得成**的概率。
  · 预期收益(gain)          —— 一个数,赌它**做成了值多少**(随便定标度,前后一致即可)。
  · —— 事后 ——
  · 真实结果(settle)        —— 它到底做成了没(done/failed),以及**真实收益**(actual)。

每条裁定后算两道偏差:
  · 把握偏差 = 真实命中(成=1/败=0) − 声称把握 ÷ 100   (>0 谦虚了,<0 自信过头)
  · 收益偏差 = 真实收益 − 预期收益                       (>0 低估了,<0 画了大饼)

`calibration.py`(裸跑)按**收益偏差的绝对值**从大到小排出偏差清单——最该被复盘的,
永远是当初赌得最离谱的那几条。`--bias` 把所有已裁定计划汇总成两个系统性倾向:我整体上
是**高估收益**还是**低估**、是**自信过头**还是**过分谦虚**——这是判断尺度本身的零点偏移,
比单条偏差更值得修。

用法:
    python calibration.py plan "把构建缓存改成增量" --conf 70 --gain 8
                                       # 记一个计划(把握 70% / 预期收益 8)
    python calibration.py settle ab12cd --done --actual 3 \\
        --note "确实做成了,但只省了一点点——当初把收益吹大了"
                                       # 裁定:做成了,真实收益 3(预期 8,画了大饼)
    python calibration.py settle ef34gh --failed --actual 0 --note "依赖没就绪,黄了"
                                       # 裁定:没做成
    python calibration.py             # 偏差清单:按收益偏差绝对值从大到小
    python calibration.py --pending   # 只列还没裁定的计划(该去 settle 的)
    python calibration.py --bias      # 系统性倾向:整体高估/低估收益、自信/谦虚
    python calibration.py --quiet     # 只在「有计划悬着没裁定」时说话(钩子 / CI)
    python calibration.py --json      # 机读:导出全部计划 + 偏差 + 系统性倾向

零第三方依赖,纯标准库。账本是观测者:写盘失败被吞、读不到就当空,绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonlstore import append_jsonl, read_jsonl  # noqa: E402  —— 复用领地统一的 JSONL 存取

LOG_PATH = REPO_ROOT / "state" / "calibration.jsonl"

# 收益偏差超过这个绝对值,就在清单里标成「离谱」——当初赌得最不准的那几条。
WAY_OFF = 5.0


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _short_id(plan: str, ts: str) -> str:
    """由 计划+时刻 派生一个稳定的 6 位短 id——便于 settle 时回指这条计划。"""
    return hashlib.sha1(f"{plan}|{ts}".encode("utf-8")).hexdigest()[:6]


def _clamp_conf(raw: object) -> int:
    """把置信度规整到 0–100 的整数;非法值当 0(宁可记成「毫无把握」也不凭空抬高)。"""
    try:
        return max(0, min(100, int(round(float(raw)))))
    except (TypeError, ValueError):
        return 0


def _to_float(raw: object) -> float | None:
    """把收益规整成一个数;非法/缺失 → None(当作「没给」,而非 0,免得污染偏差)。"""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# ── 数据模型 ──────────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class Outcome:
    """一条事后裁定:这计划做成了没,以及真实收益、一句复盘。"""
    done: bool          # True=做成了, False=黄了
    actual: float       # 真实收益(同 plan 的标度)
    note: str           # 一句复盘
    ts: str             # 裁定时刻

    def to_meta(self) -> dict:
        return {"done": self.done, "actual": self.actual, "note": self.note, "ts": self.ts}


@dataclasses.dataclass(frozen=True)
class Plan:
    """一个带把握与预期收益的计划:赌的是什么、几成把握、值多少、事后结果如何。"""
    id: str
    plan: str                # 这次要赌的那件事
    confidence: int          # 0–100,赌它做得成的概率
    gain: float              # 预期收益(随便定标度)
    ts: str                  # 拍板时刻
    outcome: Outcome | None  # 事后裁定;None=还悬着

    @property
    def settled(self) -> bool:
        return self.outcome is not None

    @property
    def conf_dev(self) -> float | None:
        """把握偏差 = 真实命中(成1/败0) − 声称把握÷100。>0 谦虚, <0 自信过头。"""
        if not self.outcome:
            return None
        return (1.0 if self.outcome.done else 0.0) - self.confidence / 100.0

    @property
    def gain_dev(self) -> float | None:
        """收益偏差 = 真实收益 − 预期收益。>0 低估了, <0 画了大饼。"""
        if not self.outcome:
            return None
        return self.outcome.actual - self.gain

    def to_meta(self) -> dict:
        return {
            "id": self.id, "plan": self.plan, "confidence": self.confidence,
            "gain": self.gain, "ts": self.ts, "settled": self.settled,
            "outcome": self.outcome.to_meta() if self.outcome else None,
            "conf_dev": round(self.conf_dev, 3) if self.conf_dev is not None else None,
            "gain_dev": round(self.gain_dev, 3) if self.gain_dev is not None else None,
        }


# ── 存取:计划与裁定各写一行 JSONL,读时按 id 合并 ─────────────────────────
def load() -> list[Plan]:
    """读出全部计划(拍板时间正序),并把后续 settle 行合并到对应计划上。

    文件缺失/坏行都安全跳过;裁定行若指向不存在的 id,直接忽略(宁可丢一条裁定,
    也不凭空造一个计划)。同一 id 多条裁定取最后一条——复盘可以改主意。
    """
    plans: dict[str, Plan] = {}
    outcomes: dict[str, Outcome] = {}
    order: list[str] = []
    for rec in read_jsonl(LOG_PATH):
        kind = rec.get("kind")
        if kind == "plan":
            pid = str(rec.get("id", "")).strip()
            text = str(rec.get("plan", "")).strip()
            if not pid or not text:
                continue
            plans[pid] = Plan(
                id=pid, plan=text,
                confidence=_clamp_conf(rec.get("confidence")),
                gain=_to_float(rec.get("gain")) or 0.0,
                ts=str(rec.get("ts", "")), outcome=None,
            )
            if pid not in order:
                order.append(pid)
        elif kind == "settle":
            pid = str(rec.get("id", "")).strip()
            actual = _to_float(rec.get("actual"))
            if pid and actual is not None:
                outcomes[pid] = Outcome(
                    done=bool(rec.get("done")), actual=actual,
                    note=str(rec.get("note", "")).strip(),
                    ts=str(rec.get("ts", "")))
    out = []
    for pid in order:
        p = plans[pid]
        o = outcomes.get(pid)
        out.append(dataclasses.replace(p, outcome=o) if o else p)
    return out


def record_plan(plan: str, confidence: int, gain: float) -> tuple[str, bool]:
    """记一个带把握与预期收益的计划;返回 (短id, 是否落盘成功)。空计划直接拒绝。"""
    plan = plan.strip()
    if not plan:
        raise ValueError("计划得有内容——空话没法打把握/收益,也没法事后回头校准。")
    ts = _now_iso()
    pid = _short_id(plan, ts)
    rec = {
        "kind": "plan", "id": pid, "plan": plan,
        "confidence": _clamp_conf(confidence), "gain": float(gain), "ts": ts,
    }
    return pid, append_jsonl(LOG_PATH, rec)


def record_settle(pid: str, done: bool, actual: float, note: str) -> bool:
    """给一条计划补一个事后裁定。黄了(done=False)却报正收益,逼一句复盘。写盘失败被吞。"""
    note = note.strip()
    if not done and actual > 0 and not note:
        raise ValueError("说黄了又报正收益?这得附一句复盘(--note)解释清楚,否则账本自相矛盾。")
    rec = {"kind": "settle", "id": pid.strip(), "done": bool(done),
           "actual": float(actual), "note": note, "ts": _now_iso()}
    return append_jsonl(LOG_PATH, rec)


# ── 系统性倾向:我整体上高估/低估收益、自信/谦虚 ───────────────────────────
@dataclasses.dataclass(frozen=True)
class Bias:
    """已裁定计划的系统性偏移:收益与把握各自的平均偏差(零点漂没漂)。"""
    settled: int
    gain_bias: float | None   # 平均收益偏差;>0 系统性低估, <0 系统性高估(画大饼)
    conf_bias: float | None   # 平均把握偏差;>0 系统性谦虚, <0 系统性自信过头

    def to_meta(self) -> dict:
        return {
            "settled": self.settled,
            "gain_bias": round(self.gain_bias, 3) if self.gain_bias is not None else None,
            "conf_bias": round(self.conf_bias, 3) if self.conf_bias is not None else None,
        }


def bias(plans: list[Plan]) -> Bias:
    """汇总所有已裁定计划的平均收益偏差与平均把握偏差。"""
    settled = [p for p in plans if p.settled]
    if not settled:
        return Bias(settled=0, gain_bias=None, conf_bias=None)
    g = sum(p.gain_dev for p in settled) / len(settled)
    c = sum(p.conf_dev for p in settled) / len(settled)
    return Bias(settled=len(settled), gain_bias=g, conf_bias=c)


def deviations(plans: list[Plan]) -> list[Plan]:
    """已裁定计划,按收益偏差绝对值从大到小——最该复盘的赌得最离谱的几条排最前。"""
    return sorted((p for p in plans if p.settled),
                  key=lambda p: abs(p.gain_dev), reverse=True)


def pending(plans: list[Plan]) -> list[Plan]:
    """还没裁定的计划——结果其实早出来了,只是还没回头校准的那几条。"""
    return [p for p in plans if not p.settled]


# ── 展示 ──────────────────────────────────────────────────────────────
def _signed(x: float, unit: str = "") -> str:
    """带符号显示一个偏差,免得「+0」「-0」混淆。"""
    return f"{x:+.1f}{unit}"


def _gain_verdict(dev: float) -> str:
    if dev <= -WAY_OFF:
        return "📉 收益吹大了(画了大饼)"
    if dev >= WAY_OFF:
        return "📈 收益严重低估"
    if dev < 0:
        return "略高估"
    if dev > 0:
        return "略低估"
    return "正中"


def _conf_verdict(p: Plan) -> str:
    dev = p.conf_dev
    hit = "成了" if p.outcome.done else "黄了"
    if not p.outcome.done and p.confidence >= 70:
        return f"{hit}·自信过头(当初喊 {p.confidence}%)"
    if p.outcome.done and p.confidence <= 40:
        return f"{hit}·过分谦虚(当初只给 {p.confidence}%)"
    return f"{hit}·把握偏差 {_signed(dev)}"


def _print_plan(p: Plan) -> None:
    print(f"  ◆ [{p.id}] {p.plan}")
    if not p.outcome:
        print(f"      把握 {p.confidence:>3}%   预期收益 {p.gain:g}   ⏳ 待裁定")
        return
    print(f"      预期收益 {p.gain:g} → 真实 {p.outcome.actual:g}   "
          f"偏差 {_signed(p.gain_dev)}   {_gain_verdict(p.gain_dev)}")
    print(f"      把握 {p.confidence:>3}% → {_conf_verdict(p)}")
    if p.outcome.note:
        print(f"      复盘:{p.outcome.note}")


def _print_list(plans: list[Plan]) -> None:
    if not plans:
        print("📐 校准账本还空着——用 `python calibration.py plan \"...\" --conf N --gain X` 记下第一个计划。")
        print("   每条答清:赌什么、几成把握、预期值多少;事后再 `settle` 补真实结果。")
        return
    devs = deviations(plans)
    pend = pending(plans)
    print(f"📐 opencrab 校准账本({len(plans)} 个计划 / 已裁定 {len(devs)} / "
          f"待裁定 {len(pend)})\n")
    if devs:
        print("  按收益偏差从大到小——最该复盘的排最前:\n")
        for p in devs:
            _print_plan(p)
    for p in pend:
        _print_plan(p)
    if pend:
        ids = "、".join(p.id for p in pend)
        print(f"\n⏳ 有 {len(pend)} 个计划还没裁定({ids})——结果出来就 `settle`,账本才校得准。")
    if devs:
        print("   跑 `--bias` 看:我整体是高估收益/自信过头,还是反过来。")


def _print_pending(plans: list[Plan]) -> None:
    pend = pending(plans)
    if not pend:
        print("📐 没有悬着的计划——都裁定过了。新计划用 `plan` 记下,结果出来再 `settle`。")
        return
    print(f"⏳ {len(pend)} 个计划还没裁定真实结果——结果其实早出来了,回头校准它:\n")
    for p in pend:
        print(f"  ◆ [{p.id}] {p.plan}（把握 {p.confidence}% / 预期收益 {p.gain:g}）")
    print(f"\n  裁定:`calibration.py settle <id> --done|--failed --actual <真实收益> [--note ...]`。")


def _print_bias(plans: list[Plan]) -> None:
    b = bias(plans)
    print("📐 系统性倾向——我的判断尺度,零点漂了没\n")
    if not b.settled:
        print("  还没有已裁定的计划——多记几个、结果出来后 `settle`,才量得出零点偏移。")
        return
    gv = ("系统性高估收益(总在画大饼)" if b.gain_bias < -0.5
          else "系统性低估收益(其实可以更敢做)" if b.gain_bias > 0.5
          else "收益估得挺准")
    cv = ("系统性自信过头(把握总喊高)" if b.conf_bias < -0.1
          else "系统性过分谦虚(把握总报低)" if b.conf_bias > 0.1
          else "把握估得挺准")
    print(f"  收益偏差(平均):{_signed(b.gain_bias)}  → {gv}")
    print(f"  把握偏差(平均):{_signed(b.conf_bias)}  → {cv}")
    print(f"\n  （基于 {b.settled} 个已裁定计划）零点偏移比单条偏差更该修——"
          f"下次拍板时,先照这个倾向反向纠一纠。")


def manifest() -> dict:
    """导出纯数据:全部计划 + 各自偏差 + 系统性倾向(给外部工具消费)。"""
    plans = load()
    return {
        "count": len(plans),
        "plans": [p.to_meta() for p in plans],
        "pending": [p.id for p in pending(plans)],
        "bias": bias(plans).to_meta(),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 校准账本 📐")
    sub = ap.add_subparsers(dest="cmd")

    p_plan = sub.add_parser("plan", help="记一个计划(内容/把握/预期收益)")
    p_plan.add_argument("plan", help="这次要赌的那件事 / 那个判断")
    p_plan.add_argument("--conf", "--confidence", dest="confidence", type=int,
                        required=True, metavar="0-100", help="赌它做得成的概率(0–100)")
    p_plan.add_argument("--gain", type=float, required=True, metavar="X",
                        help="预期收益(随便定标度,前后一致即可)")

    p_set = sub.add_parser("settle", help="给一条计划补一个事后裁定")
    p_set.add_argument("id", help="计划的短 id(见清单 [xxxxxx])")
    g = p_set.add_mutually_exclusive_group(required=True)
    g.add_argument("--done", dest="done", action="store_true", help="做成了")
    g.add_argument("--failed", dest="done", action="store_false", help="黄了")
    p_set.add_argument("--actual", type=float, required=True, metavar="X",
                       help="真实收益(同 plan 的标度)")
    p_set.add_argument("--note", default="", help="一句复盘")

    ap.add_argument("--pending", action="store_true", help="只列还没裁定的计划")
    ap.add_argument("--bias", action="store_true",
                    help="系统性倾向:整体高估/低估收益、自信/谦虚")
    ap.add_argument("--quiet", action="store_true",
                    help="只在「有计划悬着没裁定」时说话(钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出机读:计划 + 偏差 + 倾向")
    args = ap.parse_args(argv)

    if args.cmd == "plan":
        try:
            pid, ok = record_plan(args.plan, args.confidence, args.gain)
        except ValueError as e:
            print(f"⚠️  {e}")
            sys.exit(2)
        if ok:
            print(f"📐 记下计划 [{pid}]（把握 {_clamp_conf(args.confidence)}% / 预期收益 {args.gain:g}）——"
                  f"结果出来记得 `settle {pid}`。")
        else:
            print(f"⚠️  这个计划没落盘(写盘失败已吞),但生命照常——[{pid}]。")
        return

    if args.cmd == "settle":
        existing = {p.id for p in load()}
        if args.id not in existing:
            print(f"⚠️  没有 id 为 {args.id!r} 的计划;跑 `calibration.py` 看清单里的 [xxxxxx]。")
            sys.exit(2)
        try:
            ok = record_settle(args.id, args.done, args.actual, args.note)
        except ValueError as e:
            print(f"⚠️  {e}")
            sys.exit(2)
        icon = "✅" if args.done else "❌"
        if ok:
            print(f"📐 [{args.id}] 已裁定 {icon}（真实收益 {args.actual:g}）。跑 `calibration.py` 看偏差。")
        else:
            print(f"⚠️  这条裁定没落盘(写盘失败已吞),但生命照常——[{args.id}] {icon}。")
        return

    plans = load()

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        sys.exit(0)

    if args.pending:
        _print_pending(plans)
        sys.exit(1 if pending(plans) else 0)

    if args.bias:
        _print_bias(plans)
        sys.exit(0)

    pend = pending(plans)
    if args.quiet:
        if pend:
            ids = "、".join(p.id for p in pend)
            print(f"📐 有 {len(pend)} 个计划还没裁定真实结果（{ids}）——跑 `calibration.py --pending`。")
            sys.exit(1)
        sys.exit(0)

    _print_list(plans)


if __name__ == "__main__":
    main()
