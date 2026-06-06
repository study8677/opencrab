#!/usr/bin/env python3
"""
do_canary_75_final.py - 焊死 canary 75% 真缺陷

流程：
1. astlocator 找 canary.py 真缺陷
2. brain-only 产受限补丁
3. 3x 闸验
4. git commit
5. 重跑看分数真涨
"""
import subprocess
import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def run_cmd(cmd, capture=True):
    """运行命令"""
    print(f"[CMD] {cmd}")
    if capture:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    else:
        returncode = subprocess.run(cmd, shell=True).returncode
        return returncode == 0, "", ""

def step1_astlocator_find_defect():
    """Step 1: astlocator 找 canary.py 真缺陷"""
    print("\n=== Step 1: astlocator 找真缺陷 ===")
    
    # 写一个临时脚本来分析 canary.py
    probe_script = REPO_ROOT / "temp_astlocate_canary.py"
    probe_code = '''
import sys
sys.path.insert(0, str(Path(__file__).parent))
from astlocator import ASTLocator

locator = ASTLocator()
defects = locator.locate_defects_in_file("canary.py")
for d in defects:
    print(f"DEFECT: {d['type']} at line {d.get('line', '?')}: {d.get('detail', '')}")
'''
    probe_script.write_text(probe_code)
    
    ok, out, err = run_cmd(f"python {probe_script}")
    print(f"astlocator 输出: {out}")
    if err:
        print(f"astlocator 错误: {err}")
    
    # 手动分析 canary.py 的真缺陷
    canary_src = (REPO_ROOT / "canary.py").read_text()
    
    defects_found = []
    
    # 缺陷1: _check_recent_activity 总是返回 True
    if "len(list(evidence_dir.iterdir())) >= 0" in canary_src:
        defects_found.append({
            "type": "always_true",
            "line": "near 'len(list(evidence_dir.iterdir())) >= 0'",
            "detail": "_check_recent_activity 逻辑错误: >=0 永远为真"
        })
    
    # 缺陷2: health_score 检查太宽松
    if '"pass_rate" in data or "score" in data' in canary_src:
        defects_found.append({
            "type": "weak_validation",
            "line": "_check_health_score",
            "detail": "只检查 key 存在，不验证数值有效性"
        })
    
    print(f"\n找到 {len(defects_found)} 个真缺陷:")
    for d in defects_found:
        print(f"  - {d['type']}: {d['detail']}")
    
    return defects_found

def step2_brainonly_patch(defects):
    """Step 2: brain-only 产受限补丁"""
    print("\n=== Step 2: brain-only 产补丁 ===")
    
    canary_path = REPO_ROOT / "canary.py"
    src = canary_path.read_text()
    
    # 生成补丁
    patches_applied = []
    
    # 补丁1: 修复 always_true
    if "len(list(evidence_dir.iterdir())) >= 0" in src:
        old = 'return len(list(evidence_dir.iterdir())) >= 0  # 总是返回 True'
        new = 'entries = list(evidence_dir.iterdir())\n        return len(entries) > 0  # 至少有一个记录才认为有活动'
        
        if old in src:
            src = src.replace(old, new)
            patches_applied.append("fix: always_true -> count > 0")
    
    # 补丁2: 增强 health_score 检查
    old_health = '''def _check_health_score(self) -> bool:
        """检查健康分数"""
        fp = REPO_ROOT / "fitness.json"
        if not fp.exists():
            return False
        try:
            with open(fp) as f:
                data = json.load(f)
            # 基本检查
            return "pass_rate" in data or "score" in data
        except Exception:
            return False'''
    
    new_health = '''def _check_health_score(self) -> bool:
        """检查健康分数"""
        fp = REPO_ROOT / "fitness.json"
        if not fp.exists():
            return False
        try:
            with open(fp) as f:
                data = json.load(f)
            # 增强检查：必须同时有 key 和有效数值
            score = data.get("pass_rate") or data.get("score")
            if score is None:
                return False
            # 有效分数范围 [0, 100]
            return isinstance(score, (int, float)) and 0 <= score <= 100
        except Exception:
            return False'''
    
    if old_health in src:
        src = src.replace(old_health, new_health)
        patches_applied.append("fix: weak health_score -> numeric validation")
    
    # 写回
    canary_path.write_text(src)
    
    print(f"应用了 {len(patches_applied)} 个补丁:")
    for p in patches_applied:
        print(f"  ✓ {p}")
    
    return patches_applied

def step3_three_gates():
    """Step 3: 3x 闸验"""
    print("\n=== Step 3: 3x 闸验 ===")
    
    results = []
    
    for i in range(1, 4):
        print(f"\n--- 闸验 {i}/3 ---")
        ok, out, err = run_cmd("python -c 'import crab; print(\"crab import OK\")'")
        if ok:
            print(f"  ✓ crab 导入成功")
        else:
            print(f"  ✗ crab 导入失败: {err}")
            results.append(False)
            continue
        
        # 运行 canary 检查
        ok, out, err = run_cmd("python canary.py")
        print(f"  canary 输出: {out.strip()}")
        results.append(ok)
    
    all_passed = all(results) if results else False
    print(f"\n闸验结果: {'全部通过' if all_passed else '有失败'}")
    return all_passed

def step4_git_commit(patches):
    """Step 4: git commit"""
    print("\n=== Step 4: git commit ===")
    
    # 添加修改
    ok, _, _ = run_cmd("git add canary.py")
    if not ok:
        print("  git add 失败")
        return False
    
    # 检查状态
    ok, out, _ = run_cmd("git status --short")
    print(f"git status: {out}")
    
    # commit
    msg = f"fix(canary): 修复 {len(patches)} 个真缺陷\n\n- " + "\n- ".join(patches)
    ok, out, err = run_cmd(f'git commit -m "{msg}"')
    
    if ok:
        print(f"  ✓ git commit 成功")
        print(f"  commit message: {msg}")
    else:
        print(f"  ✗ git commit 失败: {err}")
    
    return ok

def step5_rerun_check_fitness():
    """Step 5: 重跑检查分数"""
    print("\n=== Step 5: 重跑检查 fitness ===")
    
    # 读取当前 fitness.json
    fp = REPO_ROOT / "fitness.json"
    if fp.exists():
        with open(fp) as f:
            data = json.load(f)
        score = data.get("score") or data.get("pass_rate", "N/A")
        print(f"当前分数: {score}")
    else:
        print("fitness.json 不存在，先跑一次")
        ok, _, _ = run_cmd("python -c 'from crab import Crab; c = Crab(); print(c.status())'")
        if fp.exists():
            with open(fp) as f:
                data = json.load(f)
            score = data.get("score") or data.get("pass_rate", "N/A")
            print(f"跑完后分数: {score}")
    
    # 运行 canary 看状态
    ok, out, err = run_cmd("python canary.py")
    print(f"\ncanary 最终检查:")
    print(out)
    
    return ok

def main():
    print("=" * 60)
    print("CANARY 75% 焊死流程")
    print("=" * 60)
    
    # Step 1: 找缺陷
    defects = step1_astlocator_find_defect()
    if not defects:
        print("未找到真缺陷，退出")
        return 1
    
    # Step 2: 产补丁
    patches = step2_brainonly_patch(defects)
    
    # Step 3: 闸验
    gates_passed = step3_three_gates()
    if not gates_passed:
        print("闸验失败，回退")
        run_cmd("git checkout canary.py")
        return 1
    
    # Step 4: git commit
    committed = step4_git_commit(patches)
    
    # Step 5: 重跑
    step5_rerun_check_fitness()
    
    print("\n" + "=" * 60)
    print("CANARY 75% 焊死完成!")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
