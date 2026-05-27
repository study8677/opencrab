"""
新手十分钟断点实测：空环境跑 onboarding→userlab→smoke，记录首个卡点并最小修复
"""
import sys
import traceback
import time
from pathlib import Path

# 确保当前目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent))

def record_bottleneck(step: str, error: Exception):
    """记录首个卡点到文件"""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_file = Path("tenminute_drill.log")
    
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"时间: {timestamp}\n")
        f.write(f"卡点步骤: {step}\n")
        f.write(f"错误类型: {type(error).__name__}\n")
        f.write(f"错误信息: {str(error)}\n")
        f.write(f"详细堆栈:\n{traceback.format_exc()}\n")
    
    print(f"❌ 卡点已记录到 {log_file}")
    print(f"   步骤: {step}")
    print(f"   错误: {type(error).__name__}: {error}")

def main():
    """主执行流程"""
    steps = [
        ("onboarding", "启动 onboarding"),
        ("userlab", "进入 userlab"),
        ("smoke", "执行 smoke 测试")
    ]
    
    print("🚀 开始新手十分钟断点实测")
    print("=" * 40)
    
    for module_name, description in steps:
        print(f"\n▶ {description}...")
        
        try:
            # 动态导入模块
            import importlib
            module = importlib.import_module(module_name)
            
            # 尝试调用主函数
            if hasattr(module, "main"):
                module.main()
            elif hasattr(module, "run"):
                module.run()
            elif hasattr(module, "execute"):
                module.execute()
            else:
                # 如果没有明显主函数，尝试直接导入（可能有副作用）
                print(f"  ℹ {module_name} 模块已导入，无主函数")
            
            print(f"  ✅ {description} 完成")
            
        except Exception as e:
            record_bottleneck(module_name, e)
            print(f"\n💡 最小修复建议:")
            
            # 根据错误类型提供修复提示
            if "No module named" in str(e):
                print(f"   1. 检查依赖: pip install {module_name}")
                print(f"   2. 检查模块路径是否正确")
            elif "FileNotFoundError" in str(e):
                print(f"   1. 确保所需文件存在")
                print(f"   2. 检查工作目录")
            elif "config" in str(e).lower() or "配置" in str(e):
                print(f"   1. 创建默认配置文件: {module_name}_config.yaml")
                print(f"   2. 或设置环境变量")
            
            return 1
    
    print("\n" + "=" * 40)
    print("🎉 新手十分钟断点实测全部通过！")
    return 0

if __name__ == "__main__":
    sys.exit(main())
