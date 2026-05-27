"""半自动更新 docs/index.html 展示页，确保数字与真实状态同步。"""

import os
import re
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
import importlib
import sys

# 确保 docs 目录存在
DOCS_DIR = Path(__file__).parent / 'docs'
DOCS_DIR.mkdir(exist_ok=True)

def count_modules(exclude_prefixes=('test_', 'setup')):
    """统计当前目录下的 .py 模块数量（排除测试文件等）。"""
    here = Path(__file__).parent
    count = 0
    for f in here.glob("*.py"):
        if any(f.name.startswith(p) for p in exclude_prefixes):
            continue
        if f.name == "__init__.py":
            continue
        count += 1
    return count

def count_recent_milestones(days=30):
    """尝试从 changelog.py 或 timeline.py 提取近 N 天的里程碑事件。"""
    # 简单启发：查找带有 date 或 timestamp 的行，假设格式类似 "YYYY-MM-DD"
    # 实际实现可能需要更精确的解析
    here = Path(__file__).parent
    milestones = []
    date_pattern = re.compile(r'\d{4}-\d{2}-\d{2}')
    cutoff = datetime.now() - timedelta(days=days)

    for source in ['changelog.py', 'timeline.py']:
        path = here / source
        if not path.exists():
            continue
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 提取所有日期并检查是否在窗口内
        for match in date_pattern.finditer(content):
            try:
                dt = datetime.strptime(match.group(), '%Y-%m-%d')
                if dt >= cutoff:
                    milestones.append(match.group())
            except ValueError:
                continue
    return len(set(milestones))  # 去重后计数

def generate_update_timestamp():
    """生成当前更新时间戳。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def update_index_html(module_count, milestone_count, timestamp):
    """更新 docs/index.html 中的关键数字。"""
    index_path = Path(__file__).parent / 'docs' / 'index.html'
    if not index_path.exists():
        print(f"警告：{index_path} 不存在，跳过更新。")
        return False

    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 替换模块数量
    content = re.sub(
        r'(<span id="module-count">)\d+(</span>)',
        rf'\g<1>{module_count}\g<2>',
        content
    )
    # 替换近期里程碑数量（假设也有类似标记）
    content = re.sub(
        r'(<span id="recent-milestones">)\d+(</span>)',
        rf'\g<1>{milestone_count}\g<2>',
        content
    )
    # 替换更新时间戳
    content = re.sub(
        r'(<span id="last-updated">)[^<]*(</span>)',
        rf'\g<1>{timestamp}\g<2>',
        content
    )

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"已更新 {index_path}")
    return True

def main():
    """CLI 入口：计算并更新文档页。"""
    module_count = count_modules()
    milestone_count = count_recent_milestones()
    timestamp = generate_update_timestamp()

    print(f"模块数量: {module_count}")
    print(f"近期里程碑 (30天): {milestone_count}")
    print(f"更新时间: {timestamp}")

    success = update_index_html(module_count, milestone_count, timestamp)
    return 0 if success else 1

if __name__ == '__main__':
    sys.exit(main())
