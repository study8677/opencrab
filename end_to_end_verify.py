"""端到端验证橱窗刷新链条：检查 showcase_refresher 生成的数字是否与真实状态一致。"""
import glob
import json
import subprocess
import sys
from pathlib import Path

def get_real_counts():
    """获取真实的模块数、提交数、技能图谱数。"""
    root = Path(__file__).parent
    
    # 模块数（与 showcase_refresher 相同的统计方式）
    modules = len(list(root.glob("*.py")))
    
    # 提交数
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, cwd=root
        )
        commits = int(result.stdout.strip())
    except:
        commits = 0
    
    # 技能图谱数（尝试从 skillgraph 模块获取，否则从 showcase_data.json 读取历史）
    try:
        from skillgraph import SkillGraph
        sg = SkillGraph()
        skills = len(sg.entries) if hasattr(sg, 'entries') else 0
    except:
        # 降级：读取最近的 showcase_data.json
        try:
            with open("docs/showcase_data.json", "r") as f:
                data = json.load(f)
                skills = data.get("skillgraph_entries", 0)
        except:
            skills = 0
    
    return {"modules": modules, "commits": commits, "skillgraph_entries": skills}

def verify():
    """运行验证检查。"""
    print("=== 端到端验证开始 ===")
    
    # 1. 运行 showcase_refresher
    print("运行 showcase_refresher.py ...")
    result = subprocess.run(
        [sys.executable, "showcase_refresher.py", "--run", "--check-freshness"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("❌ showcase_refresher 运行失败:")
        print(result.stderr)
        return False
    
    # 2. 读取 showcase_refresher 生成的数字
    try:
        with open("docs/showcase_data.json", "r") as f:
            showcase_data = json.load(f)
    except Exception as e:
        print(f"❌ 无法读取 showcase_data.json: {e}")
        return False
    
    # 3. 获取真实状态
    real_counts = get_real_counts()
    
    # 4. 比对
    print("\n比对结果:")
    mismatches = []
    for key in ["modules", "commits", "skillgraph_entries"]:
        showcase_val = showcase_data.get(key, "缺失")
        real_val = real_counts.get(key, "无法获取")
        match = "✅" if showcase_val == real_val else "❌"
        print(f"  {key}: 展示={showcase_val}, 真实={real_val} {match}")
        if showcase_val != real_val:
            mismatches.append(key)
    
    if mismatches:
        print(f"\n❌ 数字不一致的项: {mismatches}")
        print("需要修复 showcase_refresher.py 或数据源")
        return False
    else:
        print("\n✅ 所有数字一致")
        
        # 5. 运行 docs_updater 更新页面
        print("\n运行 docs_updater.py 更新页面...")
        result = subprocess.run(
            [sys.executable, "docs_updater.py"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print("❌ docs_updater 运行失败:")
            print(result.stderr)
            return False
        
        # 6. 检查 docs/index.html 是否存在
        if Path("docs/index.html").exists():
            print("✅ docs/index.html 已更新")
        else:
            print("⚠️  docs/index.html 未找到（可能未生成）")
        
        print("\n=== 端到端验证完成 ===")
        return True

if __name__ == "__main__":
    success = verify()
    sys.exit(0 if success else 1)
