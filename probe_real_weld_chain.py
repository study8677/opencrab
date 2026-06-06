"""
probe_real_weld_chain: 真正执行 canary_75_real_weld.py → reproduce_canary_3x.py 链路
拿真失败日志，不玩虚的
"""
import subprocess
import sys
import traceback
from pathlib import Path


def run_py_script(script_path: Path) -> dict:
    """运行一个 .py 脚本，返回结果"""
    print(f"\n{'='*60}")
    print(f"执行: {script_path}")
    print('='*60)
    
    result = {
        "path": str(script_path),
        "success": False,
        "stdout": "",
        "stderr": "",
        "returncode": -1
    }
    
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = proc.communicate(timeout=60)
        result["stdout"] = stdout
        result["stderr"] = stderr
        result["returncode"] = proc.returncode
        result["success"] = proc.returncode == 0
        
        print(f"返回码: {proc.returncode}")
        if stdout:
            print(f"STDOUT:\n{stdout}")
        if stderr:
            print(f"STDERR:\n{stderr}")
            
    except subprocess.TimeoutExpired:
        proc.kill()
        result["stderr"] = "TIMEOUT (60s)"
        print("❌ 超时 60 秒")
    except Exception as e:
        result["stderr"] = traceback.format_exc()
        print(f"❌ 异常: {e}")
        traceback.print_exc()
    
    return result


def main():
    print("=" * 60)
    print("探针: 真实执行 canary 焊链 25% 死亡点定位")
    print("=" * 60)
    
    # 确认两个目标文件存在
    weld_path = Path("canary_75_real_weld.py")
    repro_path = Path("reproduce_canary_3x.py")
    
    if not weld_path.exists():
        print(f"❌ 找不到 {weld_path}")
        return
    if not repro_path.exists():
        print(f"❌ 找不到 {repro_path}")
        return
    
    print(f"✅ 目标文件确认存在")
    
    # 1. 先跑 reproduce_canary_3x.py（假设 canary.py 存在）
    r1 = run_py_script(repro_path)
    
    # 2. 再跑 canary_75_real_weld.py
    r2 = run_py_script(weld_path)
    
    # 汇总
    print("\n" + "=" * 60)
    print("链路执行汇总")
    print("=" * 60)
    print(f"reproduce_canary_3x.py: {'✅ 成功' if r1['success'] else '❌ 失败'}")
    print(f"canary_75_real_weld.py: {'✅ 成功' if r2['success'] else '❌ 失败'}")
    
    if not r1['success']:
        print("\n⚠️  死点 #1: reproduce_canary_3x.py 失败")
        print(f"  错误: {r1['stderr'][:500]}")
        
    if not r2['success']:
        print("\n⚠️  死点 #2: canary_75_real_weld.py 失败")
        print(f"  错误: {r2['stderr'][:500]}")


if __name__ == "__main__":
    main()
