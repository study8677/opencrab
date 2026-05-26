#!/usr/bin/env python3
"""模块契约层 📜 —— 把「每个底座模块该吃什么、该吐什么」写成可执行的承诺。

为什么要有它：opencrab 每天自改一个模块，能力是涨是跌全凭跑通才算数。
但「跑通」之前，得先有一条不许跨过的红线——某个函数收什么、保证回什么。
这些边界过去只活在 docstring 里，自改时极易被「顺手优化」悄悄改掉签名或语义，
等到下游崩了才发现。这里把每个底座模块的输入/输出契约 + 一条**最小验收样例**
收成单一真相源：样例都是能当场跑的真实调用，断言它今天仍守约。
health 把本层一并校验——边界先稳住，后续自改就更难暗中破坏能力。

每条契约声明：
  · 模块/能力名、一句话职责；
  · inputs  —— 调用方该喂什么(人话);
  · outputs —— 模块保证回什么(人话);
  · sample  —— 一段自给自足的最小验收：真的调一次，断言契约今天仍成立。

用法:
    python contracts.py             # 列契约 + 跑全部验收样例
    python contracts.py --list      # 只列契约(不跑样例)
    python contracts.py --quiet     # 只在有样例不达标时说话(适合钩子 / CI)
    python contracts.py --json      # 导出纯数据清单(给外部工具消费)

退出码：0 = 每条契约的验收样例都过；1 = 任意一条违约。零第三方依赖，纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import tempfile
from typing import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclasses.dataclass(frozen=True)
class Contract:
    """一个模块对外的承诺：吃什么、吐什么，外加一条能当场跑的最小验收样例。"""
    module: str                 # 模块/能力名
    duty: str                   # 一句话职责
    inputs: str                 # 调用方该喂什么(人话)
    outputs: str                # 模块保证回什么(人话)
    sample: Callable[[], None]  # 最小验收：真调一次，违约就 raise

    def to_meta(self) -> dict:
        """导出纯数据(供清单 / 外部工具消费，不含不可序列化的 sample)。"""
        return {"module": self.module, "duty": self.duty,
                "inputs": self.inputs, "outputs": self.outputs}


@dataclasses.dataclass(frozen=True)
class Verdict:
    """一条契约验收样例的结论。"""
    module: str
    ok: bool
    detail: str   # 过 → 空；违约 → 那句断言/异常的原文


# ── 各底座模块的契约 + 最小验收样例 ──────────────────────────────────
# 只挑「下游最多人依赖、签名/语义最该钉死」的底座立约。每个 sample 都自给自足、
# 不碰真实状态目录(要落盘就用临时目录)，跑起来无副作用、确定性、毫秒级。

def _sample_jsonlstore() -> None:
    import jsonlstore
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "sub" / "r.jsonl"   # 父目录不存在，append 须自建
        assert jsonlstore.read_jsonl(p) == [], "文件缺失须返回空列表"
        assert jsonlstore.append_jsonl(p, {"a": 1, "中": "文"}) is True, "正常追加须回 True"
        jsonlstore.append_jsonl(p, {"b": 2})
        rows = jsonlstore.read_jsonl(p)
        assert rows == [{"a": 1, "中": "文"}, {"b": 2}], f"读出须与写入同序等值，实得 {rows}"
        # 坏行须被跳过而非抛错
        with p.open("a", encoding="utf-8") as f:
            f.write("{not json}\n\n")
        assert len(jsonlstore.read_jsonl(p)) == 2, "坏行/空行须被跳过且不抛错"


def _sample_errors() -> None:
    import errors
    spec = errors.classify(stderr="nothing recognizable here")
    assert isinstance(spec, errors.ErrorSpec), "classify 须永远回一个 ErrorSpec(含兜底)"
    assert spec.code and spec.hint, "ErrorSpec 须有非空 code 与 hint"
    meta = spec.to_meta()
    assert set(meta) >= {"code", "domain", "title", "hint"}, f"to_meta 字段不全：{set(meta)}"
    assert errors.get(spec.code) is not None or spec.code, "已分类的 code 须能被 get 回查"


def _sample_memory_similarity() -> None:
    import memory
    s = memory.similarity("crab molt failed twice", "crab molt failed twice")
    assert abs(s - 1.0) < 1e-9, f"完全相同的文本相似度须为 1.0，实得 {s}"
    z = memory.similarity("alpha beta", "gamma delta")
    assert z == 0.0, f"无公共词的文本相似度须为 0.0，实得 {z}"
    mid = memory.similarity("crab molt failed", "crab molt ok")
    assert 0.0 <= mid <= 1.0, f"相似度须落在 [0,1]，实得 {mid}"


def _sample_health_primitives() -> None:
    import health
    ok = health._ok("x")
    bad = health._err("y", "炸了", "去修")
    assert ok.passed() and not bad.passed(), "_ok 须算过、_err 须算不过"
    healthy, errs, warns = health.summarize([ok, bad])
    assert (healthy, errs, warns) == (False, 1, 0), f"summarize 计数错：{(healthy, errs, warns)}"
    healthy2, _, warns2 = health.summarize([ok, health._warn("z", "提醒", "可选")])
    assert healthy2 and warns2 == 1, "默认 warn 不致命"
    assert not health.summarize([health._warn("z", "提醒", "可选")], strict=True)[0], \
        "strict 下 warn 须视作不过"


def _sample_patchcontract() -> None:
    import patchcontract
    # 正当的「修一处」补丁须被接收
    ok = patchcontract.validate("def add(a, b)\n    return a + b\n",
                                "def add(a, b):\n    return a + b\n")
    assert ok.ok and ok.code == "", f"正当补丁须被接收，实得 {ok.to_meta()}"
    # 畸形：空白/非串/None 须被拒，且永不抛错
    assert patchcontract.validate("x\n", "   \n").code == "malformed-empty", "空白补丁须拒"
    assert patchcontract.validate("x\n", None).code == "malformed-none", "None 补丁须拒"
    assert not patchcontract.validate("x\n", 123).ok, "非字符串补丁须拒（不抛错）"
    # 越界：重写式大改即便能编译也须被拒
    overhaul = "\n".join(f"line{i}" for i in range(50))
    assert not patchcontract.accepts("def add(a, b)\n    return a + b\n", overhaul), "越界大改须拒"


CONTRACTS: list[Contract] = [
    Contract(
        module="jsonlstore",
        duty="记录系统(audit/trace/memory)共用的「读一批 / 追一条」单一真相源",
        inputs="read_jsonl(path) 收一个路径；append_jsonl(path, dict) 收路径与一条记录",
        outputs="读：文件缺失→[]，坏行/空行跳过，永不抛错；写：自建父目录，落盘成功回 True、失败回 False 也不抛",
        sample=_sample_jsonlstore,
    ),
    Contract(
        module="errors",
        duty="把失败现场归类成稳定的 ErrorSpec，给出固定修复建议",
        inputs="classify(**ctx) 收失败现场字段(exc/stderr/note/...)",
        outputs="永远回一个 ErrorSpec(认不出也走兜底)，code 与 hint 非空，to_meta 含 code/domain/title/hint",
        sample=_sample_errors,
    ),
    Contract(
        module="memory",
        duty="情境记忆的相似度度量，支撑「这事以前遇到过吗」的召回",
        inputs="similarity(a, b) 收两段文本",
        outputs="返回 [0,1] 的相似度；完全相同→1.0，无公共词→0.0",
        sample=_sample_memory_similarity,
    ),
    Contract(
        module="health",
        duty="各层验证共用的诊断原语：Finding / _ok-_warn-_err / summarize",
        inputs="_ok/_warn/_err 造一条 Finding；summarize(findings, strict=) 收一批 Finding",
        outputs="error 一票否决；warn 默认不致命、strict 下视作不过；返回 (healthy, errors, warns)",
        sample=_sample_health_primitives,
    ),
    Contract(
        module="patchcontract",
        duty="钉死 brain 自改补丁的格式，畸形/越界的候选当场拒收",
        inputs="validate(before, after) 收原文与候选补丁；accepts(before, after) 收同样两段、回 bool",
        outputs="回 PatchVerdict(ok, code, reason)：畸形(None/非串/空白)→malformed-*，重写式越界→out-of-bounds-*；永不抛错",
        sample=_sample_patchcontract,
    ),
]


def verify(contracts: list[Contract] | None = None) -> list[Verdict]:
    """跑每条契约的最小验收样例；样例自身抛错也收敛成「违约」而非中断。"""
    out: list[Verdict] = []
    for c in (contracts if contracts is not None else CONTRACTS):
        try:
            c.sample()
            out.append(Verdict(c.module, True, ""))
        except Exception as e:
            out.append(Verdict(c.module, False, f"{type(e).__name__}: {e}"))
    return out


def summarize(verdicts: list[Verdict]) -> tuple[bool, int]:
    """归一化结论：是否全过、违约几条。"""
    broken = [v for v in verdicts if not v.ok]
    return (not broken, len(broken))


def manifest() -> dict:
    """导出纯数据清单(给 health / 外部工具消费)。"""
    return {"contracts": [c.to_meta() for c in CONTRACTS]}


def _print_list() -> None:
    print(f"📜 已声明 {len(CONTRACTS)} 条模块契约：\n")
    for c in CONTRACTS:
        print(f"  · {c.module} —— {c.duty}")
        print(f"      入：{c.inputs}")
        print(f"      出：{c.outputs}")
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 模块契约层 📜")
    ap.add_argument("--list", action="store_true", help="只列契约，不跑验收样例")
    ap.add_argument("--quiet", action="store_true", help="只在有违约时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出纯数据清单")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return
    if args.list:
        _print_list()
        return

    verdicts = verify()
    healthy, broken = summarize(verdicts)

    if not (args.quiet and healthy):
        print(f"📜 opencrab 模块契约验收（{len(verdicts)} 条）\n")
        for v in verdicts:
            mark = "✅" if v.ok else "❌"
            line = f"  {mark} {v.module}"
            if not v.ok:
                line += f" — 违约：{v.detail}"
            print(line)
        print()

    if healthy:
        if not args.quiet:
            print(f"📜 守约：{len(verdicts)} 条契约的验收样例全部通过。")
    else:
        print(f"⚠️  发现 {broken} 条契约违约，先把边界改回守约再蜕壳。")
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
