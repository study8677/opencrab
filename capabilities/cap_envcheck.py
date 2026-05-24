"""能力 · 配置与环境一致性 🔧 —— 复用 envcheck.py，启动前确认运行条件对齐。

和 `cap_checkup`(宽口径体检)分工：这里只盯「配置与环境的一致性」一件事——
.env 与范本是否对齐、数值/枚举填得对不对、本机依赖版本符不符合约定，
并给每条不一致一句可操作的修复建议。
"""
from __future__ import annotations

import pathlib
import sys

from . import Result, capability

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@capability("envcheck", "校验配置与环境一致性：.env 对齐、取值合法、依赖版本匹配",
            category="健康", tags=("config", "env", "integrity", "selfcheck"))
def run(ctx: dict) -> Result:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import envcheck

    strict = bool((ctx or {}).get("strict"))
    findings = envcheck.run()
    healthy, errors, warns = envcheck.summarize(findings, strict=strict)

    if healthy:
        summary = f"{len(findings)} 项校验通过" + (f"（{warns} 处提醒）" if warns else "")
    else:
        bad = [f.label for f in findings if not f.passed]
        summary = f"{errors} 处不一致：{', '.join(bad)}"

    detail_lines = []
    for f in findings:
        mark = envcheck._MARK[f.level]
        line = f"{mark} {f.label}" + (f" — {f.detail}" if f.detail else "")
        if f.fix:
            line += f"\n    ↳ 修复：{f.fix}"
        detail_lines.append(line)

    return Result(ok=healthy, summary=summary, detail="\n".join(detail_lines),
                  data={"healthy": healthy, "errors": errors, "warns": warns,
                        "findings": [f.to_meta() for f in findings]})
