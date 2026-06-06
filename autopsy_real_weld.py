"""
尸检报告：canary_75_real_weld.py 4拍"开焊"焊枪没响的根因
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def audit_crab_methods():
    """1. 检查 crab.py 是否有关键方法"""
    print("=" * 60)
    print("【1】crab.py 方法审计")
    print("=" * 60)
    
    crab_path = REPO_ROOT / "crab.py"
    if not crab_path.exists():
        print("❌ crab.py 不存在！")
        return False
    
    source = crab_path.read_text()
    
    methods_needed = [
        "apply_patch",
        "snapshot", 
        "get_cell",
        "list_cells",
    ]
    
    all_found = True
    for method in methods_needed:
        found = f"def {method}" in source or f"async def {method}" in source
        status = "✅" if found else "❌"
        print(f"  {status} {method}: {'存在' if found else '不存在！'}")
        if not found:
            all_found = False
    
    # 额外检查：apply_patch 实现
    if "apply_patch" in source:
        idx = source.find("def apply_patch")
        snippet = source[idx:idx+300] if idx >= 0 else ""
        print(f"\n  apply_patch 实现片段:\n{snippet[:300]}")
    
    return all_found

def audit_fitness_json():
    """2. 检查 fitness.json 是否有被回写"""
    print("\n" + "=" * 60)
    print("【2】fitness.json 回写审计")
    print("=" * 60)
    
    fitness_path = REPO_ROOT / "fitness.json"
    if not fitness_path.exists():
        print("❌ fitness.json 不存在！")
        print("   → 这就是根因：write_fitness_json() 第一次就跑不了")
        return False
    
    try:
        with open(fitness_path) as f:
            data = json.load(f)
        print(f"✅ fitness.json 存在")
        print(f"   keys: {list(data.keys())}")
        print(f"   runs 条目数: {len(data.get('runs', []))}")
        print(f"   total_delta: {data.get('total_delta', 'N/A')}")
        print(f"   weld_count: {data.get('weld_count', 'N/A')}")
        
        if not data.get("runs"):
            print("   ⚠️ runs 为空——从未被回写过！")
            return False
        return True
    except Exception as e:
        print(f"❌ fitness.json 解析失败: {e}")
        return False

def audit_real_weld_bugs():
    """3. 检查 canary_75_real_weld.py 本身的 bug"""
    print("\n" + "=" * 60)
    print("【3】canary_75_real_weld.py 代码审计")
    print("=" * 60)
    
    rw_path = REPO_ROOT / "canary_75_real_weld.py"
    if not rw_path.exists():
        print("❌ canary_75_real_weld.py 不存在！")
        return False
    
    source = rw_path.read_text()
    bugs = []
    
    # Bug 1: weld_count 未定义就使用
    if "weld_count > 0" in source:
        # 检查前面有没有定义
        lines_before = source[:source.find("weld_count > 0")]
        if "weld_count" not in lines_before or "get(weld_count" in lines_before:
            # 确认是否在函数外定义
            main_section = source[source.find("def main"):] if "def main" in source else source
            weld_defs = [i for i in main_section.split('\n') if 'weld_count' in i and 'get(' not in i and '=' in i]
            if not weld_defs:
                bugs.append(("❌ 未定义变量: weld_count 在 main() 中使用前未定义", 
                           "weld_count = final_data.get('weld_count', 0)  # 需要提前从文件读"))
    
    # Bug 2: 3x 复现没调用 reproduce 验证
    if "run_reproduce_verification" in source:
        # 检查 main 里有没有调用
        main_start = source.find("def main")
        main_end = source.find("\ndef ", main_start + 1)
        main_body = source[main_start:main_end] if main_end > 0 else source[main_start:]
        if "run_reproduce_verification()" not in main_body:
            bugs.append(("⚠️ 缺失调用: run_reproduce_verification() 定义了但 main() 没调用",
                         "在 total_avg 计算后添加验证调用"))
    
    # Bug 3: crab.snapshot() 可能不存在
    if "crab.snapshot()" in source:
        idx = source.find("crab.snapshot()")
        snippet = source[max(0,idx-50):idx+50]
        bugs.append(("⚠️ 可能问题: trial_crab = crab.snapshot() - snapshot() 可能不存在",
                     "改用 crab.copy() 或在 crab.py 中实现 snapshot()"))
    
    if bugs:
        for desc, fix in bugs:
            print(f"  {desc}")
            print(f"     → 修复建议: {fix}\n")
        return False
    else:
        print("  ✅ 未发现明显 bug")
        return True

def audit_git_status():
    """4. 检查 git diff"""
    print("\n" + "=" * 60)
    print("【4】git status 审计")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10
        )
        print(f"git status 输出:\n{result.stdout}")
        if result.stderr:
            print(f"stderr: {result.stderr}")
    except FileNotFoundError:
        print("⚠️ git 未安装或不在 PATH 中")
    except Exception as e:
        print(f"⚠️ git 命令失败: {e}")

def audit_upstream_chain():
    """5. 审计上游模块"""
    print("\n" + "=" * 60)
    print("【5】上游模块审计")
    print("=" * 60)
    
    upstream = {
        "canary.py": "Canary 类健康检查",
        "reproduce_canary_3x.py": "3x 复现验证脚本",
    }
    
    for fname, desc in upstream.items():
        path = REPO_ROOT / fname
        if path.exists():
            print(f"  ✅ {fname}: {desc}")
        else:
            print(f"  ❌ {fname}: 不存在！{desc}")

def main():
    print("🔍 CANARY 75% REAL WELD 尸检报告")
    print("=" * 60)
    
    results = {
        "crab_methods": audit_crab_methods(),
        "fitness_json": audit_fitness_json(),
        "real_weld_code": audit_real_weld_bugs(),
    }
    
    audit_git_status()
    audit_upstream_chain()
    
    print("\n" + "=" * 60)
    print("【结论】")
    print("=" * 60)
    
    if not results["crab_methods"]:
        print("❌ 根因1: crab.py 缺少关键方法 (apply_patch/snapshot/get_cell)")
        print("   → 焊枪根本没打响，因为 crab 根本不支持这些操作")
    elif not results["real_weld_code"]:
        print("❌ 根因2: canary_75_real_weld.py 本身有 bug")
        print("   → weld_count 未定义、snapshot 可能不存在、reproduce 没调用")
    elif not results["fitness_json"]:
        print("❌ 根因3: fitness.json 没被回写")
        print("   → 可能是首次运行文件不存在，或 write_fitness_json 从未被执行")
    else:
        print("✅ 链条完整，可能是运行时逻辑问题（delta 为负/三闸不过）")

if __name__ == "__main__":
    main()
