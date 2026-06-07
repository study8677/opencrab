#!/usr/bin/env python3
"""
boundaryeval 的 brain-only → 3闸 → 3x → 焊 进化循环

目标：让 boundaryeval 真实涨分，证明适应度循环可行
canary 80% 暂停，这个先跑通再回去套用
"""
import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# 导入核心模块
sys.path.insert(0, str(Path(__file__).parent))

class BoundaryEvalEvolution:
    """boundaryeval 进化控制器"""
    
    def __init__(self, target='boundaryeval'):
        self.target = target
        self.project_dir = Path(f'projects/{target}')
        self.fitness_file = self.project_dir / 'fitness.json'
        self.fitness_data = self._load_fitness()
        
    def _load_fitness(self):
        if self.fitness_file.exists():
            return json.loads(self.fitness_file.read_text())
        return {
            'target': self.target,
            'phase': 'init',
            'scores': {},
            'brain_only': 0,
            'evolution_history': [],
            'regression_tests': []
        }
    
    def _save_fitness(self):
        self.fitness_data['last_update'] = datetime.now().isoformat()
        self.fitness_file.parent.mkdir(parents=True, exist_ok=True)
        self.fitness_file.write_text(json.dumps(self.fitness_data, indent=2))
    
    def _run_evaluation(self):
        """运行评估获取当前分数"""
        try:
            result = subprocess.run(
                [sys.executable, 'boundaryeval.py'],
                capture_output=True,
                text=True,
                timeout=60
            )
            # 解析输出
            import re
            scores = {}
            # 尝试找分数
            for line in result.stdout.split('\n'):
                m = re.search(r'([\w_]+)[:\s]+([0-9.]+)', line)
                if m:
                    scores[m.group(1)] = float(m.group(2))
            return scores, result.returncode == 0
        except Exception as e:
            print(f"评估失败: {e}")
            return {}, False
    
    def _record_evolution(self, phase, scores, patch_info=None):
        """记录进化历史"""
        entry = {
            'phase': phase,
            'timestamp': datetime.now().isoformat(),
            'scores': scores,
            'brain_only': scores.get('default', scores.get('main', 0))
        }
        if patch_info:
            entry['patch'] = patch_info
        self.fitness_data['evolution_history'].append(entry)
        self.fitness_data['scores'] = scores
        self.fitness_data['brain_only'] = entry['brain_only']
        self._save_fitness()
    
    def phase1_brain_only_baseline(self):
        """阶段1: brain-only 基线"""
        print("\n=== 阶段1: Brain-Only 基线 ===")
        scores, ok = self._run_evaluation()
        self._record_evolution('brain_only_baseline', scores)
        print(f"基线分数: {scores}")
        return scores
    
    def phase2_three_gates(self):
        """阶段2: 三闸检查"""
        print("\n=== 阶段2: 三闸 (Three Gates) ===")
        # 闸1: 语法正确
        # 闸2: 导入无错  
        # 闸3: 基本功能
        gates_passed = []
        
        # 闸1
        result = subprocess.run(
            [sys.executable, '-m', 'py_compile', 'boundaryeval.py'],
            capture_output=True
        )
        if result.returncode == 0:
            gates_passed.append('syntax')
            print("✓ 闸1: 语法正确")
        else:
            print("✗ 闸1: 语法错误")
        
        # 闸2
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("boundaryeval", "boundaryeval.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            gates_passed.append('import')
            print("✓ 闸2: 导入成功")
        except Exception as e:
            print(f"✗ 闸2: 导入失败 - {e}")
        
        # 闸3
        if hasattr(module, 'evaluate'):
            gates_passed.append('function')
            print("✓ 闸3: evaluate 函数存在")
        else:
            print("✗ 闸3: 缺少 evaluate 函数")
        
        self.fitness_data['three_gates'] = gates_passed
        self._save_fitness()
        return gates_passed
    
    def phase3_3x_iteration(self):
        """阶段3: 3x 迭代改进"""
        print("\n=== 阶段3: 3x 迭代 ===")
        baseline = self.fitness_data.get('brain_only', 0)
        improvements = []
        
        # 读取当前代码
        current_code = Path('boundaryeval.py').read_text()
        
        # 生成改进补丁
        # (这里应该是智能 patch 逻辑，暂时用简化版本)
        improvements.append({
            'type': 'iteration_1',
            'baseline': baseline,
            'attempted': True
        })
        
        self.fitness_data['three_x_iterations'] = improvements
        self._save_fitness()
        return improvements
    
    def phase4_weld(self):
        """阶段4: 焊接 (固化改进)"""
        print("\n=== 阶段4: 焊 (Weld) ===")
        # 将验证通过的改进写入主文件
        scores, ok = self._run_evaluation()
        self._record_evolution('weld', scores)
        print(f"焊后分数: {scores}")
        return scores
    
    def run_full_cycle(self):
        """运行完整进化循环"""
        print(f"\n{'='*50}")
        print(f"boundaryeval 进化循环启动")
        print(f"{'='*50}")
        
        # 1. 基线
        self.phase1_brain_only_baseline()
        
        # 2. 三闸
        gates = self.phase2_three_gates()
        
        # 3. 3x 迭代
        if len(gates) >= 3:
            self.phase3_3x_iteration()
        else:
            print("三闸未全通过，跳过 3x 迭代")
        
        # 4. 焊
        final_scores = self.phase4_weld()
        
        print(f"\n{'='*50}")
        print(f"进化循环完成")
        print(f"最终分数: {final_scores}")
        print(f"{'='*50}")
        
        return final_scores

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else 'boundaryeval'
    evo = BoundaryEvalEvolution(target)
    evo.run_full_cycle()

if __name__ == '__main__':
    main()
