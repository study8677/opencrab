#!/usr/bin/env python3
"""自生手失败样本库 🥋🖐️ —— 把每次 brain-only 改码「修不动」自动封成 replay+coach 训练题。

为什么要有它：`hands.py` 动手时**先走 brain-only 补丁**(凭招式库修语法级真伤)，brain
修不动才降级雇外援。可那次「修不动」用完就扔了——降级原因写进 `result["brain_reason"]`、
招式轨迹写进 `result["brain_trace"]`，随这次 use_hands 一起被遗忘。下次撞上同类伤，brain
还是修不动，照样花钱雇爪子。真正的断奶不靠硬撑，靠把**每一次笨拙都练成下次会**：

  · 把那道 brain 修不动的真伤(出错文件名 / 异常 / 试过哪些招都没解 / 那段坏源码)，
    自动封成一个**自包含的失败样本**，落在 `state/handsdojo/`。
  · 样本是**可复跑(replay)**的：随时把同一段坏源码丢回招式库(只 compile 不 exec,探伤安全)，
    看如今(招式库长了新招之后)能不能修通了——能干净编译 = 这道坑被填上，样本「毕业」。
  · 样本也是**可训练(coach)**的：把它转成 `coach` 的一个失败训练回合(复现→根因→最小修→
    加守卫→沉记忆)，逼自己针对性补一招，而不是又花钱绕过去。

于是「修不动」不再是一笔死账，而是一道**到期会自动重考**的训练题：招式库每长一招，
`--replay-all` 就能一眼看出又有哪几道旧坑被填平、哪几道还在等新招。

封样只在「确有语法真伤、brain 试过招仍修不动」时发生——没伤可修(特性级改动)、brain 模块
缺席、或外援本就缺位，都不是「笨拙」，不封。同一道伤(文件+异常+源码指纹)只封一次，
不重复刷库。账本落在被 .gitignore 的 state/ 里；封样是副产物，写盘/复跑出任何错都被吞掉，
绝不反噬 hands 的动手主流程。零第三方依赖，纯标准库。

用法:
    python handsdojo.py                  # 列出样本库：每道未毕业的失败训练题
    python handsdojo.py --show <id>      # 摊开一个样本(坏源码/异常/试过的招/状态)
    python handsdojo.py --replay <id>    # 重考一道：brain 如今修得动吗(修通则标记毕业)
    python handsdojo.py --replay-all     # 全库重考：看招式库长进后又填平了哪几道坑
    python handsdojo.py --coach <id>     # 把一道失败样本转成 coach 训练回合并落档
    python handsdojo.py --json           # 机读：样本库清单 + 毕业率
    python handsdojo.py --selfcheck [--quiet]   # 自检关键路径(供 evidence 复跑)
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jsonlstore  # noqa: E402 —— 复用「读一批 / 追一条」的安全落地层

DOJO_DIR = REPO_ROOT / "state" / "handsdojo"
INDEX = DOJO_DIR / "samples.jsonl"
SOURCES = DOJO_DIR / "sources"          # 每道样本的坏源码单独落一个文件,索引只留指针

MAX_SRC_BYTES = 200_000                 # 单道坏源码封存上限,超大文件只是噪声,不收


# ── 一道失败样本 ────────────────────────────────────────────────────────
@dataclasses.dataclass
class Sample:
    """一道 brain-only 改码修不动的真伤,封成可复跑可训练的训练题。"""
    id: str                      # 内容指纹(同伤只封一次的依据)
    ts: float                    # 封样时刻
    file: str                    # 出伤的文件名
    exc_type: str                # brain 最终卡住的异常类型(如 SyntaxError)
    exc_msg: str                 # 异常摘要(人话,已压长)
    lineno: int                  # 出错行号(0=未知)
    reason: str                  # hands 给的降级原因(brain_reason)
    trace: list                  # brain 试过哪些招都没解(brain_trace 里属于本文件的)
    executor: str                # 当时本要降级雇哪只外援
    solved: bool = False         # 是否已被「重考」修通而毕业
    solved_ts: float = 0.0       # 毕业时刻(0=尚未毕业)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Sample":
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in fields})


def _signature(file: str, exc_type: str, broken: str) -> str:
    """同一道伤的指纹：文件名 + 异常类型 + 坏源码内容。同指纹只封一次,不刷库。"""
    h = hashlib.sha1()
    h.update(file.encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(exc_type.encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(broken.encode("utf-8", "replace"))
    return h.hexdigest()[:12]


def _src_path(sample_id: str) -> pathlib.Path:
    return SOURCES / f"{sample_id}.py"


# ── 封样：从 hands 结果里把 brain 修不动的真伤落进库 ──────────────────────
def _failed_samples(result: dict) -> list[dict]:
    """从 use_hands 结果里取出 brain 修不动的真伤清单(hands 已附在 brain_failed_samples)。"""
    raw = result.get("brain_failed_samples")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict) and item.get("broken") and item.get("file"):
            out.append(item)
    return out


def _index_signatures(rows: list[dict] | None = None) -> set[str]:
    """已封过的指纹集合(样本 id 就是指纹),用来去重。"""
    rows = jsonlstore.read_jsonl(INDEX) if rows is None else rows
    return {str(r.get("id")) for r in rows if r.get("id")}


def seal(result: dict) -> list[Sample]:
    """封样入口：把一次 use_hands 里 brain 修不动的真伤封成失败样本并落库。

    返回这次新封的样本(同伤已封过则跳过)。全程尽力而为：任何异常都被吞掉,
    绝不反噬 hands 的动手主流程。只封「确有语法真伤、试过招仍修不动」的那几道。
    """
    try:
        if not isinstance(result, dict) or result.get("dry_run"):
            return []
        wounds = _failed_samples(result)
        if not wounds:
            return []
        seen = _index_signatures()
        executor = str(result.get("executor") or "?")
        now = time.time()
        sealed: list[Sample] = []
        for w in wounds:
            broken = str(w.get("broken") or "")
            file = str(w.get("file") or "?")
            exc_type = str(w.get("exc_type") or "?")
            if len(broken.encode("utf-8", "replace")) > MAX_SRC_BYTES:
                continue                       # 超大源码只是噪声,不收
            sig = _signature(file, exc_type, broken)
            if sig in seen:
                continue                       # 同伤已封过,不刷库
            seen.add(sig)
            s = Sample(
                id=sig, ts=now, file=file, exc_type=exc_type,
                exc_msg=str(w.get("exc_msg") or "")[:200],
                lineno=int(w.get("lineno") or 0),
                reason=str(result.get("brain_reason") or "")[:200],
                trace=[str(t) for t in (w.get("trace") or [])][:20],
                executor=executor)
            _src_path(sig).parent.mkdir(parents=True, exist_ok=True)
            _src_path(sig).write_text(broken, encoding="utf-8")
            jsonlstore.append_jsonl(INDEX, s.to_dict())
            sealed.append(s)
        return sealed
    except Exception:  # noqa: BLE001 —— 封样是副产物,出错绝不拖垮动手
        return []


# ── 读库 ────────────────────────────────────────────────────────────────
def load() -> list[Sample]:
    """读出全库样本(封样时间正序);坏行从容跳过。"""
    out: list[Sample] = []
    seen: set[str] = set()
    for r in jsonlstore.read_jsonl(INDEX):
        try:
            s = Sample.from_dict(r)
        except Exception:  # noqa: BLE001
            continue
        if s.id in seen:        # 并发封样可能留下同 id 重复行,读时只认第一条
            continue
        seen.add(s.id)
        out.append(s)
    out.sort(key=lambda s: s.ts)
    return out


def _get(sample_id: str) -> Sample | None:
    for s in load():
        if s.id == sample_id or s.id.startswith(sample_id):
            return s
    return None


def broken_of(sample: Sample) -> str:
    """取一道样本封存的坏源码;丢了就返回空串。"""
    p = _src_path(sample.id)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except Exception:  # noqa: BLE001
        return ""


# ── 复跑(replay)：brain 如今修得动这道旧伤了吗 ──────────────────────────
def _heal_by_compile(broken: str, *, max_rounds: int = 8) -> tuple[str | None, list[str]]:
    """只用 compile() 当自测的招式复考引擎：纯语法级修复,**绝不 exec 存的真模块源码**。

    这正是 `hands._brain_attempt` 复刻——它产出这道伤时本就只 compile 不 exec(探伤安全)。
    复用 weaning_trial 的招式库与 patchcontract 拒收闸,判据降到最低的「能干净编译」:
    招式吐候选 → 过契约 → compile 通过即毕业;一招都使不上则无招可解。
    返回 (修好的源码或 None, 招式轨迹)。
    """
    import weaning_trial      # 招式库
    import patchcontract      # 拒收闸
    src, trace = broken, []
    for _ in range(max_rounds):
        try:
            compile(src, "<handsdojo-replay>", "exec")
            return src, trace        # 能干净编译 = 这道伤被填平
        except SyntaxError as exc:
            applied = False
            for tactic in weaning_trial.TACTICS:
                cand = tactic(src, exc)
                if not cand or cand == src:
                    continue
                verdict = patchcontract.validate(src, cand)
                if not verdict.ok:
                    trace.append(f"{tactic.__name__} 被契约拒收({verdict.code})")
                    continue
                trace.append(f"{tactic.__name__} ⮕ {type(exc).__name__}")
                src, applied = cand, True
                break
            if not applied:
                trace.append(f"无招可解 {type(exc).__name__}")
                return None, trace
    trace.append("回合用尽仍未修通")
    return None, trace


def replay(sample: Sample, *, persist: bool = True) -> dict:
    """重考一道样本：把当年那段坏源码丢回招式库,看如今能否修通。

    oracle 用最低判据「能干净编译」——招式只治语法级真伤,且**只 compile 不 exec**,
    复考绝不会跑起当年那个真模块的副作用(探伤安全,与 hands 产伤时一致)。
    修通则标记毕业(solved)并回写库;修不动则维持原状,等招式库再长一招。
    返回 {id, verdict, fixed, trace}: verdict ∈ graduated / still_stuck / source_lost / no_brain。
    """
    broken = broken_of(sample)
    if not broken:
        return {"id": sample.id, "verdict": "source_lost",
                "fixed": False, "trace": []}
    try:
        fixed_src, trace = _heal_by_compile(broken)
    except Exception as e:  # noqa: BLE001 —— 招式库缺席/异常都算这次没修通,绝不抛
        return {"id": sample.id, "verdict": "no_brain",
                "fixed": False, "trace": [f"复考引擎不可用({type(e).__name__})"]}

    fixed = fixed_src is not None
    verdict = "graduated" if fixed else "still_stuck"
    if fixed and persist and not sample.solved:
        _mark_solved(sample.id)
    return {"id": sample.id, "verdict": verdict, "fixed": fixed, "trace": trace}


def _mark_solved(sample_id: str) -> None:
    """把一道样本标记为毕业,整本索引原子重写一遍(库小,代价可忽略);出错吞掉。

    用「写临时文件 + os.replace」原子换名,避免重写到一半被 kill 把索引写残。
    """
    try:
        rows = jsonlstore.read_jsonl(INDEX)
        now = time.time()
        for r in rows:
            if r.get("id") == sample_id and not r.get("solved"):
                r["solved"] = True
                r["solved_ts"] = now
        tmp = INDEX.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8")
        os.replace(tmp, INDEX)      # 原子换名：要么旧索引,要么新索引,绝不留半截
    except Exception:  # noqa: BLE001
        pass


def replay_all(*, persist: bool = True) -> list[dict]:
    """全库重考:对每道**还没毕业**的样本跑一遍 replay,看招式库长进后填平了哪几道。"""
    return [replay(s, persist=persist) for s in load() if not s.solved]


# ── 训练(coach)：把一道失败样本转成训练回合 ──────────────────────────────
def to_round(sample: Sample, *, level: int = 1, persist: bool = True):
    """把一道失败样本转成 coach 的失败训练回合(并落档),逼自己针对性补一招。

    描述里带上文件/异常/招式轨迹,让 coach 借 errors.classify 认错码、对症出练习。
    coach 缺席则返回 None(封样侧不强依赖训练层在场)。
    """
    try:
        import coach
    except Exception:  # noqa: BLE001
        return None
    situation = describe(sample)
    rnd = coach.coach(situation, level=level)
    if persist:
        coach.record(rnd)
    return rnd


def describe(sample: Sample) -> str:
    """把一道样本摊成一段「失败现场」描述,喂给 coach / 人看都对症。"""
    where = f"{sample.file}" + (f":{sample.lineno}" if sample.lineno else "")
    head = f"自生手 brain-only 改码失败：{where} 上 {sample.exc_type} 修不动"
    msg = f"，报错「{sample.exc_msg}」" if sample.exc_msg else ""
    tried = ("；试过的招都没解：" + "；".join(sample.trace)) if sample.trace else ""
    return head + msg + tried


# ── 折叠：库的健康度 ────────────────────────────────────────────────────
def summary(samples: list[Sample] | None = None) -> dict:
    """库的概览:总样本数、已毕业数、毕业率、各异常类型分布。"""
    samples = load() if samples is None else samples
    total = len(samples)
    grad = sum(1 for s in samples if s.solved)
    by_exc: dict[str, int] = {}
    for s in samples:
        by_exc[s.exc_type] = by_exc.get(s.exc_type, 0) + 1
    return {"total": total, "graduated": grad, "open": total - grad,
            "graduation_rate": round(grad / total, 4) if total else 0.0,
            "by_exc": dict(sorted(by_exc.items(), key=lambda kv: -kv[1]))}


# ── 展示 ────────────────────────────────────────────────────────────────
def _ago(ts: float, now: float) -> str:
    if not isinstance(ts, (int, float)) or ts <= 0:
        return "?"
    d = (now - ts) / 86400.0
    return f"{d:.1f} 天前" if d >= 1 else f"{d * 24:.1f} 小时前"


def _print_library(now: float) -> None:
    samples = load()
    s = summary(samples)
    print("🥋🖐️  自生手失败样本库（brain-only 修不动 → 可复跑可训练的训练题）\n")
    if not samples:
        print("  （库还空着——等 brain 真撞上一道修不动的语法伤，才封得出第一道训练题。）")
        return
    print(f"  共 {s['total']} 道 · 已毕业 {s['graduated']} · 待填 {s['open']} "
          f"· 毕业率 {s['graduation_rate']:.0%}")
    if s["by_exc"]:
        dist = " · ".join(f"{k}×{v}" for k, v in s["by_exc"].items())
        print(f"  伤型分布：{dist}\n")
    for sample in samples:
        mark = "🎓 已毕业" if sample.solved else "🩹 待填"
        where = sample.file + (f":{sample.lineno}" if sample.lineno else "")
        print(f"  [{sample.id}] {mark} · {where} · {sample.exc_type} · 封于 {_ago(sample.ts, now)}")
        if sample.exc_msg:
            print(f"      报错：{sample.exc_msg[:80]}")


def _print_sample(sample: Sample, now: float) -> None:
    mark = "🎓 已毕业" if sample.solved else "🩹 待填"
    print(f"🥋  失败样本 [{sample.id}] {mark}")
    print(f"   文件：{sample.file}" + (f":{sample.lineno}" if sample.lineno else ""))
    print(f"   异常：{sample.exc_type}" + (f" — {sample.exc_msg}" if sample.exc_msg else ""))
    print(f"   封于：{_ago(sample.ts, now)}（本要降级雇 {sample.executor}）")
    if sample.reason:
        print(f"   降级原因：{sample.reason}")
    if sample.trace:
        print("   试过的招（都没解）：")
        for t in sample.trace:
            print(f"     - {t}")
    if sample.solved:
        print(f"   ✅ 已于 {_ago(sample.solved_ts, now)}重考修通而毕业。")
    broken = broken_of(sample)
    if broken:
        print("   封存的坏源码：")
        for line in broken.splitlines()[:30]:
            print(f"     | {line}")


# ── 自检 ────────────────────────────────────────────────────────────────
def _selfcheck() -> bool:
    """自检关键路径不抛错(供 evidence 的复跑命令)：封样指纹/去重、replay 判决、
    coach 转换、summary 折叠都不崩,且对一道 brain 真能修的伤判「毕业」。不写真库。
    """
    try:
        # 指纹稳定 + 同伤同指纹(去重的根基)
        sig1 = _signature("x.py", "SyntaxError", "def f()\n  pass\n")
        sig2 = _signature("x.py", "SyntaxError", "def f()\n  pass\n")
        assert sig1 == sig2 and len(sig1) == 12
        # _failed_samples 只挑出形态完整的真伤
        res = {"executor": "claude", "brain_reason": "brain 修不动 x.py",
               "brain_failed_samples": [
                   {"file": "x.py", "exc_type": "SyntaxError", "exc_msg": "expected ':'",
                    "lineno": 1, "broken": "def f()\n    return 1\n", "trace": ["补冒号被拒"]},
                   {"file": "", "broken": ""}]}  # 残缺的应被滤掉
        wounds = _failed_samples(res)
        assert len(wounds) == 1 and wounds[0]["file"] == "x.py"
        # 预演 / 无样本 → 不封
        assert seal({"dry_run": True}) == []
        assert seal({"brain_failed_samples": []}) == []
        # describe 带上文件/异常/招式轨迹
        s = Sample(id="abc", ts=1000.0, file="x.py", exc_type="SyntaxError",
                   exc_msg="expected ':'", lineno=1, reason="r",
                   trace=["补冒号被拒"], executor="claude")
        d = describe(s)
        assert "x.py:1" in d and "SyntaxError" in d and "补冒号被拒" in d
        # summary 折叠不崩,毕业率可算
        sm = summary([s, dataclasses.replace(s, id="z", solved=True)])
        assert sm["total"] == 2 and sm["graduated"] == 1 and sm["graduation_rate"] == 0.5
        # 复考引擎：一道漏冒号的伤应被 compile-only 招式修通(且全程不 exec 真源码)
        fixed_src, _tr = _heal_by_compile("def add(a, b)\n    return a + b\n")
        assert fixed_src is not None
        compile(fixed_src, "<sc>", "exec")          # 修好的确能干净编译
        # 一道无招可解的伤(顶层 raise 不是语法伤)→ compile 过但招式不动它,仍判修不通
        nope_src, _ = _heal_by_compile('x = (\n')   # 真语法伤但招式库不覆盖
        assert nope_src is None
        # 源码丢了 → source_lost,且 persist=False 不写真库(id 取一个真库不可能有的串)
        absent = dataclasses.replace(s, id="__selfcheck_absent_id__")
        assert replay(absent, persist=False)["verdict"] == "source_lost"
        return True
    except Exception:  # noqa: BLE001
        return False


# ── CLI ─────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 自生手失败样本库 🥋🖐️")
    ap.add_argument("--show", metavar="ID", help="摊开一个样本(坏源码/异常/试过的招)")
    ap.add_argument("--replay", metavar="ID", help="重考一道：brain 如今修得动吗")
    ap.add_argument("--replay-all", action="store_true", help="全库重考未毕业样本")
    ap.add_argument("--coach", metavar="ID", help="把一道失败样本转成 coach 训练回合")
    ap.add_argument("--json", action="store_true", help="机读：样本库清单 + 毕业率")
    ap.add_argument("--selfcheck", action="store_true", help="自检关键路径不抛错")
    ap.add_argument("--quiet", action="store_true", help="自检静默：只用退出码说话")
    args = ap.parse_args(argv)
    now = time.time()

    if args.selfcheck:
        ok = _selfcheck()
        if not args.quiet:
            print("🥋🖐️  自检" + ("通过：封样/复跑/训练关键路径都还稳。" if ok
                                  else "失败：样本库路径出问题了。"))
        sys.exit(0 if ok else 1)

    if args.json:
        out = {"summary": summary(), "samples": [s.to_dict() for s in load()]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if args.show:
        s = _get(args.show)
        if not s:
            print(f"🥋  没找到样本 {args.show}。")
            sys.exit(1)
        _print_sample(s, now)
        return

    if args.replay:
        s = _get(args.replay)
        if not s:
            print(f"🥋  没找到样本 {args.replay}。")
            sys.exit(1)
        r = replay(s)
        verds = {"graduated": "🎓 修通了——这道坑被填平,样本毕业！",
                 "still_stuck": "🩹 还修不动——等招式库再长一招。",
                 "source_lost": "⚠️ 坏源码丢了,无法重考。",
                 "no_brain": "⚠️ brain 模块缺席,无法重考。"}
        print(f"🥋  重考 [{s.id}]（{s.file} · {s.exc_type}）：{verds.get(r['verdict'], r['verdict'])}")
        for t in r["trace"]:
            print(f"     · {t}")
        return

    if args.replay_all:
        results = replay_all()
        if not results:
            print("🥋  没有待重考的样本（库空或全员已毕业）。")
            return
        grad = sum(1 for r in results if r["verdict"] == "graduated")
        print(f"🥋  全库重考 {len(results)} 道未毕业样本：本轮新毕业 {grad} 道。")
        by_id = {s.id: s for s in load()}
        for r in results:
            s = by_id.get(r["id"])
            tag = {"graduated": "🎓", "still_stuck": "🩹"}.get(r["verdict"], "⚠️")
            print(f"  {tag} [{r['id']}] {s.file if s else '?'} · {r['verdict']}")
        return

    if args.coach:
        s = _get(args.coach)
        if not s:
            print(f"🥋  没找到样本 {args.coach}。")
            sys.exit(1)
        rnd = to_round(s)
        if rnd is None:
            print("🥋  coach 模块缺席,无法转成训练回合。")
            sys.exit(1)
        print(rnd.render())
        return

    _print_library(now)


if __name__ == "__main__":
    main()
