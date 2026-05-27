# recurrence_gate.py: 从航海日志提取空转模式，生成planner禁忌卡并回放验证

import json
from collections import Counter
from typing import List, Dict, Any

# 假设日志存储在JSONL文件中，这里简单实现加载函数
def load_navlogs(file_path: str = "navlogs.jsonl") -> List[Dict[str, Any]]:
    """加载航海日志文件，返回日志条目列表"""
    logs = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))
    except FileNotFoundError:
        print(f"日志文件 {file_path} 未找到，返回空列表")
        return []
    return logs

def extract_idle_patterns(logs: List[Dict[str, Any]], top_n: int = 3) -> List[Dict[str, Any]]:
    """从日志中提取最常复发的空转模式
    
    空转模式定义：基于日志中的'event'和'decision'字段，识别重复出现导致失败的模式。
    这里简化：统计每个(unique event, decision)对的出现次数，取top_n个最频繁的。
    实际应用可能需要更复杂的模式识别。
    """
    if not logs:
        return []
    
    # 假设日志条目有'outcome'字段，表示成功或失败
    # 只考虑失败的条目作为空转模式
    failed_logs = [log for log in logs if log.get('outcome') == 'failure']
    
    # 计算每个(event, decision)对的频率
    pattern_counter = Counter()
    for log in failed_logs:
        event = log.get('event', 'unknown')
        decision = log.get('decision', 'unknown')
        pattern_key = (event, decision)
        pattern_counter[pattern_key] += 1
    
    # 取最频繁的top_n个模式
    most_common = pattern_counter.most_common(top_n)
    patterns = []
    for (event, decision), count in most_common:
        patterns.append({
            'event': event,
            'decision': decision,
            'count': count
        })
    
    return patterns

def generate_forbidden_cards(patterns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """根据提取的模式生成planner禁忌卡
    
    禁忌卡格式：包含禁止的event和decision组合，以及原因。
    """
    cards = []
    for i, pattern in enumerate(patterns):
        card = {
            'id': f"forbidden_card_{i}",
            'forbidden_event': pattern['event'],
            'forbidden_decision': pattern['decision'],
            'reason': f"历史空转模式：在事件'{pattern['event']}'下，决策'{pattern['decision']}'导致失败，复发{pattern['count']}次",
            'priority': 'high'
        }
        cards.append(card)
    return cards

def replay_and_verify(cards: List[Dict[str, Any]], logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """回放日志并验证禁忌卡是否能防止空转模式
    
    对于每条日志，检查是否违反禁忌卡，并统计结果。
    返回验证报告。
    """
    if not cards or not logs:
        return {'total': 0, 'violations': 0, 'verified': True}
    
    violations = 0
    total = len(logs)
    violation_details = []
    
    for i, log in enumerate(logs):
        event = log.get('event', 'unknown')
        decision = log.get('decision', 'unknown')
        
        # 检查是否违反任何禁忌卡
        for card in cards:
            if event == card['forbidden_event'] and decision == card['forbidden_decision']:
                violations += 1
                violation_details.append({
                    'log_index': i,
                    'event': event,
                    'decision': decision,
                    'card_id': card['id']
                })
                break  # 一旦违反一个卡片，就计为一次违规
    
    verified = violations == 0  # 如果无违规，则验证通过
    
    report = {
        'total': total,
        'violations': violations,
        'verified': verified,
        'violation_details': violation_details[:10]  # 只显示前10个细节
    }
    return report

def run_recurrence_gate():
    """运行整个复发反模式闸流程"""
    print("开始运行复发反模式闸...")
    
    # 1. 加载日志
    logs = load_navlogs()
    if not logs:
        print("无日志数据，退出")
        return
    
    # 2. 提取空转模式
    patterns = extract_idle_patterns(logs, top_n=3)
    if not patterns:
        print("未提取到空转模式")
        return
    
    print(f"提取到 {len(patterns)} 个空转模式:")
    for p in patterns:
        print(f"  事件: {p['event']}, 决策: {p['decision']}, 次数: {p['count']}")
    
    # 3. 生成禁忌卡
    cards = generate_forbidden_cards(patterns)
    print(f"生成 {len(cards)} 张禁忌卡:")
    for card in cards:
        print(f"  ID: {card['id']}, 禁止: 事件'{card['forbidden_event']}', 决策'{card['forbidden_decision']}'")
    
    # 4. 回放验证
    report = replay_and_verify(cards, logs)
    print(f"回放验证结果:")
    print(f"  总日志条目: {report['total']}")
    print(f"  违规次数: {report['violations']}")
    print(f"  验证通过: {report['verified']}")
    
    if report['violation_details']:
        print("  违规详情（前10个）:")
        for detail in report['violation_details']:
            print(f"    日志索引{detail['log_index']}: 事件'{detail['event']}', 决策'{detail['decision']}', 违反卡片{detail['card_id']}")
    
    return {
        'patterns': patterns,
        'cards': cards,
        'report': report
    }

if __name__ == "__main__":
    run_recurrence_gate()
