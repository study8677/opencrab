"""验证 form_intent 能正确读取 state/projects/ 并对进行中项目返回 continue"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from planner import form_intent
from crab import read_state
import tempfile
import shutil

def verify():
    # 模拟 canary 焊链进行中项目
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建临时 state/projects/
        proj_dir = os.path.join(tmpdir, 'projects')
        os.makedirs(proj_dir)
        
        # 写入一个进行中的 canary 焊链项目
        project_file = os.path.join(proj_dir, 'canary_weld_chain.md')
        with open(project_file, 'w') as f:
            f.write("""# canary_weld_chain

## 元信息
- 项目名: canary_weld_chain
- 状态: 进行中
- 开始时间: 2024-01-01
- 最后心跳: 2024-06-05
- 优先级: p1

## 当前进度
- 阶段: 焊链第3轮
- 进度: 进行中
- 待修复: canary_80_weld_rootcause

## 心跳记录
| 时间 | 动作 | 状态 |
|------|------|------|
| 2024-06-01 | 开始焊链 | 进行中 |
| 2024-06-05 | 继续焊链 | 进行中 |

## 意图历史
- 2024-06-01: 启动 canary 焊链
- 2024-06-05: 继续深耕，不换山头
""")

        # 用 monkeypatch 方式让 read_state 能读到临时目录
        original_read_state = read_state
        
        def mock_read_state(*args, **kwargs):
            # 临时切换到测试目录
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                return original_read_state(*args, **kwargs)
            finally:
                os.chdir(old_cwd)
        
        import crab
        old_func = crab.read_state
        crab.read_state = mock_read_state
        
        try:
            # 调用 form_intent，传入 canary_weld_chain 项目
            intent = form_intent('canary_weld_chain')
            
            print(f"form_intent 返回: {intent}")
            
            # 验证返回的是 continue
            if intent.get('strategy') == 'continue':
                print("✅ 验证通过: 对进行中项目返回 continue 策略")
                return True
            else:
                print(f"❌ 验证失败: 期望 strategy='continue'，得到 {intent}")
                return False
        finally:
            crab.read_state = old_func

if __name__ == '__main__':
    success = verify()
    sys.exit(0 if success else 1)
