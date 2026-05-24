"""能力 · 自检 🪞 —— 复用领地的镜子 checkup.py，照一次健康。"""
from __future__ import annotations

import pathlib
import sys

from . import Result, capability

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@capability("checkup", "照镜子：关键文件、语法、导入、领地结构是否健康",
            category="健康", tags=("health", "integrity", "selfcheck"))
def run(ctx: dict) -> Result:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import checkup

    healthy, results = checkup.run()
    failed = [label for ok, label, _ in results if not ok]
    summary = (f"{len(results)} 项全部通过" if healthy
               else f"{len(failed)} 处未过：{', '.join(failed)}")
    detail = "\n".join(f"{'✅' if ok else '❌'} {label}"
                       + (f" — {d}" if d else "")
                       for ok, label, d in results)
    return Result(ok=healthy, summary=summary, detail=detail,
                  data={"healthy": healthy, "failed": failed})
