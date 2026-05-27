"""
recurrence_gate – 从尸检报告中提取重复根因，防止再次踩坑。
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

from autopsy import load_autopsies  # 导入 autopsy 模块的加载函数


def extract_recurring_causes(autopsy_dir: str = "autopsy_logs") -> dict:
    """
    从尸检报告目录中提取重复出现的根因。
    返回 {root_cause: count} 字典，按频率降序排列。
    """
    autopsies = load_autopsies(autopsy_dir)
    
    # 统计每个 root_cause 的出现次数
    cause_counter = Counter()
    for autopsy in autopsies:
        # 假设每个 autopsy 记录有 "root_cause" 字段
        root_cause = autopsy.get("root_cause")
        if root_cause:
            cause_counter[root_cause] += 1
    
    # 只保留出现次数 >1 的根因（重复）
    recurring = {cause: count for cause, count in cause_counter.items() if count > 1}
    return dict(sorted(recurring.items(), key=lambda x: x[1], reverse=True))


def save_recurrence_report(recurring: dict, output_file: str = "recurrence_report.json"):
    """将重复根因报告保存为 JSON 文件。"""
    with open(output_file, "w") as f:
        json.dump(recurring, f, indent=2)
    print(f"重复根因报告已保存到 {output_file}")


def main():
    """命令行入口：扫描尸检报告并输出重复根因。"""
    import argparse
    
    parser = argparse.ArgumentParser(description="提取尸检报告中的重复根因，防止再次踩坑。")
    parser.add_argument(
        "--autopsy-dir",
        default="autopsy_logs",
        help="尸检报告目录路径 (默认: autopsy_logs)"
    )
    parser.add_argument(
        "--output",
        default="recurrence_report.json",
        help="输出报告的文件路径 (默认: recurrence_report.json)"
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=2,
        help="视为重复的最小出现次数 (默认: 2)"
    )
    
    args = parser.parse_args()
    
    # 提取重复根因
    recurring = extract_recurring_causes(args.autopsy_dir)
    
    # 按 min_count 过滤
    filtered = {cause: count for cause, count in recurring.items() if count >= args.min_count}
    
    if not filtered:
        print("未发现重复根因。")
        return 0
    
    # 输出到控制台
    print("发现以下重复根因：")
    for cause, count in filtered.items():
        print(f"  {cause}: {count}次")
    
    # 保存报告
    save_recurrence_report(filtered, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
