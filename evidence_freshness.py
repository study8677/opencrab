"""
证据续航调度器：自动找出过期/低信任证据，按影响面排队重跑最小验证并更新账本
"""

import time
from typing import List, Dict, Any, Optional
from evidence import EvidenceStore
from trustscore import TrustScore
from calibration import EvidenceValidator

class EvidenceFreshnessScheduler:
    """
    证据续航调度器：保持证据新鲜，防止自我误判
    """
    
    def __init__(self,
                 evidence_store: Optional[EvidenceStore] = None,
                 trust_scorer: Optional[TrustScore] = None,
                 validator: Optional[EvidenceValidator] = None,
                 max_age: float = 86400,  # 默认最大年龄: 1天(秒)
                 min_trust: float = 0.7,  # 默认最低信任分
                 batch_size: int = 10):
        """
        Args:
            evidence_store: 证据存储实例
            trust_scorer: 信任评分器实例
            validator: 证据验证器实例
            max_age: 证据最大年龄(秒)
            min_trust: 最低信任分数阈值
            batch_size: 批量处理大小
        """
        self.evidence_store = evidence_store or EvidenceStore()
        self.trust_scorer = trust_scorer or TrustScore()
        self.validator = validator or EvidenceValidator()
        self.max_age = max_age
        self.min_trust = min_trust
        self.batch_size = batch_size
        
    def scan_stale_evidence(self) -> List[Dict[str, Any]]:
        """
        扫描过期/低信任证据
        
        Returns:
            需要更新的证据列表
        """
        current_time = time.time()
        all_evidence = self.evidence_store.get_all()
        
        stale_evidence = []
        for evidence in all_evidence:
            # 检查是否过期
            if self._is_expired(evidence, current_time):
                stale_evidence.append(evidence)
            # 检查信任分是否过低
            elif self._is_low_trust(evidence):
                stale_evidence.append(evidence)
        
        return stale_evidence
    
    def prioritize_evidence(self, stale_evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        按影响面排序证据（高影响面优先）
        
        Args:
            stale_evidence: 需要更新的证据列表
            
        Returns:
            按影响面排序的证据列表
        """
        return sorted(stale_evidence, 
                      key=lambda e: self._calculate_impact(e), 
                      reverse=True)
    
    def refresh_evidence(self, evidence_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        重跑最小验证并更新账本
        
        Args:
            evidence_list: 按优先级排序的证据列表
            
        Returns:
            更新统计信息
        """
        stats = {
            "total_processed": 0,
            "refreshed": 0,
            "removed": 0,
            "failed": 0,
            "start_time": time.time()
        }
        
        batch = evidence_list[:self.batch_size]
        for evidence in batch:
            try:
                stats["total_processed"] += 1
                
                # 重跑最小验证
                new_evidence = self._run_minimum_verification(evidence)
                
                if new_evidence:
                    # 更新证据存储
                    self.evidence_store.update(new_evidence)
                    stats["refreshed"] += 1
                else:
                    # 验证失败，移除无效证据
                    self.evidence_store.remove(evidence["id"])
                    stats["removed"] += 1
                    
            except Exception as e:
                stats["failed"] += 1
                print(f"证据更新失败 {evidence.get('id')}: {str(e)}")
        
        stats["end_time"] = time.time()
        stats["duration"] = stats["end_time"] - stats["start_time"]
        
        return stats
    
    def run_refresh_cycle(self) -> Dict[str, Any]:
        """
        执行完整的证据刷新周期
        
        Returns:
            刷新统计信息
        """
        # 1. 扫描过期/低信任证据
        stale_evidence = self.scan_stale_evidence()
        
        if not stale_evidence:
            return {"status": "no_stale_evidence", "message": "所有证据都是新鲜的"}
        
        # 2. 按影响面排序
        prioritized = self.prioritize_evidence(stale_evidence)
        
        # 3. 刷新证据
        stats = self.refresh_evidence(prioritized)
        
        # 4. 记录调度器活动
        self._log_activity(stats)
        
        return stats
    
    def _is_expired(self, evidence: Dict[str, Any], current_time: float) -> bool:
        """检查证据是否过期"""
        if "last_verified" not in evidence:
            return True
        return (current_time - evidence["last_verified"]) > self.max_age
    
    def _is_low_trust(self, evidence: Dict[str, Any]) -> bool:
        """检查证据是否信任分过低"""
        if "trust_score" not in evidence:
            return True
        return evidence["trust_score"] < self.min_trust
    
    def _calculate_impact(self, evidence: Dict[str, Any]) -> float:
        """
        计算证据影响面
        考虑因素：引用次数、信任分衰减、关联证据数量
        """
        base_impact = evidence.get("references", 0) * 0.4
        
        # 信任分越低，影响面越大（需要优先处理）
        trust_impact = (1.0 - evidence.get("trust_score", 0.5)) * 0.3
        
        # 关联证据数量
        related_count = evidence.get("related_evidence", [])
        related_impact = len(related_count) * 0.3
        
        return base_impact + trust_impact + related_impact
    
    def _run_minimum_verification(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        重跑最小验证
        """
        try:
            # 使用验证器进行快速验证
            validation_result = self.validator.quick_validate(evidence)
            
            if validation_result["valid"]:
                # 更新证据字段
                evidence["last_verified"] = time.time()
                evidence["verification_count"] = evidence.get("verification_count", 0) + 1
                evidence["trust_score"] = validation_result["new_trust"]
                return evidence
            else:
                return None
                
        except Exception as e:
            print(f"验证过程出错: {str(e)}")
            return None
    
    def _log_activity(self, stats: Dict[str, Any]) -> None:
        """记录调度器活动"""
        log_entry = {
            "timestamp": time.time(),
            "activity": "evidence_refresh",
            "stats": stats
        }
        
        # 这里可以集成到现有的日志系统
        print(f"证据刷新完成: {stats['refreshed']}/{stats['total_processed']} 已更新")
    
    def get_freshness_report(self) -> Dict[str, Any]:
        """
        生成证据新鲜度报告
        
        Returns:
            包含新鲜度统计的字典
        """
        all_evidence = self.evidence_store.get_all()
        current_time = time.time()
        
        total = len(all_evidence)
        if total == 0:
            return {"total": 0, "fresh": 0, "stale": 0, "average_trust": 0}
        
        fresh = 0
        total_trust = 0
        
        for evidence in all_evidence:
            if not self._is_expired(evidence, current_time) and not self._is_low_trust(evidence):
                fresh += 1
            total_trust += evidence.get("trust_score", 0.5)
        
        return {
            "total": total,
            "fresh": fresh,
            "stale": total - fresh,
            "fresh_ratio": fresh / total,
            "average_trust": total_trust / total,
            "recommendation": "需要立即刷新" if (total - fresh) > total * 0.3 else "证据状态良好"
        }

# 便捷函数
def run_evidence_maintenance():
    """运行证据维护任务"""
    scheduler = EvidenceFreshnessScheduler()
    report = scheduler.get_freshness_report()
    
    if report["stale"] > 0:
        result = scheduler.run_refresh_cycle()
        return {"report": report, "refresh_result": result}
    else:
        return {"report": report, "message": "无需刷新"}
