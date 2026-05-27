"""橱窗自动刷新器：每拍生成展示数据并记录证据。"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

# 复用现有模块
try:
    from crab import stat  # 用于统计模块数、提交数
except ImportError:
    stat = None  # 若 stat 模块不存在则降级

try:
    from crab import evidence  # 用于记录刷新证据
except ImportError:
    evidence = None

try:
    from crab import skillgraph  # 用于获取技能图谱条目数
except ImportError:
    skillgraph = None


def _count_modules() -> int:
    """统计仓库中的 .py 模块数（简单实现，可替换为更精确的统计）。"""
    root = Path(__file__).parent
    return len(list(root.glob("*.py")))


def _count_commits() -> int:
    """统计 git 提交数（简化版，实际应调用 git）。"""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, cwd=Path(__file__).parent
        )
        return int(result.stdout.strip())
    except Exception:
        return 0


def _count_skillgraph_entries() -> int:
    """统计技能图谱条目数。"""
    if skillgraph is not None and hasattr(skillgraph, "count"):
        return skillgraph.count()
    return 0


def refresh_showcase(
    output_path: str = "docs/showcase_data.json",
    evidence_path: str = "evidence/account.jsonl"
) -> Dict[str, Any]:
    """
    刷新橱窗数据：
    1. 收集当前统计信息
    2. 写入 JSON 文件供前端渲染
    3. 记录刷新证据（时间和差异）
    
    返回本次生成的数据字典。
    """
    # 收集数据
    modules_count = _count_modules()
    commits_count = _count_commits()
    skillgraph_count = _count_skillgraph_entries()
    refresh_time = datetime.now(timezone.utc).isoformat()
    
    data = {
        "refresh_time": refresh_time,
        "modules": modules_count,
        "commits": commits_count,
        "skillgraph_entries": skillgraph_count,
        "source": "showcase_refresher"
    }
    
    # 读取上次数据以计算差异
    diff = {}
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            prev_data = json.load(f)
            for key in ["modules", "commits", "skillgraph_entries"]:
                if key in prev_data:
                    diff[key] = data[key] - prev_data[key]
    except (FileNotFoundError, json.JSONDecodeError):
        pass  # 首次运行，无历史数据
    
    # 写入 JSON 文件
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # 记录证据
    evidence_entry = {
        "type": "showcase_refresh",
        "timestamp": refresh_time,
        "data": data,
        "diff": diff,
        "message": f"橱窗刷新完成，模块数 {modules_count}，提交数 {commits_count}，技能图谱条目 {skillgraph_count}"
    }
    
    if evidence is not None and hasattr(evidence, "append"):
        evidence.append(evidence_entry)
    else:
        # 降级：直接追加到文件
        try:
            with open(evidence_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(evidence_entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 证据写入失败不影响主流程
    
    return data


def main():
    """命令行入口：运行一次刷新并打印结果。"""
    data = refresh_showcase()
    print(f"橱窗数据已刷新：{json.dumps(data, indent=2, ensure_ascii=False)}")
    
    # 展示页已由 refresh_showcase() 直接生成并更新


if __name__ == "__main__":
    main()
