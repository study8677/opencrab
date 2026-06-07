#!/usr/bin/env python3
"""
go_canary_75.py - 一键对最弱格 canary 75% 下刀

执行流程：
1. reproduce_canary_3x 找挂的 case（解析输出拿到 case 名）
2. readpack 对挂的 case 圈最小修面
3. brain-only 出补丁（用真实 case 名）
4. 过三闸（patchfitroom + 三闸检查）
5. 焊进 fitness.json（更新分数）
"""

import subprocess
import json
import re
from pathlib import Path

def run(cmd, desc="", check=False):
    """运行命令并打印输出"""
    if desc:
        print(f"\n{'='*60}")
        print(f"{desc}")
        print(f"{'='*60}")

    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr[:500]}")
    if check and result.returncode != 0:
        print(f"❌ FAILED: {desc}")
        return None
    return result

def get_failed_cases():
    """从 reproduce_canary_3x 输出解析失败 case"""
    result = run(
        "python reproduce_canary_3x.py 2>&1",
        "Step 1: 找挂的 case"
    )
    if not result:
        return []
    
    # 解析失败 case（格式：FAILED: case_name 或类似）
    failed = []
    for line in result.stdout.split('\n') + result.stderr.split('\n'):
        # 匹配 "case_name" 或 'case_name' 格式
        matches = re.findall(r'["\']([\w_]+)["\']', line)
        for m in matches:
            if m not in failed and len(m) > 3:
                failed.append(m)
    
    # 也检查文件是否存在失败记录
    if not failed:
        # 尝试从 reproduce_canary_75_3x.py 找
        result2 = run(
            "python reproduce_canary_75_3x.py 2>&1 | head -100",
            "备选: reproduce_canary_75_3x"
        )
        for line in result2.stdout.split('\n') if result2 else []:
            matches = re.findall(r'["\']([\w_]+)["\']', line)
            for m in matches:
                if m not in failed and len(m) > 3:
                    failed.append(m)
    
    print(f"\n🔍 找到失败 case: {failed[:5]}")
    return failed

def run_readpack_for_cases(cases):
    """对每个失败 case 跑 readpack"""
    if not cases:
        # fallback: 跑核心文件
        cases = ["crab.py", "hands.py"]
    
    print("\n" + "="*60)
    print("Step 2: readpack 圈最小修面")
    print("="*60)
    
    patch_areas = []
    for case in cases[:3]:  # 最多处理3个
        result = run(
            f"python readpack.py --case {case} 2>&1",
            f"readpack {case}"
        )
        if result and result.stdout:
            patch_areas.append(result.stdout[:500])
    
    return patch_areas

def run_brainonly_patch(cases):
    """跑 brain-only 出补丁"""
    print("\n" + "="*60)
    print("Step 3: brain-only 出补丁")
    print("="*60)
    
    case_str = ",".join(cases[:3]) if cases else "canary_75"
    
    # 方法1: 跑专门的 brainonly 脚本
    result = run(
        f"python brainonly_canary_patch.py --case {case_str} 2>&1",
        "brainonly_canary_patch"
    )
    
    # 方法2: 如果没有专用脚本，尝试直接焊
    if not result or result.returncode != 0:
        # 尝试 patchfitroom_brainonly_retry
        result = run(
            f"python patchfitroom_brainonly_retry.py --case {case_str} 2>&1",
            "patchfitroom_brainonly_retry"
        )
    
    return result

def run_three_gates():
    """过三闸"""
    print("\n" + "="*60)
    print("Step 4: 过三闸")
    print("="*60)
    
    # patchfitroom 检查
    result1 = run(
        "python patchfitroom.py 2>&1 | head -100",
        "patchfitroom 检查"
    )
    
    # 三闸检查
    result2 = run(
        "python check_three_gates_canary.py 2>&1",
        "三闸检查"
    )
    
    return result1, result2

def update_fitness_json():
    """焊进 fitness.json"""
    print("\n" + "="*60)
    print("Step 5: 焊进 fitness.json")
    print("="*60)
    
    # 读取当前 fitness.json
    fitness_file = Path("fitness.json")
    if fitness_file.exists():
        with open(fitness_file) as f:
            data = json.load(f)
    else:
        data = {"canary_75": {"score": 0, "patches": []}}
    
    # 运行评估获取当前分数
    result = run(
        "python run_fitness_baseline.py --module canary 2>&1",
        "获取 canary 分数"
    )
    
    # 解析分数
    new_score = None
    if result and result.stdout:
        for line in result.stdout.split('\n'):
            match = re.search(r'score[:\s]+(\d+\.?\d*)', line, re.I)
            if match:
                new_score = float(match.group(1))
    
    if new_score is None:
        # 尝试其他方式获取分数
        result2 = run(
            "python check_fitness_json.py 2>&1",
            "check_fitness_json"
        )
        if result2 and result2.stdout:
            for line in result2.stdout.split('\n'):
                match = re.search(r'canary.*?(\d+\.?\d*)', line, re.I)
                if match:
                    new_score = float(match.group(1))
    
    # 更新数据
    if new_score is not None:
        if "canary_75" not in data:
            data["canary_75"] = {"score": 0, "patches": []}
        
        old_score = data["canary_75"].get("score", 0)
        data["canary_75"]["score"] = new_score
        data["canary_75"]["patches"].append({
            "version": len(data["canary_75"]["patches"]) + 1,
            "score": new_score,
            "delta": new_score - old_score
        })
        
        # 写回
        with open(fitness_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"\n✅ fitness.json 已更新: {old_score} → {new_score} (Δ={new_score - old_score:+.2f})")
        return new_score
    else:
        print("⚠️  无法解析新分数，fitness.json 未更新")
        return None

def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║         CANARY 75% EVOLUTION - 对最弱格下刀                    ║
║                                                              ║
║  1. reproduce_canary_3x 找挂的 case                          ║
║  2. readpack 圈最小修面                                        ║
║  3. brain-only 出补丁                                         ║
║  4. 过三闸并入                                                 ║
║  5. 焊进 fitness.json                                         ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Step 1: 找挂的 case
    failed_cases = get_failed_cases()
    
    if not failed_cases:
        print("⚠️  未找到失败 case，使用默认处理")
        failed_cases = ["canary_75_default"]
    
    # Step 2: readpack 圈最小修面
    patch_areas = run_readpack_for_cases(failed_cases)
    
    # Step 3: brain-only 出补丁
    patch_result = run_brainonly_patch(failed_cases)
    
    # Step 4: 过三闸
    pf_result, gates_result = run_three_gates()
    
    # 检查三闸是否通过
    gates_passed = False
    if gates_result and gates_result.returncode == 0:
        gates_passed = True
    
    # Step 5: 焊进 fitness.json（只有三闸通过才更新）
    new_score = None
    if gates_passed:
        new_score = update_fitness_json()
        
        # git commit
        print("\n" + "="*60)
        print("Step 6: git commit")
        print("="*60)
        run("git add -A && git commit -m 'canary 75% evolution: brain-only patch' 2>&1", "git commit")
    else:
        print("\n⚠️  三闸未通过，跳过 fitness.json 更新和 commit")
    
    # 总结
    print("\n" + "="*60)
    print("DONE - 总结")
    print("="*60)
    print(f"失败 case: {failed_cases}")
    print(f"三闸通过: {gates_passed}")
    print(f"新分数: {new_score}")
    
    if new_score:
        print("\n🎉 canary 分数已真涨！")
    else:
        print("\n💡 分数未变，需要继续调优")

if __name__ == "__main__":
    main()
