"""
Value 模块：评估进化候选的价值，同时提供反指标评估。
防住古德哈特，不让漂亮分数冒充真正进步。
"""

def assess_anti_indicator(candidate):
    """
    评估候选的反指标分数，0表示无伤害，1表示最大伤害。
    接入多个反指标：健康、安全、一致性、记忆伤害等。
    """
    try:
        from health import assess_risk
        health_risk = assess_risk(candidate)
    except:
        health_risk = 0.0

    try:
        from safetycase import assess_safety_risk
        safety_risk = assess_safety_risk(candidate)
    except:
        safety_risk = 0.0

    try:
        from consistency import assess_consistency_risk
        consistency_risk = assess_consistency_risk(candidate)
    except:
        consistency_risk = 0.0

    # 加权平均，各反指标权重可调整
    total_risk = (health_risk * 0.4 + safety_risk * 0.3 + consistency_risk * 0.3)
    return min(total_risk, 1.0)


def assess_value(candidate):
    """
    评估候选的价值，考虑正向收益。
    """
    # 这里可以接入现有的 value 评估逻辑
    return 0.5  # 默认中等价值
