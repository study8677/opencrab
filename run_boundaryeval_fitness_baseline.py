#!/usr/bin/env python3
"""
为 boundaryeval 建立真实 fitness 基线
brain-only → 3闸 → 3x → 焊 循环的第一步
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

def run_arena_eval():
    """运行 arena 评估获取当前 fitness"""
    # 尝试用 evalbench
    try:
        from evalbench import evaluate
        result = evaluate('boundaryeval')
        return result
    except ImportError:
        pass
    
    # 备选：直接跑 boundaryeval.py
    result = subprocess.run(
        [sys.executable, 'boundaryeval.py'],
        capture_output=True,
        text=True,
        timeout=60
    )
    return {
        'stdout': result.stdout,
        'stderr': result.stderr,
        'returncode': result.returncode
    }

def create_baseline(target='boundaryeval'):
    """创建基线数据"""
    project_dir = Path(f'projects/{target}')
    project_dir.mkdir(parents=True, exist_ok=True)
    
    fitness_file = project_dir / 'fitness.json'
    
    # 检查现有数据
    existing = {}
    if fitness_file.exists():
        existing = json.loads(fitness_file.read_text())
    
    # 运行评估
    eval_result = run_arena_eval()
    
    # 解析得分
    scores = {}
    if isinstance(eval_result, dict):
        if 'scores' in eval_result:
            scores = eval_result['scores']
        elif 'stdout' in eval_result:
            # 尝试从 stdout 解析
            try:
                import re
                score_matches = re.findall(r'score[:\s]+([0-9.]+)', eval_result['stdout'], re.I)
                if score_matches:
                    scores['default'] = float(score_matches[0])
            except:
                pass
    
    # 构建基线记录
    baseline = {
        'target': target,
        'timestamp': datetime.now().isoformat(),
        'phase': 'brain_only_baseline',
        'scores': scores,
        'brain_only': scores.get('default', scores.get('main', 0)),
        'eval_result': str(eval_result)[:500] if eval_result else None,
        'regression_tests': [],
        'evolution_history': []
    }
    
    # 合并现有数据
    if existing:
        baseline['evolution_history'] = existing.get('evolution_history', [])
        baseline['regression_tests'] = existing.get('regression_tests', [])
    
    baseline['evolution_history'].append({
        'phase': 'brain_only_baseline',
        'timestamp': baseline['timestamp'],
        'scores': scores
    })
    
    fitness_file.write_text(json.dumps(baseline, indent=2))
    print(f"✓ 基线已写入 projects/{target}/fitness.json")
    print(f"  brain_only score: {baseline['brain_only']}")
    print(f"  scores: {scores}")
    
    return baseline

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'boundaryeval'
    create_baseline(target)
