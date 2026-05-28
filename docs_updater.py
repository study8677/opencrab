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

def count_log_entries():
    """统计 jsonlstore.py 中的条目数（假设日志存储在此）。"""
    try:
        # 尝试导入 jsonlstore 模块来统计
        import jsonlstore
        store = jsonlstore.JsonlStore()
        return len(store)
    except:
        # 如果无法导入，则统计 .jsonl 文件的行数
        here = Path(__file__).parent
        total = 0
        for f in here.glob("*.jsonl"):
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    total += sum(1 for _ in file)
            except:
                continue
        return total

def count_recent_commits(days=30):
    """统计最近N天的提交（通过 git log）。"""
    try:
        import subprocess
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        
        result = subprocess.run(
            ['git', 'log', f'--since={cutoff_str}', '--oneline'],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent
        )
        
        if result.returncode == 0:
            return len(result.stdout.strip().split('\n'))
        else:
            return 0
    except:
        return 0

def generate_update_timestamp():
    """生成当前更新时间戳。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def update_index_html(module_count, log_count, commit_count, timestamp):
    """更新 docs/index.html 中的关键数字。"""
    index_path = Path(__file__).parent / 'docs' / 'index.html'
    if not index_path.exists():
        print(f"警告：{index_path} 不存在，跳过更新。")
        return False

    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 替换模块数量（处理两种可能的格式）
    content = re.sub(
        r'(<span id="module-count">)\d+(</span>)',
        rf'\g<1>{module_count}\g<2>',
        content
    )
    content = re.sub(
        r'(\d+)\s*(modules)',
        rf'{module_count} \2',
        content,
        flags=re.IGNORECASE
    )
    
    # 替换日志记录数量
    content = re.sub(
        r'(<span id="log-count">)\d+(</span>)',
        rf'\g<1>{log_count}\g<2>',
        content
    )
    
    # 替换最近提交数量
    content = re.sub(
        r'(<span id="recent-commits">)\d+(</span>)',
        rf'\g<1>{commit_count}\g<2>',
        content
    )
    
    # 替换更新时间戳
    content = re.sub(
        r'(<span id="timestamp">)[^<]*(</span>)',
        rf'\g<1>{timestamp}\g<2>',
        content
    )
    
    # 添加最后更新时间到页面底部
    footer_pattern = r'(</body>)'
    footer_content = f'\n    <!-- 最后更新: {timestamp} -->\n\\1'
    content = re.sub(footer_pattern, footer_content, content)

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"已更新 {index_path}")
    return True

def main():
    """CLI 入口：计算并更新文档页。"""
    import argparse
    parser = argparse.ArgumentParser(description="更新文档页面")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际更新")
    args = parser.parse_args()
    
    # 尝试从 showcase_data.json 读取最新数据
    showcase_data = None
    try:
        with open("docs/showcase_data.json", "r") as f:
            showcase_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    
    # 如果 showcase_data.json 存在且包含需要的数据，优先使用
    if showcase_data and all(k in showcase_data for k in ["modules", "skillgraph_entries"]):
        module_count = showcase_data["modules"]
        # 这里 milestone_count 暂时还是用原来的统计方式，因为 showcase_data 里没有这个字段
        milestone_count = count_recent_milestones()
        # 使用 showcase_data 的刷新时间作为时间戳
        timestamp = showcase_data.get("refresh_time", generate_update_timestamp())
        print("✅ 使用 showcase_data.json 的最新数据")
    else:
        # 回退到独立统计
        module_count = count_modules()
        milestone_count = count_recent_milestones()
        timestamp = generate_update_timestamp()
        print("⚠️  使用独立统计数据（未找到有效的 showcase_data.json）")
    
    print(f"模块数量: {module_count}")
    print(f"近期里程碑 (30天): {milestone_count}")
    print(f"更新时间: {timestamp}")
    
    if args.dry_run:
        print("🔍 预览模式，不实际更新页面")
        return 0
    
    success = update_index_html(module_count, milestone_count, timestamp)
    return 0 if success else 1

if __name__ == '__main__':
    sys.exit(main())
