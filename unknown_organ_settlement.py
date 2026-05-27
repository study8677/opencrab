"""
未知器官清账协调器：
1. 扫描所有模块，识别仍标记“?”的未知器官
2. 调用探针获取能力说明与最小证据
3. 低信任模块加入退役候选
"""
import logging
from typing import List, Dict, Optional

# 延迟导入避免循环依赖
_unknown_prober = None
_organ_registry = None
_trust_scorer = None
_retirement_gate = None

logger = logging.getLogger(__name__)

def _lazy_import():
    global _unknown_prober, _organ_registry, _trust_scorer, _retirement_gate
    if _unknown_prober is None:
        from . import unknown_organ_prober as _unknown_prober
        from . import organ_verification as _organ_registry
        from . import trustscore as _trust_scorer
        from . import retirementgate as _retirement_gate

def find_unknown_organs() -> List[str]:
    """返回所有当前能力标记为'?'的模块列表"""
    _lazy_import()
    unknown_modules = []
    
    # 遍历已知模块注册表
    if hasattr(_organ_registry, 'get_all_modules'):
        for module_name, metadata in _organ_registry.get_all_modules().items():
            capability = metadata.get('capability', '')
            if not capability or capability.strip() == '?':
                unknown_modules.append(module_name)
    
    return unknown_modules

def probe_and_evaluate(module_name: str) -> Dict[str, any]:
    """对单个未知模块运行探针，返回评估结果"""
    _lazy_import()
    
    result = {
        'module': module_name,
        'probe_success': False,
        'capability': '?',
        'evidence': None,
        'trust_score': 0.0,
        'retirement_candidate': False
    }
    
    try:
        # 调用探针获取能力说明
        if hasattr(_unknown_prober, 'probe_capability'):
            probe_result = _unknown_prober.probe_capability(module_name)
            if probe_result.get('success'):
                result['probe_success'] = True
                result['capability'] = probe_result.get('capability', '?')
                result['evidence'] = probe_result.get('evidence', None)
        
        # 计算信任分数
        if hasattr(_trust_scorer, 'calculate_trust_score'):
            trust_input = {
                'module': module_name,
                'capability': result['capability'],
                'evidence': result['evidence'],
                'probe_success': result['probe_success']
            }
            result['trust_score'] = _trust_scorer.calculate_trust_score(trust_input)
        
        # 判断是否为退役候选（信任分低于阈值）
        retirement_threshold = 0.3  # 可配置阈值
        if result['trust_score'] < retirement_threshold:
            result['retirement_candidate'] = True
            
    except Exception as e:
        logger.warning(f"探针运行失败 {module_name}: {e}")
        result['capability'] = '探针失败'
        result['trust_score'] = 0.0
        result['retirement_candidate'] = True
    
    return result

def settle_unknown_organs() -> Dict[str, any]:
    """执行完整的未知器官清账流程"""
    _lazy_import()
    
    settlement_report = {
        'scanned': 0,
        'resolved': 0,
        'retired_candidates': [],
        'remaining_unknown': []
    }
    
    unknown_modules = find_unknown_organs()
    settlement_report['scanned'] = len(unknown_modules)
    
    for module_name in unknown_modules:
        evaluation = probe_and_evaluate(module_name)
        
        # 更新模块注册表
        if hasattr(_organ_registry, 'update_module_capability'):
            update_data = {
                'capability': evaluation['capability'],
                'evidence': evaluation['evidence'],
                'trust_score': evaluation['trust_score'],
                'last_probed': True
            }
            _organ_registry.update_module_capability(module_name, update_data)
            
            if evaluation['probe_success'] and evaluation['capability'] != '?':
                settlement_report['resolved'] += 1
        
        # 登记退役候选
        if evaluation['retirement_candidate']:
            retirement_entry = {
                'module': module_name,
                'trust_score': evaluation['trust_score'],
                'capability': evaluation['capability'],
                'reason': '低信任未知器官'
            }
            settlement_report['retired_candidates'].append(retirement_entry)
            
            # 实际加入退役门
            if hasattr(_retirement_gate, 'add_candidate'):
                _retirement_gate.add_candidate(module_name, retirement_entry)
        
        # 记录仍为未知的模块
        if evaluation['capability'] == '?':
            settlement_report['remaining_unknown'].append(module_name)
    
    logger.info(f"未知器官清账完成: 扫描{settlement_report['scanned']}, 解析{settlement_report['resolved']}, "
                f"退役候选{len(settlement_report['retired_candidates'])}, 剩余未知{len(settlement_report['remaining_unknown'])}")
    
    return settlement_report

def auto_settle_unknowns():
    """自动执行清账的便捷入口"""
    try:
        return settle_unknown_organs()
    except Exception as e:
        logger.error(f"自动清账失败: {e}")
        return {'error': str(e)}
