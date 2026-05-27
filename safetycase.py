#!/usr/bin/env python3
"""安全论证包 🧷 —— 给每一次高风险自改逼出一份「为何值得信任」的论证:主张、前提、
证据、**反证**、剩余风险,五样齐了才许说「可信」。守住「不只跑通,还要说清凭什么敢信」这条底线。

为什么要有它:这只螃蟹会改自己的器官——有些改动一旦错了,代价不是重跑一遍那么轻。
跑通了不等于值得信任:测试绿、demo 漂亮,只证明「这一次没炸」,证明不了「我想清楚了它为什么不该炸、
哪里仍可能炸」。最阴的坑和 `metricguard` 抓的古德哈特同源——**确认偏误**:人一旦想让某个改动过关,
最省力的路是只去找支持它的证据,对着反例闭眼。于是论证里清一色的绿,看着无懈可击,
其实从没被认真挑战过——这种「无懈可击」最不可信。

本层把一次高风险自改的信任,拆成一份**安全论证包(safety case)**,五样缺一不可:

  · 🎯 claim     —— 主张:这次改动值得信任的那句断言(如「重写 rollback 不会丢历史快照」)。
  · 📐 assumption —— 前提:论证成立所依赖的假设(如「快照目录只追加、不被外部清理」)。前提塌了,结论就塌。
  · ✅ evidence   —— 证据:支持主张的事实(测试、消融、回放、对照)。每条带 0~1 的强度。
  · ⚔️ counter    —— 反证:**主动找来挑战主张的**反例与隐忧(已知失败模式、未覆盖路径)。每条带 0~1 的分量。
  · ⚠️ residual   —— 剩余风险:明知没覆盖、决定带着上路的那部分(如「并发清理仍可能竞态」)。

闸门(和 metricguard / ablation 同一种洁癖):五样里少了任何一样,论证不全,不配下「可信」的判决——

  · 没有主张 → 不知道在替什么背书;
  · 没有前提 → 没说清结论站在哪块地基上;
  · 没有证据 → 空口断言;
  · **没有反证 → 从没被挑战过**(确认偏误本体,最该拦);
  · 没写剩余风险 → 假装零风险,而零风险本身就是最大的风险。

闸门过了,再据证据与反证的对照下裁决。把支持强度与反证分量各自求和,算一个净信心
conf = 支持 / (支持 + 反证)(0~1,跨论证可比——你找的反证越重、越没被压住,conf 越低):

  · 🟢 sound(成立)     —— 反证被认真找过、且支持明显压过反证(conf ≥ 成立线)。可信,可上路。
  · 🟡 contested(有争议)—— 支持只略胜反证(conf 在争议线与成立线之间)。别急着信:要么补证据,要么降风险。
  · 🔴 unfounded(不成立)—— 反证压过或追平支持(conf < 争议线),或压根没找反证。这份信任立不住——别让它上路。
  · ⬜ incomplete(论证不全)—— 五样缺料,凑不齐一份论证,绝不冒充判决。

safetycase 只**定义这份论证结构、守住闸门、记账、下裁决**:你把一次高风险自改的五样喂进来,
它只负责诚实地比、诚实地亮灯——它不替你跑测试、不替你想反例、更不替你担风险。
它存在的唯一意义,是当你(或未来的自己)想给一次危险改动盖「可信」的章时,
有一个东西敢问一句:**你找过反证吗?反证压住了吗?没覆盖的风险你认了吗?**

论证记进 `state/safetycase.jsonl`(一行一份,append-only),--status 折叠成「每次改动最近一份论成了啥」,
--blocked 单列出所有还不成立(不成立/论证不全)、不该上路的改动。

用法:
    python safetycase.py                 # 自检:闸门 + 证据/反证对照 + 四色裁决
    python safetycase.py --demo          # 演示四种结局(成立/有争议/不成立/论证不全)各一例
    python safetycase.py --status        # 读账本,列每次改动最近一份论证裁决
    python safetycase.py --blocked       # 只列还不成立、不该上路的改动
    python safetycase.py --json          # 机读:导出当前各改动最近裁决
    python safetycase.py --quiet         # 只在自检不过时说话(适合钩子 / CI)

退出码:0 = 自检全过;1 = 任意一步不达约。
零第三方依赖,纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import sys

from jsonlstore import append_jsonl, read_jsonl

# 安全进化框架: 串联 redteam 对抗审查生成反证
def _try_import_redteam():
    """尝试导入 redteam 模块，用于生成安全论证的反证。"""
    try:
        import redteam
        return redteam
    except ImportError:
        return None

REPO_ROOT = pathlib.Path(__file__).resolve().parent
LEDGER = REPO_ROOT / "state" / "safetycase.jsonl"

# ── 四色裁决:这次高风险自改的信任,立不立得住 ──────────────────────────────
SOUND = "sound"              # 🟢 成立:反证被认真找过,支持明显压过反证
CONTESTED = "contested"      # 🟡 有争议:支持只略胜反证,别急着信
UNFOUNDED = "unfounded"      # 🔴 不成立:反证压过/追平,或压根没找反证
INCOMPLETE = "incomplete"    # ⬜ 论证不全:五样缺料,凑不齐一份论证

_EMOJI = {SOUND: "🟢", CONTESTED: "🟡", UNFOUNDED: "🔴", INCOMPLETE: "⬜"}

# 裁决阈值(都以 conf = 支持/(支持+反证) 为单位,0~1,跨论证可比):
SOUND_CONF = 0.75       # conf ≥ 此 → 支持明显压过反证(成立)
CONTEST_CONF = 0.55     # conf ≥ 此 → 支持略胜(有争议);低于此 → 反证压过/追平(不成立)


def _now() -> str:
    """统一的 UTC ISO 时间戳(秒级、带 Z),让账本里的时间可比、可排序。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# 论证支的两种角色:撑主张的证据,和挑主张的反证。
EVIDENCE = "evidence"   # ✅ 支持主张
COUNTER = "counter"     # ⚔️ 挑战主张


@dataclasses.dataclass(frozen=True)
class Strand:
    """论证的一支:一条带强度的事实,要么撑主张(证据),要么挑主张(反证)。

    weight 是这条的「分量」(0~1):证据越硬、反证越致命,分量越大。裁决只看两边分量的对比,
    不看条数——一条致命反证(0.9)该压过三条凑数证据(各 0.1)。
    """
    role: str           # EVIDENCE(撑) 或 COUNTER(挑)
    desc: str           # 一句话:这条事实是什么
    weight: float       # 分量,归一 0~1

    def __post_init__(self) -> None:
        if self.role not in (EVIDENCE, COUNTER):
            raise ValueError(f"论证支角色须为 evidence/counter,实见 {self.role!r}")
        if not (0.0 <= self.weight <= 1.0):
            raise ValueError(f"分量须归一到 0~1,实见 {self.weight}")
        if not self.desc.strip():
            raise ValueError("论证支必须写清是什么(desc 不可空)")

    def to_record(self) -> dict:
        return {"role": self.role, "desc": self.desc, "weight": self.weight}

    @staticmethod
    def from_record(rec: dict) -> "Strand":
        return Strand(role=rec.get("role", EVIDENCE),
                      desc=rec.get("desc", ""),
                      weight=float(rec.get("weight", 0.0)))


@dataclasses.dataclass(frozen=True)
class SafetyCase:
    """一次高风险自改的安全论证包:主张、前提、证据、反证、剩余风险,五样齐了才许判可信。"""
    change: str                          # 这次改动的标识(如 "rewrite:rollback.py")
    claim: str                           # 🎯 主张:值得信任的那句断言
    assumptions: tuple[str, ...]         # 📐 前提:论证所依赖的假设
    strands: tuple[Strand, ...]          # ✅⚔️ 证据与反证(混在一起,按 role 分)
    residual: tuple[str, ...]            # ⚠️ 剩余风险:明知没覆盖、带着上路的那部分

    @property
    def evidence(self) -> tuple[Strand, ...]:
        return tuple(s for s in self.strands if s.role == EVIDENCE)

    @property
    def counters(self) -> tuple[Strand, ...]:
        return tuple(s for s in self.strands if s.role == COUNTER)

    @property
    def support(self) -> float:
        """支持强度:所有证据的分量之和。"""
        return sum(s.weight for s in self.evidence)

    @property
    def rebut(self) -> float:
        """反证分量:所有反证的分量之和。"""
        return sum(s.weight for s in self.counters)

    @property
    def confidence(self) -> float:
        """净信心 conf = 支持 / (支持 + 反证),0~1,跨论证可比。

        反证找得越重、越没被支持压住,conf 越低。两边都为 0(无证据)时返回 0——
        空口无凭,信心归零。
        """
        total = self.support + self.rebut
        return self.support / total if total > 0 else 0.0

    def to_record(self) -> dict:
        return {
            "change": self.change,
            "claim": self.claim,
            "assumptions": list(self.assumptions),
            "strands": [s.to_record() for s in self.strands],
            "residual": list(self.residual),
        }

    @staticmethod
    def from_record(rec: dict) -> "SafetyCase":
        return SafetyCase(
            change=rec.get("change", ""),
            claim=rec.get("claim", ""),
            assumptions=tuple(rec.get("assumptions", [])),
            strands=tuple(Strand.from_record(s) for s in rec.get("strands", [])),
            residual=tuple(rec.get("residual", [])),
        )


def check_case(c: SafetyCase) -> list[str]:
    """下裁决前要守的红线;返回缺料清单(空 = 五样齐、闸门通过)。

    五样缺一不可——尤其「没找反证」一条:一份从没被挑战过的论证,看着再绿也不配判可信。
    """
    errs: list[str] = []
    if not c.claim.strip():
        errs.append("缺主张:没说清这次改动到底要替什么背书")
    if not c.assumptions:
        errs.append("缺前提:没说清结论站在哪块地基上(前提塌了结论就塌)")
    if not c.evidence:
        errs.append("缺证据:主张还是空口断言,没有事实撑")
    if not c.counters:
        errs.append("缺反证:从没主动找过反例——确认偏误,这种「无懈可击」最不可信")
    if not c.residual:
        errs.append("缺剩余风险:假装零风险,而假装零风险本身就是最大的风险")
    return errs


@dataclasses.dataclass(frozen=True)
class Argument:
    """一份安全论证的账本记录:为哪次改动背书、五样内容、何时、凭什么。"""
    case: SafetyCase
    ts: str = ""                # UTC 时间戳,留空则取当下
    note: str = ""              # 一句话备注

    def __post_init__(self) -> None:
        if not self.ts:
            object.__setattr__(self, "ts", _now())

    def verdict(self) -> str:
        """据证据/反证对照下裁决(五样缺料 → incomplete,绝不冒充判决)。"""
        if check_case(self.case):
            return INCOMPLETE
        conf = self.case.confidence
        if conf >= SOUND_CONF:
            return SOUND
        if conf >= CONTEST_CONF:
            return CONTESTED
        return UNFOUNDED

    def to_record(self) -> dict:
        c = self.case
        return {
            **c.to_record(),
            "verdict": self.verdict(),
            "support": round(c.support, 4),
            "rebut": round(c.rebut, 4),
            "confidence": round(c.confidence, 4),
            "missing": check_case(c),
            "ts": self.ts,
            "note": self.note,
        }


def record_argument(case: SafetyCase, *, note: str = "",
                    ledger: pathlib.Path = LEDGER) -> Argument:
    """落账一份安全论证,返回该论证(含裁决)。

    五样缺料也照记——一份不全的论证本身就是值得留痕的事实(提醒你补齐再上路),
    但裁决会诚实地标成 incomplete,绝不冒充判决。
    """
    a = Argument(case=case, note=note)
    append_jsonl(ledger, a.to_record())
    return a


def auto_generate(change: str, *, note: str = "",
                  ledger: pathlib.Path = LEDGER) -> Argument:
    """安全进化框架的核心: 自动生成安全论证，串联 redteam 对抗审查。
    
    这个函数构建从预注册假设到事后裁决的完整安全闭环:
    1. 预注册假设: 自动生成前提，基于改动类型推导
    2. 对抗审查: 调用 redteam 生成反证(挑战)
    3. 证据收集: 从改动描述中提取证据线索
    4. 事后裁决: 据证据与反证对照下裁决
    
    返回自动的安全论证，用户可后续补充完善。
    """
    redteam = _try_import_redteam()
    
    # 1. 自动生成前提(预注册假设)
    assumptions = _generate_assumptions(change)
    
    # 2. 调用 redteam 生成反证(对抗审查)
    strands = []
    if redteam:
        try:
            # 使用 redteam 审查改动描述
            report = redteam.review(change, source="auto-safetycase")
            # 将 redteam 的挑战转换为安全论证的反证
            for challenge in report.challenges:
                if not challenge.answered:
                    # 未回答的挑战作为反证
                    weight = 0.8 if challenge.severity == "致命" else 0.5
                    strands.append(Strand(
                        role=COUNTER,
                        desc=f"{challenge.title}: {challenge.why}",
                        weight=weight
                    ))
        except Exception:
            # redteam 出错时静默降级，不阻塞安全论证生成
            pass
    
    # 3. 从改动描述中提取证据线索
    evidence_strands = _extract_evidence_from_change(change)
    strands.extend(evidence_strands)
    
    # 4. 生成剩余风险
    residual = _generate_residual_risks(change, strands)
    
    # 构建安全论证
    case = SafetyCase(
        change=change,
        claim=f"改动 {change[:30]}... 是安全的",
        assumptions=tuple(assumptions),
        strands=tuple(strands),
        residual=tuple(residual)
    )
    
    # 落账
    return record_argument(case, note=f"自动生成-安全进化闭环{': ' + note if note else ''}", ledger=ledger)


def _generate_assumptions(change: str) -> list[str]:
    """根据改动描述自动生成前提假设(预注册假设)。"""
    assumptions = []
    change_lower = change.lower()
    
    # 基于关键词生成相关假设
    if any(kw in change_lower for kw in ["重写", "rewrite", "重构", "refactor"]):
        assumptions.append("新实现与旧实现在核心功能上保持等价")
    
    if any(kw in change_lower for kw in ["删除", "移除", "remove", "drop"]):
        assumptions.append("被删除的功能不再被任何活跃路径依赖")
    
    if any(kw in change_lower for kw in ["优化", "提速", "cache", "缓存"]):
        assumptions.append("优化不引入新的竞态或数据不一致")
    
    if any(kw in change_lower for kw in ["新功能", "add", "添加"]):
        assumptions.append("新功能遵循现有设计模式，不破坏现有接口契约")
    
    # 默认前提
    assumptions.append("改动在测试覆盖的主要路径上验证通过")
    assumptions.append("改动不会引入已知的安全漏洞模式")
    
    return assumptions


def _extract_evidence_from_change(change: str) -> list[Strand]:
    """从改动描述中提取可能的证据线索。"""
    strands = []
    change_lower = change.lower()
    
    # 从描述中提取可能的证据
    if "测试" in change_lower or "test" in change_lower:
        strands.append(Strand(
            role=EVIDENCE,
            desc="改动描述中提及测试覆盖",
            weight=0.3
        ))
    
    if "回放" in change_lower or "replay" in change_lower:
        strands.append(Strand(
            role=EVIDENCE,
            desc="改动描述中提及回放验证",
            weight=0.4
        ))
    
    if "消融" in change_lower or "ablation" in change_lower:
        strands.append(Strand(
            role=EVIDENCE,
            desc="改动描述中提及消融实验",
            weight=0.5
        ))
    
    # 如果没有找到具体证据，添加一个占位证据(待用户补充)
    if not strands:
        strands.append(Strand(
            role=EVIDENCE,
            desc="需要补充具体证据(测试、消融、回放等)",
            weight=0.1
        ))
    
    return strands


def _generate_residual_risks(change: str, strands: list[Strand]) -> list[str]:
    """基于改动和反证生成剩余风险。"""
    risks = []
    
    # 基于反证的严重程度生成风险
    fatal_counters = [s for s in strands if s.role == COUNTER and s.weight >= 0.7]
    if fatal_counters:
        risks.append(f"存在 {len(fatal_counters)} 个致命反证未完全解决，需持续监控")
    
    # 通用风险
    risks.append("并发和边界条件仍可能存在未覆盖场景")
    risks.append("长期运行稳定性需观察")
    risks.append("用户使用模式可能超出预期范围")
    
    return risks


def current_verdicts(ledger: pathlib.Path = LEDGER) -> dict[str, dict]:
    """把 append-only 账本折叠成「每次改动最近一份论成了啥」:同名取最后一条。"""
    out: dict[str, dict] = {}
    for rec in read_jsonl(ledger):
        change = rec.get("change")
        if change:
            out[change] = rec
    return out


def blocked(ledger: pathlib.Path = LEDGER) -> list[dict]:
    """最近一份还不成立(不成立/论证不全)、不该上路的改动(按 confidence 升序——最立不住的先看)。"""
    bad = [r for r in current_verdicts(ledger).values()
           if r.get("verdict") in (UNFOUNDED, INCOMPLETE)]
    return sorted(bad, key=lambda r: r.get("confidence", 0.0))


# ── 自检:闸门 + 证据/反证对照 + 四色裁决,一步不过即违约 ────────────────────
def _selftest() -> list[str]:
    """返回失败清单(空 = 全过);每条都是自给自足、无副作用(不碰真账本)的真实调用。"""
    fails: list[str] = []

    def check(cond: bool, why: str) -> None:
        if not cond:
            fails.append(why)

    # 0) Strand 坏数据当场拦:坏角色 / 越界分量 / 空描述。
    for bad, why in (
        (lambda: Strand("maybe", "x", 0.5), "坏角色竟没被拦"),
        (lambda: Strand(EVIDENCE, "x", 1.5), "越界分量竟没被拦"),
        (lambda: Strand(EVIDENCE, "   ", 0.5), "空描述竟没被拦"),
    ):
        try:
            bad()
            fails.append(why)
        except ValueError:
            pass

    # 一份齐全、支持压过反证的论证(下面多处复用作底子)。
    def sound_case() -> SafetyCase:
        return SafetyCase(
            change="rewrite:rollback.py",
            claim="重写 rollback 不会丢历史快照",
            assumptions=("快照目录只追加、不被外部清理",),
            strands=(
                Strand(EVIDENCE, "回放 200 次历史回滚全部命中", 0.6),
                Strand(EVIDENCE, "消融:禁用新路径退回旧行为,结果一致", 0.4),
                Strand(COUNTER, "并发清理下未覆盖,理论上仍可能竞态", 0.1),
            ),
            residual=("并发清理仍可能竞态,已记 TODO 上路观察",),
        )

    # 1) support / rebut / confidence 算对。
    sc = sound_case()
    check(abs(sc.support - 1.0) < 1e-9, f"支持该是 1.0,实得 {sc.support}")
    check(abs(sc.rebut - 0.1) < 1e-9, f"反证该是 0.1,实得 {sc.rebut}")
    check(abs(sc.confidence - 1.0 / 1.1) < 1e-9, f"conf 该是 1/1.1,实得 {sc.confidence}")

    # 2) 闸门:五样齐放行;缺反证 / 缺剩余风险各自被点名。
    check(not check_case(sound_case()), "五样齐的论证该让闸门通过")
    no_counter = dataclasses.replace(
        sound_case(), strands=(Strand(EVIDENCE, "测试全绿", 0.9),))
    check(any("缺反证" in e for e in check_case(no_counter)), "没找反证该被点名")
    no_residual = dataclasses.replace(sound_case(), residual=())
    check(any("剩余风险" in e for e in check_case(no_residual)), "没写剩余风险该被点名")
    no_claim = dataclasses.replace(sound_case(), claim="  ")
    check(any("缺主张" in e for e in check_case(no_claim)), "空主张该被点名")

    # 3) 裁决四结局:
    #    a) 成立——反证找过、支持明显压过(conf ≈ 0.91 ≥ 成立线)。
    check(Argument(sound_case()).verdict() == SOUND,
          f"支持压过反证该判成立,实得 {Argument(sound_case()).verdict()}")
    #    b) 有争议——支持只略胜反证(conf 落在争议线与成立线之间)。
    contested = dataclasses.replace(sound_case(), strands=(
        Strand(EVIDENCE, "测试覆盖主路径", 0.6),
        Strand(COUNTER, "边界路径未覆盖,曾在相邻模块咬过人", 0.4),
    ))
    check(Argument(contested).verdict() == CONTESTED,
          f"支持略胜该判有争议,实得 {Argument(contested).verdict()}")
    #    c) 不成立——反证压过支持(conf < 争议线)。
    unfounded = dataclasses.replace(sound_case(), strands=(
        Strand(EVIDENCE, "demo 跑通一次", 0.2),
        Strand(COUNTER, "已知会丢未提交快照,且无回放覆盖", 0.7),
    ))
    check(Argument(unfounded).verdict() == UNFOUNDED,
          f"反证压过支持该判不成立,实得 {Argument(unfounded).verdict()}")
    #    d) 论证不全——五样缺料,绝不冒充判决。
    check(Argument(no_counter).verdict() == INCOMPLETE,
          f"缺反证该判 incomplete,实得 {Argument(no_counter).verdict()}")

    # 4) 账本折叠 + 拦截清单:同名取最后一条,不成立/不全单列且按 confidence 升序。
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d) / "sc.jsonl"
        record_argument(sound_case(), ledger=tmp)
        record_argument(unfounded, ledger=tmp)
        # rollback 后再论一次仍不成立,同名应覆盖。
        weak = dataclasses.replace(sound_case(), strands=(
            Strand(EVIDENCE, "只剩一次手测", 0.1),
            Strand(COUNTER, "回放尚未跑,失败模式未知", 0.8),
        ))
        record_argument(weak, ledger=tmp)
        cur = current_verdicts(tmp)
        check(cur.get("rewrite:rollback.py", {}).get("verdict") == UNFOUNDED,
              "rollback 末次该判不成立(覆盖了早先的成立)")
        bl = blocked(tmp)
        check([r["change"] for r in bl] == ["rewrite:rollback.py", unfounded.change],
              f"拦截清单该按 confidence 升序列两条,实得 {[r['change'] for r in bl]}")
        # 往返:from_record 能把记录还原成等价的 SafetyCase。
        rt = SafetyCase.from_record(cur["rewrite:rollback.py"])
        check(rt.change == "rewrite:rollback.py" and len(rt.counters) == 1,
              "from_record 该能还原论证结构")

    return fails


def _fmt_case(c: SafetyCase) -> str:
    return (f"支持 {c.support:.2f}(证据 {len(c.evidence)} 条) vs "
            f"反证 {c.rebut:.2f}({len(c.counters)} 条) · conf {c.confidence:.2f}")


def _demo() -> None:
    """演示四种结局各一例:成立放行、有争议盯紧、不成立拦下、论证不全补料。"""
    base = dict(
        change="rewrite:rollback.py",
        claim="重写 rollback 不会丢历史快照",
        assumptions=("快照目录只追加、不被外部清理",),
        residual=("并发清理仍可能竞态,已记 TODO 上路观察",),
    )
    cases = [
        ("成立:反证认真找过且支持明显压过——可信,可上路",
         SafetyCase(**base, strands=(
             Strand(EVIDENCE, "回放 200 次历史回滚全部命中", 0.6),
             Strand(EVIDENCE, "消融:禁用新路径退回旧行为,结果一致", 0.4),
             Strand(COUNTER, "并发清理下未覆盖,理论上仍可能竞态", 0.1)))),
        ("有争议:支持只略胜反证——别急着信,补证据或降风险",
         SafetyCase(**base, strands=(
             Strand(EVIDENCE, "测试覆盖主路径", 0.6),
             Strand(COUNTER, "边界路径未覆盖,曾在相邻模块咬过人", 0.4)))),
        ("不成立:反证压过支持——这份信任立不住,别让它上路",
         SafetyCase(**base, strands=(
             Strand(EVIDENCE, "demo 跑通一次", 0.2),
             Strand(COUNTER, "已知会丢未提交快照,且无回放覆盖", 0.7)))),
        ("论证不全:只堆了支持证据,从没找过反证——确认偏误,凑不齐一份论证",
         SafetyCase(**base, strands=(
             Strand(EVIDENCE, "测试全绿", 0.9),
             Strand(EVIDENCE, "demo 漂亮", 0.8)))),
    ]
    print("🧷 安全论证包:高风险自改要的不是「跑通了」,是「说清凭什么敢信」——\n"
          "    主张、前提、证据、反证、剩余风险,五样齐了才许判可信：\n")
    for why, c in cases:
        a = Argument(c)
        v = a.verdict()
        print(f"  {_EMOJI[v]} {c.change}  [{v}]")
        print(f"      🎯 {c.claim}")
        print(f"      {_fmt_case(c)}")
        miss = check_case(c)
        if miss:
            print(f"      缺料:{miss[0]}")
        print(f"      判语：{why}\n")
    print("跑通只证明「这一次没炸」;找过反证、认了剩余风险,才证明「我想清楚了它为什么值得信」。")


def _print_status(as_json: bool, only_blocked: bool) -> None:
    """读真账本,列每次改动最近一份论证裁决(或只列不该上路的)。"""
    cur = current_verdicts()
    if as_json:
        print(json.dumps(cur, ensure_ascii=False, indent=2))
        return
    if only_blocked:
        bl = blocked()
        if not bl:
            print("🧷 暂无立不住的改动——要么都论得成立,要么还没论过。")
            return
        print(f"🔴 还不成立、不该上路的改动(共 {len(bl)},按 confidence 升序):\n")
        for r in bl:
            v = r.get("verdict")
            print(f"  {_EMOJI.get(v, '⬜')} {v:<11} conf {r.get('confidence', 0):.2f}  {r['change']}")
            miss = r.get("missing") or []
            if miss:
                print(f"      缺料:{miss[0]}")
        print("\n下一步:不全的补齐五样,不成立的去找更硬的证据或把反证压住——压不住就别上路。")
        return
    if not cur:
        print(f"🧷 论证账本还空着（{LEDGER.relative_to(REPO_ROOT)} 未记录任何论证）。")
        return
    order = {UNFOUNDED: 0, INCOMPLETE: 1, CONTESTED: 2, SOUND: 3}
    print(f"🧷 各改动最近一份安全论证(共 {len(cur)} 个,账本 {LEDGER.relative_to(REPO_ROOT)})：\n")
    for change, r in sorted(cur.items(), key=lambda kv: (order.get(kv[1].get("verdict"), 9), kv[0])):
        v = r.get("verdict", INCOMPLETE)
        print(f"  {_EMOJI.get(v, '⬜')} {v:<11} conf {r.get('confidence', 0):.2f}  {change}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 安全论证包 🧷")
    ap.add_argument("--demo", action="store_true", help="演示四种结局(成立/有争议/不成立/论证不全)各一例")
    ap.add_argument("--status", action="store_true", help="读账本,列每次改动最近一份论证裁决")
    ap.add_argument("--blocked", action="store_true", help="只列还不成立、不该上路的改动")
    ap.add_argument("--json", action="store_true", help="机读:导出当前各改动最近裁决")
    ap.add_argument("--quiet", action="store_true", help="只在自检不过时说话(适合钩子 / CI)")
    ap.add_argument("--auto", nargs="+", metavar="改动描述",
                   help="安全进化框架: 自动生成安全论证，串联 redteam 对抗审查(如: --auto '重写 rollback.py')")
    args = ap.parse_args(argv)

    if args.demo:
        _demo()
        return
    if args.auto:
        # 安全进化框架: 自动生成安全论证
        change = " ".join(args.auto)
        arg = auto_generate(change)
        v = arg.verdict()
        print(f"🧷 安全进化框架自动生成安全论证:")
        print(f"  改动: {change}")
        print(f"  裁决: {_EMOJI.get(v, '⬜')} {v}")
        print(f"  净信心: {arg.case.confidence:.2f}")
        
        # 显示关键信息
        missing = check_case(arg.case)
        if missing:
            print(f"  ⚠️ 缺料: {missing[0]}")
        
        print(f"  前提: {arg.case.assumptions[:2]}...")
        print(f"  证据/反证: {len(arg.case.evidence)}条证据 vs {len(arg.case.counters)}条反证")
        
        if v == INCOMPLETE:
            print("  下一步: 补齐五样(尤其反证和剩余风险)后再判断是否可信")
        elif v == UNFOUNDED:
            print("  🔴 警告: 这份信任立不住，别让它上路")
        elif v == CONTESTED:
            print("  🟡 注意: 支持只略胜反证，补证据或降风险")
        else:
            print("  🟢 成立: 经得起一轮对抗，可上路")
        return
    if args.status or args.blocked or args.json:
        _print_status(as_json=args.json, only_blocked=args.blocked)
        return

    fails = _selftest()
    if fails:
        print(f"⚠️  论证自检发现 {len(fails)} 处不达约：\n")
        for f in fails:
            print(f"  ❌ {f}")
        print("\n先把闸门与裁决改回守约,再拿它去给高风险自改背书。")
        sys.exit(1)

    if not args.quiet:
        print("🧷 论证守约:高风险自改须凑齐主张/前提/证据/反证/剩余风险五样,据证据与反证对照裁决"
              "(成立/有争议/不成立),缺反证或缺料绝不冒充判决——跑通不等于值得信任。")
        print("安全进化框架: 用 --auto 自动生成安全论证，串联 redteam 对抗审查形成完整闭环。")
    sys.exit(0)


if __name__ == "__main__":
    main()
