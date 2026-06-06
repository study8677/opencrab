#!/usr/bin/env python3
"""
fitness_replication_protocol audit - 跑出 canary 75% 那 25% 失败案例的真实数据
不脑补下刀，让数据指给 form_intent 续旧
"""
import json
import subprocess
import sys
from pathlib import Path

def run_and_capture(cmd):
    """执行命令并捕获输出"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def load_fitness_json():
    """加载最新的 fitness 运行结果"""
    fit_dir = Path("fitness_runs")
    if not fit_dir.exists():
        return None
    
    runs = sorted(fit_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime)
    if not runs:
        return None
    
    with open(runs[-1]) as f:
        return json.load(f)

def run_replication_protocol():
    """运行完整的 fitness_replication_protocol"""
    print("=== 运行 fitness_replication_protocol ===")
    stdout, stderr, code = run_and_capture("python -c 'from fitness_replication_protocol import run_replication; run_replication()'")
    
    if code != 0:
        print(f"STDERR: {stderr}")
        return None
    
    print(stdout)
    return stdout

def find_canary_75_failures():
    """找出 canary 75% 中那 25% 的失败案例"""
    print("\n=== 扫描 canary_75 相关文件找失败案例 ===")
    
    failures = []
    
    # 1. 检查 fitness_replication_protocol 的输出
    result = run_replication_protocol()
    if result:
        # 找 "failed", "error", "regression" 关键词
        for line in result.split('\n'):
            if any(k in line.lower() for k in ['failed', 'error', 'regression', 'canary']):
                failures.append(("replication_protocol", line))
    
    # 2. 检查 canary_75 相关的运行日志
    canary_logs = list(Path(".").glob("*canary*75*log*")) + list(Path(".").glob("*canary*75*.log"))
    for log_file in canary_logs:
        try:
            with open(log_file) as f:
                content = f.read()
                for i, line in enumerate(content.split('\n')):
                    if any(k in line.lower() for k in ['failed', 'regression', '25%', 'unmatched']):
                        failures.append((str(log_file), f"L{i}: {line}"))
        except Exception as e:
            failures.append((str(log_file), f"读取失败: {e}"))
    
    # 3. 检查 fitness 状态文件
    fit_status = load_fitness_json()
    if fit_status:
        if 'canary_75' in fit_status:
            cs = fit_status['canary_75']
            if isinstance(cs, dict):
                if cs.get('status') == 'failed' or cs.get('status') == 'regression':
                    failures.append(("fitness_json.canary_75", str(cs)))
                if 'details' in cs:
                    failures.append(("fitness_json.canary_75.details", str(cs['details'])))
    
    # 4. 运行 canary_75 脚本找实际失败
    print("\n=== 直接运行 canary_75 检查 ===")
    stdout, stderr, code = run_and_capture("python -c 'from canary_75 import run; run()' 2>&1")
    if code != 0 or 'failed' in stdout.lower() or 'error' in stdout.lower():
        failures.append(("canary_75.run", stdout[:500]))
        if stderr:
            failures.append(("canary_75.run.stderr", stderr[:500]))
    
    # 5. 检查最近的 regression 结果
    print("\n=== 检查 regression 相关文件 ===")
    reg_files = list(Path(".").glob("*regression*result*")) + list(Path(".").glob("*regression*canary*"))
    for rf in reg_files:
        try:
            with open(rf) as f:
                content = f.read()
                if 'canary' in content.lower() or '75' in content:
                    failures.append((str(rf), content[:1000]))
        except:
            pass
    
    return failures

def extract_golden_tasks_from_failures(failures):
    """从失败案例中提取黄金任务"""
    print("\n=== 从失败案例提取黄金任务 ===")
    
    golden_tasks = []
    
    # 分析每个失败案例
    for source, detail in failures:
        # 提取任务标识
        if 'task' in detail.lower():
            # 找任务 ID 或名称
            import re
            task_ids = re.findall(r'task[_\-]?(\w+)', detail, re.IGNORECASE)
            for tid in task_ids:
                golden_tasks.append({
                    'task_id': tid,
                    'source': source,
                    'context': detail[:200]
                })
        
        # 找具体的 patch 或 intent 失败
        if 'intent' in detail.lower() or 'form_intent' in detail.lower():
            golden_tasks.append({
                'type': 'intent_failure',
                'source': source,
                'context': detail[:300]
            })
    
    return golden_tasks

def run_deep_canary_analysis():
    """深入分析 canary 75% 的问题"""
    print("\n=== 深度分析 canary_75 ===")
    
    results = {
        'canary_75_file_analysis': {},
        'import_test': {},
        'run_test': {},
        'golden_tasks': []
    }
    
    # 分析 canary_75.py
    canary_75_file = Path("canary_75.py")
    if canary_75_file.exists():
        with open(canary_75_file) as f:
            content = f.read()
        
        # 找关键函数和配置
        import re
        functions = re.findall(r'def (\w+)', content)
        results['canary_75_file_analysis']['functions'] = functions
        
        # 找配置参数
        config_patterns = [
            (r'fitness[:\s]+([0-9.]+)', 'fitness'),
            (r'ratio[:\s]+([0-9.]+)', 'ratio'),
            (r'threshold[:\s]+([0-9.]+)', 'threshold'),
        ]
        for pattern, name in config_patterns:
            matches = re.findall(pattern, content)
            if matches:
                results['canary_75_file_analysis'][name] = matches
    
    # 测试导入
    stdout, stderr, code = run_and_capture("python -c 'import canary_75; print(dir(canary_75))' 2>&1")
    if code == 0:
        results['import_test']['success'] = True
        results['import_test']['exports'] = stdout.strip()
    else:
        results['import_test']['success'] = False
        results['import_test']['error'] = stderr[:500]
    
    # 测试运行
    stdout, stderr, code = run_and_capture("timeout 30 python -c 'from canary_75 import run; run()' 2>&1")
    results['run_test']['returncode'] = code
    results['run_test']['stdout'] = stdout[:1000] if stdout else ""
    results['run_test']['stderr'] = stderr[:1000] if stderr else ""
    
    if code != 0:
        # 分析错误
        if 'form_intent' in stderr or 'form_intent' in stdout:
            results['form_intent_error'] = True
            # 提取相关行
            for line in (stderr + stdout).split('\n'):
                if 'form_intent' in line.lower():
                    results['golden_tasks'].append({
                        'type': 'form_intent_failure',
                        'line': line.strip()
                    })
    
    return results

def main():
    print("=" * 60)
    print("fitness_replication_protocol AUDIT")
    print("目标: 找出 canary 75% 那 25% 的失败案例真实数据")
    print("=" * 60)
    
    # 1. 先找失败案例
    failures = find_canary_75_failures()
    
    print("\n" + "=" * 60)
    print("FAILURES FOUND:")
    print("=" * 60)
    for source, detail in failures:
        print(f"\n[{source}]")
        print(detail)
    
    # 2. 深度分析
    deep_results = run_deep_canary_analysis()
    
    print("\n" + "=" * 60)
    print("DEEP ANALYSIS:")
    print("=" * 60)
    print(json.dumps(deep_results, indent=2, ensure_ascii=False))
    
    # 3. 提取黄金任务
    golden_tasks = extract_golden_tasks_from_failures(failures)
    golden_tasks.extend(deep_results.get('golden_tasks', []))
    
    print("\n" + "=" * 60)
    print("GOLDEN TASKS FOR form_intent TO RESUME:")
    print("=" * 60)
    print(json.dumps(golden_tasks, indent=2, ensure_ascii=False))
    
    # 4. 生成 form_intent 续旧所需的锚点数据
    anchor_data = {
        'audit_time': str(Path(__file__).stat().st_mtime),
        'failures_count': len(failures),
        'golden_tasks': golden_tasks,
        'deep_analysis': deep_results,
        'raw_failures': [(s, d[:500]) for s, d in failures]
    }
    
    # 保存锚点数据
    anchor_file = Path("form_intent_resume_anchors.json")
    with open(anchor_file, 'w') as f:
        json.dump(anchor_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n锚点数据已保存到: {anchor_file}")
    
    return anchor_data

if __name__ == "__main__":
    main()
