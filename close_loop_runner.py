#!/usr/bin/env python3
"""
闭环进化运行器 - 提供简单的命令行接口
支持单次运行、连续监控和历史查看
"""
import argparse
import time
from close_loop import main as run_close_loop

def continuous_monitor(interval_minutes=60):
    """连续监控模式"""
    print(f"🔄 启动连续监控模式，每 {interval_minutes} 分钟运行一次闭环")
    
    iteration = 0
    while True:
        iteration += 1
        print(f"\n{'='*60}")
        print(f"📅 第 {iteration} 次闭环进化 - {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        try:
            success = run_close_loop()
            
            if success:
                print(f"✅ 第 {iteration} 次闭环成功")
            else:
                print(f"⚠️  第 {iteration} 次闭环完成，但未观察到提升")
                
        except KeyboardInterrupt:
            print("\n\n🛑 用户中断，停止监控")
            break
        except Exception as e:
            print(f"❌ 第 {iteration} 次闭环异常: {e}")
        
        # 等待下一次运行
        print(f"\n⏳ 等待 {interval_minutes} 分钟后进行下一次闭环...")
        try:
            time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            print("\n\n🛑 用户中断，停止监控")
            break

def view_history():
    """查看历史结果"""
    import json
    from pathlib import Path
    
    evidence_path = Path("evidence/close_loop_results.jsonl")
    
    if not evidence_path.exists():
        print("📭 没有找到历史记录")
        return
    
    print("📊 历史闭环进化记录:")
    print("-" * 80)
    
    records = []
    with open(evidence_path, "r") as f:
        for line in f:
            try:
                record = json.loads(line.strip())
                records.append(record)
            except:
                continue
    
    if not records:
        print("📭 没有有效记录")
        return
    
    # 显示统计
    total = len(records)
    successful = sum(1 for r in records if r.get('success'))
    avg_improvement = sum(r.get('improvement', 0) for r in records) / total
    
    print(f"总运行次数: {total}")
    print(f"成功次数: {successful} ({successful/total*100:.1f}%)")
    print(f"平均改善幅度: {avg_improvement:+.4f}")
    print("-" * 80)
    
    # 显示最近5次
    print("\n最近5次运行:")
    for record in records[-5:]:
        status = "✅" if record.get('success') else "⚠️"
        timestamp = record.get('timestamp', 'N/A')[:19]
        improvement = record.get('improvement', 0)
        weakness = record.get('weakness_targeted', 'N/A')
        
        print(f"{status} {timestamp} | 改善: {improvement:+.3f} | 弱点: {weakness}")

def main():
    parser = argparse.ArgumentParser(description='闭环进化运行器')
    parser.add_argument('--mode', choices=['single', 'monitor', 'history'], 
                       default='single', help='运行模式')
    parser.add_argument('--interval', type=int, default=60,
                       help='监控模式下的间隔时间（分钟）')
    
    args = parser.parse_args()
    
    if args.mode == 'single':
        success = run_close_loop()
        exit(0 if success else 1)
    elif args.mode == 'monitor':
        continuous_monitor(args.interval)
    elif args.mode == 'history':
        view_history()

if __name__ == "__main__":
    main()
