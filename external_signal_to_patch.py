"""
外部信号→价值评估→补丁生成→验证落地 闭环演示
从具体观察（如橱窗数字老旧）出发，走通进化管线的实际一环
"""
import intake
import value
import patchfitroom
import json
from datetime import datetime


def run_external_signal_loop(observation: str, context: dict = None):
    """
    运行一次完整的外部信号→补丁闭环
    
    Args:
        observation: 外部观察文本（如"橱窗数字版本显示v2.3，但实际已到v3.1"）
        context: 补充上下文信息（如发生位置、频率等）
    
    Returns:
        dict: 包含闭环各阶段结果的字典
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "observation": observation,
        "context": context or {},
        "stages": {}
    }
    
    # 阶段1: intake - 信号摄入与结构化
    print(f"[intake] 处理外部信号: {observation}")
    try:
        intake_result = intake.process_signal(observation, context)
        result["stages"]["intake"] = intake_result
        print(f"[intake] 结构化结果: {intake_result.get('structured', '无结构')}")
    except Exception as e:
        result["stages"]["intake"] = {"error": str(e)}
        print(f"[intake] 错误: {e}")
        return result
    
    # 阶段2: value - 价值评估
    signal_id = intake_result.get("signal_id", "unknown")
    print(f"[value] 评估信号价值: {signal_id}")
    try:
        value_result = value.evaluate_signal(intake_result)
        result["stages"]["value"] = value_result
        print(f"[value] 价值评分: {value_result.get('score', 0)}")
        
        if value_result.get("action") != "patch":
            print(f"[value] 价值不足，不进入补丁流程")
            return result
    except Exception as e:
        result["stages"]["value"] = {"error": str(e)}
        print(f"[value] 错误: {e}")
        return result
    
    # 阶段3: patchfitroom - 补丁生成与验证
    print(f"[patchfitroom] 开始补丁流程")
    try:
        patch_result = patchfitroom.generate_and_verify_patch(
            intake_result, 
            value_result
        )
        result["stages"]["patchfitroom"] = patch_result
        
        if patch_result.get("verification_passed"):
            print(f"[patchfitroom] ✅ 补丁验证通过，准备应用")
            result["status"] = "ready_to_apply"
        else:
            print(f"[patchfitroom] ❌ 补丁验证失败: {patch_result.get('failure_reason')}")
            result["status"] = "verification_failed"
    except Exception as e:
        result["stages"]["patchfitroom"] = {"error": str(e)}
        print(f"[patchfitroom] 错误: {e}")
        result["status"] = "error"
    
    return result


def demo_with_window_case():
    """使用橱窗案例进行演示"""
    print("=" * 60)
    print("开始外部信号闭环演示")
    print("=" * 60)
    
    # 示例1: 橱窗数字老旧
    observation1 = "用户反馈：文档首页显示版本号v2.3.1，但实际最新版本已是v3.0.0，存在误导"
    context1 = {
        "location": "文档首页",
        "frequency": "多次报告",
        "urgency": "medium",
        "impact_scope": "新用户引导"
    }
    
    result1 = run_external_signal_loop(observation1, context1)
    print("\n" + "-" * 40)
    print("最终结果:")
    print(json.dumps(result1, indent=2, ensure_ascii=False))
    
    # 示例2: 错误提示不友好
    observation2 = "API错误返回'发生错误'，没有具体错误码，用户无法自助排查"
    context2 = {
        "location": "API错误响应",
        "frequency": "日常发生",
        "urgency": "high",
        "impact_scope": "所有API用户"
    }
    
    result2 = run_external_signal_loop(observation2, context2)
    print("\n" + "-" * 40)
    print("最终结果:")
    print(json.dumps(result2, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    demo_with_window_case()
