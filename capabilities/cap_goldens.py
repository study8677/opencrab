"""能力 · 回归快照 🧪 —— 复用 goldens.py，比对关键命令的行为有没有悄悄退化。"""
from __future__ import annotations

import pathlib
import sys

from . import Result, capability

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@capability("goldens", "回归比对：关键命令的输出/退出码与黄金样本是否一致",
            category="健康", tags=("regression", "golden", "behavior"))
def run(ctx: dict) -> Result:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import goldens

    v = goldens.verify()
    if v.ok:
        summary = f"{len(v.passed)}/{v.total} 条用例无回归"
    else:
        parts = []
        if v.regressed:
            parts.append(f"{len(v.regressed)} 回归：{', '.join(v.regressed)}")
        if v.missing:
            parts.append(f"{len(v.missing)} 未录：{', '.join(v.missing)}")
        summary = "；".join(parts)
    detail_lines = []
    for name in v.regressed:
        detail_lines.append(f"❌ {name}")
        detail_lines += ["   " + ln for ln in v.diffs.get(name, [])]
    return Result(ok=v.ok, summary=summary, detail="\n".join(detail_lines),
                  data={"regressed": v.regressed, "missing": v.missing})
