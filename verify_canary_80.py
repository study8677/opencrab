#!/usr/bin/env python3
"""
三闸验证: canary_75 → 80 补丁
闸1: 语法正确
闸2: 导入无错
闸3: fitness.json已更新
"""
import json
import subprocess
import sys
from pathlib import Path

def log(msg):
    print(f"[verify] {msg}")

def gate1_syntax():
    """闸1: 语法检查"""
    log("闸1: 语法检查")
    
    files = [
        "canary_75.py",
        "canary_75_evolution.py",
        "brainonly_canary_patch.py",
    ]
    
    all_ok = True
    for f in files:
        p = Path(f)
        if p.exists():
            result = subprocess.run(
                ["python", "-m", "py_compile", str(p)],
                capture_output=True
            )
            if result.returncode == 0:
                log(f"  ✅ {f}")
            else:
                log(f"  ❌ {f}: {result.stderr.decode()[:100]}")
                all_ok = False
        else:
            log(f"  ⏭️ {f} 不存在, 跳过")
    
    return all_ok

def gate2_import():
    """闸2: 导入测试"""
    log("闸2: 导入测试")
    
    try:
        import canary_75
        log("  ✅ canary_75 导入成功")
        
        # 测试功能
        score = canary_75.score_canary("canary thread lock timeout")
        log(f"  ✅ score_canary('canary thread lock timeout') = {score}")
        
        return True
    except Exception as e:
        log(f"  ❌ 导入失败: {e}")
        return False

def gate3_fitness():
    """闸3: fitness验证"""
    log("闸3: fitness验证")
    
    p = Path("fitness.json")
    if not p.exists():
        log("  ❌ fitness.json 不存在")
        return False
    
    data = json.loads(p.read_text())
    
    # 找canary_75相关key
    found = False
    for k, v in data.items():
        if 'canary_75' in k.lower():
            log(f"  {k} = {v}")
            if isinstance(v, (int, float)) and v >= 80:
                found = True
    
    if found:
        log("  ✅ canary_75 >= 80")
        return True
    else:
        log("  ❌ canary_75 未达到80")
        return False

def main():
    log("=" * 50)
    log("三闸验证: canary_75 → 80")
    log("=" * 50)
    
    results = []
    
    results.append(("语法", gate1_syntax()))
    results.append(("导入", gate2_import()))
    results.append(("fitness", gate3_fitness()))
    
    log("\n" + "=" * 50)
    log("验证结果:")
    all_pass = True
    for name, ok in results:
        status = "✅" if ok else "❌"
        log(f"  {status} {name}")
        if not ok:
            all_pass = False
    
    log("=" * 50)
    
    if all_pass:
        log("🎉 全部三闸通过!")
        return 0
    else:
        log("⚠️ 有闸未通过")
        return 1

if __name__ == "__main__":
    sys.exit(main())
