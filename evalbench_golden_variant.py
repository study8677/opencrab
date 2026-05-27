"""
黄金任务变体回放模块
为 evalbench 热样本自动生成等价扰动并比对裁决，防止背题以确保真进步。
"""
import json
import random
import copy
from typing import List, Dict, Any, Optional

# 尝试导入 evalbench 模块，若不可用则提供默认接口
try:
    from evalbench import get_hot_samples, evaluate_sample, get_sample_by_id
except ImportError:
    # 默认实现：假设 evalbench 数据在 'evalbench_samples.json' 中
    import os
    
    _SAMPLE_FILE = 'evalbench_samples.json'
    _samples = []
    
    def _load_samples():
        global _samples
        if os.path.exists(_SAMPLE_FILE):
            with open(_SAMPLE_FILE, 'r', encoding='utf-8') as f:
                _samples = json.load(f)
    
    def get_hot_samples(count: int = 10) -> List[Dict[str, Any]]:
        """返回热样本列表（默认取前 count 个）"""
        if not _samples:
            _load_samples()
        return _samples[:count]
    
    def get_sample_by_id(sample_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取样本"""
        if not _samples:
            _load_samples()
        for sample in _samples:
            if sample.get('id') == sample_id:
                return sample
        return None
    
    def evaluate_sample(sample: Dict[str, Any]) -> Any:
        """评估样本并返回裁决（默认模拟返回随机数）"""
        # 模拟裁决：基于 input 长度生成随机浮点数
        input_text = sample.get('input', '')
        return random.uniform(0.0, 1.0) * len(input_text) % 10


def generate_perturbations(sample: Dict[str, Any], num_variants: int = 3) -> List[Dict[str, Any]]:
    """
    生成等价扰动变体。
    方法：在输入文本前添加不同前缀，并随机变换标点符号。
    """
    variants = []
    input_text = sample.get('input', '')
    
    # 前缀选项
    prefixes = [
        "请回答：",
        "回答以下问题：",
        "问题：",
        "解答：",
        ""  # 无前缀
    ]
    
    # 标点变换：替换或添加标点
    punctuation_map = {
        '？': '?',
        '！': '!',
        '，': ',',
        '。': '.',
        '：': ':',
    }
    
    for i in range(num_variants):
        variant = copy.deepcopy(sample)
        
        # 随机选择前缀
        prefix = random.choice(prefixes)
        new_input = prefix + input_text
        
        # 随机变换标点：以 30% 概率替换一个标点
        if random.random() < 0.3:
            for punct, replacement in punctuation_map.items():
                if punct in new_input:
                    # 替换第一个出现的标点
                    new_input = new_input.replace(punct, replacement, 1)
                    break
        
        # 随机添加空格（以 20% 概率）
        if random.random() < 0.2:
            words = new_input.split()
            if len(words) > 1:
                idx = random.randint(0, len(words) - 1)
                words[idx] = words[idx] + ' '  # 添加尾部空格
                new_input = ' '.join(words)
        
        variant['input'] = new_input
        # 保留原始 ID 但添加后缀
        if 'id' in variant:
            variant['id'] = f"{variant['id']}_variant_{i}"
        variants.append(variant)
    
    return variants


def compare_judgments(original_judgment: Any, perturbed_judgments: List[Any], tolerance: float = 0.5) -> Dict[str, Any]:
    """
    比对裁决一致性。
    返回字典，包含一致性布尔值和详细比较结果。
    """
    results = {
        'consistent': False,
        'original': original_judgment,
        'perturbed': perturbed_judgments,
        'deviations': []
    }
    
    if original_judgment is None:
        return results
    
    # 处理数值型裁决
    if isinstance(original_judgment, (int, float)):
        consistent = True
        for judgment in perturbed_judgments:
            if judgment is None or not isinstance(judgment, (int, float)):
                consistent = False
                results['deviations'].append(None)
                continue
            deviation = abs(original_judgment - judgment)
            results['deviations'].append(deviation)
            if deviation > tolerance:
                consistent = False
        results['consistent'] = consistent
    
    # 处理字符串型裁决
    elif isinstance(original_judgment, str):
        # 简单字符串比较（忽略大小写和空格）
        normalized_original = original_judgment.strip().lower()
        consistent = True
        for judgment in perturbed_judgments:
            if judgment is None or not isinstance(judgment, str):
                consistent = False
                results['deviations'].append(None)
                continue
            normalized_perturbed = judgment.strip().lower()
            deviation = 0 if normalized_original == normalized_perturbed else 1
            results['deviations'].append(deviation)
            if deviation > 0:
                consistent = False
        results['consistent'] = consistent
    
    # 其他类型：直接相等比较
    else:
        consistent = all(original_judgment == judgment for judgment in perturbed_judgments)
        results['consistent'] = consistent
        results['deviations'] = [original_judgment != judgment for judgment in perturbed_judgments]
    
    return results


def golden_task_variant_replay(sample_ids: Optional[List[str]] = None, num_variants: int = 3) -> List[Dict[str, Any]]:
    """
    执行黄金任务变体回放。
    如果提供 sample_ids，则只处理指定样本；否则处理所有热样本。
    返回每个样本的比对结果。
    """
    if sample_ids:
        samples = [get_sample_by_id(sid) for sid in sample_ids]
        samples = [s for s in samples if s is not None]  # 过滤无效
    else:
        samples = get_hot_samples()
    
    all_results = []
    for sample in samples:
        original_judgment = sample.get('judgment', None)
        if original_judgment is None:
            # 如果无裁决，尝试评估原始样本
            original_judgment = evaluate_sample(sample)
        
        variants = generate_perturbations(sample, num_variants)
        perturbed_judgments = []
        for variant in variants:
            judgment = evaluate_sample(variant)
            perturbed_judgments.append(judgment)
        
        comparison = compare_judgments(original_judgment, perturbed_judgments)
        
        result = {
            'sample_id': sample.get('id'),
            'original_input': sample.get('input', ''),
            'original_judgment': original_judgment,
            'perturbed_judgments': perturbed_judgments,
            'comparison': comparison,
            'consistent': comparison['consistent']
        }
        all_results.append(result)
    
    return all_results


def report_inconsistencies(results: List[Dict[str, Any]], threshold: float = 0.5) -> List[Dict[str, Any]]:
    """
    报告不一致的样本（潜在背题风险）。
    threshold 用于数值型偏差。
    """
    inconsistent = []
    for result in results:
        if not result['consistent']:
            inconsistent.append(result)
    return inconsistent


# 主函数入口
if __name__ == '__main__':
    # 示例：执行回放并输出结果
    print("执行黄金任务变体回放...")
    replay_results = golden_task_variant_replay(num_variants=2)
    
    # 统计
    total = len(replay_results)
    consistent_count = sum(1 for r in replay_results if r['consistent'])
    print(f"总样本数: {total}, 一致样本数: {consistent_count}, 不一致样本数: {total - consistent_count}")
    
    # 报告不一致
    inconsistencies = report_inconsistencies(replay_results)
    if inconsistencies:
        print("\n不一致样本（潜在背题风险）:")
        for inc in inconsistencies[:3]:  # 只显示前 3 个
            print(f"  ID: {inc['sample_id']}")
            print(f"    原始裁决: {inc['original_judgment']}")
            print(f"    扰动裁决: {inc['perturbed_judgments']}")
    
    # 保存结果到文件
    output_file = 'golden_variant_replay_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(replay_results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存至 {output_file}")
