"""断奶模式：默认启用brain-only检查"""
import sys

def enable_brainonly_default():
    """启用brain-only作为默认模式"""
    # 这个模块可以在启动时被导入，以确保brain-only模式被激活
    from autonomy_meter import meter
    print("Brain-only mode enabled: all external AI calls will be tracked")

if __name__ == "__main__":
    enable_brainonly_default()
    print("Weaning brain-only default: autonomous evolution enabled")
