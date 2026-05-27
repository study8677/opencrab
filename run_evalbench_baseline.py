#!/usr/bin/env python3
"""
运行 evalbench 黄金任务全集，获取当前基线分数。
用于验证近期基础设施改进是否带来实际效能提升。
"""

import subprocess
import sys
import time
import json
from pathlib import Path

def run_evalbench():
    """运行 evalbench.py 并捕获输出"""
    start_time = time.time()
    
    try:
        # 运行 evalbench.py 的黄金任务集
        result = subprocess.run(
            [sys.executable, "evalbench.py", "--suite", "golden"],
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )
        
        elapsed = time.time() - start_time
        
        # 解析结果
        if result.returncode == 0:
            try:
                output = result.stdout.strip()
                # 尝试解析 JSON 格式的分数
                if output.startswith('{'):
                    scores = json.loads(output)
                    return {
                        "status": "success",
                        "scores": scores,
                        "elapsed_seconds": elapsed,
                        "raw_output": output
                    }
                else:
                    # 尝试从文本中提取分数
                    return {
                        "status": "success",
                        "raw_output": output,
                        "elapsed_seconds": elapsed
                    }
            except json.JSONDecodeError:
                return {
                    "status": "success",
                    "raw_output": result.stdout,
                    "elapsed_seconds": elapsed
                }
        else:
            return {
                "status": "error",
                "error": result.stderr,
                "stdout": result.stdout,
                "returncode": result.returncode,
                "elapsed_seconds": elapsed
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "elapsed_seconds": 300
        }
    except Exception as e:
        return {
            "status": "exception",
            "error": str(e),
            "elapsed_seconds": time.time() - start_time
        }

def format_report(result):
    """格式化输出报告"""
    print("=" * 60)
    print("EVALBENCH 黄金任务全集 基线测试报告")
    print("=" * 60)
    
    status = result.get("status", "unknown")
    print(f"状态: {status.upper()}")
    
    if "elapsed_seconds" in result:
        print(f"耗时: {result['elapsed_seconds']:.2f} 秒")
    
    if status == "success":
        print("\n✅ 测试成功完成")
        
        # 如果有分数，显示分数
        if "scores" in result:
            scores = result["scores"]
            print("\n📊 分数详情:")
            if isinstance(scores, dict):
                for key, value in scores.items():
                    print(f"  {key}: {value}")
            else:
                print(f"  {scores}")
        
        # 显示部分原始输出
        if "raw_output" in result:
            output = result["raw_output"]
            if len(output) > 500:
                print(f"\n📝 原始输出 (前500字符):")
                print(output[:500] + "...")
            else:
                print(f"\n📝 原始输出:")
                print(output)
    
    elif status == "error":
        print(f"\n❌ 测试失败，返回码: {result.get('returncode', 'N/A')}")
        if "error" in result:
            print(f"错误信息: {result['error']}")
        if "stdout" in result:
            print(f"标准输出: {result['stdout']}")
    
    elif status == "timeout":
        print(f"\n⏰ 测试超时 (300秒)")
    
    elif status == "exception":
        print(f"\n💥 发生异常: {result.get('error', 'Unknown error')}")
    
    print("=" * 60)
    
    return status == "success"

def main():
    """主函数"""
    print("正在运行 evalbench 黄金任务全集...")
    result = run_evalbench()
    
    # 输出报告
    success = format_report(result)
    
    # 保存结果到文件
    output_file = Path("evalbench_baseline_result.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n结果已保存到: {output_file}")
    
    # 返回退出码
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
