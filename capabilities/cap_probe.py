"""能力 · 依赖与外部工具健康探针 🩺 —— 复用 probe.py，启动前确认「能不能跑」。

和 `cap_envcheck`(配置一致性)、`cap_checkup`(宽口径体检)分工：这里只盯
运行时真够不够得着依赖——解释器、标准库、外部命令(git/执行器)、第三方包——
并能把结果原样写进审计，让自愈与失败分流有据可依。
"""
from __future__ import annotations

import pathlib
import sys

from . import Result, capability

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@capability("probe", "健康探针：探解释器/标准库/外部命令/第三方包够不够得着，并写入审计",
            category="健康", tags=("deps", "tools", "runtime", "selfcheck", "audit"))
def run(ctx: dict) -> Result:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import health as probe   # 原 probe.py 已并入 health.py（探测项/汇总/审计均在此）

    strict = bool((ctx or {}).get("strict"))
    findings = probe.probe_run()
    healthy, errors, warns = probe.summarize(findings, strict=strict)
    probe.probe_record_to_audit(findings)   # 探测结果固化进审计，供回放/失败分流

    if healthy:
        summary = f"{len(findings)} 项探测通过" + (f"（{warns} 处提醒）" if warns else "")
    else:
        bad = [f.label for f in findings if not f.passed]
        summary = f"{errors} 处缺失：{', '.join(bad)}"

    detail_lines = []
    for f in findings:
        line = f"{probe._MARK[f.level]} {f.label}" + (f" — {f.detail}" if f.detail else "")
        if f.fix:
            line += f"\n    ↳ 修复：{f.fix}"
        detail_lines.append(line)

    return Result(ok=healthy, summary=summary, detail="\n".join(detail_lines),
                  data={"healthy": healthy, "errors": errors, "warns": warns,
                        "findings": [f.to_meta() for f in findings]})
