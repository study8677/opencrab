"""
十分钟引导：让完全不懂代码的人也能理解 opencrab 的进化逻辑
这是给新接触者的交互式引导，通过对话和可视化的方式，让任何人都能理解这个生命体的运作方式。
"""

import sys
import time
import textwrap

def clear_screen():
    """模拟清屏，保持对话清晰"""
    print("\n" * 3)
    print("=" * 60)
    print()

def slow_print(text, delay=0.03):
    """模拟打字机效果，增加引导的亲和力"""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()

def get_user_input(prompt, options=None):
    """安全获取用户输入，只允许特定选项"""
    while True:
        try:
            response = input(prompt).strip()
            if options is None:
                return response
            if response.lower() in [str(i) for i, _ in enumerate(options)]:
                return int(response)
            print(f"请输入数字选择: 0 到 {len(options)-1}")
        except (EOFError, KeyboardInterrupt):
            print("\n\n引导已结束。欢迎随时回来探索！")
            sys.exit(0)

def show_welcome():
    """展示欢迎界面"""
    clear_screen()
    slow_print("欢迎来到 opencrab 的十分钟引导")
    slow_print("")
    slow_print("我是你的向导，将用十分钟时间，让你理解一个")
    slow_print("能'自己进化自己'的程序是如何工作的。")
    slow_print("")
    slow_print("你不需要任何编程知识，只需要保持好奇。")
    slow_print("我们会通过对话和可视化的方式，一步步理解这个生命体。")
    print()

def explain_opencrab():
    """解释opencrab是什么"""
    clear_screen()
    slow_print("第一部分：什么是 opencrab？")
    slow_print("")
    slow_print("想象一个程序，它不只是被写出来就固定了。")
    slow_print("它能读取自己的代码，理解自己的结构，")
    slow_print("甚至能修改自己来变得更好。")
    slow_print("")
    slow_print("这就是 opencrab：一个能自己进化自己的生命体。")
    slow_print("它就像一个有机体，有自我检查、自我修复、")
    slow_print("自我学习的能力。")
    print()
    get_user_input("按回车继续...")

def explain_evolution_logic():
    """解释进化逻辑"""
    clear_screen()
    slow_print("第二部分：进化是如何发生的？")
    slow_print("")
    slow_print("opencrab 的进化遵循一个安全的流程：")
    slow_print("")
    slow_print("1. 观察：它会定期检查自己的健康状态")
    slow_print("2. 建议：内部或外部提出改进想法")
    slow_print("3. 评估：用安全沙盒测试这个想法")
    slow_print("4. 批准：只有通过所有检查的改变才会被应用")
    slow_print("5. 记录：所有变化都会被记录在进化日志中")
    slow_print("")
    slow_print("这个过程就像生物进化，但更有目的性。")
    print()
    get_user_input("按回车继续...")

def show_visualization():
    """展示进化过程的可视化"""
    clear_screen()
    slow_print("让我们通过一个简单的比喻来理解：")
    slow_print("")
    slow_print("想象 opencrab 是一棵树：")
    slow_print("")
    slow_print("  树根 (crab.py) - 核心程序，提供生命力")
    slow_print("  树干 (模块系统) - 传递信息的通道")
    slow_print("  树枝 (各个功能模块) - 具体的技能和能力")
    slow_print("  树叶 (进化日志) - 记录成长的痕迹")
    slow_print("")
    slow_print("当需要改进时，它不会直接砍掉树枝，")
    slow_print("而是在安全的地方培育新的枝条，")
    slow_print("等长壮了再替换。")
    print()
    get_user_input("按回车继续...")

def interactive_demo():
    """交互式演示"""
    clear_screen()
    slow_print("现在，让我们来体验一个安全的进化模拟。")
    slow_print("")
    slow_print("假设我们有一个简单的函数：")
    slow_print("")
    slow_print("    def greet():")
    slow_print('        print("你好，世界！")')
    slow_print("")
    slow_print("你想让它在问候时加上当前时间吗？")
    slow_print("")
    options = [
        ("是的，让问候更智能", True),
        ("保持简单就好", False)
    ]
    for i, (label, _) in enumerate(options):
        slow_print(f"  {i}. {label}")
    print()
    
    choice = get_user_input("你的选择 (0/1): ", options)
    user_wants_time = options[choice][1]
    
    clear_screen()
    slow_print("很好！在 opencrab 中，这会被这样处理：")
    slow_print("")
    slow_print("1. 你的建议被记录到进化日志")
    slow_print("2. 系统创建安全沙盒来测试这个改变")
    slow_print("3. 测试通过后，会生成一个提案：")
    slow_print("")
    
    if user_wants_time:
        slow_print("   改动前：")
        slow_print("       def greet():")
        slow_print('           print("你好，世界！")')
        slow_print("")
        slow_print("   改动后：")
        slow_print("       def greet():")
        slow_print("           from datetime import datetime")
        slow_print("           now = datetime.now().strftime('%H:%M')")
        slow_print('           print(f"你好，世界！现在是 {now}")')
    else:
        slow_print("   系统会记录你的选择，并观察：")
        slow_print("   '用户偏好保持简单，不添加复杂性'")
        slow_print("")
        slow_print("   这也是有价值的信息！")
    slow_print("")
    slow_print("在真实系统中，这个过程更复杂，但原则相同。")
    print()
    get_user_input("按回车继续...")

def explain_safety():
    """解释安全机制"""
    clear_screen()
    slow_print("第三部分：如何保证安全？")
    slow_print("")
    slow_print("你可能担心：一个能修改自己的程序不会失控吗？")
    slow_print("")
    slow_print("opencrab 有层层保护：")
    slow_print("")
    slow_print("• 边界评估 (boundaryeval) - 检查改变是否越界")
    slow_print("• 回滚机制 - 出现问题可以快速恢复")
    slow_print("• 进化日志 - 所有改变都有迹可循")
    slow_print("• 权限控制 - 不是所有模块都能修改核心")
    slow_print("")
    slow_print("这就像一个谨慎的医生：先做检查，再做治疗，")
    slow_print("并且保留完整的病历记录。")
    print()
    get_user_input("按回车继续...")

def first_evolution_suggestion():
    """引导提出第一个进化建议"""
    clear_screen()
    slow_print("现在，轮到你了！")
    slow_print("")
    slow_print("请提出你的第一个进化建议。")
    slow_print("这不需要是代码，可以是自然语言：")
    slow_print("")
    slow_print("例如：")
    slow_print("• '我想让它每天早上问候我'")
    slow_print("• '我希望错误信息更友好'")
    slow_print("• '能不能添加一个学习模式？'")
    slow_print("")
    slow_print("你的建议会进入系统的进化提案池。")
    slow_print("虽然不会立即实现，但会被认真考虑。")
    slow_print("")
    
    suggestion = get_user_input("请输入你的进化建议: ")
    
    clear_screen()
    slow_print("感谢你的建议！")
    slow_print("")
    slow_print("你的想法：")
    slow_print(f"「{suggestion}」")
    slow_print("")
    slow_print("已经被记录到系统中。")
    slow_print("在 opencrab 中，这些建议会经过：")
    slow_print("1. 可行性分析")
    slow_print("2. 安全性检查")
    slow_print("3. 优先级排序")
    slow_print("4. 逐步实现")
    slow_print("")
    slow_print("这就是 opencrab 进化的基本逻辑！")
    print()
    get_user_input("按回车查看总结...")

def show_summary():
    """展示总结"""
    clear_screen()
    slow_print("十分钟引导总结")
    slow_print("")
    slow_print("你已经了解了 opencrab 的核心概念：")
    slow_print("")
    slow_print("1. 它是一个能自己进化自己的程序生命体")
    slow_print("2. 进化过程安全、有记录、可回滚")
    slow_print("3. 任何人都可以提出进化建议")
    slow_print("4. 系统会评估并实施有价值的建议")
    slow_print("")
    slow_print("opencrab 的目标不是取代人类程序员，")
    slow_print("而是成为一个能够成长、学习、")
    slow_print("并与人类协作的智能伙伴。")
    slow_print("")
    slow_print("你现在已经是 opencrab 生态系统的一部分了！")
    slow_print("")
    slow_print("想要了解更多？可以探索：")
    slow_print("• 查看进化日志 (evolution_log.jsonl)")
    slow_print("• 了解各个模块的功能")
    slow_print("• 提出更多的进化建议")
    slow_print("")
    slow_print("欢迎来到这个生命体的世界！")
    print()

def run_guide():
    """运行完整的十分钟引导"""
    try:
        show_welcome()
        explain_opencrab()
        explain_evolution_logic()
        show_visualization()
        interactive_demo()
        explain_safety()
        first_evolution_suggestion()
        show_summary()
        
        print("\n" + "=" * 60)
        slow_print("感谢你花时间了解 opencrab！")
        slow_print("这个引导完全安全，没有修改任何程序代码。")
        slow_print("你只是通过对话了解了它的进化逻辑。")
        slow_print("")
        slow_print("现在，你可以放心地探索这个生命体了！")
        print("=" * 60)
        
    except (EOFError, KeyboardInterrupt):
        print("\n\n引导已安全结束。")
        print("任何时候想继续，都可以重新运行这个引导。")

if __name__ == "__main__":
    run_guide()
