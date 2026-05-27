"""让 showcase_freshness_gate 能触发实际刷新。"""

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
