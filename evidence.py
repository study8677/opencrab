#!/usr/bin/env python3
"""证据账本 🧾 —— 给每条能力声明配一条「跑得通才算数」的验证命令，记下何时验过、是否过期。

为什么要有它：`skillgraph.py` 从领地里**静态地**看「这个模块有没有被某处点过名」，
那只能回答「曾经被守过吗」。但能力会**漂**：依赖换了、平台变了、上游悄悄改了行为——
半年前跑通的证明，今天未必还成立。一句「我会 X」若说不出「上次什么时候、用哪条命令
亲手验过」，就只是印象，不是证据。

本层把「我会什么」钉成一本**可证、有时效**的账本：

  · 声明(Claim) —— 我自称会做的一件事 + **能当场复跑**的验证命令(argv) + 时效(ttl)。
                    声明写在代码里，是单一真相源(像 contracts，但这里证的是「跑得通」)。
  · 验证(verify)—— 真的把那条命令跑一遍，退出码 0 = 成立，连同时间戳追加进账本。
  · 账本(ledger)—— 每次验证留一行 JSONL(只追加、不改写)，是「我何时、用啥、验出啥」的流水。
  · 时效(status)—— 把账本折叠成每条声明的**当前**状态：
                      🟢 新鲜  —— 验过且通过，仍在时效内；
                      🟡 过期  —— 验过且通过，但已超时效，证据失效，得重证；
                      🔴 失守  —— 最近一次验证没跑通(能力真塌了)；
                      ⚪ 未证  —— 账本里压根没它，光有声明没证据。

判过期靠时间戳 + 每条声明各自的时效天数，而非「最近想没想它」——能力在不在，和我
记不记得它无关。任意一条 🟡/🔴/⚪ 都让退出码非零，可挂进钩子 / CI 当门禁。

用法：
    python evidence.py                # 账本现状：每条声明的新鲜度小结
    python evidence.py --verify       # 复跑全部验证命令，追加进账本，再看现状
    python evidence.py --verify NAME  # 只复验某一条声明
    python evidence.py --quiet        # 只在有过期/失守/未证时说话(适合钩子 / CI)
    python evidence.py --json         # 机读：导出每条声明的当前状态

零第三方依赖，纯标准库。账本落在被 .gitignore 的 state/ 里，写盘失败绝不反噬生命。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402  —— 账本复用「读一批 / 追一条」的单一真相源

LEDGER_PATH = REPO_ROOT / "state" / "evidence" / "ledger.jsonl"
VERIFY_TIMEOUT = 120          # 单条验证命令的墙钟上限(秒)：证据不该把生命拖死


@dataclasses.dataclass(frozen=True)
class Claim:
    """一条能力声明：我自称会做什么 + 能当场复跑的验证命令 + 证据的时效。"""
    name: str                 # 声明名(账本里的主键)
    asserts: str              # 一句话：这条声明断言我会做什么
    argv: list[str]           # 验证命令：退出码 0 即视作成立
    ttl_days: float           # 证据时效：超过这么多天没复验，就算过期
    risk: float = 1.0         # 风险权重：这块能力悄悄腐烂的代价(越高越该优先巡到)

    def to_meta(self) -> dict:
        return {"name": self.name, "asserts": self.asserts,
                "argv": self.argv, "ttl_days": self.ttl_days, "risk": self.risk}


# ── 能力声明清单：单一真相源 ──────────────────────────────────────────
# 每条都点名一条**领地里真实存在、能当场跑**的命令；都带 --quiet / 自身够快，
# 复跑无外部副作用。新增一块能力，就在这里补一条它的「跑得通」证明。
_PY = [sys.executable]

CLAIMS: list[Claim] = [
    Claim(
        name="contracts",
        asserts="各底座模块的输入/输出契约今天仍守约",
        argv=_PY + ["contracts.py", "--quiet"],
        ttl_days=7,
    ),
    Claim(
        name="smoke",
        asserts="核心模块的烟雾用例仍能跑通",
        argv=_PY + ["smoke.py", "--quiet"],
        ttl_days=7,
    ),
    Claim(
        name="regression",
        asserts="历史回归用例没有重新破坏",
        argv=_PY + ["regression.py", "--quiet"],
        ttl_days=7,
    ),
    Claim(
        name="health",
        asserts="领地整体自检健康(各层验证全过)",
        argv=_PY + ["health.py", "--quiet"],
        ttl_days=3,
        risk=2.0,
    ),
    Claim(
        name="hands",
        # 这条能力的「新鲜证据」主要由 handsfeedback 回灌：每次亲手改完自测的判决会落账，
        # 让 trustscore 据此算出「自生手」的信任分。复跑命令则验证回灌这条管子本身还稳。
        asserts="自生手改完代码能自测、且自测判决能回灌成证据",
        argv=_PY + ["handsfeedback.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="patchnote",
        # 每爪落笔时同步写下「依据/契约影响/回滚点」，让动手可审可追责。
        # 复跑命令验证这条解释管子本身还稳：三种 integrate 模式的退路都能正确分流。
        asserts="自生手每落一爪都能同步写出依据、契约影响与可跑的回滚点",
        argv=_PY + ["patchnote.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="weaning_trial",
        # 断奶实战赛：拔掉外援,只准 brain 自己产补丁→自测→修不动就回滚。
        # 复跑命令验证 3 道真修仍全过、且回滚探针仍能触发——独立性靠通过率持续证明,不靠宣言。
        asserts="brain 不雇外援也能独立修通真伤,修不动则老实回滚保命",
        argv=_PY + ["weaning_trial.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="purefix_trial",
        # 纯函数小修实战赛:从「会修语法伤」迈向「会亲手改一处代码逻辑」。函数能跑但算错时,
        # 驱动力不是异常而是失败的判据——brain 拿通用变异算子改一处→过契约→全部判据复验,
        # 修不动就回滚。复跑命令验证 3 道真修仍全过、回滚探针仍触发、且修好的补丁真能过试衣间。
        asserts="brain 不雇外援也能凭失败的判据修对一处纯函数逻辑,且补丁真能过试衣间,修不动则回滚",
        argv=_PY + ["purefix_trial.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="patchcontract",
        # 自生补丁契约:钉死「什么样的改动才算一个合法的 brain 补丁」,畸形(空/非串)与
        # 越界(重写式大改)的候选当场拒收。复跑命令验证这道拒收闸仍把畸形/越界拒在门外、
        # 把正当的「修一处」补丁放进来——自生的手要可靠,先让每一爪可验证、可拒绝。
        asserts="brain 自改补丁的格式被钉死,畸形/越界的候选都会被契约当场拒收",
        argv=_PY + ["patchcontract.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="astlocator",
        # AST 自生手定位器:让 brain 小修按函数/方法/CLI 入口精确「找准下刀处」,只改那一段。
        # 复跑命令验证三类真实修补仍①定位准 ②只改那一段(段外不动) ③契约放行 ④oracle 判真修好——
        # 亲手写代码不能只会整文件替换,先得长出稳定的「找准下刀处」。
        asserts="brain 小修能按函数/方法/CLI入口精确定位并只改那一段,段外原样不动",
        argv=_PY + ["astlocator.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="autonomy_meter",
        # 自主依赖脱钩仪表:把每次自改逐条点名(调没调外援/回没回滚/证据回没回灌),
        # 折成 7 日断奶趋势线。复跑命令验证汇流/折叠/趋势判读这条观测管子本身还稳——
        # 独立性要被持续观测,不靠一次比赛宣称。
        asserts="每次自改的外援依赖/回滚/回灌能被汇流成可观测的 7 日断奶趋势线",
        argv=_PY + ["autonomy_meter.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="patchfitroom",
        # brain 补丁试衣间:候选补丁绝不直接写真文件,先穿到隔离临时副本上过 语法/import/契约 三闸,
        # 四闸全过才原子写回,没过则真文件分毫不动。复跑命令验证过闸写回成立、四道闸各能拒收、
        # 且每次拒收后真文件确实没被碰过——一只会动手的爪子,第一要务是先学会不伤到自己。
        asserts="brain 补丁先在临时副本过 语法/触觉/import/契约 闸,过闸才原子写回,没过则真文件分毫不动",
        argv=_PY + ["patchfitroom.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="readpack",
        # 自生手读码上下文包:改码前围着 astlocator 定位到的那一段,自动汇总目标本体/调用方/
        # 契约/近邻测试四样。复跑命令验证四个断面都汇准、定不到位与畸形源码都老实回「读不出」——
        # 亲手写代码的第二步是先读懂下刀处的上下文,看清边界再落笔。
        asserts="改码前能围着下刀处汇准目标签名/调用方/契约/近邻测试,看懂边界再落笔",
        argv=_PY + ["readpack.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="fitrework",
        # 试衣间拒收返工单:把每次被试衣间拦下的补丁,自动封成可复跑的 replay 案例(命令走 --fit-dry,
        # 重跑只判收/拒、绝不写真文件)+ 一道 coach 失败训练题。复跑命令验证拒收才封、过闸跳过、
        # 案例命令能零副作用重跑出同样的拒收——自生的手会犯错,犯过的错要复练得到才会真正长稳。
        asserts="试衣间拒收的补丁会被自动封成可复跑的 replay 案例+coach 训练题,且重跑零副作用",
        argv=_PY + ["fitrework.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="touch",
        # 自生手触觉层:落笔前后比对目标的副作用足迹,候选若在原本只算数的地方偷长出新的
        # IO/环境变量/网络/执行命令,当场拒收。复跑命令验证四类新增各能摸出并拒收、原文已有的
        # 副作用不误伤、候选解析失败稳稳弃权——手不只要会写得对,还要摸得到自己这一爪会不会伸向身体之外。
        asserts="落笔前后比对副作用,候选新增 IO/环境变量/网络/执行命令即被触觉摸出并拒收,只拒新增不误伤原有",
        argv=_PY + ["touch.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="moveset",
        # 自生手补丁招式库:把 weaning 的底层招式(补冒号/括号print/名字纠偏)收成「落爪前先查一眼」的谱——
        # 每招配自验(拿自己的 worked example 重跑还修不修得通)+ 从历次战报采掘的实战胜率。复跑命令验证
        # 每招都能自验修通、且 suggest 只端「真能对这段源码落地」的招并按可靠度排序——手不该只会试错,
        # 还要把经验变成下次落爪前的直觉。
        asserts="撞上报错时,招式库能按实战可靠度荐出真能对这段源码落地的改写招,而非盲目逐招试",
        argv=_PY + ["moveset.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="retirement_drill",
        # 低热低信任退役演练:替每个退役候选真去证一遍替代路径(继任者在不在/门开不开/证据信不信),
        # 证到位才给删/并/降级,证不出就留人、after 一律留空绝不现编。复跑命令验证替代闸四态分明、
        # 删/并/降级/不许动判得清、「证不出绝不编 after 骗过 lifecycle 闸门」——代谢要靠证替代,不靠拍脑袋删。
        asserts="退役候选必先证明替代路径活着(继任者在/门开/证据可信)才给删/并/降级,证不出则留人且 after 留空",
        argv=_PY + ["retirement_drill.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="coldstart_drill",
        # 账本冷启动一致性演练:带一本来历不明的账本重新醒来时,封印能各按其分处置——
        # 空账本→自建(给空账本立起可校验基准)、旧基准→迁移(判旧版本而非篡改、免 force 重封)、
        # 改过了→拒伪(判篡改报警且非 force 拒绝重封洗白)。复跑命令验证三态判决各得其位、
        # 互不相同——记忆与证据不可信,自主进化就失了根,这条根要每日可见地守住。
        asserts="冷启动三态各按其分:空账本能自建基准、旧封印格式判旧版本能迁移重封、篡改判伪且拒绝无 force 洗白",
        argv=_PY + ["coldstart_drill.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="handsdojo",
        # 自生手失败样本库:brain-only 改码「修不动」自动封成可复跑(replay)可训练(coach)的训练题。
        # 同伤只封一次,招式库每长一招就能 --replay-all 看又填平了哪几道旧坑。复跑命令验证
        # 封样指纹/去重、replay 判决(brain 真能修的伤判毕业)、coach 转换、summary 折叠都不崩——
        # 真正的断奶靠把每次笨拙练成下次会,不靠硬撑。
        asserts="brain 修不动的真伤能封成失败样本,可复跑看如今修没修通、可转成 coach 训练回合",
        argv=_PY + ["handsdojo.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
    Claim(
        name="hotpath_stress",
        # 自生手热路径端到端压测:拿 3 道真实小修当负载,把整条热路径——brain(产补丁)→试衣(过五闸)
        # →验证(还能不能启动+真修好了没)→回灌(提炼成证据)——逐段掐表跑一遍,量出第一个卡点。
        # 复跑命令验证 3 道小修热路径全段贯通、性能卡点点到墙钟最重的段、无解伤被准确判成 brain 段硬卡点——
        # 会动手不等于手稳:稳,先得知道慢在哪、卡在哪。
        asserts="自生手整条热路径(brain→试衣→验证→回灌)端到端贯通,且能量出墙钟/硬卡点这第一个瓶颈",
        argv=_PY + ["hotpath_stress.py", "--selfcheck", "--quiet"],
        ttl_days=7,
        risk=2.0,
    ),
]


@dataclasses.dataclass(frozen=True)
class Status:
    """一条声明折叠后的当前状态。"""
    name: str
    state: str        # "fresh" | "stale" | "broken" | "unproven"
    last_ok: bool | None    # 最近一次验证是否通过(未证→None)
    verified_at: float | None  # 最近一次验证的时间戳(epoch 秒；未证→None)
    age_days: float | None     # 距上次验证多少天(未证→None)
    ttl_days: float
    detail: str       # 失守时的现场原文；否则空

    _MARKS = {"fresh": "🟢", "stale": "🟡", "broken": "🔴", "unproven": "⚪"}
    _WORDS = {"fresh": "新鲜", "stale": "过期", "broken": "失守", "unproven": "未证"}

    @property
    def mark(self) -> str:
        return self._MARKS[self.state]

    @property
    def word(self) -> str:
        return self._WORDS[self.state]

    @property
    def settled(self) -> bool:
        """是否「有充分有效证据」——只有新鲜算数；过期/失守/未证都不算。"""
        return self.state == "fresh"

    def to_meta(self) -> dict:
        return {"name": self.name, "state": self.state, "last_ok": self.last_ok,
                "verified_at": self.verified_at, "age_days": self.age_days,
                "ttl_days": self.ttl_days, "detail": self.detail}


# ── 验证：真的把命令跑一遍 ────────────────────────────────────────────
def run_verify(claim: Claim, *, now: float | None = None) -> dict:
    """复跑一条声明的验证命令，返回可落账的记录(不负责落盘)。

    退出码 0 → ok=True。命令超时 / 起不来 → ok=False，detail 记下原因(绝不抛错)。
    """
    ts = time.time() if now is None else now
    try:
        proc = subprocess.run(
            claim.argv, cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=VERIFY_TIMEOUT,
        )
        ok = proc.returncode == 0
        detail = "" if ok else (proc.stderr or proc.stdout or "").strip()[-500:]
    except subprocess.TimeoutExpired:
        ok, detail = False, f"验证命令超过 {VERIFY_TIMEOUT}s 未结束"
    except Exception as e:  # noqa: BLE001  —— 验证是观测者，起不来也只是「这次没验成」
        ok, detail = False, f"{type(e).__name__}: {e}"
    return {"name": claim.name, "ok": ok, "ts": ts, "detail": detail,
            "argv": claim.argv}


def record(rec: dict) -> bool:
    """把一条验证记录追加进账本(只追加、不改写)。写盘失败被吞掉，不反噬生命。"""
    return jsonlstore.append_jsonl(LEDGER_PATH, rec)


def verify(claim: Claim) -> dict:
    """复跑 + 落账一条声明，返回那条记录。"""
    rec = run_verify(claim)
    record(rec)
    return rec


# ── 折叠：账本 → 每条声明的当前状态 ───────────────────────────────────
def _latest_by_name(rows: list[dict]) -> dict[str, dict]:
    """账本是只追加的流水，按名取「时间戳最大」的那条作为最近一次验证。"""
    latest: dict[str, dict] = {}
    for r in rows:
        name = r.get("name")
        if not isinstance(name, str):
            continue
        prev = latest.get(name)
        if prev is None or r.get("ts", 0) >= prev.get("ts", 0):
            latest[name] = r
    return latest


def classify(claim: Claim, rec: dict | None, *, now: float | None = None) -> Status:
    """把「一条声明 + 它最近一次验证记录」判成当前状态。

    无记录 → ⚪未证；最近一次没跑通 → 🔴失守；跑通但超时效 → 🟡过期；否则 🟢新鲜。
    """
    now = time.time() if now is None else now
    if rec is None:
        return Status(claim.name, "unproven", None, None, None, claim.ttl_days, "")

    ts = rec.get("ts")
    verified_at = float(ts) if isinstance(ts, (int, float)) else None
    age_days = (now - verified_at) / 86400.0 if verified_at is not None else None
    ok = bool(rec.get("ok"))

    if not ok:
        return Status(claim.name, "broken", False, verified_at, age_days,
                      claim.ttl_days, str(rec.get("detail", "")))
    if age_days is None or age_days > claim.ttl_days:
        return Status(claim.name, "stale", True, verified_at, age_days,
                      claim.ttl_days, "")
    return Status(claim.name, "fresh", True, verified_at, age_days,
                  claim.ttl_days, "")


def status(claims: list[Claim] | None = None, *,
           rows: list[dict] | None = None, now: float | None = None) -> list[Status]:
    """读账本，折叠出每条声明的当前状态(全程只读，不复跑、不落盘)。"""
    claims = CLAIMS if claims is None else claims
    rows = jsonlstore.read_jsonl(LEDGER_PATH) if rows is None else rows
    latest = _latest_by_name(rows)
    return [classify(c, latest.get(c.name), now=now) for c in claims]


def summarize(statuses: list[Status]) -> tuple[bool, dict[str, int]]:
    """归一化：是否每条都有充分有效证据(全 🟢)，外加各状态计数。"""
    counts = {"fresh": 0, "stale": 0, "broken": 0, "unproven": 0}
    for s in statuses:
        counts[s.state] += 1
    all_settled = all(s.settled for s in statuses)
    return all_settled, counts


# ── 巡逻：按过期度 × 风险抽样复验，失败自动开修复小单 ────────────────────
# 全量复验越来越贵(声明只增不减)，而能力腐烂是渐进的——不必每次都全验。
# 巡逻按「该不该现在重看」给每条声明打分，只复验最该看的前 N 条：
#   · 未证(⚪) / 失守(🔴) —— 最该盯，给最高基线分；
#   · 新鲜/过期 —— 按过期度(age/ttl，越超期分越高)算；
#   · 再统一乘以各自的风险权重(risk)——腐烂代价高的，同等过期度下先巡；
#   · 最后按 usageheat 的真实常用度加权——被真实反复用到的能力，同等过期度下更该先巡
#     (强弱应先盯真实常用处，而非雨露均沾)。
# 分数 ≤ 0(远未到期且不急)的不打扰，省得把生命耗在没必要的复跑上。
# 真实常用度加权：高频用到的能力，同等过期度下先巡——强弱应先盯真实常用处，
# 而非雨露均沾。点名次数 ≥ _USAGE_CAP 即视作「很常用」，最多把分数抬到 2 倍。
_USAGE_CAP = 5


def _usage_weights() -> dict[str, int]:
    """从 usageheat 取每个模块近期被点名次数，作为巡逻的「真实常用度」权重。

    读不到（审计缺失 / usageheat 不在）则回空——巡逻退化回纯「过期度×风险」，绝不臆测谁热。
    """
    try:
        import usageheat  # 延迟导入：避免与 usageheat 互相引用成环，且巡逻不强依赖它在场
        return usageheat.mentions_by_module()
    except Exception:  # noqa: BLE001
        return {}


def patrol_score(status: Status, claim: Claim, *, usage: int = 0) -> float:
    """这条声明此刻「该不该重看」的紧迫度：未证/失守最高，其余按过期度，乘风险权重。

    usage = 该能力近期被点名次数；同等过期度下，被真实用得越多的越先巡（最多抬到 2 倍）。
    """
    if status.state == "unproven":
        base = 2.0           # 光有声明没证据，最该补一次
    elif status.state == "broken":
        base = 1.5           # 已知塌了，复验确认是否修回来/仍塌
    else:
        # 新鲜/过期：过期度 = 距上次验证的天数 ÷ 时效。=1 恰好到期，>1 已超期。
        overdue = (status.age_days or 0.0) / claim.ttl_days if claim.ttl_days > 0 else 1.0
        base = overdue - 0.5  # 留半个时效的余量：才验过没多久的，分数为负，不打扰
    score = base * claim.risk
    # 只对「本就该看(分数>0)」的加权——别把才验过的常用能力硬拽回来重跑。
    if score > 0 and usage > 0:
        score *= 1.0 + min(usage, _USAGE_CAP) / _USAGE_CAP
    return score


def select_patrol(statuses: list[Status], budget: int,
                  claims: list[Claim] | None = None,
                  *, usage: dict[str, int] | None = None) -> list[Claim]:
    """挑出本轮最该复验的前 budget 条声明(分数 > 0 才入选；按分数降序、同分按名字定序)。

    usage 缺省时自动从 usageheat 取真实常用度；传 {} 可显式关掉常用度加权。
    """
    by_name = {c.name: c for c in (CLAIMS if claims is None else claims)}
    usage = _usage_weights() if usage is None else usage
    scored = []
    for s in statuses:
        c = by_name.get(s.name)
        if c is None:
            continue
        score = patrol_score(s, c, usage=usage.get(s.name, 0))
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda t: (-t[0], t[1].name))
    return [c for _, c in scored[:max(0, budget)]]


def file_fix_ticket(claim: Claim, rec: dict) -> bool:
    """复验失守 → 往进件队列开一张修复小单(尽力而为，开不出也不反噬巡逻)。

    小单文案对每条声明**稳定**(不含时间戳)，于是 intake 按内容去重——
    持续失守只攒一张单，修回来后那张单自然不再被复开。
    """
    try:
        import intake  # 延迟导入：巡逻不强依赖进件层在场
        detail = (rec.get("detail") or "").splitlines()
        first = detail[0][:160] if detail else ""
        cmd = " ".join(claim.argv[1:]) or claim.argv[0]
        text = (f"能力『{claim.name}』证据复验失守(回归失败)：{claim.asserts}。"
                f"复验命令 `{cmd}` 退出码非零。验收线：该命令重新跑通(退出码 0)。"
                + (f" 现场：{first}" if first else ""))
        _, is_new = intake.capture(text, source=intake.SOURCE_JOURNAL, ref="evidence")
        return is_new
    except Exception:  # noqa: BLE001 —— 开单是副产物，进件层缺席/出错都不该拖垮巡逻
        return False


def patrol(budget: int = 2, *, claims: list[Claim] | None = None) -> dict:
    """巡逻一轮：按过期度×风险抽样复验前 budget 条，失败自动开修复小单。

    返回本轮纪要：复验了哪些、各自通过否、开出几张修复小单。全程尽力而为。
    """
    claims = CLAIMS if claims is None else claims
    befores = status(claims)
    picked = select_patrol(befores, budget, claims)
    results, tickets = [], []
    for c in picked:
        rec = verify(c)
        results.append(rec)
        if not rec["ok"] and file_fix_ticket(c, rec):
            tickets.append(c.name)
    return {"budget": budget, "checked": [r["name"] for r in results],
            "failed": [r["name"] for r in results if not r["ok"]],
            "tickets": tickets, "results": results}


# ── 展示 ──────────────────────────────────────────────────────────────
def _fmt_age(s: Status) -> str:
    if s.age_days is None:
        return "从未验证"
    d = s.age_days
    when = f"{d:.1f} 天前" if d >= 1 else f"{d * 24:.1f} 小时前"
    return f"{when}(时效 {s.ttl_days:g} 天)"


def _print_status(statuses: list[Status]) -> None:
    all_settled, counts = summarize(statuses)
    print(f"🧾 opencrab 证据账本（{len(statuses)} 条声明）\n")
    by_name = {c.name: c for c in CLAIMS}
    for s in statuses:
        claim = by_name.get(s.name)
        asserts = claim.asserts if claim else ""
        print(f"  {s.mark} {s.name}（{s.word}）—— {asserts}")
        print(f"      上次验证：{_fmt_age(s)}")
        if s.state == "broken" and s.detail:
            print(f"      失守现场：{s.detail.splitlines()[0][:120]}")
        if claim:
            print(f"      复验命令：{' '.join(claim.argv[1:]) or claim.argv[0]}")
    print()
    bar = "  ".join(f"{Status._MARKS[k]}{counts[k]}"
                    for k in ("fresh", "stale", "broken", "unproven"))
    print(f"  小结：{bar}")
    if all_settled:
        print("🧾 每条能力声明都有新鲜、跑得通的证据。")
    else:
        need = [s.name for s in statuses if not s.settled]
        print(f"⚠️  {len(need)} 条声明证据不足（过期/失守/未证）：{'、'.join(need)}")
        print("    跑 `python evidence.py --verify` 复证，或把已塌的能力修回来。")


def manifest() -> dict:
    """导出纯数据：每条声明 + 其当前状态(给 health / 外部工具消费)。"""
    return {"claims": [c.to_meta() for c in CLAIMS],
            "status": [s.to_meta() for s in status()]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 证据账本 🧾")
    ap.add_argument("--verify", nargs="?", const="*", metavar="NAME",
                    help="复跑验证命令并落账：不带名=全部，带名=只验该条")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有过期/失守/未证时输出(适合钩子 / CI)")
    ap.add_argument("--patrol", nargs="?", type=int, const=2, metavar="N",
                    help="巡逻：按过期度×风险抽样复验最该看的前 N 条(默认 2)，失败自动开修复小单")
    ap.add_argument("--json", action="store_true", help="导出机读状态清单")
    args = ap.parse_args(argv)

    if args.patrol is not None:
        rep = patrol(args.patrol)
        if not args.quiet:
            checked = rep["checked"]
            print(f"🧾 证据巡逻：抽样复验 {len(checked)} 条"
                  f"（{'、'.join(checked) or '无到期声明'}）")
            for r in rep["results"]:
                print(f"  {'🟢' if r['ok'] else '🔴'} {r['name']}")
            if rep["tickets"]:
                print(f"  ✍️  已开 {len(rep['tickets'])} 张修复小单进进件队列："
                      f"{'、'.join(rep['tickets'])}")
            print()

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if args.verify is not None:
        target = args.verify
        todo = CLAIMS if target == "*" else [c for c in CLAIMS if c.name == target]
        if not todo:
            print(f"⚠️  没有名为 {target!r} 的声明；可选："
                  f"{'、'.join(c.name for c in CLAIMS)}")
            sys.exit(2)
        if not args.quiet:
            print(f"🧾 复证 {len(todo)} 条声明……\n")
        for c in todo:
            rec = verify(c)
            mark = "🟢" if rec["ok"] else "🔴"
            if not args.quiet:
                line = f"  {mark} {c.name}"
                if not rec["ok"] and rec["detail"]:
                    line += f" — {rec['detail'].splitlines()[0][:120]}"
                print(line)
        if not args.quiet:
            print()

    statuses = status()
    all_settled, _ = summarize(statuses)
    if not (args.quiet and all_settled):
        _print_status(statuses)
    sys.exit(0 if all_settled else 1)


if __name__ == "__main__":
    main()
