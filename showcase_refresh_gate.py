"""Thin wrapper that triggers a full showcase refresh.

Runs showcase_refresher.py (to update JSON data) then showcase.py
(to regenerate HTML) in sequence. Used by freshness gate as the
action side of the check-then-refresh pattern.
"""

import subprocess
import sys
from pathlib import Path


def main():
    """运行 showcase_refresher.py 更新 showcase_data.json，然后更新 index.html。"""
    root = Path(__file__).parent

    # 1. 先更新 JSON 数据
    refresher = root / "showcase_refresher.py"
    if refresher.exists():
        subprocess.run([sys.executable, str(refresher)], cwd=root, check=True)

    # 2. 再更新 HTML 展示页
    showcase = root / "showcase.py"
    if showcase.exists():
        subprocess.run([sys.executable, str(showcase)], cwd=root, check=True)

    print("展示已刷新")


if __name__ == "__main__":
    main()
