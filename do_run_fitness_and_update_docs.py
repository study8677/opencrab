"""真跑 run_fitness_baseline.py + 刷 docs/index.html 的真实状态"""
import json
import os
import subprocess
import sys
import re
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent

def run_fitness_baseline():
    """真运行 run_fitness_baseline.py"""
    print("=" * 60)
    print("🚀 真跑 run_fitness_baseline.py")
    print("=" * 60)
    
    result = subprocess.run(
        [sys.executable, "run_fitness_baseline.py"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    return result.returncode

def get_real_module_count():
    """获取真实的 .py 模块数量"""
    py_files = list(REPO_ROOT.glob("*.py"))
    # 排除 __pycache__ 和测试文件
    py_files = [f for f in py_files if "__pycache__" not in str(f) and not f.name.startswith("test_")]
    return len(py_files)

def get_real_commit_count():
    """获取真实的 git commit 数"""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except:
        pass
    return None

def update_docs_index_html():
    """更新 docs/index.html 的真实数字"""
    docs_path = REPO_ROOT / "docs" / "index.html"
    if not docs_path.exists():
        print(f"⚠ docs/index.html 不存在，跳过")
        return False
    
    with open(docs_path, encoding="utf-8") as f:
        content = f.read()
    
    original = content
    
    # 获取真实数字
    module_count = get_real_module_count()
    commit_count = get_real_commit_count()
    
    print(f"\n📊 真实状态:")
    print(f"   模块数: {module_count}")
    print(f"   Commit 数: {commit_count}")
    
    # 更新模块数 - 找类似 "26 modules" 或 "220+ modules" 的模式
    # 模式1: "26 modules" -> "XXX modules"
    content = re.sub(
        r'(\d+[\+\]?)\s+(?:modules|modules)',
        f'{module_count} modules',
        content,
        flags=re.IGNORECASE
    )
    
    # 模式2: "modules: 26" -> "modules: XXX"
    content = re.sub(
        r'modules[:\s]+(\d+[\+\]?)',
        f'modules: {module_count}',
        content,
        flags=re.IGNORECASE
    )
    
    # 更新 commit 数
    if commit_count:
        content = re.sub(
            r'(\d+)\s+(?:commits|commits)',
            f'{commit_count} commits',
            content,
            flags=re.IGNORECASE
        )
        content = re.sub(
            r'commits[:\s]+(\d+)',
            f'commits: {commit_count}',
            content,
            flags=re.IGNORECASE
        )
    
    if content != original:
        with open(docs_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ docs/index.html 已更新")
        return True
    else:
        print(f"⚠ docs/index.html 没有变化（可能格式不同）")
        return False

def verify_fitness_json():
    """验证 fitness.json 已正确写入"""
    fitness_path = REPO_ROOT / "fitness.json"
    if not fitness_path.exists():
        print(f"❌ fitness.json 不存在！")
        return False
    
    with open(fitness_path) as f:
        fitness = json.load(f)
    
    print(f"\n📋 fitness.json 验证:")
    if "baseline" in fitness:
        b = fitness["baseline"]
        print(f"   pass_rate: {b.get('pass_rate', 'N/A')}")
        print(f"   canary_pass_rate: {b.get('canary_pass_rate', 'N/A')}")
        print(f"   total_tests: {b.get('total_tests', 'N/A')}")
    
    if "dimensions" in fitness:
        print(f"   四格真分:")
        for dim, d in fitness["dimensions"].items():
            print(f"     - {dim}: {d.get('passed',0)}/{d.get('total',0)}")
    
    return True

def main():
    print("=" * 60)
    print("🦀 真适应度 + 真橱窗 进化")
    print("=" * 60)
    
    # 1. 真跑基线
    rc = run_fitness_baseline()
    
    # 2. 验证 fitness.json
    if rc == 0:
        print("\n✅ run_fitness_baseline.py 执行成功")
        verify_fitness_json()
    else:
        print(f"\n⚠ run_fitness_baseline.py 返回 {rc}，但继续更新橱窗")
    
    # 3. 刷 docs/index.html
    update_docs_index_html()
    
    print("\n" + "=" * 60)
    print("🦀 进化完成！")
    print("=" * 60)

if __name__ == "__main__":
    main()
