"""自治分数校准：对比自治预判、审计外援与真实落地，产出过度自信样本"""

import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from jsonlstore import JsonlStore


class AutonomyCalibration:
    """自治分数校准器，用于检测过度自信的自治判断"""

    def __init__(self, store: JsonlStore):
        self.store = store
        self.confidence_threshold = 0.7  # 自治预判阈值
        self.outcome_threshold = 0.5     # 真实落地阈值（低于此值视为失败）

    def extract_recent_modifications(self, days: int = 30, limit: int = 20) -> List[Dict[str, Any]]:
        """提取近N天的自改记录"""
        cutoff = datetime.now() - timedelta(days=days)
        
        # 从存储中读取记录
        records = []
        for record in self.store.read_all():
            try:
                # 尝试解析记录中的时间
                if 'timestamp' in record:
                    record_time = datetime.fromisoformat(record['timestamp'])
                    if record_time >= cutoff:
                        records.append(record)
                else:
                    # 没有时间戳的记录也纳入
                    records.append(record)
            except (ValueError, KeyError):
                continue
        
        # 按时间排序并取最近的记录
        records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return records[:limit]

    def analyze_modification(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """分析单条自改记录，提取关键指标"""
        result = {
            'id': record.get('id', 'unknown'),
            'timestamp': record.get('timestamp', 'unknown'),
            'description': record.get('description', ''),
        }
        
        # 提取自治预判分数
        autonomy_data = record.get('autonomy', {})
        result['autonomy_score'] = autonomy_data.get('score', 0.0)
        result['autonomy_reasoning'] = autonomy_data.get('reasoning', '')
        
        # 提取审计外援信息
        audit_data = record.get('audit', {})
        result['audit_external'] = audit_data.get('external_used', False)
        result['audit_recommendation'] = audit_data.get('recommendation', '')
        
        # 提取真实落地结果
        outcome_data = record.get('outcome', {})
        result['outcome_score'] = outcome_data.get('score', 0.0)
        result['outcome_details'] = outcome_data.get('details', '')
        
        # 计算是否过度自信
        result['overconfident'] = self._is_overconfident(
            result['autonomy_score'],
            result['audit_external'],
            result['outcome_score']
        )
        
        return result

    def _is_overconfident(self, autonomy_score: float, 
                         audit_external: bool, outcome_score: float) -> bool:
        """判断是否过度自信"""
        # 如果自治预判高，但没有使用审计外援，且落地效果差，则为过度自信
        return (autonomy_score >= self.confidence_threshold and 
                not audit_external and 
                outcome_score < self.outcome_threshold)

    def calibrate(self) -> Dict[str, Any]:
        """执行校准，返回分析结果"""
        recent_mods = self.extract_recent_modifications()
        analyzed = []
        overconfident_samples = []
        
        for record in recent_mods:
            analysis = self.analyze_modification(record)
            analyzed.append(analysis)
            
            if analysis['overconfident']:
                overconfident_samples.append(analysis)
        
        # 计算统计信息
        stats = {
            'total_analyzed': len(analyzed),
            'overconfident_count': len(overconfident_samples),
            'overconfident_rate': len(overconfident_samples) / len(analyzed) if analyzed else 0,
            'avg_autonomy_score': sum(a['autonomy_score'] for a in analyzed) / len(analyzed) if analyzed else 0,
            'avg_outcome_score': sum(a['outcome_score'] for a in analyzed) / len(analyzed) if analyzed else 0,
        }
        
        return {
            'analysis_timestamp': datetime.now().isoformat(),
            'samples': analyzed,
            'overconfident_samples': overconfident_samples,
            'statistics': stats,
            'recommendations': self._generate_recommendations(stats, overconfident_samples)
        }

    def _generate_recommendations(self, stats: Dict[str, Any], 
                                overconfident_samples: List[Dict[str, Any]]) -> List[str]:
        """生成改进建议"""
        recommendations = []
        
        if stats['overconfident_rate'] > 0.3:
            recommendations.append("自治判断过度自信率过高，需要增加审计外援调用")
        
        if stats['avg_autonomy_score'] > stats['avg_outcome_score'] + 0.2:
            recommendations.append("自治预判普遍高于实际效果，需校准自治计量器")
        
        # 分析过度自信样本的模式
        if overconfident_samples:
            common_patterns = self._find_common_patterns(overconfident_samples)
            if common_patterns:
                recommendations.append(f"常见过度自信模式: {common_patterns}")
        
        if not recommendations:
            recommendations.append("自治判断与落地效果基本一致，无需立即校准")
        
        return recommendations

    def _find_common_patterns(self, samples: List[Dict[str, Any]]) -> str:
        """分析过度自信样本的共同模式"""
        # 简单实现：统计常见描述关键词
        keywords = {}
        for sample in samples:
            desc = sample['description'].lower()
            for word in desc.split():
                if len(word) > 3:  # 忽略短词
                    keywords[word] = keywords.get(word, 0) + 1
        
        if keywords:
            top_keyword = max(keywords.items(), key=lambda x: x[1])[0]
            return f"涉及'{top_keyword}'的修改容易过度自信"
        return ""


def run_calibration(store_path: str = "data/records.jsonl") -> Dict[str, Any]:
    """运行校准的便捷函数"""
    store = JsonlStore(store_path)
    calibrator = AutonomyCalibration(store)
    return calibrator.calibrate()


if __name__ == "__main__":
    # 测试运行
    result = run_calibration()
    print(f"校准完成，共分析 {result['statistics']['total_analyzed']} 条记录")
    print(f"过度自信样本: {result['statistics']['overconfident_count']} 条")
    print(f"过度自信率: {result['statistics']['overconfident_rate']:.1%}")
    print("建议:")
    for rec in result['recommendations']:
        print(f"- {rec}")
